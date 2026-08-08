# Deploy patient-portal Edge Function (requires Supabase CLI)
# Install: https://supabase.com/docs/guides/cli/getting-started
# Usage: .\scripts\deploy_patient_portal_function.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Get-Command supabase -ErrorAction SilentlyContinue)) {
    Write-Error "Supabase CLI not found. Install from https://supabase.com/docs/guides/cli then run: supabase login"
}

Write-Host "Deploying patient-portal Edge Function..."
supabase functions deploy patient-portal --project-ref zndiehpmrxpfskwygkhv
Write-Host "Done. Set PATIENT_PORTAL_ALLOWED_ORIGINS in Dashboard if needed."
