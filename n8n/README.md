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

**3. The target sheet is already set** to document
`REDACTED_SPREADSHEET_ID`, first tab.

The tab is addressed by **gid `0`** rather than by title. `sheetName` has no
"by name" mode — only *From List*, *By URL* and *By ID*, where the ID is the gid —
so a title like `Leads` is not a value this field accepts, and gid 0 is the first
tab whatever it ends up being called.

Row 1 of that sheet was empty when this was wired. `appendOrUpdate` maps fields
onto the header row, so either let the first run write the headers or paste them
yourself to be certain:

```
id	Company	Domain	City	Currently runs	Agents	Score	Heat	Status	Contact	Title	Phone	Email	Industry	Employees	Vendor verified	Draft subject	Draft body	Created
```

**4. Connect Google.** The node is set to **Service Account** authentication, not
OAuth2 — see below for why, and for the OAuth2 route if you prefer it.

### Service account (what this workflow is wired for)

A service account is its own Google identity with its own key. No consent screen,
no test-user list, no redirect URI, and no browser sign-in that can expire — which
is the right shape for something running unattended every 6 hours.

In [Google Cloud Console](https://console.cloud.google.com), in any project:

1. **APIs & Services → Library** → enable **Google Sheets API**.
2. **IAM & Admin → Service Accounts → Create service account**. Any name. No
   roles are needed — project roles govern Google Cloud resources, and a
   spreadsheet is not one. Access comes from step 4.
3. Open it → **Keys → Add key → Create new key → JSON** → download. The file
   contains, among other things:
   ```json
   { "client_email": "something@your-project.iam.gserviceaccount.com",
     "private_key": "-----BEGIN PRIVATE KEY-----\nMII...\n-----END PRIVATE KEY-----\n" }
   ```
4. **Share the spreadsheet with `client_email`, as Editor.** This is the step that
   is easy to miss and it is the one that grants access: the service account is a
   separate identity from you, so your own ownership of the sheet gives it
   nothing. Skipping it produces a 403 that reads like a scope problem.
5. In n8n, on the *Append or update in Sheets* node → **Create new credential** →
   *Google Service Account API*. Two fields:
   - **Service Account Email** ← `client_email`
   - **Private Key** ← `private_key`, pasted whole, including the
     `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----` lines
   Leave *Impersonate a User* off. n8n tests this credential when you save it, so
   a bad paste is reported immediately rather than at the first run.

Note that the *From List* pickers stay empty under a service account — it can only
see files shared with it, and listing goes through Drive. This workflow addresses
the document and tab by ID, so nothing depends on those pickers.

### OAuth2 instead, if you would rather

Switch *Authentication* on the node to *OAuth2*. Self-hosted n8n ships **no Google
app of its own**, which is why "Sign in with Google" does nothing on a fresh
credential — there is no client ID behind the button yet. Supply one:

### Creating the OAuth client

In [Google Cloud Console](https://console.cloud.google.com), in any project:

1. **APIs & Services → Library** — enable **Google Sheets API** and **Google
   Drive API**. Drive is needed as well as Sheets: the *From List* pickers in the
   node list your files through Drive, and without it they come back empty even
   though sign-in succeeded.
2. **APIs & Services → OAuth consent screen** — set it up as *External*. While it
   is in **Testing**, only accounts listed under **Test users** can sign in, so
   **add your own Google address there**. Skipping this is the most common cause
   of a sign-in that opens, asks for permission and then fails with
   "Access blocked".
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: **Web application**
   - **Authorised redirect URI** — exactly this, no trailing slash:
     ```
     https://n8n.swandigitals.com/rest/oauth2-credential/callback
     ```
     A mismatch here is reported by Google as `redirect_uri_mismatch`, and it is
     literal: `http` instead of `https`, or a trailing slash, is a mismatch.
4. Copy the **Client ID** and **Client secret**.

### Putting them into n8n

Open the *Append or update in Sheets* node → **Create new credential** → *Google
Sheets OAuth2 API*. Paste the client ID and secret, save, then click **Sign in
with Google** and pick the account that owns the spreadsheet.

n8n shows its own expected redirect URI at the top of that credential screen. If
it differs from the one above, trust n8n's and put that into Google Cloud —
it is derived from `N8N_EDITOR_BASE_URL`, which is
`https://n8n.swandigitals.com` on this instance.

This n8n has no credentials stored in any of its credential tables, so there is
nothing existing to reuse.

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
