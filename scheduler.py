"""Scheduled auto-push: poll news per market, analyze, and post to channels."""
import asyncio
import random
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from services import analysis, news, prefilter, publisher
from storage import db

IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}

DUPLICATES_LOG = "duplicates.log"
AUDIT_LOG = "gate_audit.log"


def _log_to_file(filename: str, line: str, url: str = ""):
    """Append a timestamped line to a local log file (best-effort)."""
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(filename, "a", encoding="utf-8") as f:
            f.write(f"{stamp} {line}\n")
            if url:
                f.write(f"    {url}\n")
    except Exception as e:  # noqa: BLE001 - logging must never break a poll
        print(f"[scheduler] could not write {filename}: {e}")


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
    duplicates = 0
    if candidates:
        # Stage 1: ONE cheap batched call rates all candidates and flags
        # articles covering a story we already posted (or another candidate).
        recent = await asyncio.to_thread(db.recent_posted_stories, market)
        classifications = await asyncio.to_thread(
            analysis.classify_batch, candidates, recent
        )
        if classifications is None:
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
        for article, cls in zip(candidates, classifications):
            if posted >= config.MAX_ARTICLES_PER_POLL:
                break
            if cls.get("duplicate"):
                duplicates += 1
                _log_to_file(
                    DUPLICATES_LOG,
                    f"[{market}] \"{article['title']}\" "
                    f"({article.get('source', '?')})",
                    article.get("url", ""),
                )
                continue
            impact = cls.get("impact", "low")
            if IMPACT_RANK.get(impact, 1) < min_rank:
                continue
            summarized += 1
            result = await asyncio.to_thread(analysis.analyze_article, article)
            if result is None:
                continue  # summary failed — skip rather than post a stub

            # Stage 2 gets the full article context, so treat it as the
            # authoritative verdict. If it disagrees with stage 1, don't post —
            # this catches stage-1 false positives and keeps the displayed
            # impact consistent with the rationale shown next to it.
            final_impact = (result.get("impact") or "low").lower()
            if IMPACT_RANK.get(final_impact, 1) < min_rank:
                print(
                    f"[scheduler] {market}: stage-2 downgraded "
                    f"'{article['title'][:60]}' to {final_impact} — not posting"
                )
                continue
            try:
                await channel.send(embed=publisher.build_news_embed(article, result))
                posted += 1
                # Remember what we posted so other outlets' copies of the same
                # story get flagged as duplicates in future polls.
                db.add_posted_story(article["title"], market)
            except Exception as e:  # noqa: BLE001
                print(f"[scheduler] send failed for {market}: {e}")

    # Optional QA: check whether the keyword gate dropped anything important.
    if config.AUDIT_GATE and dropped:
        await _audit_dropped(market, dropped, min_rank)

    print(
        f"[scheduler] {market}: fetched {len(articles)}, "
        f"gate-dropped {len(dropped)}, classified {len(candidates)}, "
        f"duplicates {duplicates}, summarized {summarized}, posted {posted}"
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
    classifications = await asyncio.to_thread(analysis.classify_batch, sample)
    if classifications is None:
        return  # audit is best-effort; skip quietly if the API is unavailable
    for article, cls in zip(sample, classifications):
        impact = cls.get("impact", "low")
        if IMPACT_RANK.get(impact, 1) >= min_rank:
            line = (
                f"[{market}] gate DROPPED a '{impact}' article -> "
                f"{article['title']}"
            )
            print(f"[audit] {line}")
            _log_to_file(AUDIT_LOG, line, article.get("url", ""))


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
