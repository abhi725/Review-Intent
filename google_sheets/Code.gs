/**
 * Intent Desk -> Google Sheets. No Google credentials, no deployment.
 *
 * This script lives inside the spreadsheet and runs *as you*. It already has
 * permission to write to the sheet, because it is the sheet. There is no client
 * ID, no consent screen, no service account, no key file, and nothing to deploy.
 * "API executable" and web-app deployments are for calling a script from
 * outside; the Run button and a time trigger need neither.
 *
 * Setup:
 *   1. In the spreadsheet: Extensions -> Apps Script
 *   2. Select all of Code.gs and paste this over it
 *   3. Run `intentDeskDiagnose` and read the log
 *   4. Run `intentDeskInstallTrigger` once to repeat every 6 hours
 *
 * Written defensively in two specific ways, because Apps Script reports most
 * failures as "An unknown error has occurred, please try again later", which
 * names neither the stage nor the line:
 *
 * **ES5 only — `var`, no `const`/`let`, no arrow functions, no template
 * literals.** A project on the legacy Rhino runtime rejects `const` outright,
 * and a syntax error at load time is one of the things that surfaces as that
 * generic message rather than as a syntax error. `var` also *may be redeclared*,
 * so pasting this alongside older code cannot produce a duplicate-declaration
 * failure — which `const` would, because every .gs file in a project shares one
 * global scope.
 *
 * **Every name is prefixed.** Two files declaring `TOKEN` or `syncLeads` collide
 * in that shared scope, and nothing in the editor points at the collision.
 */

// ---------------------------------------------------------------- configuration
// Function-scoped rather than global: a global cannot collide with anything if it
// does not exist.
function intentDeskConfig_() {
  return {
    apiUrl: 'https://intent.swandigitals.com/cron/leads',

    // MCP_BEARER_TOKEN from /root/intent-desk/.env.prod. It stays inside your own
    // Apps Script project, which only you can read.
    token: 'PASTE_MCP_BEARER_TOKEN_HERE',

    // By ID rather than getActiveSpreadsheet(), which returns null in a
    // standalone script project -- one created at script.google.com instead of
    // from Extensions -> Apps Script inside the sheet.
    spreadsheetId: 'REDACTED_SPREADSHEET_ID',

    sheetIndex: 0,

    // The column identifying a lead for its lifetime. Everything else about a
    // lead can change -- score, status, phone, the draft -- so matching on
    // anything else appends a second copy instead of updating the first.
    key: 'id',

    pageSize: 500
  };
}

// ---------------------------------------------------------------------- syncing
function intentDeskSync() {
  var cfg = intentDeskConfig_();
  var rows = intentDeskFetch_(cfg);
  if (!rows.length) {
    Logger.log('no leads returned -- nothing to write');
    return;
  }
  var sheet = intentDeskSheet_(cfg);
  var headers = intentDeskHeaders_(sheet, rows[0]);
  intentDeskUpsert_(cfg, sheet, headers, rows);
  Logger.log('synced %s leads', rows.length);
}

function intentDeskSheet_(cfg) {
  var book = SpreadsheetApp.openById(cfg.spreadsheetId);
  var sheets = book.getSheets();
  if (cfg.sheetIndex >= sheets.length) {
    throw new Error('sheetIndex ' + cfg.sheetIndex + ' but the spreadsheet has '
                    + 'only ' + sheets.length + ' tab(s)');
  }
  return sheets[cfg.sheetIndex];
}

/**
 * Every page, followed to the end.
 *
 * Paged because Cloudflare cuts a request at about 100 seconds and reports it as
 * a failure even when the work succeeded, so one unbounded request would begin
 * failing silently as the queue grew. `has_more` is the endpoint's own signal; a
 * short page is not relied on as a proxy for it.
 */
function intentDeskFetch_(cfg) {
  var out = [];
  var offset = 0;

  while (true) {
    var url = cfg.apiUrl + '?limit=' + cfg.pageSize + '&offset=' + offset;
    var response = UrlFetchApp.fetch(url, {
      method: 'get',
      headers: { Authorization: 'Bearer ' + cfg.token },
      // Without this a non-200 throws with a message that omits the body, which
      // is where the reason actually is.
      muteHttpExceptions: true
    });

    var code = response.getResponseCode();
    if (code === 401) {
      throw new Error('401 from Intent Desk -- the token is wrong or missing. '
                      + 'It is MCP_BEARER_TOKEN from .env.prod.');
    }
    if (code !== 200) {
      throw new Error('Intent Desk returned ' + code + ': '
                      + response.getContentText().slice(0, 300));
    }

    var body = JSON.parse(response.getContentText());
    var page = body.rows || [];
    for (var i = 0; i < page.length; i++) {
      out.push(page[i]);
    }
    if (!body.has_more) {
      return out;
    }

    offset += cfg.pageSize;
    // A runaway guard, not a business rule.
    if (offset > 20000) {
      return out;
    }
  }
}

/**
 * Header row, written from the data rather than hard-coded here.
 *
 * A hard-coded list would be a second place to edit whenever the export changes
 * columns, and when the two disagree the failure is silent: rows land under the
 * wrong headings.
 */
function intentDeskHeaders_(sheet, sample) {
  var wanted = Object.keys(sample);
  var width = sheet.getLastColumn();
  var existing = [];
  if (width) {
    var row = sheet.getRange(1, 1, 1, width).getValues()[0];
    for (var i = 0; i < row.length; i++) {
      if (row[i] !== '' && row[i] !== null) {
        existing.push(row[i]);
      }
    }
  }

  // Compared element by element rather than by joining on a separator. Choosing
  // a separator is how a stray control character got into this file once, and
  // the comparison does not need one: equal length plus equal members is the
  // actual question.
  var unchanged = existing.length === wanted.length;
  if (unchanged) {
    for (var j = 0; j < wanted.length; j++) {
      if (existing[j] !== wanted[j]) {
        unchanged = false;
        break;
      }
    }
  }
  if (unchanged) {
    return existing;
  }

  sheet.getRange(1, 1, 1, wanted.length).setValues([wanted]);
  sheet.getRange(1, 1, 1, wanted.length).setFontWeight('bold');
  sheet.setFrozenRows(1);
  return wanted;
}

/** Update the leads already present, append the ones that are not. */
function intentDeskUpsert_(cfg, sheet, headers, rows) {
  var keyCol = headers.indexOf(cfg.key) + 1;
  if (!keyCol) {
    throw new Error('no "' + cfg.key + '" column -- cannot match rows');
  }

  // Existing keys mapped to their row number, read in one call. Reading per-lead
  // would be one API round trip each and Apps Script would time out.
  var lastRow = sheet.getLastRow();
  var seen = {};
  if (lastRow > 1) {
    var keys = sheet.getRange(2, keyCol, lastRow - 1, 1).getValues();
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i][0];
      if (k !== '' && k !== null) {
        seen[String(k)] = i + 2;
      }
    }
  }

  var appends = [];
  for (var r = 0; r < rows.length; r++) {
    var line = [];
    for (var c = 0; c < headers.length; c++) {
      var v = rows[r][headers[c]];
      line.push(v === undefined || v === null ? '' : v);
    }
    var at = seen[String(rows[r][cfg.key])];
    if (at) {
      sheet.getRange(at, 1, 1, line.length).setValues([line]);
    } else {
      appends.push(line);
    }
  }

  // One write for all new rows rather than one per row.
  if (appends.length) {
    sheet.getRange(sheet.getLastRow() + 1, 1, appends.length, headers.length)
         .setValues(appends);
  }
}

// ------------------------------------------------------------------ diagnostics
/**
 * Run this first. It walks the four things that can independently break and logs
 * each with its interpretation, so one run says which stage is at fault instead
 * of "an unknown error has occurred".
 */
function intentDeskDiagnose() {
  var cfg = intentDeskConfig_();

  Logger.log('--- 0. environment ---');
  Logger.log('runtime supports ES5+; this script is ES5-only so it runs on both');
  if (cfg.token.indexOf('PASTE_') === 0) {
    Logger.log('STOP: the token is still the placeholder. Set cfg.token.');
    return;
  }
  Logger.log('token length: %s', cfg.token.length);

  Logger.log('--- 1. reaching the spreadsheet ---');
  try {
    var book = SpreadsheetApp.openById(cfg.spreadsheetId);
    var names = [];
    var sheets = book.getSheets();
    for (var i = 0; i < sheets.length; i++) {
      names.push(sheets[i].getName());
    }
    Logger.log('OK: "%s", tabs: %s', book.getName(), names.join(', '));
  } catch (e1) {
    Logger.log('FAILED: %s', e1.message);
    Logger.log('-> cannot open the sheet. The ID is wrong, or this Google account '
               + 'has no access to it.');
    return;
  }

  Logger.log('--- 2. calling Intent Desk ---');
  var body;
  try {
    var r = UrlFetchApp.fetch(cfg.apiUrl + '?limit=2&offset=0', {
      method: 'get',
      headers: { Authorization: 'Bearer ' + cfg.token },
      muteHttpExceptions: true
    });
    Logger.log('HTTP %s, %s bytes', r.getResponseCode(),
               r.getContentText().length);
    if (r.getResponseCode() !== 200) {
      Logger.log('body: %s', r.getContentText().slice(0, 300));
      Logger.log('-> 401 means the token is wrong; 403 means Cloudflare refused '
                 + 'the client rather than an auth failure.');
      return;
    }
    body = JSON.parse(r.getContentText());
  } catch (e2) {
    Logger.log('FAILED: %s', e2.message);
    Logger.log('-> if this mentions authorisation, re-run and approve the prompt.');
    return;
  }

  Logger.log('--- 3. reading the payload ---');
  var rows = body.rows || [];
  Logger.log('rows: %s, has_more: %s', rows.length, body.has_more);
  if (!rows.length) {
    Logger.log('-> no rows, so there is nothing to write. Not an error.');
    return;
  }
  Logger.log('columns: %s', Object.keys(rows[0]).join(', '));

  Logger.log('--- 4. writing to the sheet ---');
  try {
    var sheet = intentDeskSheet_(cfg);
    var probe = sheet.getLastRow() + 1;
    sheet.getRange(probe, 1).setValue('diagnose: write test');
    SpreadsheetApp.flush();
    sheet.getRange(probe, 1).clearContent();
    Logger.log('OK: wrote and cleared row %s of "%s"', probe, sheet.getName());
    Logger.log('--- all stages passed; intentDeskSync should work ---');
  } catch (e3) {
    Logger.log('FAILED: %s', e3.message);
    Logger.log('-> the sheet opened but will not accept a write. Check it is not '
               + 'protected and that this account has edit access.');
  }
}

// --------------------------------------------------------------------- schedule
/** Run once. Repeated runs replace the old trigger rather than stacking. */
function intentDeskInstallTrigger() {
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === 'intentDeskSync') {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  ScriptApp.newTrigger('intentDeskSync').timeBased().everyHours(6).create();
  Logger.log('installed: intentDeskSync every 6 hours');
}
