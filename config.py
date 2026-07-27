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

# ---- Gate audit (QA: catch important articles the keyword gate dropped) ----
# When true, gate-dropped articles ALSO get classified so the bot warns you if
# any were actually high-impact (i.e. a keyword is missing). Costs extra LLM
# calls, so enable it temporarily to tune PREFILTER_KEYWORDS, then turn it off.
AUDIT_GATE = os.getenv("AUDIT_GATE", "false").lower() in ("1", "true", "yes")
# Max gate-dropped articles to audit per market per poll (bounds the extra cost).
AUDIT_MAX = int(os.getenv("AUDIT_MAX", "10"))

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
    "energy crisis", "supply shock", "trump",
    # Geoeconomics / de-dollarization
    "brics", "de-dollarization", "dedollarization", "reserve currency",
    "trade deal", "trade agreement", "trade war", "export ban",
    # Markets / corporate
    "earnings", "guidance", "merger", "acquisition", "buyout", "ipo",
    "bankruptcy", "bailout", "lawsuit", "regulation", "antitrust",
    "ban", "halt", "delisting", "crash", "plunge", "surge", "selloff",
    "record high", "record low",
    # Crypto
    "bitcoin", "ethereum", "etf approval", "spot etf", "hack", "exploit",
    "stablecoin", "halving", "crypto", "whale",
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

# Blocklist: dropped even if a keyword matched. These are recurring
# prediction/recommendation columns and listicles — published daily, never
# actually market-moving, and they'd otherwise burn an LLM call every poll.
_DEFAULT_BLOCK = [
    # Indonesian daily columns
    "prediksi", "rekomendasi saham", "rekomendasi teknikal", "saham pilihan",
    # English equivalents
    "stocks to watch", "stocks to buy", "best stocks", "top picks",
    "price prediction", "technical analysis", "what to watch",
    "things to know", "how to", "explainer",
    # Analyst opinion / speculation (note: "credit rating" stays allowed —
    # these are distinct phrases, matched whole)
    "price target", "analyst rating", "hold rating", "buy rating",
    "sell rating", "stock split", "will explode", "here's why",
    "here's when", "here is why", "here is when",
    # Crypto price-hype patterns
    "prediction", "predicts", "should you buy", "buy the dip",
]

_env_block = os.getenv("PREFILTER_BLOCK")
PREFILTER_BLOCK = (
    [k.strip().lower() for k in _env_block.split(",") if k.strip()]
    if _env_block
    else _DEFAULT_BLOCK
)

# ---- Trusted sources ----
# Curated outlets whose articles bypass the keyword gate (so good stories with
# no keyword aren't pre-dropped) AND post at a lower impact bar. Matched as a
# substring against each article's source name and URL.
_env_trusted = os.getenv("TRUSTED_SOURCES")
TRUSTED_SOURCES = (
    [s.strip().lower() for s in _env_trusted.split(",") if s.strip()]
    if _env_trusted
    else ["bloomberg technoz", "bloombergtechnoz"]
)
# Impact bar for trusted sources (vs MIN_IMPACT for everything else).
TRUSTED_MIN_IMPACT = os.getenv("TRUSTED_MIN_IMPACT", "medium").lower()

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
