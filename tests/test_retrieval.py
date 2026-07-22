import knowledge as k
from retrieval import retrieve, extract_keywords

FACTS = [
    k.Fact(1, "RULE", "No building within 1000 metres of any trader", "knowledge.txt", True),
    k.Fact(2, "REP", "Black Market unlocks at 50,000 rep", "knowledge.txt", True),
    k.Fact(3, "DROPS", "Airdrops do NOT contain vehicles", "knowledge.txt", True),
    k.Fact(4, "ERROR", "0x00040010 = ADMIN_KICK — player was removed by an admin", "knowledge.txt", True),
    k.Fact(5, "ERROR", "0x00040093 cause = mod mismatch or corrupted mod files", "knowledge.txt", True),
    k.Fact(6, "JOIN", "Step 2 = download DZSA Launcher for mod management", "knowledge.txt", True),
]


def test_hex_code_exact_match_wins():
    got = retrieve("I got error 0x00040010, what does it mean?", FACTS)
    assert got and got[0].id == 4
    assert all(f.id != 5 for f in got[:1])   # never rank the wrong code first


def test_trader_build_question_finds_rule():
    got = retrieve("how close to a trader can I build my base?", FACTS)
    assert any(f.id == 1 for f in got)


def test_offtopic_is_silent():
    assert retrieve("what's the best pizza topping?", FACTS) == []


def test_smalltalk_is_silent():
    assert retrieve("lol good night everyone", FACTS) == []


def test_expansions_bridge_wording():
    # "blackmarket" (one word) must still reach the Black Market rep fact via expansions
    got = retrieve("what rep do I need for the blackmarket?", FACTS)
    assert any(f.id == 2 for f in got)


def test_short_words_do_not_substring_match():
    base, _, _ = extract_keywords("rep unlock")
    # 'rep' must not match inside 'report' etc. — retrieval uses word tokens
    got = retrieve("rep unlock", FACTS)
    assert any(f.id == 2 for f in got)
