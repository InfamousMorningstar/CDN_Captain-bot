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
