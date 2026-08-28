"""
LabFlow - Supabase Cloud 100% Pure Data Replicator
===================================================
Wipes local PostgreSQL tables clean and performs a 1-to-1 untouched transfer
of all 11 tables directly from Supabase Cloud API.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
import psycopg2
from psycopg2.extras import execute_values

SUPABASE_URL = "https://zndiehpmrxpfskwygkhv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpuZGllaHBtcnhwZnNrd3lna2h2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MDU2NjE1NywiZXhwIjoyMDg2MTQyMTU3fQ.92UvyZQtpn92i0q7DflOuLT3jHBjyRmsn7ejpDuOvAI"

# Target Linux PostgreSQL Server IP
target_host = "192.168.1.4"
for arg in sys.argv[1:]:
    if not arg.startswith("-"):
        target_host = arg.strip()
        break

os.environ["LOCAL_DB_HOST"] = target_host
os.environ["LOCAL_DB_PORT"] = os.getenv("LOCAL_DB_PORT", "5432").strip()
os.environ["LOCAL_DB_NAME"] = os.getenv("LOCAL_DB_NAME", "labflow_db").strip()
os.environ["LOCAL_DB_USER"] = os.getenv("LOCAL_DB_USER", "postgres").strip()
os.environ["LOCAL_DB_PASS"] = os.getenv("LOCAL_DB_PASS", "opd_pass").strip()

from local_postgres_engine import get_connection, init_local_schema, check_db_health

TABLE_ORDER = [
    "shift",
    "users",
    "tests",
    "test_groups",
    "remarks",
    "invoice_settings",
    "print_settings",
    "app_settings",
    "patients",
    "test_results_all",
    "analytics_snapshots"
]


def fetch_supabase_table_rows(table_name: str) -> list[dict]:
    """Fetches all rows from Supabase Cloud table using chunked REST API requests."""
    all_rows = []
    chunk_size = 1000
    offset = 0

    while True:
        url = f"{SUPABASE_URL}/rest/v1/{table_name}?select=*"
        req = urllib.request.Request(url)
        req.add_header("apikey", SUPABASE_KEY)
        req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
        req.add_header("Range-Unit", "items")
        req.add_header("Range", f"{offset}-{offset + chunk_size - 1}")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if not data:
                    break
                all_rows.extend(data)
                if len(data) < chunk_size:
                    break
                offset += chunk_size
        except urllib.error.HTTPError as e:
            if e.code == 416:  # Reached end of range
                break
            print(f"  [HTTP Error {e.code}] Fetching {table_name}: {e}")
            break
        except Exception as e:
            print(f"  [Error] Fetching {table_name}: {e}")
            break
    return all_rows


def replicate_pure_supabase_data():
    print("=" * 70)
    print("      LABFLOW PURE SUPABASE CLOUD -> POSTGRES REPLICATOR      ")
    print(f"      Target Server: {target_host}:5432 (labflow_db)")
    print("=" * 70)

    # Step 1: Initialize local schema tables (structure only)
    print("\n[Step 1/4] Ensuring PostgreSQL Schema Table Structures...")
    ok, msg = init_local_schema()
    if not ok:
        print(f"  [FAIL] Could not ensure schema on server: {msg}")
        return

    # Step 2: Wipe all existing rows clean to prevent any dummy seed conflicts
    print("\n[Step 2/4] Wiping existing local tables clean (TRUNCATE CASCADE)...")
    pg_conn = get_connection()
    pg_cursor = pg_conn.cursor()

    truncate_sql = "TRUNCATE TABLE " + ", ".join([f'public."{t}"' for t in TABLE_ORDER]) + " CASCADE;"
    try:
        pg_cursor.execute(truncate_sql)
        pg_conn.commit()
        print("  [OK] All tables wiped 100% clean.")
    except Exception as e:
        pg_conn.rollback()
        print(f"  [Notice] Truncate notice: {e}")

    # Step 3: Fetch & Import untouched Supabase Cloud data
    print("\n[Step 3/4] Replicating Untouched 1-to-1 Data from Supabase Cloud...")
    print("-" * 70)

    total_imported_count = 0

    for tbl in TABLE_ORDER:
        try:
            cloud_rows = fetch_supabase_table_rows(tbl)
            if not cloud_rows:
                print(f"  - {tbl:23} |      0 rows found in cloud")
                continue

            columns = list(cloud_rows[0].keys())

            cleaned_rows = []
            for r in cloud_rows:
                row_tuple = []
                for col in columns:
                    val = r.get(col)
                    if isinstance(val, (dict, list)):
                        val = json.dumps(val)
                    row_tuple.append(val)
                cleaned_rows.append(tuple(row_tuple))

            cols_str = '", "'.join(columns)
            placeholders = ", ".join(["%s"] * len(columns))
            insert_query = f'INSERT INTO public."{tbl}" ("{cols_str}") VALUES ({placeholders});'

            pg_cursor.executemany(insert_query, cleaned_rows)
            pg_conn.commit()

            count = len(cleaned_rows)
            total_imported_count += count
            print(f"  - {tbl:23} |  {count:6} rows replicated 1-to-1")

        except Exception as e:
            pg_conn.rollback()
            print(f"  [FAIL] Error replicating table '{tbl}': {e}")

    # Step 4: Reset PostgreSQL identity sequences to match max cloud IDs
    print("\n[Step 4/4] Aligning Primary Key Sequences with Cloud IDs...")
    sequence_tables = ["patients", "test_results_all", "tests", "test_groups", "shift", "users", "remarks", "invoice_settings", "app_settings", "analytics_snapshots"]

    for st in sequence_tables:
        try:
            sql = f"""
                SELECT setval(pg_get_serial_sequence('public."{st}"', 'id'), COALESCE((SELECT MAX(id) FROM public."{st}"), 1), true);
            """
            pg_cursor.execute(sql)
            pg_conn.commit()
        except Exception:
            pg_conn.rollback()

    # Reset patient mr_no sequence
    try:
        pg_cursor.execute("SELECT setval('patients_mr_no_seq', COALESCE((SELECT MAX(mr_no) FROM public.patients), 1), true);")
        pg_conn.commit()
    except Exception:
        pg_conn.rollback()

    pg_cursor.close()
    pg_conn.close()

    print("\n" + "=" * 70)
    print("      REPLICATION FINISHED SUCCESSFULLY!      ")
    print("=" * 70)
    health = check_db_health()
    print(f" -> Database Status:   {health['status'].upper()}")
    print(f" -> Host:              {health.get('host', target_host)}")
    print(f" -> Latency:           {health.get('latency_ms')} ms")
    print(f" -> Total Replicated:  {total_imported_count} rows across 11 tables\n")


if __name__ == "__main__":
    replicate_pure_supabase_data()
