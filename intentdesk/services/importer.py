"""Install-base import from CSV.

This exists so the pipeline is not hostage to a BuiltWith or Wappalyzer
subscription: any list of companies running a competitor — exported from a
tech-detection UI, bought, or assembled by hand — can be loaded and scored.

Expected header (extra columns are ignored, order does not matter):

    name,domain,vendor,city,agents_est,employee_band
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

from intentdesk.services import companies, signals

REQUIRED = {"name", "domain", "vendor"}


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


async def import_installbase_csv(path: str | Path, source: str = "csv") -> dict:
    """Load companies and record an 'install' signal for each.

    Re-importing the same file is safe: companies upsert on domain and the
    install signal dedups on (source, source_id).
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    if not rows:
        return {"imported": 0, "skipped": 0, "errors": ["file has no data rows"]}

    header = {h.strip().lower() for h in (rows[0].keys() or [])}
    missing = REQUIRED - header
    if missing:
        return {
            "imported": 0,
            "skipped": len(rows),
            "errors": [f"missing required column(s): {', '.join(sorted(missing))}"],
        }

    now = datetime.now(timezone.utc)
    imported = skipped = 0
    errors: list[str] = []

    for i, raw in enumerate(rows, start=2):  # row 1 is the header
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not row.get("name") or not row.get("domain") or not row.get("vendor"):
            skipped += 1
            errors.append(f"row {i}: name, domain and vendor are all required")
            continue

        if await companies.is_suppressed(row["domain"]):
            skipped += 1
            continue

        company = await companies.upsert(
            name=row["name"],
            domain=row["domain"],
            vendor=row["vendor"],
            city=row.get("city") or None,
            employee_band=row.get("employee_band") or None,
            agents_est=_int_or_none(row.get("agents_est")),
        )
        await signals.record(
            kind="install",
            source=source,
            source_id=f"{source}:{company['domain']}",
            observed_at=now,
            company_id=company["id"],
            quote=f"{row['vendor']} detected on {company['domain']}.",
            weight=30,
            matched_confidence=1.0,
        )
        imported += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:20],
        "error_count": len(errors),
    }
