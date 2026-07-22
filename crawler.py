"""Weekly site ingest: Playwright crawl -> per-page hash diff -> Haiku extraction of
CHANGED pages only -> facts.db. Also ingests the Discord reference channel."""
import asyncio
import hashlib
import re
from urllib.parse import urljoin, urldefrag, urlparse

from bs4 import BeautifulSoup

import config
import knowledge
from logging_util import log

_EXTRACTION_PROMPT = """\
You are extracting structured facts from the CDNDayz DayZ server website.
Read ALL of the content below and extract EVERY concrete fact.

CRITICAL RULES — follow these exactly:
- Extract EVERY fact, rule, number, policy, distance, cause, fix, and server-specific detail
- MAXIMUM GRANULARITY: each individual cause, fix, step, or sub-detail gets its own line
- Do NOT summarise — reproduce the actual content
- Do NOT add commentary, blank lines, or explanations
- Every output line MUST start with a TAG: prefix (ALL-CAPS tag, invent one if needed)

Existing tags — use these when they apply:
  RULE WIPE ERROR DONATION SERVER_IP SCIFI REP DUNGEON TRADER BASE EVENT FAQ JOIN MOD
  POPULATION LOOT ZONE PRIVACY TERMS

Format examples (this is the REQUIRED granularity):
RULE: No building within 1000 metres of any trader
WIPE: All CDN servers wipe approximately every 90 days
WIPE: Last wipe: 2026-06-14
ERROR: 0x00040010 = ADMIN_KICK — player was removed by a server administrator
ERROR: 0x00040010 fix = if a restart was announced, wait and reconnect
REP: Black Market unlocks at 50,000 rep
FAQ: Q: Is PvP allowed? A: Not on standard servers. HC servers allow territory PvP

Only output facts. No explanations. No blank lines. No markdown.

Content:
"""

_CHUNK_CHARS = 24000   # per extraction call; pages larger than this are chunked


def page_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def extract_facts_from_text(client, source: str, text: str) -> list[tuple[str, str]]:
    """Run Haiku extraction over (possibly chunked) page text. Returns (tag, text) pairs."""
    facts: list[tuple[str, str]] = []
    seen: set[str] = set()
    chunks = [text[i:i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)] or [""]
    for chunk in chunks:
        try:
            resp = await client.messages.create(
                model=config.ANSWER_MODEL,
                max_tokens=8192,
                messages=[{"role": "user", "content": _EXTRACTION_PROMPT + f"[{source}]\n{chunk}"}],
            )
        except Exception as exc:
            log(f"Extraction failed for {source}: {exc}", "warn")
            continue
        for line in resp.content[0].text.splitlines():
            parsed = knowledge.parse_fact_line(line)
            if parsed and line.strip() not in seen:
                seen.add(line.strip())
                facts.append(parsed)
    return facts


# ── Playwright crawl ─────────────────────────────────────────────────────────
def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "noscript", "iframe", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def _normalise_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc == "cdndayz.com":
        url = parsed._replace(netloc="www.cdndayz.com").geturl()
    return url.rstrip("/")


def _discover_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_netloc = urlparse(config.CDN_WEBSITE).netloc.removeprefix("www.")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full, _ = urldefrag(urljoin(base_url, href))
        p = urlparse(full)
        if p.netloc.removeprefix("www.") == base_netloc and p.scheme in ("http", "https"):
            links.append(_normalise_url(full))
    return links


async def _fetch_page(browser, url: str) -> tuple[str, str, str]:
    """Fetch one page with JS rendering; click through sibling <button> tab bars so
    conditionally-rendered content is captured. Returns (url, html, all_text)."""
    page = None
    try:
        page = await browser.new_page()
        await page.set_extra_http_headers({"User-Agent": "CDN-Captain-Bot/2.0"})
        await page.goto(url, wait_until="networkidle", timeout=20000)
        html = await page.content()
        parts = [_extract_text(html)]
        tab_groups = await page.evaluate("""() => {
            const groups = new Map();
            for (const btn of document.querySelectorAll('button')) {
                const p = btn.parentElement;
                if (!p) continue;
                if (!groups.has(p)) groups.set(p, []);
                groups.get(p).push(btn);
            }
            const out = [];
            for (const [, btns] of groups) {
                const named = btns.filter(b => b.innerText.trim().length > 0);
                if (named.length >= 2 && named.length <= 6) out.push(named.map(b => b.innerText.trim()));
            }
            return out;
        }""")
        for group in tab_groups:
            for name in group[1:]:
                try:
                    await page.get_by_role("button", name=name, exact=True).click()
                    await page.wait_for_timeout(900)
                    t = _extract_text(await page.content())
                    if t and t not in parts:
                        parts.append(t)
                except Exception:
                    pass
        return url, html, "\n\n--- (tab) ---\n\n".join(parts)
    except Exception as exc:
        log(f"Could not load page: {url} ({exc})", "warn")
        return url, "", ""
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def crawl_site() -> dict[str, str]:
    """BFS crawl of cdndayz.com with headless Chromium. Returns url -> visible text."""
    from playwright.async_api import async_playwright

    log("Crawling cdndayz.com (renders JavaScript)...", "crawl")
    visited: set[str] = set()
    queue = [_normalise_url(config.CDN_WEBSITE)]
    result: dict[str, str] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            while queue and len(visited) < config.MAX_PAGES_TO_CRAWL:
                batch = []
                while queue and len(batch) < config.CRAWL_CONCURRENCY:
                    u = queue.pop(0)
                    if u not in visited:
                        visited.add(u)
                        batch.append(u)
                if not batch:
                    break
                for url, html, text in await asyncio.gather(*[_fetch_page(browser, u) for u in batch]):
                    if not html:
                        continue
                    if text:
                        result[url] = text
                    for link in _discover_links(html, url):
                        if link not in visited and link not in queue:
                            queue.append(link)
        finally:
            await browser.close()
    log(f"Crawl done — {len(result)} pages", "ok")
    return result


async def fetch_reference_text(bot) -> str:
    """Read the reference channel's messages as one text blob (ingest source, not a prompt dump)."""
    if bot is None:
        return ""
    channel = bot.get_channel(config.REFERENCE_CHANNEL_ID)
    if channel is None:
        log(f"Cannot find the reference channel (ID: {config.REFERENCE_CHANNEL_ID})", "warn")
        return ""
    lines = []
    try:
        async for msg in channel.history(limit=config.REFERENCE_CHANNEL_MSG_LIMIT, oldest_first=True):
            if msg.content.strip():
                lines.append(msg.content.strip())
    except Exception as exc:
        log(f"Could not read reference channel: {exc}", "warn")
        return ""
    return "\n".join(lines)


async def run_ingest(client, bot=None, db_path: str | None = None) -> str:
    """Full ingest: crawl -> diff hashes -> extract changed pages only -> retire gone
    pages -> ingest reference channel -> reload the fact cache. Returns a summary."""
    pages = await crawl_site()
    old_hashes = await knowledge.get_page_hashes(db_path=db_path)
    changed = unchanged = 0
    for url, text in pages.items():
        h = page_hash(text)
        if old_hashes.get(url) == h:
            await knowledge.touch_page(url, db_path=db_path)
            unchanged += 1
            continue
        extracted = await extract_facts_from_text(client, url, text)
        await knowledge.replace_page_facts(url, h, extracted, db_path=db_path)
        changed += 1
    retired = 0
    if pages:  # a failed/empty crawl must never wipe the KB
        retired = await knowledge.retire_pages(set(pages.keys()), db_path=db_path)

    ref_text = await fetch_reference_text(bot)
    if ref_text and old_hashes.get("ref-channel") != page_hash(ref_text):
        extracted = await extract_facts_from_text(client, "ref-channel", ref_text)
        await knowledge.replace_page_facts("ref-channel", page_hash(ref_text), extracted, db_path=db_path)

    total = await knowledge.reload_facts(db_path=db_path)
    summary = (f"Ingest done — {changed} page(s) re-extracted, {unchanged} unchanged, "
               f"{retired} retired, {total} facts loaded")
    log(summary, "ok")
    return summary


async def ingest_loop(client, bot) -> None:
    """Background task: re-ingest every CRAWL_INTERVAL_SECONDS."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(config.CRAWL_INTERVAL_SECONDS)
        try:
            await run_ingest(client, bot)
        except Exception as exc:
            log(f"Scheduled ingest failed: {exc}", "error")
