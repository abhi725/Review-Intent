"""Outreach drafting and complaint analysis.

Both go through `intentdesk.llm`, so the provider (OpenAI or Claude) is a
configuration choice rather than something baked into the prompt code.

## The correction (Phase B2)

This module previously forbade the draft from referencing the signal *at all*,
and never passed the complaint into the prompt. The intent was right and the
implementation over-shot: with no complaint in the context, the model had nothing
to write about except the value proposition, so every draft came out as the same
generic pitch. The whole pipeline — collect reviews, classify complaints, score
leads — fed a message that could have been written without any of it.

Three settings exist and the middle one is not the target:

    too far   "I saw your 3-star review complaining about integrations"
    before    generic pitch, complaint discarded
    now       "Most organisers your size tell us reporting and integrations
               are where their platform costs them time"

So the complaint now reaches the prompt, and the negative rule is narrowed to
what it was actually protecting: no quoting, no attribution, no hint of having
read anything. What the draft may do — must do — is name the *problem*.

Why that is a real distinction and not a loophole: a complaint category is a
statement about the market ("organisers on this platform struggle with payouts"),
which we are entitled to know and to talk about. A quote is a statement about a
person. `_complaint_context()` below prefers the platform-wide pattern over the
company's own review for exactly this reason — the aggregate is both safer and
more persuasive, because it reads as knowing the industry rather than as knowing
the recipient.
"""

from typing import Optional

from intentdesk import db, llm, market
from intentdesk.services import leads, preferences, signals

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

# The four rules that carry the correction, shared by both channels so email and
# phone cannot drift apart on the part that matters.
#
# Rule 2 is the one doing the work. "Never mention a review" on its own is what
# produced the generic pitch, because it reads as "do not discuss the problem".
# Stated as a separation — the problem is fair game, the source is not — the model
# has something specific to write and still cannot give away that we read
# anything.
_SIGNAL_RULES = (
    "- The context names a problem organisers on their current platform run "
    "into. Address that problem specifically. A message that could have been "
    "sent to any organiser has failed.\n"
    "- Attribute it to the market, never to the reader: \"most organisers "
    "running X tell us...\", not \"you are having trouble with...\". You do not "
    "know anything about this particular company's experience and must not "
    "imply that you do.\n"
    "- Never quote, paraphrase, or reproduce any phrase from a review, forum "
    "post, listing or complaint. Never mention reviews, feedback, ratings, "
    "posts, or 'what people are saying'. Never suggest you have read, seen, "
    "noticed or heard anything about them.\n"
    "- Do not name the reader's current platform's failings as accusations "
    "about the platform; describe the difficulty organisers have, not a verdict "
    "on the vendor.\n"
)

DRAFT_SYSTEM = (
    f"You write short cold outreach emails from an Indian SME software vendor to "
    f"{market.BUYER_ROLE}s running a competitor's {market.PLATFORM_NOUN}.\n\n"
    "Hard rules:\n"
    + _SIGNAL_RULES +
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
    + _SIGNAL_RULES +
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


# --------------------------------------------------------------- leak check
#
# The prompt rules are instructions to a model, which means they are followed
# most of the time rather than always. This is the mechanical check, and it is
# shared with the test suite rather than reimplemented there — a guarantee
# asserted by a test that measures something slightly different is not a
# guarantee.

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "that", "this", "as", "at",
    "by", "from", "we", "our", "you", "your", "they", "their", "i", "my", "not",
}


def _words(text: str) -> list[str]:
    return [w for w in "".join(
        ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in (text or "")
    ).split() if w]


def shared_ngrams(a: str, b: str, n: int = 5) -> set[str]:
    """Word n-grams appearing in both texts.

    Five words is the threshold because shorter runs collide by chance on shared
    vocabulary. A window also has to carry at least two *content* words to count:
    "on the day of the" appears in both a clean draft and the review, and it is
    not a leak — it is English. Requiring one content word was not enough, since
    that phrase has one ("day"), and a check that fires on ordinary sentences is a
    check somebody switches off.
    """
    def grams(text: str) -> set[str]:
        words = _words(text)
        out = set()
        for i in range(len(words) - n + 1):
            window = words[i:i + n]
            if sum(1 for w in window if w not in _STOPWORDS) < 2:
                continue
            out.add(" ".join(window))
        return out

    return grams(a) & grams(b)


def leaks_source_text(draft: str, source_text: str, n: int = 5) -> bool:
    """True when the draft has reproduced a run of words from the review."""
    return bool(shared_ngrams(draft, source_text, n))


async def analyse(text: str) -> dict:
    """Classify a complaint. Raises llm.LLMError when no provider is usable."""
    return llm.complete_json(
        ANALYSIS_SYSTEM, f"Review or post:\n\n{text[:4000]}", ANALYSIS_SCHEMA
    )


async def classify_pending(limit: int = 25) -> dict:
    """Run the analyser over reviews that have no category yet.

    This closes a gap that made the drafter correction inert: `analyse()` and
    `signals.classify()` both existed and **nothing called either of them**, so
    `signals.category` was NULL on every stored row. `_complaint_context()` would
    therefore have found no pattern for any platform and fallen back to the value
    proposition alone — the exact generic pitch the correction set out to replace,
    still generic, but now for a reason nobody would have thought to look for.

    Billed in LLM tokens rather than provider credits, which is why it sits on the
    cron beside drafting instead of behind a paid button: the Apify cap does not
    apply to it and a classification pass over 25 reviews is fractions of a cent.

    Best-effort per row. One malformed review must not stop the batch — the whole
    point is that the next scan finds fewer unclassified rows than the last.
    """
    rows = await db.fetch(
        """
        SELECT id, raw_text, quote
        FROM signals
        WHERE kind IN ('review', 'forum')
          AND category IS NULL
          AND COALESCE(raw_text, quote) IS NOT NULL
          AND length(COALESCE(raw_text, quote)) > 40
        ORDER BY observed_at DESC
        LIMIT $1
        """,
        min(limit, 200),
    )

    done, errors = 0, []
    for row in rows:
        text = row["raw_text"] or row["quote"]
        try:
            verdict = await analyse(text)
        except llm.LLMError as exc:
            # A provider outage affects every row, so there is no value in trying
            # the other twenty-four.
            errors.append(f"signal {row['id']}: {exc}")
            break
        except (KeyError, ValueError) as exc:
            errors.append(f"signal {row['id']}: {exc}")
            continue

        category = verdict.get("category")
        if category not in COMPLAINT_CATEGORIES:
            # Gemini's schema dialect silently degrades to free-form JSON, so an
            # off-enum category is a real possibility rather than defensive
            # paranoia. Recording it as-is would poison the platform pattern that
            # every draft is now written from.
            errors.append(f"signal {row['id']}: category {category!r} is not in the taxonomy")
            continue

        try:
            severity = int(verdict.get("severity") or 3)
        except (TypeError, ValueError):
            severity = 3

        await signals.classify(
            row["id"], category,
            str(verdict.get("core_complaint") or "")[:1000],
            max(1, min(severity, 5)),
        )
        done += 1

    remaining = await db.fetchval(
        """
        SELECT count(*) FROM signals
        WHERE kind IN ('review','forum') AND category IS NULL
          AND COALESCE(raw_text, quote) IS NOT NULL
        """
    )

    return {
        "candidates": len(rows),
        "classified": done,
        "remaining": int(remaining or 0),
        "errors": errors[:10],
        "provider": llm.status()["active"],
    }


async def _complaint_context(company_id: int, vendor: Optional[str]) -> dict:
    """What problem this draft should address, and where that came from.

    Two sources, and the aggregate is deliberately preferred:

    1. **The platform pattern** — the most common complaint category across every
       classified review of the vendor this company runs. This is a fact about the
       market, it is what makes "most organisers running Explara tell us..." true
       rather than a rhetorical device, and it reveals nothing about the
       recipient.
    2. **The company's own signal** — used only when the platform has no
       classified reviews at all. Narrower, and the reason the "market, never the
       reader" rule in the prompt is not optional: this *is* their complaint, and
       the draft must still read as though we had never seen it.

    Returns `category: None` when neither exists, which is the common case for a
    company discovered from a sitemap. The draft then falls back to the value
    proposition alone — the old behaviour, now an honest fallback rather than the
    only path.
    """
    pattern = await db.fetchval(
        """
        SELECT category
        FROM signals
        WHERE platform = $1
          AND category IS NOT NULL
          AND observed_at >= now() - interval '365 days'
        GROUP BY category
        -- Total severity, which is volume and intensity in one number.
        --
        -- Average severity alone was wrong and the live data showed it
        -- immediately: Eventbrite's one severity-3 support complaint outranked
        -- nine severity-2.8 complaints about fees, so every draft would have led
        -- with the rarest thing anyone said. Count alone has the opposite fault —
        -- a pile of mild grumbles about page design would outrank a handful of
        -- outages. The sum settles it: nine × 2.8 beats one × 3.
        ORDER BY sum(COALESCE(severity, 3)) DESC, count(*) DESC
        LIMIT 1
        """,
        vendor,
    ) if vendor else None

    if pattern:
        n = await db.fetchval(
            "SELECT count(*) FROM signals WHERE platform = $1 AND category = $2",
            vendor, pattern,
        )
        return {
            "category": pattern,
            "label": market.COMPLAINT_LABELS.get(pattern, pattern.replace("_", " ")),
            # No per-review sentence on this branch, and that is the point: an
            # aggregate over many reviews has no single reviewer's phrasing to
            # leak. It is the safer of the two bases as well as the more
            # persuasive one.
            "core_complaint": None,
            "basis": "platform_pattern",
            "evidence_count": int(n or 0),
        }

    own = await db.fetchrow(
        """
        SELECT category, core_complaint, raw_text
        FROM signals
        WHERE company_id = $1 AND category IS NOT NULL
        ORDER BY COALESCE(severity, 3) DESC, observed_at DESC
        LIMIT 1
        """,
        company_id,
    )
    if own:
        # `core_complaint` is the analyser's one-sentence restatement, and a
        # restatement can borrow the reviewer's own words. Passing it through
        # unchecked would put a phrase from the review into the prompt, which is
        # the exact thing the draft is forbidden to reproduce — so it is dropped
        # when it shares a run of words with the review it came from.
        summary = own["core_complaint"]
        if summary and leaks_source_text(summary, own["raw_text"] or ""):
            summary = None

        return {
            "category": own["category"],
            "label": market.COMPLAINT_LABELS.get(
                own["category"], own["category"].replace("_", " ")
            ),
            "core_complaint": summary,
            "basis": "own_signal",
            "evidence_count": 1,
        }

    return {"category": None, "label": None, "core_complaint": None,
            "basis": "none", "evidence_count": 0}


async def draft_for_lead(lead_id: int) -> dict:
    """Generate and persist a draft for one lead."""
    lead = await leads.get_lead(lead_id)
    if lead is None:
        raise ValueError(f"no lead with id {lead_id}")

    if await db.fetchval("SELECT 1 FROM suppression WHERE domain = $1", lead["domain"]):
        raise ValueError(f"{lead['domain']} is suppressed — refusing to draft")

    prefs = await preferences.all_prefs()
    channel = str(prefs["outreach_channel"])

    complaint = await _complaint_context(lead["company_id"], lead.get("vendor"))

    # Non-identifying facts, plus the problem to write about. Still no quotes and
    # no signal detail — the complaint arrives as a category and a phrase from our
    # own vocabulary (`market.COMPLAINT_LABELS`), not as anything a reviewer
    # wrote.
    lines = [
        f"Company: {lead['company']}",
        f"City: {lead.get('city') or 'unknown'}",
        f"Currently runs: {lead['vendor']}",
        f"Company size: {lead.get('employees_est') or lead.get('agents_est') or 'unknown'} staff",
        f"Recipient role: {lead.get('contact_title') or 'unknown'}",
        f"What we sell: {prefs['value_proposition']}",
    ]

    if complaint["category"]:
        lines += [
            "",
            f"Problem to address: {complaint['label']}",
            f"Problem category: {complaint['category']}",
        ]
        if complaint.get("core_complaint"):
            lines.append(
                f"In more detail: {complaint['core_complaint']} "
                "(our own summary — do not reuse its wording)"
            )
        if complaint["basis"] == "platform_pattern":
            lines.append(
                f"Basis: this is the most common difficulty organisers on "
                f"{lead['vendor']} report ({complaint['evidence_count']} cases). "
                f"It is a pattern across the platform, NOT something known about "
                f"this company — write it as market knowledge."
            )
        else:
            lines.append(
                "Basis: a single unattributed data point. Write it as a general "
                "industry observation and nothing more."
            )
    else:
        lines += [
            "",
            "Problem to address: none identified yet, so lead with the value "
            "proposition above and keep the message short.",
        ]

    context = "\n".join(lines)

    if channel == "phone":
        body = llm.complete(CALL_SYSTEM, context, max_tokens=400)
        subject = llm.complete(CALL_LABEL_SYSTEM, body, max_tokens=120)
    else:
        body = llm.complete(DRAFT_SYSTEM, context, max_tokens=600)
        subject = llm.complete(SUBJECT_SYSTEM, body, max_tokens=120)

    subject = subject.strip().strip('"').splitlines()[0][:120]

    updated = await leads.update_draft(lead_id, subject=subject, body=body)
    # Returned alongside the lead so a caller — the API, a test, the UI — can see
    # what the draft was written about without re-deriving it. `basis: "none"` is
    # the honest signal that this draft is the generic pitch.
    if updated is not None:
        updated["complaint_basis"] = complaint
    return updated


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
