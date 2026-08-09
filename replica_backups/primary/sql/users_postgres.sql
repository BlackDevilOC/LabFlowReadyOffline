-- Table: users
DROP TABLE IF EXISTS "users" CASCADE;
CREATE TABLE IF NOT EXISTS "users" (
    "created_at" TIMESTAMPTZ,
    "default_shift_id" INTEGER,
    "email" TEXT,
    "id" INTEGER,
    "is_active" BOOLEAN,
    "name" TEXT,
    "permissions" JSONB,
    "pwd" TEXT,
    PRIMARY KEY ("id")
);

INSERT INTO "users" ("created_at", "default_shift_id", "email", "id", "is_active", "name", "permissions", "pwd")
VALUES
('2026-02-12T18:57:02.524412+00:00', 2, 'admin@admin.com', 1, TRUE, 'Rehan Ahmed', '{"admin": true, "print": true, "fitness": true, "register": true, "analytics": true, "manage_tests": true, "manage_users": true, "fluid_reports": true, "update_results": true}', 'admin'),
('2026-02-13T17:29:17.164569+00:00', NULL, 'aman@aman.com', 2, TRUE, 'Aman', '{}', 'aman'),
('2026-02-19T09:59:35.713826+00:00', NULL, 'iba@iba.com', 3, TRUE, 'iba', '{}', 'iba'),
('2026-05-30T07:36:24.950282+00:00', 2, 'evening@lab.com', 4, TRUE, 'daniyal', '{"admin": false, "print": true, "fitness": false, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": false, "update_results": true}', 'Keeper@1'),
('2026-06-30T10:46:57.073835+00:00', 2, 'nazeer@gmail.com', 5, TRUE, 'Nazeer', '{"admin": true, "print": true, "fitness": true, "register": true, "analytics": true, "manage_tests": true, "manage_users": true, "fluid_reports": true, "update_results": true}', 'Nazeer'),
('2026-08-07T06:58:42.794748+00:00', 1, 'rehan@guest.com', 6, TRUE, 'rehan-guest', '{"admin": false, "print": true, "fitness": true, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": true, "update_results": true}', '031579')
ON CONFLICT DO NOTHING;
