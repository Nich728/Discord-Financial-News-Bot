"""Claude-powered news analysis: summary + market-impact assessment.

Uses Haiku by default (cheap, fast). Asks for a JSON object and parses it
defensively so a stray code fence or preamble doesn't break the pipeline.
Synchronous — call via asyncio.to_thread from the async bot.
"""
import json
import re

from anthropic import Anthropic

import config

# max_retries handles transient 429/5xx (incl. 529 "overloaded") automatically
# with exponential backoff before an exception ever reaches us.
_client = Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=60.0, max_retries=5)

SYSTEM = (
    "You are a financial news analyst. Rate how much a news item is likely to "
    "move markets. Be strict and skeptical: the large majority of headlines are "
    "routine and should be rated 'low'. Reserve 'high' for genuinely "
    "market-moving events. You are informational only and never give financial advice."
)

_PROMPT = """Headline: {title}
Source: {source}
Snippet: {description}
Market: {market}

Rate the market impact using this guide:
- "high": macroeconomic data (CPI/inflation, central-bank or Fed rate decisions,
  GDP, jobs/unemployment), geopolitical shocks (war, major military strikes,
  sanctions, oil/energy supply shocks), systemic financial events, major
  regulatory or policy changes, or large-cap earnings/M&A that move a whole
  sector or index.
- "medium": notable single-company news, meaningful sector moves, or analyst
  actions with real consequences.
- "low": EVERYTHING ELSE — predictions, forecasts, price targets, stock
  recommendations, analyst opinion, technical analysis, daily outlook or
  "stocks to watch" columns, routine updates, minor announcements, rumors,
  listicles, price recaps, promotional or how-to content. Commentary ABOUT
  the market is not the same as an event that MOVES the market.

Respond with ONLY a JSON object (no prose, no code fences) with these keys:
- "summary": 1-2 sentence plain-English summary
- "sentiment": one of "bullish", "bearish", "neutral"
- "impact": one of "high", "medium", "low" (follow the guide above strictly)
- "tickers": array of affected ticker symbols (may be empty)
- "rationale": one sentence on why this moves the asset or sector"""

_DEFAULT = {
    "summary": "",
    "sentiment": "neutral",
    "impact": "low",
    "tickers": [],
    "rationale": "",
}


def _parse(text: str) -> dict:
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return {**_DEFAULT, **json.loads(text)}
    except Exception:  # noqa: BLE001
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return {**_DEFAULT, **json.loads(match.group(0))}
            except Exception:  # noqa: BLE001
                pass
    # Last resort: return the raw text as the summary so nothing is lost.
    return {**_DEFAULT, "summary": text[:400]}


def analyze_article(article: dict):
    """Stage 2 / on-demand: full summary + impact for a single article.

    Returns None if the API call failed, so callers can skip rather than post
    a degraded embed.
    """
    prompt = _PROMPT.format(
        title=article.get("title", ""),
        source=article.get("source", ""),
        description=article.get("description", "") or "(no snippet)",
        market=article.get("market", ""),
    )
    try:
        resp = _client.messages.create(
            model=config.ANALYSIS_MODEL,
            max_tokens=400,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return _parse(text)
    except Exception as e:  # noqa: BLE001
        print(f"[analysis] summarize failed: {e}")
        return None


# ---- Stage 1: cheap, batched impact classification ----

_CLASSIFY_SYSTEM = (
    "You are a financial news analyst. For each numbered headline, rate how "
    "likely it is to move markets. Be strict: the large majority of headlines "
    "are routine and should be 'low'. Reserve 'high' for genuinely market-moving "
    "events — macroeconomic data, central-bank/Fed decisions, geopolitical "
    "shocks, systemic financial events, or major corporate/regulatory news."
)


def _parse_classifications(text: str, n: int):
    """Parse the classify response into [{"impact": ..., "duplicate": bool}].

    Fail-open on impact ("high" -> proceeds to stage 2, which re-judges) and
    fail-closed on duplicate (False -> never wrongly suppress a story).
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    results = [{"impact": "high", "duplicate": False} for _ in range(n)]
    raw = text
    if not raw.startswith("["):
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            raw = match.group(0)
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return results
    for obj in data if isinstance(data, list) else []:
        try:
            i = int(obj.get("index"))
            impact = (obj.get("impact") or "").lower()
        except Exception:  # noqa: BLE001
            continue
        if 0 <= i < n:
            if impact in ("high", "medium", "low"):
                results[i]["impact"] = impact
            results[i]["duplicate"] = bool(obj.get("duplicate", False))
    return results


def classify_batch(articles: list, recent_titles: list = None):
    """Rate many headlines in ONE cheap call (tiny output per item).

    Returns [{"impact": "high"/"medium"/"low", "duplicate": bool}, ...] aligned
    with `articles`, or None if the API call failed — the caller should then
    retry the batch next poll rather than guessing.

    `recent_titles` (stories already posted) enables duplicate detection: the
    same event covered by many outlets should only be posted once.
    """
    if not articles:
        return []
    lines = []
    for i, a in enumerate(articles):
        desc = (a.get("description", "") or "")[:200]
        lines.append(f"{i}. [{a.get('market', '')}] {a.get('title', '')} — {desc}")

    recent_section = ""
    if recent_titles:
        recent_section = (
            "Stories we ALREADY POSTED recently (a headline about the same "
            "underlying event as any of these is a duplicate):\n"
            + "\n".join(f"- {t}" for t in recent_titles)
            + "\n\n"
        )

    prompt = (
        recent_section
        + "Rate the likely market impact of each numbered headline as "
        '"high", "medium", or "low", using this guide:\n'
        '- "high": ONLY events that have already happened and move markets — '
        "macroeconomic data releases (CPI, GDP, jobs), central-bank/Fed rate "
        "decisions, geopolitical shocks (war, strikes, sanctions), systemic "
        "financial events, major regulatory rulings, or large-cap "
        "earnings/M&A that move a whole sector or index.\n"
        '- "medium": notable single-company news or sector moves that actually '
        "occurred.\n"
        '- "low": EVERYTHING ELSE. This includes predictions, forecasts, price '
        "targets, stock recommendations, analyst opinion, technical analysis, "
        "daily market outlook or 'stocks to watch' columns, routine price "
        "recaps, listicles, how-to and explainer content, and rumors. "
        "Commentary ABOUT the market is not the same as an event that MOVES "
        "the market.\n\n"
        "Be strict: most headlines are 'low'. If a headline only predicts, "
        "recommends, or comments, it is 'low' no matter which assets it names.\n\n"
        + "\n".join(lines)
        + "\n\nAlso set \"duplicate\": true on any headline that covers the same "
        "underlying event/story as (a) one of the already-posted stories above, "
        "or (b) a LOWER-numbered headline in this batch. Different angles on "
        "the same event still count as duplicates.\n\n"
        "Respond with ONLY a JSON array, one object per headline, reusing "
        'the same indices: [{"index": 0, "impact": "low", "duplicate": false}, ...]'
    )
    try:
        resp = _client.messages.create(
            model=config.ANALYSIS_MODEL,
            max_tokens=20 + 25 * len(articles),
            system=_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return _parse_classifications(text, len(articles))
    except Exception as e:  # noqa: BLE001
        print(f"[analysis] classify failed: {e}")
        return None
