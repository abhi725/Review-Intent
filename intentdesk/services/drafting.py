"""Outreach drafting and complaint analysis.

Both go through `intentdesk.llm`, so the provider (OpenAI or Claude) is a
configuration choice rather than something baked into the prompt code.

The drafting rule that matters most is negative: the draft never references the
signal that surfaced the lead. Quoting someone's review back at them is both
unsettling to receive and, where the reviewer is identifiable, a use of their
words they did not agree to. The draft speaks to the industry problem instead.
"""

from intentdesk import db, llm
from intentdesk.services import leads, preferences

COMPLAINT_CATEGORIES = [
    "pricing_increase", "high_fees", "slow_support", "complex_setup",
    "missing_feature", "reliability", "poor_integrations", "billing_dispute",
]

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": COMPLAINT_CATEGORIES},
        "core_complaint": {"type": "string"},
        "severity": {"type": "integer"},
        "company_name": {"type": ["string", "null"]},
    },
    "required": ["category", "core_complaint", "severity", "company_name"],
    "additionalProperties": False,
}

ANALYSIS_SYSTEM = (
    "You classify complaints about helpdesk software from public reviews and "
    "forum posts. Return the single best-fitting category, a one-sentence "
    "statement of the underlying complaint, a severity from 1 to 5, and the "
    "reviewer's employer if — and only if — it is named outright in the text. "
    "Never infer or guess an employer from industry, job title, or writing "
    "style; return null instead. A wrong company name means contacting a "
    "business about a complaint it never made."
)

DRAFT_SYSTEM = (
    "You write short cold outreach emails from an Indian SME software vendor to "
    "companies running a competitor's helpdesk.\n\n"
    "Hard rules:\n"
    "- Never mention, quote, or allude to any review, forum post, job listing "
    "or other signal. Write as though you had never seen one.\n"
    "- Speak to the industry problem, not to the individual's grievance.\n"
    "- 90 words maximum. No preamble, no sign-off, no placeholder brackets.\n"
    "- Plain, concrete language. No hype, no exclamation marks, no emoji.\n"
    "- Close with one low-friction question, not a hard ask for a meeting.\n\n"
    "Return the email body only, with no subject line and no commentary."
)

SUBJECT_SYSTEM = (
    "Write one email subject line of at most 8 words for the message provided. "
    "Concrete and specific; no colons, no title case, no clickbait. "
    "Return the subject line only."
)


async def analyse(text: str) -> dict:
    """Classify a complaint. Raises llm.LLMError when no provider is usable."""
    return llm.complete_json(
        ANALYSIS_SYSTEM, f"Review or post:\n\n{text[:4000]}", ANALYSIS_SCHEMA
    )


async def draft_for_lead(lead_id: int) -> dict:
    """Generate and persist a draft for one lead."""
    lead = await leads.get_lead(lead_id)
    if lead is None:
        raise ValueError(f"no lead with id {lead_id}")

    if await db.fetchval("SELECT 1 FROM suppression WHERE domain = $1", lead["domain"]):
        raise ValueError(f"{lead['domain']} is suppressed — refusing to draft")

    prefs = await preferences.all_prefs()

    # Only non-identifying facts reach the prompt: what they run, roughly how
    # big they are, where they are. No quotes, no signal detail.
    context = "\n".join(
        [
            f"Company: {lead['company']}",
            f"City: {lead.get('city') or 'unknown'}",
            f"Currently runs: {lead['vendor']}",
            f"Support team size: {lead.get('agents_est') or 'unknown'} agents",
            f"Recipient role: {lead.get('contact_title') or 'unknown'}",
            f"What we sell: {prefs['value_proposition']}",
        ]
    )

    body = llm.complete(DRAFT_SYSTEM, context, max_tokens=600)
    subject = llm.complete(SUBJECT_SYSTEM, body, max_tokens=120)
    subject = subject.strip().strip('"').splitlines()[0][:120]

    return await leads.update_draft(lead_id, subject=subject, body=body)


async def draft_pending(limit: int = 10) -> dict:
    """Draft for contactable leads that do not have one yet, best-effort."""
    rows = await db.fetch(
        """
        SELECT l.id FROM leads l
        WHERE l.status = 'NEW'
          AND l.contact_email IS NOT NULL
          AND (l.draft_body IS NULL OR l.draft_body = '')
        ORDER BY l.score DESC
        LIMIT $1
        """,
        limit,
    )

    drafted, errors = 0, []
    for row in rows:
        try:
            await draft_for_lead(row["id"])
            drafted += 1
        except (llm.LLMError, ValueError) as exc:
            errors.append(f"lead {row['id']}: {exc}")

    return {
        "candidates": len(rows),
        "drafted": drafted,
        "errors": errors[:10],
        "provider": llm.status()["active"],
    }
