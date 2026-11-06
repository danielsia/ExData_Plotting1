"""Entry point: python -m x_scanner.main [--config config.yaml] [--loop]"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .delivery import deliver_all
from .report import render_digest, render_html, render_markdown
from .summarizer import Summarizer
from .x_client import Post, XClient, dedupe_and_rank

log = logging.getLogger("x_scanner")


def collect(cfg: dict, x: XClient) -> dict[str, tuple[str, list[Post]]]:
    hours = cfg["lookback_hours"]
    out = {}
    for key, cat in cfg["categories"].items():
        posts: list[Post] = []
        queries = list(cat.get("queries", []))
        accounts = cat.get("accounts") or []
        if accounts:
            queries.append("(" + " OR ".join(f"from:{a.lstrip('@')}" for a in accounts) + ") -is:retweet")
        for q in queries:
            try:
                got = x.search_recent(q, hours, cfg["max_posts_per_query"], cfg["max_pages_per_query"])
                log.info("[%s] %d posts for query: %s", key, len(got), q)
                posts.extend(got)
            except Exception:
                log.exception("[%s] query failed: %s", key, q)
        ranked = dedupe_and_rank(posts, cfg["min_likes"], cfg["posts_per_category_for_llm"], set(accounts))
        out[key] = (cat.get("title", key), ranked)
    return out


def run_once(cfg: dict, out_dir: Path) -> Path:
    now = datetime.now(timezone.utc)
    x = XClient(os.environ.get("X_BEARER_TOKEN", ""))
    collected = collect(cfg, x)

    summarizer = Summarizer()
    results = {}
    for key, (title, posts) in collected.items():
        log.info("Summarising %s (%d posts)", key, len(posts))
        try:
            summary = summarizer.summarize(title, posts, cfg["lookback_hours"])
        except Exception:
            log.exception("Summarising %s failed", key)
            summary = None
        results[key] = (title, summary, posts)

    md = render_markdown(results, now, cfg["lookback_hours"])
    html = render_html(md)
    digest = render_digest(results, now)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"briefing-{now:%Y%m%d-%H%M}"
    (out_dir / f"{stem}.md").write_text(md, encoding="utf-8")
    (out_dir / f"{stem}.html").write_text(html, encoding="utf-8")
    (out_dir / "latest.md").write_text(md, encoding="utf-8")
    (out_dir / "latest.html").write_text(html, encoding="utf-8")

    sent = deliver_all(f"X Briefing {now:%Y-%m-%d %H:%M} UTC", digest, md, html)
    log.info("Report written to %s; delivered via: %s", out_dir / f"{stem}.md", ", ".join(sent) or "none")
    print(digest)
    return out_dir / f"{stem}.md"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scan X and summarise stocks, crypto and news.")
    ap.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.yaml"))
    ap.add_argument("--out", default="reports", help="Directory for generated reports")
    ap.add_argument("--loop", action="store_true",
                    help="Keep running and scan every lookback_hours (for a server/VPS instead of cron)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text())

    if not args.loop:
        run_once(cfg, Path(args.out))
        return 0
    while True:
        try:
            run_once(cfg, Path(args.out))
        except Exception:
            log.exception("Scan failed; will retry next cycle")
        time.sleep(cfg["lookback_hours"] * 3600)


if __name__ == "__main__":
    sys.exit(main())
