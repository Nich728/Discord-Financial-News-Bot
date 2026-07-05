"""Scheduled auto-push: poll news per market, analyze, and post to channels."""
import asyncio
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

    # Free keyword gate -> collect the unseen candidates worth an LLM look.
    gated = 0
    candidates = []
    for article in articles:
        if len(candidates) >= config.MAX_SCAN_PER_POLL:
            break
        if db.is_seen(article["url"]):
            continue
        if not prefilter.is_relevant(article):
            db.mark_seen(article["url"])
            gated += 1
            continue
        candidates.append(article)

    if not candidates:
        if gated:
            print(f"[scheduler] {market}: gate-dropped {gated}, nothing to analyze")
        return

    # These are being handled this cycle — don't reconsider them next poll.
    for article in candidates:
        db.mark_seen(article["url"])

    # Stage 1: ONE cheap batched call rates all candidates.
    impacts = await asyncio.to_thread(analysis.classify_batch, candidates)

    # Stage 2: full summary only for the ones that clear the impact bar.
    posted = 0
    summarized = 0
    for article, impact in zip(candidates, impacts):
        if posted >= config.MAX_ARTICLES_PER_POLL:
            break
        if IMPACT_RANK.get(impact, 1) < min_rank:
            continue
        summarized += 1
        result = await asyncio.to_thread(analysis.analyze_article, article)
        result["impact"] = impact  # keep the strict stage-1 verdict
        try:
            await channel.send(embed=publisher.build_news_embed(article, result))
            posted += 1
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] send failed for {market}: {e}")

    print(
        f"[scheduler] {market}: gate-dropped {gated}, classified {len(candidates)}, "
        f"summarized {summarized}, posted {posted}"
    )


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
