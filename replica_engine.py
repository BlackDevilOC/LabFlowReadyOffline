"""
LabFlow - Supabase Continuous Replica & Disaster Recovery Engine
================================================================
Continuously replicates all Supabase cloud database tables and assets
into two redundant local/drive locations in multiple migration-ready formats:
1. Live SQLite Database (labflow_replica.db)
2. Standalone PostgreSQL Migration Dump (migration_postgres_full.sql)
3. PostgreSQL Incremental Upsert Script (migration_postgres_upsert.sql)
4. Standalone SQLite Migration Dump (migration_sqlite_full.sql)
5. JSON Table Snapshots & Manifest (tables/*.json, replica_manifest.json)
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import hashlib
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

# Try importing Supabase and logging utils
from supabase import create_client, Client
from dotenv import load_dotenv

# Set up dedicated replica logger
logger = logging.getLogger("LabFlow.Replica")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - [REPLICA] - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


def get_base_dir() -> str:
    """Returns the base working directory for LabFlow."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# Known default tables in LabFlow
DEFAULT_TABLES = [
    "patients",
    "test_results_all",
    "tests",
    "test_groups",
    "shift",
    "users",
    "remarks",
    "invoice_settings",
    "print_settings",
    "app_settings",
    "analytics_snapshots"
]

# Primary key hints for tables
TABLE_PRIMARY_KEYS: Dict[str, List[str]] = {
    "patients": ["mr_no"],
    "test_results_all": ["id"],
    "tests": ["id"],
    "test_groups": ["id"],
    "shift": ["id"],
    "users": ["id"],
    "remarks": ["id"],
    "invoice_settings": ["id"],
    "print_settings": ["id"],
    "app_settings": ["id"],
    "analytics_snapshots": ["id"]
}

KNOWN_BOOLEAN_COLS = {"status", "is_active", "is_doctor", "is_receptionist"}


def sanitize_sql_value(val: Any, col_name: str = "", col_type: str = "") -> str:
    """Formats a Python value safely for standard SQL INSERT statements, respecting column types."""
    if val is None:
        return "NULL"
    
    # Check if this column is boolean
    if col_type == "BOOLEAN" or col_name in KNOWN_BOOLEAN_COLS:
        if isinstance(val, bool):
            return "TRUE" if val else "FALSE"
        val_str = str(val).strip().lower()
        if val_str in ("1", "true", "t", "yes"):
            return "TRUE"
        if val_str in ("0", "false", "f", "no"):
            return "FALSE"
        return "TRUE" if val else "FALSE"
        
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    elif isinstance(val, (int, float)):
        return str(val)
    elif isinstance(val, (dict, list)):
        dumped = json.dumps(val, ensure_ascii=False)
        escaped = dumped.replace("'", "''")
        return f"'{escaped}'"
    else:
        escaped = str(val).replace("'", "''")
        return f"'{escaped}'"


def get_disk_free_mb(path: str) -> Optional[int]:
    """Returns free disk space in MB for the given path, or None if unavailable."""
    try:
        if not os.path.exists(path):
            parent = os.path.dirname(os.path.abspath(path))
            if not os.path.exists(parent):
                return None
            path = parent
        usage = shutil.disk_usage(path)
        return int(usage.free / (1024 * 1024))
    except Exception:
        return None


class SupabaseReplicaEngine:
    """
    Continuous replication engine that queries Supabase, tracks high-water marks,
    and updates two physical/drive replica locations in real-time.
    """

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        location_1: Optional[str] = None,
        location_2: Optional[str] = None,
        poll_interval: int = 20,
        full_reconcile_interval: int = 900  # 15 minutes
    ):
        base_dir = get_base_dir()
        
        # Load .env if credentials not directly passed
        if not supabase_url or not supabase_key:
            env_path = os.path.join(base_dir, ".env")
            if os.path.exists(env_path):
                load_dotenv(env_path)
            else:
                load_dotenv()
        self.supabase_url = supabase_url or os.getenv("SUPABASE_URL", "")
        self.supabase_key = supabase_key or os.getenv("SUPABASE_KEY", "")
        self.secondary_supabase_url = os.getenv("SECONDARY_SUPABASE_URL", "")
        self.secondary_supabase_key = os.getenv("SECONDARY_SUPABASE_KEY", "")

        # Location 1: Default to local replica folder inside project
        self.location_1 = location_1 or os.path.join(base_dir, "replica_backups", "primary")

        # Location 2: Default to D:\LabFlow_Replica_Secondary or C:\LabFlow_Replica_Secondary
        if location_2:
            self.location_2 = location_2
        else:
            if os.path.exists("D:\\"):
                self.location_2 = "D:\\LabFlow_Replica_Secondary"
            else:
                self.location_2 = "C:\\LabFlow_Replica_Secondary"

        self.poll_interval = poll_interval
        self.full_reconcile_interval = full_reconcile_interval
        self.tables = list(DEFAULT_TABLES)

        # Thread safety & state tracking
        self._lock = threading.Lock()
        self.is_running = False
        self.is_syncing = False
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None

        # Live metrics
        self.last_sync_time: Optional[str] = None
        self.last_sync_type: str = "none"
        self.last_sync_duration_ms: int = 0
        self.total_sync_cycles: int = 0
        self.consecutive_errors: int = 0
        self.last_error: Optional[str] = None
        self.tables_state: Dict[str, Dict[str, Any]] = {}
        self.last_full_reconcile_time: float = 0.0

        # Secondary Supabase Cloud metrics
        self.secondary_sync_status: str = "configured" if self.secondary_supabase_url else "unconfigured"
        self.secondary_last_push_time: Optional[str] = None
        self.secondary_records_pushed: int = 0
        self._secondary_client: Optional[Client] = None

        # Initialize directories
        self._ensure_directories()
        self._load_sync_state()

    def _ensure_directories(self):
        """Creates standard replica directory structure at both locations."""
        for loc in [self.location_1, self.location_2]:
            try:
                if loc:
                    os.makedirs(os.path.join(loc, "database"), exist_ok=True)
                    os.makedirs(os.path.join(loc, "sql"), exist_ok=True)
                    os.makedirs(os.path.join(loc, "tables"), exist_ok=True)
                    os.makedirs(os.path.join(loc, "schema"), exist_ok=True)
                    os.makedirs(os.path.join(loc, "assets"), exist_ok=True)
            except Exception as e:
                logger.warning(f"Could not initialize directory structure for {loc}: {e}")

    def _get_state_file_path(self, location: str) -> str:
        return os.path.join(location, "sync_state.json")

    def _load_sync_state(self):
        """Loads high-water marks and row stats from Location 1 or Location 2."""
        state_loaded = False
        for loc in [self.location_1, self.location_2]:
            state_file = self._get_state_file_path(loc)
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.tables_state = data.get("tables", {})
                        self.last_sync_time = data.get("last_sync_time")
                        state_loaded = True
                        logger.info(f"Loaded existing sync state from {state_file}")
                        break
                except Exception as e:
                    logger.warning(f"Failed to read state file at {state_file}: {e}")

        if not state_loaded:
            # Initialize empty state for known tables
            for tbl in self.tables:
                self.tables_state[tbl] = {
                    "last_updated_at": None,
                    "last_created_at": None,
                    "max_id": 0,
                    "row_count": 0,
                    "last_sync_time": None,
                    "status": "pending"
                }

    def _save_sync_state(self):
        """Persists current high-water marks to both replica locations."""
        state_data = {
            "version": "1.0.0",
            "last_sync_time": self.last_sync_time,
            "last_sync_type": self.last_sync_type,
            "total_sync_cycles": self.total_sync_cycles,
            "tables": self.tables_state
        }
        for loc in [self.location_1, self.location_2]:
            try:
                state_file = self._get_state_file_path(loc)
                tmp_file = state_file + ".tmp"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2)
                if os.path.exists(state_file):
                    os.replace(tmp_file, state_file)
                else:
                    os.rename(tmp_file, state_file)
            except Exception as e:
                logger.warning(f"Could not persist sync state to {loc}: {e}")

    def get_client(self) -> Client:
        """Creates a fresh Supabase client."""
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("Supabase URL and Key are required. Check your .env file.")
        return create_client(self.supabase_url, self.supabase_key)

    def get_secondary_client(self) -> Optional[Client]:
        """Creates or returns the secondary Supabase client."""
        if not self.secondary_supabase_url or not self.secondary_supabase_key:
            return None
        if self._secondary_client is None:
            self._secondary_client = create_client(self.secondary_supabase_url, self.secondary_supabase_key)
        return self._secondary_client

    def _get_sqlite_conn(self, location: str) -> sqlite3.Connection:
        """Returns a SQLite connection for a given replica location in WAL mode."""
        db_path = os.path.join(location, "database", "labflow_replica.db")
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _sync_sqlite_table(self, location: str, table_name: str, records: List[Dict[str, Any]], primary_keys: List[str]):
        """Creates/Updates SQLite schema and inserts/upserts records."""
        if not records:
            return

        db_path = os.path.join(location, "database", "labflow_replica.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        with self._get_sqlite_conn(location) as conn:
            cursor = conn.cursor()
            
            # 1. Infer SQLite column definitions from records
            all_keys = set()
            for r in records:
                all_keys.update(r.keys())
            cols = sorted(list(all_keys))

            # Determine primary key clause
            valid_pks = [pk for pk in primary_keys if pk in cols]
            pk_clause = f", PRIMARY KEY ({', '.join(valid_pks)})" if valid_pks else ""

            # Check if table exists
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            table_exists = cursor.fetchone() is not None

            if not table_exists:
                col_defs = []
                for col in cols:
                    sample_vals = [r.get(col) for r in records if r.get(col) is not None]
                    sample = sample_vals[0] if sample_vals else None
                    if isinstance(sample, int) and col in valid_pks and len(valid_pks) == 1:
                        col_defs.append(f"{col} INTEGER PRIMARY KEY")
                    elif isinstance(sample, int):
                        col_defs.append(f"{col} INTEGER")
                    elif isinstance(sample, float):
                        col_defs.append(f"{col} REAL")
                    elif isinstance(sample, bool):
                        col_defs.append(f"{col} INTEGER")
                    else:
                        col_defs.append(f"{col} TEXT")
                
                # If single integer pk was added above, omit duplicate pk clause
                if any("PRIMARY KEY" in d for d in col_defs):
                    create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} (\n  " + ",\n  ".join(col_defs) + "\n)"
                else:
                    create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} (\n  " + ",\n  ".join(col_defs) + f"{pk_clause}\n)"
                
                cursor.execute(create_sql)
            else:
                # Add any missing columns to existing SQLite table
                cursor.execute(f"PRAGMA table_info({table_name})")
                existing_cols = {row["name"] for row in cursor.fetchall()}
                for col in cols:
                    if col not in existing_cols:
                        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} TEXT")

            # 2. Prepare UPSERT
            placeholders = ", ".join(["?"] * len(cols))
            columns_str = ", ".join(cols)
            insert_sql = f"INSERT OR REPLACE INTO {table_name} ({columns_str}) VALUES ({placeholders})"

            batch_values = []
            for r in records:
                row_vals = []
                for col in cols:
                    val = r.get(col)
                    if isinstance(val, (dict, list)):
                        val = json.dumps(val, ensure_ascii=False)
                    elif isinstance(val, bool):
                        val = 1 if val else 0
                    row_vals.append(val)
                batch_values.append(row_vals)

            cursor.executemany(insert_sql, batch_values)
            conn.commit()

    def generate_postgres_migration_sql(self, table_name: str, records: List[Dict[str, Any]], primary_keys: List[str]) -> Tuple[str, str]:
        """
        Generates:
        1. Full standard PostgreSQL DDL + batch insert script.
        2. PostgreSQL incremental ON CONFLICT DO UPDATE upsert script.
        """
        if not records:
            return "", ""

        # Collect columns and sample types
        all_keys = set()
        for r in records:
            all_keys.update(r.keys())
        cols = sorted(list(all_keys))

        valid_pks = [pk for pk in primary_keys if pk in cols]
        if not valid_pks and "id" in cols:
            valid_pks = ["id"]

        # Postgres Column definitions
        col_defs = []
        col_type_map = {}
        for col in cols:
            if col in KNOWN_BOOLEAN_COLS:
                col_type = "BOOLEAN"
            else:
                sample_vals = [r.get(col) for r in records if r.get(col) is not None]
                sample = sample_vals[0] if sample_vals else None
                
                if isinstance(sample, bool):
                    col_type = "BOOLEAN"
                elif isinstance(sample, int):
                    col_type = "BIGINT" if abs(sample) > 2147483647 else "INTEGER"
                elif isinstance(sample, float):
                    col_type = "NUMERIC"
                elif isinstance(sample, (dict, list)):
                    col_type = "JSONB"
                elif isinstance(sample, str) and ("_at" in col or "date" in col) and len(sample) >= 10:
                    col_type = "TIMESTAMPTZ"
                else:
                    col_type = "TEXT"

            col_type_map[col] = col_type
            col_defs.append(f'    "{col}" {col_type}')

        pk_quoted = ', '.join([f'"{k}"' for k in valid_pks])
        pk_clause = f",\n    PRIMARY KEY ({pk_quoted})" if valid_pks else ""
        col_defs_str = ',\n'.join(col_defs)

        ddl = f"""-- Table: {table_name}
DROP TABLE IF EXISTS "{table_name}" CASCADE;
CREATE TABLE IF NOT EXISTS "{table_name}" (
{col_defs_str}{pk_clause}
);
"""

        # Generate Upsert and Full Insert statements in chunks
        chunk_size = 250
        full_insert_statements = []
        upsert_statements = []

        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            value_rows = []
            for r in chunk:
                row_vals = [sanitize_sql_value(r.get(col), col_name=col, col_type=col_type_map.get(col, "")) for col in cols]
                value_rows.append(f"({', '.join(row_vals)})")
            
            cols_joined = ", ".join([f'"{c}"' for c in cols])
            values_block = ",\n".join(value_rows)

            # Full insert
            full_sql = f"INSERT INTO \"{table_name}\" ({cols_joined})\nVALUES\n{values_block}\nON CONFLICT DO NOTHING;"
            full_insert_statements.append(full_sql)

            # Upsert
            if valid_pks:
                update_cols = [c for c in cols if c not in valid_pks]
                if update_cols:
                    updates_block = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in update_cols])
                    conflict_target = ", ".join([f'"{k}"' for k in valid_pks])
                    upsert_sql = f"INSERT INTO \"{table_name}\" ({cols_joined})\nVALUES\n{values_block}\nON CONFLICT ({conflict_target}) DO UPDATE SET {updates_block};"
                else:
                    upsert_sql = full_sql
            else:
                upsert_sql = full_sql
            
            upsert_statements.append(upsert_sql)

        full_table_sql = ddl + "\n" + "\n\n".join(full_insert_statements) + "\n"
        upsert_table_sql = ddl + "\n" + "\n\n".join(upsert_statements) + "\n"

        return full_table_sql, upsert_table_sql

    def _fetch_table_delta(self, client: Client, table_name: str, state: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
        """
        Fetches updated records from Supabase using delta high-water marks.
        Falls back gracefully if timestamp columns don't exist.
        """
        last_updated_at = state.get("last_updated_at")
        last_created_at = state.get("last_created_at")
        max_id = state.get("max_id", 0)

        # 1. Try delta by updated_at if available
        if last_updated_at:
            try:
                res = client.table(table_name).select("*").gt("updated_at", last_updated_at).order("updated_at").limit(1000).execute()
                if res.data is not None:
                    return res.data, "delta_updated_at"
            except Exception as e:
                logger.debug(f"Table '{table_name}' does not support gt(updated_at): {e}")

        # 2. Try delta by created_at
        if last_created_at:
            try:
                res = client.table(table_name).select("*").gt("created_at", last_created_at).order("created_at").limit(1000).execute()
                if res.data is not None:
                    return res.data, "delta_created_at"
            except Exception as e:
                logger.debug(f"Table '{table_name}' does not support gt(created_at): {e}")

        # 3. Try delta by max(id) if id is integer
        if max_id and isinstance(max_id, int) and max_id > 0:
            try:
                res = client.table(table_name).select("*").gt("id", max_id).order("id").limit(1000).execute()
                if res.data is not None:
                    return res.data, "delta_max_id"
            except Exception as e:
                logger.debug(f"Table '{table_name}' does not support gt(id): {e}")

        # 4. Fetch full table
        try:
            # Paginate if needed
            all_records = []
            page_size = 1000
            start = 0
            while True:
                res = client.table(table_name).select("*").range(start, start + page_size - 1).execute()
                data = res.data or []
                all_records.extend(data)
                if len(data) < page_size:
                    break
                start += page_size
            return all_records, "full"
        except Exception as e:
            err_str = str(e)
            if "PGRST205" in err_str or "Could not find the table" in err_str or ("relation" in err_str and "does not exist" in err_str):
                logger.debug(f"Table '{table_name}' is not present on remote Supabase: {e}")
                return [], "not_found_on_remote"
            logger.error(f"Failed to fetch records for table '{table_name}': {e}")
            raise

    def _sync_assets_and_files(self):
        """Mirrors local configurations, branding, and logos to both replica locations."""
        base_dir = get_base_dir()
        assets_to_copy = [
            os.path.join(base_dir, "hospital_logo.png"),
            os.path.join(base_dir, "logo_icon.ico"),
            os.path.join(base_dir, "all_tests.json"),
            os.path.join(base_dir, "app_config.py")
        ]

        for loc in [self.location_1, self.location_2]:
            if not loc:
                continue
            dest_assets_dir = os.path.join(loc, "assets")
            try:
                os.makedirs(dest_assets_dir, exist_ok=True)
                for src in assets_to_copy:
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(dest_assets_dir, os.path.basename(src)))
            except Exception as e:
                logger.debug(f"Could not copy assets to {loc}: {e}")

    def perform_sync(self, force_full: bool = False) -> Dict[str, Any]:
        """
        Executes a complete replication cycle across all tables.
        Updates SQLite DBs, JSON snapshots, and PostgreSQL SQL dumps in both locations.
        """
        with self._lock:
            self.is_syncing = True
            start_time = time.time()
            sync_type = "full" if force_full else "delta"
            tables_summary = {}
            total_records_updated = 0
            errors = []

            # Check if periodic full reconcile is due
            now = time.time()
            if not force_full and (now - self.last_full_reconcile_time) >= self.full_reconcile_interval:
                force_full = True
                sync_type = "periodic_full"

            try:
                client = self.get_client()
                
                # Check for dynamic tables if possible
                for table_name in self.tables:
                    state = self.tables_state.get(table_name, {})
                    pks = TABLE_PRIMARY_KEYS.get(table_name, ["id"])

                    try:
                        if force_full or not state.get("row_count"):
                            # Full table fetch
                            records, fetch_mode = self._fetch_table_delta(client, table_name, {})
                        else:
                            # Delta fetch
                            records, fetch_mode = self._fetch_table_delta(client, table_name, state)

                        if fetch_mode == "not_found_on_remote":
                            state["status"] = "not_found_on_remote"
                            state["row_count"] = 0
                            self.tables_state[table_name] = state
                            tables_summary[table_name] = {
                                "row_count": 0,
                                "updated_records": 0,
                                "fetch_mode": fetch_mode,
                                "last_updated_at": None,
                                "status": "not_found_on_remote"
                            }
                            continue

                        # Update state with latest high-water marks
                        if records:
                            total_records_updated += len(records)
                            for r in records:
                                if "updated_at" in r and r["updated_at"]:
                                    if not state.get("last_updated_at") or r["updated_at"] > state["last_updated_at"]:
                                        state["last_updated_at"] = r["updated_at"]
                                if "created_at" in r and r["created_at"]:
                                    if not state.get("last_created_at") or r["created_at"] > state["last_created_at"]:
                                        state["last_created_at"] = r["created_at"]
                                if "id" in r and isinstance(r["id"], int):
                                    if r["id"] > state.get("max_id", 0):
                                        state["max_id"] = r["id"]

                        # Always write/update SQLite at both locations
                        for loc in [self.location_1, self.location_2]:
                            if not loc:
                                continue
                            try:
                                if records:
                                    self._sync_sqlite_table(loc, table_name, records, pks)
                            except Exception as loc_err:
                                logger.warning(f"Error syncing SQLite for table '{table_name}' at {loc}: {loc_err}")

                        # Get exact row count from SQLite
                        loc1_conn = self._get_sqlite_conn(self.location_1)
                        try:
                            c = loc1_conn.cursor()
                            c.execute(f"SELECT COUNT(*) FROM {table_name}")
                            current_count = c.fetchone()[0]
                            state["row_count"] = current_count
                        except Exception:
                            current_count = len(records) if force_full else state.get("row_count", 0)
                            state["row_count"] = current_count
                        finally:
                            loc1_conn.close()

                        # Export full table JSON and SQL if full sync or records updated
                        if force_full or records:
                            # Read all rows from local replica SQLite for pure clean export
                            all_rows = []
                            try:
                                conn = self._get_sqlite_conn(self.location_1)
                                cur = conn.cursor()
                                cur.execute(f"SELECT * FROM {table_name}")
                                col_names = [d[0] for d in cur.description]
                                for row in cur.fetchall():
                                    row_dict = {}
                                    for idx, col in enumerate(col_names):
                                        val = row[idx]
                                        # Parse JSON strings if applicable
                                        if isinstance(val, str) and (val.startswith("{") or val.startswith("[")):
                                            try:
                                                val = json.loads(val)
                                            except Exception:
                                                pass
                                        row_dict[col] = val
                                    all_rows.append(row_dict)
                                conn.close()
                            except Exception as e:
                                all_rows = records

                            # Write JSON snapshot & Postgres SQL to both locations
                            full_pg_sql, upsert_pg_sql = self.generate_postgres_migration_sql(table_name, all_rows, pks)

                            for loc in [self.location_1, self.location_2]:
                                if not loc:
                                    continue
                                try:
                                    # JSON snapshot
                                    json_path = os.path.join(loc, "tables", f"{table_name}.json")
                                    tmp_json = json_path + ".tmp"
                                    with open(tmp_json, "w", encoding="utf-8") as jf:
                                        json.dump(all_rows, jf, indent=2, ensure_ascii=False)
                                    os.replace(tmp_json, json_path)

                                    # Table SQL files
                                    table_sql_path = os.path.join(loc, "sql", f"{table_name}_postgres.sql")
                                    with open(table_sql_path, "w", encoding="utf-8") as sf:
                                        sf.write(full_pg_sql)
                                except Exception as write_err:
                                    logger.warning(f"Error saving snapshot for '{table_name}' at {loc}: {write_err}")

                        state["last_sync_time"] = datetime.now(timezone.utc).isoformat()
                        state["status"] = "healthy"
                        self.tables_state[table_name] = state

                        # Automatically push delta records directly to Secondary Supabase Cloud
                        if self.secondary_supabase_url and self.secondary_supabase_key and records and not getattr(self, '_secondary_push_paused', False):
                            try:
                                sec_client = self.get_secondary_client()
                                if sec_client:
                                    cleaned_records = []
                                    for r in records:
                                        rec_copy = dict(r)
                                        for k, v in rec_copy.items():
                                            if k in KNOWN_BOOLEAN_COLS:
                                                if v is not None:
                                                    rec_copy[k] = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "t", "yes")
                                        cleaned_records.append(rec_copy)

                                    for i in range(0, len(cleaned_records), 50):
                                        chunk = cleaned_records[i:i + 50]
                                        sec_client.table(table_name).upsert(chunk).execute()
                                    self.secondary_records_pushed += len(records)
                                    self.secondary_last_push_time = datetime.now(timezone.utc).isoformat()
                                    self.secondary_sync_status = "active_synced"
                            except Exception as sec_err:
                                sec_err_str = str(sec_err)
                                if "401" in sec_err_str or "Unauthorized" in sec_err_str or "JWT" in sec_err_str:
                                    self.secondary_sync_status = "needs_service_role_key"
                                    self._secondary_push_paused = True
                                    logger.warning("Secondary Supabase Cloud push paused: SECONDARY_SUPABASE_KEY is an 'anon' key or lacks service_role write permissions.")
                                elif "PGRST205" in sec_err_str or "schema cache" in sec_err_str or "400" in sec_err_str:
                                    self.secondary_sync_status = "needs_schema_setup"
                                else:
                                    self.secondary_sync_status = f"notice: {sec_err_str[:60]}"
                                    logger.debug(f"Secondary push note for '{table_name}': {sec_err}")

                        tables_summary[table_name] = {
                            "row_count": state.get("row_count", 0),
                            "updated_records": len(records),
                            "fetch_mode": fetch_mode,
                            "last_updated_at": state.get("last_updated_at"),
                            "status": "healthy"
                        }

                    except Exception as tbl_err:
                        logger.error(f"Error syncing table '{table_name}': {tbl_err}")
                        state["status"] = f"error: {str(tbl_err)}"
                        self.tables_state[table_name] = state
                        errors.append(f"{table_name}: {str(tbl_err)}")

                # Mirror Assets
                self._sync_assets_and_files()

                # Generate Master Migration SQLs (`migration_postgres_full.sql`, `migration_postgres_upsert.sql`, `migration_sqlite_full.sql`)
                self._generate_master_migration_scripts()

                # Update replication metrics
                duration_ms = int((time.time() - start_time) * 1000)
                self.last_sync_time = datetime.now(timezone.utc).isoformat()
                self.last_sync_type = sync_type
                self.last_sync_duration_ms = duration_ms
                self.total_sync_cycles += 1
                self.consecutive_errors = 0
                self.last_error = None
                if force_full:
                    self.last_full_reconcile_time = now

                # Persist sync state & manifest
                self._save_sync_state()
                self._write_manifest(duration_ms, total_records_updated)

                logger.info(f"Replication cycle ({sync_type}) complete in {duration_ms}ms. Total updated: {total_records_updated} rows across {len(self.tables)} tables.")

                return {
                    "status": "success",
                    "sync_type": sync_type,
                    "duration_ms": duration_ms,
                    "records_updated": total_records_updated,
                    "tables": tables_summary,
                    "errors": errors
                }

            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.consecutive_errors += 1
                self.last_error = str(e)
                logger.error(f"Replication cycle failed: {e}")
                return {
                    "status": "error",
                    "sync_type": sync_type,
                    "duration_ms": duration_ms,
                    "error": str(e),
                    "errors": errors
                }
            finally:
                self.is_syncing = False

    def _generate_master_migration_scripts(self):
        """Combines all table SQLs into master migration files at both replica locations."""
        for loc in [self.location_1, self.location_2]:
            if not loc:
                continue
            try:
                full_pg_lines = [
                    "-- ========================================================",
                    "-- LabFlow Master PostgreSQL Migration & Disaster Recovery",
                    f"-- Generated at: {datetime.now(timezone.utc).isoformat()}",
                    "-- Destination: Any PostgreSQL (Neon, Supabase, Railway, RDS)",
                    "-- ========================================================\n",
                    "BEGIN;\n"
                ]

                upsert_pg_lines = [
                    "-- ========================================================",
                    "-- LabFlow Master PostgreSQL Incremental Upsert Script",
                    f"-- Generated at: {datetime.now(timezone.utc).isoformat()}",
                    "-- Safely updates secondary running database without drop",
                    "-- ========================================================\n",
                    "BEGIN;\n"
                ]

                sql_dir = os.path.join(loc, "sql")
                for tbl in self.tables:
                    tbl_sql_file = os.path.join(sql_dir, f"{tbl}_postgres.sql")
                    if os.path.exists(tbl_sql_file):
                        with open(tbl_sql_file, "r", encoding="utf-8") as f:
                            content = f.read()
                            full_pg_lines.append(content)
                            upsert_pg_lines.append(content)

                grant_sql = "\n-- Grant permissions to Supabase roles\nGRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role;\nGRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role;\n"
                full_pg_lines.append(grant_sql)
                upsert_pg_lines.append(grant_sql)

                full_pg_lines.append("\nCOMMIT;\n")
                upsert_pg_lines.append("\nCOMMIT;\n")

                # Write master files
                with open(os.path.join(loc, "sql", "migration_postgres_full.sql"), "w", encoding="utf-8") as f:
                    f.write("\n".join(full_pg_lines))

                with open(os.path.join(loc, "sql", "migration_postgres_upsert.sql"), "w", encoding="utf-8") as f:
                    f.write("\n".join(upsert_pg_lines))

                # SQLite master dump
                sqlite_dump_path = os.path.join(loc, "sql", "migration_sqlite_full.sql")
                db_path = os.path.join(loc, "database", "labflow_replica.db")
                if os.path.exists(db_path):
                    with self._get_sqlite_conn(loc) as conn:
                        with open(sqlite_dump_path, "w", encoding="utf-8") as dump_file:
                            for line in conn.iterdump():
                                dump_file.write(f"{line}\n")

            except Exception as e:
                logger.warning(f"Could not generate master migration scripts for {loc}: {e}")

    def _write_manifest(self, duration_ms: int, records_updated: int):
        """Generates a rich replica_manifest.json at both locations."""
        manifest = {
            "app_name": "LabFlow",
            "version": "1.0.0",
            "manifest_generated_at": datetime.now(timezone.utc).isoformat(),
            "last_sync_type": self.last_sync_type,
            "last_sync_duration_ms": duration_ms,
            "total_records_updated": records_updated,
            "locations": {
                "location_1": {
                    "path": self.location_1,
                    "exists": os.path.exists(self.location_1),
                    "free_mb": get_disk_free_mb(self.location_1)
                },
                "location_2": {
                    "path": self.location_2,
                    "exists": os.path.exists(self.location_2),
                    "free_mb": get_disk_free_mb(self.location_2)
                }
            },
            "tables": self.tables_state,
            "export_files": [
                "database/labflow_replica.db",
                "sql/migration_postgres_full.sql",
                "sql/migration_postgres_upsert.sql",
                "sql/migration_sqlite_full.sql",
                "replica_manifest.json"
            ]
        }

        for loc in [self.location_1, self.location_2]:
            if not loc:
                continue
            try:
                manifest_path = os.path.join(loc, "replica_manifest.json")
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)
            except Exception as e:
                logger.warning(f"Could not write manifest to {loc}: {e}")

    def start_background_worker(self):
        """Starts the continuous background replication thread."""
        if self.is_running:
            logger.info("Replica background worker is already running.")
            return

        self.is_running = True
        self.stop_event.clear()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="SupabaseReplicaWorker")
        self.worker_thread.start()
        logger.info(f"Started continuous Supabase replica worker (polling interval: {self.poll_interval}s)")

    def stop_background_worker(self):
        """Stops the background worker thread gracefully."""
        if not self.is_running:
            return
        logger.info("Stopping Supabase replica worker...")
        self.stop_event.set()
        self.is_running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
        logger.info("Supabase replica worker stopped.")

    def _worker_loop(self):
        """Continuous polling loop with exponential backoff on connection errors."""
        # Initial run: force full reconcile on boot
        logger.info("Running initial full snapshot replication...")
        self.perform_sync(force_full=True)

        backoff = 1.0
        while not self.stop_event.is_set():
            # Wait for poll interval or until signaled
            if self.stop_event.wait(timeout=self.poll_interval):
                break

            try:
                result = self.perform_sync(force_full=False)
                if result.get("status") == "success":
                    backoff = 1.0
                else:
                    backoff = min(backoff * 1.5, 60.0)
                    time.sleep(backoff)
            except Exception as e:
                logger.error(f"Unhandled error in replica worker loop: {e}")
                backoff = min(backoff * 2.0, 60.0)
                time.sleep(backoff)

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive real-time status of the replication engine."""
        return {
            "is_running": self.is_running,
            "is_syncing": self.is_syncing,
            "last_sync_time": self.last_sync_time,
            "last_sync_type": self.last_sync_type,
            "last_sync_duration_ms": self.last_sync_duration_ms,
            "total_sync_cycles": self.total_sync_cycles,
            "consecutive_errors": self.consecutive_errors,
            "last_error": self.last_error,
            "poll_interval_seconds": self.poll_interval,
            "full_reconcile_interval_seconds": self.full_reconcile_interval,
            "locations": {
                "location_1": {
                    "path": self.location_1,
                    "exists": os.path.exists(self.location_1),
                    "free_mb": get_disk_free_mb(self.location_1),
                    "db_size_bytes": os.path.getsize(os.path.join(self.location_1, "database", "labflow_replica.db")) if os.path.exists(os.path.join(self.location_1, "database", "labflow_replica.db")) else 0
                },
                "location_2": {
                    "path": self.location_2,
                    "exists": os.path.exists(self.location_2),
                    "free_mb": get_disk_free_mb(self.location_2),
                    "db_size_bytes": os.path.getsize(os.path.join(self.location_2, "database", "labflow_replica.db")) if os.path.exists(os.path.join(self.location_2, "database", "labflow_replica.db")) else 0
                }
            },
            "tables": self.tables_state
        }


# Global singleton instance for app-wide access
_engine_instance: Optional[SupabaseReplicaEngine] = None
_engine_lock = threading.Lock()


def get_replica_engine() -> SupabaseReplicaEngine:
    """Returns the singleton SupabaseReplicaEngine instance."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = SupabaseReplicaEngine()
        return _engine_instance
