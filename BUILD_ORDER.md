# Build order, sorted by file

Companion to `ARCHITECTURE.md`. Same 23 items, regrouped so each file is opened
once and finished, instead of being revisited in every phase.

Legend: **A** = Phase A (free, unblocked) · **B** = discovery unlock ·
**B2** = paid sources + controls · **C** = breadth

---

## Phase A — DONE, deployed as 0.5.0 on 2026-08-03

All twelve items shipped. 158 tests pass, migration 006 applied (6 total),
`/`, `/app`, `/login` all 200, new endpoints auth-gated and live.

Two bugs surfaced during the work that were not on the original list:
`vendor_news` never set `platform` (7 news rows ungroupable), and **`scan.py`
dropped every new field at the `record()` boundary** — which would have made
the A3 collector fix a silent no-op in production while passing its unit tests.
Both fixed; the boundary now forwards explicitly and says why in a comment.

| # | File | Change | Depends on |
|---|---|---|---|
| A1 | `migrations/006_signal_provenance.sql` | **new** — platform, source_site, country, region, switched_from, switched_reason, subscores, category, core_complaint, severity, fetched_at + index | — |
| A2 | `intentdesk/collectors/__init__.py` | extend `RawSignal` with the same fields | A1 |
| A3 | `intentdesk/collectors/apify.py` | fix 6 G2 mappings; drop `reviewerJobTitle`/`reviewLink`; capture productName, country, region, switched*, subscores | A2 |
| A4 | `intentdesk/services/signals.py` | `record()` takes + stores new fields; `list_signals()` filters by platform, source_site, rating, country, category, date range | A1 |
| A5 | `scripts/backfill_g2.py` | **new** — re-read Apify dataset `9b0eQswNwawOdAVua` (free) into signals | A3, A4 |
| A6 | `scripts/prune_stale.py` | **new** — delete the 9 pre-pivot Freshdesk/Zoho/Zendesk signals | A4 |
| A7 | `intentdesk/services/export.py` | refuse empty ranges with a reason instead of header-only file | — |
| A8 | `intentdesk/api/app.py` | `/api/signals` gains the filter params; `/api/sources` returns registry state | A4 |
| A9 | `web/src/api.js` | client calls for the new params | A8 |
| A10 | `web/src/App.jsx` | three-level selector (competitor → source → filters) + rebuilt signal rows | A9 |
| A11 | `web/src/styles.css` | brand pass — swan-orange/pink, charcoal, DM Sans | A10 |
| A12 | `tests/test_signals.py`, `tests/test_export.py` | field mapping, filters, empty-export refusal | A3–A7 |

## Phase B — discovery (fills `companies`)

| # | File | Change |
|---|---|---|
| B1 | `intentdesk/collectors/organisers.py` | **new** — `MeraEventsOrganiserCollector` (sitemap → 7,273 names), `TownscriptOrganiserCollector` (JSON-LD `performer`) |
| B2 | `intentdesk/collectors/__init__.py` | register both; add `cadence` + `cost_model` + `robots_ok` to `Collector` |
| B3 | `intentdesk/services/enrichment.py` | `resolve_domain(name, country)` — **GMB first** (domain + phone + address, ~$0.0027), Apollo `organizations/search` as fallback; confidence scoring; `needs_review` queue |
| B3b | `intentdesk/collectors/gmb.py` | **new** — `compass~crawler-google-places` wrapper. Enrichment only; **not** a review source (office reviews ≠ product reviews) |
| B4 | `intentdesk/services/companies.py` | upsert from organiser rows; checkpoint + resume for long runs |
| B5 | `intentdesk/services/matching.py` | join reviews to companies on platform |
| B6 | `migrations/007_company_source.sql` | `companies.discovered_via`, `companies.platform`, `match_confidence` |
| B7 | `tests/test_organisers.py` | robots compliance, sitemap parsing, fuzzy-match rejection |

## Phase B2 — DONE, deployed as 0.7.0 on 2026-08-03

All eleven items shipped, plus Phase C below. 232 tests pass, migration 008
applied (8 total), `/`, `/app`, `/login` 200, every new endpoint 401s
unauthenticated and `/cron/*` stays bearer-gated.

Four things surfaced during the work that were not on the list:

1. **Nothing called the classifier.** `drafting.analyse()` and
   `signals.classify()` both existed and neither had a caller, so
   `signals.category` was NULL on all 26 stored reviews. The drafter correction
   would have shipped *inert* — no platform pattern for any brand, so every draft
   would still have been the generic pitch, for a reason nobody would have thought
   to look for. Added `classify_pending()`, `POST /api/signals/classify` and
   `/cron/classify`, and ran it: 26/26 classified, led by `high_fees` (9) and
   `limited_customization` (8).
2. **The complaint ranking was wrong on first contact with real data.** Ordering
   by average severity let Eventbrite's single severity-3 support complaint
   outrank nine severity-2.8 complaints about fees, so drafts would have led with
   the rarest thing anyone said. Now ordered by *total* severity.
3. **`free_only` was testing the wrong thing.** It filtered on `requires`, which
   meant Reddit — free, but needing OAuth credentials — was skipped from free
   runs, and any future paid source without a token would have slipped through as
   free. Now filters on `cost_model`, and a paid collector marked `scheduled` is
   refused outright as a contradiction.
4. **openpyxl rejects tz-aware datetimes**, which the review export hit
   immediately. Converted to UTC before dropping the offset — stripping it without
   shifting would have moved every Indian timestamp back five and a half hours.

| # | File | Change |
|---|---|---|
| C1 | `intentdesk/collectors/trustpilot.py` | **new** — hand-verified slugs only, never name search |
| C2 | `intentdesk/services/drafting.py` | **the correction** — pass `category` + `core_complaint`; forbid quoting/attribution; require addressing the problem |
| C3 | `intentdesk/services/identity.py` | **new** — `resolve()` with high/medium/low tiers, Apollo `people/match` |
| C4 | `intentdesk/services/spend.py` | **new** — per-call logging, monthly cap, 80% warning |
| C5 | `migrations/008_identity_spend.sql` | `reviewer_identity`, `watchlist.segment`/`trustpilot_url`/`g2_slug`, `spend` attribution columns |
| C6 | `intentdesk/services/export.py` | period export — monthly/yearly grouping + summary sheet |
| C7 | `intentdesk/api/app.py` | `/api/collect`, `/api/collect/estimate`, `/api/signals/{id}/enrich-*`, `/api/export/reviews`, `/api/spend` |
| C8 | `web/src/App.jsx` + `Sources.jsx` | per-row buttons with cost labels, Sources panel, Export panel |
| C9 | `intentdesk/services/scan.py` | scheduled scan runs **free collectors only** |
| C10 | `intentdesk/collectors/reddit.py` | pin to organiser subreddits |
| C11 | `tests/test_drafting.py` | assert no verbatim n-gram of a review survives into a draft |

## Phase C — breadth. DONE, same deploy

| # | File | Change |
|---|---|---|
| D1 | `intentdesk/collectors/reviews_b2b.py` | **new** — TrustRadius + SoftwareSuggest as free JSON-LD parsers, robots-checked, allow-list gated. **Unverified end to end**: no slug has been hand-checked, so `available()` returns False and the Sources panel says why. `scripts/verify_review_slugs.py` is the free way to change that |
| D2 | `intentdesk/market.py` | `BRANDS` is now the single source of truth — 17 brands with `segment`, region, `active`, verified `g2_slug` and `trustpilot_url`. `COMPETITORS`, `G2_SLUGS`, `TRUSTPILOT_URLS` all derive from it. 8 expansion brands registered with `active: False` |
| D3 | `scripts/seed.py` | seeds segments and verified slugs; `COALESCE` on the URL columns so a re-seed cannot wipe a hand-entered page |

### What Phase C did not deliver, and why

No new review row. TrustRadius and SoftwareSuggest are written and free, but a
paid source taught the rule they follow: **a slug is hand-verified or it is not
used.** `ti.to` name-matched Tito-Express, a German printer-ink retailer, and
billed us for twelve reviews about undelivered toner. Guessing a slug on a free
source is worse than on a paid one — it costs nothing and writes another
product's complaints into `signals` under our competitor's name, where nothing
downstream can tell they are wrong. So `B2B_REVIEW_SLUGS` ships empty, with
candidates in `B2B_SLUG_CANDIDATES` and a script that fetches each one and prints
the product name it actually found.

Expect the script to report 403 for at least one of the two: this VM's datacenter
IP is already blocked by Trustpilot, Reddit and Google, and that answer means the
free route is closed rather than that the collector is broken.

---

## Still open after 0.7.0 — mostly closed by 0.9.1, below

| | |
|---|---|
| ~~**The audience gap**~~ | **Closed in 0.8.0.** See below |
| **Trustpilot has never actually run** | Ticket Tailor is cleared and priced at $0.05. Not spent — paid work runs on a click, and that click is the user's |
| **Apollo `people/match`** | Still 403 on the free plan. `identity.resolve()` reports that as a billing state rather than "no person found", and 25 named reviewers are waiting. Most are G2 rows that `assess()` refuses for free anyway |
| **Unledgered spend** | Now measurable: `/cron/reconcile` reports `recorded 1.5064` against Apify's own `3.162`, understated by **$1.6556**. All of it pre-dates `spend_calls` — that table is still empty, so nothing since has cost anything — but the monthly cap is guarding the smaller number |

---

# 0.8.0 → 0.9.1, deployed 2026-08-03

266 tests, migration 009. The audience gap is closed: a real lead
(`Replay Events`, id 24) drafted with `basis: "platform_pattern"`,
`category: high_fees`, `evidence_count: 8` — the drafter's centrepiece firing on
real data for the first time. Everything below was free; `spend_calls` is still
empty.

## What closed the gap

Not another review source. Both cheap ones are closed from this VM and were
measured, not assumed: **TrustRadius and SoftwareSuggest return 403 to their own
robots.txt** for all twelve candidate slugs, and **every Ticket Tailor path sits
behind a Cloudflare interstitial** — including `/sitemap.xml`, which its
robots.txt explicitly permits.

What worked was the other direction: stop hunting complaints about the platform
our companies run, and find companies on the platform whose complaints are
already classified. `EventbriteOrganisers` reads
`sitemap_xml/organizer_profile_pages00/01.xml.gz` — ~100,000 organisers, and the
name is in the slug, so a pass costs **two** HTTP requests rather than one per
profile.

## Four defects found by running it, not by reading it

| | |
|---|---|
| **`APOLLO_API_KEY` never reached production** | Set in `.env.prod`, absent from the compose `environment:` allow-list. Second time that list has bitten (`PUBLIC_BASE_URL`, Aug 2) and worse, because every consumer treats a missing key as an empty result: `/cron/enrich` returned `enriched 0` and the resolver reported no match — both indistinguishable from Apollo not knowing these companies. With the key passed through: **10/10 enriched.** `test_prod_env_passthrough.py` now diffs the three files |
| **Promotion hardcoded `country="IN"`** | True while MeraEvents was the only source, false once Eventbrite was added — "Replay Events" (Milton Keynes) and "The Green Light" (Roosendaal) were stored as Indian leads. The gate could not catch it: `apollo_search` collapsed a country to `"IN" if name == "India" else None`, so *known foreign* and *unknown* were the same value and the non-India downgrade could never fire on the only free resolver. `is_india()` is now three-state |
| **`companies.country` was `NOT NULL DEFAULT 'IN'`** | The assumption was in the schema, so the first honest unknown crashed `resolve_batch`. 009 drops both. A default of `'IN'` is invisible at the call site in a way a constraint violation is not |
| **Resolution spent in discovery order** | 2,031 MeraEvents rows queued ahead of 450 Eventbrite ones, and MeraEvents has no classified complaint — every one bought a company whose best draft is the generic pitch. Pending organisers now sort by whether we hold classified complaints about their platform. Prioritised, not filtered |

## Two things worth not rediscovering

**The India hint orders, it never filters** — and its first version was wrong in
a way only live data showed. Ethnicity and alumni tokens (`india`, `desi`, `iit`)
sorted **US diaspora groups** to the front: "IIT Bay Area Alumni Association",
"Indian Health Center of Santa Clara Valley", and a Caribbean carnival matched on
`indian` inside "West Indian". Eventbrite's base is overwhelmingly American, so
Indian-*named* US orgs outnumber Indian companies. In-country place names only.

**Cloudflare caps a cron request at ~100s, and fails it invisibly.**
`/cron/discover?limit=400` returned an empty body while the run **completed
server-side** — 450 organisers landed. n8n would have logged a failed node for
work that succeeded. The node ships with `limit=100` (measured: 50 → 28s).

## Still open

| | |
|---|---|
| **n8n workflow is imported but INACTIVE** | All 9 nodes are in the live sqlite with real tokens. Activation needs the UI toggle or an n8n restart, and a restart interrupts 13 active production workflows — so it is the user's call, not a side effect of this work |
| **Non-Indian leads are queued, not filtered** | Truthfully labelled now, but "The Green Light — Roosendaal" still sits in the queue at score 30. Whether a confirmed foreign company should score at all is a product decision |
| **~2,400 organisers unresolved** | Apollo-only resolution is free and lands ~15% (3/20, 2/25); GMB costs ~$0.0027 and lands more. Batched and resumable |
| **`generic_pitch: true`** | Unchanged and unchangeable from here — the value proposition is the one input no code supplies |

---

## Files touched most, so worth opening once

- `intentdesk/api/app.py` — A8, C7
- `web/src/App.jsx` — A10, C8
- `intentdesk/services/export.py` — A7, C6
- `intentdesk/collectors/__init__.py` — A2, B2
