-- Table: invoice_settings
DROP TABLE IF EXISTS "invoice_settings" CASCADE;
CREATE TABLE IF NOT EXISTS "invoice_settings" (
    "developed_by" TEXT,
    "developed_by_url" TEXT,
    "hospital_name" TEXT,
    "id" INTEGER,
    "is_active" BOOLEAN,
    "logo_path" TEXT,
    "online_report_url" TEXT,
    "printer_width" TEXT,
    "qr_code_path" TEXT,
    "updated_at" TIMESTAMPTZ,
    PRIMARY KEY ("id")
);

INSERT INTO "invoice_settings" ("developed_by", "developed_by_url", "hospital_name", "id", "is_active", "logo_path", "online_report_url", "printer_width", "qr_code_path", "updated_at")
VALUES
('REHAN AHMED', 'https://example.com', 'GMMMC Teaching Hospital Sukkur', 1, TRUE, '/static/images/hospital_logo.png', 'https://gmmmcsukkur.vercel.app/', '3in', NULL, '2026-05-30T07:47:53.878769+00:00')
ON CONFLICT DO NOTHING;
