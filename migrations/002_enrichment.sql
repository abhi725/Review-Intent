-- 002_enrichment — company-level enrichment fields.
--
-- Apollo's free plan blocks every person endpoint, so there is no contact name
-- or email to store. What it does return is firmographics, a company phone, and
-- a detected technology list — enough to verify which helpdesk a company runs
-- and to reach them at the company level.

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS industry        TEXT,
    ADD COLUMN IF NOT EXISTS phone           TEXT,
    ADD COLUMN IF NOT EXISTS linkedin_url    TEXT,
    ADD COLUMN IF NOT EXISTS employees_est   INTEGER,
    ADD COLUMN IF NOT EXISTS vendor_verified BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS enriched_at     TIMESTAMPTZ;

-- Re-enrichment picks the stalest rows first.
CREATE INDEX IF NOT EXISTS companies_enriched_idx
    ON companies (enriched_at NULLS FIRST);

INSERT INTO schema_migrations (version) VALUES ('002_enrichment')
ON CONFLICT (version) DO NOTHING;
