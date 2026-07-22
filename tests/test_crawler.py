import asyncio
from types import SimpleNamespace


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


def test_page_hash_stable():
    from crawler import page_hash
    assert page_hash("abc") == page_hash("abc")
    assert page_hash("abc") != page_hash("abd")


def test_extract_facts_parses_tagged_lines():
    from crawler import extract_facts_from_text
    client = FakeClient(["RULE: No PvP on standard servers\nnot a fact line\nREP: Vehicle Trader unlocks at 10,000 rep"])
    got = asyncio.run(extract_facts_from_text(client, "https://x.com/rules", "page text"))
    assert got == [("RULE", "No PvP on standard servers"),
                   ("REP", "Vehicle Trader unlocks at 10,000 rep")]


def test_run_ingest_only_extracts_changed_pages(tmp_path, monkeypatch):
    import crawler, knowledge as k

    dbp = str(tmp_path / "facts.db")

    async def fake_crawl():
        return {"https://x.com/a": "content A", "https://x.com/b": "content B"}

    monkeypatch.setattr(crawler, "crawl_site", fake_crawl)

    async def run():
        await k.init_facts_db(dbp)
        c1 = FakeClient(["RULE: rule from A", "RULE: rule from B"])
        await crawler.run_ingest(c1, bot=None, db_path=dbp)
        assert len(c1.messages.calls) == 2          # both pages new -> both extracted
        await k.reload_facts(db_path=dbp)
        assert len(k.facts()) == 2

        # Second ingest, nothing changed -> zero API calls
        c2 = FakeClient([])
        await crawler.run_ingest(c2, bot=None, db_path=dbp)
        assert len(c2.messages.calls) == 0

        # Page A changes -> exactly one extraction call
        async def fake_crawl2():
            return {"https://x.com/a": "content A v2", "https://x.com/b": "content B"}
        monkeypatch.setattr(crawler, "crawl_site", fake_crawl2)
        c3 = FakeClient(["RULE: new rule from A"])
        await crawler.run_ingest(c3, bot=None, db_path=dbp)
        assert len(c3.messages.calls) == 1
    asyncio.run(run())


def test_extract_facts_survives_empty_response():
    from crawler import extract_facts_from_text

    class EmptyMessages:
        async def create(self, **kw):
            return SimpleNamespace(content=[])

    client = SimpleNamespace(messages=EmptyMessages())
    got = asyncio.run(extract_facts_from_text(client, "https://x.com/a", "text"))
    assert got == []


def test_failed_extraction_keeps_existing_facts(tmp_path, monkeypatch):
    import crawler, knowledge as k
    dbp = str(tmp_path / "facts.db")

    async def crawl_v1():
        return {"https://x.com/a": "content A"}
    monkeypatch.setattr(crawler, "crawl_site", crawl_v1)

    async def run():
        await k.init_facts_db(dbp)
        await crawler.run_ingest(FakeClient(["RULE: original fact"]), bot=None, db_path=dbp)
        assert len(k.facts()) == 0 or await k.reload_facts(db_path=dbp) == 1
        # Page content changes but extraction fails (empty response)
        async def crawl_v2():
            return {"https://x.com/a": "content A changed"}
        monkeypatch.setattr(crawler, "crawl_site", crawl_v2)

        class EmptyMessages:
            async def create(self, **kw):
                return SimpleNamespace(content=[])
        await crawler.run_ingest(SimpleNamespace(messages=EmptyMessages()), bot=None, db_path=dbp)
        assert await k.reload_facts(db_path=dbp) == 1   # original fact survived
        # And the hash was NOT updated: a working client now re-extracts
        c3 = FakeClient(["RULE: replacement fact"])
        await crawler.run_ingest(c3, bot=None, db_path=dbp)
        assert len(c3.messages.calls) == 1
    asyncio.run(run())
