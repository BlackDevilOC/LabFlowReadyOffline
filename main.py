import os
import sys
import json
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from schemas import ChangeVisiblity, GetAllDataFromRegPage, FitnessPatientSchema
from dbActions import GetAllBasicAndTestInfo, LoadTestGroups, getPatientBasicInfoAll, getPatientBasicInfoLimit, load_patient,load_tests, loadPrintSettings, loginUsers,register_new_patient,add_tests_to_patient, SaveTestResult, save_fitness_record_db, save_fitness_record_json, sync_single_record_bg, sync_offline_records, get_fitness_records, add_tests_to_patient_all, list_users_admin, create_user_admin, update_user_admin, authenticate_user, generate_patient_pin, resolve_selected_test_display_names, sync_invoice_settings_cache, sync_lab_print_settings_cache, sync_user_preferences_cache, sync_remarks_cache, record_remark_usage, list_remarks_admin, create_remark_admin, update_remark_admin, delete_remark_admin, list_shifts_admin, create_shift_admin, update_shift_admin, delete_shift_admin, list_login_users, get_lab_print_settings_admin, update_lab_print_settings_admin
from user_access import PERMISSION_KEYS, PERMISSION_LABELS, DEFAULT_PERMISSIONS
from payloads import split_patient_and_tests
from logdata import save_log, logger, get_all_logs, log_error, get_system_stats
from dbActions import init_supabase
from search_utils import parse_advanced_filters, row_matches_advanced_filters
from patient_list_query import fetch_test_result_list_rows, BROWSE_PATIENT_LIMIT
from analytics_router import router as analytics_router
from replica_engine import get_replica_engine

try:
    from offline.database import insert_audit_log, list_audit_trail
except Exception:
    try:
        # pyrefly: ignore [missing-import]
        from database import insert_audit_log, list_audit_trail
    except Exception:
        insert_audit_log = None
        list_audit_trail = None

def get_base_path():
    if getattr(sys, 'frozen', False):
        # Running as a bundled executable
        base = sys._MEIPASS # type: ignore
        logger.info(f"Frozen mode detected. _MEIPASS: {base}")
        # In some cases, static/templates might be one level up or in _internal
        if not os.path.exists(os.path.join(base, "static")):
            alt_base = os.path.dirname(sys.executable)
            if os.path.exists(os.path.join(alt_base, "static")):
                return alt_base
        return base
    return os.path.dirname(os.path.abspath(__file__))

base_path = get_base_path()

# initialization of fastapi and database
app = FastAPI(title="LabFlow API")
app.include_router(analytics_router)

# Ensure directories exist or log error
static_dir = os.path.join(base_path, "static")
templates_dir = os.path.join(base_path, "templates")

if not os.path.exists(static_dir):
    logger.error(f"CRITICAL: Static directory not found at {static_dir}")
if not os.path.exists(templates_dir):
    logger.error(f"CRITICAL: Templates directory not found at {templates_dir}")

fetcheddata_dir = os.path.join(base_path, "fetcheddata")
os.makedirs(fetcheddata_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.mount("/fetcheddata", StaticFiles(directory=fetcheddata_dir), name="fetcheddata")
templates = Jinja2Templates(directory=templates_dir)
templates.env.globals["is_offline"] = False
templates.env.globals["url_prefix"] = ""

_orig_main_template_response = templates.TemplateResponse

def _safe_main_template_response(*args, **kwargs):
    if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], dict):
        name = args[0]
        context = args[1]
        req = context.get("request") or kwargs.get("request")
        return _orig_main_template_response(request=req, name=name, context=context)
    elif len(args) == 1 and isinstance(args[0], str):
        name = args[0]
        context = kwargs.get("context", {})
        req = kwargs.get("request") or context.get("request")
        return _orig_main_template_response(request=req, name=name, context=context)
    return _orig_main_template_response(*args, **kwargs)

templates.TemplateResponse = _safe_main_template_response

# Mount legacy offline app under /offline if available
try:
    from offline.app import app as offline_app
    app.mount("/offline", offline_app)
except Exception:
    logger.info("Legacy offline module not mounted (running in direct local PostgreSQL mode).")

logger.info(f"App started. Assets path: {base_path}")


@app.get("/api/health")
def api_health():
    """Fast readiness probe for desktop splash → login handoff."""
    return {"ok": True}


from db_switcher import get_current_db_status, switch_database_target, run_full_diagnostics


@app.middleware("http")
async def security_desktop_middleware(request: Request, call_next):
    path = request.url.path
    if (
        path == "/login"
        or path == "/logout"
        or path == "/api/health"
        or path.startswith("/static")
        or path.startswith("/fetcheddata")
        or path.startswith("/offline")
        or path.startswith("/api/emergency-dr")
        or path.startswith("/page/emergency-dr")
        or path.startswith("/offline/page/emergency-dr")
        or path.startswith("/api/database")
        or path.startswith("/api/admin/replica")
    ):
        return await call_next(request)

    user_agent = request.headers.get("user-agent", "")
    is_desktop = "LabFlowDesktopApp" in user_agent
    is_logged_in = request.cookies.get("isLoggedIn") == "true" or request.cookies.get("userEmail")

    if not is_desktop and not is_logged_in:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/login", status_code=302)

    return await call_next(request)


# ----------------- Database Switcher & Diagnostics APIs -----------------

@app.get("/api/database/status")
def api_database_status():
    """Returns current active database target and connection configuration."""
    return get_current_db_status()


@app.post("/api/database/switch")
async def api_database_switch(request: Request):
    """Manually switches active database to primary, secondary, or offline with master password."""
    try:
        data = await request.json()
        target = data.get("target", "")
        password = data.get("password", "")
        result = switch_database_target(target, password)
        if result.get("status") == "error":
            status_code = 403 if "password" in result.get("message", "").lower() or "denied" in result.get("message", "").lower() else 400
            return JSONResponse(status_code=status_code, content=result)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.post("/api/emergency-dr/diagnose")
def api_emergency_dr_diagnose():
    """Runs live health probes across primary cloud, secondary cloud, and local replica."""
    return run_full_diagnostics()


@app.post("/api/emergency-dr/switch")
async def api_emergency_dr_switch(request: Request):
    """Alias for /api/database/switch."""
    return await api_database_switch(request)



LAB_CATEGORIES = [
    "Hematology",
    "Biochemistry",
    "Serology",
    "Microbiology",
    "PCR",
    "Microscopic Examination",
    "Urine Analysis",
    "Stool Analysis",
    "Hormones / Endocrine",
    "Immunology",
    "Coagulation",
    "Tumor Markers",
    "Fluid Analysis",
    "Histopathology",
    "Cytology",
    "Group Test",
    "General",
]

PATIENT_LIST_SELECT = (
    "id,mr_no,patient_name,test_name,category,status,created_at,remarks,"
    "patients(relation,relation_name,age,gender,shift,mobile,patient_token,user,user_id)"
)


def _flatten_patient_test_row(item: dict, shift_filter: str = None) -> dict | None:
    p = item.get("patients") or {}
    item_shift = p.get("shift") or ""
    if shift_filter and shift_filter != "all" and item_shift.lower() != shift_filter.lower():
        return None
    item["relation_type"] = p.get("relation") or ""
    item["relation_name"] = p.get("relation_name") or ""
    item["gender"] = p.get("gender") or "Male"
    item["age"] = p.get("age") or ""
    item["shift"] = item_shift
    item["mobile"] = p.get("mobile") or ""
    item["patient_token"] = p.get("patient_token") or ""
    item["user"] = p.get("user") or ""
    item["user_id"] = p.get("user_id")
    item["synced"] = item.get("status") == "Completed"
    return item


# basic home page and other pages route 
@app.get('/',)
def home(request:Request):
    logger.debug("Accessing Home Page")
    return templates.TemplateResponse('home.html',{"request": request,"title":"Home Page","name":"Rehan","user_bane":"rehan@gmail.com"})

@app.get('/login', include_in_schema=False)
def login_page(request: Request):
    logger.debug("Accessing Login Page")
    return templates.TemplateResponse('login.html', {"request": request, "is_offline": False})

@app.get('/logout', include_in_schema=False)
def logout(request: Request):
    logger.info("User requested logout")
    return RedirectResponse(url="/login")

@app.get('/register', include_in_schema=False)
def register(request: Request):
    logger.debug("Accessing Registration Page (New Checkbox UI default)")
    return templates.TemplateResponse('register_new_ui.html', {"request": request, "title": "Patient Registration", "name": "Rehan"})

@app.get('/register-new', include_in_schema=False)
def register_new_ui(request: Request):
    logger.debug("Accessing New Checkbox Registration Page")
    return templates.TemplateResponse('register_new_ui.html', {"request": request, "title": "Patient Registration", "name": "Rehan"})

@app.get('/register-classic', include_in_schema=False)
def register_classic(request: Request):
    logger.debug("Accessing Classic Dropdown Registration Page")
    return templates.TemplateResponse('register.html', {"request": request, "title": "Patient Registration (Classic)", "name": "Rehan", "test_total_to_display": 8})


@app.get('/update-results', include_in_schema=False)
def update_results(request: Request):
    logger.debug("Accessing Update Results Page")
    return templates.TemplateResponse('update_results.html', {"request": request, "title": "Update Test Results", "name": "Rehan"})

@app.get("/page/enter-results/{record_id}", include_in_schema=False)
def enter_results_page(request: Request, record_id: int):
    logger.info(f"Accessing Enter Results Page for record ID: {record_id}")
    return templates.TemplateResponse('enter_results.html', {"request": request, "title": "Enter Test Results", "record_id": record_id})


@app.get("/page/enter-results-patient/{mr_no}", include_in_schema=False)
def enter_results_patient_page(request: Request, mr_no: int):
    logger.info(f"Accessing Enter Patient Results Page for MR No: {mr_no}")
    return templates.TemplateResponse('enter_results_patient.html', {"request": request, "title": "Enter Patient Results", "mr_no": mr_no})



@app.get("/page/PatientTests/{patient_id}",include_in_schema=False)
def patientTestReportsPage(request:Request,patient_id:int):
    logger.info(f"Generating Test Report Page for patient: {patient_id}")
    return templates.TemplateResponse('patient_report.html', {"request": request,"patient_id":patient_id})


@app.get("/page/register/patientinvoice/{patient_id}",include_in_schema=False)
def patientInvoiceGanerate(request: Request, patient_id: int, tests: str = "", pin: str = ""):
    logger.info(f"Generating Invoice for patient: {patient_id}")
    return templates.TemplateResponse(
        "patient_invoice.html",
        {
            "request": request,
            "title": "Patient Receipt",
            "name": "Rehan",
            "patient_id": patient_id,
            "invoice_tests": tests,
            "invoice_pin": pin,
        },
    )

#Page to go for fitness static page 
@app.get("/page/fitness",include_in_schema=False)
def fitness(request:Request, background_tasks: BackgroundTasks):
    logger.info(f"Generating Fitness report page")
    background_tasks.add_task(sync_offline_records, "System")
    return templates.TemplateResponse('fitness.html', {"request": request, "title": "Fitness Report", "name": "Rehan"})

#Page to view fitness records
@app.get("/page/fitness-records", include_in_schema=False)
def fitness_records_page(request: Request):
    logger.info("Accessing Fitness Records page")
    return templates.TemplateResponse('fitness_records.html', {"request": request, "title": "Fitness Records", "name": "Rehan"})


@app.get("/page/lab-print-records", include_in_schema=False)
def lab_print_records_page(request: Request):
    logger.info("Accessing Lab Print Records page")
    return templates.TemplateResponse('lab_print_records.html', {"request": request, "title": "Lab Print Records", "name": "Rehan"})


@app.get("/page/lab-test-print/{mr_no}", include_in_schema=False)
def lab_test_print_preview_page(request: Request, mr_no: int, date: str = None):
    """
    Simple Lab Test print preview (grouped by category).
    `date` is optional (YYYY-MM-DD) and filters records on created_at.
    """
    logger.info(f"Accessing Lab Test Print Preview for MR: {mr_no}, date={date}")
    return templates.TemplateResponse(
        'lab_test_print_preview.html',
        {"request": request, "title": "Lab Test Print Preview", "mr_no": mr_no, "date": date or ""}
    )


@app.get("/page/fast-results", include_in_schema=False)
def fast_update_results_page(request: Request):
    logger.info("Accessing Fast Results Entry workspace")
    return templates.TemplateResponse(
        'fast_update_results.html',
        {"request": request, "title": "Fast Results Entry", "name": "User", "hide_sidebar": True}
    )


@app.get("/page/fast-print", include_in_schema=False)
def fast_print_records_page(request: Request):
    logger.info("Accessing Fast Print Stream workspace")
    return templates.TemplateResponse(
        'fast_print_records.html',
        {"request": request, "title": "Fast Print Stream", "name": "User", "hide_sidebar": True}
    )


@app.get("/page/print-records", include_in_schema=False)
def print_records_hub_page(request: Request):
    return RedirectResponse(url="/page/lab-print-records", status_code=302)


@app.get("/page/sync-history", include_in_schema=False)
def sync_history_page(request: Request):
    return templates.TemplateResponse('mr_sync_history.html', {
        "request": request,
        "title": "MR Sync History",
        "name": "User",
        "is_offline": False,
        "url_prefix": ""
    })


@app.get("/api/admin/offline-sync-log")
def api_admin_offline_sync_log(search: str = None, limit: int = 200):
    try:
        from offline.database import list_mr_sync_log
        logs = list_mr_sync_log(limit=min(limit, 500), search=search)
        return {"status": "Success", "logs": logs}
    except Exception as e:
        logger.error(f"offline-sync-log failed: {e}")
        return {"status": "Error", "message": str(e), "logs": []}

@app.get("/api/fitness/records")
def get_fitness_records_api(
    request: Request,
    password: str = None,
    date_from: str = None,
    date_to: str = None,
    search: str = None,
    filters: str = None,
):
    provided_pwd = password or request.headers.get("x-fitness-password")
    if not provided_pwd or provided_pwd.strip() != "admin":
        return JSONResponse(status_code=401, content={"status": "error", "message": "Invalid password for fitness records", "records": [], "total": 0})

    try:
        adv_filters = parse_advanced_filters(filters)
        records = get_fitness_records(
            date_from=date_from,
            date_to=date_to,
            search=None if adv_filters else search,
        )
        if adv_filters:
            records = [
                r for r in records
                if row_matches_advanced_filters(r, adv_filters, legacy_search=search)
            ]
        return {"status": "ok", "records": records, "total": len(records)}
    except Exception as e:
        log_error(e, "API_GET_FITNESS_RECORDS")
        return {"status": "error", "records": [], "total": 0}


@app.get("/api/print-records")
def get_print_records_api(
    date_from: str = None,
    date_to: str = None,
    search: str = None,
    filters: str = None,
    record_type: str = "all",
    status: str = None,
    shift: str = None,
    category: str = None,
    limit: int = 500,
):
    """Combined fitness + lab rows for Print Records page (print actions wired later)."""
    try:
        combined = []
        rtype = (record_type or "all").lower()
        adv_filters = parse_advanced_filters(filters)

        if rtype in ("all", "fitness"):
            for r in get_fitness_records(date_from=date_from, date_to=date_to, search=search):
                if adv_filters and not row_matches_advanced_filters(r, adv_filters, legacy_search=None):
                    continue
                combined.append({
                    "record_type": "fitness",
                    "id": r.get("id"),
                    "mr_no": r.get("mr_no"),
                    "patient_name": r.get("patient_name"),
                    "report_date": r.get("report_date"),
                    "created_at": r.get("created_at"),
                    "relation_type": r.get("relation_type"),
                    "relation_name": r.get("relation_name"),
                    "gender": r.get("gender"),
                    "synced": r.get("synced", True),
                    "status": "Saved" if r.get("synced") else "Pending",
                    "report_label": "Fitness",
                    "raw": r,
                })

        if rtype in ("all", "lab"):
            supabase = init_supabase()
            rows, _meta = fetch_test_result_list_rows(
                supabase,
                lambda item, _shift: _flatten_patient_test_row(item, None),
                search=search,
                filters=filters,
                date_from=date_from,
                date_to=date_to,
                status=status,
                shift=shift,
                category=category,
                browse_patient_limit=BROWSE_PATIENT_LIMIT,
            )
            for row in rows:
                if status and status != "all":
                    want = "Completed" if status in ("synced", "completed") else "Pending"
                    if row.get("status") != want:
                        continue
                combined.append({
                    "record_type": "lab",
                    "id": row.get("id"),
                    "mr_no": row.get("mr_no"),
                    "patient_name": row.get("patient_name"),
                    "created_at": row.get("created_at"),
                    "relation_type": row.get("relation_type"),
                    "relation_name": row.get("relation_name"),
                    "shift": row.get("shift"),
                    "patient_token": row.get("patient_token"),
                    "synced": row.get("status") == "Completed",
                    "status": row.get("status"),
                    "test_name": row.get("test_name"),
                    "category": row.get("category"),
                    "remarks": (row.get("remarks") or "").strip(),
                    "report_label": row.get("test_name") or "Lab",
                    "raw": row,
                })

        combined.sort(key=lambda x: (x.get("created_at") or x.get("report_date") or ""), reverse=True)
        return {"status": "ok", "records": combined, "total": len(combined)}
    except Exception as e:
        log_error(e, "API_PRINT_RECORDS")
        return {"status": "error", "records": [], "total": 0}


@app.get("/api/lab/print/{mr_no}")
def api_lab_print_payload(mr_no: int, date: str = None):
    """
    Build lab print payload from test_results_all + patients table.
    Returns patient header info and a list of records for the preview renderer.
    """
    try:
        supabase = init_supabase()

        patient_resp = supabase.table("patients").select("*").eq("mr_no", mr_no).single().execute()
        patient = patient_resp.data or {}

        q = supabase.table("test_results_all").select("*").eq("mr_no", mr_no).eq("delete_status", False)
        if date:
            q = q.gte("created_at", f"{date}T00:00:00Z").lte("created_at", f"{date}T23:59:59Z")
        tests_resp = q.order("created_at", desc=False).execute()
        rows = tests_resp.data or []

        # Normalize output for frontend
        normalized = []
        for r in rows:
            row = _normalize_test_result_row(dict(r))
            normalized.append({
                "id": row.get("id"),
                "category": row.get("category") or "General",
                "test_name": row.get("test_name") or "Test",
                "test_values": row.get("test_values") or {},
                "remarks": (row.get("remarks") or "").strip(),
                "created_at": row.get("created_at"),
                "status": row.get("status") or "Pending",
            })
        # Build group parameter order map from test_groups in DB
        group_orders = {}
        try:
            tg_resp = supabase.table("test_groups").select("group_name, component_ids").execute()
            t_resp = supabase.table("tests").select("id, name").execute()
            test_names_by_id = {t["id"]: t["name"] for t in (t_resp.data or []) if t.get("id") and t.get("name")}
            for g in (tg_resp.data or []):
                g_name = (g.get("group_name") or "").strip()
                c_ids = g.get("component_ids") or []
                if g_name and c_ids:
                    group_orders[g_name] = [test_names_by_id.get(cid) for cid in c_ids if test_names_by_id.get(cid)]
        except Exception:
            pass

        return {"status": "ok", "patient": patient, "tests": normalized, "group_orders": group_orders}
    except Exception as e:
        log_error(e, "API_LAB_PRINT_PAYLOAD")
        return {"status": "error", "patient": None, "tests": [], "group_orders": {}}


@app.get("/api/admin/lab-categories")
def admin_lab_categories():
    return {"status": "Success", "categories": LAB_CATEGORIES}

#Page to view Fluid Reports Hub
@app.get("/page/fluid-reports", include_in_schema=False)
def fluid_reports_hub(request: Request):
    logger.info("Accessing Fluid Reports Hub")
    return templates.TemplateResponse('fluid_reports.html', {"request": request, "title": "Fluid Reports Hub", "name": "Rehan"})

#Page to go for Ascitic Fluid DR static report page
@app.get("/page/ascitic-fluid", include_in_schema=False)
def ascitic_fluid(request: Request):
    logger.info(f"Generating Ascitic Fluid DR report page")
    return templates.TemplateResponse('ascitic_fluid.html', {"request": request, "title": "Ascitic Fluid DR Report", "name": "Rehan"})

#Page to go for CSF DR static report page
@app.get("/page/csf-fluid", include_in_schema=False)
def csf_fluid(request: Request):
    logger.info(f"Generating CSF DR report page")
    return templates.TemplateResponse('csf_fluid.html', {"request": request, "title": "CSF DR Report", "name": "Rehan"})

#Page to go for Pleural Fluid For DR static report page
@app.get("/page/pleural-fluid", include_in_schema=False)
def pleural_fluid(request: Request):
    logger.info(f"Generating Pleural Fluid For DR report page")
    return templates.TemplateResponse('pleural_fluid.html', {"request": request, "title": "Pleural Fluid For DR Report", "name": "Rehan"})


@app.get("/page/analytics", include_in_schema=False)
def analytics_dashboard(request: Request, view: str = "overview"):
    """Analytics, Telemetry & Reporting Suite for Pathologist Incharge."""
    return templates.TemplateResponse(
        "analytics_dashboard.html",
        {
            "request": request,
            "title": "LabFlow Analytics",
            "name": "Rehan",
            "current_view": view if view in ("overview", "telemetry", "tests") else "overview",
            "hide_sidebar": True,
        },
    )


@app.get("/page/admin", include_in_schema=False)
def admin_panel(request: Request, view: str = "overview", date: str = None):
    """
    Enhanced Admin panel with multiple views and date filtering.
    """
    # Offline admin pages use SQLite + offline APIs — always serve from /offline mount
    if view.startswith("offline-"):
        from urllib.parse import urlencode
        return RedirectResponse(
            url="/offline/page/admin?" + urlencode(dict(request.query_params)),
            status_code=302,
        )

    try:
        stats = get_system_stats()
        
        admin_config_views = (
            "tests", "tests-edit", "test-selection", "test-suggestions", "users", "shifts", "remarks", "print-settings", "cloud-sync", "audit-trail", "replica", "junk-cleaner",
        )
        if view in admin_config_views:
            return templates.TemplateResponse('admin_panel.html', {
                "request": request,
                "title": f"Admin - {view.replace('-', ' ').title()}",
                "name": "Admin",
                "logs": [],
                "stats": stats,
                "current_view": view,
                "current_date": date,
                "admin_email": "rehan031579@gmail.com",
                "lab_categories": LAB_CATEGORIES,
                "permission_keys": PERMISSION_KEYS,
                "permission_labels": PERMISSION_LABELS,
                "default_permissions": DEFAULT_PERMISSIONS,
                "is_offline": False,
                "url_prefix": "",
                "hide_sidebar": True
            })
        
        if view == "errors":
            logs = get_all_logs(level_filter="ERROR", date_filter=date)
        elif view == "logs":
            logs = get_all_logs(date_filter=date)
        elif view == "system":
            logs = []
        else: # overview
            logs = get_all_logs(date_filter=date)[:20]
            
        return templates.TemplateResponse('admin_panel.html', {
            "request": request, 
            "title": f"Admin - {view.capitalize()}", 
            "name": "Admin",
            "logs": logs,
            "stats": stats,
            "current_view": view,
            "current_date": date,
            "admin_email": "rehan031579@gmail.com",
            "lab_categories": LAB_CATEGORIES,
            "permission_keys": PERMISSION_KEYS,
            "permission_labels": PERMISSION_LABELS,
            "default_permissions": DEFAULT_PERMISSIONS,
            "is_offline": False,
            "url_prefix": "",
            "hide_sidebar": True
        })
    except Exception as e:
        log_error(e, "ADMIN_PANEL_RECOVERY")
        return templates.TemplateResponse('admin_panel.html', {
            "request": request, 
            "title": "Admin Console", 
            "name": "Admin",
            "logs": [], 
            "stats": {
                "total": 0,
                "errors": 0,
                "warnings": 0,
                "unique_pcs": 0,
                "categories": {},
            },
            "current_view": "overview",
            "admin_email": "rehan031579@gmail.com",
            "lab_categories": LAB_CATEGORIES,
            "permission_keys": PERMISSION_KEYS,
            "permission_labels": PERMISSION_LABELS,
            "default_permissions": DEFAULT_PERMISSIONS,
            "is_offline": False,
            "url_prefix": "",
            "hide_sidebar": True
        })


@app.get("/page/emergency-dr")
@app.get("/offline/page/emergency-dr")
def page_emergency_dr(request: Request):
    """Dedicated full-screen Disaster Recovery and Live Diagnostic Console."""
    return templates.TemplateResponse(request=request, name="emergency_dr.html", context={"title": "Disaster Recovery Console"})




def get_current_user(request: Request, form_data: dict = None):
    """
    Helper to extract user context.
    Checks headers first, then form data.
    """
    user = request.headers.get("X-User-Email")
    if not user and form_data:
        user = form_data.get("user_email")
    return user or "Anonymous"

# --------------------------------- working apis--------------------

@app.post("/register/patient")
async def register_patient(request: Request, background_tasks: BackgroundTasks):
    try:
        form = await request.form()
        data = dict(form)
        user = get_current_user(request, form_data=data)
        save_log(f"Received registration request for: {data.get('patient_name')}", category="REGISTRATION", user=user)
        
        item = GetAllDataFromRegPage(**data) # type: ignore
        patient, tests = split_patient_and_tests(item)
        if not patient.get("user"):
            patient["user"] = user.split("@")[0] if "@" in str(user) else str(user)
        if not patient.get("user_id") and user and str(user) != "Anonymous":
            try:
                lookup = init_supabase().table("users").select("id").eq("email", user).limit(1).execute()
                if lookup.data:
                    patient["user_id"] = lookup.data[0]["id"]
            except Exception:
                pass

        if not patient.get("user_id"):
            patient["user_id"] = 1

        patient_pin = generate_patient_pin()
        patient["pwd"] = patient_pin

        patient_id, patient_mr_no = register_new_patient(patient, user=user)
        if patient_id:
            logger.info(f"Patient registered. ID: {patient_id}, MR: {patient_mr_no}. Queuing test creation in background...")

            selected_tests = [
                item.test_1,
                item.test_2,
                item.test_3,
                item.test_4,
                item.test_5,
                item.test_6,
                item.test_7,
                item.test_8,
            ]
            test_display_names = resolve_selected_test_display_names(selected_tests)

            background_tasks.add_task(
                add_tests_to_patient_all,
                patient_id,
                patient_mr_no,
                patient["patient_name"],
                selected_tests,
                user,
            )

            save_log(f"New patient registered: {patient_mr_no}", category="AUTH_SUCCESS", user=user)

            # Record local audit trail entry
            try:
                if insert_audit_log:
                    insert_audit_log(
                        mr_no=str(patient_mr_no),
                        patient_name=patient.get("patient_name"),
                        action="REGISTER",
                        user_name=str(user).split("@")[0] if user else "Staff",
                        details=f"Registered patient with {len(test_display_names)} test(s): {', '.join(test_display_names[:6])}{'...' if len(test_display_names) > 6 else ''} (Shift: {item.shift})",
                    )
            except Exception as a_err:
                logger.debug(f"Audit log on register error: {a_err}")

            query = urlencode(
                {
                    "tests": "|".join(test_display_names),
                    "pin": patient_pin,
                }
            )
            return RedirectResponse(
                url=f"/page/register/patientinvoice/{patient_id}?{query}",
                status_code=303,
            )
        else:
            log_error("Registration failed - no patient_id returned from DB", category="DB_ERROR", user=user)
            raise HTTPException(status_code=500, detail="Database registration failed")
            
    except Exception as e:
        log_error(e, "API_REGISTER_PATIENT", user=user)
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/api/update/result") 
async def save_results_to_db(request: Request):
    user = get_current_user(request)
    try:
        data = await request.json()
        save_log(f"Updating results for {len(data)} items", category="UPDATES", user=user)
        for i in data:
            id = i["id"]
            result = i["result_value"]
            SaveTestResult(id,result)
        save_log(f"Updated {len(data)} test results", category="DATA_MODIFICATION", user=user)
        return {"Status": "Success", "Count": len(data)}
    except Exception as e:
        log_error(e, "API_UPDATE_RESULT", user=user)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fitness/save")
async def save_fitness_patient(item: FitnessPatientSchema, request: Request, background_tasks: BackgroundTasks):
    user = get_current_user(request, form_data=item.model_dump())
    payload = item.model_dump()
    try:
        # Save to local JSON first (this is guaranteed and synchronous)
        filename = save_fitness_record_json(payload)
        
        # Enqueue the actual database insertion and scan for other offline records
        background_tasks.add_task(sync_single_record_bg, payload, filename, user)
        background_tasks.add_task(sync_offline_records, user)
        
        return {"status": "Success", "message": "Record queued locally"}
    except Exception as e:
        log_error(e, "API_SAVE_FITNESS", user=user)
        raise HTTPException(status_code=500, detail=str(e))



TEST_SELECTION_CONFIG_PATH = os.path.join(fetcheddata_dir, "test_selection_config.json")
TEST_SUGGESTIONS_CONFIG_PATH = os.path.join(fetcheddata_dir, "test_value_suggestions.json")

def get_test_selection_config():
    if os.path.exists(TEST_SELECTION_CONFIG_PATH):
        try:
            with open(TEST_SELECTION_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "allow_single_tests": False,
        "mode": "group_only",
        "categories_order": ["Popular", "Regular", "Group Test"],
        "custom_categories": {},
        "category_items_order": {},
        "popular_order": [],
        "regular_preset": [],
        "auto_select_regular": False
    }

def save_test_selection_config(config_data: dict):
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with open(TEST_SELECTION_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

def get_test_suggestions_config() -> dict:
    if os.path.exists(TEST_SUGGESTIONS_CONFIG_PATH):
        try:
            with open(TEST_SUGGESTIONS_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "by_test_name": {},
        "by_param_name": {},
        "presets": []
    }

def save_test_suggestions_config(config_data: dict) -> None:
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with open(TEST_SUGGESTIONS_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

@app.get("/api/admin/test-selection-config")
def api_get_test_selection_config():
    cfg = get_test_selection_config()
    # Migration helper for old regular_preset if quick_presets missing
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
    if "category_items_order" not in cfg:
        cfg["category_items_order"] = {}
    if "popular_order" not in cfg and "Popular" in cfg.get("category_items_order", {}):
        cfg["popular_order"] = cfg["category_items_order"]["Popular"]
    return {"status": "Success", **cfg}

@app.post("/api/admin/test-selection-config")
def api_save_test_selection_config(payload: dict):
    existing = get_test_selection_config()
    mode = payload.get("mode", existing.get("mode", "group_only"))
    allow_single = (mode == "group_and_single") or bool(payload.get("allow_single_tests", existing.get("allow_single_tests", False)))
    
    quick_presets = payload.get("quick_presets")
    if quick_presets is None:
        # Fallback to old structure if legacy payload passed
        old_preset = payload.get("regular_preset", existing.get("regular_preset", []))
        auto_sel = bool(payload.get("auto_select_regular", existing.get("auto_select_regular", False)))
        quick_presets = [{
            "id": "preset_regular",
            "name": "Regular Package",
            "tests": old_preset,
            "auto_select": auto_sel
        }] if old_preset else []

    category_items_order = payload.get("category_items_order", existing.get("category_items_order", {}))
    popular_order = payload.get("popular_order", category_items_order.get("Popular", existing.get("popular_order", [])))
    if popular_order and "Popular" not in category_items_order:
        category_items_order["Popular"] = popular_order

    new_config = {
        "allow_single_tests": allow_single,
        "mode": "group_and_single" if allow_single else "group_only",
        "categories_order": payload.get("categories_order", existing.get("categories_order", ["Popular", "Regular", "Group Test"])),
        "custom_categories": payload.get("custom_categories", existing.get("custom_categories", {})),
        "category_items_order": category_items_order,
        "popular_order": popular_order,
        "quick_presets": quick_presets,
        "category_styles": payload.get("category_styles", existing.get("category_styles", {})),
        "regular_preset": payload.get("regular_preset", existing.get("regular_preset", [])),
        "auto_select_regular": bool(payload.get("auto_select_regular", existing.get("auto_select_regular", False)))
    }
    save_test_selection_config(new_config)
    return {"status": "Success", "config": new_config}


# Quick result suggestions APIs
@app.get("/api/admin/test-suggestions")
def api_get_test_suggestions():
    return {"status": "Success", "suggestions": get_test_suggestions_config()}


@app.post("/api/admin/test-suggestions")
async def api_save_test_suggestions(request: Request):
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")
        save_test_suggestions_config(data)
        actor = get_current_user(request, form_data=data)
        logger.info(f"Test value suggestions updated by {actor}")
        return {"status": "Success", "message": "Test value suggestions saved successfully", "suggestions": data}
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "API_SAVE_TEST_SUGGESTIONS")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/test-suggestions/{target_type}/{target_key}")
def api_delete_test_suggestion(target_type: str, target_key: str, request: Request):
    try:
        cfg = get_test_suggestions_config()
        if target_type == "test":
            cfg.get("by_test_name", {}).pop(target_key, None)
        elif target_type == "param":
            cfg.get("by_param_name", {}).pop(target_key, None)
        save_test_suggestions_config(cfg)
        return {"status": "Success", "message": f"Deleted suggestion for {target_key}", "suggestions": cfg}
    except Exception as e:
        log_error(e, "API_DELETE_TEST_SUGGESTION")
        raise HTTPException(status_code=500, detail=str(e))


#  load tests from db 
@app.get("/tests")
def load_test():
    try:
        result = load_tests()
        cfg = get_test_selection_config()
        result["allow_single_tests"] = cfg.get("allow_single_tests", False)
        result["test_selection_mode"] = cfg.get("mode", "group_only")
        result["categories_order"] = cfg.get("categories_order", [])
        result["custom_categories"] = cfg.get("custom_categories", {})
        result["category_items_order"] = cfg.get("category_items_order", {})
        result["popular_order"] = cfg.get("popular_order", cfg.get("category_items_order", {}).get("Popular", []))
        result["regular_preset"] = cfg.get("regular_preset", [])
        result["auto_select_regular"] = cfg.get("auto_select_regular", False)
        
        # New multiple quick presets & category styles
        quick_presets = cfg.get("quick_presets")
        if quick_presets is None and cfg.get("regular_preset"):
            quick_presets = [{
                "id": "preset_regular",
                "name": "Regular Package",
                "tests": cfg.get("regular_preset", []),
                "auto_select": cfg.get("auto_select_regular", False)
            }]
        result["quick_presets"] = quick_presets or []
        result["category_styles"] = cfg.get("category_styles", {})
        return result
    except Exception as e:
        log_error(e, "API_LOAD_TESTS")
        return {
            "tests": [],
            "group_test": [],
            "allow_single_tests": False,
            "test_selection_mode": "group_only",
            "categories_order": [],
            "custom_categories": {},
            "category_items_order": {},
            "popular_order": [],
            "regular_preset": [],
            "auto_select_regular": False,
            "quick_presets": [],
            "category_styles": {}
        }

# fetch all the basic patient info to display in update test result page
@app.get("/api/patient/basic/all")
def get_patient_basic_info_all(
    search: str = None,
    filters: str = None,
    date_from: str = None,
    date_to: str = None,
    status: str = None,
    shift: str = None,
    category: str = None
):
    try:
        supabase = init_supabase()
        adv_filters = parse_advanced_filters(filters)
        query = supabase.table("test_results_all").select("*, patients(*)").eq("delete_status", False)
        
        if search and not adv_filters:
            search_str = search.strip()
            if search_str.isdigit():
                query = query.eq("mr_no", int(search_str))
            else:
                query = query.ilike("patient_name", f"%{search_str}%")
                
        if date_from:
            query = query.gte("created_at", f"{date_from}T00:00:00Z")
        if date_to:
            query = query.lte("created_at", f"{date_to}T23:59:59Z")
            
        if status and status != "all":
            db_status = status.capitalize() if status in ["pending", "completed"] else status
            query = query.eq("status", db_status)
            
        if category and category != "all":
            query = query.eq("category", category)
            
        query = query.order("created_at", desc=True)
        response = query.execute()
        
        flat_data = []
        for item in (response.data or []):
            p = item.get("patients") or {}
            
            # Python-based filter for shift to guarantee safety and compatibility
            item_shift = p.get("shift") or ""
            if shift and shift != "all" and item_shift.lower() != shift.lower():
                continue
                
            item["relation_type"] = p.get("relation") or ""
            item["relation_name"] = p.get("relation_name") or ""
            item["gender"] = p.get("gender") or "Male"
            item["age"] = p.get("age") or ""
            item["shift"] = item_shift
            item["mobile"] = p.get("mobile") or ""
            item["cnic"] = p.get("cnic") or ""
            item["patient_token"] = p.get("patient_token") or ""
            item["user"] = p.get("user") or ""
            item["user_id"] = p.get("user_id")
            item["synced"] = True
            if not row_matches_advanced_filters(item, adv_filters, legacy_search=search if not adv_filters else None):
                continue
            flat_data.append(item)
            
        return {"Response": flat_data}
    except Exception as e:
        log_error(e, "API_GET_PATIENTS_ALL")
        return {"Response": []}

# fetch all the basic patient info to display in update test result page but with limit for performance
@app.get("/api/patient/basic/{limit}")
def get_patient_basic_info_with_limit(
    limit: int,
    search: str = None,
    filters: str = None,
    date_from: str = None,
    date_to: str = None,
    status: str = None,
    shift: str = None,
    category: str = None,
    load_all: bool = False,
    offset: int = 0,
    chunk_size: int = 1000,
):
    """Browse: latest N patients. Filters: up to 1000 rows. load_all: paged chunks (requires date range)."""
    try:
        from patient_list_query import (
            MAX_LOAD_ALL_ROWS,
            fetch_test_result_list_rows,
            has_full_date_range,
            BROWSE_PATIENT_LIMIT,
        )

        if load_all and not has_full_date_range(date_from, date_to):
            return {
                "Response": [],
                "meta": {"error": "load_all requires both date_from and date_to"},
            }

        if load_all and offset >= MAX_LOAD_ALL_ROWS:
            return {"Response": [], "meta": {"has_more": False, "returned": 0, "offset": offset}}

        supabase = init_supabase()
        browse_limit = max(1, min(int(limit or BROWSE_PATIENT_LIMIT), 200))
        size = max(1, min(int(chunk_size or 1000), 1000))

        flat_data, meta = fetch_test_result_list_rows(
            supabase,
            lambda item, _shift: _flatten_patient_test_row(item, None),
            search=search,
            filters=filters,
            date_from=date_from,
            date_to=date_to,
            status=status,
            shift=shift,
            category=category,
            browse_patient_limit=browse_limit,
            load_all=load_all,
            offset=max(0, int(offset or 0)),
            chunk_size=size if load_all else None,
        )
        return {"Response": flat_data, "meta": meta}
    except Exception as e:
        log_error(e, f"API_GET_PATIENTS_LIMIT_{limit}")
        return {"Response": [], "meta": {"error": str(e)}}

@app.get("/api/test-results/record/{record_id}")
def get_test_record_by_id(record_id: int):
    try:
        supabase = init_supabase()
        response = supabase.table("test_results_all").select("*, patients(*)").eq("id", record_id).single().execute()
        data = _normalize_test_result_row(response.data) if response.data else None
        if data:
            p = data.get("patients") or {}
            data["relation_type"] = p.get("relation") or ""
            data["relation_name"] = p.get("relation_name") or ""
            data["age"] = p.get("age") or ""
            data["gender"] = p.get("gender") or "Male"
            data["mobile"] = p.get("mobile") or ""
            data["shift"] = p.get("shift") or ""
            data["patient_token"] = p.get("patient_token") or ""
            data["synced"] = True
        return {"status": "Success", "data": data}
    except Exception as e:
        log_error(e, f"API_GET_TEST_RECORD_{record_id}")
        return {"status": "Error", "data": None}

def _sanitize_test_values(raw):
    """Keep only parameter entries in test_values; never store remarks in jsonb."""
    if not isinstance(raw, dict):
        return {}
    # Unwrap mistaken nesting from an earlier bug: test_values = { remarks, test_values: {...} }
    if isinstance(raw.get("test_values"), dict):
        raw = raw["test_values"]
    return {k: v for k, v in raw.items() if k not in ("remarks", "test_values")}


def _normalize_test_result_row(row: dict) -> dict:
    """Split remarks out of test_values jsonb when reading from DB."""
    if not row:
        return row
    tv = row.get("test_values") or {}
    remarks = row.get("remarks")
    if isinstance(tv, dict):
        if tv.get("remarks") not in (None, "") and not remarks:
            remarks = tv.get("remarks")
        tv = _sanitize_test_values(tv)
    row["test_values"] = tv
    row["remarks"] = remarks
    return row


def _parse_test_result_update_body(data):
    """Accept legacy body (params only) or { test_values, remarks }."""
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


@app.post("/api/test-results/update/{record_id}")
async def update_test_record_results(record_id: int, request: Request):
    try:
        data = await request.json()
        test_values, remarks = _parse_test_result_update_body(data)
        supabase = init_supabase()
        update_row = {
            "test_values": test_values,
            "status": "Completed",
            "remarks": remarks if remarks is not None else "",
        }
        response = supabase.table("test_results_all").update(update_row).eq("id", record_id).execute()
        if remarks and str(remarks).strip():
            meta = (
                supabase.table("test_results_all")
                .select("test_name, category")
                .eq("id", record_id)
                .limit(1)
                .execute()
            )
            if meta.data:
                m = meta.data[0]
                record_remark_usage(str(remarks).strip(), m.get("test_name"), m.get("category"))

        # Local audit log for single record result update
        try:
            if insert_audit_log:
                meta = (
                    supabase.table("test_results_all")
                    .select("mr_no, patient_name, test_name")
                    .eq("id", record_id)
                    .limit(1)
                    .execute()
                )
                if meta.data:
                    m = meta.data[0]
                    actor = data.get("user_name") or data.get("logged_in_user") or "Staff"
                    val_summary = _format_audit_test_values(test_values)
                    rem_str = f" [Remark: {remarks}]" if remarks else ""
                    details_msg = f"{m.get('test_name')}: {val_summary}{rem_str}" if val_summary else f"Updated {m.get('test_name')}{rem_str}"
                    insert_audit_log(
                        mr_no=str(m.get("mr_no")),
                        patient_name=m.get("patient_name"),
                        action="UPDATE_RESULT",
                        user_name=actor,
                        details=details_msg,
                    )
        except Exception as a_err:
            logger.debug(f"Audit log on update error: {a_err}")

        save_log(f"Updated results for test_results_all ID: {record_id}", category="DATA_MODIFICATION")
        return {"status": "Success", "data": response.data}
    except Exception as e:
        log_error(e, f"API_UPDATE_TEST_RESULTS_RECORD_{record_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/test-results/patient/{mr_no}")
def get_test_records_by_mr_no(mr_no: int):
    try:
        supabase = init_supabase()
        response = supabase.table("test_results_all").select("*, patients(*)").eq("mr_no", mr_no).eq("delete_status", False).execute()
        data = [_normalize_test_result_row(r) for r in (response.data or [])]
        patient_info = {}
        if data:
            p = data[0].get("patients") or {}
            patient_info = {
                "patient_name": data[0].get("patient_name"),
                "mr_no": mr_no,
                "relation_type": p.get("relation") or "",
                "relation_name": p.get("relation_name") or "",
                "age": p.get("age") or "",
                "gender": p.get("gender") or "Male",
                "mobile": p.get("mobile") or "",
                "shift": p.get("shift") or "",
                "patient_token": p.get("patient_token") or ""
            }
        else:
            patient_resp = (
                supabase.table("patients")
                .select("patient_name, mr_no, relation, relation_name, age, gender, mobile, shift, patient_token")
                .eq("mr_no", mr_no)
                .limit(1)
                .execute()
            )
            if patient_resp.data:
                p = patient_resp.data[0]
                patient_info = {
                    "patient_name": p.get("patient_name"),
                    "mr_no": mr_no,
                    "relation_type": p.get("relation") or "",
                    "relation_name": p.get("relation_name") or "",
                    "age": p.get("age") or "",
                    "gender": p.get("gender") or "Male",
                    "mobile": p.get("mobile") or "",
                    "shift": p.get("shift") or "",
                    "patient_token": p.get("patient_token") or ""
                }
        return {"status": "Success", "patient": patient_info, "records": data}
    except Exception as e:
        log_error(e, f"API_GET_PATIENT_TESTS_{mr_no}")
        return {"status": "Error", "records": []}


@app.post("/api/test-results/patient/update/{mr_no}")
async def update_patient_test_records(mr_no: int, request: Request):
    try:
        data = await request.json()  # Dict of record_id -> test_values dict
        supabase = init_supabase()
        record_ids = [int(k) for k in data.keys()]
        meta_rows = {}
        if record_ids:
            meta_resp = (
                supabase.table("test_results_all")
                .select("id, test_name, category")
                .in_("id", record_ids)
                .execute()
            )
            meta_rows = {r["id"]: r for r in (meta_resp.data or [])}
        for record_id_str, item in data.items():
            record_id = int(record_id_str)
            test_values, remarks = _parse_test_result_update_body(item)
            update_row = {
                "test_values": test_values,
                "status": "Completed",
                "remarks": remarks if remarks is not None else "",
            }
            supabase.table("test_results_all").update(update_row).eq("id", record_id).eq("mr_no", mr_no).execute()
            if remarks and str(remarks).strip():
                m = meta_rows.get(record_id, {})
                record_remark_usage(str(remarks).strip(), m.get("test_name"), m.get("category"))

        # Local audit log for bulk results update
        try:
            if insert_audit_log:
                actor = data.get("user_name") or data.get("logged_in_user") or "Staff"
                p_name = None
                p_resp = supabase.table("patients").select("patient_name").eq("mr_no", mr_no).limit(1).execute()
                if p_resp.data:
                    p_name = p_resp.data[0].get("patient_name")

                breakdown = []
                for record_id_str, item in data.items():
                    record_id = int(record_id_str)
                    tv, rem = _parse_test_result_update_body(item)
                    m = meta_rows.get(record_id, {})
                    tname = m.get("test_name") or f"Test #{record_id}"
                    val_str = _format_audit_test_values(tv)
                    rem_str = f" [Remark: {rem}]" if rem else ""
                    if val_str:
                        breakdown.append(f"• {tname}: {val_str}{rem_str}")
                    elif rem:
                        breakdown.append(f"• {tname}:{rem_str}")

                details_msg = "\n".join(breakdown) if breakdown else f"Bulk updated {len(data)} test record(s)"
                insert_audit_log(
                    mr_no=str(mr_no),
                    patient_name=p_name,
                    action="UPDATE_RESULT",
                    user_name=actor,
                    details=details_msg,
                )
        except Exception as a_err:
            logger.debug(f"Audit log on bulk update error: {a_err}")

        save_log(f"Updated all results for patient MR: {mr_no}", category="DATA_MODIFICATION")
        return {"status": "Success"}
    except Exception as e:
        log_error(e, f"API_UPDATE_PATIENT_TESTS_MR_{mr_no}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/test-results/delete/{record_id}")
async def soft_delete_test_record(record_id: int, request: Request):
    """Soft-delete a test record by setting delete_status=True and recording who deleted it."""
    try:
        data = await request.json()
        person_deleting = data.get("person_deleting", "Anonymous")
        supabase = init_supabase()
        response = supabase.table("test_results_all").update({
            "delete_status": True,
            "person_deleting": person_deleting
        }).eq("id", record_id).execute()

        try:
            if insert_audit_log and response.data:
                r = response.data[0]
                insert_audit_log(
                    mr_no=str(r.get("mr_no")),
                    patient_name=r.get("patient_name"),
                    action="DELETE_TEST",
                    user_name=person_deleting,
                    details=f"Deleted test ID: {record_id}",
                )
        except Exception as a_err:
            logger.debug(f"Audit log on delete error: {a_err}")

        save_log(f"Soft-deleted test record ID: {record_id} by {person_deleting}", category="DATA_DELETION")
        return {"status": "Success", "data": response.data}
    except Exception as e:
        log_error(e, f"API_SOFT_DELETE_TEST_{record_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/test-results/patient/{mr_no}/add")
async def add_patient_test_record(mr_no: int, request: Request):
    """Add a single test (or group test) to an existing patient."""
    try:
        data = await request.json()
        selected_test = data.get("selected_test")
        if selected_test in (None, "", 0, "0"):
            raise HTTPException(status_code=400, detail="No test selected")

        supabase = init_supabase()
        patient_resp = (
            supabase.table("patients")
            .select("id, patient_name, mr_no")
            .eq("mr_no", mr_no)
            .limit(1)
            .execute()
        )
        patient_rows = patient_resp.data or []
        if not patient_rows:
            raise HTTPException(status_code=404, detail="Patient not found")

        patient = patient_rows[0]
        user = get_current_user(request)

        inserted = add_tests_to_patient_all(
            patient["id"],
            patient["mr_no"],
            patient["patient_name"],
            [selected_test],
            user=user,
        )
        if not inserted:
            return {"status": "Error", "message": "Failed to add test"}

        save_log(
            f"Added test for patient MR: {mr_no} (selection: {selected_test})",
            category="DATA_MODIFICATION",
            user=user,
        )
        return {"status": "Success", "added": len(inserted)}
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, f"API_ADD_PATIENT_TEST_{mr_no}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/metadata/registrar-users")
def get_registrar_users():
    """Distinct users who registered patients + system users table for advanced search picker."""
    try:
        supabase = init_supabase()
        seen: dict[str, dict] = {}

        try:
            users_resp = supabase.table("users").select("id, name, email").execute()
            for u in users_resp.data or []:
                uid = u.get("id")
                label = (u.get("name") or "").strip() or (u.get("email") or "").split("@")[0]
                if uid is not None:
                    seen[str(uid)] = {"user_id": uid, "user": label, "email": u.get("email")}
        except Exception:
            pass

        try:
            patients_resp = supabase.table("patients").select("user, user_id").execute()
            for r in patients_resp.data or []:
                uid = r.get("user_id")
                name = (r.get("user") or "").strip()
                if not name and uid is None:
                    continue
                key = str(uid) if uid is not None else f"n:{name.lower()}"
                if key not in seen:
                    seen[key] = {"user_id": uid, "user": name or f"User #{uid}"}
        except Exception:
            pass

        users = sorted(seen.values(), key=lambda x: (x.get("user") or "").lower())
        return {"status": "Success", "users": users}
    except Exception as e:
        log_error(e, "API_REGISTRAR_USERS")
        return {"status": "Success", "users": []}


@app.get("/api/metadata/filters")
def get_filter_metadata():
    try:
        supabase = init_supabase()
        
        # Query shifts directly from shift table
        shifts = []
        try:
            shift_resp = supabase.table("shift").select("shift").execute()
            shifts = sorted(list(set([r["shift"] for r in (shift_resp.data or []) if r.get("shift")])))
        except Exception:
            pass

        if not shifts:
            try:
                patients_resp = supabase.table("patients").select("shift").execute()
                shifts = sorted(list(set([r["shift"] for r in (patients_resp.data or []) if r.get("shift")])))
            except Exception:
                pass

        # Query categories from tests table
        categories = []
        try:
            tests_resp = supabase.table("tests").select("category").execute()
            categories = sorted(list(set([r["category"] for r in (tests_resp.data or []) if r.get("category")])))
        except Exception:
            pass
        
        if not shifts:
            shifts = ["MORNING", "EVENING", "NIGHT", "HOLIDAY", "OPD"]
        if not categories:
            categories = ["Hematology", "Biochemistry", "Serology", "Fluid Reports"]
            
        return {
            "status": "Success",
            "shifts": shifts,
            "categories": categories
        }
    except Exception as e:
        log_error(e, "API_METADATA_FILTERS")
        return {
            "status": "Success", 
            "shifts": ["MORNING", "EVENING", "NIGHT", "HOLIDAY", "OPD"], 
            "categories": ["Hematology", "Biochemistry", "Serology", "Fluid Reports"]
        }


@app.get("/api/admin/tests-catalog")
def admin_tests_catalog():
    try:
        supabase = init_supabase()
        tests_resp = supabase.table("tests").select(
            "id,name,category,unit,normal_min,normal_max,status"
        ).order("name").execute()
        groups_resp = supabase.table("test_groups").select(
            "id,group_name,category,component_ids,status"
        ).order("group_name").execute()
        return {
            "status": "Success",
            "tests": tests_resp.data or [],
            "groups": groups_resp.data or [],
            "categories": LAB_CATEGORIES,
        }
    except Exception as e:
        log_error(e, "API_ADMIN_TESTS_CATALOG")
        return {"status": "Error", "tests": [], "groups": [], "categories": LAB_CATEGORIES}


def _optional_range_value(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@app.post("/api/admin/tests")
async def admin_create_test(request: Request):
    try:
        payload = await request.json()
        name = (payload.get("name") or "").strip()
        category = (payload.get("category") or "").strip() or "General"
        unit = (payload.get("unit") or "").strip()
        status = bool(payload.get("status", True))

        if not name:
            raise HTTPException(status_code=400, detail="Test name is required")

        normal_min = _optional_range_value(payload.get("normal_min"))
        normal_max = _optional_range_value(payload.get("normal_max"))

        supabase = init_supabase()
        response = supabase.table("tests").insert({
            "name": name,
            "category": category,
            "unit": unit or None,
            "normal_min": normal_min,
            "normal_max": normal_max,
            "status": status
        }).execute()

        save_log(f"Created test: {name}", category="ADMIN_CONFIG")
        return {"status": "Success", "data": response.data}
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "API_ADMIN_CREATE_TEST")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/test-groups")
async def admin_create_test_group(request: Request):
    try:
        payload = await request.json()
        group_name = (payload.get("group_name") or "").strip()
        category = (payload.get("category") or "").strip() or "Group Test"
        status = bool(payload.get("status", True))
        component_ids_raw = payload.get("component_ids") or []

        if not group_name:
            raise HTTPException(status_code=400, detail="Group name is required")
        if not isinstance(component_ids_raw, list) or len(component_ids_raw) == 0:
            raise HTTPException(status_code=400, detail="Select at least one test")

        component_ids = [int(x) for x in component_ids_raw]

        supabase = init_supabase()
        response = supabase.table("test_groups").insert({
            "group_name": group_name,
            "category": category,
            "component_ids": component_ids,
            "status": status
        }).execute()

        save_log(f"Created test group: {group_name}", category="ADMIN_CONFIG")
        return {"status": "Success", "data": response.data}
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "API_ADMIN_CREATE_TEST_GROUP")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/tests/{test_id}")
async def admin_update_test(test_id: int, request: Request):
    try:
        payload = await request.json()
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Test name is required")

        update_data = {
            "name": name,
            "category": (payload.get("category") or "").strip() or "General",
            "unit": (payload.get("unit") or "").strip() or None,
            "normal_min": _optional_range_value(payload.get("normal_min")),
            "normal_max": _optional_range_value(payload.get("normal_max")),
            "status": bool(payload.get("status", True)),
        }
        supabase = init_supabase()
        response = supabase.table("tests").update(update_data).eq("id", test_id).execute()
        save_log(f"Updated test ID {test_id}: {name}", category="ADMIN_CONFIG")
        return {"status": "Success", "data": response.data}
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, f"API_ADMIN_UPDATE_TEST_{test_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/test-groups/{group_id}")
async def admin_update_test_group(group_id: int, request: Request):
    try:
        payload = await request.json()
        group_name = (payload.get("group_name") or "").strip()
        if not group_name:
            raise HTTPException(status_code=400, detail="Group name is required")
        component_ids_raw = payload.get("component_ids") or []
        if not isinstance(component_ids_raw, list) or len(component_ids_raw) == 0:
            raise HTTPException(status_code=400, detail="Select at least one test")
        component_ids = [int(x) for x in component_ids_raw]

        supabase = init_supabase()
        response = supabase.table("test_groups").update({
            "group_name": group_name,
            "category": (payload.get("category") or "").strip() or "Group Test",
            "component_ids": component_ids,
            "status": bool(payload.get("status", True)),
        }).eq("id", group_id).execute()
        save_log(f"Updated test group ID {group_id}: {group_name}", category="ADMIN_CONFIG")
        return {"status": "Success", "data": response.data}
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, f"API_ADMIN_UPDATE_GROUP_{group_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/patient/info/{mr_no}")
def get_patient_info(mr_no: int):
    """Patient demographics from DB only (used by enter-results / info modal; not list cache)."""
    try:
        supabase = init_supabase()
        response = (
            supabase.table("patients")
            .select(
                "patient_name, mr_no, relation, relation_name, age, gender, "
                "mobile, shift, patient_token"
            )
            .eq("mr_no", mr_no)
            .limit(1)
            .execute()
        )
        if not response.data:
            return {"status": "Error", "message": "Patient not found", "patient": None}
        p = response.data[0]
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
            },
        }
    except Exception as e:
        log_error(e, f"API_GET_PATIENT_INFO_{mr_no}")
        return {"status": "Error", "message": str(e), "patient": None}


@app.post("/api/patient/update-info/{mr_no}")
async def update_patient_info(mr_no: int, request: Request):
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
                    
        supabase = init_supabase()
        response = supabase.table("patients").update(allowed_payload).eq("mr_no", mr_no).execute()
        
        if "patient_name" in allowed_payload:
            supabase.table("test_results_all").update({
                "patient_name": allowed_payload["patient_name"]
            }).eq("mr_no", mr_no).execute()

        # Local audit log for patient demographic edit
        try:
            if insert_audit_log:
                actor = data.get("user_name") or data.get("logged_in_user") or "Staff"
                insert_audit_log(
                    mr_no=str(mr_no),
                    patient_name=allowed_payload.get("patient_name"),
                    action="EDIT_PATIENT",
                    user_name=actor,
                    details=f"Updated demographics: {', '.join(allowed_payload.keys())}",
                )
        except Exception as a_err:
            logger.debug(f"Audit log on patient edit error: {a_err}")
            
        save_log(f"Updated patient info for MR: {mr_no}", category="DATA_MODIFICATION")
        return {"status": "Success", "data": response.data}
    except Exception as e:
        log_error(e, f"API_UPDATE_PATIENT_INFO_{mr_no}")
        raise HTTPException(status_code=500, detail=str(e))

# fetch all the  patient info and test info  to display in update test result action page for specific user 
@app.get("/api/patient/allinfo/{patient_id}")
def get_patient_info_full(patient_id : int):
    try:
        response = GetAllBasicAndTestInfo(patient_id)
        return {"Response":response}
    except Exception as e:
        log_error(e, f"API_GET_PATIENT_INFO_{patient_id}")
        return {"Response": None}


# load test groups allow us to group the tests like urea cretinane to UC after fetching form DB
@app.get("/api/patient/testgroups")
def loadTestGroupsFromDb():
    try:
        response = LoadTestGroups()
        return response
    except Exception as e:
        log_error(e, "API_LOAD_TEST_GROUPS")
        return []

# this will fetch all the settings related to print page so the page can be dynamic as well
@app.get("/api/setting/loadprintsetting")
def loadPrintSetting():
    try:
        response = loadPrintSettings()
        return response
    except Exception as e:
        log_error(e, "API_LOAD_PRINT_SETTINGS")
        return []

@app.get("/api/lo")
def userLogin():
    """Legacy — prefer POST /api/auth/login."""
    try:
        response = loginUsers()
        return response
    except Exception as e:
        log_error(e, "API_LOGIN")
        return []


@app.get("/api/auth/login-users")
def api_auth_login_users():
    """Public list of active users for the login page dropdown."""
    return list_login_users()


def sync_online_to_offline_db():
    """
    Background worker to pull all configuration tables from online Supabase
    and save them into the local offline SQLite database for future offline usage.
    """
    import threading

    def _run():
        try:
            logger.info("Starting background metadata sync from online to offline database...")
            from offline.database import (
                upsert_tests_from_supabase,
                upsert_test_groups_from_supabase,
                upsert_shifts_from_supabase,
                upsert_users_from_supabase,
                upsert_remarks_from_supabase,
                upsert_invoice_settings_from_supabase,
            )
            from dbActions import init_supabase, load_invoice_settings_row
            
            supabase = init_supabase()
            
            # 1. Sync Tests
            try:
                tests = supabase.table("tests").select("*").execute().data or []
                if tests:
                    upsert_tests_from_supabase(tests)
                    logger.info(f"Offline DB: Synced {len(tests)} tests from Supabase")
            except Exception as e:
                logger.warning(f"Offline DB sync tests failed: {e}")
                
            # 2. Sync Test Groups
            try:
                groups = supabase.table("test_groups").select("*").execute().data or []
                if groups:
                    upsert_test_groups_from_supabase(groups)
                    logger.info(f"Offline DB: Synced {len(groups)} test groups from Supabase")
            except Exception as e:
                logger.warning(f"Offline DB sync test groups failed: {e}")

            # 3. Sync Shifts
            try:
                shifts = supabase.table("shift").select("*").execute().data or []
                if shifts:
                    upsert_shifts_from_supabase(shifts)
                    logger.info(f"Offline DB: Synced {len(shifts)} shifts from Supabase")
            except Exception as e:
                logger.warning(f"Offline DB sync shifts failed: {e}")

            # 4. Sync Users
            try:
                users = supabase.table("users").select("*").execute().data or []
                if users:
                    upsert_users_from_supabase(users)
                    logger.info(f"Offline DB: Synced {len(users)} users from Supabase")
            except Exception as e:
                logger.warning(f"Offline DB sync users failed: {e}")

            # 5. Sync Remarks
            try:
                remarks = supabase.table("remarks").select("*").execute().data or []
                if remarks:
                    upsert_remarks_from_supabase(remarks)
                    logger.info(f"Offline DB: Synced {len(remarks)} remarks from Supabase")
            except Exception as e:
                logger.warning(f"Offline DB sync remarks failed: {e}")

            # 6. Sync Invoice Settings
            try:
                inv_settings = load_invoice_settings_row()
                if inv_settings:
                    upsert_invoice_settings_from_supabase(inv_settings)
                    logger.info("Offline DB: Synced invoice settings from Supabase")
            except Exception as e:
                logger.warning(f"Offline DB sync invoice settings failed: {e}")

            logger.info("Background metadata sync to offline database complete.")
        except Exception as e:
            logger.error(f"Background metadata sync to offline database crashed: {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


@app.post("/api/auth/login")
async def api_auth_login(request: Request):
    try:
        data = await request.json()
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
        user = authenticate_user(email, password)
        if user and user.get("disabled"):
            return {"status": "Error", "message": "This account is disabled. Contact your administrator."}
        if not user:
            return {"status": "Error", "message": "Invalid email or password."}
        try:
            sync_invoice_settings_cache()
        except Exception as cache_err:
            logger.warning(f"Invoice settings cache failed on login: {cache_err}")
        try:
            sync_lab_print_settings_cache()
        except Exception as print_err:
            logger.warning(f"Lab print settings cache failed on login: {print_err}")
        try:
            sync_user_preferences_cache(user_id=user.get("id"), email=user.get("email"))
        except Exception as pref_err:
            logger.warning(f"User preferences cache failed on login: {pref_err}")
        try:
            sync_remarks_cache()
        except Exception as remarks_err:
            logger.warning(f"Remarks cache failed on login: {remarks_err}")
        
        # Sync all metadata tables from online Supabase to local offline SQLite database
        try:
            sync_online_to_offline_db()
        except Exception as offline_sync_err:
            logger.warning(f"Background offline DB sync failed to launch: {offline_sync_err}")

        return {"status": "Success", "user": user}
    except Exception as e:
        log_error(e, "API_AUTH_LOGIN")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/remarks")
def api_admin_list_remarks():
    return list_remarks_admin()


@app.post("/api/admin/remarks")
async def api_admin_create_remark(request: Request):
    try:
        data = await request.json()
        actor = request.headers.get("X-User-Email") or "Admin"
        return create_remark_admin(data, actor=actor)
    except Exception as e:
        log_error(e, "API_ADMIN_CREATE_REMARK")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/remarks/{remark_id}")
async def api_admin_update_remark(remark_id: int, request: Request):
    try:
        data = await request.json()
        actor = request.headers.get("X-User-Email") or "Admin"
        return update_remark_admin(remark_id, data, actor=actor)
    except Exception as e:
        log_error(e, "API_ADMIN_UPDATE_REMARK")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/remarks/{remark_id}")
async def api_admin_delete_remark(remark_id: int, request: Request):
    try:
        actor = request.headers.get("X-User-Email") or "Admin"
        return delete_remark_admin(remark_id, actor=actor)
    except Exception as e:
        log_error(e, "API_ADMIN_DELETE_REMARK")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/remarks/sync-cache")
def api_admin_sync_remarks_cache():
    payload = sync_remarks_cache()
    if payload is None:
        raise HTTPException(status_code=500, detail="Could not sync remarks cache")
    return {"status": "Success"}


@app.get("/api/admin/shifts")
def api_admin_list_shifts():
    return list_shifts_admin()


@app.post("/api/admin/shifts")
async def api_admin_create_shift(request: Request):
    try:
        data = await request.json()
        actor = get_current_user(request, form_data=data)
        result = create_shift_admin(data.get("shift") or data.get("name") or "", actor=actor)
        if result.get("status") != "Success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "API_ADMIN_CREATE_SHIFT")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/shifts/{shift_id}")
async def api_admin_update_shift(shift_id: int, request: Request):
    try:
        data = await request.json()
        actor = get_current_user(request, form_data=data)
        result = update_shift_admin(shift_id, data.get("shift") or data.get("name") or "", actor=actor)
        if result.get("status") != "Success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, f"API_ADMIN_UPDATE_SHIFT_{shift_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/shifts/{shift_id}")
async def api_admin_delete_shift(shift_id: int, request: Request):
    try:
        actor = get_current_user(request)
        result = delete_shift_admin(shift_id, actor=actor)
        if result.get("status") != "Success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, f"API_ADMIN_DELETE_SHIFT_{shift_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/users")
def api_admin_list_users():
    return list_users_admin()


@app.post("/api/admin/users")
async def api_admin_create_user(request: Request):
    try:
        data = await request.json()
        actor = get_current_user(request, form_data=data)
        result = create_user_admin(data, actor=actor)
        if result.get("status") == "schema_required":
            raise HTTPException(status_code=503, detail=result.get("message"))
        if result.get("status") != "Success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "API_ADMIN_CREATE_USER")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/admin/users/{user_id}")
async def api_admin_update_user(user_id: int, request: Request):
    try:
        data = await request.json()
        actor = get_current_user(request, form_data=data)
        result = update_user_admin(user_id, data, actor=actor)
        if result.get("status") == "schema_required":
            raise HTTPException(status_code=503, detail=result.get("message"))
        if result.get("status") != "Success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, f"API_ADMIN_UPDATE_USER_{user_id}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Custom Print Layout (per test-set fingerprint) ─────────────────────────

PRINT_LAYOUTS_PATH = os.path.join(fetcheddata_dir, "print_layouts.json")


def _load_print_layouts() -> dict:
    if os.path.exists(PRINT_LAYOUTS_PATH):
        try:
            with open(PRINT_LAYOUTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_print_layouts(layouts: dict) -> None:
    os.makedirs(fetcheddata_dir, exist_ok=True)
    with open(PRINT_LAYOUTS_PATH, "w", encoding="utf-8") as f:
        json.dump(layouts, f, indent=2, ensure_ascii=False)


@app.get("/api/lab/print-layout")
def api_get_print_layout(fingerprint: str = None):
    """
    Load a saved custom print layout for a given test-set fingerprint.
    Returns {status, layout} where layout is null if not found.
    """
    if not fingerprint:
        return {"status": "ok", "layout": None}
    layouts = _load_print_layouts()
    layout = layouts.get(fingerprint)
    return {"status": "ok", "layout": layout, "fingerprint": fingerprint}


@app.post("/api/lab/print-layout")
async def api_save_print_layout(request: Request):
    """
    Save a custom print layout for a test-set fingerprint.
    """
    try:
        data = await request.json()
        fingerprint = (data.get("fingerprint") or "").strip()
        layout = data.get("layout")
        actor = get_current_user(request, form_data=data)
        if not fingerprint:
            raise HTTPException(status_code=400, detail="fingerprint is required")
        if layout is None:
            raise HTTPException(status_code=400, detail="layout is required")
        layouts = _load_print_layouts()
        layouts[fingerprint] = {
            "page_map": layout.get("page_map", {}),   # {testName: pageIndex}
            "test_order": layout.get("test_order", []), # [testName1, ...]
            "saved_by": actor,
            "saved_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "test_count": layout.get("test_count", 0),
            "display_options": layout.get("display_options", {}),  # visibility toggle states
        }
        _save_print_layouts(layouts)
        logger.info(f"Print layout saved by {actor} for fingerprint {fingerprint[:40]}")
        return {"status": "ok", "message": "Layout saved successfully."}
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "API_SAVE_PRINT_LAYOUT")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/lab/print-layout")
async def api_delete_print_layout(request: Request, fingerprint: str = None):
    """Delete a saved custom print layout."""
    if not fingerprint:
        raise HTTPException(status_code=400, detail="fingerprint is required")
    layouts = _load_print_layouts()
    removed = layouts.pop(fingerprint, None)
    if removed is None:
        return {"status": "ok", "message": "Layout not found (already deleted)."}
    _save_print_layouts(layouts)
    return {"status": "ok", "message": "Layout deleted."}


# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/admin/print-settings")
def api_admin_get_print_settings():
    try:
        return get_lab_print_settings_admin()
    except Exception as e:
        log_error(e, "API_ADMIN_GET_PRINT_SETTINGS")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/print-settings")
async def api_admin_update_print_settings(request: Request):
    try:
        data = await request.json()
        actor = get_current_user(request, form_data=data)
        result = update_lab_print_settings_admin(data, actor=actor)
        if result.get("status") != "Success":
            raise HTTPException(status_code=400, detail=result.get("message", "Failed to update print settings"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "API_ADMIN_UPDATE_PRINT_SETTINGS")
        raise HTTPException(status_code=500, detail=str(e))


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
    """Retrieve registration dropdown options and default settings."""
    opts = _load_registration_options()
    if opts is None:
        opts = {
            "salutations": [
                {"value": "Mr.", "label": "Mr.", "default_gender": "MALE"},
                {"value": "Mrs.", "label": "Mrs.", "default_gender": "FEMALE"},
                {"value": "Miss.", "label": "Miss.", "default_gender": "FEMALE"},
                {"value": "Baby", "label": "Baby", "default_gender": ""}
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
                "salutation": "Mr.",
                "relation": "S",
                "gender": "MALE",
                "shift": "MORNING"
            }
        }
        _save_registration_options(opts)
    return {"status": "Success", "options": opts}


@app.post("/api/admin/registration-options")
async def api_save_registration_options(request: Request):
    """Save updated registration dropdown options and default values."""
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")
        _save_registration_options(data)
        actor = get_current_user(request, form_data=data)
        logger.info(f"Registration options updated by {actor}")
        return {"status": "Success", "message": "Registration options saved successfully"}
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "API_SAVE_REGISTRATION_OPTIONS")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Cloud Settings Sync (Push/Pull to Supabase) ──────────────────────────────

@app.post("/api/admin/cloud-settings/push")
async def api_cloud_settings_push(request: Request):
    """Upload local fetcheddata JSON settings to Supabase for cross-PC sharing."""
    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        actor = get_current_user(request, form_data=data)
        
        print_layouts = _load_print_layouts()
        test_selection_cfg = get_test_selection_config()
        registration_opts = _load_registration_options()
        test_suggestions_cfg = get_test_suggestions_config()
        
        payload = {
            "print_layouts": print_layouts,
            "test_selection_config": test_selection_cfg,
            "registration_options": registration_opts,
            "test_value_suggestions": test_suggestions_cfg,
            "pushed_by": actor,
            "pushed_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        }
        
        supabase = init_supabase()
        supabase.table("app_settings").upsert({
            "setting_type": "all_app_settings",
            "payload": payload,
            "updated_by": actor,
            "updated_at": payload["pushed_at"]
        }, on_conflict="setting_type").execute()
        
        logger.info(f"Cloud settings pushed to Supabase by {actor}")
        return {"status": "Success", "message": "Local settings successfully uploaded to cloud!", "pushed_at": payload["pushed_at"], "pushed_by": actor}
    except Exception as e:
        log_error(e, "API_CLOUD_SETTINGS_PUSH")
        raise HTTPException(status_code=500, detail=f"Failed to upload settings: {str(e)}")


@app.post("/api/admin/cloud-settings/pull")
async def api_cloud_settings_pull(request: Request):
    """Fetch cloud settings from Supabase and overwrite local fetcheddata JSON files."""
    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        actor = get_current_user(request, form_data=data)
        
        supabase = init_supabase()
        res = supabase.table("app_settings").select("*").eq("setting_type", "all_app_settings").execute()
        
        if not res.data:
            return {"status": "Error", "message": "No cloud settings found in Supabase. Please push settings from your main PC first."}
            
        cloud_entry = res.data[0]
        payload = cloud_entry.get("payload") or {}
        
        print_layouts = payload.get("print_layouts")
        test_selection_cfg = payload.get("test_selection_config")
        registration_opts = payload.get("registration_options")
        test_suggestions_cfg = payload.get("test_value_suggestions")
        
        if print_layouts is not None:
            _save_print_layouts(print_layouts)
            
        if test_selection_cfg is not None:
            save_test_selection_config(test_selection_cfg)

        if registration_opts is not None:
            _save_registration_options(registration_opts)

        if test_suggestions_cfg is not None:
            save_test_suggestions_config(test_suggestions_cfg)
            
        logger.info(f"Cloud settings pulled from Supabase by {actor}")
        return {
            "status": "Success",
            "message": "Cloud settings successfully downloaded and applied to this PC!",
            "pushed_by": payload.get("pushed_by", "Unknown"),
            "pushed_at": payload.get("pushed_at", "")
        }
    except Exception as e:
        log_error(e, "API_CLOUD_SETTINGS_PULL")
        raise HTTPException(status_code=500, detail=f"Failed to fetch cloud settings: {str(e)}")


def _auto_pull_cloud_settings_sync():
    """Background helper to pull latest master settings from Supabase Cloud on startup/login."""
    try:
        supabase = init_supabase()
        res = supabase.table("app_settings").select("*").eq("setting_type", "all_app_settings").execute()
        if res.data:
            payload = res.data[0].get("payload") or {}
            pl = payload.get("print_layouts")
            tsc = payload.get("test_selection_config")
            ro = payload.get("registration_options")
            tsug = payload.get("test_value_suggestions")
            if pl is not None:
                _save_print_layouts(pl)
            if tsc is not None:
                save_test_selection_config(tsc)
            if ro is not None:
                _save_registration_options(ro)
            if tsug is not None:
                save_test_suggestions_config(tsug)
            logger.info("Cloud sync auto-pull completed successfully from Supabase.")
    except Exception as e:
        logger.debug(f"Cloud auto-pull skipped (offline or unconfigured): {e}")


@app.on_event("startup")
def on_app_startup():
    """Auto-pull cloud settings and launch continuous Supabase replica background worker."""
    import threading
    threading.Thread(target=_auto_pull_cloud_settings_sync, daemon=True).start()
    try:
        from offline.app import sync_pending_offline_patients_background
        threading.Thread(target=sync_pending_offline_patients_background, daemon=True).start()
        logger.info("Triggered auto-push of pending offline patients on app boot.")
    except Exception as e:
        logger.debug(f"Offline auto-push trigger on startup error: {e}")
    try:
        engine = get_replica_engine()
        engine.start_background_worker()
        logger.info("Supabase continuous replica engine background worker started on app boot.")
    except Exception as e:
        logger.warning(f"Could not start replica engine on boot: {e}")


@app.on_event("shutdown")
def on_app_shutdown():
    """Stop continuous replica background worker cleanly on app shutdown."""
    try:
        engine = get_replica_engine()
        engine.stop_background_worker()
    except Exception as e:
        logger.debug(f"Replica worker shutdown error: {e}")


@app.get("/api/admin/cloud-settings/status")
def api_cloud_settings_status():
    """Get cloud sync status from Supabase."""
    try:
        supabase = init_supabase()
        res = supabase.table("app_settings").select("updated_by, updated_at, payload").eq("setting_type", "all_app_settings").execute()
        if res.data:
            entry = res.data[0]
            payload = entry.get("payload") or {}
            return {
                "status": "Success",
                "exists": True,
                "pushed_by": payload.get("pushed_by") or entry.get("updated_by") or "Admin",
                "pushed_at": payload.get("pushed_at") or entry.get("updated_at") or "",
                "layout_count": len(payload.get("print_layouts") or {})
            }
        return {"status": "Success", "exists": False}
    except Exception as e:
        return {"status": "Error", "exists": False, "detail": str(e)}


# ---------------------------------------------------------------------------
# Supabase Continuous Replica & Disaster Recovery Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/admin/replica/status")
def api_replica_status():
    """Get real-time status of the Supabase replica engine and storage locations."""
    try:
        engine = get_replica_engine()
        return engine.get_status()
    except Exception as e:
        log_error(e, "API_REPLICA_STATUS")
        return {"is_running": False, "error": str(e), "tables": {}, "locations": {}}


@app.post("/api/admin/replica/sync-now")
def api_replica_sync_now(request_data: Optional[dict] = None):
    """Trigger an immediate replication cycle (delta or forced full)."""
    try:
        engine = get_replica_engine()
        force_full = False
        if request_data and isinstance(request_data, dict):
            force_full = bool(request_data.get("force_full", False))
        result = engine.perform_sync(force_full=force_full)
        return result
    except Exception as e:
        log_error(e, "API_REPLICA_SYNC_NOW")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/replica/config")
def api_replica_update_config(config_data: dict):
    """Update replica settings (polling interval, locations, auto-sync)."""
    try:
        engine = get_replica_engine()
        if "poll_interval_seconds" in config_data:
            engine.poll_interval = max(5, int(config_data["poll_interval_seconds"]))
        if "location_1" in config_data and config_data["location_1"]:
            engine.location_1 = str(config_data["location_1"])
        if "location_2" in config_data and config_data["location_2"]:
            engine.location_2 = str(config_data["location_2"])
        engine._ensure_directories()
        return {"status": "success", "config": engine.get_status()}
    except Exception as e:
        log_error(e, "API_REPLICA_CONFIG")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/replica/download-sql")
def api_replica_download_sql(format: str = "postgres_full"):
    """Download PostgreSQL or SQLite migration SQL dumps."""
    try:
        engine = get_replica_engine()
        loc = engine.location_1
        
        if format == "postgres_full":
            file_path = os.path.join(loc, "sql", "migration_postgres_full.sql")
            filename = f"labflow_postgres_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        elif format == "postgres_upsert":
            file_path = os.path.join(loc, "sql", "migration_postgres_upsert.sql")
            filename = f"labflow_postgres_upsert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        elif format == "sqlite_dump":
            file_path = os.path.join(loc, "sql", "migration_sqlite_full.sql")
            filename = f"labflow_sqlite_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        elif format == "sqlite_db":
            file_path = os.path.join(loc, "database", "labflow_replica.db")
            filename = f"labflow_replica_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        else:
            raise HTTPException(status_code=400, detail="Invalid format requested")

        if not os.path.exists(file_path):
            # Run a sync to generate the files if not present
            engine.perform_sync(force_full=True)

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Requested replica file not found.")

        return FileResponse(file_path, filename=filename, media_type="application/octet-stream")
    except Exception as e:
        log_error(e, "API_REPLICA_DOWNLOAD")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/replica/test-migration")
def api_replica_test_migration(payload: dict):
    """Test connection and perform dry-run verification against target PostgreSQL URL."""
    try:
        pg_url = payload.get("target_pg_url", "").strip()
        if not pg_url:
            raise HTTPException(status_code=400, detail="Target PostgreSQL URL is required.")
        
        engine = get_replica_engine()
        from migrate_to_provider import load_master_sql, execute_pg_migration
        sql_content = load_master_sql(engine.location_1, upsert_only=False)
        result = execute_pg_migration(pg_url, sql_content, dry_run=True)
        return result
    except Exception as e:
        log_error(e, "API_REPLICA_TEST_MIGRATION")
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Database Junk Data Scanner & Selective Cleaner Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/admin/junk-data/scan")
def api_admin_junk_data_scan():
    """
    Scans the database for junk, orphan, and soft-deleted data without modifying anything.
    Returns categorized lists with item details for manual inspection and selective deletion.
    """
    try:
        supabase = init_supabase()
        scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Fetch Patients & Test Results
        # Using pagination/limit safety
        patients_res = supabase.table("patients").select("id, mr_no, patient_name, age, gender, mobile, created_at, user, shift").order("id", desc=True).limit(5000).execute()
        patients = patients_res.data or []
        patient_mr_set = {p.get("mr_no") for p in patients if p.get("mr_no") is not None}
        patient_mr_map = {p.get("mr_no"): p for p in patients if p.get("mr_no") is not None}

        # Fetch test results (both active and deleted)
        tests_res = supabase.table("test_results_all").select("id, mr_no, patient_name, category, test_name, test_values, status, created_at, delete_status, person_deleting, remarks").order("id", desc=True).limit(10000).execute()
        all_tests = tests_res.data or []

        # 2. Soft-Deleted Tests (delete_status == True or 1)
        deleted_tests = []
        active_tests = []
        test_mr_set = set()

        for t in all_tests:
            is_deleted = bool(t.get("delete_status"))
            if is_deleted:
                deleted_tests.append({
                    "id": t.get("id"),
                    "mr_no": t.get("mr_no"),
                    "patient_name": t.get("patient_name") or (patient_mr_map.get(t.get("mr_no"), {}).get("patient_name", "Unknown")),
                    "test_name": t.get("test_name") or "Unnamed Test",
                    "category": t.get("category") or "General",
                    "status": t.get("status") or "Deleted",
                    "person_deleting": t.get("person_deleting") or "Staff",
                    "remarks": t.get("remarks") or "",
                    "created_at": t.get("created_at") or ""
                })
            else:
                active_tests.append(t)
                if t.get("mr_no") is not None:
                    test_mr_set.add(t.get("mr_no"))

        # 3. Orphan Patients (Registered in patients, but 0 associated test records in test_results_all)
        orphan_patients = []
        for p in patients:
            mr = p.get("mr_no")
            if mr not in test_mr_set:
                orphan_patients.append({
                    "id": p.get("id"),
                    "mr_no": mr,
                    "patient_name": p.get("patient_name") or "Unnamed Patient",
                    "age": p.get("age"),
                    "gender": p.get("gender") or "",
                    "mobile": p.get("mobile") or "",
                    "user": p.get("user") or "System",
                    "shift": p.get("shift") or "",
                    "created_at": p.get("created_at") or ""
                })

        # 4. Ghost Test Records (Test results whose mr_no does not exist in patients table)
        ghost_tests = []
        for t in active_tests:
            mr = t.get("mr_no")
            if mr not in patient_mr_set:
                ghost_tests.append({
                    "id": t.get("id"),
                    "mr_no": mr,
                    "patient_name": t.get("patient_name") or "Unknown",
                    "test_name": t.get("test_name") or "Unnamed Test",
                    "category": t.get("category") or "",
                    "status": t.get("status") or "",
                    "created_at": t.get("created_at") or ""
                })

        # 5. Abandoned / Empty Draft Tests (Pending, delete_status=False, empty test_values older than 7 days)
        abandoned_drafts = []
        now_dt = datetime.now()
        for t in active_tests:
            if t.get("status") == "Pending":
                vals = t.get("test_values")
                is_empty = False
                if vals is None or vals == {} or vals == "" or vals == "{}":
                    is_empty = True
                elif isinstance(vals, dict) and all(v in (None, "", "0", 0) for v in vals.values()):
                    is_empty = True

                if is_empty:
                    # Check age
                    created_raw = t.get("created_at") or ""
                    days_old = 0
                    if created_raw:
                        try:
                            c_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00").split("+")[0])
                            days_old = (now_dt - c_dt).days
                        except Exception:
                            days_old = 0
                    
                    if days_old >= 7:
                        abandoned_drafts.append({
                            "id": t.get("id"),
                            "mr_no": t.get("mr_no"),
                            "patient_name": t.get("patient_name") or "Unknown",
                            "test_name": t.get("test_name") or "Unnamed",
                            "category": t.get("category") or "",
                            "days_old": days_old,
                            "created_at": created_raw
                        })

        # 6. Duplicate Test Results (Accidental double-clicks: same mr_no, test_name, created within 3 minutes)
        duplicate_tests = []
        seen_combos = {}
        for t in active_tests:
            mr = t.get("mr_no")
            tname = (t.get("test_name") or "").strip().lower()
            key = f"{mr}_{tname}"
            if key in seen_combos:
                duplicate_tests.append({
                    "id": t.get("id"),
                    "mr_no": mr,
                    "patient_name": t.get("patient_name") or "",
                    "test_name": t.get("test_name") or "",
                    "original_id": seen_combos[key].get("id"),
                    "created_at": t.get("created_at") or ""
                })
            else:
                seen_combos[key] = t

        # 7. Old Analytics Snapshots (> 30 days old)
        old_snapshots = []
        try:
            snap_res = supabase.table("analytics_snapshots").select("id, snapshot_type, date_from, date_to, computed_at").order("id", desc=True).limit(200).execute()
            snaps = snap_res.data or []
            for s in snaps:
                c_at = s.get("computed_at") or ""
                if c_at:
                    try:
                        c_dt = datetime.fromisoformat(c_at.replace("Z", "+00:00").split("+")[0])
                        if (now_dt - c_dt).days >= 30:
                            old_snapshots.append(s)
                    except Exception:
                        pass
        except Exception:
            old_snapshots = []

        # 8. Inactive Remarks with 0 usage
        inactive_remarks = []
        try:
            rem_res = supabase.table("remarks").select("id, remark_text, test_name, category, usage_count, is_active").eq("is_active", False).execute()
            remarks_list = rem_res.data or []
            for r in remarks_list:
                if (r.get("usage_count") or 0) == 0:
                    inactive_remarks.append(r)
        except Exception:
            inactive_remarks = []

        # 9. Inactive Catalog Tests
        inactive_tests = []
        try:
            cat_res = supabase.table("tests").select("id, name, unit, category, status").eq("status", False).execute()
            inactive_tests = cat_res.data or []
        except Exception:
            inactive_tests = []

        total_junk_count = (
            len(deleted_tests) + 
            len(orphan_patients) + 
            len(ghost_tests) + 
            len(abandoned_drafts) + 
            len(duplicate_tests) + 
            len(old_snapshots) + 
            len(inactive_remarks)
        )

        return {
            "status": "success",
            "scan_time": scan_time,
            "summary": {
                "total_patients": len(patients),
                "total_tests": len(all_tests),
                "active_tests": len(active_tests),
                "total_junk_records": total_junk_count,
                "deleted_tests_count": len(deleted_tests),
                "orphan_patients_count": len(orphan_patients),
                "ghost_tests_count": len(ghost_tests),
                "abandoned_drafts_count": len(abandoned_drafts),
                "duplicate_tests_count": len(duplicate_tests),
                "old_snapshots_count": len(old_snapshots),
                "inactive_remarks_count": len(inactive_remarks),
                "inactive_tests_count": len(inactive_tests)
            },
            "data": {
                "deleted_tests": deleted_tests,
                "orphan_patients": orphan_patients,
                "ghost_tests": ghost_tests,
                "abandoned_drafts": abandoned_drafts,
                "duplicate_tests": duplicate_tests,
                "old_snapshots": old_snapshots,
                "inactive_remarks": inactive_remarks,
                "inactive_tests": inactive_tests
            }
        }
    except Exception as e:
        log_error(e, "API_JUNK_DATA_SCAN")
        return {"status": "error", "error": str(e), "summary": {}, "data": {}}


@app.post("/api/admin/junk-data/clean")
def api_admin_junk_data_clean(payload: dict):
    """
    Permanently deletes only the explicitly selected items with administrator permission.
    Never deletes anything automatically. Requires explicit ID/MR lists and audit logging.
    """
    try:
        supabase = init_supabase()
        admin_user = payload.get("admin_user", "Admin").strip()
        confirmation = payload.get("confirmation", "").strip().upper()

        if confirmation != "CONFIRM":
            raise HTTPException(
                status_code=400, 
                detail="Confirmation code 'CONFIRM' required to perform permanent deletion."
            )

        selected_deleted_test_ids = payload.get("deleted_test_ids", [])
        selected_orphan_mr_nos = payload.get("orphan_patient_mr_nos", [])
        selected_ghost_test_ids = payload.get("ghost_test_ids", [])
        selected_abandoned_draft_ids = payload.get("abandoned_draft_ids", [])
        selected_duplicate_test_ids = payload.get("duplicate_test_ids", [])
        selected_snapshot_ids = payload.get("snapshot_ids", [])
        selected_inactive_remark_ids = payload.get("inactive_remark_ids", [])
        selected_inactive_test_ids = payload.get("inactive_test_ids", [])

        cleaned_report = {
            "deleted_tests": 0,
            "orphan_patients": 0,
            "ghost_tests": 0,
            "abandoned_drafts": 0,
            "duplicate_tests": 0,
            "snapshots": 0,
            "inactive_remarks": 0,
            "inactive_tests": 0,
            "errors": []
        }

        # Helper to batch delete by column
        def batch_delete(table_name, column_name, id_list, batch_size=40):
            deleted_count = 0
            for i in range(0, len(id_list), batch_size):
                chunk = id_list[i:i + batch_size]
                try:
                    supabase.table(table_name).delete().in_(column_name, chunk).execute()
                    deleted_count += len(chunk)
                except Exception as ex:
                    err_msg = f"Failed batch delete in {table_name}.{column_name}: {str(ex)}"
                    cleaned_report["errors"].append(err_msg)
                    logger.error(err_msg)
            return deleted_count

        # 1. Purge Selected Soft-Deleted Tests
        if selected_deleted_test_ids:
            cleaned_report["deleted_tests"] = batch_delete("test_results_all", "id", selected_deleted_test_ids)

        # 2. Purge Selected Orphan Patients
        if selected_orphan_mr_nos:
            cleaned_report["orphan_patients"] = batch_delete("patients", "mr_no", selected_orphan_mr_nos)

        # 3. Purge Selected Ghost Tests
        if selected_ghost_test_ids:
            cleaned_report["ghost_tests"] = batch_delete("test_results_all", "id", selected_ghost_test_ids)

        # 4. Purge Selected Abandoned Drafts
        if selected_abandoned_draft_ids:
            cleaned_report["abandoned_drafts"] = batch_delete("test_results_all", "id", selected_abandoned_draft_ids)

        # 5. Purge Selected Duplicate Tests
        if selected_duplicate_test_ids:
            cleaned_report["duplicate_tests"] = batch_delete("test_results_all", "id", selected_duplicate_test_ids)

        # 6. Purge Selected Snapshots
        if selected_snapshot_ids:
            cleaned_report["snapshots"] = batch_delete("analytics_snapshots", "id", selected_snapshot_ids)

        # 7. Purge Selected Inactive Remarks
        if selected_inactive_remark_ids:
            cleaned_report["inactive_remarks"] = batch_delete("remarks", "id", selected_inactive_remark_ids)

        # 8. Purge Selected Inactive Catalog Tests
        if selected_inactive_test_ids:
            cleaned_report["inactive_tests"] = batch_delete("tests", "id", selected_inactive_test_ids)

        total_cleaned = sum([
            cleaned_report["deleted_tests"],
            cleaned_report["orphan_patients"],
            cleaned_report["ghost_tests"],
            cleaned_report["abandoned_drafts"],
            cleaned_report["duplicate_tests"],
            cleaned_report["snapshots"],
            cleaned_report["inactive_remarks"],
            cleaned_report["inactive_tests"],
        ])

        # Audit Logging
        summary_msg = (
            f"Manual Junk Cleanup executed by '{admin_user}': Total {total_cleaned} records purged "
            f"({cleaned_report['deleted_tests']} soft-deleted tests, {cleaned_report['orphan_patients']} orphan patients, "
            f"{cleaned_report['ghost_tests']} ghost tests, {cleaned_report['abandoned_drafts']} abandoned drafts, "
            f"{cleaned_report['duplicate_tests']} duplicates, {cleaned_report['snapshots']} snapshots, "
            f"{cleaned_report['inactive_remarks']} remarks, {cleaned_report['inactive_tests']} inactive tests)."
        )
        save_log(summary_msg, category="DATABASE_CLEANUP", user=admin_user)
        if insert_audit_log:
            try:
                insert_audit_log(
                    action="DELETE_JUNK_DATA",
                    mr_no=None,
                    patient_name="System Database Maintenance",
                    user_name=admin_user,
                    details=summary_msg
                )
            except Exception:
                pass

        return {
            "status": "success",
            "total_cleaned": total_cleaned,
            "cleaned_breakdown": cleaned_report,
            "message": f"Successfully deleted {total_cleaned} selected junk records from database."
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "API_JUNK_DATA_CLEAN")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/junk-data/export-json")
def api_admin_junk_data_export():
    """
    Exports a downloadable JSON backup snapshot of all currently detected junk data.
    Provides safety before performing any permanent deletions.
    """
    try:
        scan_result = api_admin_junk_data_scan()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"labflow_junk_backup_{timestamp}.json"
        
        json_content = json.dumps(scan_result, indent=2, default=str)
        return JSONResponse(
            content=json.loads(json_content),
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "application/json"
            }
        )
    except Exception as e:
        log_error(e, "API_JUNK_DATA_EXPORT")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Emergency Disaster Recovery & Root-Cause Diagnostic Endpoints (Login/Splash)
# ---------------------------------------------------------------------------

@app.post("/api/emergency-dr/diagnose")
def api_emergency_dr_diagnose():
    """Performs comprehensive live connectivity and root-cause diagnostics on Primary, Secondary, and Local DBs."""
    import time
    import socket
    import urllib.parse
    import sqlite3
    from dotenv import load_dotenv
    from supabase import create_client
    
    base_dir = get_base_path()
    env_path = os.path.join(base_dir, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "primary": {},
        "secondary": {},
        "local_replica": {},
        "root_cause_analysis": []
    }
    
    # 1. Primary Supabase Diagnostics
    primary_url = os.getenv("SUPABASE_URL", "")
    primary_key = os.getenv("SUPABASE_KEY", "")
    report["primary"]["url"] = primary_url
    
    if not primary_url or not primary_key:
        report["primary"]["status"] = "UNCONFIGURED"
        report["root_cause_analysis"].append("Primary Supabase credentials missing in .env")
    else:
        start = time.time()
        try:
            parsed = urllib.parse.urlparse(primary_url)
            hostname = parsed.hostname or ""
            ip = socket.gethostbyname(hostname)
            report["primary"]["dns_ip"] = ip
            
            c = create_client(primary_url, primary_key)
            res = c.table("patients").select("id", count="exact").limit(0).execute()
            latency_ms = int((time.time() - start) * 1000)
            report["primary"]["status"] = "ONLINE_HEALTHY"
            report["primary"]["latency_ms"] = latency_ms
            report["primary"]["error"] = None
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            err_str = str(e)
            report["primary"]["status"] = "FAILED"
            report["primary"]["latency_ms"] = latency_ms
            report["primary"]["error"] = err_str
            
            if "getaddrinfo" in err_str or "nodename" in err_str:
                report["root_cause_analysis"].append("Primary Supabase DNS lookup failed (Check internet connection or DNS).")
            elif "401" in err_str or "403" in err_str or "Invalid API key" in err_str:
                report["root_cause_analysis"].append("Primary Supabase API authentication failed (Invalid SUPABASE_KEY).")
            elif "500" in err_str or "502" in err_str or "503" in err_str or "504" in err_str:
                report["root_cause_analysis"].append("Primary Supabase Cloud server error (Supabase region outage or 503 maintenance).")
            elif "PGRST205" in err_str or "schema cache" in err_str:
                report["root_cause_analysis"].append("Primary database table schema error (Table 'patients' missing or permissions not granted).")
            else:
                report["root_cause_analysis"].append(f"Primary Supabase connection error: {err_str[:120]}")

    # 2. Secondary Supabase Diagnostics
    sec_url = os.getenv("SECONDARY_SUPABASE_URL", "")
    sec_key = os.getenv("SECONDARY_SUPABASE_KEY", "")
    report["secondary"]["url"] = sec_url
    
    if not sec_url or not sec_key:
        report["secondary"]["status"] = "UNCONFIGURED"
    else:
        start = time.time()
        try:
            parsed = urllib.parse.urlparse(sec_url)
            hostname = parsed.hostname or ""
            ip = socket.gethostbyname(hostname)
            report["secondary"]["dns_ip"] = ip
            
            c_sec = create_client(sec_url, sec_key)
            res_sec = c_sec.table("patients").select("id", count="exact").limit(0).execute()
            latency_ms = int((time.time() - start) * 1000)
            report["secondary"]["status"] = "ONLINE_READY"
            report["secondary"]["latency_ms"] = latency_ms
            report["secondary"]["error"] = None
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            err_str = str(e)
            if "PGRST205" in err_str or "schema cache" in err_str:
                report["secondary"]["status"] = "ONLINE_NEEDS_SCHEMA"
                report["secondary"]["error"] = "Project reachable, but tables not created yet (Run setup_secondary_schema.sql in Secondary Supabase SQL editor)."
            else:
                report["secondary"]["status"] = "FAILED"
                report["secondary"]["error"] = err_str
            report["secondary"]["latency_ms"] = latency_ms

    # 3. Local SQLite Replica Diagnostics
    try:
        engine = get_replica_engine()
        loc1 = engine.location_1
        db_path = os.path.join(loc1, "database", "labflow_replica.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path, timeout=5)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM patients")
            patients_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM test_results_all")
            tests_count = cur.fetchone()[0]
            conn.close()
            report["local_replica"]["status"] = "ONLINE_HEALTHY"
            report["local_replica"]["patients_count"] = patients_count
            report["local_replica"]["tests_count"] = tests_count
            report["local_replica"]["db_size_bytes"] = os.path.getsize(db_path)
            report["local_replica"]["last_sync_time"] = engine.last_sync_time
        else:
            report["local_replica"]["status"] = "NOT_FOUND"
    except Exception as e:
        report["local_replica"]["status"] = "ERROR"
        report["local_replica"]["error"] = str(e)

    return report


@app.post("/api/emergency-dr/switch")
def api_emergency_dr_switch(payload: dict):
    """Manually switch active database provider between Primary and Secondary Supabase (Protected by youcannotenter)."""
    pwd = payload.get("password", "")
    if pwd != "youcannotenter":
        raise HTTPException(status_code=403, detail="Invalid admin password. Master password is required.")
        
    target = payload.get("target") # "primary" | "secondary"
    base_dir = get_base_path()
    env_path = os.path.join(base_dir, ".env")
    
    # Read current .env
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    # Extract keys
    env_dict = {}
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            parts = line.strip().split("=", 1)
            if len(parts) == 2:
                env_dict[parts[0]] = parts[1]
            
    primary_url = env_dict.get("PRIMARY_BACKUP_URL") or env_dict.get("SUPABASE_URL")
    primary_key = env_dict.get("PRIMARY_BACKUP_KEY") or env_dict.get("SUPABASE_KEY")
    secondary_url = env_dict.get("SECONDARY_SUPABASE_URL")
    secondary_key = env_dict.get("SECONDARY_SUPABASE_KEY")
    
    if target == "secondary":
        if not secondary_url or not secondary_key:
            raise HTTPException(status_code=400, detail="Secondary Supabase URL/Key is not configured in .env")
        # Save primary as PRIMARY_BACKUP and set secondary as active SUPABASE_URL
        env_dict["PRIMARY_BACKUP_URL"] = primary_url
        env_dict["PRIMARY_BACKUP_KEY"] = primary_key
        env_dict["SUPABASE_URL"] = secondary_url
        env_dict["SUPABASE_KEY"] = secondary_key
        active_name = "Secondary Supabase Project"
    elif target == "primary":
        if not primary_url or not primary_key:
            raise HTTPException(status_code=400, detail="Primary Supabase URL/Key not found in backup")
        env_dict["SUPABASE_URL"] = primary_url
        env_dict["SUPABASE_KEY"] = primary_key
        active_name = "Primary Supabase Project"
    else:
        raise HTTPException(status_code=400, detail="Invalid target specified")
        
    # Write back .env
    with open(env_path, "w", encoding="utf-8") as f:
        for k, v in env_dict.items():
            f.write(f"{k}={v}\n")
            
    # Reload environment
    os.environ["SUPABASE_URL"] = env_dict["SUPABASE_URL"]
    os.environ["SUPABASE_KEY"] = env_dict["SUPABASE_KEY"]
    
    return {
        "status": "success",
        "active_target": target,
        "active_url": env_dict["SUPABASE_URL"],
        "message": f"Successfully switched active database to {active_name}!"
    }


# ── Local SQLite Audit Trail & Print Tracking ─────────────────────────────────
@app.post("/api/audit/log-print")
async def api_audit_log_print_online(request: Request):
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

        print_count = 1
        if insert_audit_log:
            print_count = insert_audit_log(
                mr_no=mr_no,
                patient_name=patient_name,
                action="PRINT",
                user_name=user_name,
                user_id=user_id,
                details=details,
                pc_name=pc_name,
            ) or 1
        save_log(f"Print report for MR#{mr_no} by {user_name} (Copy #{print_count})", category="PRINT_EVENT", user=user_name)
        return {"status": "Success", "print_count": print_count}
    except Exception as e:
        logger.error(f"Online audit log print error: {e}")
        return {"status": "Error", "message": str(e)}


@app.get("/api/audit/list")
def api_audit_list_online(
    search: str = None,
    mr_no: str = None,
    user_name: str = None,
    action: str = None,
    date_from: str = None,
    date_to: str = None,
    limit: int = 200,
):
    try:
        if list_audit_trail:
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
        return {"status": "Success", "logs": [], "count": 0}
    except Exception as e:
        logger.error(f"Online audit list error: {e}")
        return {"status": "Error", "message": str(e), "logs": []}



