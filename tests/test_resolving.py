"""Name -> domain resolution, and the confidence gate in front of it.

The property under test is negative: a wrong domain must not be promoted. A
promoted row becomes a lead, and a lead becomes a phone call telling a business
we know it runs a platform it has never used. Every case below is taken from a
real Apollo or GMB response recorded on 2026-08-03.
"""

import pytest

from intentdesk.collectors.gmb import domain_of
from intentdesk.services.resolving import name_similarity, normalise, score, tokens


# ------------------------------------------------------------ name matching


def test_noise_words_do_not_create_similarity():
    """Two unrelated firms both called "... Events Pvt Ltd" share only noise.
    Counting it would make every Indian event company a match for every other."""
    assert name_similarity("Sunburn Events Pvt Ltd", "Rangoli Events Pvt Ltd") == 0.0


def test_identical_names_match():
    assert name_similarity("9 Blocks Photography", "9 Blocks Photography") == 1.0


def test_case_and_punctuation_are_ignored():
    assert name_similarity("AACE India", "A.A.C.E. INDIA") < 1.0  # not the same tokens
    assert normalise("A.A.C.E. INDIA") == "a a c e india"


# ---------------------------------------------------------------- the gate


def test_confident_match_is_promoted():
    """Real GMB response: 9 Blocks Photography -> 9blocks.in, India."""
    assert score("9 Blocks Photography", "9 Blocks Photography",
                 "9blocks.in", "IN") == "high"


def test_name_in_domain_rescues_a_rewritten_trading_name():
    """Real: "4moles" -> "4moles.com - Let's Golf!". The names diverge, but the
    organiser's own token is the domain, which is strong corroboration."""
    assert score("4moles", "4moles.com - Let's Golf!", "4moles.com", "IN") == "high"


def test_fuzzy_apollo_match_is_held_not_promoted():
    """Real: "Aad Events" -> "AAD A EVENTS" / aadyaevents.in. Plausible and
    unverified. This is the exact case that must never auto-resolve."""
    assert score("Aad Events", "AAD A EVENTS", "aadyaevents.in", "IN") == "medium"


def test_person_name_result_is_rejected():
    """Real: searching "4moles" also returned "Dinesh Thakur". A person is not
    the company, and nothing about the name suggests otherwise."""
    assert score("9 Blocks Photography", "Dinesh Thakur", "example.in", "IN") == "low"


def test_no_domain_can_never_be_high():
    """companies.domain is NOT NULL — without one there is nothing to promote,
    however good the name match is."""
    assert score("AACE India", "AACE India", None, "IN") == "low"


def test_foreign_match_on_an_indian_organiser_is_held():
    """Real: "4moles.com Thailand" sits alongside the Indian entry. Same name,
    different company, wrong country."""
    assert score("4moles", "4moles.com Thailand", "4moles-th.com", "TH") == "medium"


def test_wrong_kind_of_place_is_rejected():
    """GMB search drifts: "Eventbrite office" returned The Event Group, Denver.
    A category that cannot be an organiser is a rejection regardless of name."""
    assert score("Some Organiser", "Some Organiser", "someorganiser.in", "IN",
                 wrong_kind=True) == "low"


# --------------------------------------------------------------- domain_of


@pytest.mark.parametrize("url,expected", [
    ("https://www.9blocks.in/", "9blocks.in"),
    ("http://www.4moles.com/", "4moles.com"),
    ("https://example.co.in:443/path?x=1", "example.co.in"),
])
def test_domain_is_extracted_and_normalised(url, expected):
    assert domain_of(url) == expected


@pytest.mark.parametrize("url", [
    "https://www.facebook.com/someorganiser",
    "https://instagram.com/someorganiser",
    "https://linktr.ee/someorganiser",
    "https://wa.me/919876543210",
])
def test_social_links_are_not_treated_as_a_domain(url):
    """Several unrelated organisers link to Facebook. Keyed on that domain they
    would collapse into one company row, because companies.domain is UNIQUE."""
    assert domain_of(url) is None


@pytest.mark.parametrize("url", [
    "https://www.meraevents.com/o/some-organiser",
    "https://www.townscript.com/e/some-event",
    "https://www.eventbrite.com/o/someone",
])
def test_the_platform_itself_is_not_the_organisers_domain(url):
    """An organiser whose only link is back to the ticketing platform has no
    site of its own. Storing the competitor's domain as the lead's domain would
    put the competitor in our own outreach queue."""
    assert domain_of(url) is None


@pytest.mark.parametrize("url", [None, "", "not-a-url", "https://localhost"])
def test_unusable_urls_yield_nothing(url):
    assert domain_of(url) is None


# ------------------------------------------------------------- spam filter


def test_townscript_pharmacy_spam_is_filtered():
    """Its sitemap carries listings like "best-website-to-shop-lorazepam-
    without-prescription-231403". Each one that survives costs a paid lookup."""
    from intentdesk.collectors.organisers import TownscriptOrganisers

    spam = TownscriptOrganisers.SPAM
    assert spam.search("best-website-to-shop-lorazepam-without-prescription-231403")
    assert spam.search("Buy Xanax Online Overnight")
    assert not spam.search("astronomy-stargazing-event-340313")
    assert not spam.search("Sunburn Arena ft. Martin Garrix")


def test_meraevents_title_suffix_is_stripped():
    """Titles arrive as "AACE India's organization Events & Tickets |
    MeraEvents". The suffix is boilerplate on all 7,273 and would otherwise be
    sent to a paid lookup as part of the company name."""
    from intentdesk.collectors.organisers import MeraEventsOrganisers

    clean = MeraEventsOrganisers(limit=1)._clean
    assert clean("AACE India&#x27;s organization Events &amp; Tickets | MeraEvents") \
        == "AACE India"
    assert clean("4moles.com Events &amp; Tickets | MeraEvents") == "4moles.com"
    assert clean("9 Blocks Photography&#x27;s organization Events &amp; Tickets "
                 "| MeraEvents") == "9 Blocks Photography"
