"""The Eventbrite organiser collector.

This collector exists to close the audience gap: every classified complaint we
hold is Eventbrite's, and until now every discovered company ran MeraEvents, so
no lead could reach a pattern-based draft. That makes *name quality* the thing
worth testing. The name is derived from a URL slug rather than a page title, so
it is lossy by construction, and the failure it produces is quiet — a mangled
name resolves to the wrong domain, or to a company that does not exist, and the
lead looks real all the way to the outreach draft.

Nothing here touches the network. The fixtures are real URLs copied from
`organizer_profile_pages00.xml.gz` on 2026-08-03.
"""

import gzip

import httpx
import pytest

from intentdesk.collectors.organisers import EventbriteOrganisers

# Verbatim from the live sitemap.
REAL = [
    "https://www.eventbrite.com/o/bing0121-106164911461",
    "https://www.eventbrite.com/o/meaningful-conversations-flagstaff-107698904771",
    "https://www.eventbrite.com/o/argentine-tango-toronto-by-bulent-amp-lina-dance-school-amp-dance-company-11041193094",
    "https://www.eventbrite.com/o/glambitious-magazine-7562484405",
    "https://www.eventbrite.com/o/shoe-lane-library-city-of-london-libraries-17217910561",
]


@pytest.fixture
def collector():
    return EventbriteOrganisers(limit=10)


# --------------------------------------------------------------- name recovery


def test_trailing_id_is_not_part_of_the_name(collector):
    """The id is 6-12 digits and would otherwise be pasted onto the company name,
    where Apollo would match nothing and the row would look like a bad lead
    rather than a bad parse."""
    assert collector._name_of(REAL[1]) == "Meaningful Conversations Flagstaff"


def test_amp_becomes_an_ampersand(collector):
    """Eventbrite slugifies "&" to the bare word "amp". Left alone, every
    two-part company name reads as "Bulent Amp Lina"."""
    name = collector._name_of(REAL[2])
    assert "Amp" not in name
    assert "Bulent & Lina" in name


def test_multiword_names_with_digits_survive(collector):
    """The junk filter targets single-token handles. A real company can contain a
    number — "9 Blocks Photography" is already in this database — and filtering
    on "contains a digit" would drop it."""
    assert collector._name_of(
        "https://www.eventbrite.com/o/9-blocks-photography-12345678901"
    ) == "9 Blocks Photography"


def test_bare_handle_is_rejected(collector):
    """"bing0121" is somebody's account name. It resolves to nothing, but it
    resolves *quietly* — a row in the queue with no domain looks the same as a
    company whose website we failed to find."""
    assert collector._name_of(REAL[0]) is None


def test_url_without_the_profile_shape_is_rejected(collector):
    """Sitemaps carry more than one page type; only /o/<slug>-<id> is a profile."""
    assert collector._name_of("https://www.eventbrite.com/d/india--mumbai/events/") is None
    assert collector._name_of("https://www.eventbrite.com/e/some-event-123456") is None


# ------------------------------------------------------------------- ordering


def test_hint_does_not_match_diaspora_organisations(collector):
    """Measured against the live sitemap, not hypothetical.

    The first version of the hint used ethnicity and alumni tokens and sorted
    these four to the front of the batch — all US-based, and the carnival is
    Caribbean, matched on "indian" inside "West Indian". They are not Indian SMEs
    and each one consumes a resolution slot that bills.
    """
    for slug in (
        "iit-bay-area-alumni-association",
        "indian-health-center-of-santa-clara-valley",
        "west-indian-american-day-carnival-association",
        "desi-comedy-fest",
    ):
        assert not collector.INDIA_HINT.search(slug), slug


def test_hint_matches_an_in_country_place(collector):
    for slug in ("bengaluru-tech-meetup", "hashtag-hyderabad-entertainment", "goa-food-fest"):
        assert collector.INDIA_HINT.search(slug), slug


def test_india_hint_orders_but_does_not_filter(collector):
    """The market is Indian SMEs and the sitemap has no country field, so the
    hint is a sort key. If it ever becomes a filter, every organiser whose slug
    happens not to name a city is discarded on no evidence."""
    urls = [
        "https://www.eventbrite.com/o/flagstaff-conversations-107698904771",
        "https://www.eventbrite.com/o/bengaluru-tech-meetup-107698904772",
    ]
    urls.sort(key=lambda u: 0 if collector.INDIA_HINT.search(u.lower()) else 1)
    assert "bengaluru" in urls[0]
    assert len(urls) == 2, "ordering must not drop the non-Indian rows"


# -------------------------------------------------------------------- gzip


def test_gzipped_sitemap_is_decompressed(collector):
    payload = b"<urlset><loc>https://www.eventbrite.com/o/a-company-123456</loc></urlset>"
    response = httpx.Response(200, content=gzip.compress(payload))
    assert collector._body(response) == payload


def test_plain_sitemap_is_passed_through(collector):
    """The CDN sometimes decodes the .gz for us. Assuming gzip either way raises
    BadGzipFile and the collector reports zero found — indistinguishable from
    Eventbrite having removed the sitemap."""
    payload = b"<urlset><loc>x</loc></urlset>"
    assert collector._body(httpx.Response(200, content=payload)) == payload


# -------------------------------------------------------------- registration


def test_registered_as_free_and_scheduled():
    """A paid collector on the schedule bills unattended; this one must not be
    marked that way by accident."""
    assert EventbriteOrganisers.cost_model == "free"
    assert EventbriteOrganisers.cadence == "scheduled"


def test_platform_matches_a_tracked_brand():
    """The whole point is that this platform is one we hold complaints about. A
    typo here ("EventBrite") joins to nothing and the gap stays open while
    looking closed."""
    from intentdesk import market

    assert EventbriteOrganisers.platform in [name for name, _sources in market.COMPETITORS]


def test_included_in_discovery():
    from intentdesk.collectors.organisers import DISCOVERY

    assert EventbriteOrganisers in DISCOVERY
