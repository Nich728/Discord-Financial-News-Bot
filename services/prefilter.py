"""Cheap, free keyword gate run before any LLM call.

Decides whether an article's headline/snippet is even worth an impact rating,
so we don't spend a Claude call on obviously-routine news. Uses word-boundary
matching so "war" doesn't match "warehouse".
"""
import re

import config

_pattern = None


def _get_pattern():
    global _pattern
    if _pattern is None:
        # Longest-first so multi-word phrases match before their sub-words.
        keywords = sorted(config.PREFILTER_KEYWORDS, key=len, reverse=True)
        _pattern = re.compile(
            r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
            re.IGNORECASE,
        )
    return _pattern


def is_relevant(article: dict) -> bool:
    """True if the article should proceed to LLM analysis."""
    if not config.PREFILTER_ENABLED:
        return True
    text = f"{article.get('title', '')} {article.get('description', '')}"
    return bool(_get_pattern().search(text))
