-- 008 — reviewer identity, per-call spend attribution, watchlist segments.
--
-- Three unrelated-looking additions that share one purpose: making a paid click
-- accountable. Who did we resolve, what did it cost, and which brand page was
-- it even allowed to read.

-- ------------------------------------------------------------ reviewer identity
--
-- A review carries a display name and a country and nothing else. Turning that
-- into a person is a paid Apollo `people/match` call, and — unlike company
-- prospecting — it is personal data about someone who wrote a review, not a
-- business we found in a sitemap. DPDP and GDPR apply.
--
-- So the tier is stored as a column and enforced in code rather than left as a
-- number a screen might round away:
--   high   — rare name + a company named in the review + country agrees
--   medium — rare name + country only, held for a human
--   low    — common name, no company. Never enriched, never contacted. The row
--            still exists, because "we looked and it was not resolvable" is
--            worth knowing and stops the same signal being paid for twice.
CREATE TABLE IF NOT EXISTS reviewer_identity (
    id            BIGSERIAL PRIMARY KEY,
    signal_id     BIGINT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,

    -- What the review site published, kept verbatim so a later re-run can be
    -- compared against what it saw rather than against what we inferred.
    display_name  TEXT,
    country       TEXT,

    -- What resolution found. All nullable: a `low` row has none of them.
    full_name     TEXT,
    title         TEXT,
    company_name  TEXT,
    company_domain TEXT,
    email         TEXT,
    phone         TEXT,
    linkedin_url  TEXT,

    confidence    TEXT NOT NULL CHECK (confidence IN ('high','medium','low')),

    -- How we got there. `name_rarity` and `text_employer` are free reasoning
    -- over data already stored; `apollo_people_match` is the billable one.
    method        TEXT NOT NULL,
    reason        TEXT,

    cost_usd      NUMERIC(10,5) NOT NULL DEFAULT 0,
    resolved_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One identity per signal. This is the cache that makes a second click free,
    -- and the reason a `low` verdict has to be stored rather than discarded.
    UNIQUE (signal_id)
);

CREATE INDEX IF NOT EXISTS reviewer_identity_conf_idx
    ON reviewer_identity (confidence, resolved_at DESC);

-- --------------------------------------------------------- watchlist segments
--
-- The audience rule, as a column. A consumer marketplace's review page is full
-- of ticket buyers; an organiser-facing SaaS page is full of our buyers. Same
-- scraper, same cost, opposite value — so the segment decides whether a paid
-- review run is worth starting at all.
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS segment TEXT;

-- Hand-verified brand pages, never a name search. `ti.to` name-matched
-- Tito-Express, a German printer-ink retailer, and returned twelve reviews about
-- undelivered toner. A NULL here means "not verified yet", and the collector
-- refuses to run rather than guessing a slug.
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS trustpilot_url TEXT;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS g2_slug        TEXT;

COMMENT ON COLUMN watchlist.segment IS
    'organiser_saas | consumer_marketplace — decides whether review scraping '
    'reaches our buyer or a ticket buyer';
COMMENT ON COLUMN watchlist.trustpilot_url IS
    'Hand-verified Trustpilot business page. NULL means unverified: the '
    'collector skips rather than name-searching.';

-- ------------------------------------------------------- spend attribution
--
-- `spend` stays the day × provider rollup, because that is what the monthly cap
-- reads and two existing callers already do ON CONFLICT (day, provider). Adding
-- attribution columns there would have broken that aggregation — a per-call row
-- and a daily total cannot share one unique key.
--
-- So attribution lands in its own ledger, and the rollup gains only a call
-- count. The two are written together in `services/spend.record()`.
ALTER TABLE spend ADD COLUMN IF NOT EXISTS calls   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE spend ADD COLUMN IF NOT EXISTS last_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS spend_calls (
    id           BIGSERIAL PRIMARY KEY,

    provider     TEXT NOT NULL,          -- apify_g2 | trustpilot | gmb | apollo_people
    action       TEXT NOT NULL,          -- collect_reviews | enrich_reviewer | resolve_organiser
    units        INTEGER NOT NULL DEFAULT 1,
    amount_usd   NUMERIC(10,5) NOT NULL DEFAULT 0,

    -- Was this what we thought it would cost? A button that quotes $0.05 and
    -- bills $0.40 is the failure this column exists to make visible.
    estimated_usd NUMERIC(10,5),

    -- What it was spent on. Both nullable — a whole-source run belongs to
    -- neither a signal nor an organiser.
    signal_id    BIGINT REFERENCES signals(id) ON DELETE SET NULL,
    organiser_id BIGINT REFERENCES organisers(id) ON DELETE SET NULL,
    competitor   TEXT,

    -- Who clicked. Free work has no one to attribute it to; paid work always
    -- does, which is the whole point of moving paid work onto a button.
    actor_email  TEXT,

    detail       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS spend_calls_month_idx ON spend_calls (created_at DESC);
CREATE INDEX IF NOT EXISTS spend_calls_provider_idx ON spend_calls (provider, created_at DESC);
CREATE INDEX IF NOT EXISTS spend_calls_signal_idx ON spend_calls (signal_id)
    WHERE signal_id IS NOT NULL;
