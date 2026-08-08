# Implementation Plan - Global Print Settings Admin Page

Analyzed existing print settings architecture and logic in Supabase and frontend renderer. This plan details adding a dedicated **Print Settings** management page inside the Admin Panel to manage print settings globally, without altering any core print logic or preview layout.

## 1. Analysis of Current Print Settings Architecture

- **Supabase & Offline Database Schema (`print_settings` table)**:
  - **Fonts & Typography**: `category_font_size` (18), `group_font_size` (15), `test_name_font_size` (14), `result_font_size` (14), `patient_info_font_size` (14), `patient_info_label_font_size` (14), `footer_font_size` (11).
  - **Margins & Header/Footer**: `page_top_margin` (25mm), `page_right_margin` (15mm), `page_bottom_margin` (25mm), `page_left_margin` (15mm), `header_height` (140px), `header_bottom_margin` (10px), `footer_margin_top` (40px), `footer_padding_top` (20px).
  - **Table & Section Spacing**: `table_header_padding_vertical` (8px), `table_header_padding_horizontal` (12px), `table_cell_padding_vertical` (4px), `table_cell_padding_horizontal` (12px), `category_padding_top` (10px), `category_padding_bottom` (4px), `category_border_width` (2px), `group_padding_top` (8px), `group_padding_bottom` (2px), `group_padding_left` (4px).
  - **Colors**: `primary_color` (`#111111`), `secondary_color`, `border_color`, `bg_light`, `text_main`, `text_muted`.
  - **Display Options**: `display_verified_by` (bool), `display_pathologist_signature` (bool).

- **Data Fetching & Cache Flow**:
  - [dbActions.py](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/dbActions.py) provides `load_lab_print_settings_row()`, `sync_lab_print_settings_cache()`, and `loadPrintSettings()`.
  - Settings are cached locally under [fetcheddata/print_settings.json](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/fetcheddata/print_settings.json) and served via `/api/setting/loadprintsetting`.
  - Reports ([templates/lab_test_print_preview.html](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/templates/lab_test_print_preview.html) and [static/js/lab-print.js](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/static/js/lab-print.js)) read `/api/setting/loadprintsetting` automatically.
  - **Existing Gap**: No UI page or write API exists in the Admin Panel to view, edit, and update `print_settings` globally in Supabase.

---

## User Review Required

> [!NOTE]
> Main print logic and print preview code remain 100% intact and unchanged. The new page in Admin Panel interacts with Supabase to persist settings globally and updates the cache (`print_settings.json`) so all workstations immediately inherit the updated global configuration.

---

## Proposed Changes

### Backend Logic

#### [MODIFY] [dbActions.py](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/dbActions.py)
- Add `update_lab_print_settings_admin(settings_data: dict, actor: str)` function:
  - Updates the active row (or inserts a new active row if none exists) in Supabase `print_settings`.
  - Automatically invokes `sync_lab_print_settings_cache()` to update local cache immediately.

#### [MODIFY] [main.py](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/main.py)
- Add `"print-settings"` to `admin_config_views` list in `admin_panel` route.
- Add `GET /api/admin/print-settings` endpoint to return active print settings data.
- Add `POST /api/admin/print-settings` endpoint to receive updated settings from the Admin UI, update Supabase via `dbActions.update_lab_print_settings_admin()`, and return status response.

---

### Admin Panel Interface

#### [MODIFY] [templates/admin_panel.html](file:///d:/rehan%20d%20DRIVE/LABFLOW2.0/LabFlowReady/templates/admin_panel.html)
- **Sidebar Navigation**: Add "Print Settings" item with icon pointing to `{{ url_prefix }}/page/admin?view=print-settings`.
- **View Container**: Add `{% if current_view == 'print-settings' %}` section:
  - **Font Settings Card**: Inputs for Category, Group, Test Name, Result, Patient Info, Label, and Footer font sizes.
  - **Page Margins & Header Card**: Inputs for Top/Bottom/Left/Right margins (mm), Header Height (px), Footer Padding (px).
  - **Table & Spacing Card**: Header & cell vertical/horizontal paddings, category border width, group padding.
  - **Display Options & Colors Card**: Toggles for Pathologist Signature & Verified By section, Primary & Border color pickers.
  - **Save & Action Bar**: "Save Global Settings" button with AJAX post handling, status notifications, and reset capabilities.
- **Client-Side JS**: Add `loadAdminPrintSettings()` and `saveAdminPrintSettings()` functions to fetch current settings and send updates.

---

## Verification Plan

### Automated / Syntax Verification
- Run Python syntax checks on `main.py` and `dbActions.py`.

### Manual Verification
- Navigate to `/page/admin?view=print-settings` in browser.
- Verify existing global print settings populate correctly into input fields.
- Modify values (e.g. adjust category font size or toggle pathologist signature) and click "Save Global Settings".
- Verify Supabase record is updated and `fetcheddata/print_settings.json` is updated.
- Verify print preview (`/page/lab/print-preview/...` or `/api/setting/loadprintsetting`) reflects the saved settings.
