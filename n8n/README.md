# Google Sheets sync

Keeps a Google Sheet in step with the lead queue. Import
`leads_to_google_sheets.json` into n8n, connect your own Google account, and
activate it.

## Why it reads `/cron/leads` and not `/api/leads`

Every `/api/*` route is gated on a browser session cookie, so n8n has nothing to
present and gets a 401. `/cron/leads` is on the bearer-authed cron router
instead. It is read-only — it returns stored rows and collects nothing, so it
costs nothing to call and is safe on a schedule.

## Wiring it up

**1. Import.** n8n → *Workflows* → *Import from File* → pick
`leads_to_google_sheets.json`. Import rather than a restart on purpose: this n8n
runs 13 other production workflows and restarting it interrupts all of them.

**2. Set the bearer token.** Open the *Fetch leads* node and replace
`REPLACE_WITH_MCP_BEARER_TOKEN` in the `Authorization` header with:

```
Bearer <the MCP_BEARER_TOKEN value from /root/intent-desk/.env.prod>
```

The token is deliberately not committed here. Keep the word `Bearer` and the
space before the token.

**3. Create the sheet.** Make a Google Sheet with a tab named `Leads` and paste
this as row 1, exactly — the sync maps incoming fields onto these headers by
name, and a header that does not match arrives as a new column:

```
id	Company	Domain	City	Currently runs	Agents	Score	Heat	Status	Contact	Title	Phone	Email	Industry	Employees	Vendor verified	Draft subject	Draft body	Created
```

**4. Connect your Google account.** Open the *Append or update in Sheets* node,
create a *Google Sheets OAuth2* credential, and sign in. Then set the document:
replace `PASTE_YOUR_SPREADSHEET_ID_HERE` with your spreadsheet's ID — the part of
the URL between `/d/` and `/edit` — or switch the field to *From list* and pick it
once the credential is connected.

**5. Run it once by hand** before activating, so a mistake shows up while you are
watching. Then activate with the toggle.

## What it does

Every 6 hours: pull the queue a page at a time, split the page into one item per
lead, and *append or update* each row in the sheet keyed on `id`.

Keyed on `id` deliberately. A plain append would add a fresh copy of all ~14
leads on every run, and the sheet would be mostly duplicates within a day. With
`id` as the matching column a lead that changes — a draft written, a status moved
to approved, a phone number found by enrichment — updates the row already there.

Paging is handled inside the *Fetch leads* node rather than by a loop: it asks for
500 rows, then re-requests with `offset` advanced until the response says
`has_more: false`. This matters because Cloudflare kills a request at about 100
seconds and reports it as a failed node, so one unbounded request would start
failing the moment the queue outgrew that window — and it would fail *after* the
work succeeded server-side, which is the confusing kind of failure.

## Changing what syncs

The endpoint takes `status` and `heat`. To sync only approved leads, add
`status=APPROVED` as a query parameter on the *Fetch leads* node. To sync only
hot ones, `heat=hot`. The columns come from `export.COLUMNS`, so adding a column
there adds it here — remember to add the header to row 1 of the sheet too.

## Checking it by hand

```bash
TOK=$(grep -E '^MCP_BEARER_TOKEN=' /root/intent-desk/.env.prod | cut -d= -f2-)
curl -s -H "Authorization: Bearer $TOK" \
  "https://intent.swandigitals.com/cron/leads?limit=2" | python3 -m json.tool
```

Without the header it returns 401, which is the check that the route is not open
to anyone who guesses the URL.
