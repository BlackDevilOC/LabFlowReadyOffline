import os
import sys
import json
import time
import random
import logging
import threading
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add directories to sys.path so sibling and packaged imports always work
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

if getattr(sys, 'frozen', False):
    _base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    _offline_dir = os.path.join(_base, "offline")
    if _offline_dir not in sys.path:
        sys.path.insert(0, _offline_dir)
    if _base not in sys.path:
        sys.path.insert(0, _base)
else:
    _parent = os.path.dirname(_current_dir)
    if _parent not in sys.path:
        sys.path.insert(0, _parent)

try:
    from offline.database import (
        get_db_conn, init_db, get_next_table_id,
        insert_mr_sync_log, list_mr_sync_log,
        insert_audit_log, list_audit_trail,
        upsert_tests_from_supabase, upsert_test_groups_from_supabase,
        upsert_shifts_from_supabase, upsert_users_from_supabase,
        upsert_remarks_from_supabase, upsert_invoice_settings_from_supabase,
    )
except (ImportError, ModuleNotFoundError):
    from database import (
        get_db_conn, init_db, get_next_table_id,
        insert_mr_sync_log, list_mr_sync_log,
        insert_audit_log, list_audit_trail,
        upsert_tests_from_supabase, upsert_test_groups_from_supabase,
        upsert_shifts_from_supabase, upsert_users_from_supabase,
        upsert_remarks_from_supabase, upsert_invoice_settings_from_supabase,
    )
from dbActions import init_supabase

try:
    from user_access import PERMISSION_KEYS, PERMISSION_LABELS, DEFAULT_PERMISSIONS
except Exception:
    PERMISSION_KEYS = ["register", "update_results", "fitness", "print", "fluid_reports", "admin", "manage_users", "manage_tests"]
    PERMISSION_LABELS = {
        "register": "Patient Registration",
        "update_results": "Enter / Update Results",
        "fitness": "Fitness Certificate",
        "print": "Lab Print & Preview",
        "fluid_reports": "Fluid Reports Hub",
        "admin": "Admin Console & Logs",
        "manage_users": "Create & Edit Staff Users",
        "manage_tests": "Tests & Prices Catalog",
    }
    DEFAULT_PERMISSIONS = {
        "register": True,
        "update_results": True,
        "fitness": True,
        "print": True,
        "fluid_reports": True,
        "admin": False,
        "manage_users": False,
        "manage_tests": False,
    }

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LabFlowOffline")

# Get base path pointing to project root
base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="LabFlow Offline API")

# Initialize database schema
init_db()

# Mount parent static files and templates
static_dir = os.path.join(base_path, "static")
templates_dir = os.path.join(base_path, "templates")
fetcheddata_dir = os.path.join(base_path, "fetcheddata")
os.makedirs(fetcheddata_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.mount("/fetcheddata", StaticFiles(directory=fetcheddata_dir), name="fetcheddata")
templates = Jinja2Templates(directory=templates_dir)
templates.env.globals["is_offline"] = True
templates.env.globals["url_prefix"] = "/offline"

_orig_offline_template_response = templates.TemplateResponse

def _safe_offline_template_response(*args, **kwargs):
    if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], dict):
        name = args[0]
        context = args[1]
        req = context.get("request") or kwargs.get("request")
        return _orig_offline_template_response(request=req, name=name, context=context)
    elif len(args) == 1 and isinstance(args[0], str):
        name = args[0]
        context = kwargs.get("context", {})
        req = kwargs.get("request") or context.get("request")
        return _orig_offline_template_response(request=req, name=name, context=context)
    return _orig_offline_template_response(*args, **kwargs)

templates.TemplateResponse = _safe_offline_template_response

logger.info(f"Offline App Started. Parent path: {base_path}")

# Pydantic schemas for request validation
class GetAllDataFromRegPage(BaseModel):
    salutation: str
    patient_name: str
    relation: str
    relation_name: str
    mobile: str
    gender: str
    age: int
    cnic: str
    patient_token: str | None = "0"
    shift: str
    user: str | None = None
    user_id: str | int | None = None
    user_email: str | None = None
    test_1: str | int | list | None = None   
    test_2: str | int | list | None = None   
    test_3: str | int | list | None = None   
    test_4: str | int | list | None = None   
    test_5: str | int | list | None = None   
    test_6: str | int | list | None = None  
    test_7: str | int | list | None = None  
    test_8: str | int | list | None = None

# Static list of lab categories matching online app
LAB_CATEGORIES = [
    "Hematology", "Biochemistry", "Serology", "Microbiology", "PCR",
    "Microscopic Examination", "Urine Analysis", "Stool Analysis",
    "Hormones / Endocrine", "Immunology", "Coagulation", "Tumor Markers",
    "Fluid Analysis", "Histopathology", "Cytology", "Group Test", "General"
]

# ──────────────────────────────────────────────────────────────────────────────
# Offline MR Generator
# Starting sequence default: 185040
# Modes: 'sequential', 'timestamp' (combined), 'timestamp_compact', 'time_suffix'
# ──────────────────────────────────────────────────────────────────────────────
MR_SETTINGS_FILE = os.path.join(fetcheddata_dir, "mr_settings.json")
OFFLINE_MR_START = 185040   # Starting sequence for offline MR numbers

def get_mr_settings() -> dict:
    if os.path.exists(MR_SETTINGS_FILE):
        try:
            with open(MR_SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"mode": "sequential", "start_seq": OFFLINE_MR_START}

def save_mr_settings(settings: dict):
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with open(MR_SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def generate_offline_mr(mode: Optional[str] = None) -> str:
    """Return next offline MR number starting at configured sequence (default 185040).
    Supports modes:
      - 'sequential' (default): 185040, 185041, 185042...
      - 'timestamp' / 'combined': 185040-YYYYMMDD-0001
      - 'timestamp_compact': 185040YYMMDD001
      - 'time_suffix': 185040-HHMMSS
    """
    cfg = get_mr_settings()
    selected_mode = (mode or cfg.get("mode") or os.getenv("OFFLINE_MR_MODE", "sequential")).lower().strip()
    start_seq = int(cfg.get("start_seq") or OFFLINE_MR_START)
    now_date = time.strftime("%Y%m%d")

    with get_db_conn() as conn:
        cursor = conn.cursor()

        if selected_mode in ("timestamp", "combined"):
            prefix = f"{start_seq}-{now_date}-"
            cursor.execute(
                "SELECT mr_no FROM patients WHERE mr_no LIKE ? ORDER BY mr_no DESC LIMIT 1",
                (f"{prefix}%",)
            )
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    last_seq = int(str(row[0]).split("-")[-1])
                    seq = last_seq + 1
                except ValueError:
                    seq = 1
            else:
                seq = 1
            return f"{prefix}{seq:04d}"

        elif selected_mode == "timestamp_compact":
            compact_date = time.strftime("%y%m%d")
            prefix = f"{start_seq}{compact_date}"
            cursor.execute(
                "SELECT mr_no FROM patients WHERE mr_no LIKE ? ORDER BY mr_no DESC LIMIT 1",
                (f"{prefix}%",)
            )
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    last_seq = int(str(row[0])[len(prefix):])
                    seq = last_seq + 1
                except ValueError:
                    seq = 1
            else:
                seq = 1
            return f"{prefix}{seq:03d}"

        elif selected_mode == "time_suffix":
            time_str = time.strftime("%H%M%S")
            return f"{start_seq}-{time_str}"

        else:  # 'sequential'
            cursor.execute(
                "SELECT MAX(CAST(mr_no AS INTEGER)) FROM patients "
                "WHERE CAST(mr_no AS INTEGER) >= ? AND CAST(mr_no AS INTEGER) < 90000000 AND mr_no NOT LIKE '%-%'",
                (start_seq,)
            )
            row = cursor.fetchone()
            last = row[0] if (row and row[0]) else (start_seq - 1)
            return str(last + 1)

# Helper to generate unique offline PIN
def generate_patient_pin() -> str:
    length = random.randint(4, 8)
    low = 10 ** (length - 1)
    high = (10 ** length) - 1
    return str(random.randint(low, high))

# ----------------- Navigation Routes -----------------

@app.get("/")
def home(request: Request):
    return templates.TemplateResponse('home.html', {"request": request, "title": "Home Page (Offline)", "name": "Offline User", "user_bane": "offline@labflow.com"})

@app.get('/login', include_in_schema=False)
def login_page(request: Request):
    return templates.TemplateResponse('login.html', {"request": request, "is_offline": True})

@app.get('/logout', include_in_schema=False)
def logout(request: Request):
    return RedirectResponse(url="/login")

@app.get('/register', include_in_schema=False)
@app.get('/register-new', include_in_schema=False)
def register_page(request: Request):
    return templates.TemplateResponse('register_new_ui.html', {"request": request, "title": "Patient Registration (Offline)", "name": "Offline"})

@app.get('/register-classic', include_in_schema=False)
def register_classic_page(request: Request):
    return templates.TemplateResponse('register.html', {"request": request, "title": "Patient Registration Classic (Offline)", "name": "Offline", "test_total_to_display": 8})

@app.get('/update-results', include_in_schema=False)
def update_results(request: Request):
    return templates.TemplateResponse('update_results.html', {"request": request, "title": "Update Test Results (Offline)", "name": "Offline"})

@app.get("/page/enter-results/{record_id}", include_in_schema=False)
def enter_results_page(request: Request, record_id: int):
    return templates.TemplateResponse('enter_results.html', {"request": request, "title": "Enter Test Results (Offline)", "record_id": record_id})

@app.get("/page/enter-results-patient/{mr_no}", include_in_schema=False)
def enter_results_patient_page(request: Request, mr_no: str):
    return templates.TemplateResponse('enter_results_patient.html', {"request": request, "title": "Enter Patient Results (Offline)", "mr_no": mr_no})

@app.get("/patient-report/{patient_id}", include_in_schema=False)
@app.get("/page/patient-report/{patient_id}", include_in_schema=False)
@app.get("/page/PatientTests/{patient_id}", include_in_schema=False)
def patientTestReportsPage(request: Request, patient_id: int):
    return templates.TemplateResponse('patient_report.html', {"request": request, "patient_id": patient_id})

@app.get("/page/register/patientinvoice/{patient_id}", include_in_schema=False)
def patientInvoiceGenerate(request: Request, patient_id: int, tests: str = "", pin: str = ""):
    return templates.TemplateResponse(
        "patient_invoice.html",
        {
            "request": request,
            "title": "Patient Receipt (Offline)",
            "name": "Offline",
            "patient_id": patient_id,
            "invoice_tests": tests,
            "invoice_pin": pin,
        },
    )

@app.get("/page/lab-print-records", include_in_schema=False)
def lab_print_records_page(request: Request):
    return templates.TemplateResponse('lab_print_records.html', {"request": request, "title": "Lab Print Records (Offline)", "name": "Offline"})

@app.get("/page/lab-test-print/{mr_no}", include_in_schema=False)
def lab_test_print_preview_page(request: Request, mr_no: str, date: str = None):
    return templates.TemplateResponse(
        'lab_test_print_preview.html',
        {"request": request, "title": "Lab Test Print Preview (Offline)", "mr_no": mr_no, "date": date or ""}
    )

@app.get("/page/print-records", include_in_schema=False)
def print_records_hub_page(request: Request):
    return RedirectResponse(url="/page/lab-print-records", status_code=302)


@app.get("/page/sync-history", include_in_schema=False)
def offline_sync_history_page(request: Request):
    return templates.TemplateResponse('mr_sync_history.html', {
        "request": request,
        "title": "MR Sync History (Offline)",
        "name": "Offline User",
        "is_offline": True,
        "url_prefix": "/offline"
    })


@app.get("/page/admin", include_in_schema=False)
def admin_panel(request: Request, view: str = "offline-tests", date: str = None):
    return templates.TemplateResponse('offline_admin.html', {
        "request": request,
        "title": f"Offline Admin - {view.replace('-', ' ').title()}",
        "name": "Admin",
        "current_view": view,
        "current_date": date,
        "is_offline": True,
        "hide_sidebar": True,
        "url_prefix": "/offline"
    })


@app.get("/page/emergency-dr", include_in_schema=False)
def offline_emergency_dr_page(request: Request):
    return templates.TemplateResponse(request=request, name='emergency_dr.html', context={
        "title": "Disaster Recovery Console (Offline)",
        "is_offline": True
    })


# ----------------- APIs -----------------

@app.get("/api/health")
def api_health():
    return {"ok": True}

@app.get("/api/offline/mr-preview")
def preview_offline_mr(mode: Optional[str] = None):
    """Returns next available offline MR numbers across different generator modes."""
    cfg = get_mr_settings()
    active_mode = mode or cfg.get("mode") or os.getenv("OFFLINE_MR_MODE", "sequential")
    start_seq = int(cfg.get("start_seq") or OFFLINE_MR_START)
    return {
        "status": "Success",
        "active_mode": active_mode,
        "starting_sequence": start_seq,
        "previews": {
            "sequential": generate_offline_mr("sequential"),
            "combined": generate_offline_mr("combined"),
            "timestamp_compact": generate_offline_mr("timestamp_compact"),
            "time_suffix": generate_offline_mr("time_suffix")
        }
    }

@app.get("/api/admin/offline-mr-config")
def get_offline_mr_config_api():
    cfg = get_mr_settings()
    return {
        "status": "Success",
        "mode": cfg.get("mode", "sequential"),
        "start_seq": cfg.get("start_seq", OFFLINE_MR_START),
        "previews": {
            "sequential": generate_offline_mr("sequential"),
            "combined": generate_offline_mr("combined"),
            "timestamp_compact": generate_offline_mr("timestamp_compact"),
            "time_suffix": generate_offline_mr("time_suffix")
        }
    }

@app.post("/api/admin/offline-mr-config")
async def save_offline_mr_config_api(request: Request):
    try:
        payload = await request.json()
        mode = str(payload.get("mode") or "sequential").lower().strip()
        if mode not in ("sequential", "combined", "timestamp", "timestamp_compact", "time_suffix"):
            raise HTTPException(status_code=400, detail="Invalid MR mode specified")
        
        try:
            start_seq = int(payload.get("start_seq") or OFFLINE_MR_START)
            if start_seq < 1:
                start_seq = OFFLINE_MR_START
        except (ValueError, TypeError):
            start_seq = OFFLINE_MR_START

        cfg = {"mode": mode, "start_seq": start_seq}
        save_mr_settings(cfg)

        return {
            "status": "Success",
            "data": cfg,
            "next_mr": generate_offline_mr(mode)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"save offline mr config failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
def on_startup():
    """Pre-generate all cache files at startup so pages load without requiring login first."""
    logger.info("Offline startup: pre-generating cache files...")
    try:
        # These functions are defined below — we defer their call via the event
        # They'll be available by startup time since Python has already loaded the module
        _generate_all_caches_at_startup()
    except Exception as e:
        logger.error(f"Startup cache generation failed: {e}")

def _generate_all_caches_at_startup():
    """Generate shifts, invoice settings, print settings, and remarks caches from SQLite."""
    # Shifts
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, shift, created_at FROM shift ORDER BY id")
        shifts = [dict(r) for r in cursor.fetchall()]
    _write_json(os.path.join(fetcheddata_dir, "shifts.json"), {"shifts": shifts})

    # Invoice settings
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM invoice_settings WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT * FROM invoice_settings ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
    cached = dict(row) if row else {
        "hospital_name": "GMMMC Teaching Hospital Sukkur",
        "developed_by": "Rehan Ahmed",
        "printer_width": "3in",
        "logo_path": "/static/images/hospital_logo.png",
        "is_active": 1
    }
    cached["logo_url"] = cached.get("logo_path") or "/static/images/hospital_logo.png"
    cached["qr_url"] = "/fetcheddata/qr_placeholder.svg"
    _write_json(os.path.join(fetcheddata_dir, "invoice_settings.json"), cached)

    # Print settings
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM print_settings WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT * FROM print_settings ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
    ps = dict(row) if row else {"page_size": "A4", "is_active": 1}
    ps["page_size"] = "A4"
    _write_json(os.path.join(fetcheddata_dir, "print_settings.json"), ps)

    # Remarks
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM remarks WHERE is_active = 1")
        rows = [dict(r) for r in cursor.fetchall()]
    global_list, by_test_name, by_category = [], {}, {}
    for row in rows:
        text = (row.get("remark_text") or "").strip()
        if not text:
            continue
        entry = {"text": text, "usage_count": int(row.get("usage_count") or 0), "id": row.get("id")}
        test = (row.get("test_name") or "").strip()
        cat = (row.get("category") or "").strip()
        if test:
            by_test_name.setdefault(test, []).append(entry)
        elif cat:
            by_category.setdefault(cat, []).append(entry)
        else:
            global_list.append(entry)
    _write_json(os.path.join(fetcheddata_dir, "remarks.json"), {
        "items": rows, "global": global_list,
        "by_test_name": by_test_name, "by_category": by_category,
    })

    # Placeholder user_preferences (no user logged in yet — defaults only)
    if not os.path.exists(os.path.join(fetcheddata_dir, "user_preferences.json")):
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, shift FROM shift ORDER BY id LIMIT 1")
            first_shift = cursor.fetchone()
        _write_json(os.path.join(fetcheddata_dir, "user_preferences.json"), {
            "user_id": None, "email": None,
            "default_shift_id": first_shift["id"] if first_shift else None,
            "default_shift": first_shift["shift"] if first_shift else "MORNING",
        })

    logger.info("Offline startup: all cache files ready.")

def _write_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


@app.get("/api/auth/login-users")
def api_auth_login_users():
    users = []
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, email FROM users WHERE is_active = 1 ORDER BY name")
            users = [{"id": r["id"], "name": r["name"], "email": r["email"]} for r in cursor.fetchall()]
    except Exception as e:
        logger.warning(f"Offline SQLite users load error: {e}")

    if not users:
        # Fallback to fetcheddata/users.json
        path = os.path.join(fetcheddata_dir, "users.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for u in (data.get("users") or []):
                        if u.get("is_active") is not False:
                            users.append({
                                "id": u.get("id"),
                                "name": u.get("name") or u.get("email"),
                                "email": u.get("email")
                            })
            except Exception as e:
                logger.warning(f"Offline users.json load error: {e}")
    return {"status": "Success", "users": users}

def sync_shifts_cache():
    fetcheddata_dir = os.path.join(base_path, "fetcheddata")
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, shift, created_at FROM shift ORDER BY id")
        shifts = [dict(r) for r in cursor.fetchall()]
        
    path = os.path.join(fetcheddata_dir, "shifts.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"shifts": shifts}, f, indent=2, default=str)
    logger.info("Offline: Shifts cached to fetcheddata/shifts.json")

def sync_user_preferences_cache(user_id, email, default_shift_id, default_shift):
    fetcheddata_dir = os.path.join(base_path, "fetcheddata")
    os.makedirs(fetcheddata_dir, exist_ok=True)
    payload = {
        "user_id": user_id,
        "email": email,
        "default_shift_id": default_shift_id,
        "default_shift": default_shift,
    }
    path = os.path.join(fetcheddata_dir, "user_preferences.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info("Offline: User preferences cached to fetcheddata/user_preferences.json")

def sync_remarks_cache():
    fetcheddata_dir = os.path.join(base_path, "fetcheddata")
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM remarks WHERE is_active = 1")
        rows = [dict(r) for r in cursor.fetchall()]
        
    global_list = []
    by_test_name = {}
    by_category = {}

    def add_bucket(bucket: dict, key: str, entry: dict):
        if not key:
            return
        bucket.setdefault(key, []).append(entry)

    for row in rows:
        text = (row.get("remark_text") or "").strip()
        if not text:
            continue
        entry = {"text": text, "usage_count": int(row.get("usage_count") or 0), "id": row.get("id")}
        test = (row.get("test_name") or "").strip()
        cat = (row.get("category") or "").strip()
        if test:
            add_bucket(by_test_name, test, entry)
        elif cat:
            add_bucket(by_category, cat, entry)
        else:
            global_list.append(entry)

    for bucket in (by_test_name, by_category):
        for key in bucket:
            bucket[key].sort(key=lambda x: (-(x.get("usage_count") or 0), x.get("text", "")))

    global_list.sort(key=lambda x: (-(x.get("usage_count") or 0), x.get("text", "")))

    payload = {
        "items": rows,
        "global": global_list,
        "by_test_name": by_test_name,
        "by_category": by_category,
    }
    path = os.path.join(fetcheddata_dir, "remarks.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info("Offline: Remarks cached to fetcheddata/remarks.json")

def sync_invoice_settings_cache():
    fetcheddata_dir = os.path.join(base_path, "fetcheddata")
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM invoice_settings WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT * FROM invoice_settings ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            
    if row:
        cached = dict(row)
    else:
        cached = {
            "hospital_name": "GMMMC Teaching Hospital Sukkur (Offline)",
            "developed_by": "Rehan Ahmed",
            "developed_by_url": "https://example.com",
            "online_report_url": "https://example.com",
            "printer_width": "3in",
            "logo_path": "/static/images/hospital_logo.png",
            "qr_code_path": None,
            "is_active": 1
        }
    cached["logo_url"] = cached.get("logo_path") or "/static/images/hospital_logo.png"
    cached["qr_url"] = "/fetcheddata/qr_placeholder.svg"
    
    path = os.path.join(fetcheddata_dir, "invoice_settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cached, f, indent=2, default=str)
    logger.info("Offline: Invoice settings cached to fetcheddata/invoice_settings.json")

def sync_lab_print_settings_cache():
    fetcheddata_dir = os.path.join(base_path, "fetcheddata")
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM print_settings WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT * FROM print_settings ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            
    if row:
        cached = dict(row)
    else:
        cached = {
            "page_size": "A4",
            "is_active": 1,
        }
    cached["page_size"] = "A4"
    path = os.path.join(fetcheddata_dir, "print_settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cached, f, indent=2, default=str)
    logger.info("Offline: Lab print settings cached to fetcheddata/print_settings.json")

@app.post("/api/auth/login")
async def api_auth_login(request: Request):
    try:
        data = await request.json()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        
        user_row = None
        try:
            with get_db_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE LOWER(email) = ? LIMIT 1", (email,))
                r = cursor.fetchone()
                if r:
                    user_row = dict(r)
        except Exception as e:
            logger.warning(f"Offline SQLite login query error: {e}")

        if not user_row:
            # Check fetcheddata/users.json
            path = os.path.join(fetcheddata_dir, "users.json")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data_cached = json.load(f)
                        for u in (data_cached.get("users") or []):
                            if (u.get("email") or "").strip().lower() == email:
                                user_row = u
                                break
                except Exception:
                    pass
            
        if not user_row or user_row.get("pwd") != password:
            return {"status": "Error", "message": "Invalid email or password."}
        
        if user_row.get("is_active") is False:
            return {"status": "Error", "message": "This account is disabled."}
        
        permissions = user_row.get("permissions") or {}
        if isinstance(permissions, str):
            try:
                permissions = json.loads(permissions)
            except Exception:
                permissions = {}

        user_payload = {
            "id": user_row.get("id"),
            "name": user_row.get("name"),
            "email": user_row.get("email"),
            "permissions": permissions,
            "default_shift": "MORNING"
        }
        
        default_shift_id = user_row.get("default_shift_id")
        default_shift = "MORNING"
        if default_shift_id:
            try:
                with get_db_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT shift FROM shift WHERE id = ?", (default_shift_id,))
                    shift_row = cursor.fetchone()
                    if shift_row:
                        user_payload["default_shift"] = shift_row["shift"]
                        default_shift = shift_row["shift"]
            except Exception:
                pass
                
            if default_shift == "MORNING":
                # Check fetcheddata/shifts.json
                shifts_path = os.path.join(fetcheddata_dir, "shifts.json")
                if os.path.exists(shifts_path):
                    try:
                        with open(shifts_path, "r", encoding="utf-8") as sf:
                            sdata = json.load(sf)
                            for s in (sdata.get("shifts") or []):
                                if s.get("id") == default_shift_id:
                                    user_payload["default_shift"] = s.get("shift")
                                    default_shift = s.get("shift")
                                    break
                    except Exception:
                        pass
        
        # Sync all offline caches synchronously to allow frontend lookup
        try:
            sync_shifts_cache()
            sync_user_preferences_cache(user_row.get("id"), user_row.get("email"), default_shift_id, default_shift)
            sync_remarks_cache()
            sync_invoice_settings_cache()
            sync_lab_print_settings_cache()
        except Exception as e:
            logger.error(f"Error generating offline cache files: {e}")

        # Trigger background auto-sync of any pending offline records on login
        try:
            threading.Thread(target=sync_pending_offline_patients_background, daemon=True).start()
        except Exception:
            pass
            
        return {"status": "Success", "user": user_payload}
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

TEST_SELECTION_CONFIG_PATH = os.path.join(fetcheddata_dir, "test_selection_config.json")

def get_test_selection_config():
    if os.path.exists(TEST_SELECTION_CONFIG_PATH):
        try:
            with open(TEST_SELECTION_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"allow_single_tests": False, "mode": "group_only"}

def save_test_selection_config(config_data: dict):
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with open(TEST_SELECTION_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

@app.get("/api/admin/test-selection-config")
def api_get_test_selection_config():
    cfg = get_test_selection_config()
    if "quick_presets" not in cfg:
        old_preset = cfg.get("regular_preset", [])
        auto_sel = cfg.get("auto_select_regular", False)
        cfg["quick_presets"] = [
            {
                "id": "preset_regular",
                "name": "Regular Package",
                "tests": old_preset,
                "auto_select": auto_sel
            }
        ] if old_preset else []
    if "category_styles" not in cfg:
        cfg["category_styles"] = {}
    return {"status": "Success", **cfg}

@app.post("/api/admin/test-selection-config")
def api_save_test_selection_config(payload: dict):
    existing = get_test_selection_config()
    mode = payload.get("mode", existing.get("mode", "group_only"))
    allow_single = (mode == "group_and_single") or bool(payload.get("allow_single_tests", existing.get("allow_single_tests", False)))
    
    quick_presets = payload.get("quick_presets")
    if quick_presets is None:
        old_preset = payload.get("regular_preset", existing.get("regular_preset", []))
        auto_sel = bool(payload.get("auto_select_regular", existing.get("auto_select_regular", False)))
        quick_presets = [{
            "id": "preset_regular",
            "name": "Regular Package",
            "tests": old_preset,
            "auto_select": auto_sel
        }] if old_preset else []

    new_config = {
        "allow_single_tests": allow_single,
        "mode": "group_and_single" if allow_single else "group_only",
        "categories_order": payload.get("categories_order", existing.get("categories_order", ["Popular", "Regular", "Group Test"])),
        "custom_categories": payload.get("custom_categories", existing.get("custom_categories", {})),
        "quick_presets": quick_presets,
        "category_styles": payload.get("category_styles", existing.get("category_styles", {})),
        "regular_preset": payload.get("regular_preset", existing.get("regular_preset", [])),
        "auto_select_regular": bool(payload.get("auto_select_regular", existing.get("auto_select_regular", False)))
    }
    save_test_selection_config(new_config)
    return {"status": "Success", "config": new_config}


# ── Registration Options Management (Offline) ──────────────────────────────
def _load_registration_options():
    path = os.path.join(fetcheddata_dir, "registration_options.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading registration_options.json: {e}")
    return None

def _save_registration_options(data):
    os.makedirs(fetcheddata_dir, exist_ok=True)
    path = os.path.join(fetcheddata_dir, "registration_options.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving registration_options.json: {e}")

@app.get("/api/admin/registration-options")
def api_get_registration_options():
    opts = _load_registration_options()
    if opts is None:
        opts = {
            "salutations": [
                {"value": "Mr.", "label": "Mr.", "default_gender": "MALE", "default_relation": "S"},
                {"value": "Mrs.", "label": "Mrs.", "default_gender": "FEMALE", "default_relation": "W"},
                {"value": "Miss.", "label": "Miss.", "default_gender": "FEMALE", "default_relation": "D"},
                {"value": "Baby", "label": "Baby", "default_gender": "MALE", "default_relation": "S"}
            ],
            "relations": [
                {"value": "S", "label": "S/O", "description": "Son of"},
                {"value": "D", "label": "D/O", "description": "Daughter of"},
                {"value": "W", "label": "W/O", "description": "Wife of"}
            ],
            "genders": [
                {"value": "MALE", "label": "MALE"},
                {"value": "FEMALE", "label": "FEMALE"},
                {"value": "OTHER", "label": "OTHER"}
            ],
            "default_values": {
                "salutation": "Mr."
            }
        }
        _save_registration_options(opts)
    return {"status": "Success", "options": opts}

@app.post("/api/admin/registration-options")
async def api_save_registration_options(request: Request):
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")
        _save_registration_options(data)
        return {"status": "Success", "message": "Registration options saved successfully (Offline)"}
    except Exception as e:
        logger.error(f"Offline registration options save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Print Layouts Management (Offline) ──────────────────────────────────────
PRINT_LAYOUTS_PATH = os.path.join(fetcheddata_dir, "print_layouts.json")

def _load_print_layouts() -> dict:
    if os.path.exists(PRINT_LAYOUTS_PATH):
        try:
            with open(PRINT_LAYOUTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load print_layouts.json: {e}")
    return {}

def _save_print_layouts(data: dict):
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with open(PRINT_LAYOUTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

@app.get("/api/admin/print-layouts")
def api_admin_get_print_layouts():
    return {"status": "ok", "layouts": _load_print_layouts()}

@app.post("/api/admin/print-layouts")
async def api_admin_save_print_layouts(request: Request):
    try:
        data = await request.json()
        category = (data.get("category") or "").strip()
        items = data.get("items") or []
        if not category:
            raise HTTPException(status_code=400, detail="Category name is required.")
        layouts = _load_print_layouts()
        layouts[category] = items
        _save_print_layouts(layouts)
        return {"status": "ok", "message": f"Layout saved for '{category}' (Offline).", "category": category}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/print-layouts/{category}")
def api_admin_delete_print_layout(category: str):
    layouts = _load_print_layouts()
    if category in layouts:
        del layouts[category]
        _save_print_layouts(layouts)
    return {"status": "ok", "message": "Layout deleted (Offline)."}


# ── Print Settings (Offline) ────────────────────────────────────────────────
@app.get("/api/admin/print-settings")
def api_admin_get_print_settings():
    path = os.path.join(fetcheddata_dir, "print_settings.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not data.get("hidden_group_titles"):
                    data["hidden_group_titles"] = "UCE, HEP B, C, UC, HEP B C, HEP B / C, HEP B, C (ICT), HEP B, C ELISA, HBSAG / HCV"
                return data
        except Exception:
            pass
    return {
        "status": "Success",
        "page_size": "A4",
        "is_active": 1,
        "hidden_group_titles": "UCE, HEP B, C, UC, HEP B C, HEP B / C, HEP B, C (ICT), HEP B, C ELISA, HBSAG / HCV"
    }

@app.post("/api/admin/print-settings")
async def api_admin_update_print_settings(request: Request):
    try:
        data = await request.json()
        path = os.path.join(fetcheddata_dir, "print_settings.json")
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
        existing.update(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        return {"status": "Success", "message": "Print settings saved offline"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/tests")
def load_test():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, category, unit, normal_min, normal_max, status FROM tests WHERE status = 1")
        tests = []
        for r in cursor.fetchall():
            t = dict(r)
            t["status"] = bool(t["status"])  # SQLite returns 1/0; JS expects true/false
            tests.append(t)
        
        cursor.execute("SELECT id, group_name, component_ids, category, status FROM test_groups WHERE status = 1")
        groups = []
        for r in cursor.fetchall():
            grp = dict(r)
            grp["status"] = bool(grp["status"])  # SQLite returns 1/0; JS expects true/false
            try:
                grp["component_ids"] = json.loads(grp["component_ids"])
            except Exception:
                grp["component_ids"] = []
            groups.append(grp)
            
        cfg = get_test_selection_config()
        quick_presets = cfg.get("quick_presets")
        if quick_presets is None and cfg.get("regular_preset"):
            quick_presets = [{
                "id": "preset_regular",
                "name": "Regular Package",
                "tests": cfg.get("regular_preset", []),
                "auto_select": cfg.get("auto_select_regular", False)
            }]
            
        return {
            "tests": tests, 
            "group_test": groups, 
            "allow_single_tests": cfg.get("allow_single_tests", False),
            "test_selection_mode": cfg.get("mode", "group_only"),
            "categories_order": cfg.get("categories_order", []),
            "custom_categories": cfg.get("custom_categories", {}),
            "regular_preset": cfg.get("regular_preset", []),
            "auto_select_regular": cfg.get("auto_select_regular", False),
            "quick_presets": quick_presets or [],
            "category_styles": cfg.get("category_styles", {})
        }


@app.get("/api/patient/testgroups")
def loadTestGroupsFromDb():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test_groups")
        groups = []
        for r in cursor.fetchall():
            grp = dict(r)
            try:
                grp["component_ids"] = json.loads(grp["component_ids"])
            except Exception:
                grp["component_ids"] = []
            groups.append(grp)
        return groups

@app.get("/api/setting/loadprintsetting")
def loadPrintSetting():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM print_settings WHERE is_active = 1 LIMIT 1")
        row = cursor.fetchone()
        if row:
            return [dict(row)]
        cursor.execute("SELECT * FROM print_settings LIMIT 1")
        row = cursor.fetchone()
        return [dict(row)] if row else []


# ----------------- Demographics & Registration -----------------

def add_tests_to_patient_sqlite(conn, patient_id: int, mr_no: str, patient_name: str, selected_tests: list):
    cursor = conn.cursor()
    
    # Load all tests into local dict
    cursor.execute("SELECT * FROM tests")
    tests_by_id = {r["id"]: dict(r) for r in cursor.fetchall()}
    
    # Load all group tests
    cursor.execute("SELECT * FROM test_groups")
    groups_by_id = {r["id"]: dict(r) for r in cursor.fetchall()}
    
    min_test_id = min(tests_by_id.keys()) if tests_by_id else 171
    id_offset = min_test_id - 1
    
    def build_test_parameter_json(test_details):
        return {
            "name": test_details.get("name"),
            "value": "0",
            "unit": test_details.get("unit"),
            "normal_min": test_details.get("normal_min"),
            "normal_max": test_details.get("normal_max")
        }

    valid_selections = [t for t in selected_tests if t not in (None, "", 0, "0")]
    
    for sel in valid_selections:
        sel_str = str(sel).strip()
        
        # Check for group test (JSON format)
        if sel_str.startswith("[") and sel_str.endswith("]"):
            try:
                component_ids = json.loads(sel_str)
            except Exception as je:
                logger.error(f"Failed to parse group component IDs: {je}")
                continue
                
            matched_group = None
            sorted_components = sorted([int(x) for x in component_ids])
            
            for g in groups_by_id.values():
                try:
                    g_components = sorted([int(x) for x in json.loads(g.get("component_ids") or "[]")])
                    if g_components == sorted_components:
                        matched_group = g
                        break
                except Exception:
                    pass
            
            if matched_group:
                test_name = matched_group.get("group_name")
                category = matched_group.get("category") or "Group Test"
            else:
                test_name = f"Group {sel_str}"
                category = "Group Test"
                
            test_values = {}
            for comp_id in component_ids:
                comp_id = int(comp_id)
                actual_id = comp_id
                if comp_id < min_test_id:
                    actual_id += id_offset
                    
                test_details = tests_by_id.get(actual_id)
                if test_details:
                    test_values[f"param_{comp_id}"] = build_test_parameter_json(test_details)
            
            cursor.execute(
                "INSERT INTO test_results_all (mr_no, patient_name, category, test_name, test_values, status) VALUES (?, ?, ?, ?, ?, ?)",
                (mr_no, patient_name, category, test_name, json.dumps(test_values), "Pending")
            )
            
        else:
            # Individual test
            try:
                test_id = int(sel_str)
            except ValueError:
                continue
                
            actual_id = test_id
            if test_id < min_test_id:
                actual_id += id_offset
                
            test_details = tests_by_id.get(actual_id)
            if test_details:
                test_name = test_details.get("name")
                category = test_details.get("category") or "Test"
                
                test_values = {
                    f"param_{test_id}": build_test_parameter_json(test_details)
                }
                
                cursor.execute(
                    "INSERT INTO test_results_all (mr_no, patient_name, category, test_name, test_values, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (mr_no, patient_name, category, test_name, json.dumps(test_values), "Pending")
                )

def resolve_selected_test_display_names(cursor, selected_tests) -> list[str]:
    cursor.execute("SELECT id, name FROM tests")
    tests_by_id = {r["id"]: dict(r) for r in cursor.fetchall()}
    
    cursor.execute("SELECT * FROM test_groups")
    groups_list = [dict(r) for r in cursor.fetchall()]
    
    min_test_id = min(tests_by_id.keys()) if tests_by_id else 171
    id_offset = min_test_id - 1

    names = []
    valid = [t for t in selected_tests if t not in (None, "", 0, "0")]

    for sel in valid:
        sel_str = str(sel).strip()
        if sel_str.startswith("[") and sel_str.endswith("]"):
            try:
                component_ids = json.loads(sel_str)
            except json.JSONDecodeError:
                names.append(f"Group {sel_str}")
                continue
            sorted_components = sorted([int(x) for x in component_ids])
            matched = None
            for g in groups_list:
                try:
                    g_components = sorted([int(x) for x in json.loads(g.get("component_ids") or "[]")])
                    if g_components == sorted_components:
                        matched = g
                        break
                except Exception:
                    pass
            names.append(matched.get("group_name") if matched else f"Group {sel_str}")
        else:
            try:
                test_id = int(sel_str)
            except ValueError:
                continue
            actual_id = test_id + id_offset if test_id < min_test_id else test_id
            details = tests_by_id.get(actual_id) or tests_by_id.get(test_id)
            names.append(details.get("name") if details else f"Test {test_id}")

    return names

@app.post("/register/patient")
async def register_patient(request: Request, background_tasks: BackgroundTasks):
    try:
        form = await request.form()
        data = dict(form)
        
        user = request.headers.get("X-User-Email") or data.get("user_email") or "Offline Registrar"
        
        item = GetAllDataFromRegPage(**data)
        
        # Split tests
        selected_tests = [
            item.test_1, item.test_2, item.test_3, item.test_4,
            item.test_5, item.test_6, item.test_7, item.test_8
        ]
        
        mr_no = generate_offline_mr()
        pin = generate_patient_pin()
        
        user_name = user.split("@")[0] if "@" in str(user) else str(user)
        
        # Save to SQLite
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO patients (
                    mr_no, salutation, patient_name, relation, relation_name, 
                    mobile, gender, age, cnic, patient_token, shift, user, pwd, synced
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    mr_no, item.salutation, item.patient_name, item.relation, item.relation_name,
                    item.mobile, item.gender.upper(), item.age, item.cnic, 
                    item.patient_token if item.patient_token else "0",
                    item.shift, user_name, pin
                )
            )
            patient_id = cursor.lastrowid
            
            # Add tests immediately to avoid background task thread issues in standard desktop SQLite
            add_tests_to_patient_sqlite(conn, patient_id, mr_no, item.patient_name, selected_tests)
            
            test_display_names = resolve_selected_test_display_names(cursor, selected_tests)
            
        logger.info(f"Registered patient ID: {patient_id}, MR No: {mr_no} (Offline)")

        # Record local audit log for patient registration
        try:
            insert_audit_log(
                mr_no=mr_no,
                patient_name=item.patient_name,
                action="REGISTER",
                user_name=item.user or "Staff",
                details=f"Registered patient with {len(test_display_names)} test(s): {', '.join(test_display_names[:6])}{'...' if len(test_display_names) > 6 else ''} (Shift: {item.shift})",
            )
        except Exception as audit_err:
            logger.debug(f"Audit log error on register: {audit_err}")

        # Trigger background auto-sync to push to Supabase if internet is available
        try:
            threading.Thread(target=sync_pending_offline_patients_background, daemon=True).start()
        except Exception:
            pass

        query = urlencode({
            "tests": "|".join(test_display_names),
            "pin": pin,
        })
        
        return RedirectResponse(
            url=f"/page/register/patientinvoice/{patient_id}?{query}",
            status_code=303,
        )
    except Exception as e:
        logger.error(f"Patient registration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/patient/info/{mr_no}")
def get_patient_info(mr_no: str):
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM patients WHERE mr_no = ? LIMIT 1", (mr_no,))
        row = cursor.fetchone()
        if not row:
            return {"status": "Error", "message": "Patient not found", "patient": None}
            
        p = dict(row)
        return {
            "status": "Success",
            "patient": {
                "patient_name": p.get("patient_name"),
                "mr_no": p.get("mr_no"),
                "relation": p.get("relation") or "",
                "relation_name": p.get("relation_name") or "",
                "age": p.get("age"),
                "gender": p.get("gender") or "Male",
                "mobile": p.get("mobile") or "",
                "shift": p.get("shift") or "",
                "patient_token": p.get("patient_token"),
            }
        }

@app.post("/api/patient/update-info/{mr_no}")
async def update_patient_info(mr_no: str, request: Request):
    try:
        data = await request.json()
        allowed_payload = {}
        for field in ["patient_name", "relation", "relation_name", "shift", "patient_token", "mobile", "age", "gender"]:
            if field in data:
                if field in ["patient_token", "age"] and data[field] not in (None, ""):
                    try:
                        allowed_payload[field] = int(data[field])
                    except ValueError:
                        pass
                else:
                    allowed_payload[field] = data[field]
                    
        with get_db_conn() as conn:
            cursor = conn.cursor()
            
            # Construct dynamic update query
            if allowed_payload:
                set_clause = ", ".join([f"{k} = ?" for k in allowed_payload.keys()])
                params = list(allowed_payload.values()) + [mr_no]
                cursor.execute(f"UPDATE patients SET {set_clause} WHERE mr_no = ?", params)
                
            if "patient_name" in allowed_payload:
                cursor.execute(
                    "UPDATE test_results_all SET patient_name = ? WHERE mr_no = ?",
                    (allowed_payload["patient_name"], mr_no)
                )

        if allowed_payload:
            insert_audit_log(
                mr_no=mr_no,
                patient_name=allowed_payload.get("patient_name"),
                action="EDIT_PATIENT",
                user_name=data.get("user_name") or data.get("logged_in_user") or "Staff",
                details=f"Updated demographics: {', '.join(allowed_payload.keys())}",
            )
                
        return {"status": "Success"}
    except Exception as e:
        logger.error(f"Failed to update patient info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/patient/allinfo/{patient_id}")
def get_patient_info_full(patient_id: int):
    # Retrieve demographics and all tests for patient_id.
    # Note: SQLite patients has INTEGER primary key `id`.
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM patients WHERE id = ? LIMIT 1", (patient_id,))
        p_row = cursor.fetchone()
        if not p_row:
            return {"Response": None}
            
        p = dict(p_row)
        mr_no = p["mr_no"]
        
        cursor.execute("SELECT * FROM test_results_all WHERE mr_no = ? AND delete_status = 0", (mr_no,))
        test_rows = []
        for r in cursor.fetchall():
            td = dict(r)
            try:
                td["test_values"] = json.loads(td["test_values"] or "{}")
            except Exception:
                td["test_values"] = {}
            test_rows.append(td)
            
        # Map tests to target format
        patient_test_results = []
        for tr in test_rows:
            # Reconstruct online model structure
            for param_key, param_val in tr["test_values"].items():
                try:
                    test_id = int(param_key.replace("param_", ""))
                except ValueError:
                    test_id = 0
                patient_test_results.append({
                    "id": tr["id"],
                    "test_id": test_id,
                    "result_value": param_val.get("value", "0"),
                    "tests": {
                        "name": param_val.get("name"),
                        "unit": param_val.get("unit"),
                        "normal_min": param_val.get("normal_min"),
                        "normal_max": param_val.get("normal_max"),
                        "category": tr["category"]
                    }
                })
                
        response_payload = {
            "id": p["id"],
            "mr_no": p["mr_no"],
            "patient_name": p["patient_name"],
            "salutation": p["salutation"],
            "relation": p["relation"],
            "relation_name": p["relation_name"],
            "mobile": p["mobile"],
            "gender": p["gender"],
            "age": p["age"],
            "cnic": p["cnic"],
            "patient_token": p["patient_token"],
            "shift": p["shift"],
            "user": p["user"],
            "pwd": p["pwd"],
            "created_at": p.get("created_at"),
            "patient_test_results": patient_test_results
        }
        return {"Response": response_payload}


# ----------------- Results Update & Verification -----------------

def _sanitize_test_values(raw):
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("test_values"), dict):
        raw = raw["test_values"]
    return {k: v for k, v in raw.items() if k not in ("remarks", "test_values")}

def _parse_test_result_update_body(data):
    if not isinstance(data, dict):
        return {}, None
    if "test_values" in data:
        tv = data.get("test_values") or {}
        remarks = data.get("remarks")
        if remarks in (None, "") and isinstance(tv, dict) and tv.get("remarks") not in (None, ""):
            remarks = tv.get("remarks")
        return _sanitize_test_values(tv), remarks
    return _sanitize_test_values(data), None

def _format_audit_test_values(test_values) -> str:
    """Format test values dict into a clean string for audit logging."""
    if not isinstance(test_values, dict):
        return str(test_values) if test_values else ""
    parts = []
    for k, v in test_values.items():
        if k in ("remarks", "test_values"):
            continue
        if isinstance(v, dict):
            val = v.get("value")
            unit = v.get("unit", "")
            unit_str = f" {unit}" if unit else ""
            if val not in (None, ""):
                parts.append(f"{k}: {val}{unit_str}")
        elif v not in (None, ""):
            parts.append(f"{k}: {v}")
    return ", ".join(parts)

@app.get("/api/patient/basic/all")
def get_patient_basic_info_all(
    search: str = None,
    date_from: str = None,
    date_to: str = None,
    status: str = None,
    shift: str = None,
    category: str = None
):
    with get_db_conn() as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT t.*, p.relation, p.relation_name, p.gender, p.age, p.shift, p.mobile, p.cnic, p.patient_token, p.user, p.user_id 
            FROM test_results_all t 
            JOIN patients p ON t.mr_no = p.mr_no 
            WHERE t.delete_status = 0
        """
        params = []
        
        if search:
            search_str = search.strip()
            query += " AND (t.mr_no LIKE ? OR t.patient_name LIKE ?)"
            params.extend([f"%{search_str}%", f"%{search_str}%"])
            
        if date_from:
            query += " AND t.created_at >= ?"
            params.append(f"{date_from} 00:00:00")
        if date_to:
            query += " AND t.created_at <= ?"
            params.append(f"{date_to} 23:59:59")
            
        if status and status != "all":
            db_status = status.capitalize() if status in ["pending", "completed"] else status
            query += " AND t.status = ?"
            params.append(db_status)
            
        if category and category != "all":
            query += " AND t.category = ?"
            params.append(category)
            
        query += " ORDER BY t.created_at DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        flat_data = []
        for r in rows:
            item = dict(r)
            
            if shift and shift != "all" and (item["shift"] or "").lower() != shift.lower():
                continue
                
            item["relation_type"] = item.get("relation") or ""
            item["relation_name"] = item.get("relation_name") or ""
            item["synced"] = item.get("status") == "Completed"
            try:
                item["test_values"] = json.loads(item["test_values"] or "{}")
            except Exception:
                item["test_values"] = {}
                
            flat_data.append(item)
            
        return {"Response": flat_data}

@app.get("/api/patient/basic/{limit}")
def get_patient_basic_info_with_limit(
    limit: int,
    search: str = None,
    date_from: str = None,
    date_to: str = None,
    status: str = None,
    shift: str = None,
    category: str = None
):
    # Re-use all-info function but apply limit
    res = get_patient_basic_info_all(search, date_from, date_to, status, shift, category)
    records = res.get("Response", [])[:limit]
    return {"Response": records, "meta": {"has_more": len(res.get("Response", [])) > limit, "returned": len(records)}}

@app.get("/api/test-results/record/{record_id}")
def get_test_record_by_id(record_id: int):
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.*, p.relation, p.relation_name, p.age, p.gender, p.mobile, p.shift, p.patient_token
            FROM test_results_all t 
            JOIN patients p ON t.mr_no = p.mr_no 
            WHERE t.id = ? LIMIT 1
            """,
            (record_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {"status": "Error", "data": None}
            
        data = dict(row)
        try:
            data["test_values"] = json.loads(data["test_values"] or "{}")
        except Exception:
            data["test_values"] = {}
            
        data["relation_type"] = data.get("relation") or ""
        data["relation_name"] = data.get("relation_name") or ""
        data["synced"] = data.get("status") == "Completed"
        
        return {"status": "Success", "data": data}

@app.post("/api/test-results/update/{record_id}")
async def update_test_record_results(record_id: int, request: Request):
    try:
        data = await request.json()
        test_values, remarks = _parse_test_result_update_body(data)
        
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT mr_no, patient_name, test_name FROM test_results_all WHERE id = ?", (record_id,))
            r_meta = cursor.fetchone()
            
            cursor.execute(
                "UPDATE test_results_all SET test_values = ?, status = ?, remarks = ? WHERE id = ?",
                (json.dumps(test_values), "Completed", remarks or "", record_id)
            )

        if r_meta:
            val_summary = _format_audit_test_values(test_values)
            rem_str = f" [Remark: {remarks}]" if remarks else ""
            details_msg = f"{r_meta['test_name']}: {val_summary}{rem_str}" if val_summary else f"Updated {r_meta['test_name']}{rem_str}"
            insert_audit_log(
                mr_no=str(r_meta["mr_no"]),
                patient_name=r_meta["patient_name"],
                action="UPDATE_RESULT",
                user_name=data.get("user_name") or data.get("logged_in_user") or "Staff",
                details=details_msg,
            )
            
        return {"status": "Success"}
    except Exception as e:
        logger.error(f"Failed to update single test record results: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/test-results/patient/{mr_no}")
def get_test_records_by_mr_no(mr_no: str):
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM patients WHERE mr_no = ? LIMIT 1", (mr_no,))
        p_row = cursor.fetchone()
        if not p_row:
            return {"status": "Error", "records": []}
            
        p = dict(p_row)
        patient_info = {
            "patient_name": p["patient_name"],
            "mr_no": mr_no,
            "relation_type": p["relation"] or "",
            "relation_name": p["relation_name"] or "",
            "age": p["age"] or "",
            "gender": p["gender"] or "Male",
            "mobile": p["mobile"] or "",
            "shift": p["shift"] or "",
            "patient_token": p["patient_token"] or ""
        }
        
        cursor.execute("SELECT * FROM test_results_all WHERE mr_no = ? AND delete_status = 0", (mr_no,))
        records = []
        for r in cursor.fetchall():
            item = dict(r)
            try:
                item["test_values"] = json.loads(item["test_values"] or "{}")
            except Exception:
                item["test_values"] = {}
            records.append(item)
            
        return {"status": "Success", "patient": patient_info, "records": records}

@app.post("/api/test-results/patient/update/{mr_no}")
async def update_patient_test_records(mr_no: str, request: Request):
    try:
        data = await request.json()
        
        p_name = None
        breakdown = []
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT patient_name FROM patients WHERE mr_no = ? LIMIT 1", (mr_no,))
            p_row = cursor.fetchone()
            if p_row:
                p_name = p_row["patient_name"]

            for record_id_str, item in data.items():
                try:
                    record_id = int(record_id_str)
                except (ValueError, TypeError):
                    continue
                test_values, remarks = _parse_test_result_update_body(item)
                
                cursor.execute("SELECT test_name FROM test_results_all WHERE id = ? LIMIT 1", (record_id,))
                t_row = cursor.fetchone()
                tname = t_row["test_name"] if t_row else f"Test #{record_id}"

                cursor.execute(
                    "UPDATE test_results_all SET test_values = ?, status = ?, remarks = ? WHERE id = ? AND mr_no = ?",
                    (json.dumps(test_values), "Completed", remarks or "", record_id, mr_no)
                )
                
                val_str = _format_audit_test_values(test_values)
                rem_str = f" [Remark: {remarks}]" if remarks else ""
                if val_str:
                    breakdown.append(f"• {tname}: {val_str}{rem_str}")
                elif remarks:
                    breakdown.append(f"• {tname}:{rem_str}")
                
        if breakdown or data:
            details_msg = "\n".join(breakdown) if breakdown else f"Bulk updated {len(data)} test record(s)"
            insert_audit_log(
                mr_no=mr_no,
                patient_name=p_name,
                action="UPDATE_RESULT",
                user_name=data.get("user_name") or data.get("logged_in_user") or "Staff",
                details=details_msg,
            )
            
        return {"status": "Success"}
    except Exception as e:
        logger.error(f"Failed to bulk update patient test records: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/test-results/delete/{record_id}")
async def soft_delete_test_record(record_id: int, request: Request):
    try:
        data = await request.json()
        person_deleting = data.get("person_deleting", "Offline User")
        
        r_meta = None
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT mr_no, patient_name, test_name FROM test_results_all WHERE id = ?", (record_id,))
            r_meta = cursor.fetchone()
            cursor.execute(
                "UPDATE test_results_all SET delete_status = 1, person_deleting = ? WHERE id = ?",
                (person_deleting, record_id)
            )
            
        if r_meta:
            insert_audit_log(
                mr_no=str(r_meta["mr_no"]),
                patient_name=r_meta["patient_name"],
                action="DELETE_TEST",
                user_name=person_deleting,
                details=f"Deleted test: {r_meta['test_name']}",
            )
            
        return {"status": "Success"}
    except Exception as e:
        logger.error(f"Failed to delete test record: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/test-results/patient/{mr_no}/add")
async def add_patient_test_record(mr_no: str, request: Request):
    try:
        data = await request.json()
        selected_test = data.get("selected_test")
        if selected_test in (None, "", 0, "0"):
            raise HTTPException(status_code=400, detail="No test selected")
            
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, patient_name FROM patients WHERE mr_no = ? LIMIT 1", (mr_no,))
            p_row = cursor.fetchone()
            if not p_row:
                raise HTTPException(status_code=404, detail="Patient not found")
                
            add_tests_to_patient_sqlite(conn, p_row["id"], mr_no, p_row["patient_name"], [selected_test])
            
        return {"status": "Success", "added": 1}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add patient test: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------- Printing & Invoice APIs -----------------

@app.get("/api/lab/print/{mr_no}")
def api_lab_print_payload(mr_no: str, date: str = None):
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM patients WHERE mr_no = ? LIMIT 1", (mr_no,))
            p_row = cursor.fetchone()
            if not p_row:
                return {"status": "error", "patient": None, "tests": []}
                
            patient = dict(p_row)
            
            query = "SELECT * FROM test_results_all WHERE mr_no = ? AND delete_status = 0"
            params = [mr_no]
            if date:
                query += " AND created_at LIKE ?"
                params.append(f"{date}%")
            query += " ORDER BY created_at ASC"
            
            cursor.execute(query, params)
            test_rows = []
            for r in cursor.fetchall():
                td = dict(r)
                try:
                    td["test_values"] = json.loads(td["test_values"] or "{}")
                except Exception:
                    td["test_values"] = {}
                test_rows.append({
                    "id": td["id"],
                    "category": td["category"] or "General",
                    "test_name": td["test_name"] or "Test",
                    "test_values": td["test_values"],
                    "remarks": td["remarks"] or "",
                    "created_at": td["created_at"],
                    "status": td["status"] or "Pending"
                })
                
            return {"status": "ok", "patient": patient, "tests": test_rows}
    except Exception as e:
        logger.error(f"Failed to get print payload: {e}")
        return {"status": "error", "patient": None, "tests": []}


# ----------------- Print Records (Lab only in Offline) -----------------

@app.get("/api/print-records")
def get_print_records_api(
    date_from: str = None,
    date_to: str = None,
    search: str = None,
    record_type: str = "all",
    status: str = None,
    shift: str = None,
    category: str = None,
    limit: int = 500,
):
    """Offline version: lab records only (no fitness) from SQLite."""
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()

            q = """
                SELECT t.id, t.mr_no, t.patient_name, t.category, t.test_name,
                       t.status, t.remarks, t.created_at,
                       p.relation, p.relation_name, p.shift, p.patient_token, p.gender
                FROM test_results_all t
                JOIN patients p ON t.mr_no = p.mr_no
                WHERE t.delete_status = 0
            """
            params = []

            if search:
                q += " AND (t.mr_no LIKE ? OR t.patient_name LIKE ? OR t.test_name LIKE ?)"
                like = f"%{search}%"
                params += [like, like, like]

            if date_from:
                q += " AND DATE(t.created_at) >= ?"
                params.append(date_from)

            if date_to:
                q += " AND DATE(t.created_at) <= ?"
                params.append(date_to)

            if status and status.lower() not in ("all", ""):
                want = "Completed" if status.lower() in ("completed", "synced") else "Pending"
                q += " AND t.status = ?"
                params.append(want)

            if shift and shift.lower() not in ("all", ""):
                q += " AND UPPER(p.shift) = ?"
                params.append(shift.upper())

            if category and category.lower() not in ("all", ""):
                q += " AND t.category = ?"
                params.append(category)

            q += " ORDER BY t.created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(q, params)
            rows = [dict(r) for r in cursor.fetchall()]

        records = [
            {
                "record_type": "lab",
                "id": r["id"],
                "mr_no": r["mr_no"],
                "patient_name": r["patient_name"],
                "created_at": r["created_at"],
                "relation_type": r.get("relation") or "",
                "relation_name": r.get("relation_name") or "",
                "shift": r.get("shift") or "",
                "patient_token": r.get("patient_token") or "",
                "gender": r.get("gender") or "",
                "synced": r["status"] == "Completed",
                "status": r["status"] or "Pending",
                "test_name": r["test_name"] or "",
                "category": r["category"] or "",
                "remarks": (r.get("remarks") or "").strip(),
                "report_label": r["test_name"] or "Lab",
            }
            for r in rows
        ]
        return {"status": "ok", "records": records, "total": len(records)}
    except Exception as e:
        logger.error(f"Failed to get print records: {e}")
        return {"status": "error", "records": [], "total": 0}


# ----------------- Metadata & Filters -----------------

@app.get("/api/metadata/registrar-users")
def get_registrar_users():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT user, user_id FROM patients WHERE user IS NOT NULL")
        users = [{"user_id": r["user_id"], "user": r["user"]} for r in cursor.fetchall()]
        return {"status": "Success", "users": users}

@app.get("/api/metadata/filters")
def get_filter_metadata():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT shift FROM patients WHERE shift IS NOT NULL")
        shifts = sorted([r["shift"] for r in cursor.fetchall() if r["shift"]])
        
        cursor.execute("SELECT DISTINCT category FROM tests WHERE category IS NOT NULL")
        categories = sorted([r["category"] for r in cursor.fetchall() if r["category"]])
        
        if not shifts:
            shifts = ["MORNING", "EVENING", "NIGHT", "HOLIDAY", "OPD"]
        if not categories:
            categories = ["Hematology", "Biochemistry", "Serology", "Fluid Reports"]
            
        return {
            "status": "Success",
            "shifts": shifts,
            "categories": categories
        }

@app.get("/api/admin/tests-catalog")
def admin_tests_catalog():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, category, unit, normal_min, normal_max, status FROM tests ORDER BY name")
        tests = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT id, group_name, category, component_ids, status FROM test_groups ORDER BY group_name")
        groups = []
        for r in cursor.fetchall():
            grp = dict(r)
            try:
                grp["component_ids"] = json.loads(grp["component_ids"])
            except Exception:
                grp["component_ids"] = []
            groups.append(grp)
            
        return {
            "status": "Success",
            "tests": tests,
            "groups": groups,
            "categories": LAB_CATEGORIES,
        }

@app.get("/api/admin/remarks")
def api_admin_list_remarks():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM remarks ORDER BY sort_order")
        remarks = [dict(r) for r in cursor.fetchall()]
        return {"status": "Success", "remarks": remarks}

@app.get("/api/admin/shifts")
def api_admin_list_shifts():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shift ORDER BY id")
        shifts = [dict(r) for r in cursor.fetchall()]
        return {"status": "Success", "shifts": shifts}

@app.get("/api/admin/users")
def api_admin_list_users():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users ORDER BY id")
        users = []
        for r in cursor.fetchall():
            u = dict(r)
            try:
                u["permissions"] = json.loads(u["permissions"] or "{}")
            except Exception:
                u["permissions"] = {}
            users.append(u)
        return {"status": "Success", "users": users}


# ----------------- Offline Admin: Tests CRUD (SQLite) -----------------

def _load_offline_tests_catalog():
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, category, unit, normal_min, normal_max, status FROM tests ORDER BY name"
        )
        tests = [dict(r) for r in cursor.fetchall()]
        cursor.execute(
            "SELECT id, group_name, category, component_ids, status FROM test_groups ORDER BY group_name"
        )
        groups = []
        for r in cursor.fetchall():
            grp = dict(r)
            try:
                grp["component_ids"] = json.loads(grp["component_ids"] or "[]")
            except Exception:
                grp["component_ids"] = []
            groups.append(grp)
    return tests, groups


@app.get("/api/admin/offline-tests-catalog")
def admin_offline_tests_catalog():
    try:
        tests, groups = _load_offline_tests_catalog()
        return {
            "status": "Success",
            "tests": tests,
            "groups": groups,
            "categories": LAB_CATEGORIES,
        }
    except Exception as e:
        logger.error(f"offline-tests-catalog failed: {e}")
        return {"status": "Error", "tests": [], "groups": [], "categories": LAB_CATEGORIES}


@app.post("/api/admin/offline-tests")
async def admin_offline_create_test(request: Request):
    try:
        payload = await request.json()
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Test name is required")

        category = (payload.get("category") or "").strip() or "General"
        unit = (payload.get("unit") or "").strip()
        normal_min = (payload.get("normal_min") or "").strip() or None
        normal_max = (payload.get("normal_max") or "").strip() or None
        status = 1 if bool(payload.get("status", True)) else 0
        new_id = get_next_table_id("tests")

        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tests (id, created_at, name, unit, normal_min, normal_max, status, category)
                VALUES (?, datetime('now','localtime'), ?, ?, ?, ?, ?, ?)
                """,
                (new_id, name, unit or None, normal_min, normal_max, status, category),
            )
        return {"status": "Success", "data": {"id": new_id, "name": name}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"offline create test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/offline-tests/{test_id}")
async def admin_offline_update_test(test_id: int, request: Request):
    try:
        payload = await request.json()
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Test name is required")

        update_data = {
            "name": name,
            "category": (payload.get("category") or "").strip() or "General",
            "unit": (payload.get("unit") or "").strip() or None,
            "normal_min": (payload.get("normal_min") or "").strip() or None,
            "normal_max": (payload.get("normal_max") or "").strip() or None,
            "status": 1 if bool(payload.get("status", True)) else 0,
        }
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE tests
                SET name = ?, category = ?, unit = ?, normal_min = ?, normal_max = ?, status = ?
                WHERE id = ?
                """,
                (
                    update_data["name"], update_data["category"], update_data["unit"],
                    update_data["normal_min"], update_data["normal_max"],
                    update_data["status"], test_id,
                ),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Test not found")
        return {"status": "Success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"offline update test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/offline-tests/{test_id}")
def admin_offline_get_test(test_id: int):
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tests WHERE id = ?", (test_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Test not found")
        return {"status": "Success", "data": dict(row)}


@app.post("/api/admin/offline-test-groups")
async def admin_offline_create_test_group(request: Request):
    try:
        payload = await request.json()
        group_name = (payload.get("group_name") or "").strip()
        if not group_name:
            raise HTTPException(status_code=400, detail="Group name is required")

        component_ids_raw = payload.get("component_ids") or []
        if not isinstance(component_ids_raw, list) or not component_ids_raw:
            raise HTTPException(status_code=400, detail="Select at least one test")

        component_ids = [int(x) for x in component_ids_raw]
        category = (payload.get("category") or "").strip() or "Group Test"
        status = 1 if bool(payload.get("status", True)) else 0
        new_id = get_next_table_id("test_groups")

        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO test_groups (id, group_name, component_ids, created_at, status, category)
                VALUES (?, ?, ?, datetime('now','localtime'), ?, ?)
                """,
                (new_id, group_name, json.dumps(component_ids), status, category),
            )
        return {"status": "Success", "data": {"id": new_id, "group_name": group_name}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"offline create test group failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/offline-test-groups/{group_id}")
async def admin_offline_update_test_group(group_id: int, request: Request):
    try:
        payload = await request.json()
        group_name = (payload.get("group_name") or "").strip()
        if not group_name:
            raise HTTPException(status_code=400, detail="Group name is required")

        component_ids_raw = payload.get("component_ids") or []
        if not isinstance(component_ids_raw, list) or not component_ids_raw:
            raise HTTPException(status_code=400, detail="Select at least one test")

        component_ids = [int(x) for x in component_ids_raw]
        category = (payload.get("category") or "").strip() or "Group Test"
        status = 1 if bool(payload.get("status", True)) else 0

        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE test_groups
                SET group_name = ?, component_ids = ?, category = ?, status = ?
                WHERE id = ?
                """,
                (group_name, json.dumps(component_ids), category, status, group_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Group not found")
        return {"status": "Success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"offline update test group failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------- Offline Admin: Patient Sync -----------------

def _local_dt_to_iso(dt_str: str | None) -> str | None:
    """
    Convert a naive SQLite local-time string like '2026-06-14 13:54:58'
    to ISO-8601 with the system's local UTC offset, e.g. '2026-06-14T13:54:58+05:00'.
    This prevents Supabase/Postgres from misinterpreting the timestamp as UTC.
    """
    if not dt_str:
        return None
    try:
        from datetime import datetime, timezone, timedelta
        import time as _time
        # Parse the naive datetime
        dt = datetime.strptime(str(dt_str).strip(), "%Y-%m-%d %H:%M:%S")
        # Get local UTC offset in seconds
        offset_seconds = -_time.timezone if _time.daylight == 0 else -_time.altzone
        tz = timezone(timedelta(seconds=offset_seconds))
        # Attach timezone and return ISO format
        return dt.replace(tzinfo=tz).isoformat()
    except Exception:
        return dt_str  # Return as-is if parsing fails


def _insert_patient_to_supabase(supabase, patient: dict):
    base_payload = {
        "salutation": patient.get("salutation"),
        "patient_name": patient.get("patient_name"),
        "relation": patient.get("relation"),
        "relation_name": patient.get("relation_name"),
        "mobile": patient.get("mobile"),
        "gender": patient.get("gender"),
        "age": patient.get("age"),
        "cnic": patient.get("cnic"),
        "patient_token": patient.get("patient_token") if patient.get("patient_token") not in (None, "") else "0",
        "shift": patient.get("shift"),
        "user": patient.get("user") or "Offline",
        "pwd": patient.get("pwd"),
    }
    if patient.get("user_id"):
        base_payload["user_id"] = patient.get("user_id")
    if patient.get("created_at"):
        # Convert naive local datetime to timezone-aware ISO string to avoid Supabase UTC mismatch
        base_payload["created_at"] = _local_dt_to_iso(patient.get("created_at")) or patient.get("created_at")

    offline_mr = str(patient.get("mr_no") or "")
    extended = {
        **base_payload,
        "is_offline_sync": True,
        "original_offline_mr": offline_mr,
    }
    try:
        response = supabase.table("patients").insert(extended).execute()
    except Exception:
        response = supabase.table("patients").insert(base_payload).execute()

    if not response.data:
        raise RuntimeError("Supabase returned no patient data after insert")
    return response.data[0]["mr_no"]


def _insert_test_result_to_supabase(supabase, online_mr, test_row: dict, patient_name: str):
    try:
        test_values = json.loads(test_row.get("test_values") or "{}")
    except Exception:
        test_values = {}

    payload = {
        "mr_no": online_mr,
        "patient_name": test_row.get("patient_name") or patient_name,
        "category": test_row.get("category"),
        "test_name": test_row.get("test_name"),
        "test_values": test_values,
        "status": test_row.get("status") or "Pending",
        "remarks": test_row.get("remarks") or "",
    }
    if test_row.get("created_at"):
        # Convert naive local datetime to timezone-aware ISO string to avoid Supabase UTC mismatch
        payload["created_at"] = _local_dt_to_iso(test_row.get("created_at")) or test_row.get("created_at")

    try:
        supabase.table("test_results_all").insert({**payload, "is_offline_sync": True}).execute()
    except Exception:
        supabase.table("test_results_all").insert(payload).execute()


def _sync_one_offline_patient(supabase, patient: dict, synced_by: str = "Admin"):
    if patient.get("synced"):
        return {"patient_id": patient["id"], "status": "skipped", "message": "Already synced"}

    offline_mr = str(patient.get("mr_no") or "")
    try:
        # 1. Do HTTP insert to Supabase for the patient first
        online_mr = _insert_patient_to_supabase(supabase, patient)

        # 2. Get test results for the patient from SQLite on a quick read connection
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM test_results_all WHERE mr_no = ? AND delete_status = 0",
                (offline_mr,),
            )
            test_rows = [dict(r) for r in cursor.fetchall()]

        # 3. Do HTTP inserts to Supabase for each test
        tests_synced = 0
        for test_row in test_rows:
            _insert_test_result_to_supabase(
                supabase, online_mr, test_row, patient.get("patient_name") or ""
            )
            tests_synced += 1

        # 4. Open a single SQLite write connection/transaction to update state and log success
        with get_db_conn() as conn:
            cursor = conn.cursor()
            for test_row in test_rows:
                cursor.execute(
                    "UPDATE test_results_all SET synced = 1 WHERE id = ?",
                    (test_row["id"],),
                )
            cursor.execute(
                "UPDATE patients SET synced = 1, online_mr = ?, sync_error = NULL WHERE id = ?",
                (online_mr, patient["id"]),
            )
            # Insert log on the same connection/transaction to avoid locks
            cursor.execute(
                """
                INSERT INTO mr_sync_log
                    (offline_mr, online_mr, patient_name, synced_by, status, tests_synced, error_message, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                """,
                (
                    offline_mr,
                    str(online_mr),
                    patient.get("patient_name"),
                    synced_by,
                    "synced",
                    tests_synced,
                    None,
                ),
            )
        return {
            "patient_id": patient["id"],
            "status": "synced",
            "offline_mr": offline_mr,
            "online_mr": online_mr,
            "tests_synced": tests_synced,
        }
    except Exception as e:
        err = str(e)
        logger.error(f"Sync error for patient {offline_mr}: {err}")
        try:
            with get_db_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE patients SET sync_error = ? WHERE id = ?",
                    (err[:500], patient["id"]),
                )
                cursor.execute(
                    """
                    INSERT INTO mr_sync_log
                        (offline_mr, online_mr, patient_name, synced_by, status, tests_synced, error_message, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                    """,
                    (
                        offline_mr,
                        None,
                        patient.get("patient_name"),
                        synced_by,
                        "error",
                        0,
                        err[:500],
                    ),
                )
        except Exception as db_err:
            logger.error(f"Failed to write sync error to SQLite: {db_err}")
        return {
            "patient_id": patient["id"],
            "status": "error",
            "offline_mr": offline_mr,
            "message": err,
        }


@app.get("/api/admin/offline-patients")
def api_admin_offline_patients(
    shift: str = None,
    date_from: str = None,
    date_to: str = None,
    sync_status: str = "all",
    search: str = None,
):
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM patients WHERE 1=1"
            params: list = []

            if search:
                like = f"%{search.strip()}%"
                query += " AND (patient_name LIKE ? OR mr_no LIKE ? OR CAST(online_mr AS TEXT) LIKE ?)"
                params.extend([like, like, like])

            if shift and shift.lower() != "all":
                query += " AND UPPER(COALESCE(shift, '')) = ?"
                params.append(shift.upper())

            if date_from:
                query += " AND DATE(created_at) >= ?"
                params.append(date_from)
            if date_to:
                query += " AND DATE(created_at) <= ?"
                params.append(date_to)

            status_filter = (sync_status or "all").lower()
            if status_filter == "pending":
                query += " AND synced = 0 AND (sync_error IS NULL OR sync_error = '')"
            elif status_filter == "synced":
                query += " AND synced = 1"
            elif status_filter == "error":
                query += " AND synced = 0 AND sync_error IS NOT NULL AND sync_error != ''"

            query += " ORDER BY created_at DESC"
            cursor.execute(query, params)
            patients = []
            for r in cursor.fetchall():
                p = dict(r)
                p["synced"] = bool(p.get("synced"))
                patients.append(p)

        unsynced = sum(1 for p in patients if not p["synced"])
        synced = sum(1 for p in patients if p["synced"])
        return {
            "status": "Success",
            "patients": patients,
            "counts": {"unsynced": unsynced, "synced": synced, "total": len(patients)},
        }
    except Exception as e:
        logger.error(f"offline-patients list failed: {e}")
        return {"status": "Error", "message": str(e), "patients": [], "counts": {}}


@app.post("/api/admin/offline-patients/sync-selected")
async def api_admin_offline_patients_sync_selected(request: Request):
    try:
        data = await request.json()
        patient_ids = data.get("patient_ids") or []
        synced_by = (data.get("synced_by") or "Admin").strip() or "Admin"

        if not isinstance(patient_ids, list) or not patient_ids:
            raise HTTPException(status_code=400, detail="Select at least one patient")

        ids = []
        for pid in patient_ids:
            try:
                ids.append(int(pid))
            except (TypeError, ValueError):
                continue
        if not ids:
            raise HTTPException(status_code=400, detail="Invalid patient selection")

        # 1. Fetch patient data first using a connection that closes immediately
        with get_db_conn() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(ids))
            cursor.execute(
                f"SELECT * FROM patients WHERE id IN ({placeholders})",
                ids,
            )
            rows = [dict(r) for r in cursor.fetchall()]
            by_id = {r["id"]: r for r in rows}

        # 2. Iterate and sync each patient with individual transactions/requests
        supabase = init_supabase()
        results = []
        synced_count = 0
        error_count = 0
        skipped_count = 0

        for pid in ids:
            patient = by_id.get(pid)
            if not patient:
                error_count += 1
                results.append({"patient_id": pid, "status": "error", "message": "Patient not found"})
                continue

            outcome = _sync_one_offline_patient(supabase, patient, synced_by=synced_by)
            results.append(outcome)
            if outcome["status"] == "synced":
                synced_count += 1
            elif outcome["status"] == "skipped":
                skipped_count += 1
            else:
                error_count += 1

        return {
            "status": "Success",
            "synced_count": synced_count,
            "errors_count": error_count,
            "skipped_count": skipped_count,
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"offline sync-selected failed: {e}")
        return {"status": "Error", "message": str(e), "synced_count": 0, "errors_count": 0}


@app.get("/api/admin/offline-sync-log")
def api_admin_offline_sync_log(search: str = None, limit: int = 200):
    try:
        logs = list_mr_sync_log(limit=min(limit, 500), search=search)
        return {"status": "Success", "logs": logs}
    except Exception as e:
        logger.error(f"offline-sync-log failed: {e}")
        return {"status": "Error", "message": str(e), "logs": []}


# ── Local SQLite Audit Trail & Print Tracking ─────────────────────────────────
@app.post("/api/audit/log-print")
async def api_audit_log_print(request: Request):
    try:
        data = await request.json()
        mr_no = str(data.get("mr_no") or "").strip()
        if not mr_no:
            return {"status": "Ignored", "message": "Missing MR number"}

        patient_name = data.get("patient_name")
        user_name = data.get("user_name") or "Staff"
        user_id = str(data.get("user_id") or "")
        details = data.get("details") or "Printed lab test report"
        pc_name = data.get("pc_name")

        print_count = insert_audit_log(
            mr_no=mr_no,
            patient_name=patient_name,
            action="PRINT",
            user_name=user_name,
            user_id=user_id,
            details=details,
            pc_name=pc_name,
        )
        return {"status": "Success", "print_count": print_count}
    except Exception as e:
        logger.error(f"Audit log print error: {e}")
        return {"status": "Error", "message": str(e)}


@app.get("/api/audit/list")
def api_audit_list(
    search: str = None,
    mr_no: str = None,
    user_name: str = None,
    action: str = None,
    date_from: str = None,
    date_to: str = None,
    limit: int = 200,
):
    try:
        logs = list_audit_trail(
            search=search,
            mr_no=mr_no,
            user_name=user_name,
            action=action,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return {"status": "Success", "logs": logs, "count": len(logs)}
    except Exception as e:
        logger.error(f"Audit list error: {e}")
        return {"status": "Error", "message": str(e), "logs": []}


# ── Automatic Background Sync Worker ─────────────────────────────────────────
_auto_sync_lock = threading.Lock()
_auto_sync_worker_started = False


def sync_pending_offline_patients_background(synced_by: str = "Auto-Sync") -> dict:
    """
    Check SQLite for any unsynced patients (synced = 0) and push them to Supabase
    automatically if internet / Supabase connectivity is available.
    """
    if not _auto_sync_lock.acquire(blocking=False):
        return {"status": "busy", "message": "Auto-sync already in progress"}

    try:
        # Check SQLite for pending patients
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM patients WHERE synced = 0 ORDER BY id ASC LIMIT 50")
            pending_patients = [dict(r) for r in cursor.fetchall()]

        if not pending_patients:
            return {"status": "ok", "synced_count": 0, "message": "No pending offline records"}

        # Attempt to initialize Supabase
        try:
            supabase = init_supabase()
            if not supabase:
                return {"status": "offline", "message": "Supabase client unavailable"}
        except Exception as se:
            logger.debug(f"[Auto-Sync] Supabase not reachable: {se}")
            return {"status": "offline", "message": str(se)}

        synced_count = 0
        error_count = 0
        logger.info(f"[Auto-Sync] Found {len(pending_patients)} pending patient(s). Pushing to Supabase...")

        for patient in pending_patients:
            try:
                outcome = _sync_one_offline_patient(supabase, patient, synced_by=synced_by)
                if outcome.get("status") == "synced":
                    synced_count += 1
                    logger.info(
                        f"[Auto-Sync] Synced offline MR {outcome.get('offline_mr')} -> Online MR {outcome.get('online_mr')}"
                    )
                elif outcome.get("status") == "error":
                    error_count += 1
            except Exception as pe:
                error_count += 1
                logger.error(f"[Auto-Sync] Failed to sync patient {patient.get('id')}: {pe}")

        logger.info(f"[Auto-Sync] Sync finished: {synced_count} synced, {error_count} errors.")
        return {"status": "Success", "synced_count": synced_count, "errors_count": error_count}
    except Exception as e:
        logger.error(f"[Auto-Sync] Worker error: {e}")
        return {"status": "Error", "message": str(e)}
    finally:
        _auto_sync_lock.release()


def _auto_sync_daemon_loop():
    """Periodically check and push pending offline records every 25 seconds."""
    time.sleep(3)  # Short pause on startup
    while True:
        try:
            sync_pending_offline_patients_background(synced_by="Auto-Sync")
        except Exception as e:
            logger.debug(f"[Auto-Sync Loop] error: {e}")
        time.sleep(25)


def start_offline_auto_sync_worker():
    global _auto_sync_worker_started
    if not _auto_sync_worker_started:
        _auto_sync_worker_started = True
        worker_thread = threading.Thread(
            target=_auto_sync_daemon_loop,
            daemon=True,
            name="OfflineAutoSyncWorker"
        )
        worker_thread.start()
        logger.info("Offline background auto-sync worker started (interval: 25s).")


@app.post("/api/offline/auto-sync-now")
def api_offline_auto_sync_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(sync_pending_offline_patients_background, synced_by="User-Triggered")
    return {"status": "Success", "message": "Auto-sync triggered in background"}


# Start background worker on module load
start_offline_auto_sync_worker()

