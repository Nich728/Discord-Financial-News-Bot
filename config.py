"""Central configuration, loaded from the .env file."""
import os
from dotenv import load_dotenv

load_dotenv()

# ---- Required ----
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ---- Optional news / price API keys ----
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GNEWS_KEY = os.getenv("GNEWS_KEY")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY") or None

# ---- Channels ----
CHANNEL_ID_US = int(os.getenv("CHANNEL_ID_US", "0"))
CHANNEL_ID_ID = int(os.getenv("CHANNEL_ID_ID", "0"))
CHANNEL_ID_CRYPTO = int(os.getenv("CHANNEL_ID_CRYPTO", "0"))

CHANNELS = {
    "us": CHANNEL_ID_US,
    "id": CHANNEL_ID_ID,
    "crypto": CHANNEL_ID_CRYPTO,
}

# ---- Behaviour ----
POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "15"))
MAX_ARTICLES_PER_POLL = int(os.getenv("MAX_ARTICLES_PER_POLL", "3"))
# How many fresh articles to analyze per market per poll (bounds LLM cost).
MAX_SCAN_PER_POLL = int(os.getenv("MAX_SCAN_PER_POLL", "15"))
# Only auto-push articles at or above this impact: "high", "medium", or "low".
MIN_IMPACT = os.getenv("MIN_IMPACT", "high").lower()
ANALYSIS_MODEL = os.getenv("ANALYSIS_MODEL", "claude-haiku-4-5")
DB_PATH = os.getenv("DB_PATH", "bot.db")

# ---- Keyword pre-filter (free gate before the LLM) ----
# When enabled, only articles whose title/snippet mention a market-moving
# keyword get an LLM call. Set PREFILTER_ENABLED=false to analyze everything.
PREFILTER_ENABLED = os.getenv("PREFILTER_ENABLED", "true").lower() in ("1", "true", "yes")

_DEFAULT_KEYWORDS = [
    # Macro / monetary
    "inflation", "cpi", "ppi", "interest rate", "rate hike", "rate cut",
    "rate decision", "federal reserve", "the fed", "fomc", "central bank",
    "bank indonesia", "gdp", "unemployment", "jobs report", "nonfarm",
    "payrolls", "recession", "stimulus", "debt ceiling", "default",
    "downgrade", "credit rating", "bond yield", "treasury yield",
    # Geopolitics
    "tariff", "sanction", "war", "invasion", "airstrike", "missile",
    "military strike", "ceasefire", "conflict", "opec", "oil price",
    "energy crisis", "supply shock",
    # Markets / corporate
    "earnings", "guidance", "merger", "acquisition", "buyout", "ipo",
    "bankruptcy", "bailout", "lawsuit", "regulation", "antitrust",
    "ban", "halt", "delisting", "crash", "plunge", "surge", "selloff",
    "record high", "record low",
    # Crypto
    "bitcoin", "ethereum", "etf approval", "spot etf", "hack", "exploit",
    "stablecoin", "halving",
    # Indonesia
    "ihsg", "rupiah", "prabowo",
]

# Override with a comma-separated PREFILTER_KEYWORDS in .env if you like.
_env_keywords = os.getenv("PREFILTER_KEYWORDS")
PREFILTER_KEYWORDS = (
    [k.strip().lower() for k in _env_keywords.split(",") if k.strip()]
    if _env_keywords
    else _DEFAULT_KEYWORDS
)

MARKETS = ("us", "id", "crypto")


def validate():
    """Fail fast if the two must-have credentials are missing."""
    missing = [
        name
        for name, value in (
            ("DISCORD_BOT_TOKEN", DISCORD_BOT_TOKEN),
            ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing required env vars: "
            + ", ".join(missing)
            + "\nCopy .env.example to .env and fill them in."
        )
