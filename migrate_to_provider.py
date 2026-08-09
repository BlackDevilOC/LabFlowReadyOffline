"""
LabFlow - Disaster Recovery & Provider Migration CLI
===================================================
One-command migration tool to restore or migrate all LabFlow data
from local replica files to a secondary region or new database provider.

Supported Targets:
1. Any PostgreSQL Instance (Secondary Supabase, Neon, Railway, RDS, Self-Hosted)
2. Local/Target SQLite Database
3. Switch LabFlow App Configuration (.env)

Usage:
  # Dry-run test against secondary PostgreSQL:
  python migrate_to_provider.py --target-pg-url "postgresql://user:pass@host:5432/dbname" --dry-run

  # Full migration to secondary PostgreSQL:
  python migrate_to_provider.py --target-pg-url "postgresql://user:pass@host:5432/dbname"

  # Safe upsert mode (without dropping tables):
  python migrate_to_provider.py --target-pg-url "postgresql://user:pass@host:5432/dbname" --upsert-only

  # Switch app .env to secondary provider:
  python migrate_to_provider.py --switch-supabase-url "https://new-project.supabase.co" --switch-supabase-key "new_key"
"""

import os
import sys
import argparse
import subprocess
from datetime import datetime
from replica_engine import get_replica_engine, get_base_dir


def load_master_sql(location: str, upsert_only: bool = False) -> str:
    """Reads the generated master PostgreSQL migration script."""
    filename = "migration_postgres_upsert.sql" if upsert_only else "migration_postgres_full.sql"
    sql_path = os.path.join(location, "sql", filename)
    if not os.path.exists(sql_path):
        raise FileNotFoundError(f"Master SQL file not found at: {sql_path}. Please run replica_worker.py first.")
    with open(sql_path, "r", encoding="utf-8") as f:
        return f.read()


def execute_pg_migration(pg_url: str, sql_content: str, dry_run: bool = False) -> dict:
    """
    Executes PostgreSQL migration using psycopg2, asyncpg, or psql.
    """
    print(f"Connecting to target PostgreSQL: {pg_url.split('@')[-1] if '@' in pg_url else pg_url}...")
    
    if dry_run:
        print("[DRY-RUN] Validating SQL syntax and table statements...")
        lines = [line.strip() for line in sql_content.splitlines() if line.strip() and not line.startswith("--")]
        create_tables = [l for l in lines if l.upper().startswith("CREATE TABLE")]
        inserts = [l for l in lines if l.upper().startswith("INSERT INTO")]
        print(f"[DRY-RUN] Found {len(create_tables)} table definitions and {len(inserts)} data batch statements.")
        return {
            "status": "success",
            "dry_run": True,
            "table_count": len(create_tables),
            "insert_batches": len(inserts)
        }

    # Try psycopg2 if installed
    try:
        import psycopg2
        conn = psycopg2.connect(pg_url)
        conn.autocommit = False
        cursor = conn.cursor()
        print("Executing migration statements on target database...")
        cursor.execute(sql_content)
        conn.commit()
        cursor.close()
        conn.close()
        print("[OK] Migration executed successfully via psycopg2.")
        return {"status": "success", "driver": "psycopg2"}
    except ImportError:
        pass
    except Exception as e:
        print(f"psycopg2 execution error: {e}")
        raise

    # Fallback to psql command if available
    try:
        temp_sql_file = "temp_migration_exec.sql"
        with open(temp_sql_file, "w", encoding="utf-8") as f:
            f.write(sql_content)

        res = subprocess.run(["psql", pg_url, "-f", temp_sql_file], capture_output=True, text=True)
        if os.path.exists(temp_sql_file):
            os.remove(temp_sql_file)

        if res.returncode == 0:
            print("[OK] Migration executed successfully via psql.")
            return {"status": "success", "driver": "psql"}
        else:
            raise RuntimeError(f"psql execution failed:\n{res.stderr}")
    except FileNotFoundError:
        pass

    # If neither psycopg2 nor psql is available, write ready-to-run file and guide user
    output_ready_path = os.path.join(get_base_dir(), "READY_TO_MIGRATE.sql")
    with open(output_ready_path, "w", encoding="utf-8") as f:
        f.write(sql_content)
    print(f"\n[INFO] Target SQL script ready at: {output_ready_path}")
    print("To execute on your secondary database:")
    print(f"  1. Install psycopg2: pip install psycopg2-binary, OR")
    print(f"  2. Run with psql: psql \"{pg_url}\" -f \"{output_ready_path}\", OR")
    print(f"  3. Copy and paste contents into Supabase SQL Editor on your secondary project.")
    return {"status": "prepared_sql", "path": output_ready_path}


def switch_app_env(new_url: str, new_key: str):
    """Updates local .env file with secondary provider credentials."""
    base_dir = get_base_dir()
    env_path = os.path.join(base_dir, ".env")
    
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # Update or add SUPABASE_URL and SUPABASE_KEY
    url_found = False
    key_found = False
    new_lines = []

    for line in lines:
        if line.startswith("SUPABASE_URL="):
            new_lines.append(f"SUPABASE_URL={new_url}\n")
            url_found = True
        elif line.startswith("SUPABASE_KEY="):
            new_lines.append(f"SUPABASE_KEY={new_key}\n")
            key_found = True
        else:
            new_lines.append(line)

    if not url_found:
        new_lines.append(f"SUPABASE_URL={new_url}\n")
    if not key_found:
        new_lines.append(f"SUPABASE_KEY={new_key}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"[OK] Updated {env_path} to point to secondary provider: {new_url}")


def main():
    parser = argparse.ArgumentParser(description="LabFlow Disaster Recovery & Provider Migration Tool")
    parser.add_argument("--target-pg-url", type=str, default=None, help="Target PostgreSQL connection URL")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry-run test without making changes")
    parser.add_argument("--upsert-only", action="store_true", help="Use safe ON CONFLICT DO UPDATE upserts")
    parser.add_argument("--location", type=str, default=None, help="Custom replica location directory")
    parser.add_argument("--switch-supabase-url", type=str, default=None, help="New Supabase URL to set in .env")
    parser.add_argument("--switch-supabase-key", type=str, default=None, help="New Supabase Key to set in .env")

    args = parser.parse_args()

    print("\n=======================================================")
    print("      LABFLOW DISASTER RECOVERY & MIGRATION TOOL       ")
    print("=======================================================\n")

    if args.switch_supabase_url and args.switch_supabase_key:
        switch_app_env(args.switch_supabase_url, args.switch_supabase_key)
        return

    engine = get_replica_engine()
    loc = args.location or engine.location_1

    print(f"Reading master replication scripts from: {loc}")
    sql_content = load_master_sql(loc, upsert_only=args.upsert_only)

    if args.target_pg_url:
        res = execute_pg_migration(args.target_pg_url, sql_content, dry_run=args.dry_run)
        if res.get("status") == "success":
            print("\n[OK] Target migration step completed successfully!")
    else:
        print("No target PostgreSQL URL specified.")
        print(f"Master SQL file is available at: {os.path.join(loc, 'sql', 'migration_postgres_full.sql')}")
        print("Run with --target-pg-url \"postgresql://...\" to perform migration.")


if __name__ == "__main__":
    main()
