"""Reddit complaints.

Reddit's unauthenticated JSON endpoints return 403 from datacenter IPs, so this
uses the OAuth client-credentials flow. Creating the app is free:
https://www.reddit.com/prefs/apps → "script" type → put the id and secret in
REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET.

UNTESTED — written against the documented API but never run, because no
credentials exist on this box yet. Treat the first live run as a test.
"""

from datetime import datetime, timezone

import httpx

from intentdesk.collectors import Collector, RawSignal
from intentdesk.config import settings

SUBREDDITS = ("sysadmin", "msp", "customerservice", "india_startups", "smallbusiness")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
SEARCH_URL = "https://oauth.reddit.com/r/{sub}/search"

# Posts that merely mention the vendor are noise. These are the words that turn
# a mention into a complaint worth surfacing.
COMPLAINT_TERMS = (
    "expensive", "pricing", "price", "cost", "bill", "overpriced", "renewal",
    "alternative", "migrate", "migrating", "switch", "switching", "leaving",
    "cancel", "frustrat", "terrible", "awful", "broken", "slow", "useless",
)


class RedditCollector(Collector):
    name = "reddit"
    kind = "forum"
    requires = ("reddit_client_id", "reddit_client_secret")

    async def _token(self, client: httpx.AsyncClient) -> str:
        res = await client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(settings.reddit_client_id, settings.reddit_client_secret),
            headers={"User-Agent": settings.reddit_user_agent},
        )
        res.raise_for_status()
        return res.json()["access_token"]

    async def collect(self, competitor: str) -> list[RawSignal]:
        if not self.available():
            raise RuntimeError(f"reddit: missing {self.missing_credentials()}")

        found: list[RawSignal] = []
        headers = {"User-Agent": settings.reddit_user_agent}

        async with httpx.AsyncClient(timeout=25) as client:
            headers["Authorization"] = f"bearer {await self._token(client)}"

            for sub in SUBREDDITS:
                try:
                    res = await client.get(
                        SEARCH_URL.format(sub=sub),
                        params={"q": competitor, "restrict_sr": 1,
                                "sort": "new", "limit": 50, "t": "year"},
                        headers=headers,
                    )
                    res.raise_for_status()
                except httpx.HTTPError:
                    continue  # one dead subreddit must not kill the whole run

                for child in res.json().get("data", {}).get("children", []):
                    post = child.get("data", {})
                    text = f"{post.get('title', '')}\n{post.get('selftext', '')}"
                    if not any(t in text.lower() for t in COMPLAINT_TERMS):
                        continue
                    found.append(
                        RawSignal(
                            kind="forum",
                            source="reddit",
                            source_id=f"reddit:{post.get('id')}",
                            observed_at=datetime.fromtimestamp(
                                post.get("created_utc", 0), tz=timezone.utc
                            ),
                            quote=(post.get("title") or "")[:280],
                            raw_text=text[:4000],
                            vendor=competitor,
                        )
                    )

        return found
