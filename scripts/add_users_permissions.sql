-- Run in Supabase SQL Editor (Database → SQL)
-- Adds active flag and JSON permissions for LabFlow users.

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS permissions jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.users.is_active IS 'When false, user cannot log in.';
COMMENT ON COLUMN public.users.permissions IS 'Feature flags: register, update_results, fitness, print, fluid_reports, admin, manage_users, manage_tests';

-- Optional: grant full permissions to first admin user
-- UPDATE public.users SET permissions = '{"register":true,"update_results":true,"fitness":true,"print":true,"fluid_reports":true,"admin":true,"manage_users":true,"manage_tests":true}'::jsonb WHERE id = 1;
