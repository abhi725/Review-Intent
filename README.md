# Intent Desk

Finds companies running a competitor's helpdesk, scores them by readiness to
switch, drafts outreach, and serves it to a dashboard and an MCP server over one
shared service layer.

Plan and phases: [PLAN.md](PLAN.md).

## Layout

```
intentdesk/
  config.py        settings from .env
  db.py            asyncpg pool (no ORM — this box is short on RAM)
  services/        ALL business logic lives here
  collectors/      Phase 2 — installbase, jobs, reviews, reddit, vendor news
  api/app.py       FastAPI: REST + serves the built dashboard
  mcp/             Phase 4 — same services exposed as MCP tools
migrations/        plain SQL, applied in order
scripts/seed.py    watchlist + optional demo rows
web/               Phase 1 remainder — React dashboard
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

`GET /health` · `GET /api/stats` · `GET /api/leads` · `GET /api/leads/{id}` ·
`PATCH /api/leads/{id}` · `GET /api/signals` · `GET /api/signals/health` ·
`GET|POST /api/watchlist` · `DELETE /api/watchlist/{competitor}` ·
`GET|POST /api/suppression`

Auth is bypassed when `APP_ENV=dev` (the app is loopback-bound). Any other value
requires a Google session; the OAuth redirect URI has to be registered against
the public domain first, which happens at deploy in Phase 5.

## Schema notes

- `leads.heat` is a **generated column** off `score`, so the two cannot drift.
- A partial unique index allows **one live lead per company** (`NEW`/`APPROVED`);
  a rescan updates the score in place instead of piling up duplicates.
- `signals` dedups on `(source, source_id)` — rescanning the same G2 page cannot
  re-score a company or trigger a second draft.
- Rejecting or sending a lead **suppresses the domain** automatically.
- Postgres data lives on the named volume `swan_intent_pgdata`. Losing it means
  losing the dedup store, which means re-contacting people. Do not prune it.
