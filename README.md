# Discord Market News Bot

Updates you on news impacting **US stocks**, **Indonesian (IDX) stocks**, and **crypto**,
with Claude-powered summaries + impact analysis, plus on-demand price and technical-rating
commands.

## Features

- **Auto-push news** — polls RSS + GNews + NewsAPI every N minutes, sends each fresh
  headline to Claude for a summary + sentiment/impact assessment, and posts a clean embed
  to per-market channels (de-duplicated so you never see the same story twice).
- **Slash commands:**
  - `/ping` — health check
  - `/price <symbol> [market]` — current price (e.g. `AAPL`, `BBCA.JK`, `BTC`)
  - `/news <market>` — latest analyzed headlines (`us` / `id` / `crypto`)
  - `/ta <symbol> <exchange> <screener> [interval]` — TradingView technical rating
    (e.g. `AAPL NASDAQ america`, `BBCA IDX indonesia`, `BTCUSDT BINANCE crypto`)
  - `/watch add|remove|list` — manage a watchlist

## Data sources

| Concern | Source | Key needed? |
|---|---|---|
| US + IDX prices | yfinance (Yahoo Finance) | No |
| Crypto prices | CoinGecko | No (optional key for higher limits) |
| News | RSS feeds + GNews + NewsAPI | RSS: no · GNews/NewsAPI: yes |
| Analysis | Claude (Haiku by default) | Yes (Anthropic) |
| Technical rating | TradingView via `tradingview-ta` (unofficial) | No |

## Setup

1. **Install Python 3.11+**, then install dependencies:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. **Create your `.env`** from the template and fill in your keys:
   ```powershell
   copy .env.example .env
   ```
   Required: `DISCORD_BOT_TOKEN`, `ANTHROPIC_API_KEY`.
   Optional: `GNEWS_KEY`, `NEWSAPI_KEY`, `COINGECKO_API_KEY`.
   The channel IDs are pre-filled for your server.

3. **Run the bot:**
   ```powershell
   python bot.py
   ```

On startup it registers the slash commands, does one initial news poll after ~20 seconds,
then polls on the configured interval.

## Configuration (.env)

| Var | Default | Notes |
|---|---|---|
| `POLL_INTERVAL_MINUTES` | 15 | How often to poll for news |
| `MAX_ARTICLES_PER_POLL` | 5 | Cap per market per poll (limits first-run burst) |
| `ANALYSIS_MODEL` | `claude-haiku-4-5` | Swap to `claude-sonnet-5` for deeper analysis |
| `DB_PATH` | `bot.db` | SQLite file for de-dup + watchlist |

## Notes & next steps

- **First run** posts up to `MAX_ARTICLES_PER_POLL` recent items per market, then only
  brand-new stories after that.
- **RSS feeds** in `services/news.py` are a starting set — adjust the lists to taste.
- **Cost:** Haiku analysis is ~$0.0015/article; a normal day stays well under a few dollars.
- **Enhancements to consider:** escalate `impact: high` items to Sonnet, filter news by your
  `/watch` list, price alerts on thresholds, and per-market TA auto-enrichment.

_Informational only — not financial advice._

## Project layout

```
bot.py              # entry point + slash commands
config.py           # env loading
scheduler.py        # APScheduler auto-push job
services/
  prices.py         # yfinance + CoinGecko
  news.py           # RSS + GNews + NewsAPI aggregation
  analysis.py       # Claude summary + impact
  technical.py      # TradingView rating (optional)
  publisher.py      # Discord embeds
storage/
  db.py             # SQLite: seen-articles cache + watchlist
```
