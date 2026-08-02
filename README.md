# Intent Desk

Finds companies running a competitor's **event ticketing platform**, scores them
by readiness to switch, drafts outreach, and serves it to a dashboard and an MCP
server over one shared service layer.

What is left to do: [REMAINING.md](REMAINING.md). Original design and rationale:
[PLAN.md](PLAN.md) — written against a helpdesk market, superseded on 2026-08-02.

Everything market-specific lives in `intentdesk/market.py`: competitors,
complaint taxonomy, vendor markers, job and news queries, prompt wording. A
future pivot is an edit to that one file.

## Layout

```
intentdesk/
  config.py        settings from .env
  db.py            asyncpg pool (no ORM — this box is short on RAM)
  market.py        competitors, taxonomy, queries — the only market-specific file
  services/        ALL business logic lives here
  collectors/      jobs (Indeed), news (Google News RSS), reddit, g2, capterra
  api/app.py       FastAPI: REST + /mcp + /cron + serves the built dashboard
  mcp/             the same services exposed as MCP tools
migrations/        plain SQL, applied in order, run before uvicorn in the image
scripts/seed.py    watchlist + optional demo rows
web/               React dashboard
```

The rule that keeps the two front ends honest: **API and MCP are thin adapters.
Business logic only ever goes in `services/`.**

## Running locally

```bash
docker compose up -d                                   # Postgres on 127.0.0.1:5433
.venv/bin/python -m scripts.seed --demo                # watchlist + demo rows
.venv/bin/uvicorn intentdesk.api.app:app --port 8100
```

First-time setup:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # then fill POSTGRES_PASSWORD and DATABASE_URL
docker exec -i swan-intent-db psql -U intentdesk -d intentdesk \
  -v ON_ERROR_STOP=1 < migrations/001_init.sql
```

Demo rows all use `.example` domains (reserved by RFC 2606, can never be real).
Remove them with `python -m scripts.seed --purge-demo`.

## Ports

| Service | Port | Notes |
|---|---|---|
| Postgres | 127.0.0.1:5433 | loopback only |
| API | 8100 | |
| MCP over HTTP | 8110 | Phase 4 |

Chosen to avoid what this VM already uses: 22, 53, 80, 443, 3020, 6001, 6002,
8000, 8001, 8080, 8200.

## API

Session-authenticated (Google), for the dashboard:

`GET /health` · `GET /api/stats` · `GET /api/leads` · `GET /api/leads/{id}` ·
`PATCH /api/leads/{id}` · `POST /api/leads/{id}/draft` · `GET /api/signals` ·
`GET /api/signals/health` · `GET|POST /api/watchlist` ·
`DELETE /api/watchlist/{competitor}` · `GET|POST /api/suppression` ·
`POST /api/suppression/bulk` · `GET|PATCH /api/settings` · `POST /api/scan` ·
`GET /api/scan/status` · `GET /api/alerts` · `GET /api/digest` ·
`POST /api/enrich` · `POST /api/drafts/generate` · `GET /api/export/leads.csv`

Auth is bypassed when `APP_ENV=dev` (the app is loopback-bound). Any other value
requires a session.

### Sign-in

Branded pages at `/login` and `/signup`, server-rendered rather than part of the
React bundle — someone who cannot sign in should never be looking at a blank
page because a 168KB bundle failed to load.

Two ways in, both landing on the same `users` row: **Google** (no password to
store) and **email + password** (stdlib `hashlib.scrypt`, OWASP parameters, no
new dependency on a RAM-tight box). Signing in with Google using an address that
already has a password account links the two rather than creating a second one.

**The first account created becomes the admin**, so a fresh deploy is never
locked out of its own access settings.

**Access is open: anyone can sign in.** No company domain is required, and none
is configured — `ALLOWED_EMAIL_DOMAIN` ships empty so a default cannot quietly
become a restriction later.

`access_mode` is a runtime setting, changed in Settings without a redeploy, and
is checked on **every sign-in** rather than only at registration — so tightening
it locks out accounts created while it was loose:

| Mode | Who gets in |
|---|---|
| `open` *(current)* | Anyone. Any address may register; any Google account may sign in |
| `domain` | Only `allowed_email_domains` |
| `allowlist` | Those domains, plus addresses that already have an account |

`allowed_email_domains` is ignored entirely in `open` mode. Switching to
`domain` or `allowlist` with an empty list is refused — that lockout costs a
`psql` session to undo.

### Bearer-authenticated

Both mounted sub-apps use `MCP_BEARER_TOKEN`, because neither an MCP client nor
n8n can obtain a Google session — there is no browser to redirect. The check is
ASGI middleware rather than a route dependency: route dependencies declared on
the parent never run for a mounted sub-app, so a per-route check would be one
forgotten decorator away from an open endpoint.

| Path | Purpose |
|---|---|
| `POST /mcp` | MCP over streamable HTTP, 27 tools |
| `POST /cron/scan` | Scheduled scan. `?free_only=true` skips paid collectors |
| `POST /cron/enrich` · `/cron/draft` | Apollo enrichment, batch drafting |
| `GET /cron/digest?fmt=text` | Plain-text digest for Slack or email |
| `GET /cron/alerts` | Machine-readable health |
| `POST /cron/reconcile` | Recorded spend vs Apify's own figure |

## Schema notes

- `leads.heat` is a **generated column** off `score`, so the two cannot drift.
- A partial unique index allows **one live lead per company** (`NEW`/`APPROVED`);
  a rescan updates the score in place instead of piling up duplicates.
- `signals` dedups on `(source, source_id)` — rescanning the same G2 page cannot
  re-score a company or trigger a second draft.
- Rejecting or sending a lead **suppresses the domain** automatically.
- Postgres data lives on the named volume `swan_intent_pgdata`. Losing it means
  losing the dedup store, which means re-contacting people. Do not prune it.
