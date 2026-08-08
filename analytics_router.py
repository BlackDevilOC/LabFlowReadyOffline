"""Analytics API routes for LabFlow admin reporting."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from analytics_pdf import build_analytics_pdf
from analytics_service import get_analytics_snapshot, save_analytics_pdf_to_system_logs
from logdata import log_error, save_log
from patient_list_query import normalize_date_range

router = APIRouter(prefix="/api/v1/admin/analytics", tags=["Analytics"])

ADMIN_GATE_PASSWORD = "youcannotenter"


def _require_admin_password(request: Request) -> None:
    pwd = (request.headers.get("X-Admin-Password") or "").strip()
    if pwd != ADMIN_GATE_PASSWORD:
        raise HTTPException(status_code=403, detail="Admin password required.")


def _actor_label(request: Request) -> str:
    return (request.headers.get("X-User-Email") or "Analytics").strip() or "Analytics"


def _parse_range(date_from: str | None, date_to: str | None) -> tuple[str, str]:
    d_from, d_to = normalize_date_range(date_from, date_to)
    if not d_from or not d_to:
        from datetime import date

        today = date.today().isoformat()
        return d_from or today, d_to or today
    return d_from, d_to


@router.get("/overview")
def analytics_overview(
    request: Request,
    date_from: str | None = Query(None, description="Start date YYYY-MM-DD"),
    date_to: str | None = Query(None, description="End date YYYY-MM-DD"),
    refresh: bool = Query(False, description="Bypass snapshot cache"),
):
    _require_admin_password(request)
    d_from, d_to = _parse_range(date_from, date_to)
    try:
        data = get_analytics_snapshot("overview", d_from, d_to, force_refresh=refresh)
        save_log(
            f"Analytics overview {d_from}..{d_to}",
            category="ANALYTICS_VIEW",
            user=_actor_label(request),
        )
        return {"status": "Success", "data": data}
    except Exception as e:
        log_error(e, "ANALYTICS_OVERVIEW")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/telemetry")
def analytics_telemetry(
    request: Request,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    refresh: bool = Query(False),
):
    _require_admin_password(request)
    d_from, d_to = _parse_range(date_from, date_to)
    try:
        data = get_analytics_snapshot("telemetry", d_from, d_to, force_refresh=refresh)
        save_log(
            f"Analytics telemetry {d_from}..{d_to}",
            category="ANALYTICS_VIEW",
            user=_actor_label(request),
        )
        return {"status": "Success", "data": data}
    except Exception as e:
        log_error(e, "ANALYTICS_TELEMETRY")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/tests")
def analytics_tests(
    request: Request,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    refresh: bool = Query(False),
):
    _require_admin_password(request)
    d_from, d_to = _parse_range(date_from, date_to)
    try:
        data = get_analytics_snapshot("tests", d_from, d_to, force_refresh=refresh)
        save_log(
            f"Analytics tests {d_from}..{d_to}",
            category="ANALYTICS_VIEW",
            user=_actor_label(request),
        )
        return {"status": "Success", "data": data}
    except Exception as e:
        log_error(e, "ANALYTICS_TESTS")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/export/pdf")
def analytics_export_pdf(
    request: Request,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    pathologist_name: str | None = Query(None),
    lab_name: str | None = Query(None),
):
    _require_admin_password(request)
    d_from, d_to = _parse_range(date_from, date_to)
    try:
        pdf_bytes = build_analytics_pdf(
            d_from,
            d_to,
            pathologist_name=(pathologist_name or "Pathologist Incharge").strip(),
            lab_name=(lab_name or "Laboratory Operations Unit").strip(),
        )
        save_analytics_pdf_to_system_logs(pdf_bytes, d_from, d_to)
        save_log(
            f"Analytics PDF export {d_from}..{d_to}",
            category="ANALYTICS_EXPORT",
            user=_actor_label(request),
        )
        filename = f"LabFlow_Analytics_{d_from}_to_{d_to}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        log_error(e, "ANALYTICS_PDF_EXPORT")
        raise HTTPException(status_code=500, detail=str(e)) from e
