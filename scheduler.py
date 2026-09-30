"""Scheduled auto-push: poll news per market, analyze, and post to channels."""
import asyncio
import random
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from services import analysis, jev, news, prefilter, publisher
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
    trusted_rank = IMPACT_RANK.get(config.TRUSTED_MIN_IMPACT, 2)

    # Free keyword gate -> collect unseen candidates + track what got dropped.
    # Trusted sources bypass the gate entirely (the LLM still judges impact).
    dropped = []
    candidates = []
    for article in articles:
        if len(candidates) >= config.MAX_SCAN_PER_POLL:
            break
        if db.is_seen(article["url"]):
            continue
        if not article.get("trusted") and not prefilter.is_relevant(article):
            db.mark_seen(article["url"])
            dropped.append(article)
            continue
        candidates.append(article)

    posted = 0
    summarized = 0
    duplicates = 0
    jev_only = 0  # posts that only Jev (not Haiku) rated at/above the bar
    if candidates:
        # Stage 1: ONE cheap batched call rates all candidates and flags
        # articles covering a story we already posted (or another candidate).
        # All channels' recent titles (articles route across channels by topic).
        recent = await asyncio.to_thread(db.recent_posted_stories, None)
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
            # Trusted sources post at a lower impact bar than everyone else.
            bar = trusted_rank if article.get("trusted") else min_rank

            # Jev shadow trial: rate every non-duplicate candidate with Jev too,
            # so articles only Jev rates highly still get a chance to post.
            jev_result = await asyncio.to_thread(jev.classify_impact, article)
            jev_hit = (
                jev_result is not None
                and IMPACT_RANK.get(jev_result["impact"], 1) >= bar
            )

            impact = cls.get("impact", "low")
            if IMPACT_RANK.get(impact, 1) < bar and not jev_hit:
                continue
            summarized += 1
            result = await asyncio.to_thread(analysis.analyze_article, article)
            if result is None:
                continue  # summary failed — skip rather than post a stub

            # Stage 2 (Haiku, full context) is Haiku's final verdict. Post if
            # EITHER Haiku's final verdict or Jev clears the bar.
            final_impact = (result.get("impact") or "low").lower()
            haiku_hit = IMPACT_RANK.get(final_impact, 1) >= bar
            if not haiku_hit and not jev_hit:
                print(
                    f"[scheduler] {market}: stage-2 downgraded "
                    f"'{article['title'][:60]}' to {final_impact} — not posting"
                )
                continue
            if haiku_hit and jev_hit:
                trigger = "both"
            elif haiku_hit:
                trigger = "haiku"
            else:
                trigger = "jev"

            # Route to the channel matching the article's actual topic, not the
            # feed it came from (so e.g. a crypto story from an Indonesian feed
            # lands in the crypto channel). Fall back to the fetch market.
            target_market = cls.get("market") or market
            target_channel = bot.get_channel(config.CHANNELS.get(target_market, 0)) or channel
            try:
                await target_channel.send(
                    embed=publisher.build_news_embed(
                        article, result, jev=jev_result,
                        trigger=trigger if jev.enabled() else None,
                    )
                )
                posted += 1
                if trigger == "jev":
                    jev_only += 1
                if target_market != market:
                    print(f"[scheduler] {market} -> {target_market}: {article['title'][:60]}")
                # Remember what we posted so other outlets' copies of the same
                # story get flagged as duplicates in future polls.
                db.add_posted_story(article["title"], target_market)
            except Exception as e:  # noqa: BLE001
                print(f"[scheduler] send failed for {market}: {e}")

    # Optional QA: check whether the keyword gate dropped anything important.
    if config.AUDIT_GATE and dropped:
        await _audit_dropped(market, dropped, min_rank)

    print(
        f"[scheduler] {market}: fetched {len(articles)}, "
        f"gate-dropped {len(dropped)}, classified {len(candidates)}, "
        f"duplicates {duplicates}, summarized {summarized}, posted {posted}"
        + (f" (jev-only {jev_only})" if jev.enabled() else "")
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
