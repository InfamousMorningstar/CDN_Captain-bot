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
