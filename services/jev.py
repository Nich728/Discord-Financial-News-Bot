"""Jev (TypeSafe System One) impact classifier — runs alongside Haiku.

Shadow-trial: each candidate is rated by both models; the scheduler posts if
EITHER rates it at/above the bar, and the embed shows both verdicts so they can
be compared. Jev supports Indonesian, so headlines are sent as-is.

Synchronous — call via asyncio.to_thread. Returns None when Jev is disabled,
not installed, or the call fails, so the pipeline falls back to Haiku alone.
"""
import config

try:
    from typesafe_sdk import Choice, TypeSafeClient
except ImportError:  # SDK needs Python >= 3.10; stay optional
    Choice = TypeSafeClient = None

# Same definitions as the Haiku classify prompt, so both judge the same standard.
_IMPACT_QUESTION = None
if Choice is not None:
    _IMPACT_QUESTION = Choice(
        instructions=(
            "How much is this news likely to move financial markets? Commentary "
            "ABOUT the market is not the same as an event that MOVES the market."
        ),
        criteria={
            "high": (
                "An event that has already happened and moves markets: macroeconomic "
                "data releases (CPI, GDP, jobs), central-bank or Fed rate decisions, "
                "geopolitical shocks (war, strikes, sanctions), systemic financial "
                "events, major regulatory rulings, or large-cap earnings/M&A that "
                "move a whole sector or index."
            ),
            "medium": "Notable single-company news or sector moves that actually occurred.",
            "low": (
                "Everything else: predictions, forecasts, price targets, stock "
                "recommendations, analyst opinion, technical analysis, daily market "
                "outlook or 'stocks to watch' columns, routine price recaps, "
                "listicles, how-to or explainer content, and rumors."
            ),
        },
    )

# Which channel an article belongs to. Mirrors the Haiku routing rules.
_MARKET_QUESTION = None
if Choice is not None:
    _MARKET_QUESTION = Choice(
        instructions="Which market is this news primarily about?",
        criteria={
            "us": "US stocks or markets, the Federal Reserve, US economic data, or US companies.",
            "id": (
                "Indonesian stocks or economy: IHSG, the rupiah, Bank Indonesia, "
                "Indonesian government economic policy, or Indonesian companies."
            ),
            "crypto": "Cryptocurrency, bitcoin, ethereum, stablecoins, or crypto markets and exchanges.",
            "global": (
                "International news that moves markets but is not mainly about the US, "
                "Indonesia, or crypto: geopolitics (war, sanctions), oil/OPEC and "
                "commodities, other economies (China, Europe, Japan), global trade "
                "and tariffs, or BRICS."
            ),
        },
    )

_client = None


def enabled() -> bool:
    return bool(config.JEV_ENABLED and TypeSafeClient is not None)


def _get_client():
    global _client
    if _client is None:
        # Reads TYPESAFE_API_KEY from the environment (loaded from .env).
        _client = TypeSafeClient(timeout=15.0)
    return _client


def classify(article: dict):
    """Rate impact AND pick the market (channel) in one Jev call.

    Returns {"impact", "confidence", "market", "market_confidence"} or None.
    """
    if not enabled():
        return None
    state = {
        "headline": article.get("title", ""),
        "snippet": (article.get("description", "") or "")[:300],
        "source": article.get("source", ""),
    }
    try:
        # Both questions go in one request; Jev evaluates them in parallel.
        response = _get_client().system_one(
            state=state,
            questions={"impact": _IMPACT_QUESTION, "market": _MARKET_QUESTION},
        )
        impact = response.choices["impact"]
        market = response.choices["market"]
        return {
            "impact": impact.choice,
            "confidence": float(impact.confidence),
            "market": market.choice,
            "market_confidence": float(market.confidence),
        }
    except Exception as e:  # noqa: BLE001 - Jev is optional; never break a poll
        print(f"[jev] classify failed: {type(e).__name__}: {e}")
        return None


def classify_impact(article: dict):
    """Backwards-compatible alias (used by the smoke-test command)."""
    return classify(article)
