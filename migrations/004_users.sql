-- 004_users — accounts, so there is something for a signup page to create.
--
-- Until now a session was minted straight from the Google callback and nothing
-- was persisted: there were no accounts, so "sign up" had nothing to mean. This
-- table is what makes an account a real object — one that can hold a password,
-- be linked to a Google identity, or both.
--
-- A row can carry `password_hash`, `google_sub`, or both. Both is the ordinary
-- case once someone who registered with a password later clicks the Google
-- button with the same address: the identities merge onto one account rather
-- than silently creating a second one with the same email.

CREATE TABLE IF NOT EXISTS users (
    id             BIGSERIAL   PRIMARY KEY,
    email          TEXT        NOT NULL UNIQUE,
    name           TEXT,
    -- NULL for Google-only accounts. Never a plaintext password, and never
    -- compared with ==; see services/users.py.
    password_hash  TEXT,
    -- Google's stable subject id. Not the email: an email can be reassigned
    -- inside a Workspace, the subject cannot.
    google_sub     TEXT        UNIQUE,
    is_admin       BOOLEAN     NOT NULL DEFAULT false,
    disabled       BOOLEAN     NOT NULL DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at  TIMESTAMPTZ
);

-- Case-insensitive lookup. Addresses are lowercased on write too, but a stray
-- capital from a direct INSERT must not create a second account.
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_idx ON users (lower(email));

-- The first account to exist becomes the admin, so a fresh deploy is not locked
-- out of its own settings. Handled in application code, not here, because it
-- depends on who signs in first.

INSERT INTO schema_migrations (version) VALUES ('004_users')
ON CONFLICT (version) DO NOTHING;
