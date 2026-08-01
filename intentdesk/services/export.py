"""Queue export.

CSV rather than a Google Sheets API write: it needs no service account, no
extra scope on the login, and Sheets imports it directly (File → Import). The
Sheets sink stays on the roadmap for when a service-account key exists, but
nothing about the workflow has to wait for it.
"""

import csv
import io

from intentdesk.services import leads

COLUMNS = [
    ("company", "Company"),
    ("domain", "Domain"),
    ("city", "City"),
    ("vendor", "Currently runs"),
    ("agents_est", "Agents"),
    ("score", "Score"),
    ("heat", "Heat"),
    ("status", "Status"),
    ("contact_name", "Contact"),
    ("contact_title", "Title"),
    ("contact_email", "Email"),
    ("draft_subject", "Draft subject"),
    ("draft_body", "Draft body"),
]


async def leads_csv(status: str | None = None, heat: str | None = None) -> str:
    rows = await leads.list_leads(heat=heat, status=status, limit=500)

    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([label for _, label in COLUMNS])
    for row in rows:
        writer.writerow([row.get(key, "") if row.get(key) is not None else "" for key, _ in COLUMNS])
    return buf.getvalue()
