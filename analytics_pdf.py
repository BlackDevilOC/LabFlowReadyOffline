"""Formal Pathologist Incharge PDF report for LabFlow analytics."""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:
    colors = None
    TA_CENTER = None
    A4 = None
    ParagraphStyle = getSampleStyleSheet = cm = None
    HRFlowable = Paragraph = SimpleDocTemplate = Spacer = Table = TableStyle = None

from analytics_service import compute_overview, compute_telemetry, compute_tests


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Heading1"],
            fontSize=16,
            textColor=colors.HexColor("#1e3a8a"),
            spaceAfter=6,
            alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#475569"),
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        "section": ParagraphStyle(
            "Section",
            parent=base["Heading2"],
            fontSize=12,
            textColor=colors.HexColor("#1e40af"),
            spaceBefore=12,
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#334155"),
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#64748b"),
        ),
    }


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(_cell(v) for v in value)
    return str(value)


def _table(data: list[list], col_widths=None) -> Table:
    safe_data = [[_cell(c) for c in row] for row in data]
    tbl = Table(safe_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eff6ff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return tbl


def build_analytics_pdf(
    date_from: str,
    date_to: str,
    *,
    pathologist_name: str = "Pathologist Incharge",
    lab_name: str = "Laboratory Operations Unit",
) -> bytes:
    overview = compute_overview(date_from, date_to)
    telemetry = compute_telemetry(date_from, date_to)
    tests = compute_tests(date_from, date_to)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.8 * cm,
        title=f"LabFlow Analytics Report {date_from} to {date_to}",
    )
    s = _styles()
    story: list[Any] = []

    story.append(Paragraph("LABORATORY OPERATIONAL ANALYTICS REPORT", s["title"]))
    story.append(
        Paragraph(
            f"{lab_name}<br/>Reporting Period: {date_from} to {date_to}<br/>Generated: {generated}",
            s["subtitle"],
        )
    )
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#93c5fd")))
    story.append(Spacer(1, 10))

    ok = overview.get("kpis") or {}
    story.append(Paragraph("1. Executive Summary", s["section"]))
    summary_rows = [
        ["Metric", "Value"],
        ["Total Patient Registrations", str(ok.get("total_patients", 0))],
        ["Total Tests Ordered / Recorded", str(ok.get("total_tests", 0))],
        ["Completed Tests", str(ok.get("completed_tests", 0))],
        ["Pending Tests", str(ok.get("pending_tests", 0))],
        ["Completion Rate", f"{ok.get('completion_rate_pct', 0)}%"],
        ["Average Tests per Patient", str(ok.get("avg_tests_per_patient", 0))],
        ["Active Registration Operators", str(ok.get("unique_operators", 0))],
    ]
    story.append(_table(summary_rows, col_widths=[8 * cm, 8 * cm]))

    tk = tests.get("kpis") or {}
    ratio = tests.get("result_ratio") or {}
    story.append(Paragraph("2. Diagnostic Metrics & Result Ratios", s["section"]))
    diag_rows = [
        ["Parameter Classification", "Count"],
        ["Normal Parameters", str(ratio.get("normal", 0))],
        ["Abnormal Parameters", str(ratio.get("abnormal", 0))],
        ["Unclassified / Non-numeric", str(ratio.get("unclassified", 0))],
        ["Abnormal Rate (classifiable)", f"{tk.get('abnormal_rate_pct', 0)}%"],
    ]
    story.append(_table(diag_rows, col_widths=[8 * cm, 8 * cm]))

    story.append(Paragraph("3. Test Volume by Category", s["section"]))
    cat_rows = [["Category", "Test Count"]]
    for item in (tests.get("category_volume") or [])[:20]:
        cat_rows.append([item.get("category", "—"), str(item.get("count", 0))])
    if len(cat_rows) == 1:
        cat_rows.append(["No data in selected range", "0"])
    story.append(_table(cat_rows, col_widths=[10 * cm, 6 * cm]))

    story.append(Paragraph("4. Top Requested Tests (Top 10)", s["section"]))
    top_rows = [["Test Name", "Volume"]]
    for item in (tests.get("top_tests") or []):
        top_rows.append([item.get("test_name", "—"), str(item.get("count", 0))])
    if len(top_rows) == 1:
        top_rows.append(["No data in selected range", "0"])
    story.append(_table(top_rows, col_widths=[10 * cm, 6 * cm]))

    story.append(Paragraph("5. Staff Registration Telemetry", s["section"]))
    op_rows = [["Operator", "Registrations", "Primary Shift"]]
    for item in (telemetry.get("operator_throughput") or [])[:25]:
        op_rows.append(
            [
                item.get("operator", "—"),
                str(item.get("registrations", 0)),
                item.get("primary_shift", "—"),
            ]
        )
    if len(op_rows) == 1:
        op_rows.append(["No registrations in selected range", "0", "—"])
    story.append(_table(op_rows, col_widths=[6 * cm, 4 * cm, 6 * cm]))

    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1")))
    story.append(Spacer(1, 12))

    sig_data = [
        ["", ""],
        ["Pathologist Incharge", "Date & Signature"],
        [_cell(pathologist_name), "____________________________"],
        ["", datetime.now(timezone.utc).strftime("%Y-%m-%d")],
    ]
    story.append(_table(sig_data, col_widths=[8 * cm, 8 * cm]))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "This document is generated electronically by LabFlow Analytics Suite for internal "
            "operational review and pathologist attestation. Distribution is restricted to "
            "authorized laboratory personnel.",
            s["small"],
        )
    )

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
