"""Every source the dashboard advertises must be one the dashboard can act on.

`collectors.availability()` is what fills the Sources screen, and the screen
prices each row it renders by calling `/api/collect/estimate` and then runs it
through `/api/collect`. Both of those resolve a source name with
`collectors.get()`, which only searches `registry()` — and `availability()`
appends the three discovery sources, which are *not* in the registry.

The result was a screen that listed `eventbrite_organisers`,
`meraevents_organisers` and `townscript_organisers` with a Run button each, and
404'd on all three. It is invisible from the server side: `/api/sources` is a
200, and the estimate call is fired by the UI and swallowed by a `.catch`, so
the only symptom is a row that quotes no price and a button that fails on click.
Discovery is also the part that closes the audience gap, so these are the three
rows least able to afford being dead.

The property is a round trip: advertised implies resolvable. It fails in both
directions — a new collector missing from the registry, or a registry entry that
stops being advertised.
"""

import pytest

from intentdesk.collectors import availability, get as get_collector
from intentdesk.collectors.organisers import DISCOVERY, discovery_class


def _resolvable(name: str) -> bool:
    """Exactly what the two endpoints do to turn a name into something runnable."""
    return get_collector(name) is not None or discovery_class(name) is not None


def test_every_advertised_source_resolves():
    advertised = [s["name"] for s in availability()]
    assert advertised, "availability() returned nothing — the screen would be empty"

    unresolvable = [n for n in advertised if not _resolvable(n)]
    assert not unresolvable, (
        "these sources are listed on the Sources screen but cannot be priced or "
        f"run, so their buttons 404: {unresolvable}"
    )


def test_discovery_sources_are_advertised():
    """The other direction: a discovery source that stops being listed."""
    advertised = {s["name"] for s in availability()}
    for cls in DISCOVERY:
        assert cls.name in advertised, (
            f"{cls.name} is a discovery source but /api/sources does not list it, "
            "so there is no way to trigger it from the dashboard"
        )


def test_advertised_sources_carry_a_priced_action():
    """A row with an `action` is a row the UI will try to price."""
    for src in availability():
        if src["action"] is None:
            continue
        assert src["price"] is not None, (
            f"{src['name']} names action {src['action']!r} but carries no price, "
            "so the button renders without the cost it is supposed to show"
        )


@pytest.mark.parametrize("cls", DISCOVERY, ids=[c.name for c in DISCOVERY])
def test_discovery_class_lookup_round_trips(cls):
    assert discovery_class(cls.name) is cls


def test_discovery_class_rejects_unknown():
    assert discovery_class("not_a_source") is None
