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
