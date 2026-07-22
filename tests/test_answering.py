from answering import parse_answer, verify_citations


def test_no_answer_variants():
    assert parse_answer("NO_ANSWER") is None
    assert parse_answer("  no_answer  ") is None
    assert parse_answer("") is None


def test_parse_answer_with_citations():
    raw = "The Black Market unlocks at **50,000 rep**.\nFACTS: [2]"
    text, cited = parse_answer(raw)
    assert "50,000" in text
    assert "FACTS" not in text
    assert cited == [2]


def test_parse_answer_img_and_multi():
    text, cited = parse_answer("Do X then Y.\nFACTS: [4, IMG]")
    assert cited == [4, "IMG"]


def test_parse_answer_missing_facts_line():
    text, cited = parse_answer("Some confident claim with no citations.")
    assert cited == []          # verify_citations will reject this


def test_verify_citations():
    assert verify_citations([2], {1, 2, 3}, has_images=False) is True
    assert verify_citations([], {1, 2}, has_images=False) is False          # no citations
    assert verify_citations([9], {1, 2}, has_images=False) is False         # unknown id
    assert verify_citations(["IMG"], set(), has_images=True) is True        # screenshot answer
    assert verify_citations(["IMG"], {1}, has_images=False) is False        # IMG without image
    assert verify_citations([1, "IMG"], {1}, has_images=True) is True


import asyncio
from types import SimpleNamespace

import knowledge as k


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.replies.pop(0))])


class FakeClient:
    def __init__(self, replies):
        self.messages = FakeMessages(replies)


FACTS = [k.Fact(2, "REP", "Black Market unlocks at 50,000 rep", "knowledge.txt", True)]


def test_generate_answer_happy_path(tmp_path, monkeypatch):
    import config, answering
    monkeypatch.setattr(config, "SUPPRESSED_LOG_PATH", str(tmp_path / "s.jsonl"))
    client = FakeClient([
        "It unlocks at **50,000 rep**.\nFACTS: [2]",   # answer call
        "GROUNDED",                                     # verifier call
    ])

    ans = asyncio.run(answering.generate_answer(
        client, question="what rep for black market?", facts=FACTS, context="(none)"))
    assert ans is not None and "50,000" in ans.text and ans.cited == [2] and ans.grounded
    assert len(client.messages.calls) == 2


def test_generate_answer_no_answer(tmp_path):
    import answering
    client = FakeClient(["NO_ANSWER"])
    ans = asyncio.run(answering.generate_answer(
        client, question="namalsk traders?", facts=FACTS, context="(none)"))
    assert ans is None
    assert len(client.messages.calls) == 1   # verifier never runs on silence


def test_generate_answer_bad_citation_suppressed(tmp_path, monkeypatch):
    import config, answering
    sup = tmp_path / "s.jsonl"
    monkeypatch.setattr(config, "SUPPRESSED_LOG_PATH", str(sup))
    client = FakeClient(["Confident nonsense.\nFACTS: [99]"])
    ans = asyncio.run(answering.generate_answer(
        client, question="q?", facts=FACTS, context="(none)"))
    assert ans is None
    assert "citation" in sup.read_text()


def test_generate_answer_ungrounded_suppressed(tmp_path, monkeypatch):
    import config, answering
    sup = tmp_path / "s.jsonl"
    monkeypatch.setattr(config, "SUPPRESSED_LOG_PATH", str(sup))
    client = FakeClient([
        "The Black Market is behind the red barn.\nFACTS: [2]",
        "UNGROUNDED: location claim not in sources",
    ])
    ans = asyncio.run(answering.generate_answer(
        client, question="where is bm?", facts=FACTS, context="(none)"))
    assert ans is None                       # ENFORCED, not shadow
    assert "UNGROUNDED" in sup.read_text()


def test_verifier_fails_open_on_error():
    import answering

    class BoomMessages:
        async def create(self, **kw):
            raise RuntimeError("api down")

    client = SimpleNamespace(messages=BoomMessages())
    grounded, verdict = asyncio.run(answering.verify_grounded(client, "facts", "answer"))
    assert grounded is True and "verifier-error" in verdict


def test_generate_answer_empty_response_is_silent():
    import answering

    class EmptyMessages:
        async def create(self, **kw):
            return SimpleNamespace(content=[])

    client = SimpleNamespace(messages=EmptyMessages())
    ans = asyncio.run(answering.generate_answer(
        client, question="q?", facts=FACTS, context="(none)"))
    assert ans is None
