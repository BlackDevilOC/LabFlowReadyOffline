-- Common lab remarks for quick entry (synced to fetcheddata/remarks.json on login)
CREATE TABLE IF NOT EXISTS remarks (
    id SERIAL PRIMARY KEY,
    remark_text TEXT NOT NULL,
    test_name TEXT,
    category TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS remarks_active_test_idx ON remarks (is_active, test_name);
CREATE INDEX IF NOT EXISTS remarks_active_category_idx ON remarks (is_active, category);

-- Example seeds (safe to re-run manually with ON CONFLICT if you add a unique constraint later)
INSERT INTO remarks (remark_text, test_name, category, sort_order)
SELECT 'Within normal limits.', NULL, NULL, 1
WHERE NOT EXISTS (SELECT 1 FROM remarks WHERE lower(trim(remark_text)) = lower('Within normal limits.'));

INSERT INTO remarks (remark_text, test_name, category, sort_order)
SELECT 'Sample hemolyzed; interpret with caution.', NULL, 'Hematology', 2
WHERE NOT EXISTS (SELECT 1 FROM remarks WHERE lower(trim(remark_text)) = lower('Sample hemolyzed; interpret with caution.'));
