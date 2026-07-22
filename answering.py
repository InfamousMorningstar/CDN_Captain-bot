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
        raw = resp.content[0].text if resp.content else ""
    except Exception as exc:
        log(f"Couldn't reach Claude: {exc}", "error")
        return None

    parsed = parse_answer(raw)
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
