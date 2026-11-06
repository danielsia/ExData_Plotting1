"""Render category summaries into Markdown, HTML and a short plain-text digest."""

from __future__ import annotations

import html
from datetime import datetime

from .summarizer import CategorySummary
from .x_client import Post

MOOD_EMOJI = {"bullish": "🟢", "bearish": "🔴", "mixed": "🟡", "neutral": "⚪"}


def _links(ids: list[str], posts_by_id: dict[str, Post], limit: int = 3) -> list[tuple[str, str]]:
    out = []
    for pid in ids[:limit]:
        p = posts_by_id.get(pid)
        if p:
            out.append((f"@{p.author_username}", p.url))
    return out


def render_markdown(
    results: dict[str, tuple[str, CategorySummary | None, list[Post]]],
    generated_at: datetime,
    lookback_hours: int,
) -> str:
    lines = [
        f"# X Market & News Briefing — {generated_at:%Y-%m-%d %H:%M} UTC",
        "",
        f"_Window: last {lookback_hours}h. Summary of social-media sentiment, not investment advice._",
        "",
    ]
    for _key, (title, summary, posts) in results.items():
        lines.append(f"## {title}")
        if summary is None:
            lines += ["", "_No summary this run (no qualifying posts, or the request was declined)._", ""]
            continue
        by_id = {p.id: p for p in posts}
        lines += [
            "",
            f"**Mood:** {MOOD_EMOJI[summary.overall_mood]} {summary.overall_mood} · "
            f"**Posts analysed:** {len(posts)}",
            "",
            summary.one_paragraph_summary,
            "",
            "### Highlights",
        ]
        for i, h in enumerate(summary.highlights, 1):
            tags = ", ".join(h.tickers_or_topics)
            src = " ".join(f"[{name}]({url})" for name, url in _links(h.source_post_ids, by_id))
            lines.append(f"{i}. **{h.headline}** {MOOD_EMOJI[h.sentiment]} — {h.detail}")
            if tags or src:
                lines.append(f"   - {('Topics: ' + tags) if tags else ''}{' · ' if tags and src else ''}{src}")
        if summary.most_mentioned:
            lines += ["", f"**Most mentioned:** {', '.join(summary.most_mentioned)}"]
        if summary.contrarian_or_notable_views:
            lines += ["", "**Contrarian / notable views:**"]
            lines += [f"- {v}" for v in summary.contrarian_or_notable_views]
        if summary.caveats:
            lines += ["", f"_Caveats: {summary.caveats}_"]
        lines.append("")
    return "\n".join(lines)


def render_digest(
    results: dict[str, tuple[str, CategorySummary | None, list[Post]]],
    generated_at: datetime,
    max_highlights: int = 3,
) -> str:
    """Short plain-text version for chat apps (Telegram/Slack)."""
    lines = [f"📊 X Briefing — {generated_at:%d %b %H:%M} UTC", ""]
    for _key, (title, summary, _posts) in results.items():
        if summary is None:
            lines += [f"{title}: no data this run", ""]
            continue
        lines.append(f"{MOOD_EMOJI[summary.overall_mood]} {title} ({summary.overall_mood})")
        for h in summary.highlights[:max_highlights]:
            lines.append(f"• {h.headline}")
        lines.append("")
    return "\n".join(lines).strip()


def render_html(markdown_text: str) -> str:
    """Minimal Markdown -> HTML (enough for email); avoids an extra dependency."""
    import re

    out, in_list = [], None
    for raw in markdown_text.splitlines():
        line = html.escape(raw)
        line = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", line)
        m_ol = re.match(r"^(\d+)\. (.*)", line)
        m_ul = re.match(r"^\s*- (.*)", line)
        tag = "ol" if m_ol else "ul" if m_ul else None
        if in_list and tag != in_list and not (in_list == "ol" and m_ul):
            out.append(f"</{in_list}>")
            in_list = None
        if line.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
        elif m_ol:
            if not in_list:
                out.append("<ol>")
                in_list = "ol"
            out.append(f"<li>{m_ol.group(2)}</li>")
        elif m_ul:
            if in_list == "ol":
                out.append(f'<div style="color:#555;font-size:0.9em;margin-left:1em">{m_ul.group(1)}</div>')
            else:
                if not in_list:
                    out.append("<ul>")
                    in_list = "ul"
                out.append(f"<li>{m_ul.group(1)}</li>")
        elif line.strip():
            out.append(f"<p>{line}</p>")
    if in_list:
        out.append(f"</{in_list}>")
    body = "\n".join(out)
    return (
        '<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        f'max-width:720px;margin:auto;line-height:1.5">{body}</body></html>'
    )
