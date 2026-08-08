# Enable GitHub Pages for `gmmmc-USER-PRINT`

Your live URL will be: **https://blackdeviloc.github.io/gmmmc-USER-PRINT/**

## Quick method (recommended)

1. Open https://github.com/BlackDevilOC/gmmmc-USER-PRINT/settings/pages
2. **Build and deployment** → Source: **Deploy from a branch**
3. Branch: **main** → **/ (root)** → **Save**
4. Wait 1–3 minutes and refresh the site URL.

## Method with GitHub Actions (auto-deploy on push)

Upload these two items to the **root** of your repo (merge with existing files):

| File | Purpose |
|------|---------|
| [`.nojekyll`](.nojekyll) | Tells GitHub Pages not to strip `_` files |
| [`standalone-repo/.github/workflows/pages.yml`](standalone-repo/.github/workflows/pages.yml) | Deploys the repo root on every push |

Then:

1. **Settings → Pages → Build and deployment** → Source: **GitHub Actions**
2. Push any commit to `main` (or run the workflow manually under **Actions**)

Copy the workflow file to `.github/workflows/pages.yml` at the repo root (not inside `standalone-repo/`).

## After Pages is live

1. Edge Function `patient-portal` is already deployed on Supabase.
2. Open the site and log in with **MR number + PIN from a patient receipt**.
3. Example patient with completed results and PIN: MR **100044** (PIN is on that patient’s receipt).

Update LabFlow invoice **online report URL** to:

`https://blackdeviloc.github.io/gmmmc-USER-PRINT/`
