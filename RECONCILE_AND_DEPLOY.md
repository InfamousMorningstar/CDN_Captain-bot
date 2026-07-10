# CDN_Captain — Reconcile & Deploy (Cowork → server)

The Cowork copy and the **live server** copy (`/mnt/app-pool/cdn-captain/bot.py`,
image `cdn-captain`, container bind-mounts the dir to `/app`) are two parallel
branches of `v1.5.7`. They must be **merged selectively**, not overwritten — the
server independently evolved a few things. This file lists exactly what to apply,
what to skip, and how to ship it.

Deploy mechanism: the server runs `watchdog.py`, which auto-updates `bot.py` from
**GitHub releases**. So the clean path is: apply the changes below in a checkout,
bump the version, push, cut a `v1.5.8` release. The watchdog pulls it (hourly) — or,
once it's on GitHub, run `git -C /app pull && docker restart cdn-captain` on the NAS.

---

## Already on the server — SKIP these

- **Knowledge-file loader fix.** The server's `load_knowledge_file()` already strips
  `#` comments and treats a fact-less file as empty (its own compact form). Do **not**
  port our loader edit — it's redundant and would conflict.
- **Drops/airdrop facts.** Already appended to the server's `knowledge.txt` and live
  (4 `AIRDROP:` lines). Nothing to do.

## Apply cleanly (region matches the server) 

- **P0-2 security fix — sidekick ID-only.** Server still has the spoofable fallback at
  ~lines 1850-1853. Replace:
  ```python
      is_owner = (message.author.id == SIDEKICK_USER_ID and SIDEKICK_USER_ID != 0)
      if not is_owner:
          is_owner = (
              message.author.name.lower() == SIDEKICK_USERNAME or
              message.author.display_name.lower() == SIDEKICK_USERNAME
          )
      if not is_owner:
          return False
  ```
  with:
  ```python
      # Identity is verified ONLY by Discord user ID (unfakeable). A username/
      # display-name fallback was removed: those are user-settable and let anyone
      # impersonate the owner into the unguarded sidekick model.
      if SIDEKICK_USER_ID == 0 or message.author.id != SIDEKICK_USER_ID:
          return False
  ```
  Then delete the now-unused `SIDEKICK_USERNAME = ...` constant (~line 132).

---

## New features to add (server has none of these)

Order below is safe to apply top-to-bottom. Anchors reference the server's `bot.py`.

### 1. Imports
Near the top imports add:
```python
import sys
import json
```

### 2. Config constants (after `AI_CHEAP_MODEL = ...`)
```python
# Grounding gate: independent verifier re-checks answers against sources. SHADOW by
# default (logs would-suppress, changes nothing); set GROUNDING_GATE_ENFORCE=1 to enforce.
GROUNDING_GATE_ENFORCE = os.getenv("GROUNDING_GATE_ENFORCE", "0").strip().lower() in {"1","true","yes","on"}
SUPPRESSED_LOG_PATH    = os.getenv("SUPPRESSED_LOG_PATH", "suppressed_answers.jsonl")

# Community answer feedback (👍/👎). Votes recorded once per user; enough 👎 flags the
# answer + DMs the owner. Community votes never auto-delete; only admin ❌ deletes.
FEEDBACK_UP_EMOJI   = "👍"
FEEDBACK_DOWN_EMOJI = "👎"
FEEDBACK_DOWNVOTE_ALERT_THRESHOLD = int(os.getenv("FEEDBACK_DOWNVOTE_ALERT_THRESHOLD", "3"))
FLAGGED_LOG_PATH    = os.getenv("FLAGGED_LOG_PATH", "flagged_answers.jsonl")
```
Near `KNOWLEDGE_FILE = ...`:
```python
# Optional structured log file (plain, timestamped, level-tagged, secret-redacted).
LOG_FILE = os.getenv("LOG_FILE", "")
```
Near the other numeric constants:
```python
KB_HEALTH_CHECK_INTERVAL = 1800  # re-check knowledge-base health every 30 min (seconds)
```

### 3. Secret redaction — replace `_log`
```python
def _redact(text: str) -> str:
    """Strip known secrets from any string before it reaches a log/console."""
    for secret in (DISCORD_TOKEN, ANTHROPIC_API_KEY):
        if secret and secret in text:
            text = text.replace(secret, "***redacted***")
    return text


def _log(msg: str, level: str = "info") -> None:
    """Console log (secrets redacted). If LOG_FILE is set, also append a structured record."""
    msg = _redact(msg)
    icon_char, icon_col, text_col = _LEVEL.get(level, ("·", _GRY, _WHT))
    ts = f"{_GRY}{_ts()}{_RST}"
    print(f"  {ts}  {icon_col}{icon_char}{_RST}  {text_col}{msg}{_RST}")
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as _f:
                _f.write(f"{datetime.now(timezone.utc).isoformat()} [{level.upper():<5}] {msg}\n")
        except Exception:
            pass
```

### 4. KB health helpers (after the crawl globals `_using_knowledge_file = False`)
```python
def kb_fact_count() -> int:
    if not _structured_knowledge:
        return 0
    return sum(1 for line in _structured_knowledge.splitlines() if line.strip())

def kb_source_label() -> str:
    return f"static file ({KNOWLEDGE_FILE})" if _using_knowledge_file else "live crawl (cdndayz.com)"

def kb_health_line() -> str:
    return f"source={kb_source_label()} · {kb_fact_count()} facts · {len(_page_store)} page(s)"
```

### 5. Crawl file-mode guard (top of `crawl_site`, before `async with _crawl_lock`)
```python
    # In static knowledge-file mode the file IS the whole KB — never crawl. Without
    # this, the per-message crawl_site() call launches a full browser crawl and
    # overwrites the knowledge-file content (because _crawl_done_time stays 0).
    if _using_knowledge_file:
        return
```

### 6. DB: feedback table, grounded column, migration (in `init_db`)
After the `bot_state` table create:
```python
        await db.execute("""
            CREATE TABLE IF NOT EXISTS answer_feedback (
                message_id INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                vote       INTEGER NOT NULL,      -- +1 = 👍, -1 = 👎
                timestamp  REAL    NOT NULL,
                PRIMARY KEY (message_id, user_id)
            )
        """)
```
Add `grounded INTEGER DEFAULT NULL` to the `qa_log` CREATE, and after the commit:
```python
        try:
            await db.execute("ALTER TABLE qa_log ADD COLUMN grounded INTEGER DEFAULT NULL")
            await db.commit()
        except Exception:
            pass  # column already exists
```

### 7. DB helpers
`db_log_answer`: add param `grounded: int | None = None`, add `grounded` to the INSERT
column list and values.

`db_record_feedback_vote` (new):
```python
async def db_record_feedback_vote(message_id: int, user_id: int, vote: int) -> tuple[int, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO answer_feedback (message_id, user_id, vote, timestamp) VALUES (?,?,?,?) "
            "ON CONFLICT(message_id, user_id) DO UPDATE SET vote=excluded.vote, timestamp=excluded.timestamp",
            (message_id, user_id, vote, time.time()),
        )
        await db.commit()
        async with db.execute(
            "SELECT COALESCE(SUM(CASE WHEN vote>0 THEN 1 ELSE 0 END),0), "
            "COALESCE(SUM(CASE WHEN vote<0 THEN 1 ELSE 0 END),0) FROM answer_feedback WHERE message_id=?",
            (message_id,),
        ) as cur:
            row = await cur.fetchone()
    return (row[0] or 0, row[1] or 0)
```
`db_get_by_message_id`: add `grounded, marked_correct` to the SELECT and returned dict.

`_is_replayable` (new): only replay a prior answer as follow-up context if grounded and
not admin-marked-wrong:
```python
def _is_replayable(prior: dict | None) -> bool:
    if not prior:
        return False
    if prior.get("grounded") == 0:
        return False
    if prior.get("marked_correct") == 0:
        return False
    return True
```

### 8. JSONL log helpers (near the other module helpers)
```python
def _append_jsonl(path: str, record: dict) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        _log(f"Could not write log file {path}:  {exc}", "warn")

def _log_suppressed_answer(channel_name, question, answer, verdict, enforced) -> None:
    _append_jsonl(SUPPRESSED_LOG_PATH, {"ts": datetime.now(timezone.utc).isoformat(),
        "channel": channel_name, "question": (question or "")[:500],
        "answer": (answer or "")[:1000], "verdict": verdict[:300], "enforced": enforced})

def _log_flagged_answer(question, answer, downvotes, upvotes) -> None:
    _append_jsonl(FLAGGED_LOG_PATH, {"ts": datetime.now(timezone.utc).isoformat(),
        "question": (question or "")[:500], "answer": (answer or "")[:1000],
        "downvotes": downvotes, "upvotes": upvotes})
```

### 9. Verifier (immediately before `async def evaluate_and_answer`)
```python
async def _verify_answer_grounded(question: str, answer: str, sources_text: str) -> tuple[bool, str]:
    """Independent grounding check: a SEPARATE model call sees only sources+answer and
    judges whether every claim is supported. Fails OPEN on verifier error."""
    if not sources_text.strip():
        return True, "no-sources-skip"
    system = (
        "You are a strict grounding verifier for a support bot. You are given SOURCES and a "
        "proposed ANSWER. Decide whether EVERY specific, checkable claim in the ANSWER is directly "
        "supported by the SOURCES.\nIgnore greetings, tone, formatting. A claim is UNGROUNDED if it "
        "states a concrete fact (number, distance, rule, item, location, cause, fix, date, name) not "
        "in the SOURCES.\nReply on ONE line: 'GROUNDED' if all claims are supported, else "
        "'UNGROUNDED: <short reason>'."
    )
    user = f"SOURCES:\n{sources_text[:12000]}\n\n---\nANSWER:\n{answer[:2000]}"
    try:
        resp = await _claude_create(model=AI_CHEAP_MODEL, max_tokens=120, temperature=0,
                                    system=system, messages=[{"role":"user","content":user}])
        verdict = resp.content[0].text.strip()
        return verdict.upper().startswith("GROUNDED"), verdict
    except Exception as exc:
        return True, f"verifier-error: {exc}"
```

### 10. Gate wiring (in `evaluate_and_answer`, right before it returns the final answer,
where it sets `_last_confidence`)
```python
        sources_for_check = "\n".join(s for s in (_structured_knowledge, _wipe_info, website_content, ref_content) if s)
        grounded, verdict = await _verify_answer_grounded(message.content, answer, sources_for_check)
        if not grounded:
            enforce = GROUNDING_GATE_ENFORCE and not force
            _log_suppressed_answer(channel_name, message.content, answer, verdict, enforce)
            if enforce:
                _log(f"Grounding gate suppressed an ungrounded answer — {verdict[:120]}", "warn")
                return None
            _log(f"[shadow] Grounding gate would suppress — {verdict[:120]}", "skip")
        evaluate_and_answer._last_grounded = int(grounded)
```
(Keep the existing `evaluate_and_answer._last_confidence = confidence; return answer`.)

### 11. Owner alert + health watchdog (near `_update_check_loop`)
```python
async def _notify_owner(text: str) -> None:
    if SIDEKICK_USER_ID == 0:
        return
    try:
        owner = bot.get_user(SIDEKICK_USER_ID) or await bot.fetch_user(SIDEKICK_USER_ID)
        if owner:
            await owner.send(text)
    except Exception as exc:
        _log(f"Could not DM owner alert:  {exc}", "warn")

async def _kb_health_loop():
    await asyncio.sleep(KB_HEALTH_CHECK_INTERVAL)
    alerted = False
    while True:
        if kb_fact_count() == 0:
            _log("Knowledge base is EMPTY at runtime — bot is effectively mute", "error")
            if not alerted:
                await _notify_owner("⚠️ CDN_Captain has 0 knowledge-base facts and cannot answer. Check knowledge.txt or run !cdn crawl.")
                alerted = True
        else:
            alerted = False
        await asyncio.sleep(KB_HEALTH_CHECK_INTERVAL)
```

### 12. Startup health signal (in `on_ready`, after `fetch_reference_channel()`)
```python
    if kb_fact_count() == 0:
        _log("KNOWLEDGE BASE IS EMPTY — 0 facts loaded. The bot cannot answer anything.", "error")
        await _notify_owner("⚠️ CDN_Captain started with 0 knowledge-base facts. Check knowledge.txt or run !cdn crawl.")
    else:
        _log(f"Knowledge base ready — {kb_health_line()}", "ok")
    bot.loop.create_task(_kb_health_loop())
```

### 13. Status command (`!cdn ping`/health embed)
Compute `facts = kb_fact_count()`, colour the embed red when `facts == 0`, and show a
"Knowledge Base" field = `f"{facts} facts · {kb_source_label()}"` (or `⚠️ 0 facts — bot is MUTE`).
Make the crawl field say "n/a — static knowledge-file mode" when `_using_knowledge_file`.

### 14. Feedback reactions (in `_send_answer`, after the reply is sent)
```python
    for _emoji in (FEEDBACK_UP_EMOJI, FEEDBACK_DOWN_EMOJI):
        try:
            await sent.add_reaction(_emoji)
        except discord.HTTPException:
            pass
```

### 15. Reaction handler (`on_raw_reaction_add`) — add a community branch
At the top: ignore the bot's own reactions (`if bot.user and payload.user_id == bot.user.id: return`),
then handle 👍/👎 as signal-only (record vote via `db_record_feedback_vote`; on hitting
`FEEDBACK_DOWNVOTE_ALERT_THRESHOLD` downvotes, `_log_flagged_answer` + `_notify_owner`; never
delete), and keep the existing admin ✅/❌ path below it. (Full code in the Cowork `bot.py`.)

### 16. Log-site + follow-up gating (in `on_message`)
- At the reply-to-bot lookup: `if not _is_replayable(prior_bot_answer): prior_bot_answer = None`.
- At `db_log_answer(...)`: also pass `grounded=getattr(evaluate_and_answer, "_last_grounded", None)`.

### 17. Fail-fast config validation (before `bot.run` in `__main__`)
```python
def _validate_config() -> list[str]:
    problems = []
    if not DISCORD_TOKEN: problems.append("DISCORD_TOKEN is not set")
    if not ANTHROPIC_API_KEY: problems.append("ANTHROPIC_API_KEY is not set")
    if not isinstance(SIDEKICK_USER_ID, int) or SIDEKICK_USER_ID < 0: problems.append("SIDEKICK_USER_ID must be a non-negative int")
    if not AI_MAIN_MODEL or not AI_CHEAP_MODEL: problems.append("model names must not be empty")
    if FEEDBACK_DOWNVOTE_ALERT_THRESHOLD < 1: problems.append("FEEDBACK_DOWNVOTE_ALERT_THRESHOLD must be >= 1")
    return problems
```
```python
if __name__ == "__main__":
    _p = _validate_config()
    if _p:
        _log("Cannot start — configuration problems:", "error")
        for _x in _p: _log(f"    • {_x}", "error")
        sys.exit(1)
    bot.run(DISCORD_TOKEN)
```

---

## New files to add to the repo
- `tests/golden_questions.jsonl` — 15 behavioral cases (incl. `drops-not-vehicles`).
- `tests/check_knowledge_invariants.py` — no-API CI gate over `knowledge.txt`.
- `tests/README.md` — how to run both test layers.
- `.claude/agents/discord-bot-engineer.md` — reusable engineering subagent.
- `IMPROVEMENT_PLAN.md` — the roadmap (P0/P1/P2, all ✅ except this deploy).

(All of these are already in the Cowork folder — copy them into the checkout as-is.)

---

## Ship it
1. In a git checkout of `InfamousMorningstar/CDN_Captain-bot`, create branch `v1.5.8`.
2. Apply the items above; add the new files.
3. Verify: `python -m py_compile bot.py` and `python tests/check_knowledge_invariants.py` (must pass).
4. Bump `CURRENT_VERSION = "v1.5.8"`.
5. Commit, push, cut a `v1.5.8` GitHub release.
6. The server's `watchdog.py` auto-pulls within the hour — or on the NAS run
   `git -C /mnt/app-pool/cdn-captain pull && docker restart cdn-captain`, then check
   `docker logs cdn-captain --tail 20` for "Logged in" + the fact count.
7. After a few days of shadow-gate logs (`suppressed_answers.jsonl`), set
   `GROUNDING_GATE_ENFORCE=1` to enforce.

Backups already on the server: `bot.py.bak-predeploy-20260710-090559`,
`knowledge.txt.bak-predeploy-20260710-090559`.
