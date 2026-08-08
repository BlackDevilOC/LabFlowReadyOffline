"""User permissions and admin user-management helpers."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

# Permission keys used across the app (sidebar + admin sections).
PERMISSION_KEYS = (
    "register",
    "update_results",
    "fitness",
    "print",
    "fluid_reports",
    "admin",
    "analytics",
    "manage_users",
    "manage_tests",
)

PERMISSION_LABELS: dict[str, str] = {
    "register": "Patient Registration",
    "update_results": "Enter Test Results",
    "fitness": "Fitness Reports",
    "print": "Print Records",
    "fluid_reports": "Fluid Reports",
    "admin": "Admin Panel (overview, logs)",
    "analytics": "Analytics & Reporting",
    "manage_users": "Manage Users & Permissions",
    "manage_tests": "Tests Configuration",
}

DEFAULT_PERMISSIONS: dict[str, bool] = {
    "register": True,
    "update_results": True,
    "fitness": True,
    "print": True,
    "fluid_reports": True,
    "admin": False,
    "analytics": False,
    "manage_users": False,
    "manage_tests": False,
}

# First user / bootstrap admin gets full access when permissions column is empty.
ADMIN_FULL_PERMISSIONS: dict[str, bool] = {k: True for k in PERMISSION_KEYS}


def normalize_permissions(raw: Any) -> dict[str, bool]:
    base = deepcopy(DEFAULT_PERMISSIONS)
    if raw is None:
        return base
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return base
    if not isinstance(raw, dict):
        return base
    for key in PERMISSION_KEYS:
        if key in raw:
            base[key] = bool(raw[key])
    return base


def permissions_from_user_row(row: dict | None) -> dict[str, bool]:
    if not row:
        return deepcopy(DEFAULT_PERMISSIONS)
    perms = normalize_permissions(row.get("permissions"))
    if not row.get("permissions") and row.get("id") == 1:
        return deepcopy(ADMIN_FULL_PERMISSIONS)
    return perms


def user_is_active(row: dict | None) -> bool:
    if not row:
        return False
    if "is_active" not in row:
        return True
    return bool(row.get("is_active"))


def public_user_dict(row: dict) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.get("id"),
        "name": row.get("name") or "",
        "email": row.get("email") or "",
        "is_active": user_is_active(row),
        "permissions": permissions_from_user_row(row),
        "created_at": row.get("created_at"),
    }
    if "default_shift_id" in row:
        out["default_shift_id"] = row.get("default_shift_id")
    if row.get("default_shift"):
        out["default_shift"] = row.get("default_shift")
    return out


def sanitize_user_payload(data: dict) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    pwd = data.get("password") or data.get("pwd") or ""
    is_active = data.get("is_active", True)
    if isinstance(is_active, str):
        is_active = is_active.lower() in ("1", "true", "yes", "on")
    perms_in = data.get("permissions")
    if isinstance(perms_in, dict):
        permissions = {k: bool(perms_in.get(k)) for k in PERMISSION_KEYS}
    else:
        permissions = normalize_permissions(perms_in)
    default_shift_id = data.get("default_shift_id")
    if default_shift_id in (None, "", "null", "none"):
        shift_id_out = None
    else:
        try:
            shift_id_out = int(default_shift_id)
        except (TypeError, ValueError):
            shift_id_out = None

    return {
        "name": name,
        "email": email,
        "pwd": pwd,
        "is_active": bool(is_active),
        "permissions": permissions,
        "default_shift_id": shift_id_out,
    }
