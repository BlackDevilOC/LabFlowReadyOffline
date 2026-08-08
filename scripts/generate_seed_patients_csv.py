#!/usr/bin/env python3
"""
Generate CSV files for bulk import into Supabase (patients + test_results_all).

No test_values payload — uses empty JSON {} and status Pending, matching registration
without entered results.

Usage (from repo root):
  python scripts/generate_seed_patients_csv.py --probe
  python scripts/generate_seed_patients_csv.py --count 4000
  python scripts/generate_seed_patients_csv.py --count 4000 --start-mr 104056

Output (default): scripts/seed_output/
  patients_seed.csv
  test_results_all_seed.csv
  SEED_IMPORT_NOTES.txt

Requires SUPABASE_URL + SUPABASE_KEY in .env only for --probe / --fetch-tests (default on).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Fallback catalog if Supabase tests cannot be loaded
# ---------------------------------------------------------------------------
FALLBACK_TESTS = [
    ("CBC", "Hematology"),
    ("ESR", "Hematology"),
    ("PT/INR", "Hematology"),
    ("RBS", "Biochemistry"),
    ("UELFT", "Biochemistry"),
    ("Serum Creatinine", "Biochemistry"),
    ("Serum Urea", "Biochemistry"),
    ("Serum Electrolytes", "Biochemistry"),
    ("HBsAg", "Serology"),
    ("Anti HCV", "Serology"),
    ("HIV", "Serology"),
    ("VDRL", "Serology"),
    ("Urine DR", "Urine Analysis"),
    ("Stool DR", "Stool Analysis"),
]

FIRST_NAMES_M = [
    "Muhammad", "Ahmed", "Ali", "Hassan", "Usman", "Bilal", "Imran", "Kamran",
    "Fahad", "Saeed", "Asif", "Naveed", "Tariq", "Rashid", "Shahid", "Waqas",
]
FIRST_NAMES_F = [
    "Ayesha", "Fatima", "Sana", "Hina", "Maria", "Nadia", "Sadia", "Rabia",
    "Zainab", "Amna", "Kiran", "Shazia", "Bushra", "Samina", "Nazia", "Laiba",
]
LAST_NAMES = [
    "Khan", "Shaikh", "Malik", "Memon", "Soomro", "Chandio", "Abbasi", "Brohi",
    "Kolachi", "Ansari", "Qureshi", "Laghari", "Junejo", "Mirani", "Phulpoto",
]
RELATIONS = ["S/O", "D/O", "W/O"]
SHIFTS = ["MORNING", "EVENING", "NIGHT", "HOLIDAY", "OPD"]
SALUTATIONS = {"Male": "Mr", "Female": "Mrs"}


def _rand_mobile(rng: random.Random) -> str:
    return f"03{rng.randint(0, 9)}{rng.randint(10000000, 99999999)}"[:11]


def _rand_cnic(rng: random.Random) -> str:
    return f"{rng.randint(10000, 99999)}-{rng.randint(1000000, 9999999)}-{rng.randint(1, 9)}"


def _rand_created_at(rng: random.Random, days_back: int = 120) -> str:
    base = datetime.now(timezone.utc) - timedelta(days=days_back)
    offset = timedelta(
        days=rng.randint(0, days_back),
        hours=rng.randint(6, 20),
        minutes=rng.randint(0, 59),
    )
    return (base + offset).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def load_tests_from_supabase() -> list[tuple[str, str]]:
    try:
        from dbActions import init_supabase

        supabase = init_supabase()
        resp = (
            supabase.table("tests")
            .select("name, category, status")
            .eq("status", True)
            .execute()
        )
        rows = []
        for t in resp.data or []:
            name = (t.get("name") or "").strip()
            if not name or name.startswith("#"):
                continue
            rows.append((name, (t.get("category") or "General").strip()))
        return rows or FALLBACK_TESTS.copy()
    except Exception as exc:
        print(f"Warning: could not load tests from Supabase ({exc}). Using fallback catalog.")
        return FALLBACK_TESTS.copy()


def probe_supabase() -> dict:
    from dbActions import init_supabase

    supabase = init_supabase()
    out: dict = {"tables": {}}
    for table in ("patients", "test_results_all", "tests"):
        row = supabase.table(table).select("*").limit(1).execute()
        cols = sorted(row.data[0].keys()) if row.data else []
        cnt = supabase.table(table).select("id", count="exact").limit(0).execute()
        out["tables"][table] = {"count": cnt.count, "columns": cols}

    max_mr = (
        supabase.table("patients")
        .select("mr_no")
        .order("mr_no", desc=True)
        .limit(1)
        .execute()
    )
    out["max_mr_no"] = max_mr.data[0]["mr_no"] if max_mr.data else 0
    out["suggested_start_mr"] = int(out["max_mr_no"]) + 1
    return out


def estimate_storage(patients: int, tests_per_patient: float) -> dict:
    """Rough CSV / DB size hints for planning (not exact)."""
    test_rows = int(patients * tests_per_patient)
    patient_row_bytes = 280
    test_row_bytes = 180  # empty test_values {}
    csv_bytes = patients * patient_row_bytes + test_rows * test_row_bytes
    return {
        "patient_rows": patients,
        "test_result_rows": test_rows,
        "estimated_csv_mb": round(csv_bytes / (1024 * 1024), 2),
        "note": (
            "Supabase Free: 500 MB database quota (Postgres data). "
            "4k patients + ~8k thin test rows is typically well under 5 MB."
        ),
    }


def generate_patient_row(rng: random.Random, mr_no: int, created_at: str) -> dict:
    gender = rng.choice(["Male", "Female"])
    first = rng.choice(FIRST_NAMES_M if gender == "Male" else FIRST_NAMES_F)
    last = rng.choice(LAST_NAMES)
    relation = rng.choice(RELATIONS)
    age = rng.randint(1, 85)
    salutation = SALUTATIONS.get(gender, "Mr")
    if gender == "Female" and age < 18:
        salutation = "Miss"

    return {
        "mr_no": mr_no,
        "salutation": salutation,
        "patient_name": f"{first} {last}",
        "relation": relation,
        "relation_name": f"{rng.choice(FIRST_NAMES_M)} {rng.choice(LAST_NAMES)}",
        "mobile": _rand_mobile(rng),
        "gender": gender,
        "age": age,
        "cnic": _rand_cnic(rng),
        "patient_token": rng.randint(1, 9999),
        "shift": rng.choice(SHIFTS),
        "user": "seed_import",
        "pwd": str(rng.randint(1000, 999999)),
        "created_at": created_at,
    }


def generate_test_rows(
    rng: random.Random,
    mr_no: int,
    patient_name: str,
    catalog: list[tuple[str, str]],
    min_tests: int,
    max_tests: int,
    created_at: str,
) -> list[dict]:
    n = rng.randint(min_tests, max_tests)
    chosen = rng.sample(catalog, k=min(n, len(catalog)))
    rows = []
    for test_name, category in chosen:
        rows.append(
            {
                "mr_no": mr_no,
                "patient_name": patient_name,
                "category": category,
                "test_name": test_name,
                "test_values": "{}",
                "status": "Pending",
                "delete_status": "false",
                "remarks": "",
                "created_at": created_at,
            }
        )
    return rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_notes(path: Path, start_mr: int, count: int, probe: dict | None) -> None:
    lines = [
        "LabFlow seed import notes",
        "========================",
        "",
        "1) Import patients_seed.csv into table: patients",
        "   - Do NOT import column 'id' (auto-generated).",
        "   - Include mr_no so test rows can link.",
        "   - Do NOT import user_id (leave NULL; empty string breaks bigint).",
        "",
        "2) Import test_results_all_seed.csv into table: test_results_all",
        "   - test_values is empty JSON: {}",
        "   - status: Pending (no result entry)",
        "",
        f"3) This batch: MR {start_mr} .. {start_mr + count - 1} ({count} patients)",
        "",
        "4) After import, reset mr_no sequence (SQL editor):",
        f"   SELECT setval(pg_get_serial_sequence('patients', 'mr_no'),",
        f"          (SELECT MAX(mr_no) FROM patients));",
        "",
        "5) Verify in app: register one new real patient, search update/print lists.",
        "",
    ]
    if probe:
        lines.extend(
            [
                "Current Supabase (at generation time):",
                f"  patients count: {probe['tables']['patients']['count']}",
                f"  test_results_all count: {probe['tables']['test_results_all']['count']}",
                f"  tests catalog count: {probe['tables']['tests']['count']}",
                f"  max mr_no before seed: {probe['max_mr_no']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Supabase seed CSVs for load testing.")
    parser.add_argument("--count", type=int, default=4000, help="Number of patients (default 4000)")
    parser.add_argument(
        "--start-mr",
        type=int,
        default=None,
        help="First mr_no (default: max(mr_no)+1 from Supabase when --fetch-tests)",
    )
    parser.add_argument("--min-tests", type=int, default=1, help="Min tests per patient")
    parser.add_argument("--max-tests", type=int, default=3, help="Max tests per patient")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "scripts" / "seed_output",
        help="Output directory",
    )
    parser.add_argument(
        "--suffix",
        type=str,
        default="",
        help="Filename suffix, e.g. 80k -> patients_seed_80k.csv (keeps default files if empty)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for reproducible names",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Print Supabase table counts/columns and storage estimate; no files written",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Do not call Supabase (use fallback test catalog; you must pass --start-mr)",
    )
    args = parser.parse_args()

    if args.min_tests < 1 or args.max_tests < args.min_tests:
        parser.error("--min-tests must be >= 1 and <= --max-tests")

    probe_data = None
    if not args.no_fetch:
        try:
            probe_data = probe_supabase()
        except Exception as exc:
            print(f"Warning: Supabase probe failed: {exc}")

    if args.probe:
        if probe_data:
            print(json.dumps(probe_data, indent=2))
        avg_tests = (args.min_tests + args.max_tests) / 2
        print(json.dumps(estimate_storage(args.count, avg_tests), indent=2))
        return

    rng = random.Random(args.seed)
    start_mr = args.start_mr
    if start_mr is None:
        if probe_data:
            start_mr = probe_data["suggested_start_mr"]
        else:
            parser.error("Pass --start-mr or allow Supabase probe (omit --no-fetch)")

    catalog = FALLBACK_TESTS.copy() if args.no_fetch else load_tests_from_supabase()
    print(f"Using {len(catalog)} tests in catalog. MR range: {start_mr} .. {start_mr + args.count - 1}")

    patient_fields = [
        "mr_no",
        "salutation",
        "patient_name",
        "relation",
        "relation_name",
        "mobile",
        "gender",
        "age",
        "cnic",
        "patient_token",
        "shift",
        "user",
        "pwd",
        "created_at",
    ]
    test_fields = [
        "mr_no",
        "patient_name",
        "category",
        "test_name",
        "test_values",
        "status",
        "delete_status",
        "remarks",
        "created_at",
    ]

    patients_rows: list[dict] = []
    test_rows: list[dict] = []

    for i in range(args.count):
        mr_no = start_mr + i
        created_at = _rand_created_at(rng)
        patient = generate_patient_row(rng, mr_no, created_at)
        patients_rows.append(patient)
        test_rows.extend(
            generate_test_rows(
                rng,
                mr_no,
                patient["patient_name"],
                catalog,
                args.min_tests,
                args.max_tests,
                created_at,
            )
        )

    out_dir = args.out_dir
    tag = f"_{args.suffix.strip()}" if args.suffix and args.suffix.strip() else ""
    patients_path = out_dir / f"patients_seed{tag}.csv"
    tests_path = out_dir / f"test_results_all_seed{tag}.csv"
    notes_path = out_dir / (f"SEED_IMPORT_NOTES{tag}.txt" if tag else "SEED_IMPORT_NOTES.txt")

    write_csv(patients_path, patient_fields, patients_rows)
    write_csv(tests_path, test_fields, test_rows)
    write_notes(notes_path, start_mr, args.count, probe_data)

    avg_tests = len(test_rows) / max(args.count, 1)
    est = estimate_storage(args.count, avg_tests)
    print(f"Wrote {patients_path} ({len(patients_rows)} rows)")
    print(f"Wrote {tests_path} ({len(test_rows)} rows, ~{avg_tests:.1f} tests/patient)")
    print(f"Wrote {notes_path}")
    print(json.dumps(est, indent=2))


if __name__ == "__main__":
    main()
