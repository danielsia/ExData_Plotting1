"""Summarise collected X posts per category with Claude (structured output)."""

from __future__ import annotations

import json
import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from .x_client import Post

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"


class Highlight(BaseModel):
    headline: str = Field(description="One-line takeaway, max ~15 words")
    detail: str = Field(description="2-3 sentences: what people are saying and why it matters")
    sentiment: Literal["bullish", "bearish", "mixed", "neutral"]
    tickers_or_topics: list[str] = Field(description="Tickers ($NVDA, $BTC) or topics involved")
    source_post_ids: list[str] = Field(description="IDs of the posts that support this highlight")


class CategorySummary(BaseModel):
    overall_mood: Literal["bullish", "bearish", "mixed", "neutral"]
    one_paragraph_summary: str
    highlights: list[Highlight] = Field(description="3-7 most important highlights, most important first")
    most_mentioned: list[str] = Field(description="Most discussed tickers/topics, most mentioned first")
    contrarian_or_notable_views: list[str] = Field(
        description="Minority views or warnings worth knowing, if any"
    )
    caveats: str = Field(description="Data-quality notes: hype, bots, unverified claims, thin coverage")


SYSTEM_PROMPT = """You are a markets and news analyst producing a briefing for a busy investor.
You receive a batch of recent posts from X (Twitter) for one category. Your job is to
summarise the prevailing views and surface what actually matters.

Guidelines:
- Report what people on X are saying; do not present claims as verified fact. Use
  phrasing like "posts claim" or "traders are discussing" for unconfirmed items.
- Weight posts by engagement and author reach, but do not let one viral post dominate
  if it conflicts with the broader picture.
- Discount obvious spam, pump-and-dump promotion, giveaways and bot-like content, and
  mention in caveats if they make up a meaningful share.
- Only cite post IDs that appear in the input.
- This is a summary of social sentiment, not investment advice."""


def _posts_payload(posts: list[Post]) -> str:
    rows = [
        {
            "id": p.id,
            "author": f"@{p.author_username}",
            "followers": p.author_followers,
            "likes": p.likes,
            "reposts": p.reposts,
            "replies": p.replies,
            "created_at": p.created_at,
            "text": p.text,
        }
        for p in posts
    ]
    return json.dumps(rows, ensure_ascii=False)


class Summarizer:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model

    def summarize(self, category_title: str, posts: list[Post], lookback_hours: int) -> CategorySummary | None:
        if not posts:
            return None
        user = (
            f"Category: {category_title}\n"
            f"Window: the last {lookback_hours} hours\n"
            f"Number of posts: {len(posts)}\n\n"
            f"<posts>\n{_posts_payload(posts)}\n</posts>"
        )
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                output_format=CategorySummary,
                # On a safety-classifier decline, re-run on Anthropic's recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError:
            log.exception("Claude rate limit hit while summarising %s", category_title)
            raise
        except anthropic.APIStatusError as e:
            log.error("Claude API error (%s) for %s: %s", e.status_code, category_title, e.message)
            raise
        except anthropic.APIConnectionError:
            log.exception("Could not reach the Claude API for %s", category_title)
            raise

        if response.stop_reason == "refusal":
            log.warning("Claude declined to summarise %s", category_title)
            return None
        if response.stop_reason == "max_tokens":
            log.warning("Summary for %s hit max_tokens; output may be incomplete", category_title)
        return response.parsed_output
