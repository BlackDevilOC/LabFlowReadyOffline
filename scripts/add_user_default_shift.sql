-- Link users to shift table (run after shift table exists)
ALTER TABLE users
ADD COLUMN IF NOT EXISTS default_shift_id BIGINT REFERENCES shift(id) ON DELETE SET NULL;

COMMENT ON COLUMN users.default_shift_id IS 'Default shift for patient registration (shift.id)';
