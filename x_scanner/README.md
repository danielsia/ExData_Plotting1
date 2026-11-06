# X Market & News Scanner

Every 6 hours this app searches X (Twitter) for posts about **stocks**, **crypto** and
**key news developments**. It ranks the posts by engagement, has Claude summarise the
prevailing views in each category, and sends you the highlights.

```
X API v2 recent search ──► dedupe + rank by engagement ──► Claude (structured summary)
        (per category)          (top 120 per category)          │
                                                                ▼
                      reports/briefing-*.md / .html  +  Telegram / Slack / Email
```

Each briefing contains, for each category:
- overall mood (🟢 bullish / 🔴 bearish / 🟡 mixed / ⚪ neutral) and a one-paragraph summary
- 3–7 ranked highlights with sentiment, tickers/topics and links to the source posts
- the most-mentioned tickers/topics
- contrarian or notable views
- caveats (hype, bots, unverified claims)

## What you need

| Thing | Where | Notes |
|---|---|---|
| `X_BEARER_TOKEN` | [developer.x.com](https://developer.x.com) → your app → Keys & tokens | The recent-search endpoint needs a paid X API plan. Check current tiers and quotas. One run makes about `queries × max_pages_per_query` requests (12 with the default config), so 4 runs a day is about 48 requests and up to about 4,800 posts read. |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Uses `claude-opus-5-5`. One run makes 3 calls (one per category). |
| A delivery channel (optional) | see below | With none set, reports are only written to `reports/` (and saved as GitHub Actions artifacts). |

**Delivery channels.** Each one turns on when its variables are set:
- **Telegram:** `TELEGRAM_BOT_TOKEN` (from @BotFather) and `TELEGRAM_CHAT_ID`. Sends the short digest.
- **Slack:** `SLACK_WEBHOOK_URL`. Sends the short digest.
- **Email:** `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` (comma-separated). Sends the full HTML report. For Gmail, use `smtp.gmail.com` with an app password.

## Option A: run on GitHub Actions (no server needed)

The workflow at `.github/workflows/x-scanner.yml` runs at 00:17, 06:17, 12:17 and 18:17 UTC.

1. In the repo, open **Settings → Secrets and variables → Actions** and add `X_BEARER_TOKEN`,
   `ANTHROPIC_API_KEY` and the secrets for whichever delivery channel you want.
2. The schedule only runs from the **default branch**, so merge this branch into `master`.
3. To test, open **Actions → "X market & news scan" → Run workflow**.
4. Each run uploads the report as an artifact. To also commit every briefing to `x_scanner/reports/`,
   add the repository *variable* `COMMIT_REPORTS` = `true`.

## Option B: run locally or on a server

```bash
cd x_scanner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export X_BEARER_TOKEN=... ANTHROPIC_API_KEY=...   # plus any delivery vars

python -m x_scanner.main            # one scan now
python -m x_scanner.main --loop     # keep running, scan every lookback_hours
```

Or use cron: `17 */6 * * * cd /path/to/x_scanner && .venv/bin/python -m x_scanner.main`

## Customising

Edit `config.yaml`:
- **queries:** X search syntax, e.g. add `($PLTR OR $COIN)` or a sector you follow.
- **accounts:** handles whose posts are always included, whatever their engagement
  (e.g. analysts or news outlets you trust).
- **lookback_hours:** keep it equal to the schedule interval.
- **min_likes / posts_per_category_for_llm:** the trade-off between noise and coverage.
- **New categories:** add another block under `categories:`. It is picked up automatically.

## Tests

```bash
cd x_scanner && pip install pytest && python -m pytest -q
```

The tests run offline: they make no X or Claude calls.

> This tool summarises what people are saying on social media. It is not investment advice,
> and claims in posts are not verified.
