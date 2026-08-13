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
('2026-05-30T07:36:24.950282+00:00', 2, 'evening@lab.com', 4, FALSE, 'daniyal', '{"admin": false, "print": true, "fitness": false, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": false, "update_results": true}', 'Keeper@1'),
('2026-06-30T10:46:57.073835+00:00', 2, 'nazeer@gmail.com', 5, TRUE, 'Nazeer', '{"admin": true, "print": true, "fitness": true, "register": true, "analytics": true, "manage_tests": true, "manage_users": true, "fluid_reports": true, "update_results": true}', 'Nazeer'),
('2026-08-07T06:58:42.794748+00:00', 1, 'rehan@guest.com', 6, TRUE, 'rehan-guest', '{"admin": false, "print": true, "fitness": true, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": true, "update_results": true}', '031579'),
('2026-08-10T07:14:54.800894+00:00', 1, 'uzair@lab.com', 7, TRUE, 'Uzair', '{"admin": false, "print": true, "fitness": true, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": true, "update_results": true}', '2002'),
('2026-08-10T07:25:48.236333+00:00', 5, 'sakhar@lab.com', 8, TRUE, 'Sakhar', '{"admin": false, "print": true, "fitness": true, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": true, "update_results": true}', 'Syedshah'),
('2026-08-10T14:09:39.650211+00:00', 2, 'bilal@lab.com', 9, TRUE, 'BILAL', '{"admin": false, "print": true, "fitness": true, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": true, "update_results": true}', 'privateaccount'),
('2026-08-10T16:01:18.168519+00:00', 3, 'waqar@lab.com', 10, TRUE, 'Waqar', '{"admin": false, "print": true, "fitness": true, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": true, "update_results": true}', 'waqar'),
('2026-08-10T17:00:11.774297+00:00', 5, 'daniyal@lab.com', 11, TRUE, 'Daniyal', '{"admin": false, "print": true, "fitness": true, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": true, "update_results": true}', 'moosa0012'),
('2026-08-11T09:20:12.176337+00:00', 1, 'aman@lab.com', 12, TRUE, 'Aman', '{"admin": false, "print": true, "fitness": true, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": true, "update_results": true}', 'aman100888'),
('2026-08-12T11:14:27.821478+00:00', NULL, 'hamid@gmail.com', 13, TRUE, 'Hamid', '{"admin": false, "print": true, "fitness": true, "register": true, "analytics": false, "manage_tests": false, "manage_users": false, "fluid_reports": true, "update_results": true}', '1234')
ON CONFLICT DO NOTHING;
