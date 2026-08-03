-- 007 — a staging table for discovered organisers.
--
-- Discovery yields a company NAME (from a public organiser sitemap) and the
-- platform it demonstrably runs. It does not yield a domain. But
-- `companies.domain` is NOT NULL UNIQUE, so a discovered organiser cannot be
-- written there until something resolves a domain for it.
--
-- Rather than relax that constraint — which would let every unresolved name
-- into the lead queue and make `companies` a list of things we cannot contact —
-- discovery lands here, and only a confident resolution is promoted.
--
-- The two states this separation keeps distinct:
--   "we know this company exists and runs Eventbrite"   -> organisers
--   "we can actually reach it"                          -> companies

CREATE TABLE IF NOT EXISTS organisers (
    id            BIGSERIAL PRIMARY KEY,

    -- What the sitemap gave us.
    name          TEXT NOT NULL,
    platform      TEXT NOT NULL,          -- the competitor they run
    source        TEXT NOT NULL,          -- meraevents | townscript
    profile_url   TEXT,                   -- the page this came from, for audit
    city          TEXT,
    country       TEXT NOT NULL DEFAULT 'IN',

    -- What resolution found, if anything.
    resolved_domain     TEXT,
    resolved_phone      TEXT,
    resolved_address    TEXT,
    resolved_category   TEXT,
    resolve_source      TEXT,             -- gmb | apollo
    resolve_confidence  TEXT,             -- high | medium | low
    resolve_cost_usd    NUMERIC(10,5) NOT NULL DEFAULT 0,
    resolved_at         TIMESTAMPTZ,

    -- pending    — discovered, not yet resolved
    -- resolved   — domain found and promoted to companies
    -- needs_review — a domain was found but the match is not confident enough
    --                to act on. Held rather than guessed: a wrong domain means
    --                pitching a business about a platform it never used.
    -- rejected   — reviewed and dismissed, so a rescan does not resurface it
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','resolved','needs_review','rejected')),

    company_id    BIGINT REFERENCES companies(id) ON DELETE SET NULL,

    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Dedup key. The same organiser can legitimately appear on two platforms,
    -- and that is a fact worth keeping — it means they run both.
    UNIQUE (source, name, platform)
);

-- The resolver's work queue. Partial index because `pending` is the only state
-- it ever scans, and it shrinks to nothing as the backlog clears.
CREATE INDEX IF NOT EXISTS organisers_pending_idx
    ON organisers (discovered_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS organisers_platform_idx ON organisers (platform, status);
CREATE INDEX IF NOT EXISTS organisers_review_idx
    ON organisers (updated_at DESC)
    WHERE status = 'needs_review';

-- Where a company came from, so a lead can be traced back to the sitemap entry
-- that produced it and a bad source can be undone wholesale.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS discovered_via   TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS match_confidence TEXT;

-- Platform attribution comes from the sitemap the organiser was found in, never
-- from Apollo: `technology_names` came back empty for a real 5-person Indian
-- firm, so tech-stack detection cannot be relied on in this market.
COMMENT ON COLUMN companies.discovered_via IS
    'meraevents_sitemap | townscript_sitemap | csv_import | manual';
