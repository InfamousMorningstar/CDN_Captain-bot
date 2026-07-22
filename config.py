"""CDN_Captain v2 configuration. All constants live here; no other module reads env vars."""
import os
from dotenv import load_dotenv

# Load from .env in the current working directory
# This respects monkeypatched cwd changes in tests
load_dotenv(dotenv_path=os.path.join(os.getcwd(), '.env'))

# ── Secrets ───────────────────────────────────────────────────────────────────
DISCORD_TOKEN     = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ── Identity ─────────────────────────────────────────────────────────────────
BOT_NAME        = "CDN_Captain"
CURRENT_VERSION = "v2.0.0"
CDN_WEBSITE     = "https://www.cdndayz.com"
PORTFOLIO_URL   = "https://portfolio.ahmxd.net"

# ── Models ───────────────────────────────────────────────────────────────────
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "claude-haiku-4-5-20251001")

# ── Storage ──────────────────────────────────────────────────────────────────
FACTS_DB_PATH       = os.getenv("FACTS_DB_PATH", "facts.db")
MEMORY_DB_PATH      = os.getenv("MEMORY_DB_PATH", "memory.db")
KNOWLEDGE_FILE      = os.getenv("KNOWLEDGE_FILE", "knowledge.txt")
SUPPRESSED_LOG_PATH = os.getenv("SUPPRESSED_LOG_PATH", "suppressed_answers.jsonl")
FLAGGED_LOG_PATH    = os.getenv("FLAGGED_LOG_PATH", "flagged_answers.jsonl")
LOG_FILE            = os.getenv("LOG_FILE", "")

# ── Crawl / ingest ───────────────────────────────────────────────────────────
CRAWL_INTERVAL_SECONDS    = int(os.getenv("CRAWL_INTERVAL_SECONDS", str(7 * 86400)))
CRAWL_STALE_ALERT_SECONDS = 14 * 86400
MAX_PAGES_TO_CRAWL        = 60
CRAWL_CONCURRENCY         = 4
REFERENCE_CHANNEL_MSG_LIMIT = 120

# ── Retrieval / answering ────────────────────────────────────────────────────
TOP_FACTS               = 20
RETRIEVAL_MIN_SCORE     = 1.0
CONTEXT_MESSAGE_LIMIT   = 12
MAX_MESSAGE_AGE_SECONDS = 90
USER_COOLDOWN_SECONDS   = 30
ANSWER_DEDUP_TTL        = 300
ANSWER_MAX_TOKENS       = 700

# ── Discord ──────────────────────────────────────────────────────────────────
REFERENCE_CHANNEL_ID = 1340937408434405437
TICKET_CHANNEL_ID    = 1340937937940119602
IGNORED_CHANNEL_IDS: set[int] = {1084687416104865803}   # moderator-only
PROTECTED_ADMINS = {"5pntjoe", "strikezx"}
SIDEKICK_USER_ID = 699763177315106836
FEEDBACK_UP_EMOJI   = "👍"
FEEDBACK_DOWN_EMOJI = "👎"
FEEDBACK_DOWNVOTE_ALERT_THRESHOLD = int(os.getenv("FEEDBACK_DOWNVOTE_ALERT_THRESHOLD", "3"))


def validate_config() -> list[str]:
    """Return a list of fatal configuration problems (empty = OK)."""
    problems: list[str] = []
    if not DISCORD_TOKEN:
        problems.append("DISCORD_TOKEN is not set — add it to your .env file")
    if not ANTHROPIC_API_KEY:
        problems.append("ANTHROPIC_API_KEY is not set — add it to your .env file")
    if not ANSWER_MODEL:
        problems.append("ANSWER_MODEL must not be empty")
    if FEEDBACK_DOWNVOTE_ALERT_THRESHOLD < 1:
        problems.append("FEEDBACK_DOWNVOTE_ALERT_THRESHOLD must be >= 1")
    return problems
