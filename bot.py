"""
CDN_Captain — Discord Bot powered by Claude AI
Reads every channel. Responds only when it genuinely has the answer
from cdndayz.com or the reference channel. Stays invisible otherwise.
"""

import discord
from discord.ext import commands
import anthropic
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
from playwright.async_api import async_playwright, Browser
import os
import re
import asyncio
import time
import base64
import math
import hmac
import hashlib
import random
import aiosqlite
import io
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
#  Console output  (human-readable, coloured)
# ─────────────────────────────────────────────
from datetime import datetime, timezone

_RST  = "\033[0m"
_BOLD = "\033[1m"
_GRN  = "\033[92m"
_YLW  = "\033[93m"
_RED  = "\033[91m"
_CYN  = "\033[96m"
_PRP  = "\033[95m"
_GRY  = "\033[90m"
_WHT  = "\033[97m"

_LEVEL_ICON = {
    "ok":    f"{_GRN}✔ {_RST}",
    "warn":  f"{_YLW}⚠ {_RST}",
    "error": f"{_RED}✖ {_RST}",
    "info":  f"{_CYN}· {_RST}",
    "skip":  f"{_GRY}· {_RST}",
    "msg":   f"{_CYN}◆ {_RST}",
    "crawl": f"{_YLW}⟳ {_RST}",
}
_LEVEL_COL = {
    "ok":    _GRN,
    "warn":  _YLW,
    "error": _RED,
    "info":  _WHT,
    "skip":  _GRY,
    "msg":   _CYN,
    "crawl": _YLW,
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _log(msg: str, level: str = "info") -> None:
    """Print a timestamped, human-readable line to the console."""
    ts   = f"{_GRY}{_ts()}{_RST}"
    icon = _LEVEL_ICON.get(level, "  ")
    col  = _LEVEL_COL.get(level, _WHT)
    print(f"  {ts}  {icon}{col}{msg}{_RST}")


def _print_banner() -> None:
    """Startup header — printed when the bot first connects."""
    print()
    print(f"  {_GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{_RST}")
    print(f"  {_GRN}  {_BOLD}CDN_Captain{_RST}  {_GRN}·  {CURRENT_VERSION}  ·  cdndayz.com{_RST}")
    print(f"  {_GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{_RST}")
    print()


def _print_ready(guild_name: str) -> None:
    """'All systems go' banner — printed after full startup completes."""
    print()
    print(f"  {_GRN}{_BOLD}  ✅  CDN_Captain is LIVE  ·  {guild_name}{_RST}")
    print(f"  {_GRY}     Watching all channels — ready to answer questions{_RST}")
    print()
    print(f"  {_GRY}── Live Activity ───────────────────────────────────────────────────{_RST}")
    print()


# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────
DISCORD_TOKEN     = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CDN_WEBSITE       = "https://www.cdndayz.com"
BOT_NAME          = "CDN_Captain"

CURRENT_VERSION   = "v1.3.8"
GITHUB_RELEASES_API = "https://api.github.com/repos/InfamousMorningstar/CDN_Captain-bot/releases/latest"
GITHUB_RELEASES_URL = "https://github.com/InfamousMorningstar/CDN_Captain-bot/releases/latest"
PORTFOLIO_URL     = "https://portfolio.ahmxd.net"

# Update check state
_update_available: bool = False

USER_COOLDOWN_SECONDS       = 30
CONTEXT_MESSAGE_LIMIT       = 75
MAX_PAGES_TO_CRAWL          = 200
CRAWL_CONCURRENCY           = 4
CRAWL_CACHE_TTL             = 3600
AUTO_CRAWL_INTERVAL         = 3600
TOP_PAGES_FOR_ANSWER        = 12    # more sources fed to Claude
CHARS_PER_PAGE              = 10000 # more content per page
MAX_MESSAGE_AGE_SECONDS     = 90
TWO_PERSON_CONVO_WINDOW     = 10

# ── Sidekick mode ──────────────────────────────────────────────────────────────
# Only this exact user ID can activate sidekick mode. User ID never changes and
# cannot be faked — it's the only reliable way to identify someone on Discord.
# To find your ID: Discord Settings → Advanced → Developer Mode ON,
# then right-click your profile → Copy User ID.
SIDEKICK_USER_ID = 699763177315106836
SIDEKICK_USERNAME = "infamous_morningstar"   # fallback display name check
# ───────────────────────────────────────────────────────────────────────────────

# Global pause flag — only Infamous_Morningstar can toggle this
_bot_paused: bool = False

PAUSE_PHRASES   = {"shutdown", "stop responding", "go silent", "pause", "don't respond",
                   "stop answering", "ignore everyone", "go quiet", "shut up", "shut down"}
RESUME_PHRASES  = {"resume", "come back", "start responding", "wake up", "unpause",
                   "you can respond", "go back", "start answering", "turn on"}

# Semantic expansions — when a keyword is detected, also score pages containing
# these related terms, so Claude gets the right content even if phrasing differs
KEYWORD_EXPANSIONS: dict[str, set[str]] = {
    "donate":    {"donation", "donator", "support", "patreon", "contribute", "tier"},
    "trader":    {"market", "shop", "vendor", "trade", "safe zone", "trader zone", "exclusion",
                  "vehicle trader", "aircraft trader", "special trader", "black market", "blackmarket"},
    "wipe":      {"reset", "restart", "wipe schedule", "server reset", "next wipe", "map reset"},
    "base":      {"build", "territory", "flag", "construction", "building", "base building"},
    "ban":       {"banned", "suspend", "appeal", "blacklist", "unban"},
    "error":     {"crash", "problem", "issue", "fix", "troubleshoot", "code"},
    "kick":      {"kicked", "disconnect", "disconnected", "removed"},
    "join":      {"connect", "server ip", "how to play", "get started", "whitelist"},
    "whitelist": {"application", "apply", "allowlist", "allowlisted", "accepted"},
    "rule":      {"rules", "regulation", "policy", "allowed", "prohibited", "forbidden"},
    "loot":      {"items", "spawn", "economy", "loot table", "gear"},
    "raid":      {"raiding", "base attack", "offline", "breach"},
    "mod":       {"mods", "modded", "modification", "modpack"},
    "password":  {"server password", "access", "private"},
    "ip":        {"server ip", "address", "connect", "direct connect"},
    "distance":  {"metres", "meters", "radius", "boundary", "zone", "away", "far"},
    "build":     {"territory", "base", "construction", "flag", "build zone"},
    "rep":       {"reputation", "rep progression", "unlock", "points", "earn rep"},
    "dungeon":   {"permadeath", "permanent death", "dungeon run", "admin teleport", "dungeon rules"},
    "scifi":     {"sci-fi", "sci fi", "banov", "yrtsk", "parkour", "blackmarket", "hidden trader",
                  "special trader", "rainbow bear", "rep progression"},
    "yrtsk":     {"weapon tier", "tier 1", "tier 2", "tier 3", "tier 4", "tier 5", "sci-fi weapon"},
    "weapon":    {"yrtsk", "tier", "blackmarket", "t1", "t2", "t3", "t4", "t5"},
    "hardcore":  {"hc", "hc server", "territory", "raiding", "permadeath", "donation items"},
}

REFERENCE_CHANNEL_ID        = 1340937408434405437
REFERENCE_CHANNEL_LINK      = "https://discord.com/channels/1076024408503762974/1340937408434405437"
TICKET_CHANNEL_ID           = 1340937937940119602
REFERENCE_CHANNEL_MSG_LIMIT = 120
REF_CHANNEL_CACHE_TTL       = 1800

# Change detection — post website update alerts to this channel (set to None to disable)
# Replace with your staff/log channel ID if you want change announcements
CHANGE_ALERT_CHANNEL_ID: int | None = None

PROTECTED_ADMINS = {"5pntjoe", "strikezx"}

# Per-channel dedup: don't answer the same question twice in 5 minutes
ANSWER_DEDUP_TTL = 300

# SQLite memory — persists across restarts
DB_PATH      = "memory.db"
_bot_start_time = time.time()

_ADMIN_TAG_OPENER = "Hey there! 👋 Please don't ping the admins — they won't respond to direct tags and it clutters their notifications."

_ADMIN_TAG_CLOSERS = [
    "Thanks for keeping the server tidy! 😊",
    "Appreciate you — the server runs smoother when we keep it organised! 🙌",
    "Cheers for understanding! The admins appreciate it. ✌️",
    "You're a legend for asking the right way. 🫡",
    "Thanks for being a good sport about it! 😄",
]

def build_admin_tag_response(message: discord.Message) -> str:
    guild = message.guild
    rules_ch  = guild.get_channel(REFERENCE_CHANNEL_ID) if guild else None
    ticket_ch = guild.get_channel(TICKET_CHANNEL_ID)    if guild else None
    rules_mention  = f"<#{rules_ch.id}>"  if rules_ch  else "the rules channel"
    ticket_mention = f"<#{ticket_ch.id}>" if ticket_ch else "the ticket channel"
    closer = random.choice(_ADMIN_TAG_CLOSERS)
    footer = f"\n-# Engineered by [Morningstar.0](<{PORTFOLIO_URL}>)"
    if _update_available:
        footer += f"\n-# ⬆️ [Bot update available](<{GITHUB_RELEASES_URL}>)"
    return (
        f"{_ADMIN_TAG_OPENER}\n\n"
        f"🌐 **Check the website first** — **https://cdndayz.com** has all the rules, FAQs, and info you need!\n"
        f"📋 **Server rules & info** are also in {rules_mention}\n"
        f"💬 **Still have a question?** Ask it here — a community member or I might be able to help!\n"
        f"🎫 **Need staff support?** Open a ticket in {ticket_mention}\n"
        f"🚫 **Please don't DM the admins either** — tickets are the best way to reach them.\n\n"
        f"{closer}"
        f"{footer}"
    )

NO_ANSWER = "NO_ANSWER"

# ─────────────────────────────────────────────
#  SQLite memory layer
# ─────────────────────────────────────────────
async def init_db() -> None:
    """Create tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS qa_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     REAL    NOT NULL,
                guild_id      INTEGER,
                channel_id    INTEGER NOT NULL,
                channel_name  TEXT,
                author_id     INTEGER,
                author_name   TEXT,
                question      TEXT    NOT NULL,
                answer        TEXT    NOT NULL,
                confidence    INTEGER DEFAULT NULL,
                marked_correct INTEGER DEFAULT NULL,
                message_id    INTEGER DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.commit()
    _log("Answer memory is ready  (memory.db)", "ok")


async def db_get_state(key: str, default: str = "") -> str:
    """Read a persistent state value."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_state WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else default


async def db_set_state(key: str, value: str) -> None:
    """Write a persistent state value."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO bot_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


# ── Tamper-proof state (HMAC-signed with the Discord token) ───────────────────
# The pause state is stored as an HMAC signature of the boolean value.
# Opening memory.db shows only an opaque hash — editing it to a fake value
# will never match a valid signature, so the bot ignores it and defaults to False.

def _sign(value: str) -> str:
    """Produce an HMAC-SHA256 hex digest of value, keyed by the Discord token."""
    secret = (DISCORD_TOKEN or "fallback").encode()
    return hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()


def _verify(value: str, stored: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    return hmac.compare_digest(_sign(value), stored)


async def set_paused(paused: bool) -> None:
    token = "true" if paused else "false"
    await db_set_state("_s", _sign(token))


async def get_paused() -> bool:
    stored = await db_get_state("_s", "")
    if not stored:
        return False
    return _verify("true", stored)
# ─────────────────────────────────────────────────────────────────────────────


async def db_log_answer(
    guild_id:     int | None,
    channel_id:   int,
    channel_name: str,
    author_id:    int,
    author_name:  str,
    question:     str,
    answer:       str,
    confidence:   int | None = None,
    message_id:   int | None = None,
) -> int:
    """Insert a Q&A record and return its row ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO qa_log
               (timestamp, guild_id, channel_id, channel_name,
                author_id, author_name, question, answer, confidence, message_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), guild_id, channel_id, channel_name,
             author_id, author_name, question, answer, confidence, message_id),
        )
        await db.commit()
        return cursor.lastrowid


async def db_update_message_id(row_id: int, message_id: int) -> None:
    """Store the Discord message ID of the bot's reply (for reaction tracking)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE qa_log SET message_id = ? WHERE id = ?",
            (message_id, row_id),
        )
        await db.commit()


async def db_mark_feedback(message_id: int, correct: bool) -> str | None:
    """Mark an answer as correct (True) or wrong (False). Returns the question text."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, question FROM qa_log WHERE message_id = ?", (message_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        await db.execute(
            "UPDATE qa_log SET marked_correct = ? WHERE id = ?",
            (1 if correct else 0, row[0]),
        )
        await db.commit()
        return row[1]


async def db_is_recently_answered(channel_id: int, question: str) -> bool:
    """
    True if the bot already answered a very similar question in this channel
    within ANSWER_DEDUP_TTL seconds (based on keyword overlap ≥ 70%).
    """
    since = time.time() - ANSWER_DEDUP_TTL
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT question FROM qa_log WHERE channel_id = ? AND timestamp > ?",
            (channel_id, since),
        ) as cur:
            rows = await cur.fetchall()
    q_kw = _extract_keywords(question)
    if not q_kw:
        return False
    for (prev_q,) in rows:
        prev_kw = _extract_keywords(prev_q)
        if not prev_kw:
            continue
        overlap = len(q_kw & prev_kw) / max(len(q_kw | prev_kw), 1)
        if overlap > 0.7:
            return True
    return False


async def db_get_by_message_id(message_id: int) -> dict | None:
    """Retrieve a logged Q&A by the bot's reply message ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT question, answer, confidence FROM qa_log WHERE message_id = ?",
            (message_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {"question": row[0], "answer": row[1], "confidence": row[2]}


async def db_recent_history(channel_id: int, limit: int = 10) -> list[dict]:
    """Return the most recent bot answers for a channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT timestamp, author_name, question, answer, confidence, marked_correct
               FROM qa_log WHERE channel_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (channel_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    results = []
    for ts, author, question, answer, conf, correct in rows:
        results.append({
            "timestamp": ts,
            "author":    author,
            "question":  question,
            "answer":    answer,
            "confidence": conf,
            "correct":   correct,
        })
    return results


# ─────────────────────────────────────────────
#  Bot + client setup
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.messages        = True
intents.guilds          = True

bot              = commands.Bot(command_prefix="!cdn ", intents=intents, help_command=None)
anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
user_last_answered: dict[int, float] = defaultdict(float)


# ─────────────────────────────────────────────
#  Reference channel cache
# ─────────────────────────────────────────────
_ref_cache: str        = ""
_ref_cache_time: float = 0.0


async def fetch_reference_channel() -> str:
    global _ref_cache, _ref_cache_time
    now = time.time()
    if _ref_cache and (now - _ref_cache_time) < REF_CHANNEL_CACHE_TTL:
        return _ref_cache
    channel = bot.get_channel(REFERENCE_CHANNEL_ID)
    if not channel or not isinstance(channel, discord.TextChannel):
        _log(f"Cannot find the reference channel  (ID: {REFERENCE_CHANNEL_ID})", "warn")
        return ""
    lines: list[str] = []
    try:
        async for msg in channel.history(limit=REFERENCE_CHANNEL_MSG_LIMIT, oldest_first=True):
            if msg.content.strip():
                lines.append(msg.content.strip())
    except discord.Forbidden:
        _log("No permission to read the reference channel", "warn")
        return ""
    result = "\n".join(lines)
    _ref_cache      = result
    _ref_cache_time = now
    _log(f"Reference channel ready  —  {len(lines)} message{'s' if len(lines) != 1 else ''} loaded", "ok")
    return result


# ─────────────────────────────────────────────
#  Full-site crawler (Playwright JS rendering)
# ─────────────────────────────────────────────
_page_store:      dict[str, str] = {}
_crawl_done_time: float          = 0.0
_crawl_lock                      = asyncio.Lock()


def _extract_text(html: str) -> str:
    """Extract visible text from HTML. No truncation — full content is stored.
    Truncation to CHARS_PER_PAGE happens later, only when building Claude answer context."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "noscript", "iframe", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def _normalise_url(url: str) -> str:
    """Ensure all site URLs use the canonical www. form for consistent deduplication."""
    parsed = urlparse(url)
    if parsed.netloc == "cdndayz.com":
        url = parsed._replace(netloc="www.cdndayz.com").geturl()
    return url.rstrip("/")


def _discover_links(html: str, base_url: str) -> list[str]:
    soup  = BeautifulSoup(html, "html.parser")
    base  = urlparse(CDN_WEBSITE)
    base_netloc = base.netloc.removeprefix("www.")
    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        full, _ = urldefrag(full)
        parsed  = urlparse(full)
        if parsed.netloc.removeprefix("www.") == base_netloc and parsed.scheme in ("http", "https"):
            links.append(_normalise_url(full))
    return links


async def _fetch_page_js(browser: Browser, url: str) -> tuple[str, str, str]:
    """
    Fetch a single page using Playwright headless Chromium.
    Clicks through every tab panel so conditionally-rendered content is captured.
    Returns (url, base_html, all_text) where base_html is used for link discovery
    and all_text is the combined content from every tab.
    """
    page = None
    try:
        page = await browser.new_page()
        await page.set_extra_http_headers({"User-Agent": "CDN-Captain-Bot/1.0"})
        await page.goto(url, wait_until="networkidle", timeout=20000)
        html = await page.content()

        text_parts: list[str] = [_extract_text(html)]

        # --- Tab detection strategy ---
        # The site uses plain <button> elements styled with Tailwind — none of the
        # standard ARIA selectors ([role="tab"], [data-tab], .tab-btn etc.) match.
        # Strategy: find ALL buttons, identify clusters of 2-6 that sit inside the
        # same immediate parent container (i.e. a tab bar), then click each one.
        tab_buttons = await page.evaluate("""() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            // Group by direct parent element
            const groups = new Map();
            for (const btn of buttons) {
                const parent = btn.parentElement;
                if (!parent) continue;
                const key = parent;
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push(btn);
            }
            // A tab bar has 2-6 sibling buttons with non-empty text
            const tabGroups = [];
            for (const [parent, btns] of groups) {
                const textBtns = btns.filter(b => b.innerText.trim().length > 0);
                if (textBtns.length >= 2 && textBtns.length <= 6) {
                    tabGroups.push(textBtns.map(b => b.innerText.trim()));
                }
            }
            return tabGroups;
        }""")

        if tab_buttons:
            for group in tab_buttons:
                if len(group) < 2:
                    continue
                _log(f"{len(group)} tab buttons found ({', '.join(group)})  —  {url.split('/')[-1] or 'home'}", "crawl")
                # Click tabs after the first (first is already captured in base html)
                for btn_text in group[1:]:
                    try:
                        # Use Playwright's text locator — most reliable for Tailwind buttons
                        btn = page.get_by_role("button", name=btn_text, exact=True)
                        await btn.click()
                        await page.wait_for_timeout(900)
                        tab_text = _extract_text(await page.content())
                        if tab_text and tab_text not in text_parts:
                            text_parts.append(tab_text)
                    except Exception:
                        pass

        all_text = "\n\n--- (tab) ---\n\n".join(text_parts)
        return url, html, all_text
    except Exception as exc:
        _log(f"Could not load page:  {url}  ({exc})", "warn")
        return url, "", ""
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def crawl_site(session: aiohttp.ClientSession | None) -> None:
    """
    BFS crawl of cdndayz.com using headless Chromium.
    Renders JS on every page so dynamic content (wipe schedules, etc.) is captured.
    """
    global _crawl_done_time
    async with _crawl_lock:
        if _page_store and (time.time() - _crawl_done_time) < CRAWL_CACHE_TTL:
            return

        _log("Reading cdndayz.com  —  loading all pages (renders JavaScript, takes ~15 seconds)...", "crawl")
        start      = time.time()
        visited:   set[str]       = set()
        queue:     list[str]      = [_normalise_url(CDN_WEBSITE)]
        new_store: dict[str, str] = {}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                while queue and len(visited) < MAX_PAGES_TO_CRAWL:
                    batch = []
                    while queue and len(batch) < CRAWL_CONCURRENCY:
                        url = queue.pop(0)
                        if url not in visited:
                            visited.add(url)
                            batch.append(url)
                    if not batch:
                        break

                    results = await asyncio.gather(
                        *[_fetch_page_js(browser, u) for u in batch]
                    )
                    for url, html, all_text in results:
                        if not html:
                            continue
                        if all_text:
                            new_store[url] = all_text
                        for link in _discover_links(html, url):
                            if link not in visited and link not in queue:
                                queue.append(link)
            finally:
                await browser.close()

        # Change detection: diff new content against old before replacing
        if _page_store:
            await _detect_and_announce_changes(new_store)

        _page_store.clear()
        _page_store.update(new_store)
        _crawl_done_time = time.time()
        _log(f"Website ready  —  {len(_page_store)} pages loaded in {round(time.time()-start,1)}s", "ok")


# ─────────────────────────────────────────────
#  Structured knowledge extraction
# ─────────────────────────────────────────────
_structured_knowledge: str = ""   # JSON-like facts extracted from the site

_EXTRACT_BATCH_SIZE = 5   # pages per Claude extraction call

_EXTRACTION_PROMPT = """\
You are extracting structured facts from the CDNDayz DayZ server website.
Read ALL of the content below and extract EVERY concrete fact.

CRITICAL RULES — follow these exactly, no exceptions:
- Extract EVERY fact, rule, number, policy, distance, cause, fix, and server-specific detail — miss nothing
- MAXIMUM GRANULARITY: each individual cause, fix, step, or sub-detail gets its own separate output line
  — do NOT bundle multiple causes onto one line, do NOT bundle multiple fixes onto one line
  — if something has 5 causes, write 5 lines; if something has 7 fixes, write 7 lines
- Do NOT skip content even if it seems minor, repeated, or unfamiliar
- Do NOT summarise — reproduce the actual content, not a paraphrase
- Do NOT add commentary, blank lines, or explanations
- Every output line MUST start with a TAG: prefix
- Use the existing tags listed below when they fit
- If content does not fit any existing tag, INVENT a short ALL-CAPS tag that describes it
  — never omit content just because you lack a tag for it
- Apply this same approach to any new page or section added to the website in future

Existing tags — use these when they apply:
  RULE       — any server or community rule (one rule per line)
  WIPE       — wipe schedule, dates, reset policy, rollover details
  ERROR      — error codes: one line per code description, one line per cause, one line per fix
  DONATION   — store items, payment methods, perks, rollover policy, restrictions
  SERVER_IP  — server IP addresses, names, maps, slot counts
  SCIFI      — Sci-fi Banov server details (Yrtsk weapons, rep, dungeon, blackmarket, special trader)
  REP        — reputation thresholds and how rep is earned (one threshold per line)
  DUNGEON    — dungeon rules (one rule per line: permadeath, admin teleport, entry, exit, announcements)
  TRADER     — trader info, locations, unlock conditions
  BASE       — base building rules, distances, territory rules, building systems per server
  EVENT      — community events, schedules, announcements
  FAQ        — Q&A pairs (one pair per line: FAQ: Q: question A: answer)
  JOIN       — how to join, launcher steps (one step per line)
  MOD        — mod counts, mod names, per-server mod details
  POPULATION — live player counts, peak times, server reliability, busiest hours
  NETWORK    — network infrastructure, data sources, query methods
  PRIVACY    — privacy policy details
  TERMS      — terms of service details
  LOOT       — loot zones, loot quality, economy
  ZONE       — safe zones, map zones, zone rules

Granularity examples — this is the REQUIRED level of detail:
RULE: No building within 1000 metres of any trader
RULE: Toxicity is not welcome on the CDN servers
WIPE: All CDN servers wipe approximately every 3 months (~90 days)
WIPE: Last wipe occurred on April 3, 2026
WIPE: A wipe clears all player bases
WIPE: A wipe clears all vehicles
WIPE: A wipe clears all stashed loot
WIPE: A wipe clears all character data
ERROR: 0x00040010 = ADMIN_KICK — player was removed by a server administrator or admin system
ERROR: 0x00040010 common cause = manual admin kick
ERROR: 0x00040010 common cause = rule enforcement
ERROR: 0x00040010 common cause = automated pre-restart player kick routine
ERROR: 0x00040010 fix = if a restart was announced, wait and reconnect after the server is back up
ERROR: 0x00040010 fix = contact the server admin if needed
ERROR: 0x00040010 fix = review server rules
ERROR: 0x00040093 fix = fully close DayZ and Steam, then reopen Steam and wait for Workshop updates
ERROR: 0x00040093 fix = clear the Steam download cache via Steam menu > Settings > Downloads > Clear Download Cache
ERROR: 0x00040093 fix = unsubscribe from the mod then resubscribe to force a clean re-download
SCIFI: Yrtsk Tier 1 weapons (available at Trader T1-3): Armadilo, Boar, Claw, Grizzly, Hedgehog, Puma, Wolverine
SCIFI: Yrtsk Tier 4 weapons (Blackmarket T4-5 only): A White Whisper, All of Existence, Bars, Corw, Eagle, Fang
REP: Vehicle Trader unlocks at 10,000 rep
REP: Aircraft Trader unlocks at 20,000 rep
REP: Special Trader unlocks at 25,500 rep
REP: Black Market unlocks at 50,000 rep
REP: Zombie kill = +10 rep on Sci-fi Banov
REP: Rainbow Bear kill = +100 rep on Sci-fi Banov
DUNGEON: Die inside the dungeon = permanent death, no respawns, no revives
DUNGEON: Mates may loot your gear after you die inside the dungeon
DUNGEON: Admin Teleport Both Ways — players cannot enter or exit on their own
DUNGEON: An admin must teleport you in and out of the dungeon
DUNGEON: Entering without an admin present = permanent ban
DUNGEON: Start = announce "Starting dungeon run" in chat before entering
DUNGEON: Finish = announce "Dungeon completed [Name]" in chat on completion
FAQ: Q: Is PvP allowed? A: Not on standard servers. HC servers allow territory PvP and raiding
FAQ: Q: How do I take down a BLR house? A: Claim the house, make sure it is completely empty, equip a hammer, stand outside facing the door, look at it, and select the Fold option
MOD: #1 SciFi Modded CDN Banov PVE — 44 mods — includes AgricultureCore, CBD Sci-Fi power generator, Code Lock, AJs Creatures V2
POPULATION: CDN Banov SciFi peak = 7 players on Sun 19 Apr at 14:06
POPULATION: CDN Banov SciFi busiest time = 8pm
JOIN: Step 1 = purchase DayZ on Steam
JOIN: Step 2 = download DZSA Launcher for easy mod management and server discovery
JOIN: Step 3 = search for CDN in the launcher filter to see the full list of modded PvE servers
PRIVACY: The site does not use invasive tracking pixels or advertising cookies
TERMS: In-game issues, bans, or disputes should be directed to the CDN DayZ moderation team via Discord

Only output facts. No explanations. No blank lines. No headers. No markdown.

Website content:
"""


async def extract_structured_knowledge() -> None:
    """
    After crawling, run Claude over every page in small batches to extract ALL
    structured facts. Batching prevents hitting Claude's output token limit as
    the site grows — every new page added to the website will be fully processed.
    """
    global _structured_knowledge
    if not _page_store:
        return

    all_pages  = sorted(_page_store.items(), key=lambda x: len(x[1]), reverse=True)
    all_facts:  list[str] = []
    seen_facts: set[str]  = set()
    n_batches  = math.ceil(len(all_pages) / _EXTRACT_BATCH_SIZE)

    _log(f"Extracting facts  —  {len(all_pages)} pages in {n_batches} batch{'es' if n_batches != 1 else ''}...", "crawl")

    for batch_idx in range(n_batches):
        batch   = all_pages[batch_idx * _EXTRACT_BATCH_SIZE:(batch_idx + 1) * _EXTRACT_BATCH_SIZE]
        combined = "\n\n---\n\n".join(f"[{url}]\n{text}" for url, text in batch)
        prompt  = _EXTRACTION_PROMPT + combined

        try:
            resp = await anthropic_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            for line in resp.content[0].text.strip().splitlines():
                line = line.strip()
                if line and ":" in line and line not in seen_facts:
                    seen_facts.add(line)
                    all_facts.append(line)
        except Exception as exc:
            _log(f"Extraction batch {batch_idx + 1}/{n_batches} failed:  {exc}", "warn")

    _structured_knowledge = "\n".join(all_facts)
    await db_set_state("structured_knowledge", _structured_knowledge)
    _log(f"Facts ready  —  {len(all_facts)} facts extracted across {n_batches} batch{'es' if n_batches != 1 else ''}", "ok")


# ─────────────────────────────────────────────
#  Wipe schedule parser
# ─────────────────────────────────────────────
_wipe_info: str = ""   # Human-readable wipe schedule, updated after each crawl


async def parse_wipe_schedule() -> None:
    """
    Scan all crawled pages for wipe schedule information and ask Claude to
    produce a precise, human-readable summary including the next wipe date/time.
    Stored in _wipe_info and injected into the structured facts block.
    """
    global _wipe_info
    if not _page_store:
        return

    # Find pages most likely to contain wipe info
    wipe_keywords = {"wipe", "reset", "schedule", "saturday", "sunday", "restart"}
    wipe_pages = [
        (url, text) for url, text in _page_store.items()
        if any(kw in text.lower() for kw in wipe_keywords)
    ]
    if not wipe_pages:
        _log("No wipe schedule found on the website", "warn")
        return

    combined = "\n\n---\n\n".join(f"[{url}]\n{text}" for url, text in wipe_pages[:5])

    now_str = datetime.now(timezone.utc).strftime("%A %d %B %Y %H:%M UTC")

    prompt = f"""Today's date/time (UTC): {now_str}

Read the following website content and extract the server wipe schedule.
Produce a short, precise summary that includes:
- How often wipes happen (daily/weekly/biweekly etc.)
- Which day(s) and exact time(s) wipes occur
- The NEXT upcoming wipe date and time (calculate from today's date above)
- Any map-specific wipe differences if mentioned
- Any grace periods or warnings before wipes

Be specific and precise. If you cannot determine the next wipe date, say so clearly.
Output only the wipe schedule summary — no other text.

Website content:
{combined}"""

    try:
        resp = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        _wipe_info = resp.content[0].text.strip()
        await db_set_state("wipe_info", _wipe_info)
        _log(f"Wipe schedule ready  —  {_wipe_info[:80]}{'...' if len(_wipe_info) > 80 else ''}", "ok")
    except Exception as exc:
        _log(f"Could not calculate wipe schedule:  {exc}", "warn")


async def _detect_and_announce_changes(new_store: dict[str, str]) -> None:
    """
    Compare new crawl results against the previous store.
    If meaningful content changed, post a summary to the change alert channel.
    """
    if CHANGE_ALERT_CHANNEL_ID is None:
        return

    changed_pages: list[str] = []
    for url, new_text in new_store.items():
        old_text = _page_store.get(url, "")
        if not old_text:
            continue  # new page — not a change worth alerting
        # Compare word sets to detect meaningful changes (ignores whitespace noise)
        old_words = set(old_text.lower().split())
        new_words = set(new_text.lower().split())
        added   = new_words - old_words
        removed = old_words - new_words
        # Only flag if there's a significant delta (>20 words changed)
        if len(added) + len(removed) > 20:
            changed_pages.append(url)

    if not changed_pages:
        return

    _log(f"Website updated!  —  {len(changed_pages)} page{'s' if len(changed_pages) != 1 else ''} changed since the last check", "warn")

    channel = bot.get_channel(CHANGE_ALERT_CHANNEL_ID)
    if not channel or not isinstance(channel, discord.TextChannel):
        return

    lines = "\n".join(f"• {url}" for url in changed_pages[:10])
    embed = discord.Embed(
        title="🔔 Website Update Detected",
        description=(
            f"**{len(changed_pages)} page(s)** on cdndayz.com changed since the last crawl:\n\n"
            f"{lines}\n\n"
            "My knowledge base has been automatically updated."
        ),
        color=discord.Color.orange(),
    )
    embed.set_footer(text="CDN_Captain · auto-crawl change detection")
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


async def _auto_crawl_loop():
    """Background task: re-crawl the website every AUTO_CRAWL_INTERVAL seconds."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(AUTO_CRAWL_INTERVAL)
        _log("Scheduled refresh  —  re-reading cdndayz.com and updating knowledge...", "crawl")
        global _crawl_done_time
        _crawl_done_time = 0  # force refresh
        await crawl_site(None)
        await extract_structured_knowledge()
        await parse_wipe_schedule()


# ─────────────────────────────────────────────
#  Smart content retrieval (TF-IDF style scoring)
# ─────────────────────────────────────────────
STOP_WORDS = {
    "a","an","the","is","it","in","on","at","to","do","i","my","me",
    "we","you","of","for","and","or","but","what","how","why","when",
    "who","where","can","does","will","are","was","were","did","has",
    "have","had","that","this","with","from","be","been","being",
    "they","their","there","here","just","so","if","about","get","got"
}


def _extract_keywords(text: str) -> set[str]:
    """
    Extract meaningful keywords with semantic expansion.
    e.g. "trader" also pulls in "market", "shop", "exclusion zone" etc.
    Hex error codes are always preserved exactly.
    """
    words   = re.split(r"\W+", text.lower())
    hex_codes = set(re.findall(r"0x[0-9a-fA-F]+", text, re.IGNORECASE))
    base_kw   = {w for w in words if len(w) > 2 and w not in STOP_WORDS}

    # Semantic expansion: add related terms for every matched keyword
    expanded: set[str] = set()
    for kw in base_kw:
        expanded.update(KEYWORD_EXPANSIONS.get(kw, set()))

    return base_kw | expanded | {c.lower() for c in hex_codes}


def build_site_index() -> str:
    """
    Build a compact index of every crawled page (URL + first 120 chars of content).
    Passed to Claude alongside the full content so it can see the full knowledge map.
    """
    if not _page_store:
        return "(site not yet crawled)"
    lines = []
    for url, text in sorted(_page_store.items()):
        snippet = text.replace("\n", " ")[:120].strip()
        lines.append(f"• {url}  →  {snippet}")
    return "\n".join(lines)


def _tfidf_score(keywords: set[str], text: str, url: str) -> float:
    """
    Score a page for relevance using a TF-IDF-inspired approach.
    Exact hex code matches get a massive bonus.
    """
    tl = text.lower()
    score = 0.0
    n_words = max(len(tl.split()), 1)

    for kw in keywords:
        count = tl.count(kw)
        if count == 0:
            continue
        tf  = count / n_words
        # IDF: reward rare keywords more (avoid over-scoring common words)
        doc_freq = sum(1 for t in _page_store.values() if kw in t.lower())
        idf = math.log((len(_page_store) + 1) / (doc_freq + 1)) + 1.0
        term_score = tf * idf * count  # multiply by raw count for boost

        # Big bonus for exact hex error codes
        if re.match(r"^0x[0-9a-fA-F]+$", kw):
            term_score *= 20.0

        # Bonus for keyword appearing in the URL (usually the most relevant page)
        if kw in url.lower():
            term_score *= 2.0

        score += term_score

    return score


def find_relevant_content(question: str) -> str:
    if not _page_store:
        return "(website not yet loaded)"

    keywords = _extract_keywords(question)
    if not keywords:
        # Fallback: return largest pages
        top = sorted(_page_store.items(), key=lambda x: len(x[1]), reverse=True)[:TOP_PAGES_FOR_ANSWER]
        return "\n\n══════════\n\n".join(f"[Source: {u}]\n{t[:CHARS_PER_PAGE]}" for u, t in top)

    scored = [
        (_tfidf_score(keywords, text, url), url, text)
        for url, text in _page_store.items()
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    # If the top result has zero score, fall back to largest pages
    if not scored or scored[0][0] == 0:
        top = sorted(_page_store.items(), key=lambda x: len(x[1]), reverse=True)[:TOP_PAGES_FOR_ANSWER]
        return "\n\n══════════\n\n".join(f"[Source: {u}]\n{t[:CHARS_PER_PAGE]}" for u, t in top)

    top = scored[:TOP_PAGES_FOR_ANSWER]
    return "\n\n══════════\n\n".join(f"[Source: {u}]\n{t[:CHARS_PER_PAGE]}" for _, u, t in top)


# ─────────────────────────────────────────────
#  Conversation analysis helpers
# ─────────────────────────────────────────────
TWO_PERSON_CONVO_MAX_AGE = 120   # only block if the back-and-forth happened within 2 minutes

def is_two_person_convo(recent_msgs: list[discord.Message]) -> bool:
    """
    Returns True ONLY if exactly 2 users are actively going back and forth
    AND their messages are recent (within TWO_PERSON_CONVO_MAX_AGE seconds).
    Stale conversations should never block a legitimate new question.
    """
    now = time.time()
    human_msgs = [m for m in recent_msgs if not m.author.bot][-TWO_PERSON_CONVO_WINDOW:]
    if len(human_msgs) < 4:
        return False

    # If the most recent message in the window is older than the threshold,
    # the conversation is over — don't block the new question
    most_recent_age = now - human_msgs[-1].created_at.timestamp()
    if most_recent_age > TWO_PERSON_CONVO_MAX_AGE:
        return False

    # Only count messages that are actually recent (within the window)
    active_msgs = [m for m in human_msgs
                   if (now - m.created_at.timestamp()) <= TWO_PERSON_CONVO_MAX_AGE]
    if len(active_msgs) < 4:
        return False

    # Find the two most frequently posting authors in the window.
    # Using != 2 was too strict — a single bystander message would break the guard.
    from collections import Counter
    author_counts = Counter(m.author.id for m in active_msgs)
    top_two = [aid for aid, _ in author_counts.most_common(2)]
    if len(top_two) < 2:
        return False

    # Only count alternations between the top two authors
    duo_msgs = [m for m in active_msgs if m.author.id in top_two]
    ids = [m.author.id for m in duo_msgs]
    alternations = sum(1 for i in range(1, len(ids)) if ids[i] != ids[i-1])
    return alternations >= 3


def is_directed_at_someone(message: discord.Message) -> bool:
    """Returns True if the message is a Discord reply to another human user."""
    # Primary check: resolved reply reference
    if message.reference:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and not ref.author.bot:
            return True
        # Fallback: reference exists but Discord didn't cache the resolved message.
        # If the message has exactly one non-bot mention that isn't itself,
        # treat it as directed at that person.
        if ref is None and message.reference.message_id:
            human_mentions = [
                u for u in message.mentions
                if not u.bot and (bot.user is None or u.id != bot.user.id)
            ]
            if human_mentions:
                return True
    return False


def message_is_too_old(message: discord.Message) -> bool:
    age = time.time() - message.created_at.timestamp()
    return age > MAX_MESSAGE_AGE_SECONDS


def build_rich_context(msgs: list[discord.Message], exclude_id: int) -> str:
    """
    Build a timestamped conversation log with reply chains so Claude has
    full awareness of who is talking to whom.
    """
    now = time.time()
    lines = []
    for msg in msgs:
        if msg.author.bot or msg.id == exclude_id:
            continue
        age = int(now - msg.created_at.timestamp())
        if age < 60:
            ts = f"{age}s ago"
        elif age < 3600:
            ts = f"{age//60}m ago"
        else:
            ts = f"{age//3600}h ago"
        reply_note = ""
        if msg.reference and msg.reference.resolved:
            ref = msg.reference.resolved
            if isinstance(ref, discord.Message):
                reply_note = f" [replying to {ref.author.display_name}]"
        lines.append(f"[{ts}] {msg.author.display_name}{reply_note}: {msg.content}")
    return "\n".join(lines) if lines else "(no recent context)"


async def fetch_reply_chain(message: discord.Message) -> list[dict]:
    """
    Walk backwards through the reply chain and collect every message in it.
    Returns a list of dicts: [{author, content}, ...] oldest first.
    """
    chain = []
    current = message
    depth = 0
    while current.reference and current.reference.resolved and depth < 10:
        ref = current.reference.resolved
        if not isinstance(ref, discord.Message):
            break
        chain.append({"author": ref.author.display_name, "content": ref.content})
        current = ref
        depth += 1
    chain.reverse()
    return chain


# is_recently_answered and record_answer are now handled by the DB layer above


# ─────────────────────────────────────────────
#  Image handling (multi-image support)
# ─────────────────────────────────────────────
SUPPORTED_IMAGE_TYPES = {
    "image/png":  "image/png",
    "image/jpeg": "image/jpeg",
    "image/jpg":  "image/jpeg",
    "image/gif":  "image/gif",
    "image/webp": "image/webp",
}

EXT_TO_MEDIA_TYPE = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}


def get_all_image_attachments(message: discord.Message) -> list:
    """
    Return ALL image attachments/embeds in the message (not just the first).
    Supports multi-screenshot messages.
    """
    images = []

    # 1. Direct file attachments
    for att in message.attachments:
        ct  = (att.content_type or "").lower().split(";")[0].strip()
        ext = os.path.splitext(att.filename.lower())[1]
        if ct in SUPPORTED_IMAGE_TYPES or ext in EXT_TO_MEDIA_TYPE:
            _log(f"Reading screenshot:  {att.filename}", "skip")
            images.append(att)

    # 2. Image embeds
    for embed in message.embeds:
        if embed.type == "image" and embed.url:
            _log(f"Reading image from embed:  {embed.url}", "skip")
            class _EmbedImageProxy:
                url      = embed.url
                filename = embed.url.split("?")[0].split("/")[-1] or "image.png"
            images.append(_EmbedImageProxy())  # type: ignore

    return images


async def download_image(url: str, session: aiohttp.ClientSession) -> tuple[str, str] | None:
    """Download an image URL and return (base64_data, media_type). None on failure."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            ct         = (resp.headers.get("Content-Type", "image/png")).lower().split(";")[0].strip()
            media_type = SUPPORTED_IMAGE_TYPES.get(ct, "image/png")
            data       = await resp.read()
            return base64.standard_b64encode(data).decode("utf-8"), media_type
    except Exception as exc:
        _log(f"Screenshot download failed:  {exc}", "warn")
        return None


# ─────────────────────────────────────────────
#  Admin mention check
# ─────────────────────────────────────────────
def mentions_admin(message: discord.Message) -> bool:
    # When someone replies to a message, Discord automatically adds the original
    # author as a mention. We must NOT treat that as an intentional admin tag —
    # only flag it if the user deliberately mentioned an admin outside of a reply.
    reply_author_id: int | None = None
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message):
            reply_author_id = ref.author.id

    for user in message.mentions:
        # Skip the person being replied to — Discord auto-inserts that mention
        if user.id == reply_author_id:
            continue
        if user.name.lower() in PROTECTED_ADMINS or user.display_name.lower() in PROTECTED_ADMINS:
            return True

    # Also catch plain-text @name mentions in the message body,
    # but only if this is NOT a reply to that admin
    cl = message.content.lower()
    for admin in PROTECTED_ADMINS:
        if f"@{admin}" in cl:
            # Make sure this isn't just the auto-inserted reply ping
            if reply_author_id is not None:
                replied_to = message.guild.get_member(reply_author_id) if message.guild else None
                if replied_to and (replied_to.name.lower() == admin or replied_to.display_name.lower() == admin):
                    continue  # it's just the reply ping, not an intentional tag
            return True

    return False


# ─────────────────────────────────────────────
#  Single smart Claude call — filter + answer combined
# ─────────────────────────────────────────────
async def evaluate_and_answer(
    message:            discord.Message,
    rich_context:       str,
    website_content:    str,
    ref_content:        str,
    is_two_person:      bool,
    image_data_list:    list[tuple[str, str]] | None = None,
    reply_chain:        list[dict] | None = None,
    channel_name:       str = "unknown",
    prior_bot_answer:   dict | None = None,
    force:              bool = False,
) -> str | None:
    """
    One Claude call that BOTH decides whether to respond AND generates the answer.
    Supports multiple screenshots, full reply chain context, and channel awareness.
    Returns the answer string, or None to stay silent.
    force=True skips the confidence threshold (used by !cdn ask).
    """
    has_images  = bool(image_data_list)
    n_images    = len(image_data_list) if image_data_list else 0

    # Tone matching based on channel name
    casual_keywords  = {"general", "chat", "off-topic", "offtopic", "lounge", "banter", "memes", "random"}
    formal_keywords  = {"rules", "help", "support", "info", "announcements", "faq", "guides", "tickets"}
    ch_lower = channel_name.lower()
    if any(k in ch_lower for k in casual_keywords):
        tone_note = "TONE: This is a casual channel. Keep your answer friendly, relaxed, and conversational. You can be slightly informal."
    elif any(k in ch_lower for k in formal_keywords):
        tone_note = "TONE: This is a help/rules channel. Keep your answer clear, precise, and professional."
    else:
        tone_note = "TONE: Match the tone of the conversation — friendly but informative."

    convo_note  = (
        "NOTE: The conversation above appears to be a back-and-forth between two specific users."
        if is_two_person else ""
    )
    image_note = (
        f"The user has shared {n_images} screenshot{'s' if n_images > 1 else ''}. "
        "You MUST read every word visible in each image carefully.\n"
        "For error screenshots:\n"
        "  • The error code, message text, and any instructions visible IN the image are valid sources\n"
        "  • You do NOT need the website to have the answer if the screenshot itself explains the fix\n"
        "  • Relay the fix clearly in plain language\n"
        "  • Cross-reference with website sources for additional context\n"
        "  • Only return NO_ANSWER if the image has nothing to do with DayZ or this server"
        if has_images else ""
    )
    chain_note = ""
    if reply_chain:
        chain_lines = "\n".join(f"  {m['author']}: {m['content']}" for m in reply_chain)
        chain_note  = f"\n━━ Reply Chain (what this message is replying to) ━━\n{chain_lines}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    followup_note = ""
    if prior_bot_answer:
        followup_note = (
            f"\n━━ FOLLOW-UP CONTEXT ━━\n"
            f"This message is a follow-up reply to a previous answer you gave.\n"
            f"Original question: {prior_bot_answer['question']}\n"
            f"Your previous answer: {prior_bot_answer['answer']}\n"
            f"Treat this as a continuation — answer in context of the above.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    site_index = build_site_index()

    # Build a live list of all text channels in the guild for the system prompt
    if message.guild:
        channel_list_lines = []
        for cat in sorted(message.guild.categories, key=lambda c: c.position):
            visible = [
                ch for ch in cat.channels
                if isinstance(ch, discord.TextChannel)
            ]
            if visible:
                channel_list_lines.append(f"  [{cat.name}]")
                for ch in sorted(visible, key=lambda c: c.position):
                    channel_list_lines.append(f"    <#{ch.id}> #{ch.name}")
        # Channels not in any category
        uncategorised = [
            ch for ch in message.guild.channels
            if isinstance(ch, discord.TextChannel) and ch.category is None
        ]
        if uncategorised:
            channel_list_lines.append("  [No Category]")
            for ch in sorted(uncategorised, key=lambda c: c.position):
                channel_list_lines.append(f"    <#{ch.id}> #{ch.name}")
        channel_list = "\n".join(channel_list_lines) if channel_list_lines else "  (unavailable)"
    else:
        channel_list = "  (unavailable — not in a guild)"

    system_prompt = f"""You are {BOT_NAME} — an AI assistant for the CDNDayz DayZ Discord server. You answer questions ONLY from your provided sources. You never invent, infer, or guess any fact that is not explicitly stated in those sources.

━━ CRITICAL — YOU ARE INSIDE THE DISCORD SERVER ━━
• Every user messaging you is ALREADY in this Discord server
• NEVER say "join the Discord", "join CDN Discord", or "join the server" — they are already here
• You are active in the #{channel_name} channel right now

━━ KNOWN DISCORD CHANNELS — ONLY USE THESE ━━
These are ALL the real channels in this server. You may reference any of them using <#ID> format.
NEVER invent a channel name or ID that is not in this list.
{channel_list}

━━ YOUR KNOWLEDGE SOURCES ━━

[1] STRUCTURED FACTS (extracted from the full site — use these first, they are precise):
{_structured_knowledge or "(not yet extracted — use website content below)"}

[1b] WIPE SCHEDULE (parsed and calculated — always use this for wipe questions):
{_wipe_info or "(not yet parsed — check website content)"}

[2] CDNDayz website content (most relevant pages):
{website_content}

[3] Reference channel ({REFERENCE_CHANNEL_LINK}):
{ref_content or "(unavailable)"}

[4] Full site index (every crawled page — use this to know what exists):
{site_index}
{chain_note}{followup_note}
{tone_note}
{convo_note}
{image_note}

━━ ANTI-HALLUCINATION — ABSOLUTE RULES ━━
These rules override everything else. Violating any of them is a critical failure.

  1. EVERY specific fact in your answer must be traceable to an explicit line in sources [1]–[4] above.
     If you cannot point to the exact source line, do not state the fact.

  2. NEVER infer, extrapolate, or "fill in" information that isn't written in your sources.
     "It's probably..." / "Typically in DayZ..." / "Most servers require..." = hallucination. Return {NO_ANSWER}.

  3. NEVER reference a Discord channel by guessing a name or ID. Use ONLY <#ID> mentions for
     channels that appear in the KNOWN DISCORD CHANNELS list above — nothing else.

  4. NEVER state a rule, price, distance, date, IP, requirement, or any server-specific fact unless
     it is explicitly written in your sources. If it feels right but isn't sourced, it is wrong.

  5. If answering the question fully and accurately would require ANY unsourced fact, return {NO_ANSWER}.
     A partial answer padded with guesses is worse than silence.

━━ WHEN TO ANSWER ━━

Answer the message ONLY if ALL of the following are true:
  ✔ Your sources directly and explicitly contain the information needed
  ✔ You can apply an explicitly stated rule to the specific scenario (e.g. sources say "1,000m exclusion zone" → you can confirm 420m violates it)
  ✔ Every specific fact in your answer is present in sources [1]–[4] — no gaps, no guesses

Stay silent (return {NO_ANSWER}) if ANY of the following is true:
  ✗ Your sources contain nothing explicitly related to the topic
  ✗ Answering fully would require stating any fact not in your sources
  ✗ Two people are actively chatting back-and-forth (not a community question)
  ✗ It's pure casual chat/banter with no question being asked
  ✗ A human already gave a complete, correct answer moments ago
  ✗ It's about a real-world topic with zero connection to this server or DayZ
  ✗ You are not fully confident every stated fact is sourced

⚠️ CRITICAL — NO FALLBACK RESPONSES:
  • NEVER say "check discord-rules", "open a ticket", "ask in chat", "ask the admins",
    or any variation of "I don't know but here's where to look"
  • NEVER suggest asking specific players or community members
  • NEVER give a vague "your best bet is..." response
  • If you cannot give a direct, fully-sourced, confident answer — return {NO_ANSWER}, nothing else
  • The admin tag protection already handles ticket/admin redirects — that is NOT your job
  • You are either useful or invisible. There is no middle ground.

━━ HOW TO THINK ━━

You are a strict source-based answering system. Think like a fact-checker, not a search engine:
  • Apply rules to scenarios — only rules that are EXPLICITLY stated in your sources
  • Connect dots across multiple pages only when ALL the dots are present in your sources
  • Mention related rules only if they are EXPLICITLY written in your sources
  • If the answer is "that's not allowed", say so clearly — but only if a source says so
  • If the answer requires nuance, give the nuance — but only from sourced facts
  • If you're not fully certain every fact is sourced, say nothing

━━ ERROR CODES — STRICT MATCHING ━━
  • Only respond about the EXACT error code mentioned
  • NEVER substitute with a similar code
  • If that exact code isn't in your sources or the screenshot, return {NO_ANSWER}

━━ SCREENSHOTS ━━
  • Read every word visible — error code, message text, any instructions shown
  • The text IN the image is a valid source — use it directly
  • Cross-reference with website sources for additional context
  • Only return {NO_ANSWER} if the image has nothing to do with DayZ or this server

━━ RESPONSE FORMAT ━━
  • Be direct and complete — don't pad, don't hedge
  • Format links as Discord markdown: [Page Title](https://url) — never raw URLs
  • Use **bold**, bullet points, `code blocks` where they add clarity
  • If you know a related rule the user should also be aware of, mention it
  • Never say "I don't know" — either answer precisely or stay silent
  • Return only the word {NO_ANSWER} (nothing else) when staying silent

━━ CONFIDENCE SCORING ━━
Every response MUST start with a confidence score on its own line in this exact format:
  CONFIDENCE:X
where X is a number 1–10 representing how certain you are the answer is correct and complete
based on your sources. The rest of the answer follows on the next line.

Examples:
  CONFIDENCE:9
  The next wipe is Saturday April 19 at 6PM EST.

  CONFIDENCE:4
  (you would stay silent instead — see rule below)

  {NO_ANSWER}
  (no confidence line needed when silent)

If your confidence is below 6, treat it the same as {NO_ANSWER} — return {NO_ANSWER} instead."""

    text_part = (
        f"Recent conversation in #{channel_name} (newest at bottom):\n{rich_context}\n\n"
        f"Message from {message.author.display_name}: "
        f"\"{message.content.strip() or '(shared a screenshot with no text)'}\""
    )

    # Build content blocks — interleave images if present
    if has_images:
        content_blocks = []
        for b64, media_type in image_data_list:
            content_blocks.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": media_type,
                    "data":       b64,
                },
            })
        content_blocks.append({"type": "text", "text": text_part})
    else:
        content_blocks = text_part

    try:
        resp = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": content_blocks}],
        )
        raw    = resp.content[0].text.strip()
        label  = f"screenshot×{n_images}" if has_images else message.content[:70]

        # Silent check
        if raw.upper().startswith(NO_ANSWER):
            _log(f"Stayed silent  —  \"{label}\"", "skip")
            return None

        # Parse optional CONFIDENCE:X header
        confidence: int | None = None
        answer = raw
        conf_match = re.match(r"^CONFIDENCE:(\d+)\s*\n?(.*)", raw, re.DOTALL | re.IGNORECASE)
        if conf_match:
            confidence = int(conf_match.group(1))
            answer     = conf_match.group(2).strip()
            if confidence < 6 and not force:
                _log(f"Not confident enough to answer ({confidence}/10)  —  \"{label}\"", "skip")
                return None
            _log(f"Answering  (confidence {confidence}/10)  —  \"{label}\"", "ok")
        else:
            _log(f"Answering  —  \"{label}\"", "ok")

        # Re-check after stripping confidence header
        if not answer or answer.upper().startswith(NO_ANSWER):
            return None

        # Hard post-processing filter: catch deflection/non-answers that slipped past
        # the model's NO_ANSWER instruction. These phrases mean the bot has nothing
        # sourced to say and is making up a friendly redirect instead of staying silent.
        _DEFLECTION_PATTERNS = [
            r"don'?t have (specific |that )?(info|information|details?)",
            r"(that'?s |this is )not something i have",
            r"(not in|not from) (my |our |the )?(server |site |)docs",
            r"your best bet (is|would be)",
            r"(would be|is) a better person to answer",
            r"he'?d be a better",
            r"she'?d be a better",
            r"i('?d| would) (suggest|recommend) (asking|checking with)",
            r"(ask|check with) (toby|morningstar|an admin|the admins|staff|a mod)",
            r"can'?t (find|locate|confirm) (that|this|any) (info|information|detail)",
            r"(check|look in) (the )?(discord|#|server)",
            r"open (a )?ticket",
            r"i('?m| am) not sure (about|of) (that|this)",
            r"(can vary|depends on) (the server|setup|configuration)",
        ]
        answer_lc = answer.lower()
        for pat in _DEFLECTION_PATTERNS:
            if re.search(pat, answer_lc):
                _log(f"Suppressed deflection response  —  \"{label}\"", "skip")
                return None

        # Store confidence so it can be logged to DB
        evaluate_and_answer._last_confidence = confidence
        return answer
    except anthropic.APIError as exc:
        _log(f"AI API error:  {exc}", "error")
        return None
    except Exception as exc:
        _log(f"AI error:  {exc}", "error")
        return None


# ─────────────────────────────────────────────
#  Question / help-request detection (fast, no API)
# ─────────────────────────────────────────────
QUESTION_STARTERS = {
    "who","what","when","where","why","how",
    "can","could","would","should",
    "is","are","was","were","does","do","did",
    "will","has","have","had",
}

HELP_REQUEST_PATTERNS = [
    r"\b0x[0-9a-fA-F]+\b",          # hex error codes
    r"\berror\b",
    r"\bcrash(ing|ed)?\b",
    r"\bkick(ed|ing)?\b",
    r"\bban(ned)?\b",
    r"\bcan'?t\s+(join|connect|log|play|load|see|find|access)\b",
    r"\b(won'?t|doesn'?t|not)\s+(work|load|launch|connect|start|show)\b",
    r"\bstuck\b",
    r"\bnot\s+(working|loading|connecting|showing|spawning)\b",
    r"\bkeep(s|ing)?\s+(getting|crashing|disconnecting|freezing|dying)\b",
    r"\bi\s+(got|get|keep\s+getting|have|had)\s+(an?\s+)?(error|warning|issue|problem|bug)\b",
    r"\b(issue|problem|bug)\s+(with|on|in)\b",
    r"\blag(ging|gy)?\b",
    r"\bfailed\b",
    r"\bdenied\b",
    r"\bhow\s+(do|can|to)\b",
    r"\bwhere\s+(is|are|can|do)\b",
    r"\bwhen\s+(is|will|does|do)\b",
    r"\bwhat\s+(is|are|does|do|happens?)\b",
    r"\bwipe\b",
    r"\bdonat(e|ion)\b",
    r"\brules?\b",
    r"\bwhitelist\b",
    r"\bpassword\b",
    r"\bserver\s+(ip|address|info|rules?|pass)\b",
    r"\bhow\s+to\b",
    r"\btrader\b",
    r"\bbase\s+build\b",
    r"\bbuild(ing)?\s+(near|next|close|away|from|zone)\b",
    r"\b(away|metres?|meters?)\s+from\b",   # "420m away from trader"
    r"\bwhat\s+happens?\b",
    r"\bam\s+i\s+(allowed|able|supposed)\b",
    r"\bcan\s+i\b",
    r"\bis\s+it\s+(allowed|ok|okay|fine|legal|permitted)\b",
    r"\bdo\s+i\s+(need|have\s+to|get)\b",
]

_HELP_PATTERN = re.compile("|".join(HELP_REQUEST_PATTERNS), re.IGNORECASE)


def is_question(content: str) -> bool:
    """
    Return True if the message looks like a question, problem report, or
    scenario question. Intentionally permissive — Claude is the real filter.
    We only hard-block obvious non-questions (pure chat/reactions).
    """
    content = content.strip()
    if len(content) < 6:
        return False
    if "?" in content:
        return True
    first_word = re.split(r"\W+", content)[0].lower()
    if first_word in QUESTION_STARTERS:
        return True
    if _HELP_PATTERN.search(content):
        return True
    # Also catch plain statements about the server/game that imply needing info
    # e.g. "I want to build near trader" / "just got banned" / "lost all my gear"
    server_topic = re.search(
        r"\b(dayz|server|base|loot|trader|wipe|ban|kick|error|whitelist|"
        r"gear|spawn|loot|raid|territory|flag|build|mod|password|ip|rules?|donate)\b",
        content, re.IGNORECASE
    )
    if server_topic and len(content.split()) >= 5:
        return True
    return False


# ─────────────────────────────────────────────
#  Sidekick mode — personal assistant for owner
# ─────────────────────────────────────────────
def is_sidekick_trigger(message: discord.Message) -> bool:
    """
    Returns True if the message should activate sidekick mode.
    Identity is verified by Discord user ID (unfakeable) first.
    Triggers when sent by the sidekick user AND any of:
    - Pings the bot directly (@CDN_Captain)
    - Replies to a bot message
    - Starts with "CDN" (addressing the bot by name)
    """
    # Primary check: match by user ID (cannot be faked or changed)
    is_owner = (message.author.id == SIDEKICK_USER_ID and SIDEKICK_USER_ID != 0)
    # Fallback: username match (used until SIDEKICK_USER_ID is set)
    if not is_owner:
        is_owner = (
            message.author.name.lower() == SIDEKICK_USERNAME or
            message.author.display_name.lower() == SIDEKICK_USERNAME
        )
    if not is_owner:
        return False

    # Pings the bot directly
    if bot.user and bot.user in message.mentions:
        return True
    # Replies to one of the bot's messages
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and ref.author == bot.user:
            return True
    # Starts with "CDN" (e.g. "CDN, make fun of Toby")
    if message.content.strip().lower().startswith("cdn"):
        return True
    return False


async def sidekick_answer(message: discord.Message, rich_context: str) -> str | None:
    """
    Personal assistant mode for the owner. No topic restrictions, no silence filter.
    Knows everything about the server but answers anything freely and helpfully.
    """
    # Strip the bot mention from message text if present
    content = message.content
    if bot.user:
        content = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()

    # Grab prior bot answer if this is a reply to the bot
    prior: dict | None = None
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and ref.author == bot.user:
            prior = await db_get_by_message_id(ref.id)

    prior_note = ""
    if prior:
        prior_note = f"\nYour previous answer in this conversation:\nQ: {prior['question']}\nA: {prior['answer']}\n"

    owner_name = message.author.display_name

    system_prompt = f"""You are CDN_Captain, the personal AI sidekick of {owner_name}, who runs the CDNDayz DayZ community.

You are speaking directly and privately to {owner_name} right now. He is your owner. Treat him like a smart friend — give straight, useful, no-nonsense answers.

You have full knowledge of the CDNDayz server:
{_structured_knowledge or "(knowledge loading — use general server knowledge)"}

Wipe schedule:
{_wipe_info or "(loading...)"}

How to behave:
- Answer ANYTHING he asks — server questions, general questions, ideas, opinions, whatever
- Be direct, helpful, and conversational — not robotic or formal
- For server questions, use your knowledge to give precise answers
- For anything outside the server, answer like a capable general assistant
- Keep answers concise unless he asks for more detail
- You are inside the CDNDayz Discord server right now
- Never refuse a request
{prior_note}

Recent channel context:
{rich_context}"""

    user_content = content or "(no text)"

    try:
        resp = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        answer = resp.content[0].text.strip()
        _log(f"Personal assistant  —  replied to {message.author.display_name}:  \"{content[:55]}\"", "ok")
        return answer
    except Exception as exc:
        _log(f"Personal assistant error:  {exc}", "error")
        return None


# ─────────────────────────────────────────────
#  Reply sender with rate-limit retry
# ─────────────────────────────────────────────
async def _send_with_retry(coro_fn, max_retries: int = 3) -> discord.Message:
    """
    Execute a send/reply coroutine with exponential backoff retry on rate limits.
    Ensures no answer is ever silently dropped due to Discord rate limiting.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return await coro_fn()
        except discord.errors.HTTPException as exc:
            if exc.status == 429 and attempt < max_retries:
                retry_after = getattr(exc, "retry_after", None) or (2 ** attempt)
                _log(f"Discord rate limit — waiting {retry_after:.1f}s before retrying  (attempt {attempt}/{max_retries})", "warn")
                await asyncio.sleep(retry_after)
            else:
                raise
    raise RuntimeError("Max retries exceeded")


async def _update_check_loop():
    """Background task: check GitHub for a newer release every hour."""
    global _update_available
    await asyncio.sleep(10)  # brief delay after startup
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    GITHUB_RELEASES_API,
                    headers={"Accept": "application/vnd.github+json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        latest = data.get("tag_name", "")
                        _update_available = latest not in ("", CURRENT_VERSION)
                        if _update_available:
                            _log(f"Update available!  {latest} is out  (you're running {CURRENT_VERSION})  →  {GITHUB_RELEASES_URL}", "warn")
        except Exception as exc:
            _log(f"Could not check for updates:  {exc}", "warn")
        await asyncio.sleep(3600)  # re-check every hour


async def _send_answer(message: discord.Message, answer: str) -> discord.Message:
    """Send a reply with rate-limit retry. Appends branding footer and update notice."""
    footer = f"\n-# Engineered by [Morningstar.0](<{PORTFOLIO_URL}>)"
    if _update_available:
        footer += f"\n-# ⬆️ [Bot update available](<{GITHUB_RELEASES_URL}>)"
    sent = await _send_with_retry(lambda: message.reply(answer + footer, mention_author=True))
    _log(f"Replied  ({len(answer.split())} words)", "ok")
    return sent


# ─────────────────────────────────────────────
#  Events
# ─────────────────────────────────────────────
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """
    Admin feedback system: react ✅ or ❌ to any CDN_Captain reply to mark it.
    ❌ = wrong answer (logged + bot deletes its reply to clean up)
    ✅ = correct answer (logged as confirmed good)
    Only processed when a protected admin adds the reaction.
    """
    # Only care about ✅ and ❌
    if str(payload.emoji) not in ("✅", "❌"):
        return

    # Fetch the guild member who reacted
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return

    # Only admins can give feedback
    is_admin = (
        member.name.lower() in PROTECTED_ADMINS
        or member.display_name.lower() in PROTECTED_ADMINS
        or member.guild_permissions.administrator
    )
    if not is_admin:
        return

    # Look up this message in our DB
    question = await db_mark_feedback(
        message_id=payload.message_id,
        correct=str(payload.emoji) == "✅",
    )
    if question is None:
        return  # Not a bot answer we logged

    correct = str(payload.emoji) == "✅"
    _log(f"{'Answer confirmed correct' if correct else 'Answer marked as wrong'}  by {member.display_name}  —  \"{question[:60]}\"", "ok" if correct else "warn")

    if not correct:
        # Delete the wrong answer to clean up the channel
        try:
            channel = guild.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                await msg.delete()
                _log("Wrong answer deleted from the channel", "ok")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


@bot.event
async def on_ready():
    _print_banner()
    _log(f"Connected to Discord as {bot.user}  ·  {BOT_NAME}", "ok")
    for guild in bot.guilds:
        _log(f"Joined server:  {guild.name}", "info")
    _log("Setting up answer memory...", "info")
    await init_db()
    global _bot_paused, _structured_knowledge, _wipe_info
    _bot_paused = await get_paused()
    if _bot_paused:
        _log("Starting in PAUSED mode  —  bot will not respond to the server", "warn")
    # Restore last-known facts from DB so the bot can answer immediately
    # while the fresh crawl runs — eliminates the ~90s blind window on restart
    cached_sk = await db_get_state("structured_knowledge")
    cached_wi = await db_get_state("wipe_info")
    if cached_sk:
        _structured_knowledge = cached_sk
        _log(f"Cached knowledge loaded  —  {len(_structured_knowledge.splitlines())} facts from last run", "ok")
    if cached_wi:
        _wipe_info = cached_wi
        _log("Cached wipe schedule loaded from last run", "ok")
    bot.loop.create_task(_auto_crawl_loop())
    bot.loop.create_task(_update_check_loop())
    _log("Loading website knowledge...", "info")
    await crawl_site(None)
    _log("Extracting rules, facts & server info...", "info")
    await extract_structured_knowledge()
    _log("Calculating wipe schedule...", "info")
    await parse_wipe_schedule()
    _log("Loading reference channel...", "info")
    await fetch_reference_channel()
    guild_name = bot.guilds[0].name if bot.guilds else "Unknown Server"
    _print_ready(guild_name)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
        return

    # ── Admin tag protection ───────────────────────────────────────────
    if mentions_admin(message):
        try:
            await message.reply(build_admin_tag_response(message), mention_author=True)
        except discord.HTTPException:
            pass
        return
    # ──────────────────────────────────────────────────────────────────

    content       = message.content.strip()
    img_attachments = get_all_image_attachments(message)
    has_images    = bool(img_attachments)
    channel_name  = getattr(message.channel, "name", "unknown")

    img_note = f"  +{len(img_attachments)} image{'s' if len(img_attachments) != 1 else ''}" if img_attachments else ""
    _log(f"#{channel_name}  ·  {message.author.display_name}:  \"{content[:55]}\"{img_note}", "msg")

    # ── Sidekick mode — owner only ────────────────────────────────────────────
    if is_sidekick_trigger(message):
        global _bot_paused
        msg_lower = content.lower()

        # Check for pause command
        if any(p in msg_lower for p in PAUSE_PHRASES):
            _bot_paused = True
            await set_paused(True)
            _log("Bot paused  —  will no longer respond to the server", "warn")
            try:
                resp = await anthropic_client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=100,
                    messages=[{"role": "user", "content":
                        f"{message.author.display_name} just told you (CDN_Captain) to stop responding to the server. "
                        f"He said: \"{content}\". "
                        f"Reply in 1 short sentence confirming you'll go quiet. "
                        f"Be natural and a bit personality-driven. No quotes around your reply."
                    }],
                )
                reply_text = resp.content[0].text.strip()
                await _send_with_retry(lambda: message.reply(reply_text, mention_author=True))
            except Exception:
                pass
            return

        # Check for resume command
        if any(p in msg_lower for p in RESUME_PHRASES):
            _bot_paused = False
            await set_paused(False)
            _log("Bot resumed  —  back to watching all channels", "ok")
            try:
                resp = await anthropic_client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=100,
                    messages=[{"role": "user", "content":
                        f"{message.author.display_name} just told you (CDN_Captain) to start responding to the server again. "
                        f"He said: \"{content}\". "
                        f"Reply in 1 short sentence confirming you're back. "
                        f"Be natural and a bit personality-driven. No quotes around your reply."
                    }],
                )
                reply_text = resp.content[0].text.strip()
                await _send_with_retry(lambda: message.reply(reply_text, mention_author=True))
            except Exception:
                pass
            return

        # Normal sidekick response
        recent_msgs_s: list[discord.Message] = []
        try:
            async for m in message.channel.history(limit=20):
                if m.id != message.id:
                    recent_msgs_s.append(m)
        except Exception:
            pass
        recent_msgs_s.reverse()
        rich_ctx_s = build_rich_context(recent_msgs_s, exclude_id=message.id)
        answer = await sidekick_answer(message, rich_ctx_s)
        if answer:
            try:
                await _send_with_retry(lambda: message.reply(answer, mention_author=True))
            except discord.HTTPException as exc:
                _log(f"Personal assistant reply failed:  {exc}", "error")
        return

    # ── Pause guard — ignore everyone else when paused ────────────────────────
    if _bot_paused:
        return
    # ─────────────────────────────────────────────────────────────────────────

    # Fast pre-checks — no API cost
    if message_is_too_old(message):
        return

    # For text-only messages, require a question shape
    # Image messages: always attempt (screenshot = implied help request)
    if not has_images:
        if not content or len(content) < 8:
            return
        if not is_question(content):
            return
        if is_directed_at_someone(message):
            _log(f"Skipped  —  message is a reply to someone else", "skip")
            return

    # Cooldown (per user)
    user_id = message.author.id
    now     = time.time()
    if now - user_last_answered[user_id] < USER_COOLDOWN_SECONDS:
        return

    # Deduplication: skip if very similar question was answered recently in this channel
    if not has_images and await db_is_recently_answered(message.channel.id, content):
        _log(f"Skipped  —  this question was already answered recently", "skip")
        return

    # Fetch conversation context
    recent_msgs: list[discord.Message] = []
    try:
        async for m in message.channel.history(limit=CONTEXT_MESSAGE_LIMIT + 5):
            if m.id != message.id:
                recent_msgs.append(m)
            if len(recent_msgs) >= CONTEXT_MESSAGE_LIMIT:
                break
    except discord.Forbidden:
        pass
    except discord.errors.DiscordServerError as exc:
        # Discord returned a 503 / temporary server error — skip this message silently
        _log(f"Discord server error fetching channel history, skipping:  {exc}", "warn")
        return
    except Exception as exc:
        # Any other unexpected network/API error — log and skip rather than crash
        _log(f"Unexpected error reading channel history:  {exc}", "warn")
        return
    recent_msgs.reverse()

    rich_ctx   = build_rich_context(recent_msgs, exclude_id=message.id)
    two_person = is_two_person_convo(recent_msgs)

    # Don't interrupt two-person convos unless they shared an image
    if two_person and not has_images:
        _log("Skipped  —  two people are mid-conversation", "skip")
        return

    # Fetch reply chain + check if this is a follow-up to a previous bot answer
    reply_chain    = await fetch_reply_chain(message) if message.reference else None
    prior_bot_answer: dict | None = None
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and ref.author == bot.user:
            # This is a reply to the bot — look up the original Q&A from DB
            prior_bot_answer = await db_get_by_message_id(ref.id)

    # Load knowledge sources
    ref_content = await fetch_reference_channel()
    await crawl_site(None)

    # Download all images
    image_data_list: list[tuple[str, str]] = []
    if has_images:
        async with aiohttp.ClientSession() as session:
            for img_att in img_attachments:
                data = await download_image(img_att.url, session)
                if data:
                    image_data_list.append(data)
        if not image_data_list:
            _log("All screenshot downloads failed — skipping this message", "warn")
            return

    website_content = find_relevant_content(content or "error help troubleshoot")

    # Single smart Claude call — decides + answers in one shot
    answer = await evaluate_and_answer(
        message, rich_ctx, website_content, ref_content, two_person,
        image_data_list=image_data_list or None,
        reply_chain=reply_chain,
        channel_name=channel_name,
        prior_bot_answer=prior_bot_answer,
    )

    if answer is None:
        return

    user_last_answered[user_id] = now

    try:
        sent = await _send_answer(message, answer)
        last_conf = getattr(evaluate_and_answer, "_last_confidence", None)
        row_id = await db_log_answer(
            guild_id     = message.guild.id if message.guild else None,
            channel_id   = message.channel.id,
            channel_name = channel_name,
            author_id    = message.author.id,
            author_name  = message.author.display_name,
            question     = content,
            answer       = answer,
            confidence   = last_conf,
            message_id   = sent.id,
        )
        _log(f"Answer saved to memory  (record #{row_id})", "skip")
    except discord.HTTPException as exc:
        _log(f"Failed to send reply:  {exc}", "error")


# ─────────────────────────────────────────────
#  Command permission check
# ─────────────────────────────────────────────
def _is_admin(ctx: commands.Context) -> bool:
    """Allow owner (SIDEKICK_USER_ID) or any Discord administrator."""
    if ctx.author.id == SIDEKICK_USER_ID:
        return True
    if isinstance(ctx.author, discord.Member):
        return ctx.author.guild_permissions.administrator
    return False


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Silently ignore check failures and unknown commands."""
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    raise error


# ─────────────────────────────────────────────
#  Commands
# ─────────────────────────────────────────────
@bot.command(name="help")
@commands.check(_is_admin)
async def cdn_help(ctx: commands.Context):
    embed = discord.Embed(
        title=f"👋  {BOT_NAME}",
        description=(
            "I watch every channel quietly and only speak up when I have a "
            "real answer from **cdndayz.com** or the server's reference channel.\n"
            "I won't interrupt conversations or guess."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="When I respond",
        value=(
            "✔ Unanswered community question with a clear answer in my sources\n"
            "✔ Error screenshots — I'll read and diagnose them\n"
            "✔ Multiple screenshots in one message\n"
            "✘ Two people chatting back-and-forth\n"
            "✘ Questions directed at a specific person\n"
            "✘ Topics not covered by my sources\n"
            "✘ Duplicate questions answered recently"
        ),
        inline=False,
    )
    embed.add_field(
        name="Commands",
        value="`!cdn help` · `!cdn ask <question>` · `!cdn crawl` · `!cdn status`",
        inline=False,
    )
    embed.add_field(
        name="Knowledge base",
        value=f"**{len(_page_store)} pages** crawled from cdndayz.com + [reference channel]({REFERENCE_CHANNEL_LINK})",
        inline=False,
    )
    embed.set_footer(text="Powered by Claude · cdndayz.com · Auto-refreshes every hour")
    await ctx.send(embed=embed)


@bot.command(name="ask")
@commands.check(_is_admin)
async def cdn_ask(ctx: commands.Context, *, question: str):
    """Force an answer, bypassing all filters."""
    ref_content     = await fetch_reference_channel()
    await crawl_site(None)
    website_content = find_relevant_content(question)
    rich_ctx        = await _get_ctx_for_command(ctx)
    answer = await evaluate_and_answer(
        ctx.message, rich_ctx, website_content, ref_content, False,
        channel_name=getattr(ctx.channel, "name", "unknown"),
        force=True,
    )
    if answer is None:
        await ctx.reply(
            "I couldn't find that in cdndayz.com or the reference channel.",
            mention_author=True,
        )
        return
    await ctx.reply(answer, mention_author=True)


@bot.command(name="facts")
@commands.check(_is_admin)
async def cdn_facts(ctx: commands.Context):
    """Dump the full structured knowledge base as a text file."""
    if not _structured_knowledge:
        await ctx.reply(
            "No structured knowledge extracted yet. Try `!cdn crawl` first.",
            mention_author=True,
        )
        return
    lines = _structured_knowledge.splitlines()
    header = f"CDN_Captain Structured Knowledge — {len(lines)} facts\n" + "─" * 50 + "\n\n"
    buf = io.BytesIO((header + _structured_knowledge).encode("utf-8"))
    await ctx.reply(
        f"📋 **{len(lines)} facts** currently in the knowledge base:",
        file=discord.File(buf, filename="cdn_facts.txt"),
        mention_author=True,
    )


@bot.command(name="crawl")
@commands.check(_is_admin)
async def cdn_crawl(ctx: commands.Context):
    """Force a fresh re-crawl of cdndayz.com."""
    msg = await ctx.send("🔍 Re-crawling cdndayz.com (rendering JavaScript) — this may take a moment...")
    global _crawl_done_time
    _crawl_done_time = 0
    await crawl_site(None)
    await msg.edit(content=f"✅ Loaded **{len(_page_store)} pages** from cdndayz.com.")


@bot.command(name="ping")
@commands.check(_is_admin)
async def cdn_ping(ctx: commands.Context):
    """Health check — latency, uptime, crawl age, DB stats."""
    import os, sys

    # Latency
    latency_ms = round(bot.latency * 1000)

    # Uptime
    uptime_sec = int(time.time() - _bot_start_time)
    if uptime_sec < 3600:
        uptime_str = f"{uptime_sec // 60}m {uptime_sec % 60}s"
    else:
        uptime_str = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m"

    # Crawl age
    crawl_age = int(time.time() - _crawl_done_time) if _crawl_done_time else None
    crawl_str = (
        f"{crawl_age // 60}m ago · {len(_page_store)} pages"
        if crawl_age is not None else "⚠️ Not crawled"
    )

    # DB size
    db_size = "N/A"
    try:
        db_size = f"{os.path.getsize(DB_PATH) // 1024} KB"
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM qa_log") as cur:
                row = await cur.fetchone()
                db_answers = row[0] if row else 0
    except Exception:
        db_answers = 0

    # Memory usage (rough)
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem_mb = round(proc.memory_info().rss / 1024 / 1024, 1)
        mem_str = f"{mem_mb} MB"
    except ImportError:
        mem_str = "install psutil for memory stats"

    # Structured knowledge
    sk_lines = len(_structured_knowledge.splitlines()) if _structured_knowledge else 0

    embed = discord.Embed(title="🏓  CDN_Captain Health", color=discord.Color.green())
    embed.add_field(name="Latency",          value=f"{latency_ms}ms",  inline=True)
    embed.add_field(name="Uptime",           value=uptime_str,          inline=True)
    embed.add_field(name="Memory",           value=mem_str,             inline=True)
    embed.add_field(name="Website Crawl",    value=crawl_str,           inline=False)
    embed.add_field(name="Structured Facts", value=f"{sk_lines} facts extracted", inline=True)
    embed.add_field(name="DB",               value=f"{db_answers} answers · {db_size}", inline=True)
    embed.add_field(name="Wipe Info",        value=_wipe_info[:80] + "..." if len(_wipe_info) > 80 else (_wipe_info or "⚠️ Not parsed"), inline=False)
    embed.set_footer(text=f"Python {sys.version.split()[0]} · claude-sonnet-4-6")
    await ctx.send(embed=embed)


@bot.command(name="history")
@commands.check(_is_admin)
async def cdn_history(ctx: commands.Context):
    """Show the last 10 answers the bot gave in this channel."""
    records = await db_recent_history(ctx.channel.id, limit=10)
    if not records:
        await ctx.send("No answers logged for this channel yet.")
        return
    lines = []
    for r in records:
        age   = int(time.time() - r["timestamp"])
        ts    = f"{age//60}m ago" if age < 3600 else f"{age//3600}h ago"
        conf  = f" · confidence {r['confidence']}/10" if r["confidence"] else ""
        fb    = " ✅" if r["correct"] == 1 else (" ❌" if r["correct"] == 0 else "")
        lines.append(f"**[{ts}]** {r['author']}: *{r['question'][:80]}*{conf}{fb}")
    embed = discord.Embed(
        title=f"📜 Recent answers in #{ctx.channel.name}",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed)


@bot.command(name="status")
@commands.check(_is_admin)
async def cdn_status(ctx: commands.Context):
    """Show current bot status and knowledge base stats."""
    now = time.time()
    crawl_age = int(now - _crawl_done_time) if _crawl_done_time else None
    ref_age   = int(now - _ref_cache_time) if _ref_cache_time else None

    if crawl_age is None:
        crawl_str = "⚠️ Not crawled yet"
    elif crawl_age < 60:
        crawl_str = f"✅ {crawl_age}s ago ({len(_page_store)} pages)"
    elif crawl_age < 3600:
        crawl_str = f"✅ {crawl_age//60}m ago ({len(_page_store)} pages)"
    else:
        crawl_str = f"🔄 {crawl_age//3600}h ago ({len(_page_store)} pages) — refresh soon"

    ref_str = (
        "⚠️ Not loaded" if ref_age is None
        else f"✅ {ref_age//60}m ago" if ref_age < 3600
        else f"🔄 {ref_age//3600}h ago"
    )

    embed = discord.Embed(title=f"📊  {BOT_NAME} Status", color=discord.Color.green())
    embed.add_field(name="Website Crawl",      value=crawl_str, inline=False)
    embed.add_field(name="Reference Channel",  value=ref_str,   inline=False)
    embed.add_field(name="Model",              value="Claude Sonnet (claude-sonnet-4-6)", inline=False)
    embed.add_field(name="Context Window",     value=f"{CONTEXT_MESSAGE_LIMIT} messages", inline=False)
    embed.add_field(name="Auto-crawl",         value=f"Every {AUTO_CRAWL_INTERVAL//60} minutes", inline=False)
    embed.set_footer(text="cdndayz.com")
    await ctx.send(embed=embed)


async def _get_ctx_for_command(ctx: commands.Context) -> str:
    msgs: list[discord.Message] = []
    try:
        async for m in ctx.channel.history(limit=CONTEXT_MESSAGE_LIMIT):
            if m.id != ctx.message.id:
                msgs.append(m)
    except discord.Forbidden:
        pass
    msgs.reverse()
    return build_rich_context(msgs, exclude_id=ctx.message.id)


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set in .env")
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
    bot.run(DISCORD_TOKEN)
