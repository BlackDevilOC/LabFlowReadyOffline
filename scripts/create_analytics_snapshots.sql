-- Analytics snapshot cache + supporting indexes for LabFlow reporting suite.
-- Run in Supabase SQL editor or via migration tooling.

CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('overview', 'telemetry', 'tests')),
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT analytics_snapshots_range_key UNIQUE (snapshot_type, date_from, date_to)
);

CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_computed
    ON analytics_snapshots (computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_patients_created_at
    ON patients (created_at);

CREATE INDEX IF NOT EXISTS idx_patients_user_id
    ON patients (user_id);

CREATE INDEX IF NOT EXISTS idx_test_results_all_created_at_active
    ON test_results_all (created_at)
    WHERE delete_status IS NOT TRUE;

CREATE INDEX IF NOT EXISTS idx_test_results_all_category_active
    ON test_results_all (category)
    WHERE delete_status IS NOT TRUE;

CREATE INDEX IF NOT EXISTS idx_test_results_all_status_active
    ON test_results_all (status)
    WHERE delete_status IS NOT TRUE;
