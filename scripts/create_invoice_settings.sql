-- Invoice / thermal printer settings (fetched once on login, cached locally)
CREATE TABLE IF NOT EXISTS invoice_settings (
    id SERIAL PRIMARY KEY,
    hospital_name TEXT NOT NULL DEFAULT 'GMMMC Teaching Hospital Sukkur',
    developed_by TEXT NOT NULL DEFAULT 'Rehan Ahmed',
    developed_by_url TEXT,
    online_report_url TEXT DEFAULT 'www.gmc.syberclient.com/Account/PatientLogin',
    printer_width TEXT NOT NULL DEFAULT '3in',
    logo_path TEXT DEFAULT '/static/images/hospital_logo.png',
    qr_code_path TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Single active row (adjust values in Supabase dashboard as needed)
INSERT INTO invoice_settings (
    hospital_name,
    developed_by,
    developed_by_url,
    online_report_url,
    printer_width,
    logo_path,
    is_active
)
SELECT
    'GMMMC Teaching Hospital Sukkur',
    'Rehan Ahmed',
    'https://example.com',
    'www.gmc.syberclient.com/Account/PatientLogin',
    '3in',
    '/static/images/hospital_logo.png',
    TRUE
WHERE NOT EXISTS (SELECT 1 FROM invoice_settings LIMIT 1);
