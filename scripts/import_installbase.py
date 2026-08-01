"""Load an install-base CSV, then rescore the queue.

    python -m scripts.import_installbase companies.csv

Header must include name, domain and vendor; city, agents_est and
employee_band are optional. Re-running the same file is safe.
"""

import asyncio
import sys

from intentdesk import db
from intentdesk.services import importer, scan


async def main(path: str):
    await db.connect()
    try:
        result = await importer.import_installbase_csv(path)
        print(f"imported {result['imported']}, skipped {result['skipped']}")
        for err in result.get("errors", []):
            print(f"  ! {err}")
        rescored = await scan.rescore_all()
        print(
            f"rescored {rescored['companies_scored']} companies, "
            f"{rescored['leads_created']} new leads"
        )
    finally:
        await db.disconnect()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m scripts.import_installbase <file.csv>")
    asyncio.run(main(sys.argv[1]))
