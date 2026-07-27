"""Builds Discord embeds for prices, news analysis, and TA ratings."""
import discord

SENTIMENT_COLORS = {
    "bullish": 0x2ECC71,
    "bearish": 0xE74C3C,
    "neutral": 0x95A5A6,
}
RECOMMENDATION_COLORS = {
    "STRONG_BUY": 0x27AE60,
    "BUY": 0x2ECC71,
    "NEUTRAL": 0x95A5A6,
    "SELL": 0xE74C3C,
    "STRONG_SELL": 0xC0392B,
}


def _fmt_price(value, currency):
    if value is None:
        return "?"
    if currency == "IDR":
        return f"Rp {value:,.0f}"
    if currency == "USD" and value < 1:
        return f"${value:,.6f}"
    return f"${value:,.2f}"


def build_price_embed(p: dict) -> discord.Embed:
    change = p.get("change_pct")
    arrow = "▲" if (change or 0) >= 0 else "▼"
    color = 0x2ECC71 if (change or 0) >= 0 else 0xE74C3C
    symbol = p["symbol"]
    name = p.get("name") or symbol
    title = f"{name} ({symbol})" if name != symbol else symbol
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Price", value=_fmt_price(p.get("price"), p.get("currency")), inline=True)
    if change is not None:
        embed.add_field(name="Change (24h/1d)", value=f"{arrow} {change:+.2f}%", inline=True)
    embed.set_footer(text=f"{p.get('source', '')} • Not financial advice")
    return embed


def build_news_embed(article: dict, analysis: dict) -> discord.Embed:
    sentiment = (analysis.get("sentiment") or "neutral").lower()
    embed = discord.Embed(
        title=article["title"][:256],
        url=article["url"],
        description=analysis.get("summary", "")[:2000],
        color=SENTIMENT_COLORS.get(sentiment, 0x95A5A6),
    )
    embed.add_field(name="Sentiment", value=sentiment.title(), inline=True)
    embed.add_field(name="Impact", value=(analysis.get("impact") or "?").title(), inline=True)
    tickers = analysis.get("tickers") or []
    if tickers:
        embed.add_field(name="Tickers", value=", ".join(tickers[:8]), inline=True)
    if analysis.get("rationale"):
        embed.add_field(name="Why it matters", value=analysis["rationale"][:1024], inline=False)
    embed.set_footer(text=f"{article.get('source', '')} • Not financial advice")
    return embed


def _relative_time(ts) -> str:
    if not ts:
        return ""
    import time
    diff = time.time() - ts
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    return f"{int(diff // 86400)}d ago"


def build_ticker_news_embed(title: str, articles: list, hours: int = 48) -> discord.Embed:
    if not articles:
        embed = discord.Embed(
            title=title,
            description=f"No news found in the last {hours} hours.",
            color=0x95A5A6,
        )
        embed.set_footer(text="Not financial advice")
        return embed

    lines = []
    for a in articles:
        meta = " · ".join(x for x in [a.get("source", ""), _relative_time(a.get("ts"))] if x)
        lines.append(f"• [{a['title'][:180]}]({a['url']}) — {meta}")
    embed = discord.Embed(
        title=title,
        description="\n".join(lines)[:4096],
        color=0x3498DB,
    )
    embed.set_footer(text=f"Last {hours}h • Not financial advice")
    return embed


def build_ta_embed(ta: dict) -> discord.Embed:
    rec = (ta.get("recommendation") or "NEUTRAL").upper()
    embed = discord.Embed(
        title=f"TradingView TA — {ta['symbol']} ({ta['exchange']}, {ta['interval']})",
        description=f"**{rec.replace('_', ' ')}**",
        color=RECOMMENDATION_COLORS.get(rec, 0x95A5A6),
    )
    embed.add_field(name="Buy", value=str(ta.get("buy", 0)), inline=True)
    embed.add_field(name="Neutral", value=str(ta.get("neutral", 0)), inline=True)
    embed.add_field(name="Sell", value=str(ta.get("sell", 0)), inline=True)
    embed.set_footer(text="TradingView (unofficial) • Not financial advice")
    return embed
