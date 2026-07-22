import asyncio


def test_parse_fact_line():
    import knowledge as k
    assert k.parse_fact_line("RULE: No PvP on standard servers") == ("RULE", "No PvP on standard servers")
    assert k.parse_fact_line("# comment") is None
    assert k.parse_fact_line("") is None
    assert k.parse_fact_line("no tag here") is None
    assert k.parse_fact_line("  REP: Black Market unlocks at 50,000 rep  ") == ("REP", "Black Market unlocks at 50,000 rep")


def test_manual_facts_load_and_override(tmp_path):
    import knowledge as k
    dbp = str(tmp_path / "facts.db")
    kf = tmp_path / "knowledge.txt"
    kf.write_text("# header\nRULE: manual rule one\nREP: manual rep fact\n", encoding="utf-8")

    async def run():
        await k.init_facts_db(dbp)
        n = await k.load_manual_facts(db_path=dbp, knowledge_file=str(kf))
        assert n == 2
        await k.replace_page_facts("https://x.com/a", "h1", [("RULE", "crawled rule")], db_path=dbp)
        total = await k.reload_facts(db_path=dbp)
        assert total == 3
        fl = k.facts()
        # Manual facts sort first
        assert fl[0].manual and fl[1].manual and not fl[2].manual
        # Reloading manual facts replaces, doesn't duplicate
        await k.load_manual_facts(db_path=dbp, knowledge_file=str(kf))
        assert await k.reload_facts(db_path=dbp) == 3
    asyncio.run(run())


def test_page_hash_diff_and_retire(tmp_path):
    import knowledge as k
    dbp = str(tmp_path / "facts.db")

    async def run():
        await k.init_facts_db(dbp)
        await k.replace_page_facts("https://x.com/a", "h1", [("RULE", "a")], db_path=dbp)
        await k.replace_page_facts("https://x.com/b", "h2", [("RULE", "b")], db_path=dbp)
        await k.replace_page_facts("ref-channel", "h3", [("REF", "c")], db_path=dbp)
        assert await k.get_page_hashes(db_path=dbp) == {
            "https://x.com/a": "h1", "https://x.com/b": "h2", "ref-channel": "h3",
        }
        # Page b vanished from the site: retire it. ref-channel must survive.
        gone = await k.retire_pages({"https://x.com/a"}, db_path=dbp)
        assert gone == 1
        await k.reload_facts(db_path=dbp)
        sources = {f.source for f in k.facts()}
        assert sources == {"https://x.com/a", "ref-channel"}
    asyncio.run(run())


def test_manual_facts_survive_missing_file(tmp_path):
    import knowledge as k
    dbp = str(tmp_path / "facts.db")
    kf = tmp_path / "knowledge.txt"
    kf.write_text("RULE: keep me\n", encoding="utf-8")

    async def run():
        await k.init_facts_db(dbp)
        assert await k.load_manual_facts(db_path=dbp, knowledge_file=str(kf)) == 1
        # File vanishes (mid-rewrite): manual facts must survive
        kf.unlink()
        assert await k.load_manual_facts(db_path=dbp, knowledge_file=str(kf)) == -1
        assert await k.reload_facts(db_path=dbp) == 1
        # File exists but empty: owner intent — clears manual facts
        kf.write_text("# only a comment\n", encoding="utf-8")
        assert await k.load_manual_facts(db_path=dbp, knowledge_file=str(kf)) == 0
        assert await k.reload_facts(db_path=dbp) == 0
    asyncio.run(run())
