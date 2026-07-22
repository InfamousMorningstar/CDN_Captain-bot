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
