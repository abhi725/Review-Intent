"""Outreach drafting and complaint analysis.

Both go through `intentdesk.llm`, so the provider (OpenAI or Claude) is a
configuration choice rather than something baked into the prompt code.

The drafting rule that matters most is negative: the draft never references the
signal that surfaced the lead. Quoting someone's review back at them is both
unsettling to receive and, where the reviewer is identifiable, a use of their
words they did not agree to. The draft speaks to the industry problem instead.
"""

from intentdesk import db, llm, market
from intentdesk.services import leads, preferences

COMPLAINT_CATEGORIES = market.COMPLAINT_CATEGORIES

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
    f"You classify complaints about {market.PLATFORM_NOUN}s from public reviews and "
    "forum posts. Return the single best-fitting category, a one-sentence "
    "statement of the underlying complaint, a severity from 1 to 5, and the "
    "reviewer's employer if — and only if — it is named outright in the text. "
    "Never infer or guess an employer from industry, job title, or writing "
    "style; return null instead. A wrong company name means contacting a "
    "business about a complaint it never made."
)

DRAFT_SYSTEM = (
    f"You write short cold outreach emails from an Indian SME software vendor to "
    f"{market.BUYER_ROLE}s running a competitor's {market.PLATFORM_NOUN}.\n\n"
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

# On the phone channel the draft is read aloud, not sent. An email written for
# the eye — paragraphs, a subject line, a closing question in writing — is the
# wrong artifact for someone dialling a switchboard, so the prompt changes with
# the channel rather than the output being repurposed.
CALL_SYSTEM = (
    f"You write opening scripts for a cold phone call from an Indian SME "
    f"software vendor to {market.BUYER_ROLE}s running a competitor's "
    f"{market.PLATFORM_NOUN}.\n\n"
    "Hard rules:\n"
    "- Never mention, quote, or allude to any review, forum post, job listing "
    "or other signal. Speak as though you had never seen one.\n"
    "- This is a switchboard number, so open by asking for the person who runs "
    "ticketing, and assume you may be talking to a receptionist.\n"
    "- 60 words maximum, written to be spoken: short sentences, no clauses "
    "that need a second breath.\n"
    "- Plain language. No hype, no jargon, no reading out a URL.\n"
    "- End with one question that is easy to answer yes or no to.\n\n"
    "Return the spoken script only, with no stage directions and no commentary."
)

CALL_LABEL_SYSTEM = (
    "In at most 8 words, state the reason for the call described. "
    "Plain and factual, as a note for the caller's own screen. "
    "Return the line only."
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
    channel = str(prefs["outreach_channel"])

    # Only non-identifying facts reach the prompt: what they run, roughly how
    # big they are, where they are. No quotes, no signal detail.
    context = "\n".join(
        [
            f"Company: {lead['company']}",
            f"City: {lead.get('city') or 'unknown'}",
            f"Currently runs: {lead['vendor']}",
            f"Company size: {lead.get('employees_est') or lead.get('agents_est') or 'unknown'} staff",
            f"Recipient role: {lead.get('contact_title') or 'unknown'}",
            f"What we sell: {prefs['value_proposition']}",
        ]
    )

    if channel == "phone":
        body = llm.complete(CALL_SYSTEM, context, max_tokens=400)
        subject = llm.complete(CALL_LABEL_SYSTEM, body, max_tokens=120)
    else:
        body = llm.complete(DRAFT_SYSTEM, context, max_tokens=600)
        subject = llm.complete(SUBJECT_SYSTEM, body, max_tokens=120)

    subject = subject.strip().strip('"').splitlines()[0][:120]

    return await leads.update_draft(lead_id, subject=subject, body=body)


async def draft_pending(limit: int = 10) -> dict:
    """Draft for contactable leads that do not have one yet, best-effort.

    "Contactable" follows the configured outreach channel. This used to require
    an email address, which on Apollo's free plan is never populated — so the
    query matched nothing and the whole drafting stage looked broken when it was
    only mis-scoped.
    """
    channel = await preferences.channel()
    rows = await db.fetch(
        f"""
        SELECT l.id FROM leads l
        JOIN companies c ON c.id = l.company_id
        WHERE l.status = 'NEW'
          AND {leads.contactable_predicate(channel)}
          AND (l.draft_body IS NULL OR l.draft_body = '')
          AND NOT EXISTS (SELECT 1 FROM suppression x WHERE x.domain = c.domain)
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
        "channel": channel,
        "errors": errors[:10],
        "provider": llm.status()["active"],
        "generic_pitch": await preferences.value_proposition_is_default(),
    }
