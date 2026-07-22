"""Local fact retrieval. Free, deterministic, and the gate on every API call:
if this module returns nothing, the bot stays silent and spends $0."""
import math
import re

import config
from knowledge import Fact

STOP_WORDS = {
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "do", "i", "my", "me",
    "we", "you", "of", "for", "and", "or", "but", "what", "how", "why", "when",
    "who", "where", "can", "does", "will", "are", "was", "were", "did", "has",
    "have", "had", "that", "this", "with", "from", "be", "been", "being",
    "they", "their", "there", "here", "just", "so", "if", "about", "get", "got",
    "need", "want", "know", "mean", "means",
}

KEYWORD_EXPANSIONS: dict[str, set[str]] = {
    "donate":    {"donation", "donator", "support", "patreon", "contribute", "tier"},
    "trader":    {"market", "shop", "vendor", "trade", "safe zone", "trader zone", "exclusion",
                  "vehicle trader", "aircraft trader", "special trader", "black market", "blackmarket"},
    "wipe":      {"reset", "restart", "wipe schedule", "server reset", "next wipe", "map reset"},
    "base":      {"build", "territory", "flag", "construction", "building", "base building"},
    "ban":       {"banned", "suspend", "appeal", "blacklist", "unban"},
    "error":     {"crash", "problem", "issue", "fix", "troubleshoot", "code"},
    "kick":      {"kicked", "disconnect", "disconnected", "removed"},
    "join":      {"connect", "server ip", "how to play", "get started", "whitelist", "launcher", "dzsa"},
    "whitelist": {"application", "apply", "allowlist", "accepted"},
    "rule":      {"rules", "regulation", "policy", "allowed", "prohibited", "forbidden"},
    "loot":      {"items", "spawn", "economy", "loot table", "gear"},
    "raid":      {"raiding", "base attack", "offline", "breach"},
    "mod":       {"mods", "modded", "modification", "modpack"},
    "drop":      {"drops", "airdrop", "airdrops"},
    "airdrop":   {"drop", "drops", "airdrops"},
    "distance":  {"metres", "meters", "radius", "boundary", "zone", "away", "far", "close"},
    "build":     {"territory", "base", "construction", "flag", "build zone", "building"},
    "rep":       {"reputation", "rep progression", "unlock", "unlocks", "points", "earn rep"},
    "blackmarket": {"black market", "rep", "reputation", "unlocks"},
    "dungeon":   {"permadeath", "permanent death", "dungeon run", "admin teleport", "dungeon rules"},
    "scifi":     {"sci-fi", "sci fi", "banov", "yrtsk", "blackmarket", "special trader", "rainbow bear"},
    "weapon":    {"yrtsk", "tier", "blackmarket", "t1", "t2", "t3", "t4", "t5"},
    "hardcore":  {"hc", "hc server", "territory", "raiding", "permadeath"},
    "vehicle":   {"vehicles", "car", "heli", "aircraft"},
}

_HEX_RE = re.compile(r"0[xX][0-9a-fA-F]+")


def extract_keywords(text: str) -> tuple[set[str], set[str], set[str]]:
    """Return (base keywords, expanded keywords, hex error codes) for a question."""
    hex_codes = {c.lower() for c in _HEX_RE.findall(text)}
    words = re.split(r"\W+", text.lower())
    base = {w for w in words if len(w) > 2 and w not in STOP_WORDS} - hex_codes
    expanded: set[str] = set()
    for kw in base:
        expanded |= KEYWORD_EXPANSIONS.get(kw, set())
    expanded -= base
    return base, expanded, hex_codes


def _fact_tokens(fact: Fact) -> set[str]:
    return {w for w in re.split(r"\W+", f"{fact.tag} {fact.text}".lower()) if w}


def _matches(kw: str, tokens: set[str], text_lower: str) -> bool:
    # Multi-word expansions match as substrings; single words match whole tokens
    # (so 'rep' never matches inside 'report').
    return (kw in text_lower) if " " in kw else (kw in tokens)


def retrieve(question: str, fact_list: list[Fact],
             top_n: int = config.TOP_FACTS) -> list[Fact]:
    """Score every fact against the question. Empty list == stay silent."""
    if not fact_list:
        return []
    base, expanded, hex_codes = extract_keywords(question)
    all_kw = base | expanded | hex_codes
    if not all_kw:
        return []

    n = len(fact_list)
    token_cache = [(_fact_tokens(f), f.text.lower()) for f in fact_list]

    # Document frequency per keyword (for IDF weighting)
    df: dict[str, int] = {}
    for kw in all_kw:
        df[kw] = sum(1 for toks, tl in token_cache if _matches(kw, toks, tl))

    scored: list[tuple[float, Fact]] = []
    for (toks, tl), fact in zip(token_cache, fact_list):
        score = 0.0
        strong_hits = 0     # hits on base keywords / hex codes (not just expansions)
        for kw in all_kw:
            if not _matches(kw, toks, tl):
                continue
            idf = math.log((n + 1) / (df[kw] + 1)) + 1.0
            if kw in hex_codes:
                idf *= 20.0
            weight = 1.0 if (kw in base or kw in hex_codes) else 0.5
            score += idf * weight
            if kw in base or kw in hex_codes:
                strong_hits += 1
        if score > 0 and strong_hits >= 1:
            scored.append((score, fact))

    if not scored:
        return []
    scored.sort(key=lambda x: (-x[0], not x[1].manual, x[1].id))
    if scored[0][0] < config.RETRIEVAL_MIN_SCORE:
        return []
    return [f for _, f in scored[:top_n]]
