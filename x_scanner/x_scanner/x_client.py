"""Thin client for the X (Twitter) API v2 recent-search endpoint."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.x.com/2/tweets/search/recent"


@dataclass
class Post:
    id: str
    text: str
    created_at: str
    author_username: str
    author_name: str
    author_followers: int
    likes: int
    reposts: int
    replies: int
    quotes: int
    verified: bool = False
    queries: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://x.com/{self.author_username}/status/{self.id}"

    @property
    def engagement(self) -> float:
        # Reposts and quotes spread a view further than likes, so weight them up.
        return self.likes + 2 * self.reposts + 2 * self.quotes + self.replies


class XClient:
    def __init__(self, bearer_token: str, session: requests.Session | None = None):
        if not bearer_token:
            raise ValueError("X_BEARER_TOKEN is not set")
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {bearer_token}"})

    def search_recent(
        self,
        query: str,
        lookback_hours: int,
        max_results: int = 100,
        max_pages: int = 1,
    ) -> list[Post]:
        start = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        params = {
            "query": query,
            "max_results": max(10, min(max_results, 100)),
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sort_order": "relevancy",
            "tweet.fields": "created_at,public_metrics,author_id,lang",
            "expansions": "author_id",
            "user.fields": "username,name,public_metrics,verified",
        }
        posts: list[Post] = []
        for _ in range(max_pages):
            data = self._get(params)
            users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
            for t in data.get("data", []):
                u = users.get(t.get("author_id"), {})
                m = t.get("public_metrics", {})
                posts.append(
                    Post(
                        id=t["id"],
                        text=t.get("text", ""),
                        created_at=t.get("created_at", ""),
                        author_username=u.get("username", "unknown"),
                        author_name=u.get("name", ""),
                        author_followers=u.get("public_metrics", {}).get("followers_count", 0),
                        likes=m.get("like_count", 0),
                        reposts=m.get("retweet_count", 0),
                        replies=m.get("reply_count", 0),
                        quotes=m.get("quote_count", 0),
                        verified=bool(u.get("verified", False)),
                        queries=[query],
                    )
                )
            token = data.get("meta", {}).get("next_token")
            if not token:
                break
            params["next_token"] = token
        return posts

    def _get(self, params: dict, retries: int = 3) -> dict:
        for attempt in range(retries + 1):
            resp = self.session.get(SEARCH_URL, params=params, timeout=30)
            if resp.status_code == 429 and attempt < retries:
                reset = int(resp.headers.get("x-rate-limit-reset", time.time() + 60))
                wait = max(5, min(reset - int(time.time()), 900))
                log.warning("X API rate limited; sleeping %ss", wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 500 and attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            if not resp.ok:
                raise RuntimeError(f"X API error {resp.status_code}: {resp.text[:500]}")
            return resp.json()
        raise RuntimeError("X API: retries exhausted")


def dedupe_and_rank(posts: list[Post], min_likes: int, limit: int, always_include: set[str]) -> list[Post]:
    """Merge duplicates (same post from several queries), filter, and sort by engagement."""
    merged: dict[str, Post] = {}
    for p in posts:
        if p.id in merged:
            merged[p.id].queries.extend(q for q in p.queries if q not in merged[p.id].queries)
        else:
            merged[p.id] = p
    always = {a.lower().lstrip("@") for a in always_include}
    kept = [
        p for p in merged.values()
        if p.likes >= min_likes or p.author_username.lower() in always
    ]
    kept.sort(key=lambda p: p.engagement, reverse=True)
    return kept[:limit]
