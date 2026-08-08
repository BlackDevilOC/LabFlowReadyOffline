-- Add plain-text patient portal PIN (4–8 digits) on registration receipt
ALTER TABLE patients
ADD COLUMN IF NOT EXISTS pwd TEXT;

COMMENT ON COLUMN patients.pwd IS 'Plain-text PIN for patient online report login (4–8 digits)';
