"""Check candidate TrustRadius / SoftwareSuggest slugs before trusting them.

    python -m scripts.verify_review_slugs                 # all candidates
    python -m scripts.verify_review_slugs softwaresuggest # one site

Why this exists as a script rather than as logic inside the collector: the answer
to "is this the right product page?" is a judgement, and it should be made once by
a person and then written down, not re-guessed on every run. `ti.to` matched
Tito-Express — a German printer-ink retailer — and twelve reviews about
undelivered toner were collected as competitor intelligence. That mistake cost
$0.05. Making it here, on a free source, would be worse: it writes another
product's complaints into `signals` under our competitor's name, where nothing
downstream can tell they are wrong.

So this fetches each candidate page and prints what it actually found — the
product name in the page's own structured data, the review count, and the average
rating. Confirm the name matches the brand, then copy the line it prints into
`market.B2B_REVIEW_SLUGS`. Nothing here writes to the database and nothing costs
money.

Expect 403s. Several review sites block this VM's datacenter IP, which is a real
answer: it means the free route is closed for that site and only an actor with
residential proxies would work, which is no longer free.
"""

import asyncio
import sys

import httpx

from intentdesk.collectors.organisers import UA, robots_allows
from intentdesk.collectors.reviews_b2b import (
    SoftwareSuggestCollector,
    TrustRadiusCollector,
    json_ld_blocks,
    reviews_from_json_ld,
)
from intentdesk.market import B2B_SLUG_CANDIDATES

SITES = {
    "trustradius": TrustRadiusCollector(),
    "softwaresuggest": SoftwareSuggestCollector(),
}


def product_name(html: str) -> str | None:
    """The product name the page claims, from its own JSON-LD.

    This is the field to compare against the brand. A page that resolves but
    names a different product is the dangerous case, and it is invisible from the
    URL alone.
    """
    for node in json_ld_blocks(html):
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if {"Product", "SoftwareApplication", "Service"} & set(t for t in types if t):
            if node.get("name"):
                return str(node["name"])
    return None


async def check_one(client: httpx.AsyncClient, site: str, brand: str,
                    slug: str) -> dict:
    coll = SITES[site]
    path = coll.path_template.format(slug=slug)
    url = f"{coll.base}{path}"

    if not await robots_allows(client, coll.base, path):
        return {"site": site, "brand": brand, "slug": slug, "url": url,
                "verdict": "REFUSED", "detail": "robots.txt disallows this path, "
                                                "or would not serve robots.txt"}

    try:
        r = await client.get(url)
    except httpx.HTTPError as exc:
        return {"site": site, "brand": brand, "slug": slug, "url": url,
                "verdict": "UNREACHABLE", "detail": str(exc)}

    if r.status_code == 403:
        return {"site": site, "brand": brand, "slug": slug, "url": url,
                "verdict": "BLOCKED",
                "detail": "403 — this host's IP is blocked; free HTTP route closed"}
    if r.status_code == 404:
        return {"site": site, "brand": brand, "slug": slug, "url": url,
                "verdict": "NOT_FOUND", "detail": "no such product page"}
    if r.status_code != 200:
        return {"site": site, "brand": brand, "slug": slug, "url": url,
                "verdict": "HTTP_" + str(r.status_code), "detail": ""}

    name = product_name(r.text)
    reviews = reviews_from_json_ld(r.text)

    if not name and not reviews:
        return {"site": site, "brand": brand, "slug": slug, "url": url,
                "verdict": "NO_JSON_LD",
                "detail": "page loaded but publishes no schema.org data — the "
                          "parser has nothing to read and an actor would be needed"}

    # Deliberately not an automatic pass. A close name match is what produced the
    # Tito-Express failure, so the script reports and a person decides.
    matches = bool(name) and brand.split()[0].lower() in name.lower()
    return {
        "site": site, "brand": brand, "slug": slug, "url": url,
        "verdict": "CONFIRM" if matches else "MISMATCH?",
        "detail": f"page names {name!r}, {len(reviews)} review(s) in JSON-LD",
    }


async def main() -> None:
    wanted = [a for a in sys.argv[1:] if a in SITES] or list(SITES)

    async with httpx.AsyncClient(
        timeout=30, headers={"User-Agent": UA}, follow_redirects=True
    ) as client:
        for site in wanted:
            candidates = B2B_SLUG_CANDIDATES.get(site, {})
            print(f"\n=== {site} ({len(candidates)} candidates) ===")
            confirmed: dict[str, str] = {}

            for brand, slug in candidates.items():
                result = await check_one(client, site, brand, slug)
                print(f"  [{result['verdict']:<11}] {brand:<16} {slug:<20} "
                      f"{result['detail']}")
                if result["verdict"] == "CONFIRM":
                    confirmed[brand] = slug
                # Polite: one product page at a time, with a pause.
                await asyncio.sleep(1.0)

            if confirmed:
                print(f"\n  Paste into market.B2B_REVIEW_SLUGS[{site!r}] after "
                      f"opening each URL and agreeing:")
                for brand, slug in confirmed.items():
                    print(f'        "{brand}": "{slug}",')
            else:
                print("  nothing confirmed — the free route is closed for this site")


if __name__ == "__main__":
    asyncio.run(main())
