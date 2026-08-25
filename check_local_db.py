"""
LabFlow - Local PostgreSQL Diagnostic & Health Inspector CLI
============================================================
Runs comprehensive connectivity tests, schema verification,
and displays table row counts for local PostgreSQL database.
"""

import sys
import json
from local_postgres_engine import check_db_health, get_table_status, init_local_schema

def run_diagnostics():
    print("=" * 65)
    print("      LABFLOW LOCAL POSTGRESQL DATABASE DIAGNOSTICS         ")
    print("=" * 65)

    # 1. Health check
    health = check_db_health()
    status_tag = "[OK]" if health["status"] == "healthy" else "[FAIL]"
    
    print(f"\n[Connection Status] {status_tag} {health['status'].upper()}")
    print(f"  - Host:               {health.get('host')}:{health.get('port')}")
    print(f"  - Database:           {health.get('database_name')}")
    print(f"  - Latency:            {health.get('latency_ms')} ms")
    
    if health["status"] == "healthy":
        print(f"  - Server Version:     {health.get('version')}")
        print(f"  - Active Connections: {health.get('active_connections')}")
        print(f"  - Total Tables:       {health.get('total_tables')}")
    else:
        print(f"  - Detail:             {health.get('message')}")
        print("\nAttempting automated database and schema initialization...")
        ok, msg = init_local_schema()
        print(f"  - Initialization Result: {msg}")
        health = check_db_health()

    # 2. Table Inspection
    print("\n" + "-" * 65)
    print("  TABLE NAME              | EXISTS | RECORD COUNT | STATUS")
    print("-" * 65)
    
    tables = get_table_status()
    for t in tables:
        exists_str = "YES" if t["exists"] else "NO "
        print(f"  {t['table_name']:23} |  {exists_str}   | {t['row_count']:12} | {t['status']}")

    print("-" * 65)
    print("Diagnostics complete.\n")

if __name__ == "__main__":
    run_diagnostics()
