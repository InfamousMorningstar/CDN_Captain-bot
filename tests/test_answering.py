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
