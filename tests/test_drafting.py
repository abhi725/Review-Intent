"""The drafting rules, and the one guarantee that has to hold mechanically.

The interesting test here is not "does it produce text" — it is that **no run of
words from a review can reach the recipient**. That guarantee cannot rest on a
prompt instruction, because a prompt is followed most of the time rather than
always. It rests on the review text never entering the prompt at all, which is a
property of `_complaint_context` and is checkable without an LLM.

So the adversarial test below replaces the model with one that echoes its entire
input back as the draft — the worst-case model, which obeys nothing. If the
guarantee holds against that, it holds against a real one.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from intentdesk import db, llm
from intentdesk.services import drafting, leads, preferences

REVIEW = (
    "Absolutely furious. Our payout was held for six weeks after the show closed "
    "and nobody at support would give us a straight answer about when the money "
    "would land. We had to pay the crew out of our own pocket."
)


class FakeDB:
    def __init__(self, **answers):
        self.answers = answers

    async def fetch(self, sql, *args):
        return self._lookup(sql, [])

    async def fetchrow(self, sql, *args):
        return self._lookup(sql, None)

    async def fetchval(self, sql, *args):
        return self._lookup(sql, None)

    async def execute(self, sql, *args):
        return "UPDATE 1"

    def _lookup(self, sql, default):
        for needle, value in self.answers.items():
            if needle in sql:
                return value
        return default


def _async(value):
    async def run(*a, **kw):
        return value
    return run


# ------------------------------------------------------------ the leak check


def test_shared_ngrams_ignores_ordinary_english():
    """Runs of stopwords collide by chance. Flagging those would make the
    guarantee useless — every draft would trip it and the check would be
    switched off."""
    # One content word in a five-word window is not evidence of anything.
    assert drafting.shared_ngrams("on the day of the", "on the day of the") == set()
    assert not drafting.leaks_source_text(
        "We answer buyer calls on the day of the event.",
        "Nobody replied on the day of the show.",
    )


def test_shared_ngrams_catches_a_real_echo():
    draft = ("Most organisers tell us the payout was held for six weeks after the "
             "show closed, which is a familiar story.")
    assert drafting.leaks_source_text(draft, REVIEW)
    assert "payout was held for six" in " ".join(
        sorted(drafting.shared_ngrams(draft, REVIEW))
    )


def test_a_clean_draft_does_not_trip_the_check():
    draft = ("Most organisers running Explara tell us the wait for settlement after "
             "an event is where their platform costs them time. Worth a look?")
    assert not drafting.leaks_source_text(draft, REVIEW)


# ---------------------------------------------------- the complaint context


def test_platform_pattern_beats_the_company_s_own_review(monkeypatch):
    """The aggregate is preferred: it is a fact about the market rather than about
    the recipient, so it can be said out loud without revealing that we read
    anything."""
    monkeypatch.setattr(
        db, "fetchval",
        FakeDB(**{"GROUP BY category": "payout_delay", "count(*) FROM signals": 14}).fetchval,
    )
    monkeypatch.setattr(db, "fetchrow", FakeDB().fetchrow)

    ctx = asyncio.run(drafting._complaint_context(1, "Explara"))
    assert ctx["basis"] == "platform_pattern"
    assert ctx["category"] == "payout_delay"
    assert ctx["evidence_count"] == 14
    # No per-reviewer sentence on this branch, so there is nothing to leak.
    assert ctx["core_complaint"] is None
    assert "money after the event" in ctx["label"]


def test_own_signal_is_used_only_when_the_platform_has_no_pattern(monkeypatch):
    monkeypatch.setattr(db, "fetchval", FakeDB().fetchval)   # no pattern
    monkeypatch.setattr(db, "fetchrow", FakeDB(**{
        "FROM signals": {"category": "poor_support",
                         "core_complaint": "Support did not respond during the event.",
                         "raw_text": REVIEW},
    }).fetchrow)

    ctx = asyncio.run(drafting._complaint_context(1, "Townscript"))
    assert ctx["basis"] == "own_signal"
    assert ctx["category"] == "poor_support"
    # This summary shares no run of words with the review, so it survives.
    assert ctx["core_complaint"] == "Support did not respond during the event."


def test_a_core_complaint_that_echoes_the_review_is_dropped(monkeypatch):
    """The analyser's summary is a restatement, and a restatement can borrow the
    reviewer's phrasing. Passing that through would put review text into the
    prompt — the one thing the whole rule exists to prevent."""
    monkeypatch.setattr(db, "fetchval", FakeDB().fetchval)
    monkeypatch.setattr(db, "fetchrow", FakeDB(**{
        "FROM signals": {
            "category": "payout_delay",
            # Lifted almost verbatim out of REVIEW.
            "core_complaint": "Their payout was held for six weeks after the show closed.",
            "raw_text": REVIEW,
        },
    }).fetchrow)

    ctx = asyncio.run(drafting._complaint_context(1, "Townscript"))
    assert ctx["category"] == "payout_delay", "the category still comes through"
    assert ctx["core_complaint"] is None, "the echoing sentence must be dropped"


def test_no_complaint_is_reported_rather_than_guessed(monkeypatch):
    monkeypatch.setattr(db, "fetchval", FakeDB().fetchval)
    monkeypatch.setattr(db, "fetchrow", FakeDB().fetchrow)

    ctx = asyncio.run(drafting._complaint_context(1, "MeraEvents"))
    assert ctx["basis"] == "none" and ctx["category"] is None


# ------------------------------------------------------------- end to end


@pytest.fixture
def echoing_llm(monkeypatch):
    """The worst-case model: it ignores every instruction and returns its input.

    If no review text reaches the recipient even here, the guarantee is structural
    rather than a matter of the model behaving.
    """
    class Seen(list):
        """Every prompt sent, not just the last one.

        `draft_for_lead` makes two calls — the body, then the subject line — and
        reading only the final one would have inspected the subject prompt while
        claiming to check the body's rules. Both are checked here, because a leak
        in either reaches the recipient.
        """

        @property
        def systems(self) -> str:
            return "\n".join(c["system"] for c in self)

        @property
        def users(self) -> str:
            return "\n".join(c["user"] for c in self)

    seen = Seen()

    def complete(system, user, **kw):
        seen.append({"system": system, "user": user})
        return f"{system}\n{user}"

    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(llm, "status", lambda: {"active": "stub"})
    return seen


def _install_lead(monkeypatch, complaint_row=None, pattern=None):
    monkeypatch.setattr(leads, "get_lead", _async({
        "id": 7, "company_id": 3, "company": "Kadam Arts Festival",
        "domain": "kadam-arts.example", "city": "Nashik", "vendor": "Explara",
        "employees_est": 20, "agents_est": None, "contact_title": "Festival Director",
    }))
    monkeypatch.setattr(leads, "update_draft",
                        lambda lead_id, subject=None, body=None: _async(
                            {"id": lead_id, "draft_subject": subject,
                             "draft_body": body})())
    monkeypatch.setattr(preferences, "all_prefs", _async({
        "outreach_channel": "email",
        "value_proposition": "AI voice agents that answer ticket buyers on event day",
    }))
    answers = {"FROM suppression": None}
    if pattern:
        answers["GROUP BY category"] = pattern
        answers["count(*) FROM signals"] = 9
    monkeypatch.setattr(db, "fetchval", FakeDB(**answers).fetchval)
    monkeypatch.setattr(
        db, "fetchrow",
        FakeDB(**({"FROM signals": complaint_row} if complaint_row else {})).fetchrow,
    )


def test_the_review_text_never_reaches_the_prompt(monkeypatch, echoing_llm):
    _install_lead(monkeypatch, complaint_row={
        "category": "payout_delay",
        "core_complaint": "Settlement arrives long after the event ends.",
        "raw_text": REVIEW,
    })

    result = asyncio.run(drafting.draft_for_lead(7))

    assert not drafting.leaks_source_text(echoing_llm.users, REVIEW), \
        "review text reached the prompt"
    assert not drafting.leaks_source_text(result["draft_body"], REVIEW), \
        "review text reached the draft"


def test_the_complaint_does_reach_the_prompt(monkeypatch, echoing_llm):
    """The other half of the correction. A draft with no problem in it is the
    generic pitch this change exists to replace, so its absence is a failure and
    not a safe default."""
    _install_lead(monkeypatch, pattern="integration_gaps")

    asyncio.run(drafting.draft_for_lead(7))

    assert "integration_gaps" in echoing_llm.users
    assert "tools they already run" in echoing_llm.users, "the human phrasing"
    assert "Explara" in echoing_llm.users


def test_the_prompt_forbids_attribution_and_requires_the_problem(monkeypatch,
                                                                echoing_llm):
    _install_lead(monkeypatch, pattern="high_fees")
    asyncio.run(drafting.draft_for_lead(7))

    system = echoing_llm.systems
    assert "Address that problem specifically" in system
    assert "never to the reader" in system
    assert "Never quote" in system


def test_a_lead_with_no_signal_says_so_rather_than_inventing_one(monkeypatch,
                                                                 echoing_llm):
    _install_lead(monkeypatch)
    result = asyncio.run(drafting.draft_for_lead(7))

    assert result["complaint_basis"]["basis"] == "none"
    assert "none identified yet" in echoing_llm.users


def test_the_phone_channel_gets_the_spoken_prompt(monkeypatch, echoing_llm):
    _install_lead(monkeypatch, pattern="checkin_problems")
    monkeypatch.setattr(preferences, "all_prefs", _async({
        "outreach_channel": "phone",
        "value_proposition": "AI voice agents",
    }))

    asyncio.run(drafting.draft_for_lead(7))
    assert "switchboard" in echoing_llm.systems
    # The signal rules apply on this channel too — a script read aloud can leak a
    # review just as easily as an email can.
    assert "Never quote" in echoing_llm.systems
