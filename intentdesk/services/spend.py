"""Money: what a click will cost, whether it is allowed, and what it did cost.

The governing rule of this system is that free work runs on a schedule and paid
work runs on a click. That only means anything if the click can say its price
first and the total is checked before the call, not after — a provider bills as
its run proceeds, so nothing here can stop a request already in flight. What it
can do is refuse to start the next one.

Three things live here and nowhere else:

* **the price list** — measured figures with a note saying how they were
  measured, so an estimate that is really a guess says so on the button;
* **the gate** — one `guard()` every paid path calls before spending;
* **the ledger** — `spend_calls`, one row per call with what it was for and who
  clicked, alongside the `spend` day-rollup the cap itself reads.
"""

from datetime import datetime, timezone
from typing import Optional

from intentdesk import db
from intentdesk.services import preferences

# Warn here, refuse at 100%. The warning exists because the useful moment to
# find out about a budget is before it is gone.
WARN_AT = 0.80


class SpendRefused(Exception):
    """A paid call was declined before it was made.

    Carries the numbers rather than just a message, so an API layer can hand the
    UI something to render and a caller can decide whether an admin override is
    worth offering.
    """

    def __init__(self, reason: str, *, spent: float, cap: float, would_add: float):
        self.reason = reason
        self.spent = spent
        self.cap = cap
        self.would_add = would_add
        super().__init__(reason)

    def as_dict(self) -> dict:
        return {
            "refused": True,
            "reason": self.reason,
            "spent_usd": round(self.spent, 4),
            "cap_usd": round(self.cap, 2),
            "would_add_usd": round(self.would_add, 4),
        }


# ------------------------------------------------------------------ price list
#
# `unit_usd` is per *unit* of the action, and `unit` names what a unit is —
# without that, "$0.05" reads as either a run or a review and the button lies by
# a factor of twenty.
#
# `measured: False` means the figure is inferred from a provider's pricing page
# rather than observed on this account. Those are shown with a "~" and must not
# be quoted as fact.
PRICES: dict[str, dict] = {
    "collect_trustpilot": {
        "provider": "trustpilot",
        "unit": "run",
        "unit_usd": 0.05,
        "measured": True,
        "note": "memo23~trustpilot-scraper-ppe, 56 reviews across 4 brands for "
                "$0.05 per run, 2026-08-03",
    },
    "collect_g2": {
        "provider": "apify_g2",
        "unit": "review fetched",
        "unit_usd": 0.06,
        "measured": True,
        "note": "automation-lab~g2-scraper: $1.41 for 4 competitors × 50 reviews. "
                "Only ~4% are negative, so a negative review found costs ~$0.15",
    },
    "resolve_organiser": {
        "provider": "gmb",
        "unit": "organiser",
        "unit_usd": 0.0035,
        "measured": True,
        "note": "compass~crawler-google-places, $0.049 across 14 lookups, 2026-08-03",
    },
    "enrich_reviewer": {
        "provider": "apollo_people",
        "unit": "person",
        "unit_usd": 0.03,
        "measured": False,
        "note": "Apollo people/match costs one credit; the dollar figure depends "
                "on the plan and has not been observed on this account",
    },
    # Named so the UI can show a zero next to the free actions rather than
    # leaving them unpriced, which reads as unknown.
    "discover_organisers": {
        "provider": "sitemap",
        "unit": "run",
        "unit_usd": 0.0,
        "measured": True,
        "note": "public sitemaps, no actor and no key",
    },
    "collect_news": {
        "provider": "google_news",
        "unit": "run",
        "unit_usd": 0.0,
        "measured": True,
        "note": "Google News RSS, no key",
    },
    "collect_reddit": {
        "provider": "reddit",
        "unit": "run",
        "unit_usd": 0.0,
        "measured": True,
        "note": "official API on free OAuth credentials; the $0.17 Apify route "
                "was retired for returning no usable signal",
    },
    "collect_b2b_reviews": {
        "provider": "b2b_reviews",
        "unit": "run",
        "unit_usd": 0.0,
        "measured": True,
        "note": "TrustRadius and SoftwareSuggest JSON-LD, parsed over plain HTTP "
                "— no actor, no key. Free but unverified: neither has returned a "
                "row from this host yet",
    },
    "enrich_company": {
        "provider": "apollo_org",
        "unit": "company",
        "unit_usd": 0.0,
        "measured": True,
        "note": "Apollo organizations/enrich works on the free plan",
    },
}


def estimate(action: str, units: int = 1) -> dict:
    """What an action will cost, as the button should read it.

    An unknown action returns `measured: False` and a zero rather than raising:
    a new collector that forgot to register a price must not take the screen down,
    but it must not claim to be free either — hence the explicit warning text.
    """
    units = max(int(units or 1), 0)
    price = PRICES.get(action)
    if price is None:
        return {
            "action": action,
            "units": units,
            "unit": "unknown",
            "unit_usd": 0.0,
            "estimated_usd": 0.0,
            "measured": False,
            "free": False,
            "note": "no price registered for this action — the cost is unknown, "
                    "not zero",
            "label": f"{action} · cost unknown",
        }

    total = round(price["unit_usd"] * units, 5)
    free = price["unit_usd"] == 0.0
    tilde = "" if price["measured"] else "~"
    label = (f"{action} · free" if free
             else f"{action} · {tilde}${total:.2f}" if total >= 0.01
             else f"{action} · {tilde}${total:.4f}")

    return {
        "action": action,
        "provider": price["provider"],
        "units": units,
        "unit": price["unit"],
        "unit_usd": price["unit_usd"],
        "estimated_usd": total,
        "measured": price["measured"],
        "free": free,
        "note": price["note"],
        "label": label,
    }


def price_list() -> list[dict]:
    """Every priced action, for the Sources panel."""
    return [{"action": action, **estimate(action, 1)} for action in sorted(PRICES)]


# ------------------------------------------------------------------- the gate
async def month_to_date() -> dict:
    """This month against the cap.

    Reads the `spend` rollup rather than summing `spend_calls`, because the
    rollup is the record the two pre-existing callers write to and a cap that
    disagrees with the collectors' own accounting is worse than no cap.
    """
    prefs = await preferences.all_prefs()
    cap = float(prefs["monthly_spend_cap_usd"])
    spent = float(await db.fetchval(
        "SELECT COALESCE(sum(amount_usd), 0) FROM spend "
        "WHERE day >= date_trunc('month', current_date)"
    ) or 0)

    remaining = max(cap - spent, 0.0)
    fraction = (spent / cap) if cap > 0 else 1.0
    return {
        "month": datetime.now(timezone.utc).strftime("%Y-%m"),
        "spent_usd": round(spent, 4),
        "cap_usd": round(cap, 2),
        "remaining_usd": round(remaining, 4),
        "fraction_used": round(fraction, 4),
        "warning": fraction >= WARN_AT and fraction < 1.0,
        "exhausted": fraction >= 1.0,
    }


async def guard(action: str, units: int = 1, *, override: bool = False) -> dict:
    """Check before spending. Raises `SpendRefused` when the call is not allowed.

    Returns the estimate on success, so the caller has the figure it was cleared
    for and can log the difference between quoted and billed.

    `override` is the admin escape hatch. It still records that the cap was
    passed deliberately — cost approved is not cost unbounded.
    """
    est = estimate(action, units)
    if est["free"]:
        return est

    state = await month_to_date()
    would_be = state["spent_usd"] + est["estimated_usd"]

    if override:
        return {**est, "override": True, "spend_state": state}

    if state["exhausted"]:
        raise SpendRefused(
            f"The ${state['cap_usd']:.2f} monthly cap is already spent "
            f"(${state['spent_usd']:.2f}). Raise the cap in Settings, or wait for "
            f"the month to roll over.",
            spent=state["spent_usd"], cap=state["cap_usd"],
            would_add=est["estimated_usd"],
        )

    if would_be > state["cap_usd"]:
        raise SpendRefused(
            f"This would cost about ${est['estimated_usd']:.4f} and take the month "
            f"to ${would_be:.2f}, past the ${state['cap_usd']:.2f} cap. Reduce the "
            f"row count, or raise the cap in Settings.",
            spent=state["spent_usd"], cap=state["cap_usd"],
            would_add=est["estimated_usd"],
        )

    return {**est, "spend_state": state}


# ----------------------------------------------------------------- the ledger
async def record(
    provider: str,
    amount_usd: float,
    *,
    action: str = "unknown",
    units: int = 1,
    estimated_usd: Optional[float] = None,
    signal_id: Optional[int] = None,
    organiser_id: Optional[int] = None,
    competitor: Optional[str] = None,
    actor_email: Optional[str] = None,
    detail: Optional[dict] = None,
) -> dict:
    """Write one paid call to both the ledger and the day rollup.

    In one transaction on purpose. Two separate writes can leave a call in the
    ledger that the cap cannot see, which is the one inconsistency that matters
    here: it would let spending continue past the limit while the audit trail
    looked complete.

    A zero amount is still recorded. "We called this and it was free" and "we
    never called it" are different facts, and only the ledger can tell them
    apart.
    """
    amount = round(float(amount_usd or 0), 5)

    async with db.transaction() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO spend_calls (provider, action, units, amount_usd,
                                     estimated_usd, signal_id, organiser_id,
                                     competitor, actor_email, detail)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
            RETURNING id, created_at
            """,
            provider, action, max(int(units or 1), 1), amount,
            round(float(estimated_usd), 5) if estimated_usd is not None else None,
            signal_id, organiser_id, competitor, actor_email, detail,
        )
        await conn.execute(
            """
            INSERT INTO spend (day, provider, amount_usd, calls, last_at)
            VALUES (current_date, $1, $2, 1, now())
            ON CONFLICT (day, provider) DO UPDATE
                SET amount_usd = spend.amount_usd + EXCLUDED.amount_usd,
                    calls      = spend.calls + 1,
                    last_at    = now()
            """,
            provider, amount,
        )

    return {"id": row["id"], "provider": provider, "action": action,
            "amount_usd": amount, "at": row["created_at"]}


async def report(month: Optional[str] = None) -> dict:
    """Spend for a month, split the three ways someone actually asks about it:
    by provider, by action, and by who clicked.

    `month` is `YYYY-MM`; omitted means the current one.
    """
    if month:
        try:
            start = datetime.strptime(month + "-01", "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"month must be YYYY-MM, got {month!r}") from exc
        window = "AND created_at >= $1 AND created_at < ($1::date + interval '1 month')"
        args: tuple = (start,)
    else:
        window = "AND created_at >= date_trunc('month', current_date)"
        args = ()

    async def grouped(column: str) -> list[dict]:
        rows = await db.fetch(
            f"""
            SELECT COALESCE({column}, 'unattributed') AS key,
                   count(*)                    AS calls,
                   COALESCE(sum(amount_usd),0) AS spent,
                   COALESCE(sum(estimated_usd),0) AS quoted
            FROM spend_calls
            WHERE TRUE {window}
            GROUP BY 1
            ORDER BY spent DESC
            """,
            *args,
        )
        return [
            {"key": r["key"], "calls": int(r["calls"]),
             "spent_usd": round(float(r["spent"]), 4),
             "quoted_usd": round(float(r["quoted"]), 4)}
            for r in rows
        ]

    state = await month_to_date()
    by_provider = await grouped("provider")
    by_action = await grouped("action")
    by_user = await grouped("actor_email")

    ledger_total = round(sum(p["spent_usd"] for p in by_provider), 4)

    return {
        **state,
        "month": month or state["month"],
        "by_provider": by_provider,
        "by_action": by_action,
        "by_user": by_user,
        "ledger_total_usd": ledger_total,
        # The rollup predates the ledger, so early spend has no per-call rows.
        # Reported rather than reconciled away: a silent difference between the
        # two totals is how an untracked paid path hides.
        "unledgered_usd": round(max(state["spent_usd"] - ledger_total, 0.0), 4),
        "prices": price_list(),
    }
