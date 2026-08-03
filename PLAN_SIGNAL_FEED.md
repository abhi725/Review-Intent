# Plan: overcoming the empty-database blocker

Written 2026-08-03. Everything below was **tested against the live APIs**, not
assumed. Costs incurred: **$0.00** — no Apify credits, no paid keys.

---

## 0. The finding that changes everything

**A previously recorded conclusion was wrong.** The project notes said:

> "Apollo enriches a domain you already have; it can never discover one."

That is true of `mixed_companies/search`, which returns a hard 403 on the free
plan. It is **not** true of `organizations/search`, which I tested today and
which works on the free plan, returning a domain from a company **name**:

```
POST /api/v1/organizations/search  {"q_organization_name": "9 Blocks Photography"}
  -> 200  '9 Blocks Photography'  domain=9blocks.in  country=India  staff=5

POST /api/v1/organizations/search  {"q_organization_name": "AACE India"}
  -> 200  'AACE India Section'    domain=aaceindia.org  country=India  staff=1

POST /api/v1/organizations/search  {"q_organization_name": "Indian Institute of Management Bangalore"}
  -> 200  domain=iimb.ac.in  country=India  staff=1600  phone=+91 80 2658 2450
```

Name → domain works, free. That was the missing link the entire pipeline was
blocked on.

### Apollo free-plan capability map (tested today)

| Endpoint | Status | Use |
|---|---|---|
| `organizations/search` | **200 works** | **name → domain, country, headcount, sometimes phone** |
| `organizations/enrich` (by `domain`) | 200 works | domain → tech stack, phone, industry, city |
| `organizations/enrich` (by `name` only) | 200 but `{}` | useless — needs a domain |
| `mixed_companies/search` | **403** | "not included in your Free plan… even with a master key" |
| all `people/*` endpoints | 403 | person-level email/phone — genuinely paywalled |

**Conclusion on your first question: you do not need a paid Apollo plan.** The
two endpoints the pipeline needs are both free. Paid Apollo only adds
person-level contacts, which is a later problem than the one blocking you.

---

## 1. Where the companies come from — tested

I probed seven event platforms for (a) what `robots.txt` permits and (b) whether
an organiser is actually exposed.

| Platform | robots.txt | Machine-readable inventory | Verdict |
|---|---|---|---|
| **MeraEvents** | 0 disallows | **`/sitemaps/organizers/1` → 7,273 organiser URLs** | ✅ **best source** |
| **Townscript** | 0 disallows | `upcoming-event-pages.xml` → **7,547**; past → **40,000** | ✅ good, needs parsing |
| Explara | **`/e/` disallowed** | sitemap is marketing/help pages only | ❌ respect robots.txt |
| Insider | 0 disallows | `sitemap.xml` returns an HTML app shell, 0 URLs | ❌ client-rendered |
| BookMyShow | **403 on robots.txt** | — | ❌ CDN-blocked |
| AllEvents | **403 on robots.txt** | — | ❌ CDN-blocked |
| Eventbrite | 51 disallows | sitemap index available | ⚠️ later, US-heavy |

### MeraEvents is the unlock

`https://meraevents.com/sitemaps/organizers/1` is a sitemap **they publish for
crawlers**, listing 7,273 organiser profile pages:

```
https://meraevents.com/o/4moles                 -> "4moles.com"
https://meraevents.com/o/9-blocks-photography-zm7c1 -> "9 Blocks Photography"
https://meraevents.com/o/aace-india-mbldg       -> "AACE India"
https://meraevents.com/o/aad-events-9dxud       -> "Aad Events"
```

Every one is a company **demonstrably using MeraEvents as its ticketing
platform**. That is precisely the install-base fact BuiltWith wanted ~$295/month
to infer — available free, from a file published to be read.

Townscript adds a second competitor's install base: organiser name appears in
JSON-LD as `performer` on event pages (present on ~2 of 4 sampled; the rest need
the organiser section, which is Angular-rendered).

### What is *not* available anywhere

No organiser email or phone on either platform's public pages. I checked. That
is fine — Apollo supplies company phone from the domain.

---

## 2. The pipeline, end to end

```
MeraEvents organiser sitemap        7,273 names          free
  └─ organiser name + platform ─────────────────────────  free
       └─ Apollo organizations/search  → domain, country, staff, phone   free
            └─ Apollo organizations/enrich(domain) → tech stack, industry  free
                 └─ companies table  ← THE BLOCKER DISSOLVES
                      └─ G2 reviews joined on platform  (evidence)
                           └─ leads → scoring → export
```

Add Townscript and the same pipeline yields a second competitor's customer base.

### Match-quality caveat, from the test

Apollo name-matching is fuzzy and sometimes wrong:

- `"Aad Events"` → `"AAD A EVENTS"` / `aadyaevents.in` — plausible, unverified
- `"4moles"` → 3 results, one of them a person's name (`"Dinesh Thakur"`)

So the collector must **score match confidence** and hold anything doubtful for
review rather than writing it in as fact. Rules: exact/near-exact name match
plus `country == India` plus a non-null domain → auto-accept; anything else →
`needs_review`. The `signals.matched_confidence` column already exists for this.

**Untested:** Apollo's free-tier rate limit and monthly credit ceiling. 7,273
lookups may exceed it. The collector must checkpoint and resume, and record
spend per run — `job_runs` and `spend` tables already support this.

---

## 3. Bugs found in the existing G2 collector

I re-read two Apify datasets from runs already paid for (free to re-read). Real
field list from 50 records:

```
reviewId title reviewText starRating nps publishedAt submittedAt updatedAt
reviewerName country region companySegment industry
productId productName productSlug url
easeOfUse easeOfSetup easeOfAdmin qualityOfSupport meetsRequirements
switchedFromOtherProduct switchedReason loveTheme hateTheme
helpfulVotes sourceType responseType
```

| # | Bug in `collectors/apify.py` | Effect |
|---|---|---|
| 1 | reads `reviewerJobTitle` / `reviewerRole` — **neither exists** | `author_role` always NULL |
| 2 | reads `reviewLink` — **does not exist** | works only by falling through to `url` |
| 3 | `productName` / `productSlug` never captured | platform name discarded |
| 4 | `switchedFromOtherProduct` / `switchedReason` never captured | **strongest buying signal discarded** |
| 5 | `country` / `region` never captured | no India filter on an India-first product |
| 6 | sub-scores never captured | complaint category re-inferred by LLM when G2 already scored it |

**On reviewer identity:** across all 50 records the only identity field is
`reviewerName = "Jan Sytze H."` — first name, last initial. No email, no phone,
no employer, no job title. G2 does not publish them, so no scraper and no paid
tier returns them. `companySegment` is a size bucket (179 = Small Business),
`industry` a numeric taxonomy id. The feed you asked for is buildable down to
**reviewer display name, platform, rating, review text, review site and a deep
link** — five of six. Contact details come from the company via Apollo, not the
reviewer.

## 4. Stale data

16 signals, 0 matched to a company. Nine are G2 reviews of **Freshdesk, Zoho
Desk and Zendesk** — the helpdesk competitors deleted in the pivot. They predate
migration 005 so `author`/`rating`/`url` are NULL. They are what currently
renders in your feed. Delete them.

`companies` = 0 is also why the export writes a header row and nothing else. The
export code is correct; it has nothing to iterate.

---

## 4b. Live end-to-end verification of the described loop (Aug 3)

Ran the four stages against live services. Verdict per stage:

| Stage | Asked for | Reality |
|---|---|---|
| Monitor **G2** | ✅ | built, runs, but the 6 field bugs above; costs Apify credits |
| Monitor **Capterra** | ❌ | 403 — needs residential proxies the free plan lacks |
| Monitor **Trustpilot** | ❌ | **deliberately not built** — registered in `NOT_BUILT` as "wrong audience — reviewers are ticket buyers, not the organisers who buy the platform" |
| Monitor similar | ⚠️ | `vendor_news` OK; `reddit` needs a free OAuth app; `apify_jobs` known-broken |
| **Extract complaint** | ✅ | **works, verified live** |
| **Enrich company** | ✅ | works |
| **Enrich reviewer** | ❌ | impossible — G2 publishes no reviewer identity |
| **Draft to the complaint** | ❌ | **built to do the exact opposite, on purpose** |

### Extraction works — proof

A real 3★ Eventbrite review through the live LLM:

```
review : "Their reach is great… The reporting isn't great, and they don't
          integrate well with other…"
analyse -> {"category": "integration_gaps",
            "core_complaint": "The platform does not integrate well with other
                               systems, making data combination difficult.",
            "severity": 3, "company_name": null}
```

### The drafter throws that away

`drafting.py` carries a hard rule, stated in its own docstring:

> "The drafting rule that matters most is negative: the draft never references
> the signal that surfaced the lead."

`DRAFT_SYSTEM` and `CALL_SYSTEM` both say *"Never mention, quote, or allude to
any review… Write as though you had never seen one. Speak to the industry
problem, not to the individual's grievance."*

And `draft_for_lead` passes only company, city, vendor, size, role and the
value proposition. **`category` and `core_complaint` never reach the draft
prompt at all.** So the output is precisely the generic pitch you said you did
not want — not by accident, by construction.

The reasoning behind the rule is sound in one respect: quoting a review back at
its author is unsettling to receive, and for an identifiable reviewer it uses
their words without consent. But the rule overshoots. There is a middle setting
it currently skips:

- **too far:** "I saw your 3-star review complaining about integrations"
- **currently:** generic pitch, complaint discarded
- **what you want:** "Most organisers your size tell us reporting and
  integrations are where their current platform costs them time" — specific to
  the *problem*, silent about the *review*

That is a prompt-and-plumbing change: pass `category` + `core_complaint` into
the draft context, and rewrite the hard rule to forbid quoting and attribution
while requiring the message to address the identified problem category.

### Yield economics — the number that should shape expectations

Of 25 Eventbrite G2 reviews, **1 was negative** (≤3★). That run cost $0.154.
So roughly **$0.15 per negative review found**, and ~4% yield. Reaching 100
negative reviews implies ~2,500 reviews ≈ **$15** — three times the $5/month
Apify ceiling. G2 alone cannot be the volume source; it is the *evidence*
layer on top of companies discovered free from sitemaps.

### One more caveat found

Apollo returned **0 technologies** for `9blocks.in` (a real 5-person Hyderabad
organiser). Its tech data is thin for small Indian companies, so
`detect_vendors()` will usually come back empty. Platform attribution must come
from the sitemap the company was found in — which is exactly what MeraEvents
and Townscript give for free — not from Apollo.

---

## 4c. Multi-source review pull — live results (Aug 3, spend $0.27)

106 reviews actually collected. Raw data: `REVIEW_SOURCES_SAMPLE.json`.

| Source | Platform | N | Negative | Audience | Named author |
|---|---|---|---|---|---|
| Trustpilot | Eventbrite | 20 | 20 | **buyers** | 20/20 |
| Trustpilot | **Ticket Tailor** | 12 | 12 | **3 organisers** | 12/12 |
| Trustpilot | Weezevent | 12 | 12 | FR consumers | 12/12 |
| Trustpilot | Tito-Express | 12 | 12 | **wrong company** | 12/12 |
| G2 | Eventbrite | 25 | 1 | 7 organiser-ish | 25/25 |
| G2 | Zoho Desk | 25 | 1 | stale, pre-pivot | 25/25 |

### You were right, with a qualification

Trustpilot **does** carry organisers — but not on Eventbrite. All 20 negative
Eventbrite reviews are ticket buyers ("was scammed for $369", "couldn't log in",
"9 attempts to process my payment"). On **organiser-facing brands** the audience
flips:

```
Ticket Tailor 3★ Michelle Evans (US)
  "As a mahjong instructor, I love MANY of the features… for many of
   our events we don't use that…"

Ticket Tailor 2★ Abi Lupton-Levy (GB)
  "I was having problems editing my event, so tried online chat.
   They say response time is under three minutes — I waited 1.5 hours."
```

Those are leads. So the rule is not "Trustpilot is the wrong audience" — it is
**"consumer-facing marketplaces yield buyers; organiser-facing SaaS yields
organisers."** Target Ticket Tailor, Tito, Humanitix, Weezevent, Billetto,
Eventix, Ticketleap — not BookMyShow or Eventbrite's consumer front.

### Trustpilot beats G2 on identity

Trustpilot returns **full display names** plus country and review history
(`Michelle Evans`, `US`). G2 returns `"Jan Sytze H."` — first name, last
initial. For the identity-resolution idea below, Trustpilot is the better input
by a wide margin.

### Data-quality hazard found

`ti.to` matched **Tito-Express**, a German printer-ink retailer — 12 reviews of
undelivered toner cartridges. Brand→Trustpilot mapping must be a verified
allow-list of business URLs, never a name search. `strictNameMatch: true` plus a
hand-checked slug per competitor.

### Source status after today

| Source | Verdict |
|---|---|
| **Trustpilot** | ✅ works, $0.05/run, named reviewers — **build it** |
| **G2** | ✅ works, ~$0.15 per negative review found (4% yield) |
| **Reddit** | ⚠️ actor runs ($0.17) but generic search hits ticket-resale subs; must pin to `r/eventprofs`, `r/events`, `r/festivalorganizers` |
| **Capterra** | ❌ still returns nothing via `gio21` actor |
| **Google Business** | ❌ Places API needs a paid key; `compass/crawler-google-places` viable but reviews are venue-level consumer feedback, not platform complaints |
| Direct HTTP | ❌ Trustpilot, Reddit and Google all 403 this box's datacenter IP — actors with residential proxies are mandatory |

---

## 4d. NEW — reviewer identity resolution (your idea, Aug 3)

> "check review, tag name or other info of person who commented bad review then
> check database of that person in apollo or linkedin, name verify and done"

This becomes viable **now that paid Apollo is approved** — the `people/*`
endpoints that return 403 on free are exactly the ones this needs. Design:

1. Take `reviewerName` + `reviewerCountry` from Trustpilot (full names, unlike G2).
2. Mine the review text for self-identification — "As a mahjong instructor",
   "our events", a named venue or company. The existing `analyse()` already
   extracts `company_name` when stated outright and returns `null` otherwise.
3. Query Apollo `people/match` on name + country (+ company when known).
4. **Confidence tiers, enforced in code:**
   - `high` — rare name + company named in the review + country match → usable
   - `medium` — rare name + country only → hold for human review
   - `low` — common name, no company → **discard, never contact**
5. Store the tier on the lead; the UI shows it; only `high` is auto-draftable.

Honest limits, so this is not oversold: "Abi Lupton-Levy" is rare enough to
resolve; "Michelle Evans" is not. Expect a minority of reviews to reach `high`.
And contacting a named individual about a review they wrote is a different act
from company prospecting — DPDP/GDPR applies, the tier gate is what keeps it on
the right side, and outreach must still never quote the review (see §4b).

## 4e. NEW — on-demand collection trigger in the dashboard

> "there should be a button in dashboard where I can trigger which data i want"

Build a **Sources** panel on `/app`:

- one row per source × competitor, with last-run time, rows returned, spend
- checkboxes to choose sources and competitors, a star-rating filter, a row cap
- an **estimated cost** shown before the run, from measured per-run figures
  ($0.05 Trustpilot, ~$0.15 per negative G2 review, $0.17 Reddit)
- a **Run now** button posting to `/api/scan/run` with the selection
- live status from the existing `job_runs` table, and a hard monthly spend cap
  with the current month's total from the `spend` table

The backend already has most of this: `scan.run()`, the collector registry with
`availability()`, `job_runs`, and `spend`. What is missing is the selective
input and the API surface.

## 4f. NEW — on-demand, per-row fetching (your cost-control design, Aug 3)

> "in signal feed add button where which review user data i want. then our
> platform automatically take it from apollo or that g2 or trustpilot. so this
> also saves our cost… button should be trigger to fetch it."

The principle: **nothing paid happens on a schedule. Every paid call is a click,
on a specific row, with the price shown before you click it.** This is the right
call — bulk-enriching 7,273 companies would cost far more than enriching the 40
you actually intend to contact.

### Per-row enrichment button

Each signal-feed row gets an **Enrich** control with a cost label:

| Button | Calls | Returns | Est. cost |
|---|---|---|---|
| **Enrich reviewer** | Apollo `people/match` on name + country (+ company if the review names one) | person, title, LinkedIn, work email/phone | ~1 Apollo credit |
| **Enrich company** | Apollo `organizations/search` → `organizations/enrich` | domain, phone, headcount, city, tech | free tier |
| **Get more reviews** | Trustpilot or G2 actor for that platform | 10–50 more reviews | $0.05 Trustpilot / ~$0.15 per negative G2 |

Rules that keep this honest:

1. **Cost preview on the control** — the button reads `Enrich reviewer · ~$0.03`,
   never a bare "Enrich". No click ever spends an unknown amount.
2. **Cache-first, and say so.** Every fetch is written to `signals` /
   `companies` with a `fetched_at`. A second click on an already-enriched row
   reads the cache and charges nothing — the button changes to
   `Re-fetch · ~$0.03` so a deliberate refresh is still possible.
3. **Confidence gate before spending.** If reviewer identity resolves `low`
   (§4d), the Enrich-reviewer button is disabled with the reason shown, rather
   than burning a credit on a match that will be discarded anyway.
4. **Every paid call is logged** to `spend` with source, row id, user and
   amount, so `rtk`-style "what did today cost" is answerable per click.
5. **Monthly cap** in Settings. At 80% the buttons warn; at 100% they disable
   with an override for an admin. Cost being approved is not the same as cost
   being unbounded.

### Bulk export by period

> "if customer or I want to bulk export monthly wise data or yearly wise review
> rating data then that can also do"

A second export, distinct from the existing leads export (which stays as-is):

- **Endpoint** `/api/export/reviews?from=&to=&group=month|year&platform=&source=`
- **Formats** CSV and XLSX, reusing `export.py`'s BOM handling and paging
- **Row grain**: one review per row — date, platform, source site, rating,
  sub-scores, category, reviewer display name, country, review URL, matched
  company, enrichment status
- **Summary sheet** (XLSX) or companion CSV with the aggregate you asked for:
  per period × platform — review count, average rating, rating distribution
  1–5★, negative share, top three complaint categories
- **Purely from stored rows.** Export never triggers a paid fetch; it exports
  what has already been collected. Otherwise a careless date range becomes a
  large unintended bill.
- Fixes the current complaint too: when the range contains nothing, the export
  refuses with "no reviews in this period" instead of downloading headers only.

### What this changes about the collection strategy

Scheduled scanning drops to the **free** collectors only (`vendor_news`, and the
MeraEvents/Townscript organiser sitemaps). Everything with a price tag —
Trustpilot, G2, Apollo people — becomes pull, not push. That inverts the current
design, where `scan.run()` would fan out across paid collectors on a cron.

## 4g. NEW — competitor expansion (US + travel), tested Aug 3, $0.05

You asked to add Trip.com, Agoda and other US-side ticket-booking players. I ran
one Trustpilot pass across 13 brands before adding them.

**Result: 24 negative reviews from Agoda, Viator and Trip.com — 0 supplier-side,
all consumer.** Same pattern as Eventbrite: complaints about *my* booking, *my*
refund, *my* stay. Named reviewers on 24/24, but the wrong people.

The US event-ticketing brands (StubHub, SeatGeek, AXS, Ticketmaster, Vivid
Seats) and the organiser SaaS ones **returned nothing** — `strictNameMatch`
rejected them. That is a slug problem, not a verdict: they are untested, and
each needs a hand-verified Trustpilot URL, exactly like the Tito-Express lesson.

### What this means, and the scope question it raises

`market.py` sets `BUYER_ROLE = "event organiser"`. Trip.com and Agoda do not sell
to event organisers — they sell to travellers. Their B2B equivalent is the
**hotel, attraction and tour operator** on the supply side, who does complain
about commission and payouts, but on partner forums and not on Trustpilot's
consumer page.

So there are two coherent readings, and they lead to different products:

1. **Stay with event organisers.** Add the US *event* platforms (StubHub,
   SeatGeek, AXS, Eventix, Ticketleap) and skip travel. Consistent with the
   nine competitors, the complaint taxonomy and the drafter prompts already built.
2. **Widen to travel/experience supply.** Add Trip.com, Agoda, Viator, Klook,
   GetYourGuide — but the ICP changes to attraction and tour operators, which
   means new complaint categories, a new value proposition, and a different
   place to find them than Trustpilot.

**Recommendation: (1) now, (2) as a deliberate decision later.** Adding travel
brands to the watchlist today costs little, but every review they produce will
be a traveller complaining about a refund, and the queue fills with noise the
scoring cannot use. If you want (2), the honest first step is finding where
supply-side operators actually complain — partner communities, not review sites.

Either way the watchlist gains a `segment` column (`event_ticketing` |
`travel_experience`) so the two never blur in the feed or the scoring.

## 4h. NEW — signal feed structure: competitor → source → reviews

> "should be have option of choosing competitor, then platform. then below that
> all reviews will show of that review website whatever like g2, trustpilot or
> other. capterra, or producthunt, or trustradius. or google news"

Three-level selector at the top of the feed, then results beneath:

```
COMPETITOR   [ Eventbrite | BookMyShow | Ticket Tailor | Townscript | … ]
SOURCE       [ All | G2 | Trustpilot | Google News | Reddit | Capterra
               | TrustRadius | ProductHunt | SoftwareSuggest ]
FILTERS      rating ≤ N · country · date range · complaint category · switched-from
─────────────────────────────────────────────────────────────────────
reviews for that competitor × source, newest first, each row carrying
the per-row Enrich / Get-more buttons from §4f
```

Source tabs are driven by the collector registry, so each shows live state
rather than a dead tab: **available**, **needs credentials**, **known broken**
(with the reason on hover), or **not built**. Today that renders as G2 ✅,
Google News ✅, Trustpilot ✅ (once built), Reddit ⚠️ needs subreddit pinning,
Capterra ❌ returns nothing, TrustRadius / ProductHunt / SoftwareSuggest ⬜ not
built — which is honest about why a tab is empty instead of showing zero rows.

When a competitor × source pair has no stored data, the empty state carries the
**Get more reviews · ~$0.05** trigger from §4f rather than just saying "no
results" — so the feed is also how you commission the fetch.

Sources to add as collectors, in the order their yield justifies:
**Trustpilot** (built next), **TrustRadius** and **SoftwareSuggest** (B2B, Indian
presence G2 lacks), **ProductHunt** (early-stage tools only, low yield),
**Capterra** (blocked — keep the tab disabled with the reason).

---

## 5. Plan of work

### Phase A — free, no decisions needed, visible today
1. Migration 006: add `platform`, `country`, `region`, `switched_from`,
   `switched_reason`, sub-score columns to `signals`.
2. Fix the six field mappings in `G2ReviewCollector`.
3. Backfill 25 real Eventbrite reviews from dataset `9b0eQswNwawOdAVua` — free,
   already paid for. Gives the feed genuine event-ticketing rows immediately.
4. Delete the 9 stale helpdesk signals.
5. Rebuild the signal feed: platform, review title + body, star rating,
   sub-scores, reviewer display name, country, source site, deep link,
   switched-from badge. Filters by platform, rating, country, category.
6. Export refuses to download an empty file and says why.
7. Brand pass — swan-orange `#f97316`, swan-pink `#ec4899`, charcoal `#1e293b`,
   DM Sans, to match the marketing site.

### Phase B — the unlock (this is what fixes the real problem)
8. `MeraEventsOrganiserCollector`: walk the organiser sitemap, extract company
   name + profile URL + platform. Free. ~7,273 companies.
9. `ApolloNameResolver`: `organizations/search` → domain, with confidence
   scoring and a `needs_review` queue for fuzzy matches. Checkpoint + resume.
10. Existing `organizations/enrich` on each resolved domain → tech stack, phone.
11. `TownscriptOrganiserCollector` — second competitor's install base.
12. Join G2 reviews to companies on platform, so a company row carries the
    complaints made about the platform it uses.

### Phase B2 — new sources and controls (cost approved)
13. `TrustpilotCollector` against a **verified allow-list** of organiser-facing
    brands (Ticket Tailor, Tito, Humanitix, Weezevent, Billetto, Eventix,
    Ticketleap). `strictNameMatch`, hand-checked slugs, no name search.
14. Fix the drafter: pass `category` + `core_complaint` into the prompt; rewrite
    the hard rule to forbid quoting and attribution while *requiring* the
    message to address the identified problem. This is what turns the output
    from a generic pitch into the thing you asked for.
15. **Sources panel** with per-source triggers, cost estimate and spend cap (§4e).
16. **Reviewer identity resolution** with confidence tiers (§4d), gated so only
    `high` is auto-draftable.
17. **Per-row Enrich / Get-more-reviews buttons** with cost labels, cache-first
    re-fetch, confidence gating and per-click spend logging (§4f).
18. **Period export** `/api/export/reviews` — monthly/yearly review + rating
    data, CSV and XLSX, with a summary sheet and a refusal on empty ranges (§4f).
19. Move paid collectors off the cron: scheduled scanning runs **free sources
    only**, everything priced becomes pull-on-click (§4f).
20. Pin the Reddit collector to organiser subreddits and re-test.
21. **Three-level feed selector** — competitor → source → filters, with registry-
    driven source tabs showing available / broken / not-built, and the paid
    fetch trigger in the empty state (§4h).
22. **Watchlist expansion**: US event platforms (StubHub, SeatGeek, AXS,
    Ticketleap, Eventix) with hand-verified Trustpilot slugs; add a `segment`
    column so travel brands, if added, never blur with event ticketing (§4g).
23. `TrustRadiusCollector` and `SoftwareSuggestCollector`; ProductHunt if yield
    justifies; keep Capterra's tab disabled with its 403 reason shown.

### Phase C — more evidence, in yield order
13. Reddit `r/eventprofs` via the free official API (2-minute app registration).
14. SoftwareSuggest / TrustRadius — Indian B2B presence G2 lacks.
15. **Not** Play Store / App Store. Those reviewers are ticket *buyers*.
    `market.py` sets `BUYER_ROLE = "event organiser"` — consumer complaints are
    the wrong audience and would flood the queue with noise.

---

## 6. What I need from you

Nothing, to start Phase A — it is free and unblocked.

Phase B is the answer to "best option to overcome this problem": **MeraEvents
organiser sitemap + Apollo `organizations/search`, both free.** It needs no
purchase, no Apify credits, and no CSV from you. The one open risk is Apollo's
free-tier rate limit against 7,273 lookups, which the collector will discover
and checkpoint around.

Recommendation: **do Phase A and Phase B in one pass.** Phase A alone makes the
UI look right with 25 rows of borrowed data; Phase B is what makes the product
actually have customers in it.
