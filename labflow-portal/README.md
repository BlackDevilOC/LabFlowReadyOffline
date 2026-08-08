# LabFlow Patient Portal (GitHub Pages + Supabase)

Static site for patients to view **completed** lab results using **MR number** (or patient token) and **PIN** from their receipt.

**Go-live checklist for [gmmmc-USER-PRINT](https://github.com/BlackDevilOC/gmmmc-USER-PRINT):** see [SETUP_GITHUB_PAGES.md](SETUP_GITHUB_PAGES.md).

**Backend status:** Supabase Edge Function `patient-portal` is deployed (`verify_jwt` off; MR + PIN auth).

## Architecture

- **This folder** — HTML/CSS/JS hosted on GitHub Pages (no secrets in the browser).
- **`supabase/functions/patient-portal`** — Edge Function verifies PIN and returns sanitized data using the service role (server-side only).

## 1. Deploy the Edge Function

From the **repository root** (where `supabase/` lives):

```bash
# Install Supabase CLI: https://supabase.com/docs/guides/cli
supabase login
supabase link --project-ref zndiehpmrxpfskwygkhv
supabase functions deploy patient-portal
```

`verify_jwt = false` is set in `supabase/config.toml` so patients do not need a Supabase account. Security is MR/token + PIN inside the function.

### Optional: restrict CORS origins

In the [Supabase Dashboard](https://supabase.com/dashboard) → Project → Edge Functions → `patient-portal` → Secrets, add:

```text
PATIENT_PORTAL_ALLOWED_ORIGINS=https://youruser.github.io,https://labflow-yourlab.duckdns.org
```

By default, `*.github.io`, `localhost`, and `*.duckdns.org` are allowed.

## 2. Configure the static site

Edit [`config.js`](config.js):

```javascript
window.LABFLOW_PORTAL_CONFIG = {
  supabaseUrl: "https://YOUR_PROJECT_REF.supabase.co",
  functionName: "patient-portal",
  hospitalName: "Your Hospital Name",
};
```

Only the public project URL is needed — **never** put `service_role` here.

## 3. Enable GitHub Pages

1. Push this repo to GitHub.
2. **Settings → Pages → Build and deployment**: Source = **GitHub Actions**.
3. Push changes under `labflow-portal/` (or run workflow **Deploy patient portal to GitHub Pages** manually).
4. Your site will be at `https://<username>.github.io/<repo-name>/` if the repo is not `username.github.io`, or at the root for a `username.github.io` repo.

For a **project site** (repo name `LabFlowReady`), the URL is:

`https://<username>.github.io/LabFlowReady/`

Test login with a real MR number and PIN from a registration receipt.

## 4. Optional: free custom subdomain (DuckDNS)

1. Create a hostname at [duckdns.org](https://www.duckdns.org) (e.g. `labflow-yourlab.duckdns.org`).
2. Add a **CNAME** record: `labflow-yourlab` → `<username>.github.io`.
3. In GitHub **Settings → Pages → Custom domain**, enter `labflow-yourlab.duckdns.org`.
4. Add that exact origin to `PATIENT_PORTAL_ALLOWED_ORIGINS` in Supabase if you disable the default DuckDNS wildcard.

## Local testing

Serve this folder with any static server, e.g.:

```bash
cd labflow-portal
python -m http.server 8080
```

Open `http://127.0.0.1:8080` — CORS allows localhost automatically.

## Security notes

- Only tests with `status = 'Completed'` are returned.
- Failed logins are rate-limited per IP + identifier.
- Rotate your Supabase **service role** key if it was ever committed to git; keep it in `.env` locally and in Supabase secrets for Edge Functions only.
