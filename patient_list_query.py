"""Build Supabase queries for patient/test list pages (browse vs full search)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from search_utils import parse_advanced_filters, row_matches_advanced_filters

PATIENT_EMBED = (
    "patients(relation,relation_name,age,gender,shift,mobile,patient_token,user,user_id)"
)
PATIENT_EMBED_INNER = (
    "patients!inner(relation,relation_name,age,gender,shift,mobile,patient_token,user,user_id)"
)
PATIENT_LIST_BASE = (
    "id,mr_no,patient_name,test_name,category,status,created_at,remarks,"
)

BROWSE_PATIENT_LIMIT = 100
SEARCH_MAX_ROWS = 1000
CHUNK_SIZE = 1000
MAX_LOAD_ALL_ROWS = 100_000


def normalize_status_filter(status: str | None) -> str | None:
    if not status or str(status).strip().lower() == "all":
        return None
    s = str(status).strip().lower()
    if s in ("pending",):
        return "Pending"
    if s in ("completed", "synced"):
        return "Completed"
    return str(status).strip().capitalize()


def normalize_date_range(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    d_from = (date_from or "").strip()[:10] or None
    d_to = (date_to or "").strip()[:10] or None
    if d_from and d_to and d_from > d_to:
        d_from, d_to = d_to, d_from
    return d_from, d_to


def apply_date_range_filters(query, date_from: str | None, date_to: str | None):
    """Inclusive from/to using UTC day bounds."""
    d_from, d_to = normalize_date_range(date_from, date_to)
    if d_from:
        query = query.gte("created_at", f"{d_from}T00:00:00Z")
    if d_to:
        end_exclusive = datetime.strptime(d_to, "%Y-%m-%d") + timedelta(days=1)
        query = query.lt("created_at", end_exclusive.strftime("%Y-%m-%dT00:00:00Z"))
    return query


def patient_list_select(*, use_inner: bool) -> str:
    embed = PATIENT_EMBED_INNER if use_inner else PATIENT_EMBED
    return PATIENT_LIST_BASE + embed


def _needs_patient_inner(*, shift: str | None, adv_filters: list[dict]) -> bool:
    if shift and shift != "all":
        return True
    patient_fields = {"patient_token", "relation_name", "user", "mobile"}
    return any(f.get("field") in patient_fields for f in adv_filters)


def is_search_mode(
    *,
    search: str | None,
    adv_filters: list[dict],
    date_from: str | None,
    date_to: str | None,
    status: str | None,
    shift: str | None,
    category: str | None,
    load_all: bool = False,
) -> bool:
    if load_all:
        return True
    if (search or "").strip():
        return True
    if adv_filters:
        return True
    if date_from or date_to:
        return True
    if status and status != "all":
        return True
    if shift and shift != "all":
        return True
    if category and category != "all":
        return True
    return False


def has_full_date_range(date_from: str | None, date_to: str | None) -> bool:
    d_from, d_to = normalize_date_range(date_from, date_to)
    return bool(d_from and d_to)


def apply_adv_filter_to_query(query, field: str, value: str, user_id=None):
    val = (value or "").strip()
    if not val and not user_id:
        return query

    if field == "mr_no":
        if val.isdigit():
            return query.eq("mr_no", int(val))
        return query.eq("mr_no", val)

    if field == "patient_name":
        return query.ilike("patient_name", f"%{val}%")

    if field == "patient_token":
        if val.isdigit():
            return query.eq("patients.patient_token", int(val))
        return query.eq("patients.patient_token", val)

    if field == "relation_name":
        return query.ilike("patients.relation_name", f"%{val}%")

    if field == "user":
        if user_id not in (None, ""):
            return query.eq("patients.user_id", user_id)
        return query.ilike("patients.user", f"%{val}%")

    if field == "category":
        return query.ilike("category", f"%{val}%")

    if field == "test_name":
        return query.ilike("test_name", f"%{val}%")

    if field == "mobile":
        return query.ilike("patients.mobile", f"%{val}%")

    return query


def build_test_results_query(
    supabase,
    *,
    search: str | None = None,
    filters: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    shift: str | None = None,
    category: str | None = None,
    browse_patient_limit: int = BROWSE_PATIENT_LIMIT,
    load_all: bool = False,
    offset: int = 0,
    chunk_size: int | None = None,
):
    adv_filters = parse_advanced_filters(filters)
    search_mode = is_search_mode(
        search=search,
        adv_filters=adv_filters,
        date_from=date_from,
        date_to=date_to,
        status=status,
        shift=shift,
        category=category,
        load_all=load_all,
    )
    use_inner = _needs_patient_inner(shift=shift, adv_filters=adv_filters) or bool(adv_filters)
    query = (
        supabase.table("test_results_all")
        .select(patient_list_select(use_inner=use_inner))
        .eq("delete_status", False)
    )

    if date_from or date_to:
        query = apply_date_range_filters(query, date_from, date_to)

    db_status = normalize_status_filter(status)
    if db_status:
        query = query.eq("status", db_status)

    if category and category != "all":
        query = query.ilike("category", f"%{category}%")

    if shift and shift != "all":
        query = query.ilike("patients.shift", f"%{shift}%")

    if adv_filters:
        for f in adv_filters:
            query = apply_adv_filter_to_query(
                query,
                f.get("field"),
                f.get("value"),
                user_id=f.get("user_id"),
            )
    elif search and str(search).strip():
        search_str = str(search).strip()
        if search_str.isdigit():
            query = query.eq("mr_no", int(search_str))
        else:
            query = query.ilike("patient_name", f"%{search_str}%")

    query = query.order("created_at", desc=True)

    if chunk_size is not None:
        end = max(offset, 0) + max(chunk_size, 1) - 1
        query = query.range(max(offset, 0), end)
    elif load_all:
        pass
    elif search_mode:
        query = query.limit(SEARCH_MAX_ROWS)
    else:
        query = query.limit(max(browse_patient_limit * 5, 100))

    return query, adv_filters, search_mode, browse_patient_limit


def trim_rows_to_top_patients(rows: list[dict], patient_limit: int) -> list[dict]:
    if patient_limit <= 0 or not rows:
        return rows

    by_mr: dict[Any, list[dict]] = {}
    latest: dict[Any, str] = {}
    for row in rows:
        mr = row.get("mr_no")
        if mr is None:
            continue
        by_mr.setdefault(mr, []).append(row)
        created = row.get("created_at") or ""
        if mr not in latest or created > latest[mr]:
            latest[mr] = created

    ordered_mrs = sorted(latest.keys(), key=lambda m: latest[m], reverse=True)[:patient_limit]
    out: list[dict] = []
    for mr in ordered_mrs:
        out.extend(by_mr.get(mr, []))
    out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


def _process_response_rows(response, flatten_row, adv_filters, legacy_search):
    flat_data: list[dict] = []
    for item in response.data or []:
        row = flatten_row(item, None)
        if not row:
            continue
        if adv_filters and not row_matches_advanced_filters(row, adv_filters, legacy_search=legacy_search):
            continue
        flat_data.append(row)
    return flat_data


def fetch_test_result_list_rows(
    supabase,
    flatten_row,
    *,
    search: str | None = None,
    filters: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    shift: str | None = None,
    category: str | None = None,
    browse_patient_limit: int = BROWSE_PATIENT_LIMIT,
    legacy_search_with_adv: bool = False,
    load_all: bool = False,
    offset: int = 0,
    chunk_size: int | None = None,
) -> tuple[list[dict], dict]:
    """Returns (rows, meta). Use chunk_size + offset for paged load-all."""
    effective_chunk = chunk_size
    if load_all and effective_chunk is None:
        effective_chunk = CHUNK_SIZE

    query, adv_filters, search_mode, browse_limit = build_test_results_query(
        supabase,
        search=search,
        filters=filters,
        date_from=date_from,
        date_to=date_to,
        status=status,
        shift=shift,
        category=category,
        browse_patient_limit=browse_patient_limit,
        load_all=load_all,
        offset=offset,
        chunk_size=effective_chunk if (load_all or chunk_size is not None) else None,
    )
    response = query.execute()
    legacy = search if (legacy_search_with_adv and adv_filters) else None
    flat_data = _process_response_rows(response, flatten_row, adv_filters, legacy)

    if not search_mode and not load_all:
        flat_data = trim_rows_to_top_patients(flat_data, browse_limit)

    flat_data.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    returned = len(flat_data)
    has_more = bool(load_all and effective_chunk and returned >= effective_chunk)
    meta = {
        "offset": offset,
        "returned": returned,
        "has_more": has_more,
        "next_offset": offset + returned if has_more else None,
        "load_all": load_all,
        "truncated": (
            not load_all
            and search_mode
            and returned >= SEARCH_MAX_ROWS
        ),
        "date_range": normalize_date_range(date_from, date_to),
    }
    return flat_data, meta
