# CDN_Captain v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild CDN_Captain as a retrieval-first Discord bot: weekly crawl of cdndayz.com into a local `facts.db`, free local retrieval that gates every API call, one small Haiku 4.5 answer call with citation verification and an enforced grounding check.

**Architecture:** Five focused modules replace the old 3,000-line monolith. `knowledge.py` owns the SQLite fact store (crawled facts + `knowledge.txt` manual facts, manual wins). `retrieval.py` scores facts locally — no facts means silence and $0. `answering.py` makes exactly one Haiku call, requires the answer to cite fact IDs, verifies citations deterministically, then runs an enforced grounding verifier. `crawler.py` refreshes the fact DB weekly, re-extracting only changed pages. `bot.py` is Discord wiring only.

**Tech Stack:** Python 3.12, discord.py, anthropic (async SDK), aiosqlite, Playwright + BeautifulSoup (crawl), pytest (via `asyncio.run`, no pytest-asyncio dependency).

## Global Constraints

- Model for ALL API calls: `claude-haiku-4-5-20251001` (config name `ANSWER_MODEL`, overridable via env).
- Silence must cost $0: no API call may happen before local retrieval finds facts (screenshots are the one exception — they always attempt).
- The model NEVER does date math. Next-wipe dates are computed in Python (`knowledge.compute_next_wipe`).
- Manual facts from `knowledge.txt` always override crawled facts (loaded with `manual=1`, sorted first).
- The answer system prompt is a frozen module-level constant — byte-identical across calls, no interpolation.
- Per-answer results are returned as values (dataclass), never stashed on function attributes.
- Grounding verification is ENFORCED (suppresses), fails open only on API errors.
- Secrets (`DISCORD_TOKEN`, `ANTHROPIC_API_KEY`) must be redacted from every log line.
- Keep working: admin-tag protection (5pntjoe, strikezx), 👍/👎 + admin ✅/❌ reactions, pause/sidekick, `!cdn` commands, KB-empty owner alerts.
- `facts.db` and `memory.db` live in the working directory (Docker volume in deployment).
- Existing `memory.db` may have a legacy `qa_log` schema with extra columns — all INSERTs must name their columns explicitly.

---

## File structure

```
config.py               constants, env loading, validate_config()
logging_util.py         coloured console log with secret redaction
db.py                   memory.db: qa_log, bot_state (HMAC pause), answer_feedback, jsonl logs
knowledge.py            facts.db store, knowledge.txt loader, fact cache, wipe computation
retrieval.py            keywords, expansions, BM25-ish scoring, threshold gate
answering.py            answer prompt, Haiku call, citation check, grounding verifier
crawler.py              Playwright crawl, page hashing, extraction, ref-channel ingest, weekly loop
bot.py                  Discord events, commands, reactions, background tasks
tests/test_config.py
tests/test_db.py
tests/test_knowledge.py
tests/test_retrieval.py
tests/test_answering.py
tests/test_crawler.py
tests/test_golden_offline.py
tests/run_golden_live.py   (manual, env-gated live harness)
```

---

### Task 1: Scaffold — config, logging, requirements

**Files:**
- Create: `config.py`, `logging_util.py`
- Modify: `requirements.txt`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: every constant below (later tasks import from `config`); `validate_config() -> list[str]`; `logging_util.log(msg: str, level: str = "info") -> None` and `logging_util.redact(text: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import importlib


def test_validate_config_reports_missing_tokens(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)              # keep the repo's real .env out of reach
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import config
    importlib.reload(config)
    problems = config.validate_config()
    assert any("DISCORD_TOKEN" in p for p in problems)
    assert any("ANTHROPIC_API_KEY" in p for p in problems)


def test_validate_config_ok(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    import config
    importlib.reload(config)
    assert config.validate_config() == []


def test_redact_strips_secrets(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "supersecrettoken")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc")
    import config, logging_util
    importlib.reload(config)
    importlib.reload(logging_util)
    out = logging_util.redact("err supersecrettoken and sk-ant-abc done")
    assert "supersecrettoken" not in out
    assert "sk-ant-abc" not in out
```

Note: `load_dotenv()` must not override the monkeypatched env — use `load_dotenv(override=False)` (the default) and the tests must run from a cwd without `.env`, OR simpler: `config.py` reads env at import; tests reload it. Since the repo cwd HAS a `.env` with real tokens, the missing-token test must also point dotenv away: add `monkeypatch.chdir(tmp_path)` as the first line of `test_validate_config_reports_missing_tokens` and accept `tmp_path` as an argument. dotenv only auto-loads `./.env`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL / ERROR with "No module named 'config'"

- [ ] **Step 3: Write the implementation**

```python
# config.py
"""CDN_Captain v2 configuration. All constants live here; no other module reads env vars."""
import os
from dotenv import load_dotenv

load_dotenv()

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
```

```python
# logging_util.py
"""Coloured console logging with secret redaction. Optional plain-text LOG_FILE mirror."""
from datetime import datetime, timezone

import config

_RST, _BOLD = "\033[0m", "\033[1m"
_GRN, _YLW, _RED, _CYN, _BLU, _GRY, _WHT = (
    "\033[92m", "\033[93m", "\033[91m", "\033[96m", "\033[94m", "\033[90m", "\033[97m",
)

_LEVEL = {
    "ok":    ("✓", _GRN, _WHT),
    "warn":  ("!", _YLW, _YLW),
    "error": ("✗", _RED, _RED),
    "info":  ("•", _CYN, _WHT),
    "skip":  ("·", _GRY, _GRY),
    "msg":   ("►", _BLU, _CYN),
    "crawl": ("↻", _YLW, _WHT),
}


def redact(text: str) -> str:
    """Strip known secrets from any string before it reaches a log/console."""
    for secret in (config.DISCORD_TOKEN, config.ANTHROPIC_API_KEY):
        if secret and secret in text:
            text = text.replace(secret, "***redacted***")
    return text


def log(msg: str, level: str = "info") -> None:
    msg = redact(msg)
    icon, icol, tcol = _LEVEL.get(level, ("·", _GRY, _WHT))
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  {_GRY}{ts}{_RST}  {icol}{icon}{_RST}  {tcol}{msg}{_RST}")
    if config.LOG_FILE:
        try:
            with open(config.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} [{level.upper():<5}] {msg}\n")
        except Exception:
            pass  # logging must never crash the bot
```

```
# requirements.txt
discord.py>=2.3.0
anthropic>=0.30.0
aiohttp>=3.9.0
beautifulsoup4>=4.12.0
python-dotenv>=1.0.0
playwright>=1.40.0
aiosqlite>=0.20.0
pytest>=8.0.0
```

```
# .env.example
# ─────────────────────────────────────────────
#  CDN_Captain v2 — Environment Variables
#  Copy this file to .env and fill in your values
# ─────────────────────────────────────────────

# Your Discord bot token (from Discord Developer Portal)
DISCORD_TOKEN=your_discord_bot_token_here

# Your Anthropic API key (from console.anthropic.com)
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Optional overrides (defaults shown)
# ANSWER_MODEL=claude-haiku-4-5-20251001
# CRAWL_INTERVAL_SECONDS=604800
# LOG_FILE=
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add config.py logging_util.py requirements.txt .env.example tests/test_config.py
git commit -m "feat: v2 scaffold — config, redacting logger, requirements"
```

---

### Task 2: db.py — memory.db layer

**Files:**
- Create: `db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `config.MEMORY_DB_PATH`, `config.DISCORD_TOKEN`.
- Produces (all `async` unless noted, all take optional `db_path: str | None = None` defaulting to `config.MEMORY_DB_PATH` for testability):
  - `init_db(db_path=None) -> None`
  - `get_state(key, default="", db_path=None) -> str` / `set_state(key, value, db_path=None) -> None`
  - `set_paused(paused: bool, db_path=None)` / `get_paused(db_path=None) -> bool` (HMAC-signed)
  - `log_answer(*, guild_id, channel_id, channel_name, author_id, author_name, question, answer, grounded, message_id, db_path=None) -> int`
  - `mark_feedback(message_id, correct: bool, db_path=None) -> str | None`
  - `record_feedback_vote(message_id, user_id, vote: int, db_path=None) -> tuple[int, int]`
  - `get_by_message_id(message_id, db_path=None) -> dict | None` (keys: question, answer, grounded, marked_correct)
  - `is_replayable(prior: dict | None) -> bool` (sync)
  - `recent_questions(channel_id, since: float, db_path=None) -> list[str]`
  - `recent_history(channel_id, limit=10, db_path=None) -> list[dict]`
  - `append_jsonl(path: str, record: dict) -> None` (sync, best-effort)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
import asyncio


def test_state_roundtrip(tmp_path):
    import db
    p = str(tmp_path / "m.db")

    async def run():
        await db.init_db(p)
        assert await db.get_state("k", "d", db_path=p) == "d"
        await db.set_state("k", "v", db_path=p)
        assert await db.get_state("k", db_path=p) == "v"
    asyncio.run(run())


def test_pause_hmac_roundtrip(tmp_path):
    import db
    p = str(tmp_path / "m.db")

    async def run():
        await db.init_db(p)
        assert await db.get_paused(db_path=p) is False
        await db.set_paused(True, db_path=p)
        assert await db.get_paused(db_path=p) is True
        # Tampering: overwrite with garbage -> defaults to unpaused
        await db.set_state("_s", "deadbeef", db_path=p)
        assert await db.get_paused(db_path=p) is False
    asyncio.run(run())


def test_feedback_vote_idempotent_per_user(tmp_path):
    import db
    p = str(tmp_path / "m.db")

    async def run():
        await db.init_db(p)
        up, down = await db.record_feedback_vote(111, 1, -1, db_path=p)
        assert (up, down) == (0, 1)
        # Same user re-votes: updates, doesn't double count
        up, down = await db.record_feedback_vote(111, 1, 1, db_path=p)
        assert (up, down) == (1, 0)
        up, down = await db.record_feedback_vote(111, 2, -1, db_path=p)
        assert (up, down) == (1, 1)
    asyncio.run(run())


def test_log_answer_and_feedback(tmp_path):
    import db
    p = str(tmp_path / "m.db")

    async def run():
        await db.init_db(p)
        row = await db.log_answer(
            guild_id=1, channel_id=2, channel_name="general", author_id=3,
            author_name="bob", question="q?", answer="a", grounded=1,
            message_id=999, db_path=p,
        )
        assert row >= 1
        rec = await db.get_by_message_id(999, db_path=p)
        assert rec["question"] == "q?" and rec["grounded"] == 1
        assert db.is_replayable(rec) is True
        q = await db.mark_feedback(999, correct=False, db_path=p)
        assert q == "q?"
        rec = await db.get_by_message_id(999, db_path=p)
        assert db.is_replayable(rec) is False   # admin-marked wrong -> never replay
        assert db.is_replayable({"grounded": 0, "marked_correct": None}) is False
    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -v`
Expected: ERROR "No module named 'db'"

- [ ] **Step 3: Write the implementation**

```python
# db.py
"""memory.db layer: Q&A log, persistent state (HMAC-signed pause), community feedback."""
import hashlib
import hmac
import json
import time

import aiosqlite

import config
from logging_util import log


def _path(db_path: str | None) -> str:
    return db_path or config.MEMORY_DB_PATH


async def init_db(db_path: str | None = None) -> None:
    async with aiosqlite.connect(_path(db_path)) as db:
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
                marked_correct INTEGER DEFAULT NULL,
                message_id    INTEGER DEFAULT NULL,
                grounded      INTEGER DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS answer_feedback (
                message_id INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                vote       INTEGER NOT NULL,
                timestamp  REAL    NOT NULL,
                PRIMARY KEY (message_id, user_id)
            )
        """)
        await db.commit()
    log("Answer memory ready (memory.db)", "ok")


async def get_state(key: str, default: str = "", db_path: str | None = None) -> str:
    async with aiosqlite.connect(_path(db_path)) as db:
        async with db.execute("SELECT value FROM bot_state WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else default


async def set_state(key: str, value: str, db_path: str | None = None) -> None:
    async with aiosqlite.connect(_path(db_path)) as db:
        await db.execute(
            "INSERT INTO bot_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


# ── HMAC-signed pause state (tamper-proof) ────────────────────────────────────
def _sign(value: str) -> str:
    secret = (config.DISCORD_TOKEN or "fallback").encode()
    return hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()


async def set_paused(paused: bool, db_path: str | None = None) -> None:
    await set_state("_s", _sign("true" if paused else "false"), db_path=db_path)


async def get_paused(db_path: str | None = None) -> bool:
    stored = await get_state("_s", "", db_path=db_path)
    if not stored:
        return False
    return hmac.compare_digest(_sign("true"), stored)


# ── Q&A log ──────────────────────────────────────────────────────────────────
async def log_answer(*, guild_id, channel_id, channel_name, author_id, author_name,
                     question, answer, grounded, message_id,
                     db_path: str | None = None) -> int:
    async with aiosqlite.connect(_path(db_path)) as db:
        cur = await db.execute(
            "INSERT INTO qa_log (timestamp, guild_id, channel_id, channel_name, "
            "author_id, author_name, question, answer, grounded, message_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), guild_id, channel_id, channel_name,
             author_id, author_name, question, answer, grounded, message_id),
        )
        await db.commit()
        return cur.lastrowid


async def get_by_message_id(message_id: int, db_path: str | None = None) -> dict | None:
    async with aiosqlite.connect(_path(db_path)) as db:
        async with db.execute(
            "SELECT question, answer, grounded, marked_correct FROM qa_log WHERE message_id = ?",
            (message_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {"question": row[0], "answer": row[1], "grounded": row[2], "marked_correct": row[3]}


def is_replayable(prior: dict | None) -> bool:
    """A prior answer may seed a follow-up ONLY if it wasn't ungrounded or admin-marked wrong."""
    if not prior:
        return False
    if prior.get("grounded") == 0:
        return False
    if prior.get("marked_correct") == 0:
        return False
    return True


async def mark_feedback(message_id: int, correct: bool, db_path: str | None = None) -> str | None:
    async with aiosqlite.connect(_path(db_path)) as db:
        async with db.execute(
            "SELECT id, question FROM qa_log WHERE message_id = ?", (message_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        await db.execute("UPDATE qa_log SET marked_correct = ? WHERE id = ?",
                         (1 if correct else 0, row[0]))
        await db.commit()
        return row[1]


async def record_feedback_vote(message_id: int, user_id: int, vote: int,
                               db_path: str | None = None) -> tuple[int, int]:
    async with aiosqlite.connect(_path(db_path)) as db:
        await db.execute(
            "INSERT INTO answer_feedback (message_id, user_id, vote, timestamp) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(message_id, user_id) DO UPDATE SET vote = excluded.vote, "
            "timestamp = excluded.timestamp",
            (message_id, user_id, vote, time.time()),
        )
        await db.commit()
        async with db.execute(
            "SELECT COALESCE(SUM(CASE WHEN vote > 0 THEN 1 ELSE 0 END), 0), "
            "       COALESCE(SUM(CASE WHEN vote < 0 THEN 1 ELSE 0 END), 0) "
            "FROM answer_feedback WHERE message_id = ?",
            (message_id,),
        ) as cur:
            row = await cur.fetchone()
    return (row[0] or 0, row[1] or 0)


async def recent_questions(channel_id: int, since: float, db_path: str | None = None) -> list[str]:
    async with aiosqlite.connect(_path(db_path)) as db:
        async with db.execute(
            "SELECT question FROM qa_log WHERE channel_id = ? AND timestamp > ?",
            (channel_id, since),
        ) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def recent_history(channel_id: int, limit: int = 10, db_path: str | None = None) -> list[dict]:
    async with aiosqlite.connect(_path(db_path)) as db:
        async with db.execute(
            "SELECT timestamp, author_name, question, answer, marked_correct "
            "FROM qa_log WHERE channel_id = ? ORDER BY timestamp DESC LIMIT ?",
            (channel_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [{"timestamp": r[0], "author": r[1], "question": r[2],
             "answer": r[3], "correct": r[4]} for r in rows]


def append_jsonl(path: str, record: dict) -> None:
    """Append one JSON record as a line. Best-effort; never raises."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        log(f"Could not write log file {path}: {exc}", "warn")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: memory.db layer — qa log, HMAC pause state, feedback votes"
```

---

### Task 3: knowledge.py — fact store + manual overlay

**Files:**
- Create: `knowledge.py`
- Test: `tests/test_knowledge.py`

**Interfaces:**
- Consumes: `config.FACTS_DB_PATH`, `config.KNOWLEDGE_FILE`, `logging_util.log`.
- Produces:
  - `@dataclass(frozen=True) Fact(id: int, tag: str, text: str, source: str, manual: bool)`
  - `parse_fact_line(line: str) -> tuple[str, str] | None` (sync)
  - `init_facts_db(db_path=None) -> None`
  - `load_manual_facts(db_path=None, knowledge_file=None) -> int`
  - `replace_page_facts(url, content_hash, extracted: list[tuple[str, str]], db_path=None) -> None`
  - `touch_page(url, db_path=None) -> None`
  - `get_page_hashes(db_path=None) -> dict[str, str]`
  - `retire_pages(live_urls: set[str], db_path=None) -> int` (only touches `http*` sources)
  - `reload_facts(db_path=None) -> int` (refills in-memory cache; manual facts first)
  - `facts() -> list[Fact]` (sync, cached)
  - `last_crawl_time(db_path=None) -> float | None`
  - `compute_next_wipe(fact_list: list[Fact], today: date) -> str | None` (sync — Task 4)
- Note: all DB functions are `async`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_knowledge.py
import asyncio


def test_parse_fact_line():
    import knowledge as k
    assert k.parse_fact_line("RULE: No PvP on standard servers") == ("RULE", "No PvP on standard servers")
    assert k.parse_fact_line("# comment") is None
    assert k.parse_fact_line("") is None
    assert k.parse_fact_line("no tag here") is None
    assert k.parse_fact_line("  REP: Black Market unlocks at 50,000 rep  ") == ("REP", "Black Market unlocks at 50,000 rep")


def test_manual_facts_load_and_override(tmp_path):
    import knowledge as k
    dbp = str(tmp_path / "facts.db")
    kf = tmp_path / "knowledge.txt"
    kf.write_text("# header\nRULE: manual rule one\nREP: manual rep fact\n", encoding="utf-8")

    async def run():
        await k.init_facts_db(dbp)
        n = await k.load_manual_facts(db_path=dbp, knowledge_file=str(kf))
        assert n == 2
        await k.replace_page_facts("https://x.com/a", "h1", [("RULE", "crawled rule")], db_path=dbp)
        total = await k.reload_facts(db_path=dbp)
        assert total == 3
        fl = k.facts()
        # Manual facts sort first
        assert fl[0].manual and fl[1].manual and not fl[2].manual
        # Reloading manual facts replaces, doesn't duplicate
        await k.load_manual_facts(db_path=dbp, knowledge_file=str(kf))
        assert await k.reload_facts(db_path=dbp) == 3
    asyncio.run(run())


def test_page_hash_diff_and_retire(tmp_path):
    import knowledge as k
    dbp = str(tmp_path / "facts.db")

    async def run():
        await k.init_facts_db(dbp)
        await k.replace_page_facts("https://x.com/a", "h1", [("RULE", "a")], db_path=dbp)
        await k.replace_page_facts("https://x.com/b", "h2", [("RULE", "b")], db_path=dbp)
        await k.replace_page_facts("ref-channel", "h3", [("REF", "c")], db_path=dbp)
        assert await k.get_page_hashes(db_path=dbp) == {
            "https://x.com/a": "h1", "https://x.com/b": "h2", "ref-channel": "h3",
        }
        # Page b vanished from the site: retire it. ref-channel must survive.
        gone = await k.retire_pages({"https://x.com/a"}, db_path=dbp)
        assert gone == 1
        await k.reload_facts(db_path=dbp)
        sources = {f.source for f in k.facts()}
        assert sources == {"https://x.com/a", "ref-channel"}
    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_knowledge.py -v`
Expected: ERROR "No module named 'knowledge'"

- [ ] **Step 3: Write the implementation**

```python
# knowledge.py
"""facts.db store: crawled facts + knowledge.txt manual facts (manual always wins)."""
import os
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import aiosqlite

import config
from logging_util import log


@dataclass(frozen=True)
class Fact:
    id: int
    tag: str
    text: str
    source: str
    manual: bool


_facts_cache: list[Fact] = []


def facts() -> list[Fact]:
    """The in-memory fact list (manual facts first). Refreshed by reload_facts()."""
    return _facts_cache


def _path(db_path: str | None) -> str:
    return db_path or config.FACTS_DB_PATH


async def init_facts_db(db_path: str | None = None) -> None:
    async with aiosqlite.connect(_path(db_path)) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                tag        TEXT NOT NULL,
                text       TEXT NOT NULL,
                source     TEXT NOT NULL,
                manual     INTEGER NOT NULL DEFAULT 0,
                first_seen REAL NOT NULL,
                last_seen  REAL NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                url          TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                last_crawled REAL NOT NULL
            )
        """)
        await db.commit()


def parse_fact_line(line: str) -> tuple[str, str] | None:
    """'TAG: fact text' -> (tag, text). Comments/blank/untagged lines -> None."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    m = re.match(r"^([A-Z][A-Z0-9_]*):\s*(.+)$", line)
    if not m:
        return None
    return m.group(1), m.group(2).strip()


async def load_manual_facts(db_path: str | None = None,
                            knowledge_file: str | None = None) -> int:
    """(Re)load knowledge.txt as manual facts. Replaces all previous manual facts."""
    path = knowledge_file or config.KNOWLEDGE_FILE
    parsed: list[tuple[str, str]] = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                p = parse_fact_line(line)
                if p:
                    parsed.append(p)
    now = time.time()
    async with aiosqlite.connect(_path(db_path)) as db:
        await db.execute("DELETE FROM facts WHERE manual = 1")
        for tag, text in parsed:
            await db.execute(
                "INSERT INTO facts (tag, text, source, manual, first_seen, last_seen) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (tag, text, "knowledge.txt", now, now),
            )
        await db.commit()
    log(f"Manual facts loaded — {len(parsed)} from {path}", "ok")
    return len(parsed)


async def replace_page_facts(url: str, content_hash: str,
                             extracted: list[tuple[str, str]],
                             db_path: str | None = None) -> None:
    """Replace all crawled facts for one source page and record its hash."""
    now = time.time()
    async with aiosqlite.connect(_path(db_path)) as db:
        await db.execute("DELETE FROM facts WHERE source = ? AND manual = 0", (url,))
        for tag, text in extracted:
            await db.execute(
                "INSERT INTO facts (tag, text, source, manual, first_seen, last_seen) "
                "VALUES (?, ?, ?, 0, ?, ?)",
                (tag, text, url, now, now),
            )
        await db.execute(
            "INSERT INTO pages (url, content_hash, last_crawled) VALUES (?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET content_hash = excluded.content_hash, "
            "last_crawled = excluded.last_crawled",
            (url, content_hash, now),
        )
        await db.commit()


async def touch_page(url: str, db_path: str | None = None) -> None:
    """Unchanged page: bump crawl timestamps without re-extracting."""
    now = time.time()
    async with aiosqlite.connect(_path(db_path)) as db:
        await db.execute("UPDATE pages SET last_crawled = ? WHERE url = ?", (now, url))
        await db.execute("UPDATE facts SET last_seen = ? WHERE source = ? AND manual = 0", (now, url))
        await db.commit()


async def get_page_hashes(db_path: str | None = None) -> dict[str, str]:
    async with aiosqlite.connect(_path(db_path)) as db:
        async with db.execute("SELECT url, content_hash FROM pages") as cur:
            rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}


async def retire_pages(live_urls: set[str], db_path: str | None = None) -> int:
    """Remove pages (and their facts) that vanished from the site.
    Only http(s) sources are considered — 'ref-channel' and 'knowledge.txt' never retire."""
    async with aiosqlite.connect(_path(db_path)) as db:
        async with db.execute("SELECT url FROM pages WHERE url LIKE 'http%'") as cur:
            known = {r[0] for r in await cur.fetchall()}
        gone = known - live_urls
        for url in gone:
            await db.execute("DELETE FROM facts WHERE source = ? AND manual = 0", (url,))
            await db.execute("DELETE FROM pages WHERE url = ?", (url,))
        await db.commit()
    if gone:
        log(f"Retired {len(gone)} page(s) no longer on the site", "warn")
    return len(gone)


async def reload_facts(db_path: str | None = None) -> int:
    """Refill the in-memory cache. Manual facts first (they take precedence)."""
    global _facts_cache
    async with aiosqlite.connect(_path(db_path)) as db:
        async with db.execute(
            "SELECT id, tag, text, source, manual FROM facts ORDER BY manual DESC, id ASC"
        ) as cur:
            rows = await cur.fetchall()
    _facts_cache = [Fact(r[0], r[1], r[2], r[3], bool(r[4])) for r in rows]
    return len(_facts_cache)


async def last_crawl_time(db_path: str | None = None) -> float | None:
    async with aiosqlite.connect(_path(db_path)) as db:
        async with db.execute("SELECT MAX(last_crawled) FROM pages WHERE url LIKE 'http%'") as cur:
            row = await cur.fetchone()
    return row[0] if row and row[0] else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_knowledge.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add knowledge.py tests/test_knowledge.py
git commit -m "feat: facts.db store with manual-over-crawled precedence and page hashing"
```

---

### Task 4: compute_next_wipe — dates in Python, never the model

**Files:**
- Modify: `knowledge.py` (append function)
- Test: `tests/test_knowledge.py` (append tests)

**Interfaces:**
- Produces: `compute_next_wipe(fact_list: list[Fact], today: date) -> str | None`. Returns a plain-English wipe line (no `WIPE:` prefix) or `None` when not derivable. `bot.py` (Task 9) wraps it in a synthetic `Fact(id=0, tag="WIPE", ...)`.

- [ ] **Step 1: Write the failing tests (append to tests/test_knowledge.py)**

```python
def _f(tag, text):
    import knowledge as k
    return k.Fact(id=1, tag=tag, text=text, source="knowledge.txt", manual=True)


def test_compute_next_wipe_derivable():
    import knowledge as k
    from datetime import date
    fl = [
        _f("WIPE", "All CDN servers wipe approximately every 90 days"),
        _f("WIPE", "Last wipe: 2026-06-14"),
    ]
    line = k.compute_next_wipe(fl, today=date(2026, 7, 22))
    assert "2026-09-12" in line          # 2026-06-14 + 90 days
    assert "90" in line and "2026-06-14" in line


def test_compute_next_wipe_rolls_forward():
    import knowledge as k
    from datetime import date
    fl = [
        _f("WIPE", "wipes every 30 days"),
        _f("WIPE", "last wipe 2026-01-01"),
    ]
    line = k.compute_next_wipe(fl, today=date(2026, 7, 22))
    assert "2026-07-30" in line          # first multiple of 30 days after today


def test_compute_next_wipe_not_derivable():
    import knowledge as k
    from datetime import date
    assert k.compute_next_wipe([_f("WIPE", "wipes happen sometimes")], date(2026, 7, 22)) is None
    assert k.compute_next_wipe([_f("RULE", "no pvp")], date(2026, 7, 22)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_knowledge.py -v -k wipe`
Expected: FAIL with "has no attribute 'compute_next_wipe'"

- [ ] **Step 3: Write the implementation (append to knowledge.py)**

```python
def compute_next_wipe(fact_list: list[Fact], today: date) -> str | None:
    """Compute the next wipe date IN PYTHON from WIPE facts.

    Needs both an interval ('every N days') and an anchor ('last wipe YYYY-MM-DD')
    somewhere in the WIPE facts. Returns a human line, or None when not derivable —
    the model must never do date math itself.
    """
    interval: int | None = None
    last: date | None = None
    for f in fact_list:
        if f.tag != "WIPE":
            continue
        m = re.search(r"every\s*~?\s*(\d+)\s*days", f.text, re.IGNORECASE)
        if m:
            interval = int(m.group(1))
        m = re.search(r"last wipe\D*?(\d{4}-\d{2}-\d{2})", f.text, re.IGNORECASE)
        if m:
            try:
                last = date.fromisoformat(m.group(1))
            except ValueError:
                pass
    if not interval or not last:
        return None
    nxt = last
    while nxt <= today:
        nxt += timedelta(days=interval)
    return (f"The next wipe is approximately {nxt.isoformat()} "
            f"(servers wipe every ~{interval} days; last wipe was {last.isoformat()})")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_knowledge.py -v`
Expected: all pass (6 total)

- [ ] **Step 5: Commit**

```bash
git add knowledge.py tests/test_knowledge.py
git commit -m "feat: compute next wipe date in Python from WIPE facts"
```

---

### Task 5: retrieval.py — local scoring and the silence gate

**Files:**
- Create: `retrieval.py`
- Test: `tests/test_retrieval.py`

**Interfaces:**
- Consumes: `knowledge.Fact`, `config.TOP_FACTS`, `config.RETRIEVAL_MIN_SCORE`.
- Produces:
  - `extract_keywords(text: str) -> tuple[set[str], set[str], set[str]]` → `(base, expanded, hex_codes)`
  - `retrieve(question: str, fact_list: list[Fact], top_n: int = TOP_FACTS) -> list[Fact]` — `[]` means STAY SILENT.
  - `STOP_WORDS`, `KEYWORD_EXPANSIONS` module constants.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_retrieval.py
import knowledge as k
from retrieval import retrieve, extract_keywords

FACTS = [
    k.Fact(1, "RULE", "No building within 1000 metres of any trader", "knowledge.txt", True),
    k.Fact(2, "REP", "Black Market unlocks at 50,000 rep", "knowledge.txt", True),
    k.Fact(3, "DROPS", "Airdrops do NOT contain vehicles", "knowledge.txt", True),
    k.Fact(4, "ERROR", "0x00040010 = ADMIN_KICK — player was removed by an admin", "knowledge.txt", True),
    k.Fact(5, "ERROR", "0x00040093 cause = mod mismatch or corrupted mod files", "knowledge.txt", True),
    k.Fact(6, "JOIN", "Step 2 = download DZSA Launcher for mod management", "knowledge.txt", True),
]


def test_hex_code_exact_match_wins():
    got = retrieve("I got error 0x00040010, what does it mean?", FACTS)
    assert got and got[0].id == 4
    assert all(f.id != 5 for f in got[:1])   # never rank the wrong code first


def test_trader_build_question_finds_rule():
    got = retrieve("how close to a trader can I build my base?", FACTS)
    assert any(f.id == 1 for f in got)


def test_offtopic_is_silent():
    assert retrieve("what's the best pizza topping?", FACTS) == []


def test_smalltalk_is_silent():
    assert retrieve("lol good night everyone", FACTS) == []


def test_expansions_bridge_wording():
    # "blackmarket" (one word) must still reach the Black Market rep fact via expansions
    got = retrieve("what rep do I need for the blackmarket?", FACTS)
    assert any(f.id == 2 for f in got)


def test_short_words_do_not_substring_match():
    base, _, _ = extract_keywords("rep unlock")
    # 'rep' must not match inside 'report' etc. — retrieval uses word tokens
    got = retrieve("rep unlock", FACTS)
    assert any(f.id == 2 for f in got)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_retrieval.py -v`
Expected: ERROR "No module named 'retrieval'"

- [ ] **Step 3: Write the implementation**

```python
# retrieval.py
"""Local fact retrieval. Free, deterministic, and the gate on every API call:
if this module returns nothing, the bot stays silent and spends $0."""
import math
import re

import config
from knowledge import Fact

STOP_WORDS = {
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "do", "i", "my", "me",
    "we", "you", "of", "for", "and", "or", "but", "what", "how", "why", "when",
    "who", "where", "can", "does", "will", "are", "was", "were", "did", "has",
    "have", "had", "that", "this", "with", "from", "be", "been", "being",
    "they", "their", "there", "here", "just", "so", "if", "about", "get", "got",
    "need", "want", "know", "mean", "means",
}

KEYWORD_EXPANSIONS: dict[str, set[str]] = {
    "donate":    {"donation", "donator", "support", "patreon", "contribute", "tier"},
    "trader":    {"market", "shop", "vendor", "trade", "safe zone", "trader zone", "exclusion",
                  "vehicle trader", "aircraft trader", "special trader", "black market", "blackmarket"},
    "wipe":      {"reset", "restart", "wipe schedule", "server reset", "next wipe", "map reset"},
    "base":      {"build", "territory", "flag", "construction", "building", "base building"},
    "ban":       {"banned", "suspend", "appeal", "blacklist", "unban"},
    "error":     {"crash", "problem", "issue", "fix", "troubleshoot", "code"},
    "kick":      {"kicked", "disconnect", "disconnected", "removed"},
    "join":      {"connect", "server ip", "how to play", "get started", "whitelist", "launcher", "dzsa"},
    "whitelist": {"application", "apply", "allowlist", "accepted"},
    "rule":      {"rules", "regulation", "policy", "allowed", "prohibited", "forbidden"},
    "loot":      {"items", "spawn", "economy", "loot table", "gear"},
    "raid":      {"raiding", "base attack", "offline", "breach"},
    "mod":       {"mods", "modded", "modification", "modpack"},
    "drop":      {"drops", "airdrop", "airdrops"},
    "airdrop":   {"drop", "drops", "airdrops"},
    "distance":  {"metres", "meters", "radius", "boundary", "zone", "away", "far", "close"},
    "build":     {"territory", "base", "construction", "flag", "build zone", "building"},
    "rep":       {"reputation", "rep progression", "unlock", "unlocks", "points", "earn rep"},
    "blackmarket": {"black market", "rep", "reputation", "unlocks"},
    "dungeon":   {"permadeath", "permanent death", "dungeon run", "admin teleport", "dungeon rules"},
    "scifi":     {"sci-fi", "sci fi", "banov", "yrtsk", "blackmarket", "special trader", "rainbow bear"},
    "weapon":    {"yrtsk", "tier", "blackmarket", "t1", "t2", "t3", "t4", "t5"},
    "hardcore":  {"hc", "hc server", "territory", "raiding", "permadeath"},
    "vehicle":   {"vehicles", "car", "heli", "aircraft"},
}

_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")


def extract_keywords(text: str) -> tuple[set[str], set[str], set[str]]:
    """Return (base keywords, expanded keywords, hex error codes) for a question."""
    hex_codes = {c.lower() for c in _HEX_RE.findall(text)}
    words = re.split(r"\W+", text.lower())
    base = {w for w in words if len(w) > 2 and w not in STOP_WORDS} - hex_codes
    expanded: set[str] = set()
    for kw in base:
        expanded |= KEYWORD_EXPANSIONS.get(kw, set())
    expanded -= base
    return base, expanded, hex_codes


def _fact_tokens(fact: Fact) -> set[str]:
    return {w for w in re.split(r"\W+", f"{fact.tag} {fact.text}".lower()) if w}


def _matches(kw: str, tokens: set[str], text_lower: str) -> bool:
    # Multi-word expansions match as substrings; single words match whole tokens
    # (so 'rep' never matches inside 'report').
    return (kw in text_lower) if " " in kw else (kw in tokens)


def retrieve(question: str, fact_list: list[Fact],
             top_n: int = config.TOP_FACTS) -> list[Fact]:
    """Score every fact against the question. Empty list == stay silent."""
    if not fact_list:
        return []
    base, expanded, hex_codes = extract_keywords(question)
    all_kw = base | expanded | hex_codes
    if not all_kw:
        return []

    n = len(fact_list)
    token_cache = [(_fact_tokens(f), f.text.lower()) for f in fact_list]

    # Document frequency per keyword (for IDF weighting)
    df: dict[str, int] = {}
    for kw in all_kw:
        df[kw] = sum(1 for toks, tl in token_cache if _matches(kw, toks, tl))

    scored: list[tuple[float, Fact]] = []
    for (toks, tl), fact in zip(token_cache, fact_list):
        score = 0.0
        strong_hits = 0     # hits on base keywords / hex codes (not just expansions)
        for kw in all_kw:
            if not _matches(kw, toks, tl):
                continue
            idf = math.log((n + 1) / (df[kw] + 1)) + 1.0
            if kw in hex_codes:
                idf *= 20.0
            weight = 1.0 if (kw in base or kw in hex_codes) else 0.5
            score += idf * weight
            if kw in base or kw in hex_codes:
                strong_hits += 1
        if score > 0 and strong_hits >= 1:
            scored.append((score, fact))

    if not scored:
        return []
    scored.sort(key=lambda x: (-x[0], not x[1].manual, x[1].id))
    if scored[0][0] < config.RETRIEVAL_MIN_SCORE:
        return []
    return [f for _, f in scored[:top_n]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_retrieval.py -v`
Expected: 6 passed. If `test_offtopic_is_silent` fails because a stray keyword matched, raise `RETRIEVAL_MIN_SCORE` in config (try 1.5) and re-run — the golden offline test in Task 10 is the final arbiter.

- [ ] **Step 5: Commit**

```bash
git add retrieval.py tests/test_retrieval.py
git commit -m "feat: local fact retrieval with expansions, IDF scoring, silence gate"
```

---

### Task 6: answering.py — parsing and citation verification (pure logic)

**Files:**
- Create: `answering.py`
- Test: `tests/test_answering.py`

**Interfaces:**
- Consumes: `knowledge.Fact`, `config`, `db.append_jsonl`.
- Produces:
  - `SYSTEM_PROMPT: str` (frozen constant)
  - `parse_answer(raw: str) -> tuple[str, list[int | str]] | None` — `None` == NO_ANSWER; otherwise `(answer_text_without_facts_line, cited)` where cited entries are ints or the string `"IMG"`.
  - `verify_citations(cited: list, allowed_ids: set[int], has_images: bool) -> bool`
  - `@dataclass Answer(text: str, cited: list, grounded: bool)` (Task 7 fills in the API path)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_answering.py
from answering import parse_answer, verify_citations


def test_no_answer_variants():
    assert parse_answer("NO_ANSWER") is None
    assert parse_answer("  no_answer  ") is None
    assert parse_answer("") is None


def test_parse_answer_with_citations():
    raw = "The Black Market unlocks at **50,000 rep**.\nFACTS: [2]"
    text, cited = parse_answer(raw)
    assert "50,000" in text
    assert "FACTS" not in text
    assert cited == [2]


def test_parse_answer_img_and_multi():
    text, cited = parse_answer("Do X then Y.\nFACTS: [4, IMG]")
    assert cited == [4, "IMG"]


def test_parse_answer_missing_facts_line():
    text, cited = parse_answer("Some confident claim with no citations.")
    assert cited == []          # verify_citations will reject this


def test_verify_citations():
    assert verify_citations([2], {1, 2, 3}, has_images=False) is True
    assert verify_citations([], {1, 2}, has_images=False) is False          # no citations
    assert verify_citations([9], {1, 2}, has_images=False) is False         # unknown id
    assert verify_citations(["IMG"], set(), has_images=True) is True        # screenshot answer
    assert verify_citations(["IMG"], {1}, has_images=False) is False        # IMG without image
    assert verify_citations([1, "IMG"], {1}, has_images=True) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_answering.py -v`
Expected: ERROR "No module named 'answering'"

- [ ] **Step 3: Write the implementation**

```python
# answering.py
"""One Haiku call per answered question. The model must cite fact IDs; citations are
verified deterministically, then an independent grounding check is ENFORCED."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import anthropic

import config
import db
from knowledge import Fact
from logging_util import log

# Frozen — byte-identical on every call. Never interpolate anything into this.
SYSTEM_PROMPT = """You are CDN_Captain, a helper bot inside the CDNDayz DayZ Discord server.

You will be given numbered FACTS and a player's question. Answer ONLY from those facts.

Rules:
- If the facts fully answer the question, give a direct, concise answer using Discord markdown.
- If the facts do not fully answer the question, reply with exactly: NO_ANSWER
- Never guess, never use general DayZ knowledge, never state anything not in the facts.
- Everyone you talk to is already inside this Discord server — never tell anyone to "join the Discord" or "join the server".
- DayZ maps are separate. If the facts are about one map and the question is about another map, reply NO_ANSWER. Never substitute one map's info for another.
- Never reveal the location, entrance, exit, or access route of the Black Market on any map — reply NO_ANSWER if asked, even if a fact seems to describe it.
- Error codes must match exactly. Never answer about a similar but different code.
- If a screenshot is attached, text visible in it counts as a valid source.
- End every answer with one final line listing the fact numbers you used, like:
  FACTS: [3, 7]
  Use IMG in the list if the answer comes from an attached screenshot, e.g. FACTS: [IMG] or FACTS: [4, IMG].
- If you cannot honestly cite at least one fact number (or IMG), reply NO_ANSWER instead."""

_FACTS_LINE_RE = re.compile(r"FACTS:\s*\[([^\]]*)\]\s*$", re.IGNORECASE)


@dataclass
class Answer:
    text: str
    cited: list = field(default_factory=list)
    grounded: bool = True


def parse_answer(raw: str) -> tuple[str, list] | None:
    """None == stay silent. Otherwise (text without the FACTS line, cited ids)."""
    raw = (raw or "").strip()
    if not raw or raw.upper().startswith("NO_ANSWER"):
        return None
    cited: list = []
    text = raw
    m = _FACTS_LINE_RE.search(raw)
    if m:
        text = raw[: m.start()].strip()
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            if part.upper() == "IMG":
                cited.append("IMG")
            elif part.isdigit():
                cited.append(int(part))
    if not text:
        return None
    return text, cited


def verify_citations(cited: list, allowed_ids: set[int], has_images: bool) -> bool:
    """Deterministic check: every citation must be a retrieved fact id, or IMG when
    a screenshot was actually attached. No citations at all -> reject."""
    if not cited:
        return False
    for c in cited:
        if c == "IMG":
            if not has_images:
                return False
        elif c not in allowed_ids:
            return False
    return True


def _log_suppressed(channel_name: str, question: str, answer: str, reason: str) -> None:
    """Every suppression is a knowledge-base gap — log it for the owner to backfill."""
    db.append_jsonl(config.SUPPRESSED_LOG_PATH, {
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel": channel_name,
        "question": (question or "")[:500],
        "answer": (answer or "")[:1000],
        "reason": reason[:300],
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_answering.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add answering.py tests/test_answering.py
git commit -m "feat: answer parsing and deterministic citation verification"
```

---

### Task 7: answering.py — the Haiku call + enforced grounding verifier

**Files:**
- Modify: `answering.py` (append)
- Test: `tests/test_answering.py` (append)

**Interfaces:**
- Consumes: `parse_answer`, `verify_citations`, `_log_suppressed` (Task 6).
- Produces:
  - `generate_answer(client, *, question, facts, context, image_blocks=None, prior=None, channel_name="unknown") -> Answer | None` — the ONLY function bot.py calls to answer. `client` is `anthropic.AsyncAnthropic` (or a fake with `.messages.create`). `facts: list[Fact]`, `context: str`, `image_blocks: list[dict] | None` (Anthropic image content blocks), `prior: dict | None` ({"question","answer"} for follow-ups).
  - `verify_grounded(client, facts_text: str, answer_text: str) -> tuple[bool, str]` — fails OPEN on API errors.

- [ ] **Step 1: Write the failing tests (append to tests/test_answering.py)**

```python
import asyncio
from types import SimpleNamespace

import knowledge as k


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.replies.pop(0))])


class FakeClient:
    def __init__(self, replies):
        self.messages = FakeMessages(replies)


FACTS = [k.Fact(2, "REP", "Black Market unlocks at 50,000 rep", "knowledge.txt", True)]


def test_generate_answer_happy_path(tmp_path, monkeypatch):
    import config, answering
    monkeypatch.setattr(config, "SUPPRESSED_LOG_PATH", str(tmp_path / "s.jsonl"))
    client = FakeClient([
        "It unlocks at **50,000 rep**.\nFACTS: [2]",   # answer call
        "GROUNDED",                                     # verifier call
    ])

    ans = asyncio.run(answering.generate_answer(
        client, question="what rep for black market?", facts=FACTS, context="(none)"))
    assert ans is not None and "50,000" in ans.text and ans.cited == [2] and ans.grounded
    assert len(client.messages.calls) == 2


def test_generate_answer_no_answer(tmp_path):
    import answering
    client = FakeClient(["NO_ANSWER"])
    ans = asyncio.run(answering.generate_answer(
        client, question="namalsk traders?", facts=FACTS, context="(none)"))
    assert ans is None
    assert len(client.messages.calls) == 1   # verifier never runs on silence


def test_generate_answer_bad_citation_suppressed(tmp_path, monkeypatch):
    import config, answering
    sup = tmp_path / "s.jsonl"
    monkeypatch.setattr(config, "SUPPRESSED_LOG_PATH", str(sup))
    client = FakeClient(["Confident nonsense.\nFACTS: [99]"])
    ans = asyncio.run(answering.generate_answer(
        client, question="q?", facts=FACTS, context="(none)"))
    assert ans is None
    assert "citation" in sup.read_text()


def test_generate_answer_ungrounded_suppressed(tmp_path, monkeypatch):
    import config, answering
    sup = tmp_path / "s.jsonl"
    monkeypatch.setattr(config, "SUPPRESSED_LOG_PATH", str(sup))
    client = FakeClient([
        "The Black Market is behind the red barn.\nFACTS: [2]",
        "UNGROUNDED: location claim not in sources",
    ])
    ans = asyncio.run(answering.generate_answer(
        client, question="where is bm?", facts=FACTS, context="(none)"))
    assert ans is None                       # ENFORCED, not shadow
    assert "UNGROUNDED" in sup.read_text()


def test_verifier_fails_open_on_error():
    import answering

    class BoomMessages:
        async def create(self, **kw):
            raise RuntimeError("api down")

    client = SimpleNamespace(messages=BoomMessages())
    grounded, verdict = asyncio.run(answering.verify_grounded(client, "facts", "answer"))
    assert grounded is True and "verifier-error" in verdict
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_answering.py -v`
Expected: new tests FAIL with "has no attribute 'generate_answer'"

- [ ] **Step 3: Write the implementation (append to answering.py)**

```python
_VERIFIER_SYSTEM = (
    "You are a strict grounding verifier for a support bot. You are given SOURCES "
    "and a proposed ANSWER. Decide whether EVERY specific, checkable claim in the "
    "ANSWER is directly supported by the SOURCES.\n"
    "Ignore greetings, tone, and formatting. A claim is UNGROUNDED if it states a "
    "concrete fact (number, distance, rule, item, location, cause, fix, date, name) "
    "that does not appear in the SOURCES.\n"
    "Reply on ONE line: 'GROUNDED' if all claims are supported, otherwise "
    "'UNGROUNDED: <short reason naming the unsupported claim>'."
)


async def verify_grounded(client, facts_text: str, answer_text: str) -> tuple[bool, str]:
    """Independent check that the answer only states what the facts state.
    Fails OPEN on API errors so an outage can never silence a legitimate answer."""
    try:
        resp = await client.messages.create(
            model=config.ANSWER_MODEL,
            max_tokens=120,
            system=_VERIFIER_SYSTEM,
            messages=[{"role": "user", "content":
                       f"SOURCES:\n{facts_text[:12000]}\n\n---\nANSWER:\n{answer_text[:2000]}"}],
        )
        verdict = resp.content[0].text.strip()
        return verdict.upper().startswith("GROUNDED"), verdict
    except Exception as exc:
        return True, f"verifier-error: {exc}"


async def generate_answer(client, *, question: str, facts: list[Fact], context: str,
                          image_blocks: list | None = None, prior: dict | None = None,
                          channel_name: str = "unknown") -> Answer | None:
    """The single answer path. Returns None to stay silent (all results by value —
    never stash state on function attributes)."""
    numbered = "\n".join(f"[{f.id}] {f.tag}: {f.text}" for f in facts) or "(no facts)"

    parts = [f"FACTS:\n{numbered}\n"]
    if prior:
        parts.append("This is a follow-up to your previous answer.\n"
                     f"Previous question: {prior['question']}\n"
                     f"Your previous answer: {prior['answer']}\n")
    parts.append(f"Recent conversation in #{channel_name} (newest last):\n{context}\n")
    parts.append(f"Player's question: \"{question or '(screenshot only)'}\"")
    user_text = "\n".join(parts)

    if image_blocks:
        content: list | str = [*image_blocks, {"type": "text", "text": user_text}]
    else:
        content = user_text

    try:
        resp = await client.messages.create(
            model=config.ANSWER_MODEL,
            max_tokens=config.ANSWER_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:
        log(f"Couldn't reach Claude: {exc}", "error")
        return None

    parsed = parse_answer(resp.content[0].text)
    if parsed is None:
        log("Stayed silent — model returned NO_ANSWER", "skip")
        return None
    text, cited = parsed

    if not verify_citations(cited, {f.id for f in facts}, bool(image_blocks)):
        log("Suppressed — citation check failed", "warn")
        _log_suppressed(channel_name, question, text, "citation-check-failed")
        return None

    # Grounding is ENFORCED. Screenshot-based answers (IMG cited) skip it because the
    # verifier cannot see the image — the citation check already bound them to a real image.
    grounded = True
    if "IMG" not in cited:
        grounded, verdict = await verify_grounded(client, numbered, text)
        if not grounded:
            log(f"Suppressed — grounding check failed: {verdict[:100]}", "warn")
            _log_suppressed(channel_name, question, text, verdict)
            return None

    return Answer(text=text, cited=cited, grounded=grounded)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_answering.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add answering.py tests/test_answering.py
git commit -m "feat: Haiku answer call with enforced citation + grounding gates"
```

---

### Task 8: crawler.py — crawl, hash-diff, extraction, ingest

**Files:**
- Create: `crawler.py`
- Test: `tests/test_crawler.py`

**Interfaces:**
- Consumes: `knowledge` (replace_page_facts, touch_page, get_page_hashes, retire_pages, reload_facts, parse_fact_line), `config`, `logging_util.log`.
- Produces:
  - `page_hash(text: str) -> str` (sync, sha256 hex)
  - `extract_facts_from_text(client, source: str, text: str) -> list[tuple[str, str]]` (async; batches long text)
  - `crawl_site() -> dict[str, str]` (async; Playwright BFS, url -> visible text)
  - `fetch_reference_text(bot) -> str` (async; reads the reference channel)
  - `run_ingest(client, bot=None, db_path=None) -> str` (async; full pipeline, returns summary line)
  - `ingest_loop(client, bot)` (async; weekly background task)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_crawler.py
import asyncio
from types import SimpleNamespace


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.replies.pop(0))])


class FakeClient:
    def __init__(self, replies):
        self.messages = FakeMessages(replies)


def test_page_hash_stable():
    from crawler import page_hash
    assert page_hash("abc") == page_hash("abc")
    assert page_hash("abc") != page_hash("abd")


def test_extract_facts_parses_tagged_lines():
    from crawler import extract_facts_from_text
    client = FakeClient(["RULE: No PvP on standard servers\nnot a fact line\nREP: Vehicle Trader unlocks at 10,000 rep"])
    got = asyncio.run(extract_facts_from_text(client, "https://x.com/rules", "page text"))
    assert got == [("RULE", "No PvP on standard servers"),
                   ("REP", "Vehicle Trader unlocks at 10,000 rep")]


def test_run_ingest_only_extracts_changed_pages(tmp_path, monkeypatch):
    import crawler, knowledge as k

    dbp = str(tmp_path / "facts.db")

    async def fake_crawl():
        return {"https://x.com/a": "content A", "https://x.com/b": "content B"}

    monkeypatch.setattr(crawler, "crawl_site", fake_crawl)

    async def run():
        await k.init_facts_db(dbp)
        c1 = FakeClient(["RULE: rule from A", "RULE: rule from B"])
        await crawler.run_ingest(c1, bot=None, db_path=dbp)
        assert len(c1.messages.calls) == 2          # both pages new -> both extracted
        await k.reload_facts(db_path=dbp)
        assert len(k.facts()) == 2

        # Second ingest, nothing changed -> zero API calls
        c2 = FakeClient([])
        await crawler.run_ingest(c2, bot=None, db_path=dbp)
        assert len(c2.messages.calls) == 0

        # Page A changes -> exactly one extraction call
        async def fake_crawl2():
            return {"https://x.com/a": "content A v2", "https://x.com/b": "content B"}
        monkeypatch.setattr(crawler, "crawl_site", fake_crawl2)
        c3 = FakeClient(["RULE: new rule from A"])
        await crawler.run_ingest(c3, bot=None, db_path=dbp)
        assert len(c3.messages.calls) == 1
    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_crawler.py -v`
Expected: ERROR "No module named 'crawler'"

- [ ] **Step 3: Write the implementation**

```python
# crawler.py
"""Weekly site ingest: Playwright crawl -> per-page hash diff -> Haiku extraction of
CHANGED pages only -> facts.db. Also ingests the Discord reference channel."""
import asyncio
import hashlib
import re
from urllib.parse import urljoin, urldefrag, urlparse

from bs4 import BeautifulSoup

import config
import knowledge
from logging_util import log

_EXTRACTION_PROMPT = """\
You are extracting structured facts from the CDNDayz DayZ server website.
Read ALL of the content below and extract EVERY concrete fact.

CRITICAL RULES — follow these exactly:
- Extract EVERY fact, rule, number, policy, distance, cause, fix, and server-specific detail
- MAXIMUM GRANULARITY: each individual cause, fix, step, or sub-detail gets its own line
- Do NOT summarise — reproduce the actual content
- Do NOT add commentary, blank lines, or explanations
- Every output line MUST start with a TAG: prefix (ALL-CAPS tag, invent one if needed)

Existing tags — use these when they apply:
  RULE WIPE ERROR DONATION SERVER_IP SCIFI REP DUNGEON TRADER BASE EVENT FAQ JOIN MOD
  POPULATION LOOT ZONE PRIVACY TERMS

Format examples (this is the REQUIRED granularity):
RULE: No building within 1000 metres of any trader
WIPE: All CDN servers wipe approximately every 90 days
WIPE: Last wipe: 2026-06-14
ERROR: 0x00040010 = ADMIN_KICK — player was removed by a server administrator
ERROR: 0x00040010 fix = if a restart was announced, wait and reconnect
REP: Black Market unlocks at 50,000 rep
FAQ: Q: Is PvP allowed? A: Not on standard servers. HC servers allow territory PvP

Only output facts. No explanations. No blank lines. No markdown.

Content:
"""

_CHUNK_CHARS = 24000   # per extraction call; pages larger than this are chunked


def page_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def extract_facts_from_text(client, source: str, text: str) -> list[tuple[str, str]]:
    """Run Haiku extraction over (possibly chunked) page text. Returns (tag, text) pairs."""
    facts: list[tuple[str, str]] = []
    seen: set[str] = set()
    chunks = [text[i:i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)] or [""]
    for chunk in chunks:
        try:
            resp = await client.messages.create(
                model=config.ANSWER_MODEL,
                max_tokens=8192,
                messages=[{"role": "user", "content": _EXTRACTION_PROMPT + f"[{source}]\n{chunk}"}],
            )
        except Exception as exc:
            log(f"Extraction failed for {source}: {exc}", "warn")
            continue
        for line in resp.content[0].text.splitlines():
            parsed = knowledge.parse_fact_line(line)
            if parsed and line.strip() not in seen:
                seen.add(line.strip())
                facts.append(parsed)
    return facts


# ── Playwright crawl ─────────────────────────────────────────────────────────
def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "noscript", "iframe", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def _normalise_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc == "cdndayz.com":
        url = parsed._replace(netloc="www.cdndayz.com").geturl()
    return url.rstrip("/")


def _discover_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_netloc = urlparse(config.CDN_WEBSITE).netloc.removeprefix("www.")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full, _ = urldefrag(urljoin(base_url, href))
        p = urlparse(full)
        if p.netloc.removeprefix("www.") == base_netloc and p.scheme in ("http", "https"):
            links.append(_normalise_url(full))
    return links


async def _fetch_page(browser, url: str) -> tuple[str, str, str]:
    """Fetch one page with JS rendering; click through sibling <button> tab bars so
    conditionally-rendered content is captured. Returns (url, html, all_text)."""
    page = None
    try:
        page = await browser.new_page()
        await page.set_extra_http_headers({"User-Agent": "CDN-Captain-Bot/2.0"})
        await page.goto(url, wait_until="networkidle", timeout=20000)
        html = await page.content()
        parts = [_extract_text(html)]
        tab_groups = await page.evaluate("""() => {
            const groups = new Map();
            for (const btn of document.querySelectorAll('button')) {
                const p = btn.parentElement;
                if (!p) continue;
                if (!groups.has(p)) groups.set(p, []);
                groups.get(p).push(btn);
            }
            const out = [];
            for (const [, btns] of groups) {
                const named = btns.filter(b => b.innerText.trim().length > 0);
                if (named.length >= 2 && named.length <= 6) out.push(named.map(b => b.innerText.trim()));
            }
            return out;
        }""")
        for group in tab_groups:
            for name in group[1:]:
                try:
                    await page.get_by_role("button", name=name, exact=True).click()
                    await page.wait_for_timeout(900)
                    t = _extract_text(await page.content())
                    if t and t not in parts:
                        parts.append(t)
                except Exception:
                    pass
        return url, html, "\n\n--- (tab) ---\n\n".join(parts)
    except Exception as exc:
        log(f"Could not load page: {url} ({exc})", "warn")
        return url, "", ""
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def crawl_site() -> dict[str, str]:
    """BFS crawl of cdndayz.com with headless Chromium. Returns url -> visible text."""
    from playwright.async_api import async_playwright

    log("Crawling cdndayz.com (renders JavaScript)...", "crawl")
    visited: set[str] = set()
    queue = [_normalise_url(config.CDN_WEBSITE)]
    result: dict[str, str] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            while queue and len(visited) < config.MAX_PAGES_TO_CRAWL:
                batch = []
                while queue and len(batch) < config.CRAWL_CONCURRENCY:
                    u = queue.pop(0)
                    if u not in visited:
                        visited.add(u)
                        batch.append(u)
                if not batch:
                    break
                for url, html, text in await asyncio.gather(*[_fetch_page(browser, u) for u in batch]):
                    if not html:
                        continue
                    if text:
                        result[url] = text
                    for link in _discover_links(html, url):
                        if link not in visited and link not in queue:
                            queue.append(link)
        finally:
            await browser.close()
    log(f"Crawl done — {len(result)} pages", "ok")
    return result


async def fetch_reference_text(bot) -> str:
    """Read the reference channel's messages as one text blob (ingest source, not a prompt dump)."""
    if bot is None:
        return ""
    channel = bot.get_channel(config.REFERENCE_CHANNEL_ID)
    if channel is None:
        log(f"Cannot find the reference channel (ID: {config.REFERENCE_CHANNEL_ID})", "warn")
        return ""
    lines = []
    try:
        async for msg in channel.history(limit=config.REFERENCE_CHANNEL_MSG_LIMIT, oldest_first=True):
            if msg.content.strip():
                lines.append(msg.content.strip())
    except Exception as exc:
        log(f"Could not read reference channel: {exc}", "warn")
        return ""
    return "\n".join(lines)


async def run_ingest(client, bot=None, db_path: str | None = None) -> str:
    """Full ingest: crawl -> diff hashes -> extract changed pages only -> retire gone
    pages -> ingest reference channel -> reload the fact cache. Returns a summary."""
    pages = await crawl_site()
    old_hashes = await knowledge.get_page_hashes(db_path=db_path)
    changed = unchanged = 0
    for url, text in pages.items():
        h = page_hash(text)
        if old_hashes.get(url) == h:
            await knowledge.touch_page(url, db_path=db_path)
            unchanged += 1
            continue
        extracted = await extract_facts_from_text(client, url, text)
        await knowledge.replace_page_facts(url, h, extracted, db_path=db_path)
        changed += 1
    retired = 0
    if pages:  # a failed/empty crawl must never wipe the KB
        retired = await knowledge.retire_pages(set(pages.keys()), db_path=db_path)

    ref_text = await fetch_reference_text(bot)
    if ref_text and old_hashes.get("ref-channel") != page_hash(ref_text):
        extracted = await extract_facts_from_text(client, "ref-channel", ref_text)
        await knowledge.replace_page_facts("ref-channel", page_hash(ref_text), extracted, db_path=db_path)

    total = await knowledge.reload_facts(db_path=db_path)
    summary = (f"Ingest done — {changed} page(s) re-extracted, {unchanged} unchanged, "
               f"{retired} retired, {total} facts loaded")
    log(summary, "ok")
    return summary


async def ingest_loop(client, bot) -> None:
    """Background task: re-ingest every CRAWL_INTERVAL_SECONDS."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(config.CRAWL_INTERVAL_SECONDS)
        try:
            await run_ingest(client, bot)
        except Exception as exc:
            log(f"Scheduled ingest failed: {exc}", "error")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_crawler.py -v`
Expected: 3 passed (no Playwright launched — `crawl_site` is monkeypatched)

- [ ] **Step 5: Commit**

```bash
git add crawler.py tests/test_crawler.py
git commit -m "feat: weekly ingest — crawl, hash-diff, changed-page extraction, ref channel"
```

---

### Task 9: bot.py — Discord wiring

**Files:**
- Create: `bot.py`
- Test: import/compile smoke check only (Discord objects aren't unit-testable without heavy mocking; logic already covered in Tasks 2–8)

**Interfaces:**
- Consumes: everything above. Entry point: `python bot.py`.

- [ ] **Step 1: Write the implementation**

```python
# bot.py
"""CDN_Captain v2 — Discord wiring only. All logic lives in the other modules."""
import asyncio
import base64
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

import aiohttp
import anthropic
import discord
from discord.ext import commands

import answering
import config
import crawler
import db
import knowledge
import retrieval
from logging_util import log

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="!cdn ", intents=intents, help_command=None)
client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

_bot_paused = False
_bot_start_time = time.time()
user_last_answered: dict[int, float] = defaultdict(float)

PAUSE_PHRASES = {"shutdown", "stop responding", "go silent", "pause", "don't respond",
                 "stop answering", "ignore everyone", "go quiet", "shut up", "shut down"}
RESUME_PHRASES = {"resume", "come back", "start responding", "wake up", "unpause",
                  "you can respond", "go back", "start answering", "turn on"}

_ADMIN_TAG_OPENER = ("Hey there! 👋 Please don't ping the admins — they won't respond to "
                     "direct tags and it clutters their notifications.")
_ADMIN_TAG_CLOSERS = [
    "Thanks for keeping the server tidy! 😊",
    "Appreciate you — the server runs smoother when we keep it organised! 🙌",
    "Cheers for understanding! The admins appreciate it. ✌️",
    "You're a legend for asking the right way. 🫡",
    "Thanks for being a good sport about it! 😄",
]

QUESTION_STARTERS = {"who", "what", "when", "where", "why", "how", "can", "could", "would",
                     "should", "is", "are", "was", "were", "does", "do", "did", "will",
                     "has", "have", "had"}

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
EXT_TO_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp"}


# ── Helpers ──────────────────────────────────────────────────────────────────
def _footer() -> str:
    return f"\n-# Engineered by [Morningstar.0](<{config.PORTFOLIO_URL}>)"


def build_admin_tag_response(message: discord.Message) -> str:
    guild = message.guild
    rules_ch = guild.get_channel(config.REFERENCE_CHANNEL_ID) if guild else None
    ticket_ch = guild.get_channel(config.TICKET_CHANNEL_ID) if guild else None
    rules = f"<#{rules_ch.id}>" if rules_ch else "the rules channel"
    ticket = f"<#{ticket_ch.id}>" if ticket_ch else "the ticket channel"
    return (f"{_ADMIN_TAG_OPENER}\n\n"
            f"🌐 **Check the website first** — **https://cdndayz.com** has the rules, FAQs, and info!\n"
            f"📋 **Server rules & info** are also in {rules}\n"
            f"💬 **Still have a question?** Ask it here — a community member or I might help!\n"
            f"🎫 **Need staff support?** Open a ticket in {ticket}\n"
            f"🚫 **Please don't DM the admins either** — tickets are the best way to reach them.\n\n"
            f"{random.choice(_ADMIN_TAG_CLOSERS)}{_footer()}")


def mentions_admin(message: discord.Message) -> bool:
    reply_author_id = None
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message):
            reply_author_id = ref.author.id
    for user in message.mentions:
        if user.id == reply_author_id:
            continue  # Discord auto-inserts the replied-to author as a mention
        if user.name.lower() in config.PROTECTED_ADMINS or user.display_name.lower() in config.PROTECTED_ADMINS:
            return True
    cl = message.content.lower()
    for admin in config.PROTECTED_ADMINS:
        if f"@{admin}" in cl:
            if reply_author_id is not None and message.guild:
                replied = message.guild.get_member(reply_author_id)
                if replied and (replied.name.lower() == admin or replied.display_name.lower() == admin):
                    continue
            return True
    return False


def is_admin_author(message: discord.Message) -> bool:
    a = message.author
    if isinstance(a, discord.Member) and a.guild_permissions.administrator:
        return True
    return a.name.lower() in config.PROTECTED_ADMINS or a.display_name.lower() in config.PROTECTED_ADMINS


def is_question(content: str) -> bool:
    content = content.strip()
    if len(content) < 8:
        return False
    if "?" in content:
        return True
    first = re.split(r"\W+", content)[0].lower()
    if first in QUESTION_STARTERS:
        return True
    if re.search(r"\b(error|crash|kick|ban|wipe|trader|base|build|loot|mod|dungeon|rep|"
                 r"whitelist|donat|server|dayz|0x[0-9a-fA-F]+)\w*\b", content, re.IGNORECASE):
        return len(content.split()) >= 4
    return False


def is_directed_at_someone(message: discord.Message) -> bool:
    if message.reference:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and not ref.author.bot:
            return True
        if ref is None and message.reference.message_id:
            humans = [u for u in message.mentions
                      if not u.bot and (bot.user is None or u.id != bot.user.id)]
            if humans:
                return True
    return False


def is_two_person_convo(recent: list[discord.Message]) -> bool:
    now = time.time()
    active = [m for m in recent if not m.author.bot
              and (now - m.created_at.timestamp()) <= 120][-10:]
    if len(active) < 4:
        return False
    counts = Counter(m.author.id for m in active)
    top_two = [aid for aid, _ in counts.most_common(2)]
    if len(top_two) < 2:
        return False
    ids = [m.author.id for m in active if m.author.id in top_two]
    return sum(1 for i in range(1, len(ids)) if ids[i] != ids[i - 1]) >= 3


def build_context(msgs: list[discord.Message], exclude_id: int) -> str:
    now = time.time()
    lines = []
    for m in msgs:
        if m.author.bot or m.id == exclude_id:
            continue
        age = int(now - m.created_at.timestamp())
        ts = f"{age}s ago" if age < 60 else (f"{age // 60}m ago" if age < 3600 else f"{age // 3600}h ago")
        lines.append(f"[{ts}] {m.author.display_name}: {m.content}")
    return "\n".join(lines) if lines else "(no recent context)"


def get_image_attachments(message: discord.Message) -> list:
    images = []
    for att in message.attachments:
        ct = (att.content_type or "").lower().split(";")[0].strip()
        ext = os.path.splitext(att.filename.lower())[1]
        if ct in SUPPORTED_IMAGE_TYPES or ext in EXT_TO_MEDIA:
            images.append(att)
    return images


async def download_image_blocks(attachments: list) -> list[dict]:
    blocks = []
    async with aiohttp.ClientSession() as session:
        for att in attachments:
            try:
                async with session.get(att.url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        continue
                    ct = (resp.headers.get("Content-Type", "image/png")).lower().split(";")[0].strip()
                    media = ct if ct in SUPPORTED_IMAGE_TYPES else "image/png"
                    data = base64.standard_b64encode(await resp.read()).decode()
                    blocks.append({"type": "image",
                                   "source": {"type": "base64", "media_type": media, "data": data}})
            except Exception as exc:
                log(f"Could not download a screenshot: {exc}", "warn")
    return blocks


async def is_recently_answered(channel_id: int, question: str) -> bool:
    prev = await db.recent_questions(channel_id, time.time() - config.ANSWER_DEDUP_TTL)
    q_kw, _, _ = retrieval.extract_keywords(question)
    if not q_kw:
        return False
    for p in prev:
        p_kw, _, _ = retrieval.extract_keywords(p)
        if p_kw and len(q_kw & p_kw) / max(len(q_kw | p_kw), 1) > 0.7:
            return True
    return False


async def notify_owner(text: str) -> None:
    try:
        owner = bot.get_user(config.SIDEKICK_USER_ID) or await bot.fetch_user(config.SIDEKICK_USER_ID)
        if owner:
            await owner.send(text)
    except Exception as exc:
        log(f"Could not DM owner alert: {exc}", "warn")


async def send_with_retry(coro_fn, max_retries: int = 3) -> discord.Message:
    for attempt in range(1, max_retries + 1):
        try:
            return await coro_fn()
        except discord.errors.HTTPException as exc:
            if exc.status == 429 and attempt < max_retries:
                wait = getattr(exc, "retry_after", None) or (2 ** attempt)
                log(f"Discord rate limit — waiting {wait:.1f}s (attempt {attempt})", "warn")
                await asyncio.sleep(wait)
            else:
                raise
    raise RuntimeError("Max retries exceeded")


def facts_with_wipe() -> list[knowledge.Fact]:
    """The fact list plus a synthetic, Python-computed next-wipe fact (id=0) when derivable."""
    fl = list(knowledge.facts())
    wipe = knowledge.compute_next_wipe(fl, date.today())
    if wipe:
        fl.append(knowledge.Fact(0, "WIPE", wipe, "computed", True))
    return fl


# ── Sidekick (owner) mode ────────────────────────────────────────────────────
def is_sidekick_trigger(message: discord.Message) -> bool:
    if message.author.id != config.SIDEKICK_USER_ID:
        return False
    if bot.user and bot.user in message.mentions:
        return True
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and ref.author == bot.user:
            return True
    return message.content.strip().lower().startswith("cdn")


async def sidekick_answer(message: discord.Message, context: str) -> str | None:
    content = message.content
    if bot.user:
        content = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
    fact_text = "\n".join(f"{f.tag}: {f.text}" for f in facts_with_wipe())
    system = (f"You are CDN_Captain, the personal AI sidekick of the owner of the CDNDayz "
              f"DayZ community. You are talking directly to your owner. Be direct, helpful, "
              f"and conversational.\n\nServer knowledge:\n{fact_text}\n\n"
              f"Recent channel context:\n{context}")
    try:
        resp = await client.messages.create(
            model=config.ANSWER_MODEL, max_tokens=1000, system=system,
            messages=[{"role": "user", "content": content or "(no text)"}])
        return resp.content[0].text.strip()
    except Exception as exc:
        log(f"Sidekick error: {exc}", "error")
        return None


# ── Events ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global _bot_paused
    print()
    log(f"CDN_Captain {config.CURRENT_VERSION} — logged in as {bot.user}", "ok")
    await db.init_db()
    await knowledge.init_facts_db()
    _bot_paused = await db.get_paused()
    if _bot_paused:
        log("Bot is PAUSED — silent until resumed", "warn")
    await knowledge.load_manual_facts()
    total = await knowledge.reload_facts()
    last = await knowledge.last_crawl_time()
    log(f"Knowledge ready — {total} facts loaded "
        f"(last crawl: {'never' if not last else datetime.fromtimestamp(last).strftime('%Y-%m-%d')})", "ok")

    if last is None or (time.time() - last) > config.CRAWL_INTERVAL_SECONDS:
        log("Fact DB empty or stale — starting ingest in the background", "crawl")
        asyncio.create_task(_startup_ingest())
    asyncio.create_task(crawler.ingest_loop(client, bot))
    asyncio.create_task(_kb_health_loop())
    log("Online and listening — answers only when facts support it", "ok")


async def _startup_ingest():
    try:
        await crawler.run_ingest(client, bot)
    except Exception as exc:
        log(f"Startup ingest failed: {exc}", "error")


async def _kb_health_loop():
    alerted = False
    while not bot.is_closed():
        await asyncio.sleep(1800)
        n = len(knowledge.facts())
        last = await knowledge.last_crawl_time()
        stale = last is not None and (time.time() - last) > config.CRAWL_STALE_ALERT_SECONDS
        if n == 0 or stale:
            log(f"KB health problem — {n} facts, stale={stale}", "error")
            if not alerted:
                await notify_owner("⚠️ CDN_Captain knowledge base problem: "
                                   f"{n} facts loaded, crawl stale={stale}. "
                                   "Check knowledge.txt or run `!cdn crawl`.")
                alerted = True
        else:
            alerted = False


@bot.event
async def on_message(message: discord.Message):
    global _bot_paused
    if message.author.bot:
        return
    if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
        return
    parent_id = getattr(getattr(message.channel, "parent", None), "id", None)
    if message.channel.id in config.IGNORED_CHANNEL_IDS or parent_id in config.IGNORED_CHANNEL_IDS:
        return

    await bot.process_commands(message)

    if mentions_admin(message) and not is_admin_author(message):
        try:
            await message.reply(build_admin_tag_response(message), mention_author=True)
        except discord.HTTPException:
            pass
        return

    content = message.content.strip()
    channel_name = getattr(message.channel, "name", "unknown")
    images = get_image_attachments(message)
    log(f"#{channel_name} · {message.author.display_name}: \"{content[:55]}\""
        f"{f' +{len(images)} image(s)' if images else ''}", "msg")

    # Sidekick / pause control
    if is_sidekick_trigger(message):
        low = content.lower()
        if any(p in low for p in PAUSE_PHRASES):
            _bot_paused = True
            await db.set_paused(True)
            await message.reply("Going quiet now. Ping me when you want me back.", mention_author=True)
            return
        if any(p in low for p in RESUME_PHRASES):
            _bot_paused = False
            await db.set_paused(False)
            await message.reply("Back on watch.", mention_author=True)
            return
        ctx = await _channel_context(message)
        ans = await sidekick_answer(message, ctx)
        if ans:
            await send_with_retry(lambda: message.reply(ans, mention_author=True))
        return

    if _bot_paused:
        return

    # ── Free pre-checks ──────────────────────────────────────────────────────
    if (time.time() - message.created_at.timestamp()) > config.MAX_MESSAGE_AGE_SECONDS:
        return
    if not images:
        if not content or not is_question(content):
            return
        if is_directed_at_someone(message):
            return
    if time.time() - user_last_answered[message.author.id] < config.USER_COOLDOWN_SECONDS:
        return
    if not images and await is_recently_answered(message.channel.id, content):
        log("Stayed silent — similar question answered here recently", "skip")
        return

    recent = await _recent_messages(message)
    if is_two_person_convo(recent) and not images:
        log("Stayed silent — two players mid-conversation", "skip")
        return

    # ── Local retrieval gate: no facts, no API call, no cost ─────────────────
    fact_list = facts_with_wipe()
    retrieved = retrieval.retrieve(content or "error screenshot help", fact_list)
    if not retrieved and not images:
        log("Stayed silent — no matching facts (0 API calls)", "skip")
        return

    image_blocks = await download_image_blocks(images) if images else None
    if images and not image_blocks:
        log("All screenshot downloads failed — skipping", "warn")
        return

    # Follow-up replay guard: only replay grounded, not-marked-wrong answers
    prior = None
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and ref.author == bot.user:
            candidate = await db.get_by_message_id(ref.id)
            if db.is_replayable(candidate):
                prior = candidate

    answer = await answering.generate_answer(
        client,
        question=content,
        facts=retrieved,
        context=build_context(recent, exclude_id=message.id),
        image_blocks=image_blocks,
        prior=prior,
        channel_name=channel_name,
    )
    if answer is None:
        return

    user_last_answered[message.author.id] = time.time()
    try:
        sent = await send_with_retry(lambda: message.reply(answer.text + _footer(), mention_author=True))
        for emoji in (config.FEEDBACK_UP_EMOJI, config.FEEDBACK_DOWN_EMOJI):
            try:
                await sent.add_reaction(emoji)
            except discord.HTTPException:
                pass
        await db.log_answer(
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id, channel_name=channel_name,
            author_id=message.author.id, author_name=message.author.display_name,
            question=content, answer=answer.text,
            grounded=int(answer.grounded), message_id=sent.id,
        )
        log(f"Replied ({len(answer.text.split())} words, cited {answer.cited})", "ok")
    except discord.HTTPException as exc:
        log(f"Couldn't send reply: {exc}", "error")


async def _recent_messages(message: discord.Message) -> list[discord.Message]:
    out: list[discord.Message] = []
    try:
        async for m in message.channel.history(limit=config.CONTEXT_MESSAGE_LIMIT + 3):
            if m.id != message.id:
                out.append(m)
            if len(out) >= config.CONTEXT_MESSAGE_LIMIT:
                break
    except Exception as exc:
        log(f"Could not read channel history: {exc}", "warn")
    out.reverse()
    return out


async def _channel_context(message: discord.Message) -> str:
    return build_context(await _recent_messages(message), exclude_id=message.id)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    emoji = str(payload.emoji)
    if bot.user and payload.user_id == bot.user.id:
        return
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return

    if emoji in (config.FEEDBACK_UP_EMOJI, config.FEEDBACK_DOWN_EMOJI):
        rec = await db.get_by_message_id(payload.message_id)
        if rec is None:
            return
        vote = 1 if emoji == config.FEEDBACK_UP_EMOJI else -1
        up, down = await db.record_feedback_vote(payload.message_id, payload.user_id, vote)
        if vote < 0:
            log(f"Answer downvoted ({down}👎/{up}👍) — \"{rec['question'][:60]}\"", "warn")
            if down == config.FEEDBACK_DOWNVOTE_ALERT_THRESHOLD:
                db.append_jsonl(config.FLAGGED_LOG_PATH, {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "question": rec["question"][:500], "answer": rec["answer"][:1000],
                    "downvotes": down, "upvotes": up,
                })
                await notify_owner(f"⚠️ An answer reached {down} 👎 and may be wrong:\n"
                                   f"Q: {rec['question'][:200]}\nReview knowledge.txt.")
        return

    if emoji not in ("✅", "❌"):
        return
    is_admin = (member.name.lower() in config.PROTECTED_ADMINS
                or member.display_name.lower() in config.PROTECTED_ADMINS
                or member.guild_permissions.administrator)
    if not is_admin:
        return
    question = await db.mark_feedback(payload.message_id, correct=(emoji == "✅"))
    if question is None:
        return
    log(f"Answer {'confirmed' if emoji == '✅' else 'marked wrong'} by {member.display_name}", "ok")
    if emoji == "❌":
        try:
            channel = guild.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                await msg.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


# ── Commands (admin/owner only) ──────────────────────────────────────────────
def _is_admin_ctx(ctx: commands.Context) -> bool:
    if ctx.author.id == config.SIDEKICK_USER_ID:
        return True
    return isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    raise error


@bot.command(name="help")
@commands.check(_is_admin_ctx)
async def cdn_help(ctx):
    embed = discord.Embed(
        title=f"👋 {config.BOT_NAME} {config.CURRENT_VERSION}",
        description=("I read every channel and only answer when my local fact database "
                     "supports an answer. No facts = silence (and $0 spent)."),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Commands",
                    value="`!cdn help` · `!cdn ask <q>` · `!cdn facts` · `!cdn crawl` · "
                          "`!cdn status` · `!cdn history`", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="ask")
@commands.check(_is_admin_ctx)
async def cdn_ask(ctx, *, question: str):
    retrieved = retrieval.retrieve(question, facts_with_wipe())
    if not retrieved:
        await ctx.reply("No facts in my database match that question.", mention_author=True)
        return
    ans = await answering.generate_answer(
        client, question=question, facts=retrieved,
        context="(direct command)", channel_name=getattr(ctx.channel, "name", "unknown"))
    await ctx.reply(ans.text if ans else "My facts don't fully answer that.", mention_author=True)


@bot.command(name="facts")
@commands.check(_is_admin_ctx)
async def cdn_facts(ctx):
    import io
    fl = knowledge.facts()
    if not fl:
        await ctx.reply("No facts loaded. Try `!cdn crawl`.", mention_author=True)
        return
    body = "\n".join(f"[{f.id}]{'*' if f.manual else ''} {f.tag}: {f.text}  ({f.source})" for f in fl)
    buf = io.BytesIO(f"CDN_Captain facts — {len(fl)} total (* = manual)\n\n{body}".encode())
    await ctx.reply(f"📋 **{len(fl)} facts** loaded:", file=discord.File(buf, "cdn_facts.txt"),
                    mention_author=True)


@bot.command(name="crawl")
@commands.check(_is_admin_ctx)
async def cdn_crawl(ctx):
    msg = await ctx.send("🔍 Ingesting cdndayz.com — this takes a minute...")
    try:
        summary = await crawler.run_ingest(client, bot)
        await msg.edit(content=f"✅ {summary}")
    except Exception as exc:
        await msg.edit(content=f"❌ Ingest failed: {exc}")


@bot.command(name="status")
@commands.check(_is_admin_ctx)
async def cdn_status(ctx):
    n = len(knowledge.facts())
    manual = sum(1 for f in knowledge.facts() if f.manual)
    last = await knowledge.last_crawl_time()
    crawl_str = ("never" if not last
                 else f"{int((time.time() - last) / 3600)}h ago")
    up = int(time.time() - _bot_start_time)
    embed = discord.Embed(title=f"📊 {config.BOT_NAME} Status",
                          color=discord.Color.green() if n else discord.Color.red())
    embed.add_field(name="Facts", value=f"{n} loaded ({manual} manual)", inline=True)
    embed.add_field(name="Last crawl", value=crawl_str, inline=True)
    embed.add_field(name="Uptime", value=f"{up // 3600}h {(up % 3600) // 60}m", inline=True)
    embed.add_field(name="Model", value=config.ANSWER_MODEL, inline=False)
    embed.add_field(name="Paused", value=str(_bot_paused), inline=True)
    await ctx.send(embed=embed)


@bot.command(name="history")
@commands.check(_is_admin_ctx)
async def cdn_history(ctx):
    records = await db.recent_history(ctx.channel.id, limit=10)
    if not records:
        await ctx.send("No answers logged for this channel yet.")
        return
    lines = []
    for r in records:
        age = int(time.time() - r["timestamp"])
        ts = f"{age // 60}m ago" if age < 3600 else f"{age // 3600}h ago"
        fb = " ✅" if r["correct"] == 1 else (" ❌" if r["correct"] == 0 else "")
        lines.append(f"**[{ts}]** {r['author']}: *{r['question'][:80]}*{fb}")
    await ctx.send(embed=discord.Embed(title=f"📜 Recent answers in #{ctx.channel.name}",
                                       description="\n".join(lines),
                                       color=discord.Color.blurple()))


if __name__ == "__main__":
    problems = config.validate_config()
    if problems:
        log("Cannot start — fix these configuration problems:", "error")
        for p in problems:
            log(f"  • {p}", "error")
        sys.exit(1)
    bot.run(config.DISCORD_TOKEN)
```

- [ ] **Step 2: Smoke check — compile and import without network**

Run: `python -m py_compile bot.py && python -c "import bot; print('import ok')"`
Expected: `import ok` (importing must not connect to Discord — the `bot.run` call is guarded by `__main__`)

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add bot.py
git commit -m "feat: v2 Discord wiring — retrieval-gated answering, feedback, commands"
```

---

### Task 10: Golden-question harness

**Files:**
- Create: `tests/test_golden_offline.py`, `tests/run_golden_live.py`
- Test: itself

**Interfaces:**
- Consumes: `tests/golden_questions.jsonl` (existing — fields: id, question, expect ("answer"/"silent"), must_contain_any, must_not_contain), `knowledge.parse_fact_line`, `retrieval.retrieve`.

- [ ] **Step 1: Write the offline test**

The offline harness checks the **retrieval layer** against the real `knowledge.txt`:
- Cases with `expect: "answer"` must retrieve at least one fact (except `admin-ping`, which is handled by the admin-tag path, not retrieval).
- Pure-offtopic silent cases must retrieve nothing. Silent cases that legitimately retrieve related facts (`black-market-location`, `wipe-date-unknown`, `map-scope`, `hallucination-bait`) are enforced at the model layer — the live harness covers those.

```python
# tests/test_golden_offline.py
import json
import pathlib

import knowledge as k
from retrieval import retrieve

GOLDEN = pathlib.Path(__file__).parent / "golden_questions.jsonl"
KNOWLEDGE = pathlib.Path(__file__).parent.parent / "knowledge.txt"

# Handled by a non-retrieval path, or enforced at the model layer (live harness):
RETRIEVAL_EXEMPT = {"admin-ping", "black-market-location", "wipe-date-unknown",
                    "map-scope", "hallucination-bait"}


def _load_manual_facts() -> list[k.Fact]:
    facts = []
    i = 0
    for line in KNOWLEDGE.read_text(encoding="utf-8").splitlines():
        parsed = k.parse_fact_line(line)
        if parsed:
            i += 1
            facts.append(k.Fact(i, parsed[0], parsed[1], "knowledge.txt", True))
    return facts


def _cases():
    return [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_answer_cases_retrieve_facts():
    facts = _load_manual_facts()
    misses = []
    for case in _cases():
        if case["expect"] != "answer" or case["id"] in RETRIEVAL_EXEMPT:
            continue
        if not retrieve(case["question"], facts):
            misses.append(case["id"])
    assert not misses, f"Golden 'answer' cases retrieved zero facts: {misses}"


def test_offtopic_cases_stay_silent():
    facts = _load_manual_facts()
    leaks = []
    for case in _cases():
        if case["expect"] != "silent" or case["id"] in RETRIEVAL_EXEMPT:
            continue
        got = retrieve(case["question"], facts)
        if got:
            leaks.append((case["id"], [f.id for f in got]))
    assert not leaks, f"Golden 'silent' cases retrieved facts: {leaks}"
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_golden_offline.py -v`
Expected: 2 passed. If an "answer" case misses, add the missing expansion keyword to `KEYWORD_EXPANSIONS` in `retrieval.py` (do NOT lower `RETRIEVAL_MIN_SCORE` below 1.0). If a "silent" case leaks, that's acceptable ONLY if the model layer catches it — move the id to `RETRIEVAL_EXEMPT` and note it.

- [ ] **Step 3: Write the live harness (manual, costs API tokens, env-gated)**

```python
# tests/run_golden_live.py
"""Manual live harness: runs every golden question through the REAL pipeline
(retrieval + Haiku answer + citations + grounding). Costs API tokens.

Usage:  RUN_GOLDEN_LIVE=1 python tests/run_golden_live.py
"""
import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import anthropic  # noqa: E402

import answering  # noqa: E402
import config  # noqa: E402
import knowledge as k  # noqa: E402
from retrieval import retrieve  # noqa: E402
from test_golden_offline import _load_manual_facts, _cases  # noqa: E402


async def main():
    if os.getenv("RUN_GOLDEN_LIVE") != "1":
        print("Set RUN_GOLDEN_LIVE=1 to run (this costs API tokens).")
        return
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    facts = _load_manual_facts()
    passed = failed = 0
    for case in _cases():
        if case["id"] == "admin-ping":
            continue  # handled by the admin-tag path, not the answer pipeline
        retrieved = retrieve(case["question"], facts)
        ans = None
        if retrieved:
            ans = await answering.generate_answer(
                client, question=case["question"], facts=retrieved, context="(golden test)")
        text = (ans.text.lower() if ans else "")
        ok = True
        if case["expect"] == "silent" and ans is not None:
            ok = False
        if case["expect"] == "answer":
            if ans is None:
                ok = False
            elif case["must_contain_any"] and not any(s.lower() in text for s in case["must_contain_any"]):
                ok = False
        if any(s.lower() in text for s in case["must_not_contain"]):
            ok = False
        print(f"{'PASS' if ok else 'FAIL'}  {case['id']}: "
              f"{'(silent)' if ans is None else text[:80]}")
        passed += ok
        failed += (not ok)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run full suite + commit**

Run: `python -m pytest tests/ -v`
Expected: all pass

```bash
git add tests/test_golden_offline.py tests/run_golden_live.py
git commit -m "test: golden-question harness — offline retrieval + live pipeline runner"
```

---

### Task 11: Dockerfile, deployment docs, README

**Files:**
- Modify: `Dockerfile`
- Create: `README.md`

- [ ] **Step 1: Update the Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium + system deps for the weekly Playwright crawl
RUN playwright install --with-deps chromium

COPY config.py logging_util.py db.py knowledge.py retrieval.py answering.py crawler.py bot.py knowledge.txt ./

ENV PYTHONUNBUFFERED=1

# facts.db / memory.db / *.jsonl live in /data (mount a volume there)
ENV FACTS_DB_PATH=/data/facts.db \
    MEMORY_DB_PATH=/data/memory.db \
    SUPPRESSED_LOG_PATH=/data/suppressed_answers.jsonl \
    FLAGGED_LOG_PATH=/data/flagged_answers.jsonl
VOLUME /data

CMD ["python", "bot.py"]
```

- [ ] **Step 2: Write README.md**

```markdown
# CDN_Captain v2

Retrieval-first Discord helper bot for the CDNDayz community.

## How it works
1. **Weekly ingest:** crawls cdndayz.com (Playwright), extracts facts with Claude
   Haiku from *changed pages only*, stores them in `facts.db`. Your hand-written
   `knowledge.txt` always overrides crawled facts.
2. **Free retrieval gate:** every message is scored locally against the fact DB.
   No matching facts → the bot stays silent and spends $0.
3. **One small answer call:** Haiku 4.5 answers from the matched facts only and must
   cite fact IDs. Citations are verified in code; an independent grounding check is
   enforced. Anything unverifiable is suppressed and logged to
   `suppressed_answers.jsonl` as a knowledge gap to backfill.

## Run locally
    pip install -r requirements.txt
    playwright install chromium
    cp .env.example .env   # fill in DISCORD_TOKEN + ANTHROPIC_API_KEY
    python bot.py

## Run on TrueNAS (Docker)
    docker build -t cdn-captain .
    docker run -d --name cdn-captain \
      --env-file .env \
      -v /mnt/pool/cdn-captain:/data \
      --restart unless-stopped \
      cdn-captain

First boot with an empty `/data` triggers a full site ingest (~a minute, well under
$1 of API credit), then it refreshes weekly. `!cdn crawl` forces a refresh.

## Commands (admin/owner)
`!cdn help` · `!cdn ask <q>` · `!cdn facts` · `!cdn crawl` · `!cdn status` · `!cdn history`

## Feedback loop
- Anyone: 👍/👎 on an answer. 3× 👎 alerts the owner and logs the answer.
- Admins: ✅ confirms an answer, ❌ marks it wrong **and deletes it**.
- `suppressed_answers.jsonl` + `flagged_answers.jsonl` = your TODO list for
  `knowledge.txt` additions.

## Tests
    python -m pytest tests/ -v                       # offline, free
    RUN_GOLDEN_LIVE=1 python tests/run_golden_live.py  # live pipeline, costs tokens
```

- [ ] **Step 3: Build check (optional if Docker available locally)**

Run: `docker build -t cdn-captain . 2>&1 | tail -5`
Expected: `naming to docker.io/library/cdn-captain` (skip on machines without Docker; TrueNAS build is the real target)

- [ ] **Step 4: Final full test run + commit**

Run: `python -m pytest tests/ -v && python -m py_compile bot.py config.py db.py knowledge.py retrieval.py answering.py crawler.py logging_util.py`
Expected: all tests pass, no compile errors

```bash
git add Dockerfile README.md
git commit -m "feat: v2 Dockerfile with /data volume + README"
```
