# Modernize Lab Report Print UI Design

Revamp the print report user interface to incorporate the modern design aesthetic from `amh.html`, while binding dynamic LabFlow patient data (MR No, Patient Name, Age/Sex, Ref By, Branch, Ward/Unit/Shift, Collection Time) and enforcing proper A4/Letter page size and margins.

## Proposed Changes

### [Component: Report Templates & Styling]

#### [MODIFY] [patient_report.html](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/templates/patient_report.html)
- Replace old patient header box layout with the modern 2-box rounded container grid (`.patient-header-grid` & `.info-box` with `border: 1.5px solid #222` and `border-radius: 18px`).
- Map dynamic LabFlow patient data:
  - **Left Box**: Lab No (`mr_no`), Name (`salutation` + `patient_name`), Age / Sex (`age` / `gender`), Ref By (`ref_by` or relation info).
  - **Right Box**: Branch (`branch`), Ward/Unit (`ward_unit` or `shift`), Collection Time (formatted collection date/time), Reported Time.
- Update table headers (`TEST NAME`, `RESULT`, `UNIT`, `NORMAL RANGE`) with top/bottom 1.5px solid black borders.
- Style test results with bold 14.5px font and clean unit/range formatting.
- Update print CSS and `@page` rules to enforce page size (`size: A4 portrait`) and page margins.

#### [MODIFY] [patient_report.css](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/static/css/patient_report.css)
- Implement updated CSS rules for `.patient-header-grid`, `.info-box`, `.info-row`, `.info-label`, `.info-value`.
- Add section title styling (uppercase, `letter-spacing: 0.8px`, font-size `14px`, `#111`).
- Configure table borders (1.5px solid `#000` top/bottom headers).
- Add responsive print rules for page sizes (A4 / Letter) and page margins.

#### [MODIFY] [lab_test_print_preview.html](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/templates/lab_test_print_preview.html)
- Synchronize patient header layout and table header borders with the new modern 2-box design.
- Ensure page size rules (`A4` / `Letter`) pass cleanly through `@page` definitions in preview and print.

#### [MODIFY] [lab-print.js](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/static/js/lab-print.js)
- Ensure printable document generator (`buildLabPrintDocument`) generates the updated 2-box header layout and table styling.
- Retain dynamic page size calculations and configurable margin handling.

---

## Verification Plan

### Manual Verification
1. Launch the local dev server (`python main.py`).
2. Open `/patient-report/{id}` or print preview in browser.
3. Inspect patient info card: verify 2-box rounded design with 18px border radius, bold patient name, lab number, ward/unit, collection time, etc.
4. Trigger print (Ctrl+P / Print button): verify page layout, A4 page size, borders, and margins in print preview dialog.
