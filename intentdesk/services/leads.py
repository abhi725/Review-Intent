from datetime import datetime, timezone
from typing import Optional

from intentdesk import db

LIVE_STATUSES = ("NEW", "APPROVED")
ALL_STATUSES = ("NEW", "APPROVED", "REJECTED", "SENT")

# What "contactable" means depends on the channel being worked, and that answer
# is needed by drafting, stats and export alike. Defined once here so the three
# cannot disagree about which leads are actionable.
#
# Requires `leads l JOIN companies c` in scope.
CONTACTABLE_SQL = {
    "phone": "(l.contact_phone IS NOT NULL OR c.phone IS NOT NULL)",
    "email": "(l.contact_email IS NOT NULL)",
    "both": ("(l.contact_email IS NOT NULL OR l.contact_phone IS NOT NULL "
             "OR c.phone IS NOT NULL)"),
}


def contactable_predicate(channel: str) -> str:
    """SQL predicate for the configured outreach channel.

    Falls back to `both` rather than raising: an unrecognised channel should
    widen the queue, not silently empty it.
    """
    return CONTACTABLE_SQL.get(channel, CONTACTABLE_SQL["both"])

_LIST_SQL = """
SELECT l.id, l.score, l.heat, l.status, l.created_at,
       l.contact_name, l.contact_title, l.contact_email,
       -- Fall back to the company switchboard: on Apollo's free plan that is
       -- the only number there is, and a lead with no way to reach it is not
       -- a lead. `contact_phone` still wins when someone has entered a direct line.
       COALESCE(l.contact_phone, c.phone) AS contact_phone,
       l.draft_subject, l.draft_body,
       c.id AS company_id, c.name AS company, c.domain, c.city,
       c.vendor, c.agents_est, c.employees_est, c.industry, c.vendor_verified,
       COALESCE((
           SELECT json_agg(json_build_object(
                      'kind', s.kind, 'source', s.source, 'observed_at', s.observed_at)
                  ORDER BY s.observed_at DESC)
           FROM signals s
           WHERE s.company_id = c.id AND s.kind <> 'install'
       ), '[]'::json) AS chips
FROM leads l
JOIN companies c ON c.id = l.company_id
WHERE ($1::text IS NULL OR l.heat = $1)
  AND ($2::text IS NULL OR l.status = $2)
  AND ($3::text IS NULL OR c.city ILIKE $3)
  AND ($4::timestamptz IS NULL OR l.created_at >= $4)
ORDER BY l.score DESC, l.created_at DESC
LIMIT $5 OFFSET $6
"""


async def list_leads(
    heat: Optional[str] = None,
    status: Optional[str] = None,
    city: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """The lead queue. All filters are optional and combine with AND."""
    return await db.fetch(
        _LIST_SQL, heat, status, city, since, min(limit, 500), max(offset, 0)
    )


async def get_lead(lead_id: int) -> Optional[dict]:
    """One lead with its full signal timeline — what the detail panel renders."""
    lead = await db.fetchrow(
        """
        SELECT l.*, c.name AS company, c.domain, c.city, c.country,
               c.vendor, c.agents_est, c.employee_band,
               c.employees_est, c.industry, c.phone AS company_phone,
               c.linkedin_url, c.vendor_verified, c.enriched_at
        FROM leads l
        JOIN companies c ON c.id = l.company_id
        WHERE l.id = $1
        """,
        lead_id,
    )
    if lead is None:
        return None

    # Done here rather than as a second `contact_phone` column in the SELECT:
    # `l.*` already provides one, and two columns of the same name in one query
    # resolve by position in a way that is easy to break and hard to notice.
    lead["contact_phone"] = lead.get("contact_phone") or lead.get("company_phone")

    lead["signals"] = await db.fetch(
        """
        SELECT id, kind, source, observed_at, quote, weight
        FROM signals
        WHERE company_id = $1
        ORDER BY observed_at DESC
        """,
        lead["company_id"],
    )
    return lead


async def set_lead_status(lead_id: int, status: str) -> Optional[dict]:
    """Approve, reject, or mark sent.

    Rejecting suppresses the domain so the company cannot resurface in a later
    scan, and sending suppresses it so we do not contact them twice.
    """
    if status not in ALL_STATUSES:
        raise ValueError(f"status must be one of {ALL_STATUSES}, got {status!r}")

    now = datetime.now(timezone.utc)
    updated = await db.fetchrow(
        """
        UPDATE leads SET status = $2, status_changed_at = $3
        WHERE id = $1
        RETURNING id, company_id, status
        """,
        lead_id,
        status,
        now,
    )
    if updated is None:
        return None

    if status in ("REJECTED", "SENT"):
        reason = "rejected in queue" if status == "REJECTED" else "already contacted"
        await db.execute(
            """
            INSERT INTO suppression (domain, reason)
            SELECT domain, $2 FROM companies WHERE id = $1
            ON CONFLICT (domain) DO NOTHING
            """,
            updated["company_id"],
            reason,
        )

    return await get_lead(lead_id)


async def update_draft(
    lead_id: int, subject: Optional[str] = None, body: Optional[str] = None
) -> Optional[dict]:
    """Persist an edit the rep made in the draft box."""
    await db.execute(
        """
        UPDATE leads
        SET draft_subject = COALESCE($2, draft_subject),
            draft_body    = COALESCE($3, draft_body)
        WHERE id = $1
        """,
        lead_id,
        subject,
        body,
    )
    return await get_lead(lead_id)


async def upsert_lead(company_id: int, score: int, **fields) -> dict:
    """Create or refresh the live lead for a company.

    A company may only hold one live lead at a time (enforced by a partial
    unique index), so a rescan updates the score in place rather than piling up
    duplicates.
    """
    existing = await db.fetchrow(
        "SELECT id FROM leads WHERE company_id = $1 AND status = ANY($2::text[])",
        company_id,
        list(LIVE_STATUSES),
    )
    if existing:
        await db.execute(
            "UPDATE leads SET score = $2 WHERE id = $1", existing["id"], score
        )
        return await get_lead(existing["id"])

    row = await db.fetchrow(
        """
        INSERT INTO leads (company_id, score, contact_name, contact_title,
                           contact_email, contact_linkedin, enrich_source,
                           draft_subject, draft_body)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        RETURNING id
        """,
        company_id,
        score,
        fields.get("contact_name"),
        fields.get("contact_title"),
        fields.get("contact_email"),
        fields.get("contact_linkedin"),
        fields.get("enrich_source"),
        fields.get("draft_subject"),
        fields.get("draft_body"),
    )
    return await get_lead(row["id"])
