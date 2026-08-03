"""Company enrichment via Apollo.

Scope note, verified against the live API on 2026-08-02: Apollo's **free plan
blocks every person endpoint** — `people/match`, `mixed_people/search` and
`mixed_companies/search` all return 403 "not included in your Free plan and is
not accessible, even with a master key". Only `organizations/enrich` works.

So this cannot produce a named decision maker or an email address. What it does
give is worth having anyway:

- `technology_names`, which reports the ticketing platform a company actually
  runs. That verifies the vendor without a BuiltWith subscription.
- `estimated_num_employees`, which feeds size-band scoring far better than
  hand-entered counts from a CSV import.
- A company phone number — a real channel for a voice product, even with no
  email address.

Person-level contacts need a paid Apollo plan.
"""

from datetime import datetime, timezone
from typing import Optional

import httpx

from intentdesk import db
from intentdesk.config import settings
from intentdesk.market import VENDOR_MARKERS

ENRICH_URL = "https://api.apollo.io/api/v1/organizations/enrich"


class EnrichmentUnavailable(RuntimeError):
    """No usable Apollo credentials."""


def available() -> bool:
    return bool(settings.apollo_api_key)


def detect_vendors(technology_names: list[str]) -> list[str]:
    """Which tracked ticketing platforms appear in Apollo's technology list."""
    lowered = [t.lower() for t in technology_names or []]
    found = []
    for vendor, markers in VENDOR_MARKERS.items():
        if any(any(m in t for m in markers) for t in lowered):
            found.append(vendor)
    return found


async def fetch_organization(domain: str) -> Optional[dict]:
    if not available():
        raise EnrichmentUnavailable("APOLLO_API_KEY is not set")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            ENRICH_URL,
            params={"domain": domain},
            headers={"X-Api-Key": settings.apollo_api_key},
        )

    if response.status_code == 403:
        raise EnrichmentUnavailable(
            "Apollo rejected the request — organization enrichment is not "
            f"available on this plan: {response.text[:160]}"
        )
    if response.status_code == 429:
        raise EnrichmentUnavailable("Apollo rate limited")
    if response.status_code == 422:
        # Apollo answers an exhausted credit balance with 422 and the reason in
        # the body. Reporting only the status turned "your account is out of
        # credits until it resets" into "Apollo returned 422" on the button —
        # which reads as a broken feature rather than a spent allowance, and sent
        # someone looking for a bug that was not there.
        body = response.text or ""
        if "insufficient credits" in body.lower() or "credits" in body.lower():
            raise EnrichmentUnavailable(
                "Apollo enrichment credits are exhausted — the free plan's "
                "allowance resets monthly, or upgrade the Apollo plan. Nothing "
                "is wrong with the connection: earlier calls on this key "
                "succeeded and spent the balance."
            )
        raise EnrichmentUnavailable(f"Apollo rejected the request (422): {body[:200]}")
    if response.status_code != 200:
        raise EnrichmentUnavailable(
            f"Apollo returned {response.status_code}: {response.text[:200]}"
        )

    return (response.json() or {}).get("organization") or None


async def enrich_company(company_id: int) -> dict:
    """Enrich one company in place and report what changed."""
    company = await db.fetchrow(
        "SELECT id, name, domain, vendor FROM companies WHERE id = $1", company_id
    )
    if company is None:
        raise ValueError(f"no company with id {company_id}")

    org = await fetch_organization(company["domain"])
    if org is None:
        await db.execute(
            "UPDATE companies SET enriched_at = $2 WHERE id = $1",
            company_id,
            datetime.now(timezone.utc),
        )
        return {"domain": company["domain"], "found": False}

    vendors = detect_vendors(org.get("technology_names") or [])
    # Only assert verification for the vendor we already believe they run —
    # a company can appear to run several, and overwriting on a partial match
    # would silently retarget the lead.
    verified = company["vendor"] in vendors

    await db.execute(
        """
        UPDATE companies SET
            industry        = COALESCE($2, industry),
            phone           = COALESCE($3, phone),
            linkedin_url    = COALESCE($4, linkedin_url),
            employees_est   = COALESCE($5, employees_est),
            city            = COALESCE($6, city),
            country         = COALESCE($7, country),
            vendor_verified = $8,
            enriched_at     = $9
        WHERE id = $1
        """,
        company_id,
        org.get("industry"),
        org.get("phone"),
        org.get("linkedin_url"),
        org.get("estimated_num_employees"),
        org.get("city"),
        (org.get("country") or "")[:64] or None,
        verified,
        datetime.now(timezone.utc),
    )

    # Push the number onto the live lead as well. The queue reads
    # `leads.contact_phone`, so an enrichment that only updated `companies`
    # produced a reachable company and an unreachable-looking lead.
    if org.get("phone"):
        await db.execute(
            """
            UPDATE leads SET contact_phone = COALESCE(contact_phone, $2),
                             enrich_source = COALESCE(enrich_source, 'apollo')
            WHERE company_id = $1 AND status = ANY($3::text[])
            """,
            company_id,
            org.get("phone"),
            ["NEW", "APPROVED"],
        )

    return {
        "domain": company["domain"],
        "found": True,
        "employees": org.get("estimated_num_employees"),
        "industry": org.get("industry"),
        "phone_found": bool(org.get("phone")),
        "platforms_detected": vendors,
        "vendor_verified": verified,
    }


async def enrich_pending(limit: int = 25) -> dict:
    """Enrich the least-recently-enriched companies, best-effort.

    Stops early on an unavailable-credentials error rather than burning the
    whole batch against a key that cannot work.
    """
    if not available():
        return {"enriched": 0, "skipped": 0, "error": "APOLLO_API_KEY is not set"}

    # Highest-scoring first, not oldest first. Apollo credits are finite and a
    # never-enriched company at score 12 is worth less than a re-check on one at
    # 88; within the same score, the stalest row still wins. Companies with no
    # lead yet sort last rather than being excluded — they are how the queue grows.
    rows = await db.fetch(
        """
        SELECT c.id
        FROM companies c
        LEFT JOIN LATERAL (
            SELECT score FROM leads l
            WHERE l.company_id = c.id AND l.status = ANY($2::text[])
            ORDER BY score DESC LIMIT 1
        ) top ON TRUE
        WHERE c.domain NOT LIKE '%.example'
          AND NOT EXISTS (SELECT 1 FROM suppression x WHERE x.domain = c.domain)
        ORDER BY COALESCE(top.score, -1) DESC,
                 c.enriched_at NULLS FIRST,
                 c.id
        LIMIT $1
        """,
        limit,
        ["NEW", "APPROVED"],
    )

    enriched = found = verified = 0
    errors: list[str] = []
    for row in rows:
        try:
            result = await enrich_company(row["id"])
        except EnrichmentUnavailable as exc:
            errors.append(str(exc))
            break
        except Exception as exc:
            errors.append(f"company {row['id']}: {type(exc).__name__}: {exc}")
            continue
        enriched += 1
        found += bool(result.get("found"))
        verified += bool(result.get("vendor_verified"))

    return {
        "candidates": len(rows),
        "enriched": enriched,
        "found_in_apollo": found,
        "vendor_verified": verified,
        "errors": errors[:5],
    }
