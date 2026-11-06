"""Offline tests: no X or Claude calls are made."""

from datetime import datetime, timezone
from types import SimpleNamespace

from x_scanner.report import render_digest, render_html, render_markdown
from x_scanner.summarizer import CategorySummary, Highlight, Summarizer
from x_scanner.x_client import Post, XClient, dedupe_and_rank


def _post(pid, likes, user="alice", q="q1"):
    return Post(id=pid, text=f"post {pid}", created_at="2026-11-06T00:00:00Z",
                author_username=user, author_name=user, author_followers=100,
                likes=likes, reposts=0, replies=0, quotes=0, queries=[q])


def test_dedupe_and_rank():
    posts = [_post("1", 10), _post("2", 50), _post("1", 10, q="q2"), _post("3", 1), _post("4", 0, user="vip")]
    ranked = dedupe_and_rank(posts, min_likes=5, limit=10, always_include={"@VIP"})
    assert [p.id for p in ranked] == ["2", "1", "4"]
    assert ranked[1].queries == ["q1", "q2"]


class FakeResp:
    def __init__(self, payload):
        self.status_code, self.ok, self._p, self.headers, self.text = 200, True, payload, {}, ""

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, pages):
        self.pages, self.headers, self.calls = list(pages), {}, []

    def get(self, url, params, timeout):
        self.calls.append(dict(params))
        return FakeResp(self.pages.pop(0))


def test_search_recent_parses_and_paginates():
    page1 = {"data": [{"id": "10", "text": "hi $BTC", "author_id": "u1", "created_at": "t",
                       "public_metrics": {"like_count": 7, "retweet_count": 2, "reply_count": 1, "quote_count": 0}}],
             "includes": {"users": [{"id": "u1", "username": "bob", "name": "Bob",
                                     "public_metrics": {"followers_count": 999}}]},
             "meta": {"next_token": "abc"}}
    page2 = {"data": [], "meta": {}}
    sess = FakeSession([page1, page2])
    posts = XClient("tok", session=sess).search_recent("crypto", 6, 100, 3)
    assert len(posts) == 1 and posts[0].author_username == "bob" and posts[0].likes == 7
    assert posts[0].url == "https://x.com/bob/status/10"
    assert sess.calls[1]["next_token"] == "abc" and len(sess.calls) == 2


def _summary():
    return CategorySummary(
        overall_mood="bullish", one_paragraph_summary="Traders are upbeat.",
        highlights=[Highlight(headline="BTC breaks out", detail="Posts cite ETF inflows.",
                              sentiment="bullish", tickers_or_topics=["$BTC"], source_post_ids=["1"])],
        most_mentioned=["$BTC"], contrarian_or_notable_views=["Some warn of leverage."], caveats="Some hype.",
    )


def test_summarizer_uses_parse_and_handles_refusal():
    captured = {}

    def parse(**kw):
        captured.update(kw)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=_summary())

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    s = Summarizer(client=client)
    assert s.summarize("Crypto", [_post("1", 10)], 6).overall_mood == "bullish"
    assert captured["model"] == "claude-opus-5-5" and captured["output_format"] is CategorySummary
    assert s.summarize("Crypto", [], 6) is None

    client.beta.messages.parse = lambda **kw: SimpleNamespace(stop_reason="refusal", parsed_output=None)
    assert s.summarize("Crypto", [_post("1", 10)], 6) is None


def test_reports_render():
    posts = [_post("1", 10)]
    results = {"crypto": ("Crypto", _summary(), posts), "news": ("News", None, [])}
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    md = render_markdown(results, now, 6)
    assert "BTC breaks out" in md and "https://x.com/alice/status/1" in md and "No summary" in md
    html = render_html(md)
    assert '<a href="https://x.com/alice/status/1">@alice</a>' in html and "<ol>" in html
    assert "🟢 Crypto (bullish)" in render_digest(results, now)
