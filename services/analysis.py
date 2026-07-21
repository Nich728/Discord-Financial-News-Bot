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
- "low": routine updates, opinion/analysis pieces, minor announcements, rumors,
  listicles, price recaps, promotional or how-to content.

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


def _parse_impacts(text: str, n: int):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    impacts = ["high"] * n  # fail-open: if unsure, let it through to summary
    raw = text
    if not raw.startswith("["):
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            raw = match.group(0)
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return impacts
    for obj in data if isinstance(data, list) else []:
        try:
            i = int(obj.get("index"))
            impact = (obj.get("impact") or "").lower()
        except Exception:  # noqa: BLE001
            continue
        if 0 <= i < n and impact in ("high", "medium", "low"):
            impacts[i] = impact
    return impacts


def classify_batch(articles: list):
    """Rate many headlines in ONE cheap call (tiny output per item).

    Returns a list of "high"/"medium"/"low" aligned with `articles`, or None if
    the API call failed — the caller should then retry the batch next poll
    rather than guessing (guessing "high" would post unanalyzed articles).
    """
    if not articles:
        return []
    lines = []
    for i, a in enumerate(articles):
        desc = (a.get("description", "") or "")[:200]
        lines.append(f"{i}. [{a.get('market', '')}] {a.get('title', '')} — {desc}")
    prompt = (
        "Rate the likely market impact of each numbered headline as "
        '"high", "medium", or "low".\n\n'
        + "\n".join(lines)
        + "\n\nRespond with ONLY a JSON array, one object per headline, reusing "
        'the same indices: [{"index": 0, "impact": "low"}, ...]'
    )
    try:
        resp = _client.messages.create(
            model=config.ANALYSIS_MODEL,
            max_tokens=20 + 15 * len(articles),
            system=_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return _parse_impacts(text, len(articles))
    except Exception as e:  # noqa: BLE001
        print(f"[analysis] classify failed: {e}")
        return None
