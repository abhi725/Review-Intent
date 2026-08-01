-- 001_init — core schema for the intent desk.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- companies
-- The install base. One row per company detected running a tracked competitor.
CREATE TABLE companies (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT        NOT NULL,
    domain          TEXT        NOT NULL UNIQUE,
    city            TEXT,
    country         TEXT        NOT NULL DEFAULT 'IN',
    employee_band   TEXT,
    vendor          TEXT        NOT NULL,
    agents_est      INTEGER,
    first_detected  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX companies_vendor_country_idx ON companies (vendor, country);
CREATE INDEX companies_last_seen_idx      ON companies (last_seen DESC);

-- ------------------------------------------------------------------ signals
-- Every intent observation. company_id stays NULL when we cannot match it to a
-- tracked company — those still count, they tell us the collector is alive.
CREATE TABLE signals (
    id                  BIGSERIAL PRIMARY KEY,
    company_id          BIGINT      REFERENCES companies(id) ON DELETE CASCADE,
    kind                TEXT        NOT NULL
        CHECK (kind IN ('install','job_post','review','forum','vendor_news')),
    source              TEXT        NOT NULL,   -- 'g2' | 'reddit' | 'naukri' | ...
    source_id           TEXT        NOT NULL,   -- provider's own id, for dedup
    observed_at         TIMESTAMPTZ NOT NULL,
    raw_text            TEXT,
    quote               TEXT,                   -- short pull-quote for the timeline
    weight              INTEGER     NOT NULL DEFAULT 0,
    matched_confidence  REAL        NOT NULL DEFAULT 0
        CHECK (matched_confidence >= 0 AND matched_confidence <= 1),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);

CREATE INDEX signals_company_idx  ON signals (company_id, observed_at DESC);
CREATE INDEX signals_observed_idx ON signals (observed_at DESC);
CREATE INDEX signals_unmatched_idx ON signals (observed_at DESC) WHERE company_id IS NULL;

-- -------------------------------------------------------------------- leads
-- A scored, enriched, drafted company. heat is generated from score so the two
-- can never drift apart.
CREATE TABLE leads (
    id                 BIGSERIAL PRIMARY KEY,
    company_id         BIGINT      NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    score              INTEGER     NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
    heat               TEXT        GENERATED ALWAYS AS (
                           CASE WHEN score >= 80 THEN 'hot'
                                WHEN score >= 55 THEN 'warm'
                                ELSE 'cool' END
                       ) STORED,
    contact_name       TEXT,
    contact_title      TEXT,
    contact_email      TEXT,
    contact_linkedin   TEXT,
    enrich_source      TEXT,
    draft_subject      TEXT,
    draft_body         TEXT,
    status             TEXT        NOT NULL DEFAULT 'NEW'
        CHECK (status IN ('NEW','APPROVED','REJECTED','SENT')),
    status_changed_at  TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A company may only have one live lead at a time; rejected/sent ones are history.
CREATE UNIQUE INDEX leads_one_live_per_company
    ON leads (company_id) WHERE status IN ('NEW','APPROVED');

CREATE INDEX leads_queue_idx  ON leads (status, score DESC);
CREATE INDEX leads_heat_idx   ON leads (heat, score DESC);

-- -------------------------------------------------------------- suppression
CREATE TABLE suppression (
    domain    TEXT PRIMARY KEY,
    reason    TEXT        NOT NULL,
    added_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- watchlist
CREATE TABLE watchlist (
    id          BIGSERIAL PRIMARY KEY,
    competitor  TEXT    NOT NULL UNIQUE,
    sources     JSONB   NOT NULL DEFAULT '[]'::jsonb,
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------------- spend
CREATE TABLE spend (
    id          BIGSERIAL PRIMARY KEY,
    day         DATE        NOT NULL,
    provider    TEXT        NOT NULL,
    amount_usd  NUMERIC(10,4) NOT NULL DEFAULT 0,
    UNIQUE (day, provider)
);

-- ---------------------------------------------------------------- settings
-- Single-row-per-key store backing the Settings screen.
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       JSONB       NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES ('001_init');
