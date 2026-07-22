import json
import pathlib

import knowledge as k
from retrieval import retrieve

GOLDEN = pathlib.Path(__file__).parent / "golden_questions.jsonl"
KNOWLEDGE = pathlib.Path(__file__).parent.parent / "knowledge.txt"

# Handled by a non-retrieval path, or enforced at the model layer (live harness):
RETRIEVAL_EXEMPT = {"admin-ping", "black-market-location", "wipe-date-unknown",
                    "map-scope", "hallucination-bait"}


def _load_manual_facts() -> list[k.Fact]:
    facts = []
    i = 0
    for line in KNOWLEDGE.read_text(encoding="utf-8").splitlines():
        parsed = k.parse_fact_line(line)
        if parsed:
            i += 1
            facts.append(k.Fact(i, parsed[0], parsed[1], "knowledge.txt", True))
    return facts


def _cases():
    return [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_answer_cases_retrieve_facts():
    facts = _load_manual_facts()
    misses = []
    for case in _cases():
        if case["expect"] != "answer" or case["id"] in RETRIEVAL_EXEMPT:
            continue
        if not retrieve(case["question"], facts):
            misses.append(case["id"])
    assert not misses, f"Golden 'answer' cases retrieved zero facts: {misses}"


def test_offtopic_cases_stay_silent():
    facts = _load_manual_facts()
    leaks = []
    for case in _cases():
        if case["expect"] != "silent" or case["id"] in RETRIEVAL_EXEMPT:
            continue
        got = retrieve(case["question"], facts)
        if got:
            leaks.append((case["id"], [f.id for f in got]))
    assert not leaks, f"Golden 'silent' cases retrieved facts: {leaks}"
