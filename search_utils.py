"""Advanced multi-field search helpers for lab patient listings."""
import json
from typing import Any


SEARCH_FIELDS = {
    "patient_name": "Patient Name",
    "mr_no": "MR Number",
    "patient_token": "Token No",
    "relation_name": "Relation Name",
    "user": "Registered By (User)",
    "category": "Test Category",
    "test_name": "Test Name",
    "mobile": "Mobile",
}


def parse_advanced_filters(filters_param: str | None) -> list[dict[str, Any]]:
    if not filters_param or not str(filters_param).strip():
        return []
    try:
        data = json.loads(filters_param)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        value = str(item.get("value") or "").strip()
        if not field or not value:
            continue
        entry = {"field": field, "value": value}
        if item.get("user_id") not in (None, ""):
            entry["user_id"] = item.get("user_id")
        out.append(entry)
    return out


def _patient_slice(row: dict) -> dict:
    p = row.get("patients")
    return p if isinstance(p, dict) else {}


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def legacy_search_matches(row: dict, search: str | None) -> bool:
    if not search or not str(search).strip():
        return True
    s = str(search).strip()
    if s.isdigit():
        try:
            return int(row.get("mr_no") or -1) == int(s)
        except ValueError:
            pass
    return s.lower() in _norm(row.get("patient_name"))


def row_matches_advanced_filters(
    row: dict,
    filters: list[dict[str, Any]],
    *,
    legacy_search: str | None = None,
) -> bool:
    if not legacy_search_matches(row, legacy_search):
        return False
    if not filters:
        return True

    p = _patient_slice(row)

    for f in filters:
        field = f.get("field")
        val = str(f.get("value") or "").strip()
        if not val:
            continue
        val_l = val.lower()

        if field == "patient_name":
            if val_l not in _norm(row.get("patient_name")):
                return False

        elif field == "mr_no":
            mr = row.get("mr_no")
            if val.isdigit():
                if int(mr or -1) != int(val):
                    return False
            elif str(mr) != val:
                return False

        elif field == "patient_token":
            token = str(row.get("patient_token") or p.get("patient_token") or "")
            if val not in token:
                return False

        elif field == "relation_name":
            rel = _norm(row.get("relation_name") or p.get("relation_name"))
            if val_l not in rel:
                return False

        elif field == "user":
            uid = f.get("user_id")
            row_uid = row.get("user_id") if row.get("user_id") is not None else p.get("user_id")
            row_user = _norm(row.get("user") or p.get("user"))
            if uid not in (None, ""):
                if str(row_uid) != str(uid):
                    return False
            elif val_l not in row_user:
                return False

        elif field == "category":
            cat = _norm(row.get("category"))
            if val_l not in cat and cat != val_l:
                return False

        elif field == "test_name":
            if val_l not in _norm(row.get("test_name")):
                return False

        elif field == "mobile":
            mob = str(row.get("mobile") or p.get("mobile") or "")
            if val not in mob:
                return False

        else:
            continue

    return True
