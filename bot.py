"""Discord Market News Bot — entry point.

Slash commands:
  /ping                         health check
  /price   symbol [market]      current price (US / IDX / crypto)
  /news    market               latest analyzed headlines for a market
  /ta      symbol exchange screener [interval]   TradingView technical rating
  /watch   add|remove|list      manage a watchlist

Plus scheduled auto-push of analyzed news to per-market channels.
"""
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from scheduler import setup_scheduler
from services import analysis, news, prices, publisher, technical
from storage import db

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

MARKET_CHOICES = [
    app_commands.Choice(name="US stocks", value="us"),
    app_commands.Choice(name="Indonesia (IDX)", value="id"),
    app_commands.Choice(name="Crypto", value="crypto"),
]


@bot.event
async def on_ready():
    db.init_db()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:  # noqa: BLE001
        print(f"Command sync failed: {e}")
    setup_scheduler(bot)
    print(f"Logged in as {bot.user} (id: {bot.user.id})")


@bot.tree.command(name="ping", description="Check the bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! 🏓")


@bot.tree.command(name="price", description="Get the current price of a stock or crypto")
@app_commands.describe(
    symbol="e.g. AAPL, BBCA, BTC (no need for the .JK suffix)",
    market="Pick Indonesia (IDX) for local tickers like BBCA to disambiguate",
)
@app_commands.choices(market=MARKET_CHOICES)
async def price(
    interaction: discord.Interaction,
    symbol: str,
    market: Optional[app_commands.Choice[str]] = None,
):
    await interaction.response.defer()
    market_value = market.value if market else None
    try:
        result = await asyncio.to_thread(prices.get_price, symbol, market_value)
    except Exception as e:  # noqa: BLE001
        await interaction.followup.send(f"Error fetching `{symbol}`: {e}")
        return
    if not result:
        await interaction.followup.send(f"Couldn't find a price for `{symbol}`.")
        return
    await interaction.followup.send(embed=publisher.build_price_embed(result))


@bot.tree.command(name="news", description="Latest analyzed headlines for a market")
@app_commands.describe(market="Which market to pull news for")
@app_commands.choices(market=MARKET_CHOICES)
async def news_cmd(interaction: discord.Interaction, market: app_commands.Choice[str]):
    await interaction.response.defer()
    articles = await asyncio.to_thread(news.fetch_all, market.value)
    if not articles:
        await interaction.followup.send("No news found right now — try again shortly.")
        return
    sent = 0
    for article in articles[:3]:
        result = await asyncio.to_thread(analysis.analyze_article, article)
        if result is None:
            continue  # analysis unavailable (e.g. API overloaded) — skip it
        await interaction.followup.send(embed=publisher.build_news_embed(article, result))
        sent += 1
    if sent == 0:
        await interaction.followup.send(
            "Couldn't analyze the latest headlines right now (the API may be "
            "temporarily overloaded). Try again in a minute."
        )


@bot.tree.command(name="ta", description="TradingView technical rating for a symbol")
@app_commands.describe(
    symbol="Ticker as TradingView knows it, e.g. AAPL, BBCA, BTCUSDT",
    exchange="e.g. NASDAQ, NYSE, IDX, BINANCE",
    screener="e.g. america, indonesia, crypto",
    interval="1m,5m,15m,1h,4h,1d,1W,1M (default 1d)",
)
async def ta(
    interaction: discord.Interaction,
    symbol: str,
    exchange: str,
    screener: str,
    interval: str = "1d",
):
    await interaction.response.defer()
    result = await asyncio.to_thread(
        technical.get_ta_summary, symbol, exchange, screener, interval
    )
    if not result:
        await interaction.followup.send(
            "Couldn't fetch a rating. Check the symbol/exchange/screener "
            "(e.g. `AAPL NASDAQ america`, `BBCA IDX indonesia`, `BTCUSDT BINANCE crypto`)."
        )
        return
    await interaction.followup.send(embed=publisher.build_ta_embed(result))


@bot.tree.command(name="tickernews", description="Latest news about a specific ticker (last 48h)")
@app_commands.describe(
    symbol="e.g. BMRI, AAPL, BTC (no need for the .JK suffix)",
    market="Pick Indonesia (IDX) for local tickers like BMRI",
)
@app_commands.choices(market=MARKET_CHOICES)
async def tickernews(
    interaction: discord.Interaction,
    symbol: str,
    market: Optional[app_commands.Choice[str]] = None,
):
    await interaction.response.defer()
    market_value = market.value if market else None
    base = symbol.strip().lstrip("$")

    # Resolve the company/asset name for a sharper search (best-effort).
    name = None
    try:
        price = await asyncio.to_thread(prices.get_price, base, market_value)
        if price:
            name = price.get("name")
    except Exception:  # noqa: BLE001
        pass

    # Fetch a few extra (free lexical dedup already applied), then run the
    # cheap LLM semantic dedup, then trim to the display count.
    articles = await asyncio.to_thread(
        news.fetch_ticker_news, base, name, market_value, 48, 15
    )
    articles = await asyncio.to_thread(analysis.dedupe_headlines, articles)
    articles = articles[:8]
    display = (
        f"{name} ({base.upper()})"
        if name and name.upper() != base.upper()
        else base.upper()
    )
    await interaction.followup.send(
        embed=publisher.build_ticker_news_embed(f"📰 News — {display}", articles)
    )


# ---- /watch group ----
watch_group = app_commands.Group(name="watch", description="Manage your watchlist")


@watch_group.command(name="add", description="Add a symbol to your watchlist")
@app_commands.choices(market=MARKET_CHOICES)
async def watch_add(
    interaction: discord.Interaction, symbol: str, market: app_commands.Choice[str]
):
    await asyncio.to_thread(db.add_watch, symbol, market.value)
    await interaction.response.send_message(
        f"Added `{symbol.upper()}` ({market.value}) to the watchlist."
    )


@watch_group.command(name="remove", description="Remove a symbol from your watchlist")
@app_commands.choices(market=MARKET_CHOICES)
async def watch_remove(
    interaction: discord.Interaction, symbol: str, market: app_commands.Choice[str]
):
    await asyncio.to_thread(db.remove_watch, symbol, market.value)
    await interaction.response.send_message(
        f"Removed `{symbol.upper()}` ({market.value}) from the watchlist."
    )


@watch_group.command(name="list", description="Show your watchlist")
async def watch_list(interaction: discord.Interaction):
    items = await asyncio.to_thread(db.list_watch)
    if not items:
        await interaction.response.send_message("Your watchlist is empty.")
        return
    lines = [f"• `{i['symbol']}` ({i['market']})" for i in items]
    await interaction.response.send_message("**Watchlist**\n" + "\n".join(lines))


bot.tree.add_command(watch_group)


if __name__ == "__main__":
    config.validate()
    bot.run(config.DISCORD_BOT_TOKEN)
