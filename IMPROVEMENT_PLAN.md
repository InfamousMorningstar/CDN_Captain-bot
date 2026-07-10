# CDN_Captain — Improvement Plan

Prioritized, incremental roadmap from a production code review, pressure-tested in a
brainstorming pass. Each item lists the problem, the fix, the code location, and
impact/effort so work can be picked up one change at a time without destabilizing the
bot. Items marked ✅ are already done.

**Guiding decision:** the bot's core promise is *answer from sources or stay silent*.
Where we must trade off, we prefer **silence over a wrong answer** — but we roll out
suppression carefully (shadow mode first) so we don't make the bot uselessly quiet.

---

## ✅ Done this pass

- **Knowledge base restored & corrected.** `knowledge.txt` was comment-only (zero
  facts); real facts are back, plus a corrected DROPS/AIRDROPS section (gear,
  medical, high-value loot like GPUs/bitcoin-farm parts; **not** vehicles; Spiders
  signal a higher-value drop). The invented "500m"/vehicle claims are gone.
- **Loader bug fixed.** `load_knowledge_file()` now strips `#` comments per the
  file's own contract and treats a fact-less file as empty, so the bot falls back to
  the live crawl instead of running blind on nothing.

---

## Root-cause reframe (from the brainstorm)

The incident wasn't mainly a model problem — it was **operational**: the bot ran on an
empty knowledge base and *nobody noticed until a player corrected it in chat*. So the
highest-leverage fixes are the cheap ones that make "the bot is silently broken"
impossible to miss, and that turn community corrections into a data signal. The fancy
grounding gate matters, but it's the second line of defense, not the first.

A virtuous loop ties the P0 items together:
> grounding gate logs a **suppressed** question → that's a **KB gap** → owner adds the
> fact to `knowledge.txt` → the case becomes a **golden-question** regression test.

---

## P0 — Cheap, high-leverage, do first

> **Status: all three P0 items implemented.** Verified by compiling each edited
> span under real Python + authoritative boundary checks. The grounding gate is
> live in **shadow mode** (logs only). Run `python -m py_compile bot.py` on the host
> as a final check, then restart the bot.

### ✅ 1. Knowledge-base health signal  *(promoted from P2)*
- **Problem:** the bot happily ran with zero facts and no one knew. There is no
  visible signal of KB state.
- **Fix:** on startup and periodically, log/emit to the owner: KB source (file vs
  crawl), **fact count**, and last-crawl/last-loaded time. Alert the owner if fact
  count is 0 or drops sharply. Optional `!cdn health` command for on-demand check.
- **Impact:** High (prevents the exact recurrence) · **Effort:** Low

### ✅ 2. Close the sidekick privilege-escalation hole
- **Problem:** `sidekick_answer` runs with **no** guardrails ("Never refuse a
  request"). It's gated by owner user-ID, but a fallback also matches on
  **display name** (`display_name.lower() == SIDEKICK_USERNAME`, bot.py ~1846–1850),
  which anyone can set — impersonating the owner into the unguarded model.
- **Fix:** authorize on the immutable user ID only; delete the display-name fallback.
- **Impact:** High · **Effort:** Low (one-liner)

### ✅ 3. Verifier-based grounding gate — **shadow mode first**
- **Problem:** anti-hallucination is prompt-only and *self-graded* (`CONFIDENCE:X`
  written by the same model, bot.py ~1494–1694). A plausible fabrication self-scores
  high and passes. Keyword/overlap checks are too weak — the drops answer reused KB
  vocabulary and would slip through.
- **Fix:** after generation, a **separate cheap "verifier" call** sees *only* the
  sources + the answer and judges whether every claim is supported; ungrounded →
  suppress. **Roll out in shadow mode:** first log the verdict without suppressing,
  measure how often it *would* wrongly silence a good answer, tune the threshold,
  *then* enforce. **Log every suppression** (question + reason) as the KB-gap feed.
- **Impact:** High · **Effort:** Medium

---

## P1 — Turn corrections into a system

> **Status: all P1 items (4–10) implemented and verified.** Feedback vote logic and
> the DB migration are unit-tested; the golden invariant runner passes a good KB and
> fails empty + fabrication KBs; every edited span compiles under real Python. Dead
> files removed. Run `python -m py_compile bot.py` on the host as the final check.

### ✅ 4. Answer feedback signal  *(new)*
- **Problem:** today the only hallucination detector is a human noticing in chat.
- **Fix:** add 👍/👎 (or a report) reaction on bot replies; capture to the DB as an
  early-warning + KB-improvement stream.
- **Impact:** High · **Effort:** Low–Medium

### ✅ 5. Golden-question regression set  *(new)*
- **Problem:** nothing stops this exact bug from silently returning after a prompt or
  KB change.
- **Fix:** ~15 known Q→expected-behavior cases (incl. "drops → must NOT claim
  vehicles"; "wipe → answer or silence"). Run on every prompt/KB change. Seed it from
  suppression logs (#3) and 👎 feedback (#4).
- **Impact:** Medium–High · **Effort:** Low–Medium

### ✅ 6. Only replay *verified* answers as follow-up context
- Prior answers are replayed as authoritative `FOLLOW-UP CONTEXT` (bot.py ~1451–1460),
  so one hallucination seeds the next. After #3, only persist/replay answers that
  passed the gate. · **Impact:** Medium · **Effort:** Low (after #3)

### ✅ 7. Delete dead duplicate `bot_gate_fix.py`
- Byte-identical to `bot.py`; only `bot.py` runs. Foot-gun. Remove it.
  · **Impact:** Medium · **Effort:** Low

### ✅ 8. Fail-fast config validation
- Validate `DISCORD_TOKEN`, `ANTHROPIC_API_KEY`, well-formed `SIDEKICK_USER_ID` at
  boot with a clear message. · **Impact:** Medium · **Effort:** Low

### ✅ 9. Audit logs/error text for secret & PII leakage
- `_classify_anthropic_issue` surfaces raw exception text (bot.py ~458–491); ensure
  tokens/keys/PII never reach logs. · **Impact:** Medium · **Effort:** Low

### ✅ 10. Retire `knowledge.txt.old`
- Superseded; archive/delete for one source of truth. · **Impact:** Low · **Effort:** Low

---

## P2 — Later

### ✅ 11. Confirm the cheap path short-circuits — **plus a real bug fix**
- Audit result: the ordering is correct. All cheap local checks (age, min length,
  `is_question`, directed-at-someone, cooldown) and the `db_is_recently_answered`
  dedup run **before** the first API call (`should_attempt_answer` classifier) and
  the expensive `evaluate_and_answer`.
- **Bug found & fixed:** in static-file mode `_crawl_done_time` stays `0`, so
  `crawl_site()`'s cache guard never tripped — the per-message `crawl_site(None)`
  call would launch a full Playwright crawl (~15s) **and overwrite the knowledge-file
  content** in `_page_store`. Added a `_using_knowledge_file` short-circuit at the top
  of `crawl_site()` so file mode never crawls. (Reliability + performance.)

### ✅ 12. Optional structured log file
- New opt-in `LOG_FILE` env var: when set, every console line is also appended as a
  plain, timestamped, level-tagged, **secret-redacted** record for after-the-fact
  debugging. Console behavior unchanged when unset.

### 13. Modularize the ~2,600-line `bot.py` — **deferred (do in a dev checkout)**
- Still worth doing, but it is the one change that should **not** be done blind: a
  module split rewires imports across the whole file and touches the PyInstaller
  `.spec` build, so it needs a full local `py_compile` + a smoke run to verify — which
  this environment can't do reliably (the sandbox mirror desyncs on in-place edits).
- Recommended incremental seams, one PR each, behavior-preserving, verified locally:
  1. `logging_util.py` — `_log`, `_redact`, colors, `LOG_FILE`.
  2. `db.py` — the `db_*` helpers + `init_db`.
  3. `knowledge.py` — crawl, extraction, `knowledge.txt` loader, KB health.
  4. `answering.py` — `evaluate_and_answer`, verifier gate, `sidekick_answer`.
  5. `bot.py` keeps Discord wiring (events, commands) and imports the above.
- Do each seam with the golden invariant check + `py_compile` green before moving on.

---

## Suggested order
**P0:** 1 → 2 → 3 (shadow) → 3 (enforce after tuning).
**P1:** 4 → 5 (fed by 3 & 4) → 6 → 7 → 8 → 9, with 10 whenever.
**P2:** 11 → 12 done. 13 (modularization) deferred to a local dev checkout.

## Status
P0, P1, and P2 #11–#12 are implemented and verified. The only remaining code item is
#13 (modularization), intentionally deferred. Non-code follow-up: once the shadow gate
has logged real traffic, review `suppressed_answers.jsonl` and set
`GROUNDING_GATE_ENFORCE=1`.

## Cheapest test of the riskiest assumption
The riskiest assumption is that the grounding gate won't over-silence. Resolve it for
near-zero cost by running #3 in **shadow mode** and reviewing the would-suppress log
against real traffic before enforcing.
