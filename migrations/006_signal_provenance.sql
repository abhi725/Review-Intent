-- 006 — the fields the review collectors already receive and were discarding.
--
-- Verified against 50 live G2 records and 56 live Trustpilot records on
-- 2026-08-03. Every column below corresponds to something the actor returns
-- today; none of it needs a new source or a new API call. Two of the mappings
-- the collector *did* have were reading fields that do not exist at all
-- (`reviewerJobTitle`, `reviewLink`), which is why `author_role` has been NULL
-- on every row ever stored.

-- Which product the review is about. G2 gives `productName`, Trustpilot gives
-- `businessName`. Storing it means the feed can group by competitor without
-- inferring it from the watchlist row that happened to trigger the scan.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS platform      TEXT;

-- Which review site it came from. `source` already holds the collector name,
-- which is close but not the same thing: one collector may serve several sites,
-- and the UI groups by site, not by the code that fetched it.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS source_site   TEXT;

-- India-first product, and the G2 dataset turned out to be overwhelmingly US.
-- Without these the feed cannot answer "show me Indian organisers", which is
-- the first question anyone asks it.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS country       TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS region        TEXT;

-- The strongest buying signal in the whole payload, previously thrown away:
-- a reviewer stating outright that they changed platforms, and why.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS switched_from   TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS switched_reason TEXT;

-- G2's own dimension scores (easeOfUse, qualityOfSupport, easeOfSetup, …).
-- JSONB rather than columns: the set differs per source, and Trustpilot has
-- none. Scoring can use them where present without the schema pretending every
-- source supplies the same dimensions.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS subscores     JSONB;

-- Output of drafting.analyse(), persisted rather than recomputed. Re-running an
-- LLM over the same review to redraw a screen is both slow and billable.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS category       TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS core_complaint TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS severity       SMALLINT;

-- Cache key for the per-row "fetch more" button. A second click on an already
-- fetched row must read the cache and charge nothing; without a timestamp there
-- is no way to tell a cached row from a stale one.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS fetched_at    TIMESTAMPTZ;

-- The feed's primary access path: one competitor, one review site, newest
-- first. Without this it is a sequential scan over every signal ever stored.
CREATE INDEX IF NOT EXISTS signals_platform_source_idx
    ON signals (platform, source_site, observed_at DESC);

-- Filtering to negative reviews is the second most common query, and the one
-- that decides whether a row is a lead at all.
CREATE INDEX IF NOT EXISTS signals_rating_idx
    ON signals (rating, observed_at DESC)
    WHERE rating IS NOT NULL;
