-- "We don't know where this company is" has to be storable.
--
-- 001 declared `country TEXT NOT NULL DEFAULT 'IN'`, which put the assumption in
-- the schema: any insert that omitted a country silently asserted India. That
-- held while every discovery source was an Indian platform and broke when
-- Eventbrite was added — two European companies were promoted as Indian leads
-- because the column could not express the truth.
--
-- Dropping NOT NULL is what lets the resolver record what it actually observed.
-- The default goes too: a default of 'IN' means the next INSERT that forgets the
-- column re-creates exactly this bug, and a default is invisible at the call
-- site in a way a NULL constraint violation is not.
--
-- Existing rows keep their values. `scripts/repair_country.py` is the separate,
-- dated, reviewable pass over the rows written under the old assumption — a
-- backfill does not belong in a migration, where nobody can tell afterwards what
-- it changed or when.
--
-- Consequence worth knowing: `WHERE country = 'IN'` no longer matches unknowns,
-- which is correct — an unknown country is not India — but any filter that used
-- to rely on the default now excludes those rows rather than including them.

ALTER TABLE companies ALTER COLUMN country DROP NOT NULL;
ALTER TABLE companies ALTER COLUMN country DROP DEFAULT;
