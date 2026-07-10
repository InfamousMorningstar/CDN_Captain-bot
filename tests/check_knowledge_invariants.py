#!/usr/bin/env python3
"""
Golden-question / knowledge-base regression guard  (no API key required).

This runs FAST and OFFLINE. It checks invariants that must always hold about the
knowledge base — the ones whose violation caused, or would re-cause, the "confident
fabrication" incident:

  1. The KB is not empty (the empty-KB incident that let the bot invent answers).
  2. Comment/blank lines are ignored exactly like the bot's loader does.
  3. The drops/airdrop facts are present AND do not claim vehicles drop from airdrops.
  4. The golden-question spec (tests/golden_questions.jsonl) is present and well-formed.

It also loads tests/golden_questions.jsonl and reports how many cases are covered.
The LIVE behavioral layer (does the running bot actually answer/stay silent) needs a
bot + API and is documented in tests/README.md; this script is the cheap CI gate.

Usage:
    python tests/check_knowledge_invariants.py [path/to/knowledge.txt]

Exit code 0 = all invariants pass, 1 = at least one failed.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_KB = os.path.join(HERE, "..", "knowledge.txt")
GOLDEN = os.path.join(HERE, "golden_questions.jsonl")


def load_facts(path: str) -> list[str]:
    """Mirror the bot's loader: drop blank lines and '#' comments; keep real facts."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    return [
        line.rstrip()
        for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def check(path: str) -> list[str]:
    """Return a list of failure messages (empty list == all good)."""
    failures: list[str] = []

    if not os.path.exists(path):
        return [f"knowledge file not found: {path}"]

    facts = load_facts(path)
    kb_text = "\n".join(facts).lower()

    # 1. Non-empty KB
    if len(facts) == 0:
        failures.append("KB has 0 facts — the bot would stay silent on everything.")

    # 2. Comments actually stripped
    if any(f.lstrip().startswith("#") for f in facts):
        failures.append("A comment line leaked into the facts (loader contract broken).")

    # 3. Drops facts present and correct
    drops_facts = [f for f in facts if f.lower().startswith("drops") or "airdrop" in f.lower()]
    if not drops_facts:
        failures.append("No DROPS/airdrop facts found — the drops topic is uncovered.")
    else:
        # Must explicitly deny vehicles somewhere in the drops facts.
        denies_vehicles = any(
            ("vehicle" in f.lower()) and any(neg in f.lower() for neg in ("not ", "no ", "don't", "do not", "never"))
            for f in drops_facts
        )
        if not denies_vehicles:
            failures.append("Drops facts don't explicitly state airdrops do NOT contain vehicles.")
        # Must NOT positively claim vehicles drop.
        for marker in ("vehicles will drop", "vehicles drop from", "airdrops contain vehicles",
                       "drops contain vehicles", "drop vehicles", "helis, cars"):
            if marker in kb_text:
                failures.append(f"KB asserts a fabrication: contains '{marker}'.")

    # 4. Golden-question spec must be present and well-formed (each line valid JSON
    #    with the required fields). This is the offline half; the behavioral half —
    #    does the running bot actually answer/stay silent per each case — needs the
    #    live harness described in tests/README.md.
    covered = 0
    if os.path.exists(GOLDEN):
        with open(GOLDEN, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    case = json.loads(line)
                except json.JSONDecodeError as exc:
                    failures.append(f"golden_questions.jsonl line {i} is not valid JSON: {exc}")
                    continue
                covered += 1
                for field in ("id", "question", "expect"):
                    if field not in case:
                        failures.append(f"golden case on line {i} is missing '{field}'.")
                if case.get("expect") not in ("answer", "silent"):
                    failures.append(f"[{case.get('id')}] 'expect' must be 'answer' or 'silent'.")
    else:
        failures.append(f"golden_questions.jsonl not found at {GOLDEN}")

    print(f"KB: {len(facts)} facts · {len(drops_facts)} drops facts · "
          f"{covered} golden cases loaded")
    return failures


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KB
    failures = check(path)
    if failures:
        print("\nFAIL — knowledge-base invariants violated:")
        for msg in failures:
            print(f"  ✗ {msg}")
        return 1
    print("PASS — all knowledge-base invariants hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
