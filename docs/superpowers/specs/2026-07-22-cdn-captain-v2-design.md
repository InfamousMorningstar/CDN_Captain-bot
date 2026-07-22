# CDN_Captain v2 — Retrieval-First Redesign

**Date:** 2026-07-22
**Status:** Approved by owner (design review in chat)
**Goal:** Stop the bot from fabricating answers, cut Anthropic API spend ~10x, and make the
knowledge pipeline self-refreshing from cdndayz.com. Budget context: ~$110 of API credit
should last a year-plus of normal traffic.

---

## 1. Problem statement

CDN_Captain v1.5.8 answers unsolicited questions in every channel, but:

1. **It fabricates.** Anti-hallucination is prompt-only: a self-graded CONFIDENCE score,
   a regex deflection blacklist that runs *after* the paid model call, and a grounding
   verifier that ships in shadow mode (`GROUNDING_GATE_ENFORCE` unset) — i.e. it logs bad
   answers and sends them anyway.
2. **It re-sends everything, every time.** The answer prompt stuffs the entire knowledge
   base (up to three copies of the same file in knowledge-file mode), the raw reference
   channel (120 messages), a site index, and a channel list — 8–20K uncached input tokens
   per question across three API calls (Haiku gate + Sonnet answer + Haiku verifier).
3. **Stale wipe dates.** `wipe_info` (a "next wipe" date *calculated by a model* on some
   earlier date) is cached in memory.db, reloaded on startup, never invalidated in
   knowledge-file mode, and injected as "always use this for wipe questions."
4. **Concurrency bug.** Per-answer results are passed via function attributes
   (`evaluate_and_answer._last_confidence` / `._last_grounded`); concurrent messages
   clobber each other, corrupting the DB log and the follow-up replay guard.
5. **Monolith.** ~3,000-line bot.py with ~15 module-level globals.

Root cause framing: the bot is designed to try hard to answer with a tiny knowledge base
(~50 facts) and maximum answering surface. Accuracy problems are as much a *data* problem
as a model problem.

## 2. Design decisions (owner-confirmed)

- **Posture:** stays proactive — reads the conversation and answers unsolicited *when it
  knows*, silent otherwise. No @mention requirement (owner explicitly doesn't want users
  tagging the bot and burning tokens).
- **Knowledge source:** weekly crawl of cdndayz.com → local fact database on the TrueNAS
  host. First boot with an empty DB triggers a full crawl.
- **Answer model:** Haiku 4.5 (`claude-haiku-4-5-20251001`) for all runtime calls.
- **Silence is free:** if local retrieval finds nothing, zero API calls are made.

## 3. Architecture

Five modules replace the monolith (behavior-preserving split plus the new pipeline):

| Module | Responsibility |
|---|---|
| `bot.py` | Discord wiring only: events, commands, admin-tag protection, feedback reactions, pause/sidekick. |
| `crawler.py` | Playwright crawl of cdndayz.com; per-page text extraction + content hash; Haiku fact extraction for **changed pages only**; reference-channel ingestion; writes `facts.db`. |
| `knowledge.py` | Fact store (SQLite `facts.db` on a Docker volume). Loads crawled facts + `knowledge.txt` manual facts (manual overrides crawled). Wipe-schedule computation in Python. KB health checks. |
| `retrieval.py` | Local scoring (keywords + semantic expansions, BM25-style TF-IDF) over individual facts. Returns top-N facts above a threshold, or nothing. |
| `answering.py` | Single Haiku answer call, citation verification, enforced grounding verifier, suppression logging. |

### 3.1 Fact database (`facts.db`, SQLite)

```
facts(
  id INTEGER PRIMARY KEY,
  tag TEXT,            -- RULE, ERROR, REP, SCIFI, DUNGEON, FAQ, WIPE, REF, ...
  text TEXT,           -- one concrete fact
  source TEXT,         -- URL, 'knowledge.txt', or 'ref-channel'
  page_hash TEXT,      -- hash of the source page at extraction time (crawled facts)
  first_seen REAL, last_seen REAL,
  manual INTEGER DEFAULT 0   -- 1 = from knowledge.txt; wins over crawled facts
)
pages(url TEXT PRIMARY KEY, content_hash TEXT, last_crawled REAL)
```

- Weekly job (and on-boot if DB empty or older than 7 days): crawl → for each page,
  compare `content_hash`; unchanged pages keep their facts (`last_seen` bumped); changed
  or new pages go to Haiku extraction (existing extraction prompt, kept); facts from
  pages that disappeared are retired.
- `knowledge.txt` keeps its current format and is re-read on startup/restart. Manual
  facts are loaded with `manual=1`. When a manual fact and a crawled fact conflict on
  the same topic, retrieval prefers manual facts (they sort first at equal score).
- Reference channel: fetched weekly, converted to facts by the same extraction prompt,
  tagged `REF`. It is no longer injected raw into prompts.

### 3.2 Message flow (per Discord message)

1. **Free local pre-checks** (unchanged from v1): bot/channel mutes, admin-tag
   protection, message age, min length, `is_question`, directed-at-someone,
   per-user cooldown, per-channel dedup, two-person-conversation guard.
2. **Local retrieval** (`retrieval.py`): score every fact against the message (plus
   short reply-chain context). Nothing above threshold → **stay silent, $0**.
   This fully replaces the v1 Haiku classifier gate.
3. **Answer call** (`answering.py`): one Haiku 4.5 call.
   - System prompt: short frozen rules block (identity, no-invention rules, formatting,
     channel-mention rules) — static, byte-identical across calls.
   - User content: numbered retrieved facts (5–20), compact recent-conversation context,
     the question, images if attached (screenshot text remains a valid source).
   - Required output: either exactly `NO_ANSWER`, or the answer followed by a final line
     `FACTS: [<ids>]`.
4. **Citation check (deterministic, free):** every cited ID must be in the retrieved
   set; an answer with no `FACTS:` line, unknown IDs, or an empty citation list is
   suppressed. Screenshot-only answers may cite `FACTS: [IMG]`.
5. **Grounding verifier (enforced):** the existing independent Haiku check, but
   `grounded == False` now *suppresses* (no shadow mode). Verifier sees only the
   retrieved facts (+ note that screenshots were present) and the answer. Fails open on
   API errors, as today. Every suppression logs to `suppressed_answers.jsonl` as a KB gap.
6. **Send + log:** reply with the existing footer and 👍/👎 seeding; log Q/A/citations/
   grounded verdict to `qa_log`. Results are **returned** from the answer function
   (dataclass), not stashed on function attributes — fixes the race.

### 3.3 Wipe schedule

- The model never does date math. Facts store schedule *rules* (e.g. "wipes every ~90
  days", "last wipe: 2026-06-14"). `knowledge.py` computes "next wipe" in Python at
  question time and injects the computed line as a synthetic fact only when derivable.
- The `wipe_info` DB cache and `parse_wipe_schedule()` model call are deleted.

### 3.4 What is deleted from v1

- Haiku classifier gate (`should_attempt_answer`) — replaced by local retrieval.
- Self-graded `CONFIDENCE:X` protocol and its parsing.
- The `_DEFLECTION_PATTERNS` regex blacklist — replaced by citations + enforced verifier.
  (A minimal 2–3 pattern safety strainer may remain for known-bad phrasings.)
- Site index, raw reference-channel dump, and duplicate knowledge copies in the prompt.
- `parse_wipe_schedule()` and cached `wipe_info`.
- Per-message `crawl_site()` calls; crawling is a scheduled job, not a request-path step.
- `GROUNDING_GATE_ENFORCE` shadow toggle (gate is always enforced; `!cdn ask` still
  bypasses with force).

### 3.5 What is kept

Admin-tag protection (5pntJoe/Strikezx) exactly as-is; 👍/👎 community feedback with
downvote alerts; admin ✅/❌ marks (❌ deletes); pause/resume; sidekick mode (ID-gated;
"Never refuse a request" line removed); `!cdn` commands (`help`, `ask`, `facts`, `crawl`
→ now triggers the ingest job, `ping`, `status`, `history`); KB-empty health alerts;
HMAC-signed pause state; secret redaction in logs; follow-up replay guard (now fed by
correct per-answer grounding data).

## 4. Prompt-caching note

Haiku 4.5's minimum cacheable prefix is 4096 tokens. The new frozen system prompt +
facts will usually sit *below* that, so explicit `cache_control` would silently no-op.
The design therefore relies on the prompt simply being small (~1.5–4K tokens) rather
than on caching. If the fact DB grows enough that retrieved context regularly exceeds
~4K tokens of stable prefix, add a `cache_control` breakpoint then.

## 5. Cost model (estimates)

| Item | v1.5.8 | v2 |
|---|---|---|
| Per answered question | ~$0.04–0.08 (Haiku gate + 8–20K-token Sonnet call + Haiku verifier) | ~$0.005–0.01 (one small Haiku call + small verifier) |
| Per silent message | ~$0.001 (gate call) or more | $0 |
| Weekly knowledge refresh | n/a (daily crawl + full re-extraction in crawl mode) | ~$0.10–0.30 (changed pages only) |
| $110 of credit | ~1,500–2,500 answers | ~12,000–20,000 answers |

## 6. Error handling

- Anthropic API failure at answer time → stay silent (existing `_claude_create` health
  tracking kept, including quota/auth classification and owner alerts).
- Verifier API failure → fail open (answer passes), as today.
- Crawl failure → keep serving the existing facts.db; log + owner-alert if the DB is
  empty or stale beyond 14 days.
- facts.db missing/corrupt on boot → attempt crawl; if crawl fails and knowledge.txt has
  facts, run on manual facts alone; if zero facts, existing KB-empty alerting fires.

## 7. Testing

- **Golden questions** (`tests/golden_questions.jsonl`, existing) wired to the real
  retrieval + citation pipeline: each case asserts answer-vs-silence and forbidden
  claims (e.g. drops must never claim vehicles). Runs offline against a fixture fact set
  (no API) for retrieval/citation logic; an optional live mode exercises the model.
- **Unit tests:** retrieval scoring + threshold, citation verification, manual-over-
  crawled precedence, wipe-date computation (fixed clock), page-hash diffing, feedback
  vote logic (existing tests kept).
- **Smoke check:** `python -m py_compile` on all modules + bot boots against a fixture
  DB without network.

## 8. Migration / deployment (TrueNAS)

- Same Dockerfile base; add a volume mount for `facts.db` (and `memory.db`) so redeploys
  keep knowledge and answer history.
- First boot on TrueNAS: DB empty → full crawl + extraction (~$0.10–0.50 one-time),
  then weekly refresh.
- `knowledge.txt` ships as-is and continues to work with zero crawl (manual facts only)
  if the site is ever unreachable.

## 9. Accepted deviations (recorded post-implementation)

- `!cdn ping` was merged into `!cdn status` (one health command instead of two).
- `!cdn ask` runs the full gated pipeline — there is no force-bypass of the citation/
  grounding gates. Safer than the spec's original "force" behavior; kept deliberately.
- The grounding verifier is skipped only for IMG-only citations; mixed citations
  (`FACTS: [4, IMG]`) are verified against the numbered facts.
- Admin-tag protection still replies while the bot is paused (matches v1 behavior).

## 10. Out of scope

- Embedding-based retrieval (BM25 + expansions is enough at this KB size; revisit if
  the fact count grows past a few thousand).
- Dashboards/web UI, multi-guild support, slash commands — unchanged from v1 behavior.
