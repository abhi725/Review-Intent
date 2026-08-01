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


async def count_by_vendor() -> list[dict]:
    return await db.fetch(
        """
        SELECT vendor, count(*) AS companies
        FROM companies GROUP BY vendor ORDER BY companies DESC
        """
    )
