"""Tiny SQLite layer: de-dup cache for articles + a watchlist."""
import sqlite3
import threading
import time

import config

_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _lock, _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS seen_articles ("
            " url TEXT PRIMARY KEY, created_at REAL)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS watchlist ("
            " symbol TEXT, market TEXT, PRIMARY KEY (symbol, market))"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS posted_stories ("
            " title TEXT, market TEXT, posted_at REAL)"
        )


def add_posted_story(title: str, market: str):
    """Record a story we posted, for cross-poll duplicate detection."""
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO posted_stories (title, market, posted_at) VALUES (?, ?, ?)",
            (title, market, time.time()),
        )
        # Keep the table small — anything older than 7 days is irrelevant.
        c.execute(
            "DELETE FROM posted_stories WHERE posted_at < ?",
            (time.time() - 7 * 86400,),
        )


def recent_posted_stories(market: str = None, hours: int = 48, limit: int = 25):
    """Titles posted in the last `hours`, newest first.

    Pass market=None to get titles across ALL channels (used for dedup, since
    articles are routed to a channel by topic, not by the feed they came from).
    """
    cutoff = time.time() - hours * 3600
    with _lock, _conn() as c:
        if market is None:
            rows = c.execute(
                "SELECT title FROM posted_stories WHERE posted_at > ?"
                " ORDER BY posted_at DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT title FROM posted_stories"
                " WHERE market = ? AND posted_at > ?"
                " ORDER BY posted_at DESC LIMIT ?",
                (market, cutoff, limit),
            ).fetchall()
        return [r["title"] for r in rows]


def is_seen(url: str) -> bool:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT 1 FROM seen_articles WHERE url = ?", (url,)
        ).fetchone()
        return row is not None


def mark_seen(url: str):
    with _lock, _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen_articles (url, created_at) VALUES (?, ?)",
            (url, time.time()),
        )


def add_watch(symbol: str, market: str):
    with _lock, _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO watchlist (symbol, market) VALUES (?, ?)",
            (symbol.upper(), market),
        )


def remove_watch(symbol: str, market: str):
    with _lock, _conn() as c:
        c.execute(
            "DELETE FROM watchlist WHERE symbol = ? AND market = ?",
            (symbol.upper(), market),
        )


def list_watch():
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT symbol, market FROM watchlist ORDER BY market, symbol"
        ).fetchall()
        return [dict(r) for r in rows]
