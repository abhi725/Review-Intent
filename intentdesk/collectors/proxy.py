"""Apify residential proxy — the one place that knows how it is addressed.

Three sources are blocked for the same reason and are unblocked by the same
thing. Capterra returns 403 to the actor's datacenter proxies; TrustRadius and
SoftwareSuggest return 403 to this VM's datacenter IP, on their own robots.txt.
A residential exit fixes all three, and it is the only thing that does.

Two facts worth not rediscovering, both measured against the live API on
2026-08-03:

* **The proxy password is not the API token.** Authenticating with the token
  gets `407 CONNECT tunnel failed`. Apify issues a separate password, readable
  at `GET /v2/users/me` -> `data.proxy.password`.
* **A free plan cannot use it at all.** With the correct password the free
  account gets `403` on every group, including the datacenter group its own
  `availableProxyGroups` lists. So this is not a code path that can be tested
  into working — it needs the paid plan first, and until then the collectors
  must keep saying they are blocked rather than pretending to be ready.

Two shapes are needed because the two routes differ: our own HTTP client fetches
TrustRadius and SoftwareSuggest directly and wants a proxy URL, while Capterra
runs inside an actor on Apify's infrastructure and wants a `proxyConfiguration`
object in its input.
"""

from typing import Optional

from intentdesk.config import settings

# Apify's proxy endpoint. `groups-RESIDENTIAL` selects the residential pool;
# `country-XX` could be appended per source later, but every brand here is
# scraped globally so pinning a country would only shrink the pool.
PROXY_HOST = "proxy.apify.com"
PROXY_PORT = 8000
RESIDENTIAL_GROUP = "RESIDENTIAL"

# What to tell the user when a source is blocked purely on this. Written once so
# the three collectors cannot drift into three different explanations.
NEEDS_PROXY = (
    "needs the Apify residential proxy — set APIFY_RESIDENTIAL_PROXY=true and "
    "APIFY_PROXY_PASSWORD (a PAID Apify plan; a free plan is refused with 403)"
)


def enabled() -> bool:
    """True only when both the switch and the credential are present.

    Both, deliberately: the flag alone would send every request to a proxy that
    refuses it, turning a clear "blocked" into a run that fails halfway.
    """
    return bool(settings.apify_residential_proxy and settings.apify_proxy_password)


def url() -> Optional[str]:
    """Proxy URL for httpx, or None when the proxy is not configured."""
    if not enabled():
        return None
    return (
        f"http://groups-{RESIDENTIAL_GROUP}:{settings.apify_proxy_password}"
        f"@{PROXY_HOST}:{PROXY_PORT}"
    )


def actor_configuration() -> Optional[dict]:
    """`proxyConfiguration` for an Apify actor input, or None.

    Actors run on Apify's own infrastructure, so they take the group by name and
    never see the password.
    """
    if not enabled():
        return None
    return {"useApifyProxy": True, "apifyProxyGroups": [RESIDENTIAL_GROUP]}
