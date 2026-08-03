# Intent Desk — Architecture

Version 2, 2026-08-03. Supersedes `PLAN.md` (written for a helpdesk market).
Companion to `PLAN_SIGNAL_FEED.md`, which holds the evidence behind every claim
here. Every capability statement below was tested against a live API on Aug 3;
none is assumed.

---

## 1. What the product is

A competitive-intent lead-generation tool. It watches public complaints about
competing **event ticketing platforms**, identifies the **event organiser**
behind the complaint or a company known to run that platform, and drafts
outreach that speaks to that organiser's actual problem.

- **ICP:** event organisers (`market.BUYER_ROLE`), not ticket buyers.
- **Market:** event ticketing, India-first with a US/UK tail.
- **Everything market-specific lives in `intentdesk/market.py`.** A pivot is one
  file. This has already paid for itself once.

### The single rule that shapes the whole design

> **Free work runs on a schedule. Paid work runs on a click.**

Discovery from public sitemaps and RSS is free and continuous. Every call that
costs money — Apify actors, Apollo people credits — is triggered by a person, on
a specific row, with the price shown on the button before it is pressed. This
inverts the original design, in which `scan.run()` fanned out across paid
collectors on a cron.

---

## 2. Current state, measured

### Works
| Component | Evidence |
|---|---|
| FastAPI + asyncpg + Postgres 16, live behind Traefik | `intent.swandigitals.com`, 0.4.0 healthy |
| Auth: Google OAuth + password, verification, reset, profiles | 147 tests pass |
| `vendor_news` collector (Google News RSS) | free, found a real Eventbrite lawsuit story |
| G2 review collector | 50 real records re-read today |
| Complaint extraction (`drafting.analyse`) | live LLM, correct category + core complaint |
| Apollo `organizations/search` (**name → domain**) | tested: `9 Blocks Photography` → `9blocks.in` |
| Apollo `organizations/enrich` (domain → phone, tech) | tested |
| Trustpilot via `memo23~trustpilot-scraper-ppe` | 56 reviews pulled, $0.05/run |

### Broken or missing
| Component | Status |
|---|---|
| `companies` / `leads` tables | **0 rows** — the root cause of the blank export |
| Drafter | **built to discard the complaint** — produces exactly the generic pitch |
| G2 field mapping | 6 fields wrong or unread (`reviewerJobTitle`, `reviewLink` don't exist) |
| 9 signals in DB | stale Freshdesk/Zoho reviews from before the pivot |
| `apify_jobs` | disproved — Indeed doesn't search descriptions by vendor name |
| `apify_capterra` | 403, returns nothing |
| Reddit | actor runs, but generic search hits ticket-resale subreddits |
| Apollo `mixed_companies/search`, all `people/*` | 403 on free — unlocked by the approved paid plan |

---

## 3. Layered architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  PRESENTATION   React /app · server-rendered /, /login, /signup  │
│                 Signal feed · Sources panel · Settings · Export  │
├──────────────────────────────────────────────────────────────────┤
│  ADAPTERS       FastAPI routes  ·  MCP server (27 tools)         │
│                 /cron/* (bearer)  ·  thin, no business logic     │
├──────────────────────────────────────────────────────────────────┤
│  SERVICES       scan · signals · companies · leads · matching    │
│                 enrichment · identity · drafting · scoring       │
│                 export · monitoring · spend · preferences        │
├──────────────────────────────────────────────────────────────────┤
│  COLLECTORS     free/scheduled  │  paid/on-demand                │
│                 vendor_news     │  trustpilot · g2 · reddit      │
│                 organisers      │  trustradius · softwaresuggest │
├──────────────────────────────────────────────────────────────────┤
│  PROVIDERS      Apify · Apollo · OpenAI/Gemini · Resend/Mautic   │
├──────────────────────────────────────────────────────────────────┤
│  DATA           Postgres 16 — asyncpg, no ORM (RAM-tight VM)     │
└──────────────────────────────────────────────────────────────────┘
```

**Invariant:** all logic lives in `intentdesk/services/`. The API and MCP server
are adapters. This is existing law in the codebase and does not change.

---

## 4. The two pipelines

### 4.1 Discovery — free, scheduled, fills `companies`

This is what fixes the empty database.

```
MeraEvents  /sitemaps/organizers/1     →  7,273 organiser names   free
Townscript  upcoming-event-pages.xml   →  7,547 events (+40k past) free
      │        organiser via JSON-LD `performer`
      ▼
  company name + the platform they demonstrably run
      │
      ▼  Apollo organizations/search        (free)
  domain · country · headcount · phone
      │
      ▼  Apollo organizations/enrich        (free)
  tech stack · industry · city
      │
      ▼
  companies  ──────────────────────────────────────►  leads
```

Every organiser in that sitemap is a company **known to run a named
competitor** — the install-base fact BuiltWith charges ~$295/month to infer,
obtained free from a file published for crawlers.

**robots.txt is law.** MeraEvents and Townscript permit this (zero disallows).
Explara disallows `/e/` and is excluded. BookMyShow and AllEvents 403 their
robots.txt and are excluded. This is enforced in code, not left to discipline.

### 4.2 Evidence — paid, on-demand, enriches what discovery found

```
  signal feed row  ── user clicks ──►  Trustpilot / G2 / Reddit actor
                                             │
                                             ▼
                                   review + rating + author + platform
                                             │
                                             ▼  drafting.analyse()  (LLM)
                                   category · core_complaint · severity
                                             │
                                             ▼  identity.resolve()  (Apollo, paid)
                                   person + confidence tier
                                             │
                                             ▼  drafting.draft_for_lead()
                                   outreach addressing that complaint
```

Reviews are **evidence attached to a company**, never the source of companies.
G2 yields ~1 negative review per 25 at ~$0.15 each; it cannot be a volume source.

---

## 5. Data model

Existing tables keep their shape. Additions:

```sql
-- 006: what the collectors already return but we discard
ALTER TABLE signals
  ADD COLUMN platform         text,        -- G2 productName / Trustpilot businessName
  ADD COLUMN source_site      text,        -- g2 | trustpilot | reddit | google_news
  ADD COLUMN country          text,
  ADD COLUMN region           text,
  ADD COLUMN switched_from    text,        -- churn signal, currently thrown away
  ADD COLUMN switched_reason  text,
  ADD COLUMN subscores        jsonb,       -- easeOfUse, qualityOfSupport, …
  ADD COLUMN category         text,        -- from analyse()
  ADD COLUMN core_complaint   text,
  ADD COLUMN severity         smallint,
  ADD COLUMN fetched_at       timestamptz; -- cache key for re-fetch

CREATE INDEX signals_platform_source_idx ON signals (platform, source_site, observed_at DESC);

-- reviewer identity, deliberately separate from `signals`
CREATE TABLE reviewer_identity (
  signal_id     bigint PRIMARY KEY REFERENCES signals(id) ON DELETE CASCADE,
  display_name  text,
  country       text,
  confidence    text NOT NULL CHECK (confidence IN ('high','medium','low')),
  apollo_id     text,
  linkedin_url  text,
  work_email    text,
  work_phone    text,
  company_id    bigint REFERENCES companies(id),
  resolved_at   timestamptz NOT NULL DEFAULT now(),
  resolved_by   text
);

-- watchlist gains segmentation so travel never blurs with event ticketing
ALTER TABLE watchlist
  ADD COLUMN segment        text NOT NULL DEFAULT 'event_ticketing',
  ADD COLUMN trustpilot_url text,   -- hand-verified. NEVER a name search.
  ADD COLUMN g2_slug        text;

-- every paid call, attributable
ALTER TABLE spend
  ADD COLUMN source     text,
  ADD COLUMN signal_id  bigint,
  ADD COLUMN company_id bigint,
  ADD COLUMN actor      text,
  ADD COLUMN user_email text;
```

`watchlist.trustpilot_url` being hand-verified is a hard requirement:
`ti.to` name-matched **Tito-Express**, a German printer-ink retailer, and
returned 12 reviews about undelivered toner.

---

## 6. Collector architecture

```python
class Collector:
    name: str
    kind: str                  # review | forum | vendor_news | install | job_post
    cadence: str               # "scheduled" (free) | "on_demand" (paid)
    cost_model: CostModel      # per_run | per_item | free  -> drives the button label
    requires: tuple[str, ...]  # credential names
    known_broken: str = ""
    robots_ok: bool = True     # False excludes it from ever running
```

The registry is the single source of truth for what the UI renders. A source tab
shows **available / needs credentials / known broken (with reason) / not built**
— so an empty tab explains itself rather than showing zero rows.

| Collector | Cadence | Cost | State |
|---|---|---|---|
| `vendor_news` | scheduled | free | ✅ |
| `meraevents_organisers` | scheduled | free | to build — **the unlock** |
| `townscript_organisers` | scheduled | free | to build |
| `trustpilot` | on_demand | $0.05/run | to build |
| `apify_g2` | on_demand | ~$0.15/negative | ✅ needs 6 field fixes |
| `reddit` | on_demand | $0.17/run | pin to organiser subreddits |
| `trustradius`, `softwaresuggest` | on_demand | tbd | to build |
| `apify_capterra` | — | — | ❌ 403, tab disabled with reason |
| `apify_jobs` | — | — | ❌ disproved, retired |

### Audience rule, learned from evidence

> **Consumer-facing marketplaces yield ticket buyers. Organiser-facing SaaS
> yields organisers.**

Eventbrite on Trustpilot: 20/20 buyers. Ticket Tailor: 3 clear organisers.
Agoda/Trip.com/Viator: 24 reviews, 0 supplier-side. So the Trustpilot watchlist
targets **Ticket Tailor, Tito, Humanitix, Billetto, Eventix, Ticketleap**, and
US event platforms once their slugs are hand-verified — not consumer front-ends.

---

## 6b. Google My Business — enrichment, not reviews (tested Aug 3, $0.008)

Tested `compass~crawler-google-places` against both possible uses.

**As a review source: no.** "BookMyShow Office, Mumbai" has 133 reviews at 4.1,
but they are about the *office* — `1★ "Would not even pick up the call"` — not
the ticketing product. And "Eventbrite office" matched **The Event Group**, an
unrelated Denver event planner. Same brand-matching hazard as Tito-Express.

**As an enrichment source: it is the best one found.**

```
"9 Blocks Photography Hyderabad" → https://www.9blocks.in/   +91 98490 46439
                                    Wedding photographer, 4.5★, full address
"4moles Golf"                    → http://www.4moles.com/    +91 99582 65656
                                    Golf club, 4.1★
```

$0.0082 for 3 lookups — **~$0.0027 each, ≈$20 for all 7,273 organisers.**

Two reasons this outranks Apollo for this product:

1. **It returns a phone number.** Apollo returned `phone: None` for `9blocks.in`.
   Outreach here is **phone-first by default** (`leads.CONTACTABLE_SQL`), so the
   field that decides whether a lead is contactable at all comes from Google,
   not Apollo.
2. **It returns the website**, which is precisely the input Apollo's
   `organizations/enrich` needs. GMB can replace the name→domain step entirely.

Revised enrichment order: **GMB first** (domain + phone + address + category),
**Apollo second** on the resolved domain (headcount, industry, tech stack).
Apollo's `technology_names` came back empty for a real 5-person Indian firm, so
`detect_vendors()` will usually be empty — platform attribution keeps coming
from the sitemap the organiser was discovered in, never from Apollo.

## 7. Enrichment and identity

```python
# services/identity.py
async def resolve(signal_id: int) -> dict:
    """Trustpilot gives full names ('Michelle Evans'); G2 gives 'Jan Sytze H.'.
    Confidence decides whether we may act, and is enforced, not advisory."""
```

| Tier | Condition | Permitted action |
|---|---|---|
| `high` | rare name + company named in the review + country match | auto-draftable |
| `medium` | rare name + country only | held for human review |
| `low` | common name, no company | **discarded — never contacted, never enriched** |

The `low` tier disables the Enrich button *before* spending, with the reason
shown. Contacting a named individual about a review they wrote is a different
act from company prospecting; DPDP and GDPR apply, and the tier gate is what
keeps it on the right side.

---

## 8. Drafting — the correction

Today `drafting.py` forbids the draft from referencing the signal at all, and
`draft_for_lead` never passes `category` or `core_complaint` into the prompt. The
output is therefore a generic pitch by construction.

The rule was over-corrected. Three settings exist; the product wants the third:

| | |
|---|---|
| too far | "I saw your 3-star review complaining about integrations" |
| today | generic pitch, complaint discarded |
| **target** | "Most organisers your size tell us reporting and integrations are where their platform costs them time" |

**Change:** pass `category` + `core_complaint` into the draft context. Rewrite the
hard rule to forbid *quoting, attribution and any hint of having read a review*,
while **requiring** the message to address the identified problem. Add a test
asserting no verbatim n-gram of the review survives into the draft.

---

## 9. API surface

```
GET  /api/signals?competitor=&source=&rating_lte=&country=&category=&from=&to=
POST /api/signals/{id}/enrich-reviewer      → identity.resolve      (paid, gated)
POST /api/signals/{id}/enrich-company       → enrichment            (free)
POST /api/collect                           → one source × competitor (paid)
GET  /api/collect/estimate?source=&n=       → cost preview for the button
GET  /api/sources                           → registry state for the tabs
GET  /api/export/reviews?from=&to=&group=month|year&platform=&source=&format=
GET  /api/spend?month=                      → per-source, per-user, vs cap
```

Existing `/mcp` (27 tools) and bearer-authed `/cron/*` are unchanged. Bearer auth
stays **ASGI middleware** — route dependencies on the parent never run for a
mounted sub-app.

---

## 10. UI

```
/            public landing page (server-rendered, indexable)
/app         dashboard
 ├─ Signals  ── competitor → source → filters → rows with per-row buttons
 ├─ Leads    ── scored queue, drafts, status
 ├─ Sources  ── per-source triggers, cost estimates, last run, spend
 ├─ Export   ── period export, monthly/yearly, CSV + XLSX
 └─ Settings ── access mode, value proposition, spend cap, channel
```

Signal feed row: platform · source site · rating + sub-scores · review title and
body · reviewer display name + country · switched-from badge · deep link ·
matched company · `Enrich reviewer · ~$0.03` · `Enrich company` · confidence chip.

Brand: swan-orange `#f97316`, swan-orange-dark `#ea580c`, swan-pink `#ec4899`,
charcoal `#1e293b`, surface `#f8fafc`, muted `#64748b`, DM Sans — matching the
marketing site.

---

## 11. Cost model

Measured today, not estimated:

| Operation | Cost |
|---|---|
| MeraEvents / Townscript sitemaps | **free** |
| Apollo `organizations/search` + `enrich` | **free** |
| Google News RSS | **free** |
| Trustpilot run (≤ 20 reviews) | $0.05 |
| G2 per negative review found | ~$0.15 (4% yield) |
| Reddit run | $0.17 |
| Apollo `people/match` | ~1 credit (paid plan) |

Controls: cost label on every button · cache-first so a second click is free ·
`low` confidence disables the button before spending · every call written to
`spend` with source, row, user · monthly cap warning at 80%, disabling at 100%
with admin override. **Cost approved is not cost unbounded.**

Export never triggers a paid fetch. It exports stored rows only — otherwise a
careless date range becomes a large unintended bill.

---

## 12. Build sequence

**Phase A — free, unblocked, visible immediately**
1. Migration 006. 2. Fix the 6 G2 field mappings. 3. Backfill 25 real Eventbrite
reviews from dataset `9b0eQswNwawOdAVua` (already paid for, free to re-read).
4. Delete the 9 stale helpdesk signals. 5. Rebuild the signal feed with the
three-level selector. 6. Export refuses empty ranges. 7. Brand pass.

**Phase B — the unlock**
8. `meraevents_organisers`. 9. Apollo name→domain resolver with confidence
scoring, checkpoint and resume. 10. Company enrichment on resolved domains.
11. `townscript_organisers`. 12. Join reviews to companies on platform.

**Phase B2 — paid sources and controls**
13. `trustpilot` against hand-verified slugs. 14. **Drafter fix.** 15. Sources
panel. 16. `identity.resolve` with tiers. 17. Per-row buttons. 18. Period export.
19. Move paid collectors off cron. 20. Pin Reddit to organiser subreddits.

**Phase C — breadth**
21. TrustRadius, SoftwareSuggest. 22. US event platforms with verified slugs.
23. ProductHunt if yield justifies.

---

## 13. Open decisions

1. **Travel scope.** Trip.com/Agoda/Viator tested: 24 reviews, 0 supplier-side.
   Adding them changes the ICP to attraction and tour operators — new taxonomy,
   new value proposition, and a different place to find them than review sites.
   Recommendation: keep event ticketing; revisit travel as a deliberate pivot.
2. **The value proposition is still a placeholder**, flagged in the UI via
   `stats.generic_pitch`. Every draft is weaker than it should be until this is
   real. This is the highest-value thing only you can supply.
3. **Apollo free-tier rate limit** against ~7,273 lookups is untested. The
   resolver checkpoints and resumes; the real ceiling will be found by running.
4. **Reddit credentials** — free official API app, ~2 minutes, still outstanding.
5. **Nothing is committed.** 27 modified/untracked files, including work already
   deployed and serving traffic. The container is running code that exists
   nowhere but this disk.
