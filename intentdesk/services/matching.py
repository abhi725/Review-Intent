"""Tying a signal to a company.

A review or forum post rarely names a domain, so matching is the step that
decides whether a complaint becomes a lead or stays an anonymous data point.
Being wrong here is expensive — a false match means emailing the wrong company
about a complaint they never made — so anything below a confident match is left
deliberately unmatched.
"""

import re

from intentdesk import db

_SUFFIXES = {
    "pvt", "private", "ltd", "limited", "llp", "inc", "incorporated", "corp",
    "corporation", "co", "company", "plc", "gmbh", "bv", "sa", "srl", "technologies",
    "technology", "tech", "solutions", "services", "systems", "group", "holdings",
    "india", "global", "international",
}


def normalize_name(name: str) -> str:
    """Strip punctuation and corporate boilerplate so 'Acme Retail Pvt. Ltd.'
    and 'Acme Retail' compare equal."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    words = [w for w in cleaned.split() if w and w not in _SUFFIXES]
    return " ".join(words)


def normalize_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    return re.sub(r"^www\.", "", d)


async def resolve(
    company_name: str | None = None, company_domain: str | None = None
) -> tuple[int | None, float]:
    """Return (company_id, confidence).

    A domain is treated as definitive. A name match is only accepted when
    exactly one company normalizes to it — an ambiguous name is worse than no
    match at all, so ties resolve to unmatched.
    """
    if company_domain:
        row = await db.fetchrow(
            "SELECT id FROM companies WHERE domain = $1", normalize_domain(company_domain)
        )
        if row:
            return row["id"], 1.0

    if company_name:
        target = normalize_name(company_name)
        if not target:
            return None, 0.0
        rows = await db.fetch("SELECT id, name FROM companies")
        hits = [r["id"] for r in rows if normalize_name(r["name"]) == target]
        if len(hits) == 1:
            return hits[0], 0.8
        if len(hits) > 1:
            return None, 0.0  # ambiguous — refuse rather than guess

    return None, 0.0
