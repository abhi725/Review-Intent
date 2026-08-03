"""A company's country must be observed, never assumed.

This was correct-by-construction for one day and then quietly wrong. While
MeraEvents was the only discovery source, every organiser on its sitemap really
was Indian, so writing `country="IN"` at promotion time cost nothing. Adding
Eventbrite — a global platform — made the same line produce false data: on
2026-08-03 "Replay Events" (Milton Keynes) and "The Green Light"
(tgd-light.nl, Roosendaal) were both promoted as `country = IN`.

Two failures had to line up, which is why neither was visible:

The confidence gate could not see it. `apollo_search` reduced a country to
`"IN" if name == "India" else None`, so a *known* foreign country and an
*unknown* one were the same value, and the non-India downgrade in `score()`
never fired on an Apollo hit — the only resolver that runs for free.

Nothing downstream re-checks. The product targets one country, so a wrong
country is not a field somebody notices later; it is a lead that reads as
qualified all the way to the outreach draft.

So the invariant is: three states, and the promoted value is whatever was
actually reported.
"""

import pytest

from intentdesk.services.resolving import is_india, score


# ------------------------------------------------------- the three-state answer


def test_india_is_recognised_by_code_and_by_name():
    assert is_india("IN", None) is True
    assert is_india(None, "India") is True
    assert is_india("in", "india") is True


def test_a_known_foreign_country_is_false_not_unknown():
    """The bug in one line: "Netherlands" used to arrive as None."""
    assert is_india(None, "Netherlands") is False
    assert is_india("NL", None) is False
    assert is_india("GB", "United Kingdom") is False


def test_absent_country_stays_unknown():
    """Unknown must not read as foreign either — most of the queue has no country
    until enrichment runs, and treating those as foreign would stall the
    pipeline on missing data rather than on evidence."""
    assert is_india(None, None) is None
    assert is_india("", "  ") is None


# --------------------------------------------------------------- the gate


def _high_confidence_args(**over):
    """A match good enough to promote on name alone, so the country is the only
    variable under test."""
    args = dict(discovered="Replay Events", matched="Replay Events",
                domain="replayevents.com", country_code=None, wrong_kind=False)
    args.update(over)
    return args


def test_confirmed_foreign_match_is_held_for_review():
    assert score(**_high_confidence_args(country_name="Netherlands")) == "medium"


def test_indian_match_is_promoted():
    assert score(**_high_confidence_args(country_name="India")) == "high"


def test_unknown_country_still_promotes():
    assert score(**_high_confidence_args()) == "high"


def test_foreign_country_from_apollo_name_alone_is_caught():
    """The regression test proper: GMB supplies an ISO code, Apollo supplies only
    a name, and Apollo is the resolver that runs on the free plan. Before this
    fix the name was discarded and this case scored "high"."""
    assert score(**_high_confidence_args(country_code=None,
                                         country_name="United Kingdom")) == "medium"


# ----------------------------------------------------- no invented constants


def test_schema_lets_country_be_unknown():
    """The schema was the deeper half of this bug.

    001 declared `country TEXT NOT NULL DEFAULT 'IN'`, so the assumption was not
    just in the resolver — the column could not represent "unknown", and the
    first honest insert crashed with a NOT NULL violation. 009 drops both. A
    later migration re-adding either would push the assumption back below the
    code, where no amount of care in `resolving.py` can fix it.
    """
    import pathlib
    import re

    migrations = sorted(
        (pathlib.Path(__file__).resolve().parent.parent / "migrations").glob("*.sql")
    )
    text = "\n".join(p.read_text() for p in migrations)
    relaxed = text.index("ALTER COLUMN country DROP NOT NULL")
    after = text[relaxed:]
    assert not re.search(r"ALTER COLUMN country SET (NOT NULL|DEFAULT)", after), (
        "a later migration re-imposes NOT NULL or a default on companies.country"
    )
    assert not re.search(r"country\s+TEXT\s+NOT NULL", after)


def test_promotion_does_not_hardcode_a_country():
    """Reads the source, because the value is written in two places — the company
    row and the install signal — and fixing one and missing the other leaves the
    lead queue and the evidence trail disagreeing about the same company."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "intentdesk" / "services" / "resolving.py"
    body = src.read_text()
    promote = body[body.index("if confidence == \"high\""):]
    for literal in ('country="IN"', 'country="India"'):
        assert literal not in promote, (
            f'{literal} is back in the promotion path — the country must come '
            "from what the resolver reported, or be left unset"
        )
