# LabFlow Offline Sync & Admin Enhancement Plan

## Summary
This plan covers 4 interconnected features:
1. **Admin button → Online Portal Admin Panel** (redirect to Supabase-hosted web app admin with same password)
2. **Offline Tests Management page** (already exists in sidebar as `offline-tests` view — needs backend APIs in offline `app.py`)
3. **Pending Offline Patients page** (`offline-sync` view) — redesign to support filtering, multi-select, and selective push to Supabase, plus `mr_sync_log` table tracking
4. **App startup sync** — fetch tests/groups/shifts/settings from Supabase and save into SQLite on every offline app start

---

## Open Questions

> [!IMPORTANT]
> **Online portal URL**: What is the URL of the main LabFlow online app (the Supabase-hosted version)? The admin button should redirect to `<ONLINE_URL>/page/admin`. If the app is accessed locally at `http://localhost:8000`, the online version is likely a separate hosted URL. Please confirm or provide the URL.

> [!NOTE]
> Based on the code, I can see `SUPABASE_URL = https://zndiehpmrxpfskwygkhv.supabase.co` but the web app portal URL (if deployed) isn't visible in the code. I'll use a configurable constant and the admin can set it. If you have a deployed URL (e.g. Vercel, Railway, etc.), share it.

---

## Proposed Changes

### 1. Admin Button → Online App Admin Panel

#### [MODIFY] [login.html](file:///d:/rehan/LABFLOW2.0/LabFlowReady/templates/login.html)
- Change the admin gear button from `href="/page/admin"` to open a **password modal** first
- On password `youcannotenter` → redirect to the online app admin panel URL (e.g. `http://localhost:8000/page/admin` for local, or configurable online URL)
- For the offline app, clicking admin will redirect to the **offline admin panel** (`/offline/page/admin`)

#### [MODIFY] [admin_panel.html](file:///d:/rehan/LABFLOW2.0/LabFlowReady/templates/admin_panel.html)
- No change needed for the main admin — password check already exists (`youcannotenter`)

---

### 2. Offline Tests Management (Backend APIs)

The admin panel already has the HTML for `offline-tests` and `offline-tests-edit` views. The offline `app.py` is missing the CRUD API endpoints.

#### [MODIFY] [offline/app.py](file:///d:/rehan/LABFLOW2.0/LabFlowReady/offline/app.py)
Add the following API routes (matching what the JS in `admin_panel.html` already calls):
- `GET /api/admin/offline-tests-catalog` — list all tests + groups + categories
- `POST /api/admin/offline-tests` — create test
- `PUT /api/admin/offline-tests/{id}` — update test  
- `GET /api/admin/offline-tests/{id}` — get test
- `POST /api/admin/offline-test-groups` — create group
- `PUT /api/admin/offline-test-groups/{id}` — update group
- `GET /api/admin/offline-patients` — list all patients with sync status (already partially exists)
- `POST /api/admin/offline-patients/sync-selected` — NEW: sync only selected patients to Supabase
- `GET /api/admin/offline-sync-log` — return `mr_sync_log` records

---

### 3. Pending Offline Patients — Filter, Select, Push Page

#### [MODIFY] [offline/database.py](file:///d:/rehan/LABFLOW2.0/LabFlowReady/offline/database.py)
Add `mr_sync_log` table migration:
```sql
CREATE TABLE IF NOT EXISTS mr_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offline_mr TEXT NOT NULL,
    online_mr TEXT,
    patient_name TEXT,
    synced_at TEXT DEFAULT (datetime('now', 'localtime')),
    synced_by TEXT,
    status TEXT DEFAULT 'synced',
    error_message TEXT
)
```

#### [MODIFY] [templates/admin_panel.html](file:///d:/rehan/LABFLOW2.0/LabFlowReady/templates/admin_panel.html)
Replace the current `offline-sync` view HTML with:
- **Filter bar** — shift, date range, sync status (pending/synced/error)
- **Selectable table** — checkbox per row, "Select All" header checkbox
- **Stats cards** — unsynced count, synced count
- **"Push Selected to Supabase" button** — calls new `/offline/api/admin/offline-patients/sync-selected`
- **Sync log section** — table showing `mr_sync_log` history

#### [MODIFY] [offline/app.py](file:///d:/rehan/LABFLOW2.0/LabFlowReady/offline/app.py)
New endpoint: `POST /api/admin/offline-patients/sync-selected`
- Accepts `{"patient_ids": [1, 2, 3]}`
- For each patient: push patient to Supabase `patients` table, push their `test_results_all` records
- Get back the online MR number, update local SQLite `patients.synced=1, online_mr=<new_mr>`
- Write a row to `mr_sync_log` for each patient
- Return summary of successes/failures

---

### 4. App Startup Sync — Supabase → SQLite

#### [MODIFY] [offline/app.py](file:///d:/rehan/LABFLOW2.0/LabFlowReady/offline/app.py)
Enhance `on_startup()` / add new `sync_from_supabase_on_startup()` function:
- Try to connect to Supabase (with timeout)
- If connected:
  - Fetch `tests` table → upsert into SQLite `tests`
  - Fetch `test_groups` table → upsert into SQLite `test_groups`
  - Fetch `shift` table → upsert into SQLite `shift`
  - Fetch `invoice_settings` → update SQLite `invoice_settings`
  - Fetch `print_settings` → update SQLite `print_settings`
  - Fetch `remarks` → upsert into SQLite `remarks`
  - Fetch `users` (active only) → upsert into SQLite `users`
- Log result (success/no-internet) to file
- Non-blocking: runs in background thread so app starts instantly

#### [MODIFY] [offline/database.py](file:///d:/rehan/LABFLOW2.0/LabFlowReady/offline/database.py)
Add upsert helper functions for batch insert/replace operations.

---

## Verification Plan

### Automated Tests
- Run offline app: `cd offline && uvicorn app:app --reload --port 8001`
- Test CRUD: `curl http://localhost:8001/api/admin/offline-tests-catalog`
- Test sync endpoint: `curl -X POST http://localhost:8001/api/admin/offline-patients/sync-selected -H "Content-Type: application/json" -d '{"patient_ids": [1]}'`

### Manual Verification
- Click admin button on login page → password prompt → redirect to online admin panel
- Visit `offline-tests` admin view → create a test, verify it appears in list
- Visit `offline-sync` view → filter patients, select some, click Push → verify Supabase gets the data and `mr_sync_log` is populated
- Restart offline app → check logs for "Startup sync from Supabase: X tests loaded"
