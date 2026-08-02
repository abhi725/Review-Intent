# Plan to Finish Intent Desk

Status as of 2026-08-02, after the event-ticketing build.
Live at https://intent.swandigitals.com. Background: [PLAN.md](PLAN.md).

**Market: event ticketing, and only event ticketing.** The four helpdesk
competitors were deleted from the watchlist, not deactivated —
`python -m scripts.seed --prune` enforces it, and `market.RETIRED_COMPETITORS`
records the decision so it reads as intent rather than an accident.

---

## Where it stands

| Area | State |
|---|---|
| Schema, service layer, REST API, MCP server (27 tools) | Done |
| Dashboard — queue, signals, watchlist, settings, alerts | Done, operable |
| Deploy — Docker, Traefik, HTTPS, Google OAuth, migrations in image | Done |
| Scoring, matching, CSV import, scan orchestration | Done, tested |
| LLM layer — OpenAI primary, Gemini fallback, Claude written | Done, verified live |
| **Phone-first contactability, end to end** | **Done** |
| **Vendor news collector (Google News RSS, free)** | **Done, verified live** |
| **Job-board collector (Indeed via Apify)** | **Built, tested, does not work — see Phase A** |
| **Digest, alerting, spend reconciliation, cron endpoints** | **Done** |
| **Bulk suppression** | **Done** |
| Tests | 63, up from 35 |
| G2 | Works, but near-useless in this market — only Eventbrite has a presence |
| Capterra | Dead on the free Apify plan (403, needs residential proxies) |
| Reddit | Written, blocked on free OAuth credentials |

**The one thing standing between this and real output: the database has no
install base.** 0 companies, 0 leads. Every downstream stage works and has
nothing to work on. That is the whole of Phase A below and it is the only thing
that matters this week.

---

## Blocked on you

| # | Needed | Unlocks | Cost |
|---|---|---|---|
| 1 | **A list of Indian event organisers** (CSV: name, domain, city) | The first companies in the database — the critical path | Free if you have one |
| 2 | **Your real value proposition** | Every draft; the current line is a placeholder and the UI now says so | — |
| 3 | Reddit app credentials | The forum collector, already written | Free, ~2 min |
| 4 | BuiltWith or Wappalyzer key | The only remaining *automated* discovery route | Paid |
| 5 | Paid Apollo plan *(optional)* | Email addresses. Not needed if phone-first works | Paid |

Item 1 is the critical path and it is now a **manual** step — see Phase A.
**Resolved since the last revision:** the market question (event ticketing,
confirmed), the phone-vs-email decision (phone, built and defaulted), and the
job-board question (tested, does not work).

---

## Phase A — Get companies into the database · **blocked on a list from you**

Nothing else moves until this does, and the news is worse than the last
revision: **there is no free automated route to discovering companies.**

The job-board plan was the candidate and it was tested to destruction on
2026-08-02 for $0.042. Both halves of the premise failed:

- **Indeed does not search descriptions by vendor name.** `"Eventbrite"` returns
  `FOUND_NO_RESULTS` in the US; `"BookMyShow"` the same in India. The one Indian
  hit was a company *named* "Eventbrite & Exhibition" — a name collision, not a
  customer. Indeed matches job titles, not the tech stack in the body text.
- **`parseCompanyDetails` returns no employer website.** There is no
  `companyInfo` key in the output at all, so even a working search would yield
  no domain — and a domain is what makes a lead.

A role-based search (`"ticketing operations"`, IN) does return real postings for
about $0.004 each, but they name companies that merely employ support staff,
with no platform attribution and still no domain. Two steps short of useful.

The collector is left in the tree, marked `known_broken` so it can never bill
and never returns a misleading zero. **Do not re-run vendor-name job searches.**

What is left:

1. **Import a CSV** — `python -m scripts.import_installbase file.csv`, columns
   name/domain/city/vendor. Free, works today, and the only route that needs
   nothing new. This is the ask.
2. **BuiltWith or Wappalyzer** — the only automated install detection left, and
   it is paid.
3. **Apollo** then verifies the platform and returns a company phone. It enriches
   a domain you already have; it cannot discover one.

**Exit test:** `stats()` reports a non-zero install base and a non-zero
contactable count.

## Phase B — Draft quality · **blocked on your value prop**

The pipeline works and the prose is generic. `stats.generic_pitch` is now true
and the dashboard shows a warning on every lead, so this is visible rather than
assumed to be handled.

1. Replace the placeholder value proposition in Settings.
2. Add two or three examples of outreach you would actually send — few-shot
   examples move tone far more than adjectives in a system prompt.
3. Ban the marketing register explicitly (no "delight", "seamless", "empower").
4. Add a `tone` argument to `draft_for_lead` so the MCP `redraft` tool can steer.

Note the drafter is now **channel-aware**: on the phone channel it writes a
60-word spoken call opener that assumes a switchboard, not an email.

**Exit test:** five consecutive drafts you would use with at most a light edit.

## Phase C — Collectors · mostly done

1. ~~Job boards.~~ **Built and disproved** — see Phase A. Marked `known_broken`.
2. ~~Vendor news.~~ **Built and verified live** — Google News RSS, no key, no
   cost. Found a real Eventbrite breach-lawsuit story on the first run.
3. **Reddit** — written, blocked on free OAuth credentials. Do not spend more
   Apify budget here; global search was tried and returns noise.
4. **Capterra** — only revisit on a paid Apify tier.

**Exit test:** `collector_health` shows three or more sources with non-zero
counts in the last seven days. Currently one.

## Phase D — Automation · done, needs wiring

1. ~~Cron target.~~ **Done** — `POST /cron/scan`, plus `/cron/enrich`,
   `/cron/draft`, `/cron/digest`, `/cron/alerts`, `/cron/reconcile`. Bearer
   auth with `MCP_BEARER_TOKEN`, because n8n has no Google session and cannot
   get one.
2. ~~Digest.~~ **Done** — `GET /cron/digest?fmt=text` returns plain text ready
   to post to Slack. Includes the bad news deliberately.
3. ~~Zero-result alerting.~~ **Done** — `monitoring.alerts()` catches a
   collector that stopped returning and a cron that stopped firing, and the
   dashboard shows a persistent bar rather than a toast.
4. ~~Spend reconciliation.~~ **Done** — `/cron/reconcile` compares recorded
   spend against Apify's own monthly figure.

**Remaining:** point n8n at these. **Weekly, not daily**, at $5/month Apify.

**Exit test:** nobody triggers anything by hand, and a deliberately broken
collector raises an alert within one cycle.

## Phase E — Hardening · mostly done

1. ~~Migration runner in the container.~~ Done.
2. **Tests — 63, up from 35.** Scan orchestration and collector parsing now
   covered. Still uncovered: the API routes themselves, and the LLM providers
   against live responses.
3. ~~`scan_status` reporting a dead collector as READY.~~ Done.
4. ~~MCP over HTTP.~~ Done, at `/mcp` with bearer auth.
5. ~~Bulk suppression.~~ **Done** — paste a list, tolerant of URLs and emails,
   and it reports what it could not parse rather than dropping it.

**Still open:** an integration test that runs the API against a real throwaway
Postgres. The FakeDB stubs cover control flow but would not catch a bad column
name.

## Phase F — Optional

Google Sheets sink, Mautic send automation with unsubscribe headers, reply
tracking, A/B draft variants.

---

## Suggested order

**Phase A is the whole story.** Everything else is built and idle, waiting on
companies that no free source will produce. Hand over a CSV of Indian event
organisers and the rest of the machine has something to do. Then B (your pitch)
and the n8n wiring in D, both of which are hours rather than sessions.

If no such list exists, the honest options are a paid BuiltWith/Wappalyzer key
or accepting that this tool works the list you already have rather than finding
you a new one.

---

## Operating notes

**Outreach channel.** Settings → phone | email | both, default **phone**.
Apollo's free plan returns a company phone number and never an email address, so
`email` reports nothing contactable until a paid plan exists. The setting drives
contactability counting, which leads get drafted, and what the drafter writes.

**Spend.** $1.42 of $5 used this month. A job-board scan is ~$0.81. The cap is
enforced before a run starts — it cannot stop one already billing, which is why
`reconcile_spend` exists.

**LLM configuration.** Providers fall through on refusal or error:

```
LLM_PROVIDER=openai            # primary, live
LLM_FALLBACK_PROVIDER=gemini   # fallback, verified
```

Gemini's two traps are encoded in the adapter: 2.5-flash bills reasoning against
`maxOutputTokens` (thinking disabled, or short replies truncate), and its schema
dialect rejects union types like `["string", "null"]`, silently degrading to
free-form JSON — so every structured response is validated against required keys
and enums. The Claude adapter is written and unused: the `ANTHROPIC_API_KEY` on
this box is not in `sk-ant-` format.
