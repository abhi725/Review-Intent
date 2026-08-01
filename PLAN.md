# Sentinel — Competitive Intent Desk

Find companies running a competitor's helpdesk, score them by how ready they are to switch, draft outreach, and work the queue from our own dashboard. Two front ends over one core: a **web dashboard** for the sales team and our **own MCP server** for Claude.

**Date:** 2026-08-01 (rev 3) · **Status:** Awaiting market decision + tokens

---

## 1. Architecture

Everything real lives in a service layer of plain Python functions. Both front ends are thin adapters over it, and neither is allowed to hold business logic.

```
                            ┌───────────────────────────────────┐
  Dashboard (React SPA)     │  sentinel/services/               │
  ──── REST ───────────────▶│    leads · signals · scoring ·    │
                            │    enrichment · drafting ·        │
  Claude Code (stdio)       │    watchlist · export             │
  ──── MCP tools ──────────▶│                                   │
                            │  sentinel/collectors/             │
  claude.ai (HTTP + bearer) │    installbase · jobs · reviews · │
  ──── MCP tools ──────────▶│    reddit · vendornews            │
                            │                                   │
  n8n cron 07:00            │  Postgres (Coolify, named volume) │
  ──── POST /scan ─────────▶└───────────────────────────────────┘
```

Adapters: `sentinel/api/` (FastAPI, also serves the built React bundle) and `sentinel/mcp/` (FastMCP, stdio + streamable-HTTP). One Docker image runs both. Adding a tool to MCP is then a five-line wrapper around a function the dashboard already uses.

**Not in scope:** Twenty CRM writes. Google Sheets is a one-way export only, never the working surface.

### Why the funnel is install-first

Verified volumes (Aug 2026): Zendesk has ~595 Trustpilot reviews *all-time* and ~6,700 on G2, while tech detection finds **98,900–435,778** live installs. Review-first yields 3–7 identifiable leads a month. Install-first yields thousands of named companies with domains, and intent signals decide who gets contacted first rather than who exists at all.

---

## 2. The two front ends

### Dashboard — four screens behind Google OAuth

**Lead queue** is where the team lives. KPI strip on top (new today, hot, awaiting review, approved this week, install base tracked), then one table: company, what they run, *why now* as signal chips (`JOB POST · 6d`, `G2 2★ · 11d`, `PRICE HIKE`), score, status. A coloured left stripe per row encodes heat so hot leads read without reading numbers. Filters: All, Hot, Awaiting review, Approved.

Selecting a row opens the detail panel: company facts, a **Why-now timeline** of every signal with quote and age, the enriched contact, and an editable draft. Three actions — Approve, Reject, Copy.

**Signal feed** — raw signals from the last 7 days, matched to companies where possible. This screen proves the collectors are alive; an empty feed means a scraper broke, which otherwise looks exactly like a quiet week.

**Watchlist** — per competitor: sources tracked, install base in India, negatives in 180 days, leads produced. Shows which competitor earns its spend.

**Settings** — geography, agent band, recency window, spend cap, scan schedule, suppression list, and the value-prop line the drafter uses.

### MCP server — our own, over the same services

| Tool | Purpose |
|---|---|
| `list_leads(heat?, status?, city?, since?)` | query the queue |
| `get_lead(id)` | full record with signal timeline |
| `set_lead_status(id, status)` | approve, reject, mark sent |
| `redraft(id, instructions?)` | regenerate with a steer, e.g. "shorter, less formal" |
| `list_signals(kind?, matched?, since?)` | raw feed |
| `scan(collector?, competitor?)` | trigger a run, returns a summary |
| `watchlist_add / watchlist_list / watchlist_remove` | manage competitors |
| `suppress(domain, reason)` | never contact |
| `stats()` | funnel counts, identifiable %, spend to date |
| `export_sheet()` | push current queue to the Sheet |

Two transports from one codebase: **stdio** for Claude Code on this VM, and **streamable-HTTP** at `mcp.swandigitals.com` with bearer auth for claude.ai. Note: claude.ai custom connectors may require an OAuth flow rather than a static bearer — if so, bearer still covers local and server-to-server use, and OAuth becomes a small Phase 4 add-on.

---

## 3. Collectors

| Source | What it gives | Cost |
|---|---|---|
| **Tech detection** (BuiltWith / Wappalyzer API) | The install base — named companies with domains, 100% identifiable | Paid tier, main line item |
| Job boards (Naukri, LinkedIn) | "Zendesk administrator" postings — active install *and* budget | Apify actor, cheap |
| G2 + Capterra | Negative reviews ≤3★, 180-day window | `automation-lab/g2-scraper` $0.005/review · `imadjourney/capterra-reviews-scraper` ~$6/1k |
| Reddit | Complaints in r/sysadmin, r/msp, r/india_startups | **Free** — official API |
| Vendor news | Price-hike announcements as cohort triggers | Free — RSS + Haiku classifier |
| Trustpilot | **Dropped.** ~595 lifetime Zendesk reviews, mostly end users who hit a support widget, not buyers | — |

## 4. Scoring

```
install detected (base)                        30
+ job posting naming the vendor, ≤30d          25
+ negative review ≤3★, company-identifiable    30
+ forum complaint matched to company           25
+ vendor price-hike cohort member              15
+ inside target size band                      10
× recency decay per signal (180-day half-life)
```

Capped at 100. **Hot ≥80 · warm 55–79 · cool <55.** Cool leads are not discarded; they wait for a signal to lift them.

## 5. Data model (Postgres)

```sql
companies(id PK, name, domain UNIQUE, city, country, employee_band,
          vendor, agents_est, first_detected, last_seen)

signals(id PK, company_id FK NULL, kind, source, source_id UNIQUE,
        observed_at, raw_text, quote, weight, matched_confidence)

leads(id PK, company_id FK, score, heat, contact_name, contact_title,
      contact_email, contact_linkedin, enrich_source,
      draft_subject, draft_body, status, status_changed_at, created_at)

suppression(domain PK, reason, added_at)
watchlist(id PK, competitor, sources JSONB, active)
spend(id PK, day, provider, amount_usd)
```

## 6. Guardrails

1. **Company-level outreach by default.** Drafts never quote or reference the review that surfaced the lead.
2. **Nothing sends automatically.** Approve copies the draft; the rep sends from their own mailbox.
3. **Suppression checked before drafting** — customers, prior contacts, unsubscribes, rejects.
4. **Spend caps set on the provider accounts**, not only in code — providers bill as a run proceeds and code cannot reliably stop mid-run.
5. **Zero-result alert** — any collector returning nothing twice running raises a warning on the Signal feed.
6. **Postgres on a named Coolify volume.** Losing the dedup store means re-contacting people you already emailed.

---

# Phases

**Status at 2026-08-01:** live at https://intent.swandigitals.com.

- **Phase 1 — done.** Schema, service layer, REST API, dashboard, deployed behind Traefik with Google OAuth.
- **Phase 2 — partial.** Scoring, matching, CSV install-base import and scan orchestration built and tested. Every network collector is blocked on credentials; the Reddit collector is written but has never run. Apollo enrichment and the Claude drafter are not written — deliberately, until there is a key to test them against.
- **Phase 3 — done, except the Sheets API.** The dashboard is fully operable: run scan, watchlist add/deactivate, editable targeting saved to the database, suppression removal, collector status panel. Export is CSV rather than a Sheets API write, which needs no service account and imports into Sheets directly.
- **Phases 4–6 — not started.** MCP server, cron, digest, alerting, send automation.

## Phase 0 — Decide and probe · no code · ~half a session

Nothing gets built until these are settled, because the market decision changes the watchlist, the complaint taxonomy and the pitch.

- Lock **helpdesk vs event ticketing** and the final competitor list.
- Write the one-line value proposition the drafter will use.
- Collect tokens: `BUILTWITH_API_KEY` (or Wappalyzer), `APIFY_TOKEN`, `ANTHROPIC_API_KEY`, `APOLLO_API_KEY`, Reddit app credentials.
- Spend $5 per candidate Apify actor on a test run; keep the one that returns clean rows.
- Pull one install-base sample and count how many fall inside India and the target agent band.

**Exit test:** we know the real addressable count before writing a line of code. If it comes back under a few hundred companies, we change targeting rather than build on top of it.

## Phase 1 — Spine · ~1.5 sessions

The skeleton that everything later plugs into.

- Repo scaffold: `sentinel/{services,collectors,api,mcp}`, Docker Compose for local Postgres.
- Postgres schema and migrations (Alembic).
- Service layer stubs with real signatures — this is the contract both front ends bind to.
- Install-base collector for **one** competitor, writing `companies`.
- FastAPI app, Google OAuth login, `GET /leads`, `GET /stats`.
- React + Vite + Tailwind scaffold; **Lead queue screen, read-only**, reading live rows.

**Exit test:** log in and see real Indian companies running the target competitor, filterable, with correct counts in the KPI strip.

**Blocked by:** Phase 0 items 1 and 3.

## Phase 2 — Intelligence · ~2 sessions

Turning a company list into a ranked queue with drafts.

- Collectors: job boards, Reddit, G2, vendor news.
- Signal-to-company matching with a confidence score; unmatched signals still stored.
- `score.py` implementing section 4, with recency decay.
- Apollo enrichment for contacts on the top slice only, to control cost.
- Sonnet 5 drafter: ≤90 words, problem-agitate-solution, never references the source signal.
- Detail panel: Why-now timeline, contact block, editable draft, Approve / Reject / Copy.
- Suppression enforced before any draft is generated.

**Exit test:** a hot lead shows three real signals in its timeline and a draft good enough to send with at most a light edit.

## Phase 3 — Complete the dashboard · ~1 session

- Signal feed screen with matched/unmatched split.
- Watchlist screen with per-competitor add and remove.
- Settings screen: targeting, caps, suppression upload, value-prop line.
- One-way Google Sheets export.

**Exit test:** the sales team can run a full day — review, approve, reject, export — without anyone touching a terminal.

## Phase 4 — Our MCP server · ~1 session

- FastMCP app in `sentinel/mcp/`, wrapping the section-2 tool list. Thin wrappers only.
- **stdio transport** registered with Claude Code on this VM — usable immediately.
- **streamable-HTTP transport** with bearer auth, same process, separate port.
- Structured JSON returns on every tool so Claude gets data, not prose.
- OAuth flow only if claude.ai rejects the static bearer.

**Exit test:** from Claude Code, *"show me hot leads in Pune and redraft the top one shorter"* works end to end, and the change is visible in the dashboard on refresh.

## Phase 5 — Deploy and automate · ~1 session

- Single Dockerfile: build the React bundle, serve it plus the API and MCP from one image.
- Coolify app at `sentinel.swandigitals.com`, MCP at `mcp.swandigitals.com`, Postgres on a **named volume**.
- n8n 07:00 cron calling `POST /scan`; morning digest to Slack or email.
- Zero-result alerting and the spend meter wired to real provider usage.

**Exit test:** nobody triggers anything by hand. The queue is populated and the digest has landed before the team opens the dashboard.

## Phase 6 — Optional, later

Approved-send automation through Mautic with unsubscribe headers, reply tracking, A/B draft variants, and TrustRadius or GoodFirms only if lead volume proves too thin.

---

## Still blocking Phase 0

1. **Helpdesk ticketing or event ticketing?** Everything above assumes helpdesk — Zendesk, Freshdesk, Zoho Desk, Kayako.
2. The one-line value proposition.
3. The five tokens listed in Phase 0.
