-- Table for storing cross-PC application settings (print layouts, test selection layouts, etc.)
CREATE TABLE IF NOT EXISTS app_settings (
    id           BIGSERIAL PRIMARY KEY,
    setting_type TEXT NOT NULL UNIQUE,
    payload      JSONB NOT NULL,
    updated_by   TEXT,
    updated_at   TIMESTAMPTZ DEFAULT now()
);

-- Enable Row Level Security
ALTER TABLE app_settings ENABLE ROW LEVEL SECURITY;

-- Service role policies (full access)
CREATE POLICY "Allow service role full access" ON app_settings
    FOR ALL
    USING (true)
    WITH CHECK (true);
