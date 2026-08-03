"""Turn a discovered organiser name into a company we can actually contact.

Order is GMB first, Apollo second, and that order is measured rather than
assumed. Google returns a phone number and a website for small Indian firms
where Apollo returns `phone: None` and an empty `technology_names`. Since
outreach here is phone-first, Google supplies the field that decides whether a
lead is contactable at all, and the website it returns is the input Apollo's
`organizations/enrich` needs anyway.

The part that matters most is what happens when the match is *not* obvious.
Apollo name-matching is fuzzy: "Aad Events" returned "AAD A EVENTS", and
"4moles" returned three results, one of which was a person's name. Writing
those in as fact would mean pitching a business about a platform it never used.
So anything short of confident is held in `needs_review` for a human, and only
`high` is promoted automatically.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from intentdesk import db
from intentdesk.collectors.gmb import GmbLookup, domain_of
from intentdesk.config import settings
from intentdesk.services import companies, scoring, signals

log = logging.getLogger(__name__)

APOLLO = "https://api.apollo.io/api/v1"

# Words that carry no identifying weight when comparing two company names.
NOISE = {
    "the", "and", "co", "company", "pvt", "private", "ltd", "limited", "llp",
    "inc", "corp", "corporation", "events", "event", "productions", "production",
    "entertainment", "group", "india", "organization", "organisation", "org",
    "foundation", "society", "association", "club", "studio", "studios",
}


def normalise(name: str) -> str:
    name = re.sub(r"[^\w\s]", " ", (name or "").lower())
    return re.sub(r"\s+", " ", name).strip()


def tokens(name: str) -> set[str]:
    return {t for t in normalise(name).split() if t and t not in NOISE}


def name_similarity(a: str, b: str) -> float:
    """Jaccard over meaningful tokens.

    Deliberately not fuzzy string distance: "Aad Events" and "AAD A EVENTS"
    are close by edit distance and are *not* obviously the same company, which
    is exactly the case that must not auto-resolve.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def score(discovered: str, matched: str, domain: Optional[str],
          country_code: Optional[str], wrong_kind: bool = False) -> str:
    """high -> promote automatically. medium -> hold. low -> do not spend more.

    A domain is required for `high` at all: without one there is nothing to
    promote, since `companies.domain` is NOT NULL.
    """
    if not domain or wrong_kind:
        return "low"

    sim = name_similarity(discovered, matched)

    # A company's own domain is better evidence than its trading name. Real
    # case: "4moles" resolves to "4moles.com - Let's Golf! 🏌️", where the
    # taglines drag token similarity down to 0.2 while the domain says plainly
    # that this is the right company.
    #
    # `all`, not `any`: one shared token out of several is how "Sunburn Events"
    # would match sunburn-unrelated.com. Short tokens are excluded because a
    # three-letter fragment lands inside too many domains by chance, and the
    # empty-set guard stops a name made entirely of short or noise words —
    # "Aad Events" — from vacuously satisfying `all`.
    stem = re.sub(r"\..*$", "", domain).replace("-", "")
    strong = [t for t in tokens(discovered) if len(t) > 3]
    name_is_the_domain = bool(strong) and all(t in stem for t in strong)
    in_domain = any(t in stem for t in strong)

    if sim >= 0.6 or name_is_the_domain:
        # India-first product. A non-IN match on an Indian organiser is more
        # likely a same-name company elsewhere than the business we want.
        if country_code and country_code.upper() not in ("IN", ""):
            return "medium"
        return "high"
    if sim >= 0.34 or in_domain:
        return "medium"
    return "low"


async def apollo_search(name: str) -> Optional[dict]:
    """Apollo `organizations/search` — works on the FREE plan and does
    name -> domain. (`mixed_companies/search` is a hard 403 there; the two are
    easy to confuse and only one of them is usable.)"""
    if not settings.apollo_api_key:
        return None
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-api-key": settings.apollo_api_key,
        "accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{APOLLO}/organizations/search",
                headers=headers,
                json={"q_organization_name": name, "page": 1, "per_page": 3},
            )
        if r.status_code != 200:
            log.warning("apollo organizations/search %s for %r", r.status_code, name)
            return None
        orgs = r.json().get("organizations") or []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("apollo search failed for %r: %s", name, exc)
        return None

    best, best_sim = None, -1.0
    for org in orgs:
        sim = name_similarity(name, org.get("name") or "")
        if sim > best_sim:
            best, best_sim = org, sim
    if not best:
        return None
    return {
        "matched_name": best.get("name"),
        "domain": domain_of(best.get("website_url")) or best.get("primary_domain"),
        "phone": best.get("phone"),
        "city": best.get("city"),
        "country_code": "IN" if (best.get("country") or "") == "India" else None,
        "category": best.get("industry"),
        "employees": best.get("estimated_num_employees"),
        "address": None,
        "wrong_kind": False,
    }


async def resolve_batch(limit: int = 25, use_gmb: bool = True) -> dict:
    """Resolve a batch of pending organisers.

    Batched and resumable on purpose: there are ~7,273 of these, Apollo's
    free-tier rate limit is untested, and a run that dies half way must not
    have to start again. Every row is marked before the next batch begins.
    """
    pending = await db.fetch(
        """
        SELECT id, name, platform, source, city, profile_url
        FROM organisers
        WHERE status = 'pending'
        ORDER BY discovered_at
        LIMIT $1
        """,
        limit,
    )
    if not pending:
        return {"resolved": 0, "needs_review": 0, "unresolved": 0,
                "promoted": 0, "cost_usd": 0.0, "remaining": 0}

    gmb_by_query: dict[str, dict] = {}
    cost = 0.0

    if use_gmb and settings.apify_token:
        # City qualifies the search: "9 Blocks Photography" alone is ambiguous,
        # "9 Blocks Photography Hyderabad" is not.
        queries = [f"{r['name']} {r['city']}".strip() if r["city"] else r["name"]
                   for r in pending]
        try:
            items, cost = await GmbLookup().lookup(queries)
            for item in items:
                parsed = GmbLookup.parse(item)
                key = (item.get("searchString") or parsed.get("matched_name") or "")
                gmb_by_query[key.lower()] = parsed
        except (httpx.HTTPError, RuntimeError) as exc:
            # Falling back to Apollo is better than failing the batch, but it
            # must be visible: a silent downgrade means nobody notices that the
            # source supplying every phone number stopped working.
            log.warning("GMB lookup failed, falling back to Apollo: %s", exc)

    stats = {"resolved": 0, "needs_review": 0, "unresolved": 0, "promoted": 0}

    for row in pending:
        query = (f"{row['name']} {row['city']}".strip() if row["city"] else row["name"])
        hit = gmb_by_query.get(query.lower())
        via = "gmb"

        # Fall back to Apollo when GMB found nothing, or found a place with no
        # website — which is common for small organisers.
        if not hit or not hit.get("domain"):
            apollo = await apollo_search(row["name"])
            if apollo and apollo.get("domain"):
                # Keep the phone GMB found even when Apollo supplies the domain.
                phone = (hit or {}).get("phone") or apollo.get("phone")
                hit = {**apollo, "phone": phone}
                via = "apollo" if not (hit or {}).get("address") else "gmb+apollo"

        if not hit:
            await db.execute(
                "UPDATE organisers SET status='needs_review', resolve_confidence='low',"
                " resolve_cost_usd=$2, resolved_at=now(), updated_at=now() WHERE id=$1",
                row["id"], round(cost / max(len(pending), 1), 5),
            )
            stats["unresolved"] += 1
            continue

        confidence = score(
            row["name"], hit.get("matched_name") or "", hit.get("domain"),
            hit.get("country_code"), hit.get("wrong_kind", False),
        )

        company_id = None
        if confidence == "high":
            company = await companies.upsert(
                name=row["name"],
                domain=hit["domain"],
                vendor=row["platform"],
                city=hit.get("city") or row["city"],
                country="IN",
            )
            company_id = company["id"]
            # Phone is the whole point on this channel; write it if we have one
            # and the company row does not.
            await db.execute(
                "UPDATE companies SET phone = coalesce(phone, $2),"
                " discovered_via = coalesce(discovered_via, $3),"
                " match_confidence = $4 WHERE id = $1",
                company_id, hit.get("phone"), row["source"], confidence,
            )

            # The discovery is itself a signal, and recording it is what makes
            # the company reachable at all: `scan.rescore()` skips any company
            # with no signals, so without this a promoted organiser would sit in
            # `companies` forever and never enter the lead queue.
            #
            # It is also true rather than synthetic — an entry on MeraEvents'
            # own organiser sitemap is evidence that this company runs
            # MeraEvents, which is precisely what an `install` signal means.
            await signals.record(
                kind="install",
                source=row["source"],
                source_id=f"{row['source']}:{row['id']}",
                observed_at=datetime.now(timezone.utc),
                company_id=company_id,
                quote=f"Listed as an organiser on {row['platform']}",
                raw_text=(f"{row['name']} appears on the public {row['platform']} "
                          f"organiser listing at {row['profile_url']}"),
                weight=scoring.WEIGHTS.get("install", 0),
                matched_confidence=1.0,
                url=row["profile_url"],
                platform=row["platform"],
                source_site=row["source"],
                country="India",
            )
            stats["promoted"] += 1

        await db.execute(
            """
            UPDATE organisers SET
                resolved_domain    = $2,
                resolved_phone     = $3,
                resolved_address   = $4,
                resolved_category  = $5,
                resolve_source     = $6,
                resolve_confidence = $7,
                resolve_cost_usd   = $8,
                resolved_at        = now(),
                updated_at         = now(),
                company_id         = $9,
                status             = CASE WHEN $7 = 'high' THEN 'resolved'
                                          ELSE 'needs_review' END
            WHERE id = $1
            """,
            row["id"], hit.get("domain"), hit.get("phone"), hit.get("address"),
            hit.get("category"), via, confidence,
            round(cost / max(len(pending), 1), 5), company_id,
        )
        stats["resolved" if confidence == "high" else "needs_review"] += 1

    if cost:
        await db.execute(
            """
            INSERT INTO spend (day, provider, amount_usd)
            VALUES (current_date, 'gmb', $1)
            ON CONFLICT (day, provider) DO UPDATE
                SET amount_usd = spend.amount_usd + EXCLUDED.amount_usd
            """,
            cost,
        )

    remaining = await db.fetchval(
        "SELECT count(*) FROM organisers WHERE status = 'pending'"
    )
    return {**stats, "cost_usd": round(cost, 5), "remaining": int(remaining or 0)}


async def queue_stats() -> dict:
    rows = await db.fetch(
        "SELECT status, count(*) AS n, coalesce(sum(resolve_cost_usd),0) AS spent "
        "FROM organisers GROUP BY status"
    )
    return {
        "by_status": {r["status"]: int(r["n"]) for r in rows},
        "spent_usd": round(float(sum(float(r["spent"]) for r in rows)), 4),
    }
