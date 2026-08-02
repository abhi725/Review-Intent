-- 003_channels — phone as a first-class outreach channel, and a record of
-- automated runs.
--
-- Apollo's free plan returns a company phone number and never an email address,
-- so a queue that measures contactability by `contact_email IS NOT NULL` reports
-- zero contactable leads forever and `draft_pending` selects nothing. The phone
-- column is what makes the free plan produce actionable work.

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS contact_phone TEXT;

-- The queue's real working set: NEW, and reachable by some channel.
CREATE INDEX IF NOT EXISTS leads_contactable_idx
    ON leads (score DESC)
    WHERE status = 'NEW'
      AND (contact_email IS NOT NULL OR contact_phone IS NOT NULL);

-- ----------------------------------------------------------------- job_runs
-- Every automated run, successful or not. Without this a cron that quietly
-- stopped firing is indistinguishable from a week with no new leads — the same
-- failure `collector_health` exists to catch, one level up.
CREATE TABLE IF NOT EXISTS job_runs (
    id           BIGSERIAL   PRIMARY KEY,
    job          TEXT        NOT NULL,      -- 'scan' | 'digest' | 'reconcile'
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    ok           BOOLEAN,
    detail       JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS job_runs_job_idx ON job_runs (job, started_at DESC);

INSERT INTO schema_migrations (version) VALUES ('003_channels')
ON CONFLICT (version) DO NOTHING;
