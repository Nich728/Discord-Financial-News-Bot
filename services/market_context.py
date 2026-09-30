"""Live market snapshot fed to the Stage 2 prompt.

The model has no live data of its own, so "how does this news affect the market
right now" needs real figures supplied. This pulls a small set of macro
indicators from Yahoo Finance (free, same source as /price) plus the stories the
bot recently posted, and formats them as plain text for the prompt.

Cached for 10 minutes so one poll (three markets, several articles) fetches
the data once. Synchronous — call via asyncio.to_thread.
"""
import time
from datetime import datetime

import yfinance as yf

from storage import db

# (ticker, label, kind) — kind "yield" values are percentages, so their daily
# move is shown in percentage points rather than percent change.
INDICATORS = [
    ("^GSPC", "S&P 500", "index"),
    ("^IXIC", "Nasdaq Composite", "index"),
    ("^VIX", "VIX (US volatility)", "index"),
    ("^TNX", "US 10Y Treasury yield", "yield"),
    ("^IRX", "US 13-week T-bill yield", "yield"),
    ("DX-Y.NYB", "US Dollar Index (DXY)", "index"),
    ("^JKSE", "IHSG (Jakarta Composite)", "index"),
    ("IDR=X", "USD/IDR", "fx"),
    ("CL=F", "WTI crude oil (USD/bbl)", "commodity"),
    ("GC=F", "Gold (USD/oz)", "commodity"),
    ("BTC-USD", "Bitcoin (USD)", "crypto"),
]

_CACHE_TTL = 600  # seconds
_cache = {"text": "", "at": 0.0}


def _format_line(label: str, kind: str, closes) -> str:
    last = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) >= 2 else last
    first = float(closes.iloc[0])
    if kind == "yield":
        return (
            f"- {label}: {last:.2f}% "
            f"(1d {last - prev:+.2f} pts, 5d {last - first:+.2f} pts)"
        )
    d1 = (last - prev) / prev * 100 if prev else 0.0
    d5 = (last - first) / first * 100 if first else 0.0
    return f"- {label}: {last:,.2f} (1d {d1:+.2f}%, 5d {d5:+.2f}%)"


def _fetch_snapshot() -> str:
    tickers = [t for t, _, _ in INDICATORS]
    data = yf.download(
        tickers, period="7d", interval="1d", group_by="ticker",
        auto_adjust=False, progress=False, threads=True,
    )
    lines = []
    for ticker, label, kind in INDICATORS:
        try:
            closes = data[ticker]["Close"].dropna().tail(6)  # ~5 trading days
            if len(closes) == 0:
                continue
            lines.append(_format_line(label, kind, closes))
        except Exception:  # noqa: BLE001 - one missing ticker shouldn't sink the rest
            continue
    if not lines:
        return ""
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    return f"Market snapshot (Yahoo Finance, as of {stamp}):\n" + "\n".join(lines)


def get_snapshot() -> str:
    """Cached market snapshot text, or "" if it can't be fetched."""
    now = time.time()
    if _cache["text"] and now - _cache["at"] < _CACHE_TTL:
        return _cache["text"]
    try:
        text = _fetch_snapshot()
    except Exception as e:  # noqa: BLE001 - never break a poll over context
        print(f"[market_context] snapshot failed: {type(e).__name__}: {e}")
        text = ""
    if text:
        _cache.update(text=text, at=now)
    return text


def build_context() -> str:
    """Snapshot plus recently posted stories, ready to drop into a prompt."""
    parts = []
    snapshot = get_snapshot()
    parts.append(
        snapshot
        or "Market snapshot: unavailable. Reason from the news alone and do not "
        "state current price or yield levels."
    )
    try:
        recent = db.recent_posted_stories(None, 48, 10)
    except Exception:  # noqa: BLE001
        recent = []
    if recent:
        parts.append(
            "Recent developments the bot already reported (last 48h):\n"
            + "\n".join(f"- {t}" for t in recent)
        )
    return "\n\n".join(parts)
