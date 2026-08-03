-- 005 — proving an address is yours, filling out an account, and keeping the
-- parts of a review the collectors were throwing away.
--
-- Three unrelated-looking changes in one file because they ship together and a
-- half-applied subset is worse than either state.

-- ----------------------------------------------------------------- accounts
-- NULL means unproven. Google accounts are stamped at creation — Google already
-- verified the address and a second confirmation email is noise. Password
-- accounts stay NULL until someone clicks the link.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

-- Everything a person can put on their own account. `avatar` holds the bytes
-- directly rather than a path: there is no upload volume in the compose file,
-- and a redeploy that forgets to mount one loses every photo silently. At a few
-- staff accounts of 256x256 PNG this costs nothing and cannot be misplaced.
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar            BYTEA;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_mime       TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_updated_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone             TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS job_title         TEXT;

-- Every account that exists before this migration was created by someone who
-- already had access, and there is no way for them to verify retroactively —
-- the link would go to an inbox nobody is watching for it. Grandfather them in
-- rather than locking out the only accounts that currently work.
UPDATE users SET email_verified_at = COALESCE(last_login_at, created_at)
WHERE email_verified_at IS NULL;

-- ------------------------------------------------------------- auth tokens
-- One table for verification and reset. The lifecycle is identical — mint,
-- expire, use once — and two tables would be the same code written twice.
CREATE TABLE IF NOT EXISTS auth_tokens (
    id         BIGSERIAL   PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose    TEXT        NOT NULL CHECK (purpose IN ('verify','reset')),
    -- sha256 of the token, never the token. A database dump must not hand
    -- someone a working set of password-reset links.
    token_hash TEXT        NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ,
    -- The admin who issued it, or NULL when the user asked for it themselves.
    issued_by  TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Serves both "find this user's live tokens" (to expire them when a new one is
-- issued) and the per-hour resend cap, which counts rows by created_at.
CREATE INDEX IF NOT EXISTS auth_tokens_user_idx
    ON auth_tokens (user_id, purpose, created_at DESC);

-- ----------------------------------------------------------------- signals
-- The collectors already see all four of these and drop them. `rating` is the
-- clearest case: collectors/apify.py reads it, filters on it, and never stores
-- it — so the feed can show that a review is negative but not how negative.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS url         TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS author      TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS author_role TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS rating      REAL;

-- Left nullable on purpose. Every signal collected before today has none of
-- this, and backfilling would mean re-scraping sources we already paid for.
-- The feed renders a row with all four NULL exactly as it does today.

-- The counts strip groups by kind over a recent window; without this it is a
-- sequential scan every time the signals screen is opened.
CREATE INDEX IF NOT EXISTS signals_kind_observed_idx
    ON signals (kind, observed_at DESC);

INSERT INTO schema_migrations (version) VALUES ('005_verification_profiles_signals')
ON CONFLICT (version) DO NOTHING;
