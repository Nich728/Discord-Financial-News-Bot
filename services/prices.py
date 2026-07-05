"""Price lookups: yfinance for stocks (US + IDX `.JK`), CoinGecko for crypto.

All functions are synchronous (blocking) — call them via asyncio.to_thread
from the async bot so they don't block the event loop.
"""
from typing import Optional

import httpx
import yfinance as yf

import config

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Common ticker -> CoinGecko id, so we skip a search call for the usual coins.
COMMON_CRYPTO = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "SOL": "solana",
    "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "USDT": "tether",
    "USDC": "usd-coin", "AVAX": "avalanche-2", "DOT": "polkadot",
    "MATIC": "matic-network", "LINK": "chainlink", "TRX": "tron",
    "LTC": "litecoin", "SHIB": "shiba-inu", "TON": "the-open-network",
    "HYPE": "hyperliquid", "SUI": "sui", "APT": "aptos", "ARB": "arbitrum",
    "OP": "optimism", "PEPE": "pepe", "WIF": "dogwifcoin", "BONK": "bonk",
    "NEAR": "near", "ATOM": "cosmos", "UNI": "uniswap", "AAVE": "aave",
    "INJ": "injective-protocol", "RNDR": "render-token", "TIA": "celestia",
}

# Pair/quote suffixes that clearly signal a crypto ticker (e.g. HYPEUSDT).
CRYPTO_PAIR_SUFFIXES = ("USDT", "USDC", "-USD", "BUSD")


def _cg_headers():
    return {"x-cg-demo-api-key": config.COINGECKO_API_KEY} if config.COINGECKO_API_KEY else {}


def _strip_crypto_symbol(symbol: str) -> str:
    """Strip a leading $ and any quote-pair suffix: HYPEUSDT -> HYPE."""
    sym = symbol.upper().lstrip("$")
    for suffix in ("USDT", "USDC", "BUSD", "-USD", "USD"):
        if sym.endswith(suffix) and len(sym) > len(suffix):
            return sym[: -len(suffix)]
    return sym


def get_crypto_price(symbol: str):
    sym = _strip_crypto_symbol(symbol)
    coin_id = COMMON_CRYPTO.get(sym)
    if not coin_id:
        r = httpx.get(
            f"{COINGECKO_BASE}/search",
            params={"query": sym},
            headers=_cg_headers(),
            timeout=15,
        )
        r.raise_for_status()
        coins = r.json().get("coins", [])
        if not coins:
            return None
        coin_id = coins[0]["id"]
        sym = coins[0]["symbol"].upper()

    r = httpx.get(
        f"{COINGECKO_BASE}/coins/markets",
        params={"vs_currency": "usd", "ids": coin_id},
        headers=_cg_headers(),
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    d = data[0]
    return {
        "symbol": sym,
        "name": d.get("name", sym),
        "market": "crypto",
        "price": d.get("current_price"),
        "currency": "USD",
        "change_pct": d.get("price_change_percentage_24h"),
        "source": "CoinGecko",
    }


def get_stock_price(symbol: str):
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="5d")
    if hist.empty:
        return None
    closes = hist["Close"].dropna()
    if len(closes) == 0:
        return None
    price = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) >= 2 else price
    change_pct = ((price - prev) / prev * 100) if prev else 0.0
    is_idx = symbol.upper().endswith(".JK")

    # Fetch the company's full name (best-effort; .info is slower and can flake).
    name = symbol.upper()
    try:
        info = ticker.info
        name = info.get("longName") or info.get("shortName") or name
    except Exception:  # noqa: BLE001 - name is cosmetic; fall back to the ticker
        pass

    return {
        "symbol": symbol.upper(),
        "name": name,
        "market": "id" if is_idx else "us",
        "price": price,
        "currency": "IDR" if is_idx else "USD",
        "change_pct": change_pct,
        "source": "Yahoo Finance",
    }


def get_price(symbol: str, market: Optional[str] = None):
    """Route a symbol to the right data source.

    market: optional hint ("us" | "id" | "crypto"). If omitted, we infer it.
    """
    symbol = symbol.strip().lstrip("$")
    upper = symbol.upper()

    if market == "crypto":
        return get_crypto_price(symbol)
    if market == "id":
        # IDX tickers need the .JK suffix on Yahoo Finance; add it if missing
        # so users can just type "BBCA" with market:ID.
        if not upper.endswith(".JK"):
            symbol = symbol + ".JK"
        return get_stock_price(symbol)
    if market == "us":
        return get_stock_price(symbol)

    # Auto-detect
    if upper.endswith(".JK"):
        return get_stock_price(symbol)
    if (
        upper in COMMON_CRYPTO
        or _strip_crypto_symbol(upper) in COMMON_CRYPTO
        or upper.endswith(CRYPTO_PAIR_SUFFIXES)
    ):
        return get_crypto_price(symbol)
    return get_stock_price(symbol)
