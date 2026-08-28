import sqlite3
import os
import json
from contextlib import contextmanager

import sys

if getattr(sys, 'frozen', False):
    # PyInstaller exe: store the DB next to the executable so data persists
    _DB_DIR = os.path.dirname(sys.executable)
else:
    # Dev mode: store DB inside the offline/ directory
    _DB_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(_DB_DIR, "labflow_offline.db")

@contextmanager
def get_db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL mode allows concurrent reads during writes — prevents "database is locked"
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        
        # 1. patients table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            mr_no TEXT UNIQUE NOT NULL,
            salutation TEXT,
            patient_name TEXT,
            relation TEXT,
            relation_name TEXT,
            mobile TEXT,
            gender TEXT,
            age INTEGER,
            cnic TEXT,
            patient_token INTEGER,
            shift TEXT,
            user TEXT,
            user_id INTEGER,
            pwd TEXT,
            synced INTEGER DEFAULT 0,
            online_mr INTEGER,
            sync_error TEXT
        )
        """)
        
        # 2. test_results_all table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_results_all (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mr_no TEXT NOT NULL,
            patient_name TEXT,
            category TEXT,
            test_name TEXT,
            test_values TEXT, -- JSON string
            status TEXT DEFAULT 'Pending',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            delete_status INTEGER DEFAULT 0,
            person_deleting TEXT,
            remarks TEXT,
            synced INTEGER DEFAULT 0,
            online_id INTEGER,
            FOREIGN KEY (mr_no) REFERENCES patients(mr_no)
        )
        """)
        
        # 3. tests table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY,
            created_at TEXT,
            name TEXT,
            unit TEXT,
            normal_min TEXT,
            normal_max TEXT,
            status INTEGER,
            category TEXT
        )
        """)
        
        # 4. test_groups table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_groups (
            id INTEGER PRIMARY KEY,
            group_name TEXT,
            component_ids TEXT, -- JSON list string
            created_at TEXT,
            status INTEGER,
            category TEXT
        )
        """)
        
        # 5. shift table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shift (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            shift TEXT UNIQUE NOT NULL
        )
        """)
        
        # 6. users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            email TEXT UNIQUE NOT NULL,
            pwd TEXT NOT NULL,
            name TEXT,
            is_active INTEGER,
            permissions TEXT, -- JSON string
            default_shift_id INTEGER
        )
        """)
        
        # 7. remarks table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS remarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remark_text TEXT,
            test_name TEXT,
            category TEXT,
            usage_count INTEGER DEFAULT 0,
            sort_order INTEGER,
            is_active INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
        """)
        
        # 8. invoice_settings table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoice_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_name TEXT,
            developed_by TEXT,
            developed_by_url TEXT,
            online_report_url TEXT,
            printer_width TEXT,
            logo_path TEXT,
            qr_code_path TEXT,
            is_active INTEGER,
            updated_at TEXT
        )
        """)
        
        # 9. print_settings table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS print_settings (
            id INTEGER PRIMARY KEY,
            category_font_size INTEGER,
            group_font_size INTEGER,
            test_name_font_size INTEGER,
            result_font_size INTEGER,
            patient_info_font_size INTEGER,
            patient_info_label_font_size INTEGER,
            footer_font_size INTEGER,
            page_top_margin REAL,
            page_right_margin REAL,
            page_bottom_margin REAL,
            page_left_margin REAL,
            header_height REAL,
            header_bottom_margin REAL,
            patient_info_padding_vertical REAL,
            patient_info_padding_horizontal REAL,
            patient_info_min_height REAL,
            patient_info_row_gap REAL,
            patient_info_label_width REAL,
            patient_info_bottom_margin REAL,
            table_header_padding_vertical REAL,
            table_header_padding_horizontal REAL,
            table_cell_padding_vertical REAL,
            table_cell_padding_horizontal REAL,
            category_padding_top REAL,
            category_padding_bottom REAL,
            category_border_width REAL,
            group_padding_top REAL,
            group_padding_bottom REAL,
            group_padding_left REAL,
            footer_margin_top REAL,
            footer_padding_top REAL,
            signature_block_min_width REAL,
            primary_color TEXT,
            secondary_color TEXT,
            border_color TEXT,
            bg_light TEXT,
            text_main TEXT,
            text_muted TEXT,
            is_active INTEGER,
            created_at TEXT,
            updated_at TEXT,
            created_by TEXT,
            updated_by TEXT,
            display_verified_by INTEGER,
            display_pathologist_signature INTEGER,
            footer_line1 TEXT,
            footer_line2 TEXT,
            footer_line3 TEXT,
            patient_info_border_radius REAL,
            col_test_name_width REAL,
            col_test_name_align TEXT,
            col_result_width REAL,
            col_result_align TEXT,
            col_unit_width REAL,
            col_unit_align TEXT,
            col_range_width REAL,
            col_range_align TEXT,
            hidden_group_titles TEXT
        )
        """)
        
        # Ensure hidden_group_titles column exists on existing DBs
        try:
            cursor.execute("ALTER TABLE print_settings ADD COLUMN hidden_group_titles TEXT")
        except Exception:
            pass

        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_patients_mr_no ON patients(mr_no)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_test_results_mr_no ON test_results_all(mr_no)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_patients_synced ON patients(synced)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_test_results_synced ON test_results_all(synced)")

        # 10. mr_sync_log — record of every offline→Supabase push
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS mr_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offline_mr TEXT NOT NULL,
            online_mr TEXT,
            patient_name TEXT,
            synced_at TEXT DEFAULT (datetime('now', 'localtime')),
            synced_by TEXT DEFAULT 'Admin',
            status TEXT DEFAULT 'synced',
            tests_synced INTEGER DEFAULT 0,
            error_message TEXT
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sync_log_offline_mr ON mr_sync_log(offline_mr)")

        # 11. fitness_patients table for offline storage
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fitness_patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            patient_name TEXT,
            gender TEXT,
            relation_type TEXT,
            relation_name TEXT,
            report_date TEXT,
            mr_no TEXT,
            hb TEXT,
            wbc TEXT,
            neut TEXT,
            lymph TEXT,
            mono TEXT,
            eosino TEXT,
            plt TEXT,
            hiv TEXT,
            hbsag TEXT,
            hcv TEXT,
            vdrl TEXT,
            created_by TEXT,
            synced INTEGER DEFAULT 0
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fitness_patients_mr_no ON fitness_patients(mr_no)")

        # --- Migration: add columns to existing databases that are missing them ---
        existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(mr_sync_log)").fetchall()}
        if "synced_at" not in existing_cols:
            cursor.execute(
                "ALTER TABLE mr_sync_log ADD COLUMN synced_at TEXT"
            )
        if "synced_by" not in existing_cols:
            cursor.execute("ALTER TABLE mr_sync_log ADD COLUMN synced_by TEXT DEFAULT 'Admin'")
        if "status" not in existing_cols:
            cursor.execute("ALTER TABLE mr_sync_log ADD COLUMN status TEXT DEFAULT 'synced'")
        if "tests_synced" not in existing_cols:
            cursor.execute("ALTER TABLE mr_sync_log ADD COLUMN tests_synced INTEGER DEFAULT 0")
        if "error_message" not in existing_cols:
            cursor.execute("ALTER TABLE mr_sync_log ADD COLUMN error_message TEXT")

        # Migration: add online_mr column to patients if missing
        patient_cols = {row[1] for row in cursor.execute("PRAGMA table_info(patients)").fetchall()}
        if "online_mr" not in patient_cols:
            cursor.execute("ALTER TABLE patients ADD COLUMN online_mr TEXT")
        if "sync_error" not in patient_cols:
            cursor.execute("ALTER TABLE patients ADD COLUMN sync_error TEXT")
        if "synced" not in patient_cols:
            cursor.execute("ALTER TABLE patients ADD COLUMN synced INTEGER DEFAULT 0")

        # 11. audit_trail — local tamper-resistant record of user actions (updates, prints, registrations)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_trail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mr_no TEXT NOT NULL,
            patient_name TEXT,
            action TEXT NOT NULL,
            user_name TEXT NOT NULL,
            user_id TEXT,
            details TEXT,
            pc_name TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_mr ON audit_trail(mr_no)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_trail(user_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_trail(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_trail(action)")


def insert_audit_log(
    mr_no: str,
    *,
    patient_name: str | None = None,
    action: str = "UPDATE_RESULT",
    user_name: str = "Staff",
    user_id: str | None = None,
    details: str | None = None,
    pc_name: str | None = None,
):
    """
    Insert a tamper-resistant local audit log entry with sub-millisecond WAL performance.
    """
    if not pc_name:
        try:
            import platform, getpass
            pc_name = f"{platform.node()} ({getpass.getuser()})"
        except Exception:
            pc_name = "Lab-Terminal"

    with get_db_conn() as conn:
        cursor = conn.cursor()
        print_count = 1
        if action == "PRINT":
            cursor.execute("SELECT COUNT(*) FROM audit_trail WHERE mr_no = ? AND action = 'PRINT'", (str(mr_no or "").strip(),))
            prior_row = cursor.fetchone()
            prior_prints = prior_row[0] if prior_row else 0
            print_count = prior_prints + 1
            copy_label = "Copy #1 (Original)" if print_count == 1 else f"Copy #{print_count} (Re-print)"
            details = f"[{copy_label}] {details or 'Printed report'}"

        cursor.execute(
            """
            INSERT INTO audit_trail
                (mr_no, patient_name, action, user_name, user_id, details, pc_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            (
                str(mr_no or "").strip(),
                patient_name,
                action,
                user_name or "Staff",
                str(user_id) if user_id else None,
                details,
                pc_name,
            ),
        )
        return print_count


def list_audit_trail(
    limit: int = 200,
    search: str | None = None,
    mr_no: str | None = None,
    user_name: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """
    Fetch audit log entries with instant indexed search by MR number, user, or date.
    """
    with get_db_conn() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM audit_trail WHERE 1=1"
        params: list = []

        if mr_no:
            query += " AND (mr_no = ? OR mr_no LIKE ?)"
            params.extend([mr_no.strip(), f"%{mr_no.strip()}%"])

        if user_name and user_name.lower() != "all":
            query += " AND LOWER(user_name) = ?"
            params.append(user_name.strip().lower())

        if action and action.lower() != "all":
            query += " AND UPPER(action) = ?"
            params.append(action.strip().upper())

        if date_from:
            query += " AND DATE(created_at) >= ?"
            params.append(date_from.strip())

        if date_to:
            query += " AND DATE(created_at) <= ?"
            params.append(date_to.strip())

        if search:
            s = f"%{search.strip()}%"
            query += " AND (mr_no LIKE ? OR patient_name LIKE ? OR user_name LIKE ? OR details LIKE ? OR pc_name LIKE ?)"
            params.extend([s, s, s, s, s])

        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(limit, 1000))

        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def get_next_table_id(table: str) -> int:
    """Return next integer primary key for tables that use explicit IDs."""
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}")
        row = cursor.fetchone()
        return int(row[0] if row else 1)


def insert_mr_sync_log(
    offline_mr: str,
    *,
    online_mr: str | None = None,
    patient_name: str | None = None,
    synced_by: str = "Admin",
    status: str = "synced",
    tests_synced: int = 0,
    error_message: str | None = None,
):
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO mr_sync_log
                (offline_mr, online_mr, patient_name, synced_by, status, tests_synced, error_message, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            (
                offline_mr,
                online_mr,
                patient_name,
                synced_by,
                status,
                tests_synced,
                error_message,
            ),
        )
        return cursor.lastrowid


def list_mr_sync_log(limit: int = 200, search: str | None = None):
    with get_db_conn() as conn:
        cursor = conn.cursor()
        
        # Dynamically check for older columns to support both old and new database schemas
        cursor.execute("PRAGMA table_info(mr_sync_log)")
        columns = [row["name"] for row in cursor.fetchall()]
        
        query = "SELECT * FROM mr_sync_log WHERE 1=1"
        params: list = []
        if search:
            like = f"%{search.strip()}%"
            query += " AND (offline_mr LIKE ? OR online_mr LIKE ? OR patient_name LIKE ?)"
            params.extend([like, like, like])
            
        if "pushed_at" in columns:
            query += " ORDER BY COALESCE(synced_at, pushed_at, '') DESC, id DESC LIMIT ?"
        else:
            query += " ORDER BY COALESCE(synced_at, '') DESC, id DESC LIMIT ?"
            
        params.append(limit)
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        # Normalise: expose synced_at even for old rows that only have pushed_at
        for row in rows:
            if not row.get("synced_at") and row.get("pushed_at"):
                row["synced_at"] = row["pushed_at"]
            if not row.get("synced_by") and row.get("pushed_by"):
                row["synced_by"] = row["pushed_by"]
            if not row.get("status") and row.get("push_status"):
                row["status"] = row["push_status"]
        return rows


def upsert_tests_from_supabase(rows: list[dict]):
    """Bulk upsert tests from Supabase into local SQLite tests table."""
    if not rows:
        return
    with get_db_conn() as conn:
        cursor = conn.cursor()
        for row in rows:
            cursor.execute("""
                INSERT INTO tests (id, created_at, name, unit, normal_min, normal_max, status, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    unit=excluded.unit,
                    normal_min=excluded.normal_min,
                    normal_max=excluded.normal_max,
                    status=excluded.status,
                    category=excluded.category
            """, (
                row.get("id"), row.get("created_at"), row.get("name"),
                row.get("unit"), row.get("normal_min"), row.get("normal_max"),
                1 if row.get("status", True) else 0, row.get("category")
            ))


def upsert_test_groups_from_supabase(rows: list[dict]):
    """Bulk upsert test_groups from Supabase into local SQLite."""
    if not rows:
        return
    with get_db_conn() as conn:
        cursor = conn.cursor()
        for row in rows:
            component_ids = row.get("component_ids") or []
            if isinstance(component_ids, list):
                import json
                component_ids = json.dumps(component_ids)
            cursor.execute("""
                INSERT INTO test_groups (id, group_name, component_ids, created_at, status, category)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    group_name=excluded.group_name,
                    component_ids=excluded.component_ids,
                    status=excluded.status,
                    category=excluded.category
            """, (
                row.get("id"), row.get("group_name"), component_ids,
                row.get("created_at"), 1 if row.get("status", True) else 0,
                row.get("category")
            ))


def upsert_shifts_from_supabase(rows: list[dict]):
    """Bulk upsert shifts from Supabase into local SQLite."""
    if not rows:
        return
    with get_db_conn() as conn:
        cursor = conn.cursor()
        for row in rows:
            cursor.execute("""
                INSERT INTO shift (id, created_at, shift)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET shift=excluded.shift
            """, (row.get("id"), row.get("created_at"), row.get("shift")))


def upsert_users_from_supabase(rows: list[dict]):
    """Bulk upsert active users from Supabase into local SQLite."""
    import json as _json
    if not rows:
        return
    with get_db_conn() as conn:
        cursor = conn.cursor()
        for row in rows:
            perms = row.get("permissions") or {}
            if isinstance(perms, dict):
                perms = _json.dumps(perms)
            cursor.execute("""
                INSERT INTO users (id, created_at, email, pwd, name, is_active, permissions, default_shift_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    name=excluded.name,
                    is_active=excluded.is_active,
                    permissions=excluded.permissions,
                    default_shift_id=excluded.default_shift_id
            """, (
                row.get("id"), row.get("created_at"), row.get("email"),
                row.get("pwd", ""), row.get("name"),
                1 if row.get("is_active", True) else 0,
                perms, row.get("default_shift_id")
            ))


def upsert_remarks_from_supabase(rows: list[dict]):
    """Bulk upsert remarks from Supabase into local SQLite."""
    if not rows:
        return
    with get_db_conn() as conn:
        cursor = conn.cursor()
        for row in rows:
            cursor.execute("""
                INSERT INTO remarks (id, remark_text, test_name, category, usage_count, sort_order, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    remark_text=excluded.remark_text,
                    test_name=excluded.test_name,
                    category=excluded.category,
                    usage_count=excluded.usage_count,
                    sort_order=excluded.sort_order,
                    is_active=excluded.is_active,
                    updated_at=excluded.updated_at
            """, (
                row.get("id"), row.get("remark_text"), row.get("test_name"),
                row.get("category"), row.get("usage_count", 0), row.get("sort_order", 0),
                1 if row.get("is_active", True) else 0,
                row.get("created_at"), row.get("updated_at")
            ))


def upsert_invoice_settings_from_supabase(row: dict):
    """Upsert invoice_settings from Supabase into local SQLite."""
    if not row:
        return
    with get_db_conn() as conn:
        cursor = conn.cursor()
        # Clear existing and insert fresh
        cursor.execute("DELETE FROM invoice_settings WHERE is_active = 1")
        cursor.execute("""
            INSERT INTO invoice_settings
                (hospital_name, developed_by, developed_by_url, online_report_url,
                 printer_width, logo_path, qr_code_path, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now','localtime'))
        """, (
            row.get("hospital_name"), row.get("developed_by"),
            row.get("developed_by_url"), row.get("online_report_url"),
            row.get("printer_width"), row.get("logo_path"), row.get("qr_code_path")
        ))


def insert_fitness_patient(item: dict) -> dict:
    """Insert or update a fitness patient record into local SQLite database."""
    mr_no = item.get("mr_no")
    with get_db_conn() as conn:
        cursor = conn.cursor()
        existing_id = None
        if mr_no and str(mr_no).strip():
            cursor.execute("SELECT id FROM fitness_patients WHERE mr_no = ?", (str(mr_no).strip(),))
            row = cursor.fetchone()
            if row:
                existing_id = row["id"]

        if existing_id:
            cursor.execute("""
                UPDATE fitness_patients SET
                    patient_name = ?, gender = ?, relation_type = ?, relation_name = ?,
                    report_date = ?, hb = ?, wbc = ?, neut = ?, lymph = ?, mono = ?,
                    eosino = ?, plt = ?, hiv = ?, hbsag = ?, hcv = ?, vdrl = ?, created_by = ?
                WHERE id = ?
            """, (
                item.get("patient_name"), item.get("gender"), item.get("relation_type"),
                item.get("relation_name"), item.get("report_date"), item.get("hb"),
                item.get("wbc"), item.get("neut"), item.get("lymph"), item.get("mono"),
                item.get("eosino"), item.get("plt"), item.get("hiv"), item.get("hbsag"),
                item.get("hcv"), item.get("vdrl"),
                item.get("user_email") or item.get("created_by") or "Offline User",
                existing_id
            ))
            cursor.execute("SELECT * FROM fitness_patients WHERE id = ?", (existing_id,))
            updated_row = cursor.fetchone()
            return dict(updated_row) if updated_row else {"id": existing_id, **item}
        else:
            cursor.execute("""
                INSERT INTO fitness_patients (
                    patient_name, gender, relation_type, relation_name, report_date, mr_no,
                    hb, wbc, neut, lymph, mono, eosino, plt, hiv, hbsag, hcv, vdrl, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.get("patient_name"), item.get("gender"), item.get("relation_type"),
                item.get("relation_name"), item.get("report_date"), item.get("mr_no"),
                item.get("hb"), item.get("wbc"), item.get("neut"), item.get("lymph"),
                item.get("mono"), item.get("eosino"), item.get("plt"), item.get("hiv"),
                item.get("hbsag"), item.get("hcv"), item.get("vdrl"),
                item.get("user_email") or item.get("created_by") or "Offline User"
            ))
            row_id = cursor.lastrowid
            cursor.execute("SELECT * FROM fitness_patients WHERE id = ?", (row_id,))
            row = cursor.fetchone()
            return dict(row) if row else {"id": row_id, **item}

def list_fitness_patients(search: str = None, date_from: str = None, date_to: str = None) -> list[dict]:
    """Retrieve fitness patients from local SQLite database."""
    with get_db_conn() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM fitness_patients WHERE 1=1"
        params = []
        if date_from:
            query += " AND report_date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND report_date <= ?"
            params.append(date_to)
        if search:
            query += " AND (LOWER(patient_name) LIKE ? OR LOWER(mr_no) LIKE ?)"
            s = f"%{search.lower()}%"
            params.extend([s, s])
        query += " ORDER BY id DESC"
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]

if __name__ == "__main__":
    init_db()
    print("Offline SQLite database initialized at:", DB_PATH)
