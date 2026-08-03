"""Which pending organiser gets paid for first.

Resolution is the step that bills — ~$0.0027 a row with GMB — and there are
thousands of pending rows, so the order they come out of the queue in decides
what the money buys. Discovery order is the wrong order: MeraEvents was
discovered first and in bulk (2,031 rows against Eventbrite's 450), and
MeraEvents is the platform with no G2 page, no verified Trustpilot page and so
no classified complaint. Resolving those rows first buys companies whose best
possible draft is the generic pitch, and reaches the platform we hold 26
classified complaints about last.

**What this file does and does not prove.** The suite runs against a `FakeDB`
stub, so it cannot execute SQL — these tests check that the priority clause is
in the query and ahead of the recency clause, which catches it being dropped or
reordered by a later edit. That the SQL *means* what it should was verified
against the live database on 2026-08-03, where the predicate separated the queue
as intended:

    platform   | pending | has_evidence
    Eventbrite |     450 | t
    MeraEvents |   2,031 | f

Saying so here rather than implying a passing test covers it.
"""

import asyncio
import re

import pytest

from intentdesk import db
from intentdesk.services import resolving


class QueryRecorder:
    """Records SQL instead of answering it. Returning no pending rows makes
    resolve_batch exit before it can bill anything."""

    def __init__(self):
        self.queries: list[str] = []

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        return []

    async def fetchrow(self, sql, *args):
        self.queries.append(sql)
        return None

    async def fetchval(self, sql, *args):
        self.queries.append(sql)
        return 0

    async def execute(self, sql, *args):
        self.queries.append(sql)
        return "INSERT 0 1"


@pytest.fixture
def recorder(monkeypatch):
    stub = QueryRecorder()
    for name in ("fetch", "fetchrow", "fetchval", "execute"):
        monkeypatch.setattr(db, name, getattr(stub, name))
    return stub


def _pending_query(recorder):
    asyncio.run(resolving.resolve_batch(limit=5, use_gmb=False))
    for sql in recorder.queries:
        if "FROM organisers" in sql and "status = 'pending'" in sql:
            return sql
    raise AssertionError("resolve_batch never queried the pending queue")


def test_platforms_with_evidence_are_resolved_first(recorder):
    sql = _pending_query(recorder)
    assert "FROM signals" in sql and "category IS NOT NULL" in sql, (
        "the pending queue no longer prefers platforms we hold classified "
        "complaints about, so resolution spend goes to companies that can only "
        "ever get the generic pitch"
    )


def test_priority_outranks_recency(recorder):
    """Both clauses present but in the wrong order is the subtle failure: it
    still looks prioritised and still drains the queue in discovery order."""
    sql = _pending_query(recorder)
    order_by = sql[sql.index("ORDER BY"):]
    evidence = order_by.index("FROM signals")
    recency = order_by.index("discovered_at")
    assert evidence < recency, "discovered_at is sorting ahead of the evidence check"


def test_no_platform_is_excluded(recorder):
    """Prioritising is not filtering. A platform with no complaints yet still has
    to resolve eventually — today's unmatched platform is next week's, once a
    review source for it is found."""
    sql = _pending_query(recorder)
    where = sql[sql.index("WHERE"):sql.index("ORDER BY")]
    assert "platform" not in where, (
        "platform appears in WHERE, not just ORDER BY — that drops rows instead "
        "of deferring them"
    )


def test_batch_is_still_capped(recorder):
    """The cap is what makes a 2,481-row queue resumable rather than one long
    unattended spend."""
    sql = _pending_query(recorder)
    assert re.search(r"LIMIT\s+\$1", sql)
