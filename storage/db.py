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
