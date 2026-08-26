"""
LabFlow - SQLite Replica to Local PostgreSQL Importer
======================================================
Imports all 4,390+ patients, 12,600+ test results, tests catalog, users,
and settings from SQLite replica database (TEMP_DATA/labflow_replica.db)
into local PostgreSQL (labflow_db).
"""

import os
import sys
import json
import time
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# Ensure local DB environment password is set to opd_pass
os.environ["LOCAL_DB_HOST"] = "127.0.0.1"
os.environ["LOCAL_DB_PORT"] = "5432"
os.environ["LOCAL_DB_NAME"] = "labflow_db"
os.environ["LOCAL_DB_USER"] = "postgres"
os.environ["LOCAL_DB_PASS"] = "opd_pass"

from local_postgres_engine import get_connection, init_local_schema, get_db_config

SQLITE_DB_PATH = os.path.join(os.path.dirname(__file__), "TEMP_DATA", "labflow_replica.db")


def update_env_file():
    """Updates .env file with LOCAL_DB credentials."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    # Filter out existing LOCAL_DB keys
    lines = [l for l in lines if not l.startswith("LOCAL_DB_")]
    lines.append("\nLOCAL_DB_HOST=127.0.0.1\n")
    lines.append("LOCAL_DB_PORT=5432\n")
    lines.append("LOCAL_DB_NAME=labflow_db\n")
    lines.append("LOCAL_DB_USER=postgres\n")
    lines.append("LOCAL_DB_PASS=opd_pass\n")

    with open(env_path, "w") as f:
        f.writelines(lines)


def update_labflow_config():
    """Updates labflow_config.json with LOCAL_DB_PASS=opd_pass."""
    cfg = {
        "LOCAL_DB_HOST": "127.0.0.1",
        "LOCAL_DB_PORT": 5432,
        "LOCAL_DB_NAME": "labflow_db",
        "LOCAL_DB_USER": "postgres",
        "LOCAL_DB_PASS": "opd_pass",
        "SERVER_PORT": 8000,
        "UPDATED_AT": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    for p in ["labflow_config.json", os.path.join("labflow_server_manager", "labflow_config.json")]:
        with open(p, "w") as f:
            json.dump(cfg, f, indent=2)


def run_migration():
    print("=" * 65)
    print("      LABFLOW SQLITE -> LOCAL POSTGRESQL DATA IMPORTER      ")
    print("=" * 65)

    if not os.path.exists(SQLITE_DB_PATH):
        print(f"Error: SQLite source database not found at '{SQLITE_DB_PATH}'!")
        return

    update_env_file()
    update_labflow_config()

    print("\n[Step 1/4] Ensuring PostgreSQL Database & Schema Tables...")
    ok, msg = init_local_schema()
    if not ok:
        print(f"  [FAIL] Error: {msg}")
        return
    print(f"  [OK] {msg}")

    # Connect to SQLite
    print("\n[Step 2/4] Connecting to SQLite Replica Database...")
    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    # Connect to PostgreSQL
    pg_conn = get_connection()
    pg_cursor = pg_conn.cursor()

    tables_order = [
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

    print("\n[Step 3/4] Transferring Table Data from SQLite -> PostgreSQL...")
    print("-" * 65)

    for tbl in tables_order:
        try:
            sqlite_cursor.execute(f"SELECT * FROM {tbl};")
            rows = sqlite_cursor.fetchall()

            if not rows:
                print(f"  - {tbl:23} |      0 rows (Empty)")
                continue

            columns = list(rows[0].keys())

            # Convert row dicts into tuples with data cleanups
            cleaned_rows = []
            for r in rows:
                r_dict = dict(r)

                # Process specific JSON/boolean columns
                for col_name, val in r_dict.items():
                    if val is None:
                        continue

                    # Handle boolean flags stored as 0/1 in SQLite
                    if col_name in ["status", "is_active", "delete_status", "display_pathologist_signature", "display_verified_by"]:
                        if isinstance(val, int):
                            r_dict[col_name] = bool(val)

                    # Handle JSONB string columns
                    if col_name in ["test_values", "component_ids", "permissions", "payload"]:
                        if isinstance(val, str):
                            try:
                                json.loads(val)  # Validate JSON string syntax
                            except Exception:
                                r_dict[col_name] = "{}" if col_name == "test_values" else "[]"
                        elif isinstance(val, (dict, list)):
                            r_dict[col_name] = json.dumps(val)

                cleaned_rows.append(tuple(r_dict[c] for c in columns))

            # Build PostgreSQL INSERT statement with ON CONFLICT DO NOTHING
            cols_str = '", "'.join(columns)
            placeholders = ", ".join(["%s"] * len(columns))
            insert_query = f'INSERT INTO public."{tbl}" ("{cols_str}") VALUES ({placeholders}) ON CONFLICT DO NOTHING;'

            # Execute batch insert
            pg_cursor.executemany(insert_query, cleaned_rows)
            pg_conn.commit()

            print(f"  - {tbl:23} |  {len(cleaned_rows):6} rows imported successfully")

        except Exception as e:
            pg_conn.rollback()
            print(f"  [FAIL] Error migrating table '{tbl}': {e}")

    # Step 4: Reset PostgreSQL identity sequences so future auto-increment IDs don't collide
    print("\n[Step 4/4] Resetting PostgreSQL Primary Key Identity Sequences...")
    sequence_tables = ["patients", "test_results_all", "tests", "test_groups", "shift", "users", "remarks", "invoice_settings", "app_settings", "analytics_snapshots"]

    for st in sequence_tables:
        try:
            pg_cursor.execute(f"""
                SELECT setval(pg_get_serial_sequence('{st}', 'id'), COALESCE(max(id), 1)) FROM public.{st};
            """)
            pg_conn.commit()
        except Exception:
            pg_conn.rollback()

    sqlite_conn.close()
    pg_cursor.close()
    pg_conn.close()

    print("-" * 65)
    print("Migration finished! Running final verification check...\n")


if __name__ == "__main__":
    run_migration()

    # Run check_local_db
    from check_local_db import run_diagnostics
    run_diagnostics()
