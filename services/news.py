"""News aggregation — RSS only, de-duplicated by URL. No API keys, no rate limits.

Two RSS sources per market:
  1. Curated outlet feeds (CNBC, Yahoo Finance, CoinDesk, ...).
  2. Google News RSS *search* — keyword-scoped, aggregates many outlets
     (Bloomberg, Reuters, CNBC, etc.) in real time, for free.

Each feed is wrapped in try/except so one failing feed never kills a poll.
Returns a list of article dicts:
    {title, url, source, description, published, market}
Synchronous — call via asyncio.to_thread from the async bot.
"""
from urllib.parse import urlencode

import feedparser
import httpx

# Bound every feed request so one unresponsive server can't stall a whole poll.
_HTTP_TIMEOUT = 15  # seconds
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DiscordFinanceBot/1.0)"}


def _parse_feed(url: str):
    """Download a feed with a hard timeout, then parse the bytes.

    feedparser.parse(url) has NO timeout and can hang forever on a dead server,
    which would freeze the scheduler. Fetching via httpx bounds each request.
    """
    resp = httpx.get(url, timeout=_HTTP_TIMEOUT, follow_redirects=True, headers=_HEADERS)
    resp.raise_for_status()
    return feedparser.parse(resp.content)

# Curated outlet RSS feeds per market. Adjust freely — these need no API key.
RSS_FEEDS = {
    "us": [
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://finance.yahoo.com/news/rssindex",
        # BRICS / de-dollarization — real geopolitical + currency events.
        # (Watcher.guru's general feed is skipped: it's mostly price targets.)
        "https://watcher.guru/news/category/brics/feed",
    ],
    "id": [
        "https://www.cnbcindonesia.com/market/rss",
        "https://www.kontan.co.id/rss",
        "https://www.bloombergtechnoz.com/rss",
    ],
    "crypto": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
        # Watcher.guru category feeds. Heavy on price commentary, so most items
        # are dropped by the blocklist or rated "low" — kept for event coverage.
        "https://watcher.guru/news/category/bitcoin/feed",
        "https://watcher.guru/news/category/ethereum/feed",
    ],
}

# Google News RSS search — free, no key, keyword-scoped, real-time.
# Each market has a LIST of queries; add more outlets with a site: filter.
# hl/gl/ceid localize the results (language / country / edition).
# Bloomberg's own RSS is discontinued, but a `site:bloomberg.com` Google News
# query surfaces its headlines (analysis uses the headline + snippet, which are
# available even though the full article is paywalled).
GOOGLE_NEWS = {
    "us": [
        {"q": "stock market OR S&P 500 OR Nasdaq OR Federal Reserve OR earnings",
         "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"q": "site:bloomberg.com (markets OR stocks OR economy OR Fed OR earnings)",
         "hl": "en-US", "gl": "US", "ceid": "US:en"},
    ],
    "id": [
        {"q": "IHSG OR saham OR ekonomi Indonesia OR Bank Indonesia OR rupiah",
         "hl": "id", "gl": "ID", "ceid": "ID:id"},
        {"q": "site:bloomberg.com Indonesia (markets OR economy OR rupiah)",
         "hl": "en-US", "gl": "US", "ceid": "US:en"},
    ],
    "crypto": [
        {"q": "cryptocurrency OR bitcoin OR ethereum OR crypto market",
         "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"q": "site:bloomberg.com (crypto OR bitcoin OR ethereum)",
         "hl": "en-US", "gl": "US", "ceid": "US:en"},
    ],
}


def _fetch_rss(market: str):
    out = []
    for url in RSS_FEEDS.get(market, []):
        try:
            feed = _parse_feed(url)
            source = feed.feed.get("title", url)
            for entry in feed.entries[:15]:
                link = entry.get("link")
                if not link:
                    continue
                out.append({
                    "title": entry.get("title", "(untitled)"),
                    "url": link,
                    "source": source,
                    "description": (entry.get("summary", "") or "")[:600],
                    "published": entry.get("published", ""),
                    "market": market,
                })
        except Exception as e:  # noqa: BLE001 - one bad feed shouldn't stop the rest
            print(f"[news] RSS error ({url}): {e}")
    return out


def _fetch_google_news(market: str):
    out = []
    for cfg in GOOGLE_NEWS.get(market, []):
        url = "https://news.google.com/rss/search?" + urlencode({
            "q": cfg["q"], "hl": cfg["hl"], "gl": cfg["gl"], "ceid": cfg["ceid"],
        })
        try:
            feed = _parse_feed(url)
            for entry in feed.entries[:15]:
                link = entry.get("link")
                if not link:
                    continue
                # Google News puts the outlet name in <source> and appends
                # " - Source" to the title; pull it out and clean the title.
                source = (entry.get("source") or {}).get("title", "") or "Google News"
                title = entry.get("title", "(untitled)")
                if source and title.endswith(f" - {source}"):
                    title = title[: -len(f" - {source}")]
                out.append({
                    "title": title,
                    "url": link,
                    "source": source,
                    "description": (entry.get("summary", "") or "")[:600],
                    "published": entry.get("published", ""),
                    "market": market,
                })
        except Exception as e:  # noqa: BLE001
            print(f"[news] Google News error ({market}, {cfg['q'][:30]}...): {e}")
    return out


def fetch_all(market: str):
    """Aggregate outlet RSS + Google News RSS; de-dupe by URL (order preserved)."""
    articles = _fetch_rss(market) + _fetch_google_news(market)
    seen, unique = set(), []
    for a in articles:
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        unique.append(a)
    return unique
