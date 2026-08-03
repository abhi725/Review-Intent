# Google Sheets sync without any Google setup

`Code.gs` is an Apps Script that lives **inside the spreadsheet** and pulls the
lead queue from Intent Desk on a timer. Recommended over the n8n route in
`../n8n/` if connecting Google to n8n is giving you trouble.

## Why this is easier

Connecting Google to a self-hosted n8n needs one of two things, and both are
four-step setups in Google Cloud Console where three of the steps fail in ways
that look like a permissions problem:

* **OAuth2** — a Cloud project, an OAuth client, a consent screen, your own
  address added as a test user, and a redirect URI that has to match literally.
  Self-hosted n8n ships no Google app of its own, which is why *Sign in with
  Google* does nothing until you supply a client ID.
* **Service account** — a key file, plus remembering to share the sheet with the
  service account's address, because it is a separate identity from you.

This script needs none of it. It **is** the spreadsheet, so it already has
permission to write to it. No Cloud project, no client ID, no consent screen, no
service account, no key. The only prompt is Google asking you to authorise your
own script against your own sheet.

It also pulls rather than being pushed to, so nothing has to reach into Google
from outside — and n8n stops being in the path at all.

## Setup

1. Open the spreadsheet → **Extensions → Apps Script**
2. Delete the contents of `Code.gs` and paste this file in
3. Set `TOKEN` to `MCP_BEARER_TOKEN` from `/root/intent-desk/.env.prod`
4. Choose `syncLeads` in the function dropdown and press **Run**. Google will ask
   you to authorise the script — that is your account granting your own script
   access to your own sheet. Approve it.
5. Choose `installTrigger` and press **Run** once. That schedules `syncLeads`
   every 6 hours.

Check **Executions** in the left sidebar to see each run.

## What it does

Pulls `/cron/leads` a page at a time, writes the header row from the data, then
updates the leads already in the sheet and appends the ones that are not — matched
on the `id` column.

Matching on `id` is the point. A plain append would add a fresh copy of all 14
leads every 6 hours and the sheet would be mostly duplicates within a day. Keyed
on `id`, a lead that changes — a draft written, a status moved to approved, a
phone number found by enrichment — updates the row already there.

Headers come from the data rather than being listed in the script, because a
hard-coded list would be a second place to edit whenever the export changes
columns, and when the two disagree the failure is silent: rows land under the
wrong headings.

Reads and writes are batched. Per-lead calls would be one Apps Script API round
trip each, and Apps Script would hit its execution time limit.

## Two things measured rather than assumed

**Pagination is driven by `has_more`, not by a short page.** Verified against the
live endpoint: at `limit=500` it takes one page, at `limit=5` it takes three, and
both return the same 14 rows. This matters because Cloudflare cuts a request at
about 100 seconds and reports it as a failure even when the work succeeded, so a
single unbounded request would begin failing silently as the queue grew.

**Cloudflare filters by client.** It answers `Python-urllib` with 403 while
allowing curl, axios, a browser, and — the one that matters here — the
`Google-Apps-Script` user agent, which returns 200. So this script reaches the
endpoint, but a quick test written in Python with default settings will look like
the endpoint is broken when it is not.

## Troubleshooting

| What you see | Cause |
| --- | --- |
| `401 from Intent Desk` | `TOKEN` is wrong. It is `MCP_BEARER_TOKEN`, not the Apify or Apollo key. |
| `403` | Cloudflare rejected the client, not an auth failure. |
| Runs but the sheet is empty | Check `SHEET_INDEX` — `0` is the first tab. |
| Duplicated rows | The `id` column was renamed or deleted; it is what rows are matched on. |

## Checking the endpoint by hand

```bash
TOK=$(grep -E '^MCP_BEARER_TOKEN=' /root/intent-desk/.env.prod | cut -d= -f2-)
curl -s -H "Authorization: Bearer $TOK" \
  "https://intent.swandigitals.com/cron/leads?limit=2" | python3 -m json.tool
```
