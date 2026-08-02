from typing import Optional

from intentdesk import db


async def upsert(
    name: str,
    domain: str,
    vendor: str,
    city: Optional[str] = None,
    country: str = "IN",
    employee_band: Optional[str] = None,
    agents_est: Optional[int] = None,
) -> dict:
    """Add a detected company or refresh what we know about it.

    `last_seen` moves forward on every detection so we can tell a live install
    from one that quietly churned off the competitor months ago.
    """
    return await db.fetchrow(
        """
        INSERT INTO companies (name, domain, vendor, city, country,
                               employee_band, agents_est)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (domain) DO UPDATE SET
            name          = EXCLUDED.name,
            vendor        = EXCLUDED.vendor,
            city          = COALESCE(EXCLUDED.city, companies.city),
            employee_band = COALESCE(EXCLUDED.employee_band, companies.employee_band),
            agents_est    = COALESCE(EXCLUDED.agents_est, companies.agents_est),
            last_seen     = now()
        RETURNING *
        """,
        name,
        domain.lower().strip(),
        vendor,
        city,
        country,
        employee_band,
        agents_est,
    )


async def get_by_domain(domain: str) -> Optional[dict]:
    return await db.fetchrow(
        "SELECT * FROM companies WHERE domain = $1", domain.lower().strip()
    )


async def is_suppressed(domain: str) -> bool:
    return bool(
        await db.fetchval(
            "SELECT 1 FROM suppression WHERE domain = $1", domain.lower().strip()
        )
    )


async def suppress(domain: str, reason: str) -> None:
    await db.execute(
        """
        INSERT INTO suppression (domain, reason) VALUES ($1, $2)
        ON CONFLICT (domain) DO UPDATE SET reason = EXCLUDED.reason
        """,
        domain.lower().strip(),
        reason,
    )


async def suppress_bulk(domains: list[str], reason: str = "bulk upload") -> dict:
    """Suppress many domains at once.

    Built for the list a salesperson already has — existing customers, live
    deals, anyone who has asked not to be contacted. One domain at a time meant
    that list never got loaded, which is the failure mode worth designing out:
    an unenforced do-not-contact list is worse than none, because everyone
    believes it is being honoured.

    Accepts bare domains, URLs and email addresses, since a pasted list is never
    uniform. Returns what it could not parse rather than dropping it silently.
    """
    from intentdesk.services.matching import normalize_domain

    cleaned: list[str] = []
    rejected: list[str] = []

    for raw in domains:
        candidate = (raw or "").strip()
        if not candidate or candidate.startswith("#"):
            continue
        if "@" in candidate:
            candidate = candidate.rsplit("@", 1)[-1]
        candidate = normalize_domain(candidate)
        # A value with no dot is a company name, not a domain. Suppressing it
        # would match nothing and read as protection that is not there.
        if "." not in candidate or " " in candidate:
            rejected.append(raw.strip())
            continue
        cleaned.append(candidate)

    unique = sorted(set(cleaned))
    if unique:
        await db.execute(
            """
            INSERT INTO suppression (domain, reason)
            SELECT unnest($1::text[]), $2
            ON CONFLICT (domain) DO UPDATE SET reason = EXCLUDED.reason
            """,
            unique,
            reason,
        )

    return {
        "submitted": len(domains),
        "suppressed": len(unique),
        "duplicates": len(cleaned) - len(unique),
        "rejected": rejected[:20],
        "rejected_count": len(rejected),
    }


async def count_by_vendor() -> list[dict]:
    return await db.fetch(
        """
        SELECT vendor, count(*) AS companies
        FROM companies GROUP BY vendor ORDER BY companies DESC
        """
    )
