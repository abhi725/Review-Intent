# Plan to Finish Intent Desk

Status as of 2026-08-02. Live at https://intent.swandigitals.com.
Background and rationale: [PLAN.md](PLAN.md).

## Where it stands

| Area | State |
|---|---|
| Schema, service layer, REST API, MCP server (19 tools) | Done |
| Dashboard — queue, signals, watchlist, settings | Done, operable |
| Deploy — Docker, Traefik, HTTPS, Google OAuth | Done |
| Scoring, matching, CSV install-base import, scan orchestration | Done, tested |
| **LLM layer — OpenAI + Gemini + Claude behind one interface** | **Done; Gemini verified live** |
| **Complaint analysis + outreach drafting** | **Done; drafting verified end to end** |
| G2 collector | Live, pulling real reviews |
| Capterra | Dead on the free Apify plan (403, needs residential proxies) |
| Reddit, job boards, install-base detection, vendor news | Not usable — see blockers |
| Apollo enrichment | Not written |
| Cron, digest, alerting, send automation | Not started |

**The single thing standing between this and real output: no contactable leads.**
Everything downstream of enrichment works, but nothing produces a name and an
email address yet. That makes Apollo the critical path, not the collectors.

---

## Blocked on you

| # | Needed | Unlocks | Cost |
|---|---|---|---|
| 1 | **Apollo API key** | Contacts on leads — the critical path | Free tier available |
| 2 | **Your real value proposition** | Every draft; the current line is my placeholder | — |
| 3 | Confirm **helpdesk** (not event) ticketing | Watchlist and pitch; assumed, never confirmed | — |
| 4 | OpenAI key *(optional)* | Primary LLM; Gemini already works as fallback | Usage-based |
| 5 | Reddit app credentials | Forum collector | Free, ~2 min |
| 6 | Paid Apify tier *(optional)* | Daily scans, job boards, Capterra via residential proxies | ~$39/mo |
| 7 | BuiltWith or Wappalyzer key *(optional)* | Automated install-base; CSV import covers it meanwhile | Paid |

Items 1–3 are the ones that matter. The rest are incremental.

---

## Phase A — Make leads contactable · ~1 session · **blocked on Apollo key**

Without this the queue can never produce an actionable lead, so it comes first.

1. `collectors/apollo.py` — `people/match` by company domain, `X-Api-Key` header.
2. Enrich only the top slice per scan (highest score first) to protect quota.
3. Persist contact name, title, email, LinkedIn, and `enrich_source`.
4. Record per-call spend against the monthly cap, as the Apify collectors do.
5. Report the identifiable rate in `stats()` — the number that decides whether
   this channel is worth continuing.

**Exit test:** a real company in the queue carries a named decision maker and a
verified email, and `stats().identifiable_pct` reflects the true rate.

## Phase B — Draft quality · ~half a session · **blocked on your value prop**

The pipeline works; the prose is generic. A test draft produced *"delight
customers"* and *"enhancing customer satisfaction"* — true to the rules, but not
something a founder would send.

1. Replace the placeholder value proposition with your real one.
2. Add two or three examples of outreach you would actually send; few-shot
   examples move tone far more than adjectives in the system prompt.
3. Ban the marketing register explicitly (no "delight", "seamless", "empower").
4. Add a `tone` argument to `draft_for_lead` so the MCP `redraft` tool can steer.
5. Re-test with OpenAI once its key exists and keep whichever reads better.

**Exit test:** five consecutive drafts you would send with at most a light edit.

## Phase C — Collectors worth having · ~1 session

Ordered by value per rupee, not by effort.

1. **Job boards** (Apify) — the strongest signal after install, because a
   posting naming the vendor proves an active install *and* budget.
2. **Reddit** — already written, never run. First live run is the test.
3. **Vendor news** — needs a working feed; the one in the plan 404s. Google News
   RSS filtered by vendor name is the pragmatic substitute.
4. **Capterra** — only revisit on a paid Apify tier.

**Exit test:** `collector_health` shows three or more sources with non-zero
counts in the last seven days.

## Phase D — Automation · ~1 session

1. n8n cron calling `POST /api/scan` — **weekly, not daily**, at $5/month Apify.
2. Morning digest to Slack or email: new hot leads, awaiting count, spend.
3. Zero-result alerting on `collector_health` — a dead scraper currently looks
   exactly like a quiet week, and only the Signal feed reveals it.
4. Reconcile recorded spend against Apify's real account usage automatically.

**Exit test:** nobody triggers anything by hand, and a deliberately broken
collector raises an alert within one cycle.

## Phase E — Hardening · mostly done

1. ~~Migration runner in the container.~~ **Done** — runs before uvicorn;
   verified it skips when applied and provisions all 8 tables on a fresh database.
2. **Test coverage — partly done.** 35 tests, up from 10: scoring, name/domain
   normalization, Gemini's schema dialect, the degraded-response validator,
   import parsing. Scan orchestration and the API endpoints still have none.
3. ~~`scan_status` reporting Capterra as READY while functionally dead.~~ **Done**
   — collectors can declare `known_broken`, and availability accounts for it.
4. ~~Expose the MCP HTTP transport.~~ **Done** — served at
   `https://intent.swandigitals.com/mcp` with bearer auth. No subdomain: it
   mounts into the existing app, so there was never a DNS record to add.
5. Bulk suppression upload; single-domain only today. **Still open.**

## Phase F — Optional

Google Sheets API sink for live sync, Mautic send automation with unsubscribe
headers, reply tracking, A/B draft variants.

---

## Suggested order

**A → B** first: they are what turn a working pipeline into one that produces
something a salesperson can act on. **E1 and E2** should be pulled forward if
anyone else is going to touch this — a redeploy against an empty database is a
bad way to discover the migration gap. **C and D** are volume and convenience,
worth doing once A and B prove the channel converts.

Roughly four to five sessions total, most of it gated on the Apollo key.

---

## LLM configuration

Providers are tried in order and fall through on refusal or error:

```
LLM_PROVIDER=openai            # primary
LLM_FALLBACK_PROVIDER=gemini   # fallback — currently the only one with a key
```

Gemini is verified working (`gemini-2.5-flash`). Two things learned the hard way
and encoded in the adapter: 2.5-flash is a **thinking model** whose reasoning is
billed against `maxOutputTokens`, so thinking is disabled for these short
outputs — left on, replies truncate mid-sentence. And Gemini's schema dialect
rejects union types like `["string", "null"]`, which silently drops the call
into free-form JSON; schemas are converted, and every structured response is
validated against required keys and enums so a degraded response fails loudly
instead of writing invented fields to the database.

The Claude adapter is written and unused — the `ANTHROPIC_API_KEY` on this box
is not in Anthropic's `sk-ant-` format. Add `claude` to the fallback chain if a
real key turns up.
