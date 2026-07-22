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
