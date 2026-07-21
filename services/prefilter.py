"""Cheap, free keyword gate run before any LLM call.

Decides whether an article's headline/snippet is even worth an impact rating,
so we don't spend a Claude call on obviously-routine news. Uses word-boundary
matching so "war" doesn't match "warehouse".
"""
import re

import config

_pattern = None
_block_pattern = None


def _compile(terms):
    # Longest-first so multi-word phrases match before their sub-words.
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(
        r"\b(" + "|".join(re.escape(k) for k in ordered) + r")\b",
        re.IGNORECASE,
    )


def _get_pattern():
    global _pattern
    if _pattern is None:
        _pattern = _compile(config.PREFILTER_KEYWORDS)
    return _pattern


def _get_block_pattern():
    global _block_pattern
    if _block_pattern is None and config.PREFILTER_BLOCK:
        _block_pattern = _compile(config.PREFILTER_BLOCK)
    return _block_pattern


def is_relevant(article: dict) -> bool:
    """True if the article should proceed to LLM analysis.

    An article must match a keyword AND not match the blocklist. The blocklist
    catches recurring prediction/recommendation columns that would otherwise
    pass on a keyword like "saham" or "bitcoin".
    """
    if not config.PREFILTER_ENABLED:
        return True
    text = f"{article.get('title', '')} {article.get('description', '')}"

    block = _get_block_pattern()
    if block is not None and block.search(text):
        return False

    return bool(_get_pattern().search(text))
