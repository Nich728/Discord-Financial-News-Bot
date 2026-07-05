"""News aggregation: RSS (no key) + GNews + NewsAPI, de-duplicated by URL.

Each source is wrapped in try/except so one failing feed never kills a poll.
Returns a list of article dicts:
    {title, url, source, description, published, market}
Synchronous — call via asyncio.to_thread from the async bot.
"""
import feedparser
import httpx

import config

# Curated RSS feeds per market. Adjust freely — these need no API key.
RSS_FEEDS = {
    "us": [
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://finance.yahoo.com/news/rssindex",
    ],
    "id": [
        "https://www.cnbcindonesia.com/market/rss",
        "https://www.kontan.co.id/rss",
    ],
    "crypto": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
    ],
}

# Query terms per market for the keyword-based APIs.
GNEWS_QUERY = {
    "us": ("stock market", "en", "us"),
    "id": ("saham IHSG", "id", "id"),
    "crypto": ("cryptocurrency", "en", None),
}
NEWSAPI_QUERY = {
    "us": {"category": "business", "country": "us", "_endpoint": "top-headlines"},
    "id": {"q": "saham OR IHSG OR ekonomi", "language": "id", "_endpoint": "everything"},
    "crypto": {"q": "cryptocurrency OR bitcoin", "language": "en", "_endpoint": "everything"},
}


def _fetch_rss(market: str):
    out = []
    for url in RSS_FEEDS.get(market, []):
        try:
            feed = feedparser.parse(url)
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


def _fetch_gnews(market: str):
    if not config.GNEWS_KEY:
        return []
    query, lang, country = GNEWS_QUERY[market]
    params = {"q": query, "lang": lang, "max": 10, "apikey": config.GNEWS_KEY}
    if country:
        params["country"] = country
    try:
        r = httpx.get("https://gnews.io/api/v4/search", params=params, timeout=15)
        r.raise_for_status()
        return [{
            "title": a.get("title", "(untitled)"),
            "url": a.get("url"),
            "source": (a.get("source") or {}).get("name", "GNews"),
            "description": (a.get("description", "") or "")[:600],
            "published": a.get("publishedAt", ""),
            "market": market,
        } for a in r.json().get("articles", []) if a.get("url")]
    except Exception as e:  # noqa: BLE001
        print(f"[news] GNews error ({market}): {e}")
        return []


def _fetch_newsapi(market: str):
    if not config.NEWSAPI_KEY:
        return []
    cfg = dict(NEWSAPI_QUERY[market])
    endpoint = cfg.pop("_endpoint")
    cfg["apiKey"] = config.NEWSAPI_KEY
    cfg["pageSize"] = 10
    if endpoint == "everything":
        cfg["sortBy"] = "publishedAt"
    try:
        r = httpx.get(f"https://newsapi.org/v2/{endpoint}", params=cfg, timeout=15)
        r.raise_for_status()
        return [{
            "title": a.get("title", "(untitled)"),
            "url": a.get("url"),
            "source": (a.get("source") or {}).get("name", "NewsAPI"),
            "description": (a.get("description", "") or "")[:600],
            "published": a.get("publishedAt", ""),
            "market": market,
        } for a in r.json().get("articles", []) if a.get("url")]
    except Exception as e:  # noqa: BLE001
        print(f"[news] NewsAPI error ({market}): {e}")
        return []


def fetch_all(market: str):
    """Aggregate all sources for a market and de-dupe by URL (order preserved)."""
    articles = _fetch_rss(market) + _fetch_gnews(market) + _fetch_newsapi(market)
    seen, unique = set(), []
    for a in articles:
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        unique.append(a)
    return unique
