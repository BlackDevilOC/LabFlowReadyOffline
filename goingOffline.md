# Implementation Plan - Local PostgreSQL Database Engine & Inspection System

Transition LabFlow from a cloud-dependent (Supabase) / dual-mode architecture to a **100% On-Premise Local PostgreSQL Engine** hosted on the central lab server PC.

In **Phase 1** (Current Focus), we build a dedicated **Local PostgreSQL Engine Management Module** (`local_postgres_engine.py`) that handles PostgreSQL database initialization, schema creation, live connection probing, table health inspection, and initial seed data loading. In **Phase 2** (Follow-up), we will update `dbActions.py`, `.env`, and the main app to target this local engine.

---

## User Review Required

> [!IMPORTANT]
> **PostgreSQL Prerequisites on Host PC:**
> The local server PC (PC #1) will need a standard PostgreSQL 15 or 16 installation running on `localhost:5432` (or via local Docker/service).
> * Default DB Name: `labflow_db`
> * Default User: `postgres`
> * Password: set in local `.env` as `LOCAL_POSTGRES_PASSWORD`

> [!NOTE]
> The old `offline/` directory (which held the temporary SQLite fallback engine) will be marked for deprecation once the local PostgreSQL engine is verified and integrated.

---

## Open Questions

> [!NOTE]
> None at this stage. The schema is fully defined in [`setup_secondary_schema.sql`](file:///d:/rehan%20d%20DRIVE/production/LabFlowReady-main%20%281%29/LabFlowReady-main/setup_secondary_schema.sql) and [`replica_engine.py`](file:///d:/rehan%20d%20DRIVE/production/LabFlowReady-main%20%281%29/LabFlowReady-main/replica_engine.py).

---

## Proposed Changes

### Phase 1: Local PostgreSQL Engine & Health Inspector

#### [NEW] [local_postgres_engine.py](file:///d:/rehan%20d%20DRIVE/production/LabFlowReady-main%20%281%29/LabFlowReady-main/local_postgres_engine.py)
* **Core Responsibilities:**
  1. **Connection Manager:** Establishes and manages connections/connection pool to local PostgreSQL database using `psycopg2` or `asyncpg` / `SQLAlchemy`.
  2. **Schema Initializer (`init_local_schema()`):** Automates table creation for all 11 core tables (`patients`, `test_results_all`, `tests`, `test_groups`, `shift`, `users`, `remarks`, `invoice_settings`, `print_settings`, `app_settings`, `analytics_snapshots`) and sequence indexes.
  3. **Live Health Probe (`check_db_health()`):** Tests connectivity to local PostgreSQL on `localhost:5432` (or local server IP), returning latency, active connections, database version, and status.
  4. **Table Inspector (`get_table_status()`):** Scans all tables in `labflow_db`, reporting row counts, size, and last updated status.
  5. **Data Seeder (`seed_initial_defaults()`):** Populates default shifts, print settings, invoice settings, and admin user if database is fresh.

#### [NEW] [check_local_db.py](file:///d:/rehan%20d%20DRIVE/production/LabFlowReady-main%20%281%29/LabFlowReady-main/check_local_db.py)
* Command-line diagnostic and verification utility.
* Displays a clean formatted summary of database status, table row counts, and health checks.

#### [NEW] [init_local_db.bat](file:///d:/rehan%20d%20DRIVE/production/LabFlowReady-main%20%281%29/LabFlowReady-main/init_local_db.bat)
* One-click Windows batch script to test PostgreSQL connection, run schema migrations, and seed initial data on PC #1.

---

### Phase 2: Main App Integration (Future Step)

#### [MODIFY] [.env](file:///d:/rehan%20d%20DRIVE/production/LabFlowReady-main%20%281%29/LabFlowReady-main/.env)
* Add local PostgreSQL configuration parameters (`LOCAL_DB_HOST=127.0.0.1`, `LOCAL_DB_PORT=5432`, `LOCAL_DB_NAME=labflow_db`, `LOCAL_DB_USER=postgres`, `LOCAL_DB_PASS=...`).

#### [MODIFY] [dbActions.py](file:///d:/rehan%20d%20DRIVE/production/LabFlowReady-main%20%281%29/LabFlowReady-main/dbActions.py)
* Update database provider adapter to execute queries directly against `local_postgres_engine.py` instead of routing to remote cloud Supabase endpoints.

---

## Verification Plan

### Automated Verification
1. Run `python check_local_db.py` to verify local PostgreSQL connectivity, schema tables, row counts, and index creation.
2. Execute a test insert and read query via `local_postgres_engine.py` to confirm transaction integrity.

### Manual Verification
1. Verify `labflow_db` tables using `check_local_db.py` or pgAdmin / psql CLI.
2. Validate default data seeding (print settings, invoice settings, default shifts).
