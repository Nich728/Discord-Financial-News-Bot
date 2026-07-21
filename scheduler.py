"""Scheduled auto-push: poll news per market, analyze, and post to channels."""
import asyncio
import random
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from services import analysis, news, prefilter, publisher
from storage import db

IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}


async def poll_market(bot, market: str):
    channel_id = config.CHANNELS.get(market)
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        print(f"[scheduler] channel for '{market}' not found (id={channel_id})")
        return

    try:
        articles = await asyncio.to_thread(news.fetch_all, market)
    except Exception as e:  # noqa: BLE001
        print(f"[scheduler] fetch failed for {market}: {e}")
        return

    min_rank = IMPACT_RANK.get(config.MIN_IMPACT, 3)

    # Free keyword gate -> collect unseen candidates + track what got dropped.
    dropped = []
    candidates = []
    for article in articles:
        if len(candidates) >= config.MAX_SCAN_PER_POLL:
            break
        if db.is_seen(article["url"]):
            continue
        if not prefilter.is_relevant(article):
            db.mark_seen(article["url"])
            dropped.append(article)
            continue
        candidates.append(article)

    posted = 0
    summarized = 0
    if candidates:
        # Stage 1: ONE cheap batched call rates all candidates.
        impacts = await asyncio.to_thread(analysis.classify_batch, candidates)
        if impacts is None:
            # API failed (e.g. 529 overloaded). Leave these unseen so the whole
            # batch is retried next poll rather than silently lost.
            print(
                f"[scheduler] {market}: classify failed — retrying "
                f"{len(candidates)} article(s) next poll"
            )
            return

        # Classified successfully — don't reconsider these next poll.
        for article in candidates:
            db.mark_seen(article["url"])

        # Stage 2: full summary only for the ones that clear the impact bar.
        for article, impact in zip(candidates, impacts):
            if posted >= config.MAX_ARTICLES_PER_POLL:
                break
            if IMPACT_RANK.get(impact, 1) < min_rank:
                continue
            summarized += 1
            result = await asyncio.to_thread(analysis.analyze_article, article)
            if result is None:
                continue  # summary failed — skip rather than post a stub
            result["impact"] = impact  # keep the strict stage-1 verdict
            try:
                await channel.send(embed=publisher.build_news_embed(article, result))
                posted += 1
            except Exception as e:  # noqa: BLE001
                print(f"[scheduler] send failed for {market}: {e}")

    # Optional QA: check whether the keyword gate dropped anything important.
    if config.AUDIT_GATE and dropped:
        await _audit_dropped(market, dropped, min_rank)

    print(
        f"[scheduler] {market}: fetched {len(articles)}, "
        f"gate-dropped {len(dropped)}, classified {len(candidates)}, "
        f"summarized {summarized}, posted {posted}"
    )


async def _audit_dropped(market: str, dropped: list, min_rank: int):
    """Classify a sample of gate-dropped articles; warn on any important misses.

    Writes flagged misses to gate_audit.log so you can review and add the
    missing keyword(s) to PREFILTER_KEYWORDS.
    """
    sample = (
        dropped
        if len(dropped) <= config.AUDIT_MAX
        else random.sample(dropped, config.AUDIT_MAX)
    )
    impacts = await asyncio.to_thread(analysis.classify_batch, sample)
    if impacts is None:
        return  # audit is best-effort; skip quietly if the API is unavailable
    for article, impact in zip(sample, impacts):
        if IMPACT_RANK.get(impact, 1) >= min_rank:
            line = f"[audit] {market}: gate DROPPED a '{impact}' article -> {article['title']}"
            print(line)
            _log_audit_miss(line, article)


def _log_audit_miss(line: str, article: dict):
    try:
        with open("gate_audit.log", "a", encoding="utf-8") as f:
            f.write(f"{line}\n    {article.get('url', '')}\n")
    except Exception:  # noqa: BLE001
        pass


async def poll_all(bot):
    for market in config.MARKETS:
        await poll_market(bot, market)


def setup_scheduler(bot):
    scheduler = AsyncIOScheduler()
    # Recurring poll.
    scheduler.add_job(
        poll_all,
        "interval",
        minutes=config.POLL_INTERVAL_MINUTES,
        args=[bot],
        id="poll_all",
        max_instances=1,
        coalesce=True,
    )
    # One initial poll shortly after startup so you see it working right away.
    scheduler.add_job(
        poll_all,
        "date",
        run_date=datetime.now() + timedelta(seconds=20),
        args=[bot],
        id="poll_all_initial",
    )
    scheduler.start()
    print(f"[scheduler] started — polling every {config.POLL_INTERVAL_MINUTES} min")
    return scheduler
