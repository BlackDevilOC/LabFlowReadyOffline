from supabase import Client,create_client
from dotenv import load_dotenv
from logdata import save_log, log_error, logger
import os
import json
import sys
import random
import shutil
from pathlib import Path

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def init_supabase() -> Client:
    try:
        base_path = get_base_path()
        dotenv_path = os.path.join(base_path, ".env")
        
        # Always reload fresh with override=True to support dynamic manual switching
        if os.path.exists(dotenv_path):
            load_dotenv(dotenv_path, override=True)
        else:
            load_dotenv(override=True)

        SUPABASE_URL = str(os.getenv("SUPABASE_URL", "")).strip()
        SUPABASE_KEY = str(os.getenv("SUPABASE_KEY", "")).strip()

        if not SUPABASE_URL or not SUPABASE_KEY:
            logger.warning("Supabase credentials not found in environment variables!")

        supabase: Client = create_client(supabase_key=SUPABASE_KEY, supabase_url=SUPABASE_URL) 
        return supabase
    except Exception as e:
        log_error(e, "DB_INIT_FAILED")
        raise

def load_patient():
    try:
        supabase : Client = init_supabase()
        result = supabase.table('patients').select("*").execute()
        logger.info(f"Loaded {len(result.data)} patients from database")
        return result.data
    except Exception as e:
        log_error(e, "LOAD_PATIENTS")
        return []

def load_tests(active_only: bool = True):
    try:
        supabase : Client = init_supabase()
        q_tests = supabase.table('tests').select("id","name","status")
        q_groups = supabase.table('test_groups').select("id","group_name","status","component_ids")
        if active_only:
            q_tests = q_tests.eq("status", True)
            q_groups = q_groups.eq("status", True)
        tests = q_tests.execute()
        group_test = q_groups.execute()
        
        logger.info(f"Loaded {len(tests.data)} individual tests and {len(group_test.data)} test groups (active_only={active_only})")
        return {"tests": tests.data, "group_test": group_test.data}
    except Exception as e:
        log_error(e, "LOAD_TESTS")
        return {"tests": [], "group_test": []}

def register_new_patient(item, user="System"):
    try:
        save_log(item, category="REGISTER_PATIENT_PAYLOAD", user=user)
        supabase : Client = init_supabase()
        response = supabase.table("patients").insert(item).execute()
        
        if not response.data:
            logger.error("No data returned from register_new_patient insert!")
            return None, None

        patient_row = response.data[0]
        patient_id = patient_row["id"] # type: ignore
        patient_mr_no = patient_row["mr_no"] # type: ignore
        
        logger.info(f"Successfully registered new patient. ID: {patient_id}, MR No: {patient_mr_no}")
        return patient_id, patient_mr_no
    except Exception as e:
        log_error(e, "REGISTER_NEW_PATIENT_FAILED", user=user)
        raise

def add_tests_to_patient(patient_id, tests, user="System"):
    try:
        supabase : Client = init_supabase()
        log = []
        logger.info(f"Adding {len(tests)} tests to patient ID: {patient_id}")
        for i in tests:
            payload = {
                "patient_id" : patient_id,
                "test_id": i,
                "result_value" : "0",
                "status" : "Pending"
            }
            response = supabase.table("patient_test_results").insert(payload).execute()
            log.append(response.data)
        
        logger.info(f"Successfully added {len(log)} test results for patient {patient_id}")
        return log
    except Exception as e:
        log_error(e, "ADD_TESTS_TO_PATIENT_FAILED", user=user)
        return []

def getPatientBasicInfoLimit(limit:int):
    try:
        supabase : Client = init_supabase()
        response = supabase.table("patients").select("id, patient_name, mr_no, shift").limit(limit).execute().data
        logger.debug(f"Fetched {len(response)} patients (limit: {limit})")
        return response
    except Exception as e:
        log_error(e, "GET_PATIENT_BASIC_INFO_LIMIT")
        return []

def getPatientBasicInfoAll():
    try:
        supabase : Client = init_supabase()
        response = supabase.table("patients").select("id, patient_name, mr_no, shift").execute().data
        logger.info("Fetched all basic patient info")
        return response
    except Exception as e:
        log_error(e, "GET_PATIENT_BASIC_INFO_ALL")
        return []

def GetAllBasicAndTestInfo(patient_id:int):
    try:
        supabase: Client = init_supabase()
        response = supabase.table("patients").select("*, patient_test_results(id, test_id, result_value, tests(name, unit, normal_min, normal_max,category))").eq("id", patient_id).single().execute()
        logger.info(f"Fetched full info for patient ID: {patient_id}")
        return response.data
    except Exception as e:
        log_error(e, f"GET_FULL_INFO_PATIENT_{patient_id}")
        return None

def SaveTestResult(id,value):
    try:
        supabase : Client = init_supabase()
        response = supabase.table("patient_test_results").update({"result_value":value}).eq("id",id).execute()
        logger.debug(f"Saved test result ID: {id}, Value: {value}")
        return response.data
    except Exception as e:
        log_error(e, f"SAVE_TEST_RESULT_ID_{id}")
        return None

def LoadTestGroups():
    try:
        supabase : Client = init_supabase()
        response = supabase.table("test_groups").select("*").execute()
        return response.data
    except Exception as e:
        log_error(e, "LOAD_TEST_GROUPS")
        return []

def get_fetched_data_dir() -> Path:
    path = Path(get_base_path()) / "fetcheddata"
    path.mkdir(parents=True, exist_ok=True)
    return path


def generate_patient_pin() -> str:
    """Random numeric PIN, 4–8 digits (plain text for receipt / patients.pwd)."""
    length = random.randint(4, 8)
    low = 10 ** (length - 1)
    high = (10 ** length) - 1
    return str(random.randint(low, high))


def _resolve_local_asset_path(relative_path: str) -> Path | None:
    if not relative_path:
        return None
    rel = relative_path.lstrip("/").replace("/", os.sep)
    candidate = Path(get_base_path()) / rel
    if candidate.is_file():
        return candidate
    return None


def _copy_asset_to_fetched(source: Path, dest_name: str) -> str:
    dest = get_fetched_data_dir() / dest_name
    shutil.copy2(source, dest)
    return f"/fetcheddata/{dest_name}"


def load_invoice_settings_row():
    """Active invoice_settings row; falls back to legacy print_settings if needed."""
    try:
        supabase: Client = init_supabase()
        response = (
            supabase.table("invoice_settings")
            .select("*")
            .eq("is_active", True)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]
    except Exception as e:
        logger.debug(f"invoice_settings not available: {e}")

    try:
        supabase = init_supabase()
        legacy = supabase.table("print_settings").select("*").limit(1).execute()
        if legacy.data:
            row = legacy.data[0]
            return {
                "hospital_name": row.get("hospital_name") or "GMMMC Teaching Hospital Sukkur",
                "developed_by": row.get("developed_by") or "Rehan Ahmed",
                "developed_by_url": row.get("developed_by_url"),
                "online_report_url": row.get("online_report_url"),
                "printer_width": row.get("printer_width") or "3in",
                "logo_path": row.get("logo_path") or "/static/images/hospital_logo.png",
                "qr_code_path": row.get("qr_code_path"),
            }
    except Exception as e:
        log_error(e, "LOAD_PRINT_SETTINGS_LEGACY")
    return None


def sync_invoice_settings_cache() -> dict | None:
    """Fetch invoice settings from DB on login; cache JSON + logo/QR under fetcheddata/."""
    row = load_invoice_settings_row()
    if not row:
        return None

    cache_dir = get_fetched_data_dir()
    cached = dict(row)

    logo_src = row.get("logo_path") or "/static/images/hospital_logo.png"
    logo_file = _resolve_local_asset_path(logo_src)
    if logo_file:
        cached["logo_url"] = _copy_asset_to_fetched(logo_file, "logo" + logo_file.suffix.lower())
    else:
        cached["logo_url"] = logo_src

    qr_src = row.get("qr_code_path")
    qr_file = _resolve_local_asset_path(qr_src) if qr_src else None
    if qr_file:
        cached["qr_url"] = _copy_asset_to_fetched(qr_file, "qr" + qr_file.suffix.lower())
    else:
        placeholder = cache_dir / "qr_placeholder.svg"
        if not placeholder.is_file():
            placeholder.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">'
                '<rect width="120" height="120" fill="#fff"/>'
                '<rect x="8" y="8" width="24" height="24" fill="#000"/>'
                '<rect x="88" y="8" width="24" height="24" fill="#000"/>'
                '<rect x="8" y="88" width="24" height="24" fill="#000"/>'
                '<rect x="40" y="40" width="16" height="16" fill="#000"/>'
                '<rect x="64" y="40" width="16" height="16" fill="#000"/>'
                '<rect x="40" y="64" width="40" height="16" fill="#000"/>'
                "</svg>",
                encoding="utf-8",
            )
        cached["qr_url"] = "/fetcheddata/qr_placeholder.svg"

    settings_path = cache_dir / "invoice_settings.json"
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(cached, f, indent=2, default=str)

    logger.info("Invoice settings cached to fetcheddata/")
    return cached


def list_shifts_all():
    try:
        supabase: Client = init_supabase()
        response = supabase.table("shift").select("id, shift, created_at").order("id").execute()
        return response.data or []
    except Exception as e:
        log_error(e, "LIST_SHIFTS_ALL")
        return []


def sync_shifts_cache() -> list[dict]:
    shifts = list_shifts_all()
    path = get_fetched_data_dir() / "shifts.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"shifts": shifts}, f, indent=2, default=str)
    return shifts


def _shift_label_by_id(shifts: list[dict], shift_id) -> str | None:
    if shift_id is None:
        return None
    for row in shifts:
        if row.get("id") == shift_id:
            return row.get("shift")
    return None


def sync_user_preferences_cache(user_id=None, email=None) -> dict | None:
    """Cache shifts list + logged-in user's default shift for registration page."""
    try:
        shifts = sync_shifts_cache()
        supabase: Client = init_supabase()
        default_shift_id = None
        default_shift = None
        resolved_user_id = user_id

        if user_id or email:
            query = supabase.table("users").select("id, email, default_shift_id")
            if user_id:
                query = query.eq("id", user_id)
            else:
                query = query.eq("email", (email or "").strip().lower())
            row_resp = query.limit(1).execute()
            if row_resp.data:
                u = row_resp.data[0]
                resolved_user_id = u.get("id")
                default_shift_id = u.get("default_shift_id")
                default_shift = _shift_label_by_id(shifts, default_shift_id)

        if not default_shift and shifts:
            default_shift = shifts[0].get("shift")

        payload = {
            "user_id": resolved_user_id,
            "email": email,
            "default_shift_id": default_shift_id,
            "default_shift": default_shift,
        }
        path = get_fetched_data_dir() / "user_preferences.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        logger.info("User preferences cached to fetcheddata/")
        return payload
    except Exception as e:
        log_error(e, "SYNC_USER_PREFERENCES_CACHE")
        return None


def list_shifts_admin():
    try:
        shifts = list_shifts_all()
        return {"status": "Success", "shifts": shifts}
    except Exception as e:
        log_error(e, "LIST_SHIFTS_ADMIN")
        return {"status": "Error", "shifts": [], "message": str(e)}


def create_shift_admin(shift_name: str, actor: str = "Admin"):
    try:
        label = (shift_name or "").strip().upper()
        if not label:
            return {"status": "Error", "message": "Shift name is required."}
        supabase: Client = init_supabase()
        dup = supabase.table("shift").select("id").eq("shift", label).limit(1).execute()
        if dup.data:
            return {"status": "Error", "message": f"Shift '{label}' already exists."}
        response = supabase.table("shift").insert({"shift": label}).execute()
        sync_shifts_cache()
        save_log(f"Created shift {label}", category="ADMIN_SHIFT", user=actor)
        return {"status": "Success", "data": response.data}
    except Exception as e:
        log_error(e, "CREATE_SHIFT_ADMIN", user=actor)
        return {"status": "Error", "message": str(e)}


def update_shift_admin(shift_id: int, shift_name: str, actor: str = "Admin"):
    try:
        label = (shift_name or "").strip().upper()
        if not label:
            return {"status": "Error", "message": "Shift name is required."}
        supabase: Client = init_supabase()
        dup = (
            supabase.table("shift")
            .select("id")
            .eq("shift", label)
            .neq("id", shift_id)
            .limit(1)
            .execute()
        )
        if dup.data:
            return {"status": "Error", "message": f"Shift '{label}' already exists."}
        response = supabase.table("shift").update({"shift": label}).eq("id", shift_id).execute()
        sync_shifts_cache()
        save_log(f"Updated shift ID {shift_id} -> {label}", category="ADMIN_SHIFT", user=actor)
        return {"status": "Success", "data": response.data}
    except Exception as e:
        log_error(e, f"UPDATE_SHIFT_ADMIN_{shift_id}", user=actor)
        return {"status": "Error", "message": str(e)}


def delete_shift_admin(shift_id: int, actor: str = "Admin"):
    try:
        supabase: Client = init_supabase()
        in_use = (
            supabase.table("users")
            .select("id")
            .eq("default_shift_id", shift_id)
            .limit(1)
            .execute()
        )
        if in_use.data:
            return {
                "status": "Error",
                "message": "Cannot delete: one or more users use this as their default shift.",
            }
        response = supabase.table("shift").delete().eq("id", shift_id).execute()
        sync_shifts_cache()
        save_log(f"Deleted shift ID {shift_id}", category="ADMIN_SHIFT", user=actor)
        return {"status": "Success", "data": response.data}
    except Exception as e:
        log_error(e, f"DELETE_SHIFT_ADMIN_{shift_id}", user=actor)
        return {"status": "Error", "message": str(e)}


def resolve_selected_test_display_names(selected_tests) -> list[str]:
    """Map registration dropdown values to display names for the receipt."""
    try:
        supabase: Client = init_supabase()
        tests_resp = supabase.table("tests").select("id, name").execute()
        tests_by_id = {t["id"]: t for t in (tests_resp.data or [])}
        groups_list = supabase.table("test_groups").select("*").execute().data or []
        min_test_id = min(tests_by_id.keys()) if tests_by_id else 171
        id_offset = min_test_id - 1

        names: list[str] = []
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
                    g_components = sorted([int(x) for x in (g.get("component_ids") or [])])
                    if g_components == sorted_components:
                        matched = g
                        break
                names.append(
                    matched.get("group_name") if matched else f"Group {sel_str}"
                )
            else:
                try:
                    test_id = int(sel_str)
                except ValueError:
                    continue
                actual_id = test_id + id_offset if test_id < min_test_id else test_id
                details = tests_by_id.get(actual_id) or tests_by_id.get(test_id)
                names.append(details.get("name") if details else f"Test {test_id}")

        return names
    except Exception as e:
        log_error(e, "RESOLVE_TEST_DISPLAY_NAMES")
        return []


def load_lab_print_settings_row():
    """Active print_settings row (A4 lab report layout)."""
    try:
        supabase: Client = init_supabase()
        response = (
            supabase.table("print_settings")
            .select("*")
            .eq("is_active", True)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]
        fallback = supabase.table("print_settings").select("*").order("id", desc=True).limit(1).execute()
        if fallback.data:
            return fallback.data[0]
    except Exception as e:
        log_error(e, "LOAD_LAB_PRINT_SETTINGS")
    return None


def read_cached_lab_print_settings() -> dict | None:
    path = get_fetched_data_dir() / "print_settings.json"
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.debug(f"Could not read cached print settings: {e}")
        return None


def sync_lab_print_settings_cache() -> dict | None:
    """Fetch lab print_settings from DB on login; cache under fetcheddata/."""
    existing_cached = read_cached_lab_print_settings() or {}
    row = load_lab_print_settings_row()
    if not row:
        return existing_cached or None
    cached = dict(row)
    cached["page_size"] = "A4"
    if "hidden_group_titles" not in cached or not cached["hidden_group_titles"]:
        cached["hidden_group_titles"] = existing_cached.get(
            "hidden_group_titles",
            "UCE, HEP B, C, UC, HEP B C, HEP B / C, HEP B, C (ICT), HEP B, C ELISA, HBSAG / HCV"
        )
    path = get_fetched_data_dir() / "print_settings.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cached, f, indent=2, default=str)
    logger.info("Lab print settings cached to fetcheddata/print_settings.json")
    return cached


def get_lab_print_settings_admin() -> dict:
    """Fetch global print settings for admin UI with standard fallback defaults."""
    cached = read_cached_lab_print_settings() or {}
    row = load_lab_print_settings_row()
    if row:
        merged = dict(row)
        if not merged.get("hidden_group_titles"):
            merged["hidden_group_titles"] = cached.get(
                "hidden_group_titles",
                "UCE, HEP B, C, UC, HEP B C, HEP B / C, HEP B, C (ICT), HEP B, C ELISA, HBSAG / HCV"
            )
        return merged
    if cached:
        return cached
    return {
        "category_font_size": 18,
        "group_font_size": 15,
        "test_name_font_size": 14,
        "result_font_size": 14,
        "patient_info_font_size": 14,
        "patient_info_label_font_size": 14,
        "footer_font_size": 11,
        "page_top_margin": 15,
        "page_right_margin": 15,
        "page_bottom_margin": 15,
        "page_left_margin": 15,
        "header_height": 0,
        "header_bottom_margin": 0,
        "patient_info_padding_vertical": 2,
        "patient_info_padding_horizontal": 4,
        "patient_info_min_height": 0,
        "patient_info_row_gap": 2,
        "patient_info_label_width": 110,
        "patient_info_bottom_margin": 8,
        "table_header_padding_vertical": 4,
        "table_header_padding_horizontal": 4,
        "table_cell_padding_vertical": 4,
        "table_cell_padding_horizontal": 4,
        "category_padding_top": 8,
        "category_padding_bottom": 4,
        "category_border_width": 2,
        "group_padding_top": 6,
        "group_padding_bottom": 2,
        "group_padding_left": 4,
        "footer_margin_top": 12,
        "footer_padding_top": 8,
        "signature_block_min_width": 140,
        "primary_color": "#111111",
        "secondary_color": "#475569",
        "border_color": "#0f172a",
        "bg_light": "#f8fafc",
        "text_main": "#0f172a",
        "text_muted": "#64748b",
        "display_verified_by": 1,
        "display_pathologist_signature": 1,
        "combine_categories_on_same_page": 1,
        "hide_single_param_title": 1,
        "hidden_group_titles": "UCE, HEP B, C, UC, HEP B C, HEP B / C, HEP B, C (ICT), HEP B, C ELISA, HBSAG / HCV",
        "page_size": "A4",
        "is_active": True,
    }


def update_lab_print_settings_admin(payload: dict, actor: str = "Admin") -> dict:
    """Update global lab print settings in Supabase and sync local cache."""
    try:
        supabase: Client = init_supabase()
        existing = load_lab_print_settings_row() or {}

        numeric_fields = [
            "category_font_size", "group_font_size", "test_name_font_size",
            "result_font_size", "patient_info_font_size", "patient_info_label_font_size",
            "footer_font_size", "display_verified_by", "display_pathologist_signature",
            "hide_single_param_title", "combine_categories_on_same_page",
            "page_top_margin", "page_right_margin", "page_bottom_margin", "page_left_margin",
            "header_height", "header_bottom_margin", "patient_info_padding_vertical",
            "patient_info_padding_horizontal", "patient_info_min_height", "patient_info_row_gap",
            "patient_info_label_width", "patient_info_bottom_margin",
            "table_header_padding_vertical", "table_header_padding_horizontal",
            "table_cell_padding_vertical", "table_cell_padding_horizontal",
            "category_padding_top", "category_padding_bottom", "category_border_width",
            "group_padding_top", "group_padding_bottom", "group_padding_left",
            "footer_margin_top", "footer_padding_top", "signature_block_min_width"
        ]
        str_fields = [
            "primary_color", "secondary_color", "border_color", "bg_light", "text_main", "text_muted", "hidden_group_titles"
        ]

        update_data = {}
        for key in numeric_fields:
            if key in payload and payload[key] is not None and payload[key] != "":
                try:
                    fval = float(payload[key])
                    existing_val = existing.get(key)
                    if (isinstance(existing_val, int) and not isinstance(existing_val, bool)) or fval.is_integer():
                        update_data[key] = int(round(fval))
                    else:
                        update_data[key] = fval
                except (ValueError, TypeError):
                    pass

        for key in str_fields:
            if key in payload and payload[key] is not None:
                update_data[key] = str(payload[key]).strip()

        if "is_active" in payload:
            update_data["is_active"] = bool(payload["is_active"])
        else:
            update_data["is_active"] = True

        if not update_data:
            return {"status": "Error", "message": "No valid print settings parameters provided."}

        update_data["updated_by"] = actor

        # Save to local fetcheddata cache immediately
        cached_path = get_fetched_data_dir() / "print_settings.json"
        cdata = read_cached_lab_print_settings() or {}
        cdata.update(update_data)
        if "hidden_group_titles" in payload:
            cdata["hidden_group_titles"] = str(payload["hidden_group_titles"]).strip()
        with open(cached_path, "w", encoding="utf-8") as f:
            json.dump(cdata, f, indent=2, default=str)

        # Attempt Supabase update (gracefully retry if remote schema lacks hidden_group_titles)
        result_row = None
        try:
            if existing and existing.get("id"):
                row_id = existing["id"]
                resp = supabase.table("print_settings").update(update_data).eq("id", row_id).execute()
                result_row = resp.data[0] if resp.data else None
            else:
                update_data["created_by"] = actor
                resp = supabase.table("print_settings").insert(update_data).execute()
                result_row = resp.data[0] if resp.data else None
        except Exception as se:
            err_str = str(se)
            if "hidden_group_titles" in err_str or "PGRST204" in err_str:
                update_data_clean = dict(update_data)
                update_data_clean.pop("hidden_group_titles", None)
                if existing and existing.get("id"):
                    row_id = existing["id"]
                    resp = supabase.table("print_settings").update(update_data_clean).eq("id", row_id).execute()
                    result_row = resp.data[0] if resp.data else None
                else:
                    update_data_clean["created_by"] = actor
                    resp = supabase.table("print_settings").insert(update_data_clean).execute()
                    result_row = resp.data[0] if resp.data else None
            else:
                raise se

        sync_lab_print_settings_cache()
        save_log("Lab print settings updated globally", category="ADMIN", user=actor)
        return {"status": "Success", "message": "Print settings saved successfully.", "data": result_row or cdata}
    except Exception as e:
        log_error(e, "UPDATE_LAB_PRINT_SETTINGS_ADMIN", user=actor)
        return {"status": "Error", "message": str(e)}


def list_remarks_all(active_only: bool = True) -> list[dict]:
    try:
        supabase: Client = init_supabase()
        query = supabase.table("remarks").select(
            "id, remark_text, test_name, category, usage_count, sort_order, is_active, created_at, updated_at"
        )
        if active_only:
            query = query.eq("is_active", True)
        response = query.order("sort_order").order("usage_count", desc=True).execute()
        return response.data or []
    except Exception as e:
        log_error(e, "LIST_REMARKS_ALL")
        return []


def _build_remarks_cache_payload(rows: list[dict]) -> dict:
    global_list = []
    by_test_name: dict[str, list] = {}
    by_category: dict[str, list] = {}

    def add_bucket(bucket: dict, key: str, entry: dict):
        if not key:
            return
        bucket.setdefault(key, []).append(entry)

    for row in rows:
        if not row.get("is_active", True):
            continue
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

    return {
        "items": rows,
        "global": global_list,
        "by_test_name": by_test_name,
        "by_category": by_category,
    }


def sync_remarks_cache() -> dict | None:
    """Fetch remarks from DB; cache grouped suggestions under fetcheddata/remarks.json."""
    try:
        rows = list_remarks_all(active_only=True)
        payload = _build_remarks_cache_payload(rows)
        path = get_fetched_data_dir() / "remarks.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        logger.info("Remarks cached to fetcheddata/remarks.json")
        return payload
    except Exception as e:
        log_error(e, "SYNC_REMARKS_CACHE")
        return None


def record_remark_usage(remark_text: str, test_name: str | None = None, category: str | None = None):
    """Increment usage_count when staff save a remark on a test result."""
    text = (remark_text or "").strip()
    if not text:
        return
    try:
        supabase: Client = init_supabase()
        test_key = (test_name or "").strip() or None
        cat_key = (category or "").strip() or None
        query = supabase.table("remarks").select("id, usage_count").eq("is_active", True).eq(
            "remark_text", text
        )
        if test_key:
            query = query.eq("test_name", test_key)
        elif cat_key:
            query = query.is_("test_name", "null").eq("category", cat_key)
        else:
            query = query.is_("test_name", "null").is_("category", "null")
        found = query.limit(1).execute()
        if found.data:
            row = found.data[0]
            supabase.table("remarks").update(
                {"usage_count": int(row.get("usage_count") or 0) + 1, "updated_at": "now()"}
            ).eq("id", row["id"]).execute()
    except Exception as e:
        logger.debug(f"record_remark_usage skipped: {e}")


def list_remarks_admin():
    try:
        rows = list_remarks_all(active_only=False)
        return {"status": "Success", "remarks": rows}
    except Exception as e:
        log_error(e, "LIST_REMARKS_ADMIN")
        return {"status": "Error", "remarks": [], "message": str(e)}


def create_remark_admin(payload: dict, actor: str = "Admin"):
    try:
        text = (payload.get("remark_text") or payload.get("text") or "").strip()
        if not text:
            return {"status": "Error", "message": "Remark text is required."}
        supabase: Client = init_supabase()
        row = {
            "remark_text": text,
            "test_name": (payload.get("test_name") or "").strip() or None,
            "category": (payload.get("category") or "").strip() or None,
            "sort_order": int(payload.get("sort_order") or 0),
            "is_active": bool(payload.get("is_active", True)),
        }
        resp = supabase.table("remarks").insert(row).execute()
        sync_remarks_cache()
        save_log(f"Remark created: {text[:80]}", category="ADMIN", user=actor)
        return {"status": "Success", "remark": resp.data[0] if resp.data else row}
    except Exception as e:
        log_error(e, "CREATE_REMARK_ADMIN", user=actor)
        return {"status": "Error", "message": str(e)}


def update_remark_admin(remark_id: int, payload: dict, actor: str = "Admin"):
    try:
        supabase: Client = init_supabase()
        update = {}
        if "remark_text" in payload or "text" in payload:
            text = (payload.get("remark_text") or payload.get("text") or "").strip()
            if not text:
                return {"status": "Error", "message": "Remark text cannot be empty."}
            update["remark_text"] = text
        if "test_name" in payload:
            update["test_name"] = (payload.get("test_name") or "").strip() or None
        if "category" in payload:
            update["category"] = (payload.get("category") or "").strip() or None
        if "sort_order" in payload:
            update["sort_order"] = int(payload.get("sort_order") or 0)
        if "is_active" in payload:
            update["is_active"] = bool(payload.get("is_active"))
        if not update:
            return {"status": "Error", "message": "Nothing to update."}
        update["updated_at"] = "now()"
        resp = supabase.table("remarks").update(update).eq("id", remark_id).execute()
        sync_remarks_cache()
        save_log(f"Remark updated id={remark_id}", category="ADMIN", user=actor)
        return {"status": "Success", "remark": resp.data[0] if resp.data else None}
    except Exception as e:
        log_error(e, "UPDATE_REMARK_ADMIN", user=actor)
        return {"status": "Error", "message": str(e)}


def delete_remark_admin(remark_id: int, actor: str = "Admin"):
    try:
        supabase: Client = init_supabase()
        supabase.table("remarks").update({"is_active": False, "updated_at": "now()"}).eq("id", remark_id).execute()
        sync_remarks_cache()
        save_log(f"Remark deactivated id={remark_id}", category="ADMIN", user=actor)
        return {"status": "Success"}
    except Exception as e:
        log_error(e, "DELETE_REMARK_ADMIN", user=actor)
        return {"status": "Error", "message": str(e)}


def loadPrintSettings():
    try:
        cached = read_cached_lab_print_settings()
        if cached:
            return [cached]
        row = sync_lab_print_settings_cache()
        return [row] if row else []
    except Exception as e:
        log_error(e, "LOAD_PRINT_SETTINGS")
        return []

def loginUsers():
    try:
        supabase : Client = init_supabase()
        response = supabase.table("users").select("*").execute()
        logger.info("Fetched user list for login")
        return response.data
    except Exception as e:
        log_error(e, "LOGIN_USERS_FETCH")
        return []


def _load_users_cache():
    try:
        path = os.path.join(os.path.dirname(__file__), "fetcheddata", "users.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("users") or []
    except Exception as e:
        logger.warning(f"Failed to load users cache: {e}")
    return []


def _save_users_cache(users: list):
    try:
        fetched_dir = os.path.join(os.path.dirname(__file__), "fetcheddata")
        os.makedirs(fetched_dir, exist_ok=True)
        path = os.path.join(fetched_dir, "users.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"users": users}, f, indent=2, default=str)
        logger.info(f"Saved {len(users)} users to fetcheddata/users.json")
    except Exception as e:
        logger.warning(f"Failed to save users cache: {e}")


def list_login_users():
    """Active users for login page dropdown (no passwords). Falls back to cache if offline."""
    try:
        supabase: Client = init_supabase()
        query = supabase.table("users").select("id, name, email, is_active, pwd, default_shift_id, permissions")
        response = query.order("name").execute()
        raw_users = response.data or []
        if raw_users:
            _save_users_cache(raw_users)
            try:
                from offline.database import upsert_users_from_supabase
                upsert_users_from_supabase(raw_users)
            except Exception:
                pass

        users = []
        for row in raw_users:
            if row.get("is_active") is False:
                continue
            email = (row.get("email") or "").strip().lower()
            if not email:
                continue
            users.append({
                "id": row.get("id"),
                "name": (row.get("name") or email).strip(),
                "email": email,
            })
        return {"status": "Success", "users": users}
    except Exception as e:
        logger.warning(f"Supabase list_login_users failed ({e}), falling back to local users cache.")
        cached = _load_users_cache()
        users = []
        for row in cached:
            if row.get("is_active") is False:
                continue
            email = (row.get("email") or "").strip().lower()
            if not email:
                continue
            users.append({
                "id": row.get("id"),
                "name": (row.get("name") or email).strip(),
                "email": email,
            })
        if users:
            return {"status": "Success", "users": users, "cached": True}
        log_error(e, "LIST_LOGIN_USERS")
        return {"status": "Error", "users": [], "message": str(e)}


def _users_schema_ready(supabase: Client) -> bool:
    try:
        supabase.table("users").select("is_active, permissions").limit(1).execute()
        return True
    except Exception:
        return False


def list_users_admin():
    from user_access import public_user_dict
    try:
        supabase = init_supabase()
        if not _users_schema_ready(supabase):
            return {"status": "schema_required", "users": [], "message": "Run scripts/add_users_permissions.sql in Supabase."}
        response = supabase.table("users").select("*").order("id").execute()
        shift_rows = {s["id"]: s.get("shift") for s in list_shifts_all()}
        users = []
        for r in response.data or []:
            u = public_user_dict(r)
            sid = r.get("default_shift_id")
            if sid and sid in shift_rows:
                u["default_shift"] = shift_rows[sid]
            users.append(u)
        return {"status": "Success", "users": users}
    except Exception as e:
        log_error(e, "LIST_USERS_ADMIN")
        return {"status": "Error", "users": [], "message": str(e)}


def create_user_admin(payload: dict, actor: str = "Admin"):
    from user_access import sanitize_user_payload
    try:
        supabase = init_supabase()
        if not _users_schema_ready(supabase):
            return {"status": "schema_required", "message": "Run scripts/add_users_permissions.sql in Supabase."}
        data = sanitize_user_payload(payload)
        if not data["name"] or not data["email"]:
            return {"status": "Error", "message": "Name and email are required."}
        if not data["pwd"]:
            return {"status": "Error", "message": "Password is required for new users."}
        dup = supabase.table("users").select("id").eq("email", data["email"]).limit(1).execute()
        if dup.data:
            return {"status": "Error", "message": "Email already exists."}
        insert_row = {
            "name": data["name"],
            "email": data["email"],
            "pwd": data["pwd"],
            "is_active": data["is_active"],
            "permissions": data["permissions"],
        }
        if data.get("default_shift_id") is not None:
            insert_row["default_shift_id"] = data["default_shift_id"]
        response = supabase.table("users").insert(insert_row).execute()
        save_log(f"Created user {data['email']}", category="ADMIN_USER", user=actor)
        return {"status": "Success", "data": response.data}
    except Exception as e:
        log_error(e, "CREATE_USER_ADMIN", user=actor)
        return {"status": "Error", "message": str(e)}


def update_user_admin(user_id: int, payload: dict, actor: str = "Admin"):
    from user_access import sanitize_user_payload
    try:
        supabase = init_supabase()
        if not _users_schema_ready(supabase):
            return {"status": "schema_required", "message": "Run scripts/add_users_permissions.sql in Supabase."}
        data = sanitize_user_payload(payload)
        update_row = {}
        if data["name"]:
            update_row["name"] = data["name"]
        if data["email"]:
            update_row["email"] = data["email"]
        if data["pwd"]:
            update_row["pwd"] = data["pwd"]
        update_row["is_active"] = data["is_active"]
        update_row["permissions"] = data["permissions"]
        if "default_shift_id" in data:
            update_row["default_shift_id"] = data["default_shift_id"]
        if not update_row:
            return {"status": "Error", "message": "Nothing to update."}
        response = supabase.table("users").update(update_row).eq("id", user_id).execute()
        save_log(f"Updated user ID {user_id}", category="ADMIN_USER", user=actor)
        return {"status": "Success", "data": response.data}
    except Exception as e:
        log_error(e, f"UPDATE_USER_ADMIN_{user_id}", user=actor)
        return {"status": "Error", "message": str(e)}


def authenticate_user(email: str, password: str):
    from user_access import public_user_dict, user_is_active, permissions_from_user_row
    email_norm = (email or "").strip().lower()
    try:
        supabase = init_supabase()
        response = supabase.table("users").select("*").eq("email", email_norm).limit(1).execute()
        rows = response.data or []
        if not rows:
            return None
        row = rows[0]
        if (row.get("pwd") or "") != (password or ""):
            return None
        schema_ready = _users_schema_ready(supabase)
        if schema_ready and not user_is_active(row):
            return {"disabled": True}
        user_out = public_user_dict(row)
        user_out["permissions"] = permissions_from_user_row(row) if schema_ready else None
        if row.get("default_shift_id"):
            try:
                shift_resp = (
                    supabase.table("shift")
                    .select("shift")
                    .eq("id", row["default_shift_id"])
                    .limit(1)
                    .execute()
                )
                if shift_resp.data:
                    user_out["default_shift"] = shift_resp.data[0].get("shift")
            except Exception:
                pass
        return user_out
    except Exception as e:
        logger.warning(f"Supabase authenticate_user failed ({e}), checking local users cache.")
        cached_users = _load_users_cache()
        for row in cached_users:
            if (row.get("email") or "").strip().lower() == email_norm:
                if (row.get("pwd") or "") != (password or ""):
                    return None
                if row.get("is_active") is False:
                    return {"disabled": True}
                user_out = public_user_dict(row)
                user_out["permissions"] = permissions_from_user_row(row)
                
                # Try finding shift in shifts.json
                shift_id = row.get("default_shift_id")
                if shift_id:
                    try:
                        shifts_path = os.path.join(os.path.dirname(__file__), "fetcheddata", "shifts.json")
                        if os.path.exists(shifts_path):
                            with open(shifts_path, "r", encoding="utf-8") as sf:
                                sdata = json.load(sf)
                                for s in (sdata.get("shifts") or []):
                                    if s.get("id") == shift_id:
                                        user_out["default_shift"] = s.get("shift")
                                        break
                    except Exception:
                        pass
                return user_out
        log_error(e, "AUTHENTICATE_USER")
        return None

def save_fitness_record_db(item: dict, user="System"):
    try:
        save_log(item, category="SAVE_FITNESS_PAYLOAD", user=user)
        supabase : Client = init_supabase()
        
        db_payload = {
            "patient_name": item.get("patient_name"),
            "gender": item.get("gender"),
            "relation_type": item.get("relation_type"),
            "relation_name": item.get("relation_name"),
            "report_date": item.get("report_date"),
            "mr_no": item.get("mr_no"),
            "hb": item.get("hb"),
            "wbc": item.get("wbc"),
            "neut": item.get("neut"),
            "lymph": item.get("lymph"),
            "mono": item.get("mono"),
            "eosino": item.get("eosino"),
            "plt": item.get("plt"),
            "hiv": item.get("hiv"),
            "hbsag": item.get("hbsag"),
            "hcv": item.get("hcv"),
            "vdrl": item.get("vdrl"),
            "created_by": item.get("user_email") or user
        }
        
        response = supabase.table("fitness_patients").insert(db_payload).execute()
        if not response.data:
            logger.error("No data returned from save_fitness_record_db insert!")
            return None
        
        logger.info(f"Successfully saved fitness record to Supabase. ID: {response.data[0]['id']}")
        return response.data[0]
    except Exception as e:
        log_error(e, "SAVE_FITNESS_RECORD_FAILED", user=user)
        raise

# def changeVisiblityInDb(include_in_report,patienr_id):
#     supabase : Client = init_supabase()
#     response = supabase.table("patient_test_results").update({"include_in_report":include_in_report}).eq("id",patienr_id).execute()
#     return response.data

def get_fitness_records(date_from: str = None, date_to: str = None, search: str = None):
    """Fetch fitness records from DB and merge with unsynced local JSON files."""
    import glob, time
    db_records = []
    try:
        supabase = init_supabase()
        query = supabase.table("fitness_patients").select("*").order("id", desc=True)
        if date_from:
            query = query.gte("report_date", date_from)
        if date_to:
            query = query.lte("report_date", date_to)
        result = query.execute()
        for r in (result.data or []):
            r["source"] = "db"
            r["synced"] = True
            db_records.append(r)
        logger.info(f"Loaded {len(db_records)} fitness records from DB")
    except Exception as e:
        log_error(e, "GET_FITNESS_RECORDS_DB")

    # Load unsynced local records from JSON queue
    local_records = []
    try:
        base = get_base_path()
        records_dir = os.path.join(base, "records")
        for file_path in glob.glob(os.path.join(records_dir, "fitness_*.json")):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not data.get("synced"):
                    local_records.append({
                        **data,
                        "id": None,
                        "patient_name": data.get("patient_name"),
                        "mr_no": data.get("mr_no"),
                        "relation_type": data.get("relation_type"),
                        "relation_name": data.get("relation_name"),
                        "report_date": data.get("report_date"),
                        "created_at": data.get("saved_at"),
                        "source": "local",
                        "synced": False,
                        "_file": file_path
                    })
            except Exception:
                pass
    except Exception as e:
        log_error(e, "GET_FITNESS_RECORDS_LOCAL")

    all_records = db_records + local_records

    # Apply search filter client-side across combined list
    if search:
        s = search.lower()
        all_records = [r for r in all_records if
            s in (r.get("patient_name") or "").lower() or
            s in (r.get("mr_no") or "").lower()]

    return all_records

def save_fitness_record_json(item: dict):
    try:
        import time
        # Get base path to save under base workspace folder
        base = get_base_path()
        records_dir = os.path.join(base, "records")
        os.makedirs(records_dir, exist_ok=True)
        
        mr_no = item.get("mr_no") or "unknown"
        timestamp = int(time.time() * 1000)
        filename = os.path.join(records_dir, f"fitness_{mr_no}_{timestamp}.json")
        
        file_payload = {
            **item,
            "synced": False,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(file_payload, f, indent=4)
            
        logger.info(f"Local JSON save success: {filename}")
        return filename
    except Exception as e:
        log_error(e, "SAVE_FITNESS_JSON_FAILED")
        return None

def sync_single_record_bg(item: dict, filename: str, user="System"):
    try:
        if not filename or not os.path.exists(filename):
            return
        
        logger.info(f"Background Sync: Single attempt for {filename}")
        result = save_fitness_record_db(item, user=user)
        if result:
            # Update local file state to synced
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["synced"] = True
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            logger.info(f"Background Sync: Single success for {filename}")
    except Exception as err:
        logger.error(f"Background Sync: Single failed for {filename}: {err}")

def sync_offline_records(user="System"):
    try:
        import glob
        base = get_base_path()
        records_dir = os.path.join(base, "records")
        if not os.path.exists(records_dir):
            return
            
        search_pattern = os.path.join(records_dir, "fitness_*.json")
        files = glob.glob(search_pattern)
        
        for file_path in files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                if not data.get("synced"):
                    logger.info(f"Background Sync: Syncing old record {file_path} to DB")
                    result = save_fitness_record_db(data, user=user)
                    if result:
                        data["synced"] = True
                        with open(file_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=4)
                        logger.info(f"Background Sync: Successfully synced record from file {file_path}")
            except Exception as file_err:
                logger.error(f"Background Sync: Failed to sync record file {file_path}: {file_err}")
    except Exception as e:
        logger.error(f"Background Sync: Scanning error: {e}")

def add_tests_to_patient_all(patient_id, patient_mr_no, patient_name, selected_tests, user="System"):
    try:
        supabase: Client = init_supabase()
        
        # Load all individual tests to match and fetch ranges/names
        tests_resp = supabase.table("tests").select("*").execute()
        tests_list = tests_resp.data or []
        tests_by_id = {t["id"]: t for t in tests_list}
        
        # Load all group tests to fetch categories and names
        groups_resp = supabase.table("test_groups").select("*").execute()
        groups_list = groups_resp.data or []
        
        # Dynamically compute the ID offset between seeded tests and DB IDs
        min_test_id = min(tests_by_id.keys()) if tests_by_id else 171
        id_offset = min_test_id - 1  # e.g., 171 - 1 = 170
        
        def build_test_parameter_json(test_details):
            return {
                "name": test_details.get("name"),
                "value": "0",
                "unit": test_details.get("unit"),
                "normal_min": test_details.get("normal_min"),
                "normal_max": test_details.get("normal_max")
            }

        log = []
        logger.info(f"Adding tests to patient MR: {patient_mr_no}, Name: {patient_name}")
        
        # Filter out empty/null selected tests
        valid_selections = [t for t in selected_tests if t not in (None, "", 0, "0")]
        
        for sel in valid_selections:
            sel_str = str(sel).strip()
            
            # Check if this selection is a group test
            if sel_str.startswith("[") and sel_str.endswith("]"):
                try:
                    component_ids = json.loads(sel_str)
                except Exception as je:
                    logger.error(f"Failed to parse group test JSON '{sel_str}': {je}")
                    continue
                
                # Find matching group test
                matched_group = None
                sorted_components = sorted([int(x) for x in component_ids])
                
                for g in groups_list:
                    g_components = sorted([int(x) for x in (g.get("component_ids") or [])])
                    if g_components == sorted_components:
                        matched_group = g
                        break
                
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
                
                payload = {
                    "mr_no": patient_mr_no,
                    "patient_name": patient_name,
                    "category": category,
                    "test_name": test_name,
                    "test_values": test_values,
                    "status": "Pending"
                }
                response = supabase.table("test_results_all").insert(payload).execute()
                log.append(response.data)
                
            else:
                # Individual test
                try:
                    test_id = int(sel_str)
                except ValueError:
                    logger.error(f"Invalid individual test ID: {sel_str}")
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
                    
                    payload = {
                        "mr_no": patient_mr_no,
                        "patient_name": patient_name,
                        "category": category,
                        "test_name": test_name,
                        "test_values": test_values,
                        "status": "Pending"
                    }
                    response = supabase.table("test_results_all").insert(payload).execute()
                    log.append(response.data)
                    
        logger.info(f"Successfully added {len(log)} test records in test_results_all for patient {patient_mr_no}")
        return log
        
    except Exception as e:
        log_error(e, "ADD_TESTS_TO_PATIENT_ALL_FAILED", user=user)
        return []