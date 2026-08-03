"""Who wrote this review, when that can be answered honestly.

A review gives a display name and a country. Turning that into a person is an
Apollo `people/match` call, and this is the one place in the system where the
subject is an individual rather than a business. Contacting someone about a
review they wrote is a different act from prospecting a company that appears in a
public sitemap: DPDP and GDPR apply, and the confidence tier is what keeps it on
the right side.

So the tier is enforced, not advisory:

    high    rare name + an employer named in the review + country agrees
            -> usable, auto-draftable
    medium  rare name + country only
            -> stored, held for a human, never auto-drafted
    low     a truncated name, or a common name with no employer
            -> never enriched and never contacted

The important consequence is that `low` is decided **before** any money moves.
`assess()` is free and runs on stored data alone, so the button can be disabled
with the real reason on it rather than taking a payment to discover the answer is
unusable. G2's "Irfan M." is the canonical case: there is no amount of Apollo
credit that turns an initial into a surname.

Honest limit, stated so this is not oversold: only a minority of reviews reach
`high`. "Abi Lupton-Levy" resolves; "Michelle Evans" does not, and pretending
otherwise would mean phoning a stranger about someone else's complaint.
"""

import logging
import re
from typing import Optional

import httpx

from intentdesk import db
from intentdesk.config import settings
from intentdesk.services import spend

log = logging.getLogger(__name__)

APOLLO = "https://api.apollo.io/api/v1"

# Surnames common enough that a name plus a country does not identify one person.
# Deliberately short and deliberately biased towards this market and the two
# review sites in use — a long list would be a research project, and the failure
# mode of a missing entry is a `medium` held for a human rather than a wrong call.
COMMON_SURNAMES = {
    # India
    "kumar", "singh", "sharma", "patel", "shah", "gupta", "verma", "yadav",
    "reddy", "rao", "nair", "menon", "iyer", "das", "roy", "ghosh", "bose",
    "khan", "ali", "ahmed", "hussain", "sheikh", "shaikh", "desai", "joshi",
    "mehta", "agarwal", "aggarwal", "jain", "chauhan", "pandey", "mishra",
    # UK / US / AU, where Trustpilot volume concentrates
    "smith", "jones", "williams", "brown", "taylor", "davies", "wilson",
    "evans", "thomas", "johnson", "roberts", "walker", "white", "green",
    "hall", "wood", "harris", "martin", "clark", "lewis", "young", "king",
    "miller", "davis", "moore", "anderson", "jackson", "lee", "scott",
}

# A trailing initial is Trustpilot's and G2's privacy trim, and it is fatal:
# "Irfan M." has no surname to match on. Matches "M", "M.", "M-" at the end.
_TRAILING_INITIAL = re.compile(r"\b[A-Za-z][.\-]?$")

# Names that are not names. Trustpilot lets people review under a handle.
_NOT_A_NAME = {"anonymous", "anon", "customer", "guest", "user", "a customer",
               "trustpilot user", "private user", "n/a", "unknown"}


def _clean(name: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def name_shape(display_name: Optional[str]) -> dict:
    """What kind of name this is, from the string alone. Free.

    Returns `usable: False` with a reason whenever no amount of paid lookup could
    help — which is the majority of G2 rows and a meaningful slice of Trustpilot.
    """
    name = _clean(display_name)
    lowered = name.lower()

    if not name:
        return {"usable": False, "reason": "the review carries no reviewer name",
                "first": None, "last": None, "rare": False}

    if lowered in _NOT_A_NAME:
        return {"usable": False,
                "reason": f"{name!r} is a placeholder, not a name",
                "first": None, "last": None, "rare": False}

    parts = name.split()

    if len(parts) < 2:
        return {"usable": False,
                "reason": f"{name!r} is a single name with no surname to match on",
                "first": parts[0] if parts else None, "last": None, "rare": False}

    if _TRAILING_INITIAL.search(parts[-1]) and len(parts[-1].rstrip(".-")) == 1:
        return {"usable": False,
                "reason": f"{name!r} has the surname trimmed to an initial — this "
                          "is G2's privacy trim and no lookup can undo it",
                "first": parts[0], "last": None, "rare": False}

    first, last = parts[0], parts[-1]
    surname = last.lower().strip(".")

    # A double-barrelled or hyphenated surname is strong evidence of a rare name;
    # a surname on the common list is strong evidence against.
    hyphenated = "-" in last or len(parts) > 2
    rare = hyphenated or surname not in COMMON_SURNAMES

    return {"usable": True, "reason": None, "first": first, "last": last,
            "rare": rare,
            "why": ("double-barrelled or multi-part surname" if hyphenated
                    else f"{surname!r} is not on the common-surname list" if rare
                    else f"{surname!r} is a common surname")}


def tier(shape: dict, company_name: Optional[str],
         country_matches: Optional[bool]) -> tuple[str, str]:
    """The tier and the sentence explaining it.

    Called twice per resolution — once before spending, on what is known from
    stored data, and once after, with what Apollo returned. Same function both
    times, so the pre-flight prediction and the recorded verdict cannot use
    different rules.
    """
    if not shape["usable"]:
        return "low", shape["reason"]

    if company_name and shape["rare"]:
        if country_matches is False:
            return "medium", ("name and employer line up but the country does not, "
                              "which is how a same-name person elsewhere gets "
                              "mistaken for the reviewer")
        return "high", (f"rare name, employer named in the review ({company_name})"
                        + (", country agrees" if country_matches else ""))

    if shape["rare"]:
        return "medium", ("rare name but no employer named, so the match rests on "
                          "name and country alone — a person should look")

    if company_name:
        return "medium", (f"employer named ({company_name}) but the name is common, "
                          "so several people could be the reviewer")

    return "low", (f"common name and no employer named — {shape.get('why') or ''} "
                   "This cannot be narrowed to one person, so it is not enriched "
                   "and not contacted.").strip()


# --------------------------------------------------------------- pre-flight
async def assess(signal_id: int) -> dict:
    """Can this reviewer be resolved, and what will it cost? Free, no calls.

    This is what the per-row button reads. A `low` verdict here means the control
    renders disabled with the reason on it, which is the difference between
    spending nothing and spending a credit to be told the name was an initial.
    """
    row = await db.fetchrow(
        """
        SELECT s.id, s.author, s.country, s.source_site, s.platform,
               s.company_id, c.name AS matched_company
        FROM signals s
        LEFT JOIN companies c ON c.id = s.company_id
        WHERE s.id = $1
        """,
        signal_id,
    )
    if row is None:
        raise ValueError(f"no signal with id {signal_id}")

    cached = await db.fetchrow(
        "SELECT * FROM reviewer_identity WHERE signal_id = $1", signal_id
    )

    shape = name_shape(row["author"])
    predicted, reason = tier(shape, row["matched_company"], None)
    est = spend.estimate("enrich_reviewer", 1)

    # The plan gate comes first, because it outranks everything the name can say.
    # Apollo's person endpoints answer 403 on the free plan — measured, not
    # assumed — so a perfectly resolvable name is still unresolvable, and a button
    # that looks ready is a button that wastes a click to report a 403. This is
    # deliberately not folded into `tier()`: that answers "is this name usable",
    # which is a property of the review, and conflating it with what the account
    # can afford would make a cached `low` verdict unreadable later.
    plan_refusal = None
    if not settings.apollo_people_enabled:
        plan_refusal = (
            "Reviewer resolution needs Apollo's people endpoints, which return 403 "
            "on the current plan. Company enrichment still works. Set "
            "APOLLO_PEOPLE_ENABLED=true after upgrading."
        )

    return {
        "signal_id": signal_id,
        "display_name": row["author"],
        "country": row["country"],
        "source_site": row["source_site"],
        "matched_company": row["matched_company"],
        "name_shape": shape,
        "predicted_tier": predicted,
        "reason": reason,
        # Cached is free and re-clickable; that is the point of storing `low`.
        "cached": dict(cached) if cached else None,
        "allowed": plan_refusal is None and predicted != "low" and cached is None,
        "estimate": est,
        # The plan reason wins when both apply: "your account cannot do this at
        # all" is more actionable than "this particular name is too thin".
        "refusal": plan_refusal or (reason if predicted == "low" else None),
        "plan_blocked": plan_refusal is not None,
    }


# ------------------------------------------------------------------ resolve
async def resolve(
    signal_id: int,
    *,
    actor_email: Optional[str] = None,
    override: bool = False,
) -> dict:
    """Resolve one reviewer. Costs an Apollo credit unless the answer is cached.

    Cache-first, so a second click on the same row is free — including a second
    click on a row that resolved to `low`, which is why that verdict is stored
    rather than discarded.
    """
    pre = await assess(signal_id)

    if pre["cached"]:
        return {**pre["cached"], "cached": True, "cost_usd": 0.0}

    # Enforced here as well as in the button. The UI disabling a control is a
    # courtesy; this is the guarantee — and unlike a thin name, a plan refusal is
    # **not** stored as a `low` verdict, because it says nothing about the
    # reviewer. Storing it would poison the cache: after upgrading, every row
    # would return the old refusal for free and never retry.
    if pre.get("plan_blocked"):
        return {
            "signal_id": signal_id,
            "refused": True,
            "reason": pre["refusal"],
            "cached": False,
            "cost_usd": 0.0,
        }

    if pre["predicted_tier"] == "low":
        # Recorded without calling Apollo. Storing the refusal is what makes it
        # permanent: without a row, the next click pays to learn the same thing.
        stored = await _store(
            signal_id, pre, confidence="low", method="name_shape",
            reason=pre["reason"], person=None, cost=0.0,
        )
        return {**stored, "cached": False, "cost_usd": 0.0,
                "refused": True, "reason": pre["reason"]}

    cleared = await spend.guard("enrich_reviewer", 1, override=override)

    person, cost = await _apollo_people_match(
        pre["name_shape"]["first"], pre["name_shape"]["last"],
        pre["matched_company"], pre["country"],
    )

    await spend.record(
        "apollo_people", cost,
        action="enrich_reviewer",
        units=1,
        estimated_usd=cleared["estimated_usd"],
        signal_id=signal_id,
        actor_email=actor_email,
        detail={"display_name": pre["display_name"],
                "matched": bool(person),
                "override": bool(override)},
    )

    if not person:
        stored = await _store(
            signal_id, pre, confidence="low", method="apollo_people_match",
            reason="Apollo returned no person for this name and country",
            person=None, cost=cost,
        )
        return {**stored, "cached": False, "cost_usd": cost, "refused": True,
                "reason": "Apollo returned no person for this name and country"}

    country_matches = _country_agrees(pre["country"], person.get("country"))
    company = person.get("organization_name") or pre["matched_company"]
    final, reason = tier(pre["name_shape"], company, country_matches)

    stored = await _store(
        signal_id, pre, confidence=final, method="apollo_people_match",
        reason=reason, person=person, cost=cost,
    )
    return {**stored, "cached": False, "cost_usd": cost}


async def _store(signal_id: int, pre: dict, *, confidence: str, method: str,
                 reason: Optional[str], person: Optional[dict],
                 cost: float) -> dict:
    person = person or {}
    row = await db.fetchrow(
        """
        INSERT INTO reviewer_identity
            (signal_id, display_name, country, full_name, title, company_name,
             company_domain, email, phone, linkedin_url, confidence, method,
             reason, cost_usd)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
        ON CONFLICT (signal_id) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            title = EXCLUDED.title,
            company_name = EXCLUDED.company_name,
            company_domain = EXCLUDED.company_domain,
            email = EXCLUDED.email,
            phone = EXCLUDED.phone,
            linkedin_url = EXCLUDED.linkedin_url,
            confidence = EXCLUDED.confidence,
            method = EXCLUDED.method,
            reason = EXCLUDED.reason,
            -- Accumulated, not replaced: a re-resolve is a second charge and the
            -- row is the only record of what this signal has cost in total.
            cost_usd = reviewer_identity.cost_usd + EXCLUDED.cost_usd,
            resolved_at = now()
        RETURNING *
        """,
        signal_id,
        pre["display_name"],
        pre["country"],
        person.get("name"),
        person.get("title"),
        person.get("organization_name") or pre["matched_company"],
        person.get("organization_domain"),
        person.get("email"),
        person.get("phone"),
        person.get("linkedin_url"),
        confidence,
        method,
        reason,
        round(float(cost or 0), 5),
    )
    return dict(row)


def _country_agrees(review_country: Optional[str],
                    person_country: Optional[str]) -> Optional[bool]:
    """None when either side is unknown — which is not the same as a mismatch.

    Treating unknown as a mismatch would push every Trustpilot row without a
    country flag down a tier, and treating it as a match would let a US person
    satisfy an Indian reviewer's country check.
    """
    if not review_country or not person_country:
        return None
    a, b = review_country.strip().lower(), person_country.strip().lower()
    if a == b:
        return True
    # Two-letter code against a full name, which is how these two sources differ.
    aliases = {"in": "india", "gb": "united kingdom", "uk": "united kingdom",
               "us": "united states", "au": "australia", "fr": "france",
               "de": "germany", "ae": "united arab emirates"}
    return aliases.get(a, a) == aliases.get(b, b)


async def _apollo_people_match(
    first: Optional[str], last: Optional[str],
    company: Optional[str], country: Optional[str],
) -> tuple[Optional[dict], float]:
    """Apollo `people/match`. Returns (person, cost_usd).

    These are the endpoints that 403 on the free plan — the ones the paid plan
    was approved for. A 403 here therefore means the key is still on free, and it
    is reported as such rather than as "no person found", because those call for
    completely different fixes.

    `reveal_personal_emails` is left off deliberately. A work email is what
    outreach needs; a personal one is both more expensive and a worse thing to
    hold about someone who wrote a review.
    """
    if not settings.apollo_api_key:
        return None, 0.0

    payload: dict = {"first_name": first, "last_name": last}
    if company:
        payload["organization_name"] = company

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-api-key": settings.apollo_api_key,
        "accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{APOLLO}/people/match", headers=headers,
                                  json=payload)
        if r.status_code == 403:
            raise RuntimeError(
                "Apollo people/match returned 403 — the API key is still on the "
                "free plan, where every person endpoint is blocked. This is a "
                "billing state, not a missing person."
            )
        if r.status_code == 429:
            raise RuntimeError("Apollo rate limit reached; try again shortly")
        if r.status_code != 200:
            log.warning("apollo people/match %s for %r %r", r.status_code, first, last)
            return None, 0.0
        person = r.json().get("person")
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("apollo people/match failed for %r %r: %s", first, last, exc)
        return None, 0.0

    if not person:
        return None, 0.0

    org = person.get("organization") or {}

    # `phone_numbers` is a list of dicts when present and absent entirely when
    # not, so it needs unpacking rather than a chain of `or`s — a bare index into
    # it raises IndexError on the common case.
    numbers = person.get("phone_numbers") or []
    direct = next((n.get("raw_number") for n in numbers if n.get("raw_number")), None)

    flat = {
        "name": person.get("name"),
        "title": person.get("title"),
        "organization_name": org.get("name") or person.get("organization_name"),
        "organization_domain": org.get("primary_domain") or org.get("website_url"),
        "email": person.get("email"),
        "phone": direct or person.get("organization_phone") or org.get("phone"),
        "linkedin_url": person.get("linkedin_url"),
        "country": person.get("country") or org.get("country"),
    }

    # Apollo does not itemise a per-call dollar figure in this response, and the
    # cost is a credit rather than a price. The registered estimate is recorded so
    # the ledger has a number, and `estimated_usd` on the same row makes plain
    # that it is an estimate rather than an observed charge.
    return flat, spend.PRICES["enrich_reviewer"]["unit_usd"]


async def pending(limit: int = 50) -> list[dict]:
    """Reviews with a named author and no identity resolved yet.

    Ordered so the ones worth a credit come first: a rare full name on Trustpilot
    beats a trimmed G2 name that `assess()` will refuse anyway.
    """
    rows = await db.fetch(
        """
        SELECT s.id
        FROM signals s
        LEFT JOIN reviewer_identity ri ON ri.signal_id = s.id
        WHERE s.author IS NOT NULL AND s.author <> ''
          AND ri.id IS NULL
          AND s.kind = 'review'
        ORDER BY (s.source_site = 'trustpilot') DESC,
                 s.rating ASC NULLS LAST,
                 s.observed_at DESC
        LIMIT $1
        """,
        min(limit, 200),
    )
    return [await assess(r["id"]) for r in rows]


async def stats() -> dict:
    rows = await db.fetch(
        "SELECT confidence, count(*) AS n, COALESCE(sum(cost_usd),0) AS spent "
        "FROM reviewer_identity GROUP BY confidence"
    )
    unresolved = await db.fetchval(
        """
        SELECT count(*) FROM signals s
        LEFT JOIN reviewer_identity ri ON ri.signal_id = s.id
        WHERE s.author IS NOT NULL AND s.author <> '' AND ri.id IS NULL
        """
    )
    return {
        "by_confidence": {r["confidence"]: int(r["n"]) for r in rows},
        "spent_usd": round(float(sum(float(r["spent"]) for r in rows)), 5),
        "unresolved": int(unresolved or 0),
    }
