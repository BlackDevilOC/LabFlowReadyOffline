#!/usr/bin/env python3
"""
Generate Monthly Pathology Statement (PDF & CSV) from Live Database (Supabase / SQLite).
Filters data from August 10, 2026 onwards (MR No >= 100).
"""

import os
import sys
import csv
from datetime import datetime
from collections import defaultdict

from dbActions import init_supabase

from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

MAIN_HEADERS = [
    'Date', 'CBC', 'BT CT', 'MP ICT', 'H. Pylori', 'PT INR', 'APTT', 'URINE DR', 'URINE PT',
    'BSR', 'UREA', 'CRETININE', 'LFT', 'ELECTROLYTES', 'HBs ICT', 'HCV ICT', 'HIV ICT',
    'B. Group', 'VDRL', 'RA', 'ASO TITER', 'DENGE NS1', 'DENGE IGM', 'URIC ACID', 'HBA 1c',
    'S. CHOLESTROL', 'T.G', 'HDL', 'LDL', 'S. CALCIUM', 'S. AMYLYSIS', 'S. ALBUMIN',
    'Body Fluid', 'ABG S', 'CBC TUBES', 'GEL TUBES', 'PT TUBES', 'HAPRIN TUBES'
]

POS_HEADERS = [
    'Date', 'HBs ICT +VE', 'HCV ICT +VE', 'HIV ICT +VE', 'VDRL +VE',
    'DENGUE NS1', 'DENGUE IgG/IGM', 'MP ICT +VE', 'PV', 'PF', 'MIX'
]


def fetch_live_data(start_date="2026-08-10", min_mr_no=100):
    """Fetches test results from Supabase for August 2026 starting from min_mr_no."""
    sp = init_supabase()
    if not sp:
        raise RuntimeError("Failed to connect to database.")

    start_iso = f"{start_date}T00:00:00Z"

    all_rows = []
    offset = 0
    chunk = 1000
    while True:
        res = sp.table('test_results_all').select(
            'id,mr_no,patient_name,test_name,category,created_at,test_values,delete_status'
        ).gte('created_at', start_iso).range(offset, offset + chunk - 1).execute()

        all_rows.extend(res.data)
        if len(res.data) < chunk:
            break
        offset += chunk

    # Filter out deleted and enforce MR No condition
    valid_rows = []
    for r in all_rows:
        if r.get('delete_status'):
            continue
        try:
            mr = int(r.get('mr_no', 0))
        except (ValueError, TypeError):
            mr = 0
        if mr >= min_mr_no or mr == 0: # include valid tests
            valid_rows.append(r)

    # Group records by date (DD-MM-YYYY)
    daily_tests = defaultdict(lambda: defaultdict(int))
    daily_pos = defaultdict(lambda: defaultdict(int))

    for r in valid_rows:
        created = r.get('created_at', '')
        if not created:
            continue
        dt_str = created.split('T')[0] # YYYY-MM-DD
        parts = dt_str.split('-')
        if len(parts) == 3:
            formatted_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            formatted_date = dt_str

        tname = str(r.get('test_name') or '').strip()
        tv = r.get('test_values') or {}

        # 1. Map Main Tests
        if tname == 'COMPLETE BLOOD COUNT':
            daily_tests[formatted_date]['CBC'] += 1
            daily_tests[formatted_date]['CBC TUBES'] += 1
        elif 'Hep B, C' in tname or 'HbsAg' in tname or 'Anti HCV' in tname:
            if 'Hep B, C' in tname:
                daily_tests[formatted_date]['HBs ICT'] += 1
                daily_tests[formatted_date]['HCV ICT'] += 1
                daily_tests[formatted_date]['GEL TUBES'] += 1
            elif 'HbsAg' in tname:
                daily_tests[formatted_date]['HBs ICT'] += 1
                daily_tests[formatted_date]['GEL TUBES'] += 1
            elif 'Anti HCV' in tname:
                daily_tests[formatted_date]['HCV ICT'] += 1
                daily_tests[formatted_date]['GEL TUBES'] += 1

            # Check positive values
            for pkey, pval in tv.items():
                if isinstance(pval, dict):
                    p_name = str(pval.get('name', '')).lower()
                    val = str(pval.get('value', '')).lower()
                    if 'hbsag' in p_name and ('pos' in val or 'react' in val):
                        daily_pos[formatted_date]['HBs ICT +VE'] += 1
                    if 'hcv' in p_name and ('pos' in val or 'react' in val):
                        daily_pos[formatted_date]['HCV ICT +VE'] += 1

        elif 'Anti HIV' in tname:
            daily_tests[formatted_date]['HIV ICT'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1
            for pkey, pval in tv.items():
                if isinstance(pval, dict) and ('pos' in str(pval.get('value', '')).lower() or 'react' in str(pval.get('value', '')).lower()):
                    daily_pos[formatted_date]['HIV ICT +VE'] += 1

        elif 'Liver Function' in tname or tname in ('Bilirubin Total', 'Bilirubin Direct', 'ALT (SGPT)'):
            daily_tests[formatted_date]['LFT'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1

        elif tname in ('UCE', 'Creatinine', 'Urea'):
            if tname == 'UCE':
                daily_tests[formatted_date]['UREA'] += 1
                daily_tests[formatted_date]['CRETININE'] += 1
                daily_tests[formatted_date]['ELECTROLYTES'] += 1
                daily_tests[formatted_date]['GEL TUBES'] += 1
            elif tname == 'Creatinine':
                daily_tests[formatted_date]['CRETININE'] += 1
                daily_tests[formatted_date]['GEL TUBES'] += 1
            elif tname == 'Urea':
                daily_tests[formatted_date]['UREA'] += 1
                daily_tests[formatted_date]['GEL TUBES'] += 1

        elif 'Glucose' in tname or 'RBS' in tname or 'BSR' in tname:
            daily_tests[formatted_date]['BSR'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1

        elif 'PT' in tname and 'Prothrombin' in tname:
            daily_tests[formatted_date]['PT INR'] += 1
            daily_tests[formatted_date]['PT TUBES'] += 1

        elif tname == 'APTT':
            daily_tests[formatted_date]['APTT'] += 1
            daily_tests[formatted_date]['PT TUBES'] += 1

        elif 'Electrolytes' in tname:
            daily_tests[formatted_date]['ELECTROLYTES'] += 1
            daily_tests[formatted_date]['HAPRIN TUBES'] += 1

        elif 'MP-ICT' in tname or 'Malaria' in tname:
            daily_tests[formatted_date]['MP ICT'] += 1
            for pkey, pval in tv.items():
                if isinstance(pval, dict):
                    val = str(pval.get('value', '')).lower()
                    if 'pos' in val or 'p.f' in val or 'p.v' in val:
                        daily_pos[formatted_date]['MP ICT +VE'] += 1
                        if 'p.v' in val or 'pv' in val:
                            daily_pos[formatted_date]['PV'] += 1
                        elif 'p.f' in val or 'pf' in val:
                            daily_pos[formatted_date]['PF'] += 1
                        elif 'mix' in val:
                            daily_pos[formatted_date]['MIX'] += 1

        elif 'HbA1c' in tname:
            daily_tests[formatted_date]['HBA 1c'] += 1
            daily_tests[formatted_date]['CBC TUBES'] += 1

        elif 'Uric Acid' in tname:
            daily_tests[formatted_date]['URIC ACID'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1

        elif 'Albumin' in tname:
            daily_tests[formatted_date]['S. ALBUMIN'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1

        elif 'Dengue' in tname:
            daily_tests[formatted_date]['DENGE NS1'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1

        elif 'Amylase' in tname:
            daily_tests[formatted_date]['S. AMYLYSIS'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1

        elif 'Calcium' in tname:
            daily_tests[formatted_date]['S. CALCIUM'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1

        elif 'Lipid' in tname or 'Cholesterol' in tname:
            daily_tests[formatted_date]['S. CHOLESTROL'] += 1
            daily_tests[formatted_date]['T.G'] += 1
            daily_tests[formatted_date]['HDL'] += 1
            daily_tests[formatted_date]['LDL'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1

        elif 'VDRL' in tname:
            daily_tests[formatted_date]['VDRL'] += 1
            daily_tests[formatted_date]['GEL TUBES'] += 1
            for pkey, pval in tv.items():
                if isinstance(pval, dict) and ('pos' in str(pval.get('value', '')).lower() or 'react' in str(pval.get('value', '')).lower()):
                    daily_pos[formatted_date]['VDRL +VE'] += 1

        elif 'H. Pylori' in tname:
            daily_tests[formatted_date]['H. Pylori'] += 1

        elif 'RA' in tname:
            daily_tests[formatted_date]['RA'] += 1

        elif 'Blood Group' in tname:
            daily_tests[formatted_date]['B. Group'] += 1

    # Sort all dates chronologically
    sorted_dates = sorted(daily_tests.keys(), key=lambda d: datetime.strptime(d, "%d-%m-%Y"))

    # Build matrix rows
    main_rows = []
    pos_rows = []

    totals_main = [0] * len(MAIN_HEADERS)
    totals_main[0] = 'TOTAL'

    totals_pos = [0] * len(POS_HEADERS)
    totals_pos[0] = 'TOTAL'

    for d in sorted_dates:
        # Main row
        m_row = [d]
        for col_idx, col_name in enumerate(MAIN_HEADERS[1:], 1):
            val = daily_tests[d][col_name]
            m_row.append(val)
            totals_main[col_idx] += val
        main_rows.append(m_row)

        # Pos row
        p_row = [d]
        for col_idx, col_name in enumerate(POS_HEADERS[1:], 1):
            val = daily_pos[d][col_name]
            p_row.append(val)
            totals_pos[col_idx] += val
        pos_rows.append(p_row)

    summary_stats = {
        "HCV+VE": totals_pos[POS_HEADERS.index('HCV ICT +VE')],
        "HBSAG+VE": totals_pos[POS_HEADERS.index('HBs ICT +VE')],
        "HIV+VE": totals_pos[POS_HEADERS.index('HIV ICT +VE')],
        "VDRL+VE": totals_pos[POS_HEADERS.index('VDRL +VE')],
        "DENGUE_NS1": totals_pos[POS_HEADERS.index('DENGUE NS1')],
        "DENGUE_IGM": totals_pos[POS_HEADERS.index('DENGUE IgG/IGM')],
        "MALARIA_PV": totals_pos[POS_HEADERS.index('PV')],
        "MALARIA_PF": totals_pos[POS_HEADERS.index('PF')],
        "MALARIA_MIX": totals_pos[POS_HEADERS.index('MIX')],
        "MALARIA_TOTAL": totals_pos[POS_HEADERS.index('MP ICT +VE')],
        "TOTAL_TESTS_PERFORMED": sum(totals_main[1:34]), # sum of diagnostic test counts
        "START_DATE": sorted_dates[0] if sorted_dates else "10-08-2026",
        "END_DATE": sorted_dates[-1] if sorted_dates else "20-08-2026"
    }

    return {
        "dates": sorted_dates,
        "main_headers": MAIN_HEADERS,
        "main_rows": main_rows,
        "main_totals": totals_main,
        "pos_headers": POS_HEADERS,
        "pos_rows": pos_rows,
        "pos_totals": totals_pos,
        "summary_stats": summary_stats
    }


def export_august_csvs(data, out_dir):
    """Exports August live data to CSV files."""
    os.makedirs(out_dir, exist_ok=True)
    generated_csvs = []

    start_d = data['summary_stats']['START_DATE']
    end_d = data['summary_stats']['END_DATE']

    # 1. Main Daily Test Performed CSV
    csv_main_path = os.path.join(out_dir, "monthly_test_performed_statement_august_2026.csv")
    with open(csv_main_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["--- GHULAM MUHAMMAD MAHAR MEDICAL COLLEGE SUKKUR ---"])
        writer.writerow([f"--- MONTHLY TEST PERFORMED STATEMENT ({start_d} TO {end_d}) ---"])
        writer.writerow([])
        writer.writerow(data['main_headers'])
        for row in data['main_rows']:
            writer.writerow(row)
        writer.writerow(data['main_totals'])
    generated_csvs.append(csv_main_path)

    # 2. Positive Cases Statement CSV
    csv_pos_path = os.path.join(out_dir, "monthly_positive_cases_statement_august_2026.csv")
    with open(csv_pos_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["--- GHULAM MUHAMMAD MAHAR MEDICAL COLLEGE SUKKUR ---"])
        writer.writerow([f"--- MONTHLY POSITIVE CASES STATEMENT ({start_d} TO {end_d}) ---"])
        writer.writerow([])
        writer.writerow(data['pos_headers'])
        for row in data['pos_rows']:
            writer.writerow(row)
        writer.writerow(data['pos_totals'])
    generated_csvs.append(csv_pos_path)

    # 3. Summary Statistics CSV
    csv_sum_path = os.path.join(out_dir, "monthly_summary_statistics_august_2026.csv")
    with open(csv_sum_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Metric / Category", "Value"])
        for k, v in data['summary_stats'].items():
            writer.writerow([k, v])
    generated_csvs.append(csv_sum_path)

    return generated_csvs


def generate_august_pdf(data, output_pdf_path):
    """Generates landscape PDF report for August live data."""
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=landscape(A3),
        leftMargin=0.4 * inch,
        rightMargin=0.4 * inch,
        topMargin=0.4 * inch,
        bottomMargin=0.4 * inch
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1,
        spaceAfter=4
    )

    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=colors.HexColor('#2563EB'),
        alignment=1,
        spaceAfter=12
    )

    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1E293B'),
        spaceBefore=10,
        spaceAfter=6
    )

    cell_header_style = ParagraphStyle(
        'CellHeader',
        fontName='Helvetica-Bold',
        fontSize=6.5,
        leading=7.5,
        alignment=1,
        textColor=colors.white
    )

    cell_data_style = ParagraphStyle(
        'CellData',
        fontName='Helvetica',
        fontSize=6.5,
        leading=7.5,
        alignment=1,
        textColor=colors.HexColor('#1E293B')
    )

    cell_total_style = ParagraphStyle(
        'CellTotal',
        fontName='Helvetica-Bold',
        fontSize=6.5,
        leading=7.5,
        alignment=1,
        textColor=colors.HexColor('#0F172A')
    )

    elements = []

    start_d = data['summary_stats']['START_DATE']
    end_d = data['summary_stats']['END_DATE']

    # Title Block
    elements.append(Paragraph("MONTHLY TEST PERFORMED STATEMENT SHOWING PATHOLOGY DEPARTMENT", title_style))
    elements.append(Paragraph(f"GHULAM MUHAMMAD MAHAR MEDICAL COLLEGE HOSPITAL SUKKUR — AUGUST 2026 ({start_d} TO {end_d} | FROM MR NO 100)", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563EB'), spaceAfter=10))

    # --- TABLE 1: MAIN DAILY TEST PERFORMED STATEMENT ---
    elements.append(Paragraph("1. Daily Test Performed Matrix (Morning, Evening & Night Shift)", section_style))

    headers_p = [Paragraph(str(h), cell_header_style) for h in data['main_headers']]
    table_data = [headers_p]

    for row in data['main_rows']:
        table_data.append([Paragraph(str(val), cell_data_style) for val in row])

    table_data.append([Paragraph(str(val), cell_total_style) for val in data['main_totals']])

    col_widths = [0.7 * inch] + [0.395 * inch] * 37
    t1 = Table(table_data, colWidths=col_widths, repeatRows=1)
    t1_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
    ]

    for r in range(1, len(data['main_rows']) + 1):
        bg = colors.HexColor('#F8FAFC') if r % 2 == 0 else colors.white
        t1_style.append(('BACKGROUND', (0, r), (-1, r), bg))

    tot_idx = len(table_data) - 1
    t1_style.append(('BACKGROUND', (0, tot_idx), (-1, tot_idx), colors.HexColor('#FEF08A')))
    t1_style.append(('LINEABOVE', (0, tot_idx), (-1, tot_idx), 1, colors.HexColor('#1E3A8A')))
    t1_style.append(('LINEBELOW', (0, tot_idx), (-1, tot_idx), 1, colors.HexColor('#1E3A8A')))

    t1.setStyle(TableStyle(t1_style))
    elements.append(t1)

    elements.append(Spacer(1, 15))

    # --- TABLE 2: MONTHLY POSITIVE CASES STATEMENT & SUMMARY STATS ---
    elements.append(Paragraph("2. Monthly Positive Cases & Pathological Summary", section_style))

    pos_headers_p = [Paragraph(str(h), cell_header_style) for h in data['pos_headers']]
    pos_table_data = [pos_headers_p]
    for row in data['pos_rows']:
        pos_table_data.append([Paragraph(str(val), cell_data_style) for val in row])
    pos_table_data.append([Paragraph(str(val), cell_total_style) for val in data['pos_totals']])

    pos_col_widths = [0.75 * inch] + [0.55 * inch] * 10
    t_pos = Table(pos_table_data, colWidths=pos_col_widths, repeatRows=1)
    t_pos_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#B91C1C')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]
    for r in range(1, len(data['pos_rows']) + 1):
        bg = colors.HexColor('#FEF2F2') if r % 2 == 0 else colors.white
        t_pos_style.append(('BACKGROUND', (0, r), (-1, r), bg))

    tot_pos_idx = len(pos_table_data) - 1
    t_pos_style.append(('BACKGROUND', (0, tot_pos_idx), (-1, tot_pos_idx), colors.HexColor('#FECACA')))
    t_pos.setStyle(TableStyle(t_pos_style))

    s_stats = data['summary_stats']
    sum_data = [
        [Paragraph("<b>Category / Disease Summary</b>", cell_header_style), Paragraph("<b>Count</b>", cell_header_style)],
        [Paragraph("HCV +VE Total", cell_data_style), Paragraph(f"<b>{s_stats['HCV+VE']}</b>", cell_data_style)],
        [Paragraph("HBSAG +VE Total", cell_data_style), Paragraph(f"<b>{s_stats['HBSAG+VE']}</b>", cell_data_style)],
        [Paragraph("HIV +VE Total", cell_data_style), Paragraph(f"<b>{s_stats['HIV+VE']}</b>", cell_data_style)],
        [Paragraph("VDRL +VE Total", cell_data_style), Paragraph(f"<b>{s_stats['VDRL+VE']}</b>", cell_data_style)],
        [Paragraph(f"Malaria ICT +VE (PV: {s_stats['MALARIA_PV']}, PF: {s_stats['MALARIA_PF']}, MIX: {s_stats['MALARIA_MIX']})", cell_data_style), Paragraph(f"<b>{s_stats['MALARIA_TOTAL']}</b>", cell_data_style)],
        [Paragraph("Dengue NS1 / IGM +VE Total", cell_data_style), Paragraph(f"<b>{s_stats['DENGUE_NS1'] + s_stats['DENGUE_IGM']}</b>", cell_data_style)],
        [Paragraph("<b>TOTAL DIAGNOSTIC TESTS PERFORMED</b>", cell_total_style), Paragraph(f"<b>{s_stats['TOTAL_TESTS_PERFORMED']}</b>", cell_total_style)],
    ]
    t_sum = Table(sum_data, colWidths=[2.5 * inch, 1.3 * inch])
    t_sum.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0D9488')),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#CCFBF1')),
    ]))

    side_by_side = Table([[t_pos, Paragraph("", cell_data_style), t_sum]], colWidths=[6.3 * inch, 0.4 * inch, 3.8 * inch])
    side_by_side.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(side_by_side)

    elements.append(Spacer(1, 20))

    # --- SIGNATURE BLOCK ---
    sig_style = ParagraphStyle('SigStyle', fontName='Helvetica-Bold', fontSize=9, alignment=1, textColor=colors.HexColor('#1E293B'))
    sig_data = [
        [
            Paragraph("ABDUL SAMI SOOMRO<br/><b>INCHARGE LAB TECH</b><br/>GMMMC Hospital Sukkur", sig_style),
            Paragraph("DR. IRSA KHUWAJA<br/><b>INCHARGE PATHOLOGY DEPARTMENT</b><br/>GMMMC Hospital Sukkur", sig_style)
        ]
    ]
    t_sig = Table(sig_data, colWidths=[5 * inch, 5 * inch])
    t_sig.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEABOVE', (0, 0), (0, 0), 1, colors.HexColor('#64748B')),
        ('LINEABOVE', (1, 0), (1, 0), 1, colors.HexColor('#64748B')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(KeepTogether(t_sig))

    doc.build(elements)
    return output_pdf_path


def main():
    out_dir = r"d:\rehan d DRIVE\production\LabFlowReady-main (1)\LabFlowReady-main\TEMP_DATA"

    print("[*] Querying live database for August 2026 (From 10 Aug onwards, MR No >= 100)...")
    live_data = fetch_live_data(start_date="2026-08-10", min_mr_no=100)

    print(f"[+] Total days processed: {len(live_data['dates'])} ({live_data['summary_stats']['START_DATE']} to {live_data['summary_stats']['END_DATE']})")

    # Export CSVs
    csv_files = export_august_csvs(live_data, out_dir)
    for c in csv_files:
        print(f"  -> Generated CSV: {c}")

    # Export PDF
    pdf_path = os.path.join(out_dir, "monthly_test_performed_statement_august_2026.pdf")
    generate_august_pdf(live_data, pdf_path)
    print(f"  -> Generated PDF: {pdf_path}")

    print("\n[+] August Statement Export Completed Successfully!")


if __name__ == "__main__":
    main()