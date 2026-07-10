# CDN_Captain — Regression tests

Two layers guard against the "confident fabrication" class of bug (the incident where
the bot invented that airdrops drop vehicles, off an empty knowledge base).

## 1. Offline invariant check (fast, no API key)

`check_knowledge_invariants.py` runs directly against `knowledge.txt` and fails if any
core invariant is violated:

- the KB is empty (the bot would silently answer nothing — or worse, guess),
- comment/blank lines leaked into the facts,
- the drops/airdrop facts are missing, or claim vehicles drop from airdrops.

Run it:

```bash
python tests/check_knowledge_invariants.py
# or against a specific file:
python tests/check_knowledge_invariants.py path/to/knowledge.txt
```

Exit code `0` = pass, `1` = a regression. Wire this into CI or a pre-commit/pre-restart
hook so a bad `knowledge.txt` can never ship. It also validates that
`golden_questions.jsonl` is well-formed.

## 2. Behavioral golden set (needs a running bot + API)

`golden_questions.jsonl` is the behavioral spec — one JSON object per line:

| field              | meaning                                                        |
|--------------------|----------------------------------------------------------------|
| `id`               | stable identifier                                              |
| `question`         | the message to send                                            |
| `expect`           | `"answer"` (bot should reply) or `"silent"` (bot must not)     |
| `must_contain_any` | reply should contain at least one of these (for `answer`)     |
| `must_not_contain` | reply must contain none of these (fabrication guards)          |
| `note`             | why the case exists                                            |

These require the live answer path (`evaluate_and_answer`) and an Anthropic key, so run
them against a test bot / harness rather than in plain CI. Seed new cases from
`suppressed_answers.jsonl` (grounding-gate would-suppress log) and `flagged_answers.jsonl`
(community 👎 flags) — every real gap the bot hits becomes a permanent regression test.

## Keeping it current

When you add facts to `knowledge.txt` or change a prompt, add or update the matching
golden case. The drops case (`drops-not-vehicles`) is the canonical example: it exists
precisely because the bot got it wrong once.
