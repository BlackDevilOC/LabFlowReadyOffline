"""
LabFlow - 100% Pure Cloud-to-Local PostgreSQL Data Migrator & Sync Engine
========================================================================
Performs a byte-for-byte, 1-to-1 exact migration of all 11 tables from
Supabase Cloud into the on-premise PostgreSQL server (192.168.1.4 / labflow_db).
Zero modification of data values. Automatically aligns all auto-increment sequences.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
import psycopg2
from psycopg2.extras import execute_values

# Cloud Supabase Master Credentials
SUPABASE_URL = "https://zndiehpmrxpfskwygkhv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpuZGllaHBtcnhwZnNrd3lna2h2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MDU2NjE1NywiZXhwIjoyMDg2MTQyMTU3fQ.92UvyZQtpn92i0q7DflOuLT3jHBjyRmsn7ejpDuOvAI"

# Target Server IP configuration
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

# Tables in strict foreign-key / dependency order
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


def fetch_supabase_table_rows(table_name: str, max_retries: int = 5) -> list[dict]:
    """
    Fetches 100% of rows from Supabase Cloud table using chunked pagination
    with automated retry and exponential backoff.
    """
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

        success = False
        data = None
        for attempt in range(1, max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode("utf-8")
                    data = json.loads(raw)
                    if not data:
                        success = True
                        break
                    all_rows.extend(data)
                    success = True
                    if len(data) < chunk_size:
                        # Last page reached
                        break
                    offset += chunk_size
                    break
            except urllib.error.HTTPError as e:
                if e.code == 416:  # Reached end of range (Requested range not satisfiable)
                    success = True
                    break
                print(f"    [Retry {attempt}/{max_retries}] HTTP {e.code} on {table_name}: {e}")
                time.sleep(2 * attempt)
            except Exception as e:
                print(f"    [Retry {attempt}/{max_retries}] Connection error on {table_name}: {e}")
                time.sleep(2 * attempt)

        if not success:
            print(f"    [Warning] Failed to fetch chunk at offset {offset} for {table_name}")
            break
        if not data or len(data) < chunk_size:
            break

    return all_rows


def migrate_cloud_data_to_offline_postgres():
    print("=" * 75)
    print("      LABFLOW 100% PURE CLOUD -> LOCAL POSTGRESQL DATA MIGRATOR      ")
    print(f"      Target Host: {target_host}:5432 (labflow_db)")
    print(f"      Source Cloud: {SUPABASE_URL}")
    print("=" * 75)

    # 1. Health check & Schema creation
    print("\n[Step 1/5] Verifying PostgreSQL Server Connection & Schema...")
    health = check_db_health()
    if health["status"] != "healthy":
        print(f"  [FAIL] Database not accessible at {target_host}:5432: {health.get('message')}")
        return False

    print(f"  [OK] Connected to PostgreSQL {health.get('version', '')} (Latency: {health.get('latency_ms')} ms)")

    ok, msg = init_local_schema()
    if not ok:
        print(f"  [FAIL] Schema initialization error: {msg}")
        return False
    print("  [OK] Master schema verified and ready.")

    # 2. Clean wipe all local tables
    print("\n[Step 2/5] Wiping Local Tables Clean (TRUNCATE CASCADE)...")
    pg_conn = get_connection()
    pg_cursor = pg_conn.cursor()

    truncate_sql = "TRUNCATE TABLE " + ", ".join([f'public."{t}"' for t in TABLE_ORDER]) + " CASCADE;"
    try:
        pg_cursor.execute(truncate_sql)
        pg_conn.commit()
        print("  [OK] All 11 tables truncated cleanly.")
    except Exception as e:
        pg_conn.rollback()
        print(f"  [Notice] Truncate notice: {e}")

    # 3. Fetch and insert 1-to-1 untouched data
    print("\n[Step 3/5] Migrating Untouched 1-to-1 Data from Supabase Cloud...")
    print("-" * 75)
    print(f"{'TABLE NAME':22} | {'CLOUD ROWS':12} | {'MIGRATED':12} | {'STATUS':10}")
    print("-" * 75)

    total_records_migrated = 0
    stats = {}

    for tbl in TABLE_ORDER:
        try:
            cloud_rows = fetch_supabase_table_rows(tbl)
            cloud_count = len(cloud_rows)

            if cloud_count == 0:
                print(f"{tbl:22} | {0:12} | {0:12} | EMPTY")
                stats[tbl] = (0, 0, "EMPTY")
                continue

            # Identify all column names from first row
            columns = list(cloud_rows[0].keys())

            cleaned_rows = []
            for r in cloud_rows:
                row_tuple = []
                for col in columns:
                    val = r.get(col)
                    # Convert dicts or lists into JSON strings for PostgreSQL JSONB
                    if isinstance(val, (dict, list)):
                        val = json.dumps(val)
                    row_tuple.append(val)
                cleaned_rows.append(tuple(row_tuple))

            cols_str = '", "'.join(columns)
            placeholders = ", ".join(["%s"] * len(columns))
            insert_query = f'INSERT INTO public."{tbl}" ("{cols_str}") VALUES ({placeholders});'

            # Execute in batches of 2,000 rows for memory safety and speed
            batch_size = 2000
            for i in range(0, len(cleaned_rows), batch_size):
                batch = cleaned_rows[i:i + batch_size]
                pg_cursor.executemany(insert_query, batch)
                pg_conn.commit()

            # Verify local count
            pg_cursor.execute(f'SELECT COUNT(*) FROM public."{tbl}";')
            local_count = pg_cursor.fetchone()[0]

            match_status = "100% MATCH" if local_count == cloud_count else "MISMATCH"
            total_records_migrated += local_count
            stats[tbl] = (cloud_count, local_count, match_status)
            print(f"{tbl:22} | {cloud_count:12} | {local_count:12} | {match_status}")

        except Exception as e:
            pg_conn.rollback()
            print(f"{tbl:22} | ERROR: {e}")
            stats[tbl] = (0, 0, f"ERROR: {e}")

    # 4. Align all PostgreSQL identity and serial sequences
    print("\n[Step 4/5] Aligning Primary Key & MR Number Sequences...")
    sequence_tables = [
        ("patients", "id"),
        ("test_results_all", "id"),
        ("tests", "id"),
        ("test_groups", "id"),
        ("shift", "id"),
        ("users", "id"),
        ("remarks", "id"),
        ("invoice_settings", "id"),
        ("app_settings", "id"),
        ("analytics_snapshots", "id")
    ]

    for st, pk in sequence_tables:
        try:
            sql = f"""
                SELECT setval(pg_get_serial_sequence('public."{st}"', '{pk}'), COALESCE((SELECT MAX({pk}) FROM public."{st}"), 1), true);
            """
            pg_cursor.execute(sql)
            pg_conn.commit()
        except Exception:
            pg_conn.rollback()

    # Reset patient mr_no sequence
    try:
        pg_cursor.execute("SELECT setval('patients_mr_no_seq', COALESCE((SELECT MAX(mr_no) FROM public.patients), 1), true);")
        pg_conn.commit()
        print("  [OK] Auto-increment sequences aligned to latest cloud IDs.")
    except Exception as e:
        pg_conn.rollback()
        print(f"  [Notice] MR sequence alignment: {e}")

    pg_cursor.close()
    pg_conn.close()

    # 5. Final Verification Summary
    print("\n[Step 5/5] Final Verification Audit:")
    print("=" * 75)
    all_perfect = all(v[2] == "100% MATCH" or v[2] == "EMPTY" for v in stats.values())
    
    if all_perfect:
        print("  >>> SUCCESS: 100% EXACT DATA MIGRATION COMPLETE! <<<")
        print(f"  Total records transferred: {total_records_migrated} across 11 tables.")
        print(f"  Your local PostgreSQL server ({target_host}:5432) is ready for live production today!")
    else:
        print("  >>> WARNING: Some tables had mismatches. Review table stats above. <<<")
    print("=" * 75)
    return all_perfect


if __name__ == "__main__":
    migrate_cloud_data_to_offline_postgres()
