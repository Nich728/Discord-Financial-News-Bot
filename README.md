# Discord Financial News Bot

Monitors news impacting **US stocks**, **Indonesian (IDX) stocks**, and **crypto**, uses
Claude to judge market impact, and auto-posts only the significant stories to per-market
Discord channels — plus on-demand price and technical-rating commands.

## Features

- **Auto-push news** — polls RSS feeds every N minutes and posts only **high-impact**
  stories (macro data, central-bank decisions, geopolitical shocks, major corporate news)
  as clean embeds, de-duplicated so you never see the same story twice.
- **Three-stage cost filter** (see below) keeps LLM spend low.
- **Slash commands:**
  - `/ping` — health check
  - `/price <symbol> [market]` — current price (e.g. `AAPL`, `BBCA` + market `id`, `BTC`)
  - `/news <market>` — latest analyzed headlines (`us` / `id` / `crypto`)
  - `/ta <symbol> <exchange> <screener> [interval]` — TradingView technical rating
    (e.g. `AAPL NASDAQ america`, `BBCA IDX indonesia`, `BTCUSDT BINANCE crypto`)
  - `/watch add|remove|list` — manage a watchlist

## How the filtering pipeline works

Each poll runs a funnel designed to spend as little on the LLM as possible:

```
Fetch RSS  →  Keyword gate  →  Stage 1: batched classify  →  Stage 2: full summary  →  post
 (free)         (free)              (cheap, 1 call)            (only high-impact)
```

1. **Keyword gate** (`services/prefilter.py`) — a local word-boundary match against
   `PREFILTER_KEYWORDS`. Obvious noise is dropped at **zero cost**.
2. **Stage 1 — classify** — all survivors are rated `high`/`medium`/`low` in **one** batched
   Claude call with tiny output per item.
3. **Stage 2 — summarize** — only articles meeting `MIN_IMPACT` get the full (pricier)
   summary + sentiment + rationale, then get posted.

Each poll logs the funnel:
```
[scheduler] us: fetched 75, gate-dropped 60, classified 15, summarized 1, posted 1
```

## Data sources

| Concern | Source | Key needed? |
|---|---|---|
| US + IDX prices | yfinance (Yahoo Finance) | No |
| Crypto prices | CoinGecko | No (optional key for higher limits) |
| News | Outlet RSS + **Google News RSS search** (incl. Bloomberg via `site:` filter) | **No** |
| Analysis | Claude (Haiku by default) | Yes (Anthropic) |
| Technical rating | TradingView via `tradingview-ta` (unofficial) | No |

News requires **no API keys** — Google News RSS provides keyword-scoped, real-time results
across many outlets with no rate limits.

## Local setup

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
   Required: `DISCORD_BOT_TOKEN`, `ANTHROPIC_API_KEY`, and the three `CHANNEL_ID_*` values.

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
| `MAX_ARTICLES_PER_POLL` | 3 | Max articles **posted** per market per poll |
| `MAX_SCAN_PER_POLL` | 15 | Max articles **classified** per market per poll (bounds cost) |
| `MIN_IMPACT` | `high` | Only post at/above this impact (`high`/`medium`/`low`) |
| `PREFILTER_ENABLED` | `true` | The free keyword gate; `false` = analyze everything |
| `PREFILTER_KEYWORDS` | built-in list | Optional comma-separated override |
| `AUDIT_GATE` | `false` | QA mode — see below |
| `AUDIT_MAX` | 10 | Max gate-dropped articles audited per market per poll |
| `ANALYSIS_MODEL` | `claude-haiku-4-5` | Swap to `claude-sonnet-5` for deeper analysis |
| `DB_PATH` | `bot.db` | SQLite file for de-dup + watchlist |

### Tuning the keyword gate (`AUDIT_GATE`)

The gate's one risk is dropping an important article that happens to use none of your
keywords. To find those, set `AUDIT_GATE=true` and restart. Gate-dropped articles then get
classified too, and any that come back high-impact are flagged:

```
[audit] us: gate DROPPED a 'high' article -> Powell signals rate pause
```

They're also appended to `gate_audit.log`. Add the missing word(s) to `PREFILTER_KEYWORDS`,
then set `AUDIT_GATE=false` to stop the extra cost. It's a tuning tool, not a permanent mode.

## Deployment (24/7 on a Linux VPS)

Tested on **Ubuntu 24.04** (DigitalOcean). Runs as a systemd service so it starts on boot
and restarts automatically if it crashes.

### 1. Server prep

```bash
# as root on a fresh droplet
adduser botuser
usermod -aG sudo botuser
rsync --archive --chown=botuser:botuser ~/.ssh /home/botuser
ufw allow OpenSSH
ufw enable
```

Then reconnect as `botuser` and install prerequisites:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git tmux
```

> **Run long commands inside `tmux`.** If SSH drops mid-`apt upgrade`, the work continues
> on the server; reconnect and `tmux attach`. A dropped connection during a package
> configure can leave SSH itself broken.

### 2. Clone and install

```bash
cd ~
git clone https://github.com/Nich728/Discord-Financial-News-Bot.git
cd Discord-Financial-News-Bot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Create `.env` on the server

`.env` is gitignored, so create it directly on the box:

```bash
nano .env      # paste your real values
chmod 600 .env # readable only by you
```

Test it runs before daemonizing:
```bash
python bot.py    # Ctrl+C once you see it log in
```

### 4. Install the systemd service

A ready-made unit lives at [`deploy/discordbot.service`](deploy/discordbot.service):

```bash
sudo cp deploy/discordbot.service /etc/systemd/system/discordbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now discordbot
sudo systemctl status discordbot     # expect "active (running)"
```

Adjust `User=` and the paths in the unit if you deploy elsewhere.

### 5. Logs and updates

```bash
journalctl -u discordbot -f          # live logs
journalctl -u discordbot -n 100      # recent history

# deploy an update
cd ~/Discord-Financial-News-Bot
git pull
source .venv/bin/activate
pip install -r requirements.txt      # only if requirements changed
sudo systemctl restart discordbot
```

> Only run **one** instance. If the bot is also running on your PC, stop it — two instances
> post duplicate alerts to the same channels.

## Notes

- **First run** posts up to `MAX_ARTICLES_PER_POLL` recent items per market, then only
  brand-new stories after that.
- **Feeds and queries** live at the top of `services/news.py` — add outlets with a
  `site:example.com` Google News query, or drop in more RSS URLs.
- **Cost:** with the gate + two-stage funnel, typical spend is a few dollars a month on
  Haiku. Watch the `gate-dropped` vs `summarized` counts to see the savings.
- **Timeouts:** every feed request (15s) and LLM call (60s) is bounded so one dead server
  can't stall the scheduler.

_Informational only — not financial advice._

## Project layout

```
bot.py              # entry point + slash commands
config.py           # env loading + keyword list
scheduler.py        # APScheduler poll job + gate audit
services/
  prices.py         # yfinance + CoinGecko
  news.py           # outlet RSS + Google News RSS aggregation
  prefilter.py      # free keyword gate
  analysis.py       # Claude classify (stage 1) + summary (stage 2)
  technical.py      # TradingView rating (optional)
  publisher.py      # Discord embeds
storage/
  db.py             # SQLite: seen-articles cache + watchlist
deploy/
  discordbot.service  # systemd unit for 24/7 VPS hosting
```
