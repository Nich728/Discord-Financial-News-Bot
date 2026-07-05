"""Optional TradingView technical-rating enrichment via `tradingview-ta`.

This hits TradingView's public scanner endpoint and returns their own
Buy/Sell/Neutral summary. It's unofficial but read-only and fairly stable.
You must supply the exchange + screener explicitly (TradingView requires exact
values), which is why the /ta command takes them as arguments.
Synchronous — call via asyncio.to_thread from the async bot.
"""
from tradingview_ta import TA_Handler, Interval

INTERVALS = {
    "1m": Interval.INTERVAL_1_MINUTE,
    "5m": Interval.INTERVAL_5_MINUTES,
    "15m": Interval.INTERVAL_15_MINUTES,
    "1h": Interval.INTERVAL_1_HOUR,
    "4h": Interval.INTERVAL_4_HOURS,
    "1d": Interval.INTERVAL_1_DAY,
    "1W": Interval.INTERVAL_1_WEEK,
    "1M": Interval.INTERVAL_1_MONTH,
}


def get_ta_summary(symbol: str, exchange: str, screener: str, interval: str = "1d"):
    """Return TradingView's technical summary, or None on failure.

    Examples:
      get_ta_summary("AAPL", "NASDAQ", "america", "1d")
      get_ta_summary("BBCA", "IDX", "indonesia", "1d")
      get_ta_summary("BTCUSDT", "BINANCE", "crypto", "4h")
    """
    try:
        handler = TA_Handler(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            screener=screener.lower(),
            interval=INTERVALS.get(interval, Interval.INTERVAL_1_DAY),
        )
        summary = handler.get_analysis().summary
        return {
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "interval": interval,
            "recommendation": summary.get("RECOMMENDATION", "N/A"),
            "buy": summary.get("BUY", 0),
            "sell": summary.get("SELL", 0),
            "neutral": summary.get("NEUTRAL", 0),
        }
    except Exception as e:  # noqa: BLE001
        print(f"[technical] error ({symbol}/{exchange}/{screener}): {e}")
        return None
