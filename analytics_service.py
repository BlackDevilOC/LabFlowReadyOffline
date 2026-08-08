"""Analytics aggregation, caching, and snapshot management for LabFlow."""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from dbActions import init_supabase
from logdata import log_error, logger
from patient_list_query import normalize_date_range

CHUNK_SIZE = 1000
CACHE_TTL_SECONDS = 300  # 5 minutes for current-day ranges
HISTORICAL_CACHE_TTL_SECONDS = 3600  # 1 hour for closed date ranges

ANALYTICS_PDF_ARCHIVE_ROOTS = (
    r"D:\LabFlow_System_Logs",
    r"C:\LabFlow_System_Logs",
)

PATIENT_SELECT = "id,mr_no,patient_name,shift,user,user_id,created_at"
TEST_RESULT_SELECT = (
    "id,mr_no,patient_name,test_name,category,status,created_at,test_values,delete_status"
)


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None


def _date_key(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.date().isoformat()


def _hour_key(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return f"{dt.hour:02d}:00"


def _try_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in ("-", "—", "N/A", "n/a", "Pending", "pending"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def classify_parameter(param: dict) -> str | None:
    """Return 'normal', 'abnormal', or None when not classifiable."""
    val = _try_float(param.get("value"))
    if val is None:
        return None
    n_min = _try_float(param.get("normal_min"))
    n_max = _try_float(param.get("normal_max"))
    if n_min is None and n_max is None:
        return None
    if n_min is not None and val < n_min:
        return "abnormal"
    if n_max is not None and val > n_max:
        return "abnormal"
    return "normal"


def _sanitize_test_values(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("test_values"), dict):
        raw = raw["test_values"]
    return {
        k: v
        for k, v in raw.items()
        if k not in ("remarks", "test_values") and isinstance(v, dict)
    }


def _classify_test_row(row: dict) -> tuple[int, int, int]:
    """Returns (normal_count, abnormal_count, unclassified_count) for one test row."""
    tv = _sanitize_test_values(row.get("test_values"))
    normal = abnormal = unclassified = 0
    for param in tv.values():
        result = classify_parameter(param)
        if result == "normal":
            normal += 1
        elif result == "abnormal":
            abnormal += 1
        else:
            unclassified += 1
    return normal, abnormal, unclassified


def _fetch_paginated(query_builder, chunk_size: int = CHUNK_SIZE) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        resp = query_builder().range(offset, offset + chunk_size - 1).execute()
        batch = resp.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < chunk_size:
            break
        offset += chunk_size
    return rows


def fetch_patients_in_range(date_from: str | None, date_to: str | None) -> list[dict]:
    d_from, d_to = normalize_date_range(date_from, date_to)

    def build_query():
        q = init_supabase().table("patients").select(PATIENT_SELECT)
        if d_from:
            q = q.gte("created_at", f"{d_from}T00:00:00Z")
        if d_to:
            end_exclusive = datetime.strptime(d_to, "%Y-%m-%d") + timedelta(days=1)
            q = q.lt("created_at", end_exclusive.strftime("%Y-%m-%dT00:00:00Z"))
        return q.order("created_at", desc=False)

    try:
        return _fetch_paginated(build_query)
    except Exception as e:
        log_error(e, "ANALYTICS_FETCH_PATIENTS")
        return []


def fetch_test_results_in_range(date_from: str | None, date_to: str | None) -> list[dict]:
    d_from, d_to = normalize_date_range(date_from, date_to)

    def build_query():
        q = (
            init_supabase()
            .table("test_results_all")
            .select(TEST_RESULT_SELECT)
            .eq("delete_status", False)
        )
        if d_from:
            q = q.gte("created_at", f"{d_from}T00:00:00Z")
        if d_to:
            end_exclusive = datetime.strptime(d_to, "%Y-%m-%d") + timedelta(days=1)
            q = q.lt("created_at", end_exclusive.strftime("%Y-%m-%dT00:00:00Z"))
        return q.order("created_at", desc=False)

    try:
        return _fetch_paginated(build_query)
    except Exception as e:
        log_error(e, "ANALYTICS_FETCH_TEST_RESULTS")
        return []


def _empty_overview(date_from: str, date_to: str) -> dict[str, Any]:
    return {
        "date_from": date_from,
        "date_to": date_to,
        "kpis": {
            "total_patients": 0,
            "total_tests": 0,
            "completed_tests": 0,
            "pending_tests": 0,
            "completion_rate_pct": 0.0,
            "avg_tests_per_patient": 0.0,
            "unique_operators": 0,
        },
        "registration_series": [],
        "category_volume": [],
        "result_ratio": {"normal": 0, "abnormal": 0, "unclassified": 0},
        "has_data": False,
    }


def compute_overview(date_from: str | None, date_to: str | None) -> dict[str, Any]:
    d_from, d_to = normalize_date_range(date_from, date_to)
    if not d_from or not d_to:
        today = _utc_today().isoformat()
        d_from = d_from or today
        d_to = d_to or today

    patients = fetch_patients_in_range(d_from, d_to)
    tests = fetch_test_results_in_range(d_from, d_to)

    if not patients and not tests:
        return _empty_overview(d_from, d_to)

    reg_by_day: Counter[str] = Counter()
    reg_by_hour: Counter[str] = Counter()
    operators: set[str] = set()

    for p in patients:
        dt = _parse_iso_dt(p.get("created_at"))
        day = _date_key(dt)
        hour = _hour_key(dt)
        if day:
            reg_by_day[day] += 1
        if hour:
            reg_by_hour[hour] += 1
        op = (p.get("user") or "").strip() or "Unknown"
        operators.add(op)

    category_counts: Counter[str] = Counter()
    completed = pending = 0
    normal_total = abnormal_total = unclassified_total = 0
    patients_with_tests: set[int | str] = set()

    for row in tests:
        category = (row.get("category") or "Uncategorized").strip()
        category_counts[category] += 1
        status = (row.get("status") or "").strip().lower()
        if status in ("completed", "synced", "done"):
            completed += 1
        else:
            pending += 1
        mr = row.get("mr_no")
        if mr is not None:
            patients_with_tests.add(mr)
        n, a, u = _classify_test_row(row)
        normal_total += n
        abnormal_total += a
        unclassified_total += u

    total_patients = len(patients) if patients else len(patients_with_tests)
    total_tests = len(tests)
    completion_rate = round((completed / total_tests) * 100, 1) if total_tests else 0.0
    avg_tests = round(total_tests / total_patients, 2) if total_patients else 0.0

    registration_series = [
        {"date": day, "count": reg_by_day[day]}
        for day in sorted(reg_by_day.keys())
    ]

    category_volume = [
        {"category": cat, "count": category_counts[cat]}
        for cat in sorted(category_counts.keys(), key=lambda c: (-category_counts[c], c))
    ]

    return {
        "date_from": d_from,
        "date_to": d_to,
        "kpis": {
            "total_patients": total_patients,
            "total_tests": total_tests,
            "completed_tests": completed,
            "pending_tests": pending,
            "completion_rate_pct": completion_rate,
            "avg_tests_per_patient": avg_tests,
            "unique_operators": len(operators),
        },
        "registration_series": registration_series,
        "peak_hours": [
            {"hour": h, "count": reg_by_hour[h]}
            for h in sorted(reg_by_hour.keys())
        ],
        "category_volume": category_volume,
        "result_ratio": {
            "normal": normal_total,
            "abnormal": abnormal_total,
            "unclassified": unclassified_total,
        },
        "has_data": bool(patients or tests),
    }


def compute_telemetry(date_from: str | None, date_to: str | None) -> dict[str, Any]:
    d_from, d_to = normalize_date_range(date_from, date_to)
    if not d_from or not d_to:
        today = _utc_today().isoformat()
        d_from = d_from or today
        d_to = d_to or today

    patients = fetch_patients_in_range(d_from, d_to)

    if not patients:
        return {
            "date_from": d_from,
            "date_to": d_to,
            "registration_series": [],
            "hourly_series": [],
            "operator_throughput": [],
            "shift_breakdown": [],
            "has_data": False,
        }

    reg_by_day: Counter[str] = Counter()
    reg_by_hour: Counter[str] = Counter()
    by_operator: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"registrations": 0, "user_id": None, "shifts": Counter()}
    )
    shift_counts: Counter[str] = Counter()

    for p in patients:
        dt = _parse_iso_dt(p.get("created_at"))
        day = _date_key(dt)
        hour = _hour_key(dt)
        if day:
            reg_by_day[day] += 1
        if hour:
            reg_by_hour[hour] += 1

        op_name = (p.get("user") or "").strip() or "Unknown"
        op_key = str(p.get("user_id") or op_name)
        entry = by_operator[op_key]
        entry["operator"] = op_name
        entry["user_id"] = p.get("user_id")
        entry["registrations"] += 1
        shift = (p.get("shift") or "Unassigned").strip()
        entry["shifts"][shift] += 1
        shift_counts[shift] += 1

    operator_throughput = sorted(
        [
            {
                "operator": v["operator"],
                "user_id": v["user_id"],
                "registrations": v["registrations"],
                "primary_shift": v["shifts"].most_common(1)[0][0] if v["shifts"] else "—",
            }
            for v in by_operator.values()
        ],
        key=lambda x: (-x["registrations"], x["operator"].lower()),
    )

    days_in_range = max(len(reg_by_day), 1)
    total_regs = sum(reg_by_day.values())
    avg_daily = round(total_regs / days_in_range, 1)

    return {
        "date_from": d_from,
        "date_to": d_to,
        "kpis": {
            "total_registrations": total_regs,
            "avg_daily_registrations": avg_daily,
            "peak_hour": max(reg_by_hour.items(), key=lambda x: x[1])[0] if reg_by_hour else "—",
            "peak_hour_count": max(reg_by_hour.values()) if reg_by_hour else 0,
            "active_operators": len(by_operator),
        },
        "registration_series": [
            {"date": day, "count": reg_by_day[day]} for day in sorted(reg_by_day.keys())
        ],
        "hourly_series": [
            {"hour": h, "count": reg_by_hour[h]} for h in sorted(reg_by_hour.keys())
        ],
        "operator_throughput": operator_throughput,
        "shift_breakdown": [
            {"shift": s, "count": shift_counts[s]}
            for s in sorted(shift_counts.keys(), key=lambda x: (-shift_counts[x], x))
        ],
        "has_data": True,
    }


def compute_tests(date_from: str | None, date_to: str | None) -> dict[str, Any]:
    d_from, d_to = normalize_date_range(date_from, date_to)
    if not d_from or not d_to:
        today = _utc_today().isoformat()
        d_from = d_from or today
        d_to = d_to or today

    tests = fetch_test_results_in_range(d_from, d_to)

    if not tests:
        return {
            "date_from": d_from,
            "date_to": d_to,
            "kpis": {
                "total_tests": 0,
                "completed_tests": 0,
                "pending_tests": 0,
                "normal_parameters": 0,
                "abnormal_parameters": 0,
                "abnormal_rate_pct": 0.0,
            },
            "category_volume": [],
            "top_tests": [],
            "result_ratio": {"normal": 0, "abnormal": 0, "unclassified": 0},
            "status_breakdown": [],
            "has_data": False,
        }

    category_counts: Counter[str] = Counter()
    test_name_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    normal_total = abnormal_total = unclassified_total = 0
    completed = pending = 0

    for row in tests:
        category = (row.get("category") or "Uncategorized").strip()
        category_counts[category] += 1
        test_name = (row.get("test_name") or "Unknown Test").strip()
        test_name_counts[test_name] += 1
        status = (row.get("status") or "Pending").strip()
        status_counts[status] += 1
        if status.lower() in ("completed", "synced", "done"):
            completed += 1
        else:
            pending += 1
        n, a, u = _classify_test_row(row)
        normal_total += n
        abnormal_total += a
        unclassified_total += u

    classifiable = normal_total + abnormal_total
    abnormal_rate = round((abnormal_total / classifiable) * 100, 1) if classifiable else 0.0

    top_tests = [
        {"test_name": name, "count": count}
        for name, count in test_name_counts.most_common(10)
    ]

    return {
        "date_from": d_from,
        "date_to": d_to,
        "kpis": {
            "total_tests": len(tests),
            "completed_tests": completed,
            "pending_tests": pending,
            "normal_parameters": normal_total,
            "abnormal_parameters": abnormal_total,
            "abnormal_rate_pct": abnormal_rate,
        },
        "category_volume": [
            {"category": cat, "count": category_counts[cat]}
            for cat in sorted(category_counts.keys(), key=lambda c: (-category_counts[c], c))
        ],
        "top_tests": top_tests,
        "result_ratio": {
            "normal": normal_total,
            "abnormal": abnormal_total,
            "unclassified": unclassified_total,
        },
        "status_breakdown": [
            {"status": s, "count": status_counts[s]}
            for s in sorted(status_counts.keys(), key=lambda x: (-status_counts[x], x))
        ],
        "has_data": True,
    }


def _cache_is_fresh(computed_at: str | None, date_to: str) -> bool:
    if not computed_at:
        return False
    computed = _parse_iso_dt(computed_at)
    if not computed:
        return False
    age = (datetime.now(timezone.utc) - computed.astimezone(timezone.utc)).total_seconds()
    ttl = CACHE_TTL_SECONDS if date_to >= _utc_today().isoformat() else HISTORICAL_CACHE_TTL_SECONDS
    return age <= ttl


def _load_snapshot(snapshot_type: str, date_from: str, date_to: str) -> dict | None:
    try:
        supabase = init_supabase()
        resp = (
            supabase.table("analytics_snapshots")
            .select("payload,computed_at")
            .eq("snapshot_type", snapshot_type)
            .eq("date_from", date_from)
            .eq("date_to", date_to)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        row = rows[0]
        if not _cache_is_fresh(row.get("computed_at"), date_to):
            return None
        payload = row.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as e:
        logger.debug(f"Analytics snapshot read skipped: {e}")
        return None


def _save_snapshot(snapshot_type: str, date_from: str, date_to: str, payload: dict) -> None:
    try:
        supabase = init_supabase()
        supabase.table("analytics_snapshots").upsert(
            {
                "snapshot_type": snapshot_type,
                "date_from": date_from,
                "date_to": date_to,
                "payload": payload,
                "computed_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="snapshot_type,date_from,date_to",
        ).execute()
    except Exception as e:
        logger.debug(f"Analytics snapshot write skipped: {e}")


def get_analytics_snapshot(
    snapshot_type: str,
    date_from: str | None,
    date_to: str | None,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    d_from, d_to = normalize_date_range(date_from, date_to)
    if not d_from or not d_to:
        today = _utc_today().isoformat()
        d_from = d_from or today
        d_to = d_to or today

    if not force_refresh:
        cached = _load_snapshot(snapshot_type, d_from, d_to)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    compute_map = {
        "overview": compute_overview,
        "telemetry": compute_telemetry,
        "tests": compute_tests,
    }
    compute_fn = compute_map.get(snapshot_type)
    if not compute_fn:
        raise ValueError(f"Unknown snapshot type: {snapshot_type}")

    payload = compute_fn(d_from, d_to)
    payload["from_cache"] = False
    payload["computed_at"] = datetime.now(timezone.utc).isoformat()
    _save_snapshot(snapshot_type, d_from, d_to, payload)
    return payload


def save_analytics_pdf_to_system_logs(
    pdf_bytes: bytes,
    date_from: str,
    date_to: str,
) -> list[str]:
    """Write analytics PDF copies under date-time folders on D: and C: drives."""
    timestamp_folder = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"LabFlow_Analytics_{date_from}_to_{date_to}.pdf"
    saved_paths: list[str] = []

    for root in ANALYTICS_PDF_ARCHIVE_ROOTS:
        drive = root[:2]
        if drive.endswith(":") and not os.path.exists(f"{drive}\\"):
            logger.warning(f"Analytics PDF archive skipped (drive unavailable): {root}")
            continue
        try:
            folder = os.path.join(root, timestamp_folder)
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, filename)
            with open(path, "wb") as f:
                f.write(pdf_bytes)
            saved_paths.append(path)
            logger.info(f"Analytics PDF archived: {path}")
        except Exception as e:
            log_error(e, "ANALYTICS_PDF_ARCHIVE")

    return saved_paths
