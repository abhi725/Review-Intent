"""Drive the MCP server over stdio like a real client would.

    python -m scripts.mcp_smoke

Lists the tools, then calls a few read-only ones. Nothing here spends money —
run_scan is deliberately not called.
"""

import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PARAMS = StdioServerParameters(
    command=".venv/bin/python", args=["-m", "intentdesk.mcp.server"]
)


def rows_of(result) -> list:
    """FastMCP emits one content block per item when a tool returns a list, so
    a list result arrives as N blocks rather than one JSON array."""
    out = []
    for block in result.content:
        try:
            out.append(json.loads(block.text))
        except (json.JSONDecodeError, TypeError, AttributeError):
            out.append(block.text)
    return out


def brief(result) -> str:
    rows = rows_of(result)
    if not rows:
        return "(empty)"
    if len(rows) == 1:
        return json.dumps(rows[0])[:170] if not isinstance(rows[0], str) else rows[0][:120]
    return f"{len(rows)} rows; first = {json.dumps(rows[0])[:110]}"


async def main():
    async with stdio_client(PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = (await session.list_tools()).tools
            print(f"  {len(tools)} tools exposed:")
            for t in tools:
                print(f"    {t.name:<20} {(t.description or '').splitlines()[0][:62]}")

            print("\n  calling read-only tools:")
            for name, args in [
                ("stats", {}),
                ("list_leads", {"heat": "hot", "limit": 3}),
                ("scan_status", {}),
                ("collector_health", {"days": 7}),
                ("list_signals", {"kind": "review", "matched": False, "limit": 3}),
                ("watchlist_list", {}),
                ("get_settings", {}),
            ]:
                out = await session.call_tool(name, args)
                print(f"    {name:<18} -> {brief(out)}")

            rows = rows_of(await session.call_tool("list_leads", {"heat": "hot", "limit": 1}))
            if rows:
                explained = rows_of(
                    await session.call_tool("explain_score", {"lead_id": rows[0]["id"]})
                )[0]
                print("\n  explain_score on the top hot lead:")
                print(f"    {explained['company']} = {explained['score']} ({explained['heat']})")
                for line in explained["breakdown"]:
                    print(f"      {line}")


if __name__ == "__main__":
    asyncio.run(main())
