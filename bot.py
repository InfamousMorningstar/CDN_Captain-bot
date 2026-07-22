# bot.py
"""CDN_Captain v2 — Discord wiring only. All logic lives in the other modules."""
import asyncio
import base64
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone

import aiohttp
import anthropic
import discord
from discord.ext import commands

import answering
import config
import crawler
import db
import knowledge
import retrieval
from logging_util import log, redact

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="!cdn ", intents=intents, help_command=None)
client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

_bot_paused = False
_bot_start_time = time.time()
_started = False
user_last_answered: dict[int, float] = defaultdict(float)

PAUSE_PHRASES = {"shutdown", "stop responding", "go silent", "pause", "don't respond",
                 "stop answering", "ignore everyone", "go quiet", "shut up", "shut down"}
RESUME_PHRASES = {"resume", "come back", "start responding", "wake up", "unpause",
                  "you can respond", "go back", "start answering", "turn on"}

_ADMIN_TAG_OPENER = ("Hey there! 👋 Please don't ping the admins — they won't respond to "
                     "direct tags and it clutters their notifications.")
_ADMIN_TAG_CLOSERS = [
    "Thanks for keeping the server tidy! 😊",
    "Appreciate you — the server runs smoother when we keep it organised! 🙌",
    "Cheers for understanding! The admins appreciate it. ✌️",
    "You're a legend for asking the right way. 🫡",
    "Thanks for being a good sport about it! 😄",
]

QUESTION_STARTERS = {"who", "what", "when", "where", "why", "how", "can", "could", "would",
                     "should", "is", "are", "was", "were", "does", "do", "did", "will",
                     "has", "have", "had"}

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
EXT_TO_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp"}


# ── Helpers ──────────────────────────────────────────────────────────────────
def _footer() -> str:
    return f"\n-# Engineered by [Morningstar.0](<{config.PORTFOLIO_URL}>)"


def _truncate_for_discord(answer_text: str, suffix: str = "") -> str:
    """Discord hard-caps messages at 2000 chars. Truncate the answer body (never
    the suffix) so replies never get silently dropped by discord.py."""
    if len(answer_text) + len(suffix) > 2000:
        answer_text = answer_text[: 2000 - len(suffix) - 2] + "…"
    return answer_text + suffix


def _build_reply_text(answer_text: str) -> str:
    return _truncate_for_discord(answer_text, _footer())


def build_admin_tag_response(message: discord.Message) -> str:
    guild = message.guild
    rules_ch = guild.get_channel(config.REFERENCE_CHANNEL_ID) if guild else None
    ticket_ch = guild.get_channel(config.TICKET_CHANNEL_ID) if guild else None
    rules = f"<#{rules_ch.id}>" if rules_ch else "the rules channel"
    ticket = f"<#{ticket_ch.id}>" if ticket_ch else "the ticket channel"
    return (f"{_ADMIN_TAG_OPENER}\n\n"
            f"🌐 **Check the website first** — **https://cdndayz.com** has the rules, FAQs, and info!\n"
            f"📋 **Server rules & info** are also in {rules}\n"
            f"💬 **Still have a question?** Ask it here — a community member or I might help!\n"
            f"🎫 **Need staff support?** Open a ticket in {ticket}\n"
            f"🚫 **Please don't DM the admins either** — tickets are the best way to reach them.\n\n"
            f"{random.choice(_ADMIN_TAG_CLOSERS)}{_footer()}")


def mentions_admin(message: discord.Message) -> bool:
    reply_author_id = None
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message):
            reply_author_id = ref.author.id
    for user in message.mentions:
        if user.id == reply_author_id:
            continue  # Discord auto-inserts the replied-to author as a mention
        if user.name.lower() in config.PROTECTED_ADMINS or user.display_name.lower() in config.PROTECTED_ADMINS:
            return True
    cl = message.content.lower()
    for admin in config.PROTECTED_ADMINS:
        if f"@{admin}" in cl:
            if reply_author_id is not None and message.guild:
                replied = message.guild.get_member(reply_author_id)
                if replied and (replied.name.lower() == admin or replied.display_name.lower() == admin):
                    continue
            return True
    return False


def is_admin_author(message: discord.Message) -> bool:
    a = message.author
    if isinstance(a, discord.Member) and a.guild_permissions.administrator:
        return True
    return a.name.lower() in config.PROTECTED_ADMINS or a.display_name.lower() in config.PROTECTED_ADMINS


def is_question(content: str) -> bool:
    content = content.strip()
    if len(content) < 8:
        return False
    if "?" in content:
        return True
    first = re.split(r"\W+", content)[0].lower()
    if first in QUESTION_STARTERS:
        return True
    if re.search(r"\b(error|crash|kick|ban|wipe|trader|base|build|loot|mod|dungeon|rep|"
                 r"whitelist|donat|server|dayz|0x[0-9a-fA-F]+)\w*\b", content, re.IGNORECASE):
        return len(content.split()) >= 4
    return False


def is_directed_at_someone(message: discord.Message) -> bool:
    if message.reference:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and not ref.author.bot:
            return True
        if ref is None and message.reference.message_id:
            humans = [u for u in message.mentions
                      if not u.bot and (bot.user is None or u.id != bot.user.id)]
            if humans:
                return True
    return False


def is_two_person_convo(recent: list[discord.Message]) -> bool:
    now = time.time()
    active = [m for m in recent if not m.author.bot
              and (now - m.created_at.timestamp()) <= 120][-10:]
    if len(active) < 4:
        return False
    counts = Counter(m.author.id for m in active)
    top_two = [aid for aid, _ in counts.most_common(2)]
    if len(top_two) < 2:
        return False
    ids = [m.author.id for m in active if m.author.id in top_two]
    return sum(1 for i in range(1, len(ids)) if ids[i] != ids[i - 1]) >= 3


def build_context(msgs: list[discord.Message], exclude_id: int) -> str:
    now = time.time()
    lines = []
    for m in msgs:
        if m.author.bot or m.id == exclude_id:
            continue
        age = int(now - m.created_at.timestamp())
        ts = f"{age}s ago" if age < 60 else (f"{age // 60}m ago" if age < 3600 else f"{age // 3600}h ago")
        lines.append(f"[{ts}] {m.author.display_name}: {m.content}")
    return "\n".join(lines) if lines else "(no recent context)"


def get_image_attachments(message: discord.Message) -> list:
    images = []
    for att in message.attachments:
        ct = (att.content_type or "").lower().split(";")[0].strip()
        ext = os.path.splitext(att.filename.lower())[1]
        if ct in SUPPORTED_IMAGE_TYPES or ext in EXT_TO_MEDIA:
            images.append(att)
    return images


async def download_image_blocks(attachments: list) -> list[dict]:
    blocks = []
    async with aiohttp.ClientSession() as session:
        for att in attachments:
            if getattr(att, "size", 0) > 5 * 1024 * 1024:
                log(f"Skipping screenshot over 5MB: {att.filename}", "warn")
                continue
            try:
                async with session.get(att.url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        continue
                    ct = (resp.headers.get("Content-Type", "image/png")).lower().split(";")[0].strip()
                    media = ct if ct in SUPPORTED_IMAGE_TYPES else "image/png"
                    data = base64.standard_b64encode(await resp.read()).decode()
                    blocks.append({"type": "image",
                                   "source": {"type": "base64", "media_type": media, "data": data}})
            except Exception as exc:
                log(f"Could not download a screenshot: {exc}", "warn")
    return blocks


async def is_recently_answered(channel_id: int, question: str) -> bool:
    prev = await db.recent_questions(channel_id, time.time() - config.ANSWER_DEDUP_TTL)
    q_kw, _, _ = retrieval.extract_keywords(question)
    if not q_kw:
        return False
    for p in prev:
        p_kw, _, _ = retrieval.extract_keywords(p)
        if p_kw and len(q_kw & p_kw) / max(len(q_kw | p_kw), 1) > 0.7:
            return True
    return False


async def notify_owner(text: str) -> None:
    try:
        owner = bot.get_user(config.SIDEKICK_USER_ID) or await bot.fetch_user(config.SIDEKICK_USER_ID)
        if owner:
            await owner.send(text)
    except Exception as exc:
        log(f"Could not DM owner alert: {exc}", "warn")


async def send_with_retry(coro_fn, max_retries: int = 3) -> discord.Message:
    for attempt in range(1, max_retries + 1):
        try:
            return await coro_fn()
        except discord.errors.HTTPException as exc:
            if exc.status == 429 and attempt < max_retries:
                wait = getattr(exc, "retry_after", None) or (2 ** attempt)
                log(f"Discord rate limit — waiting {wait:.1f}s (attempt {attempt})", "warn")
                await asyncio.sleep(wait)
            else:
                raise
    raise RuntimeError("Max retries exceeded")


def facts_with_wipe() -> list[knowledge.Fact]:
    """The fact list plus a synthetic, Python-computed next-wipe fact (id=0) when derivable."""
    fl = list(knowledge.facts())
    wipe = knowledge.compute_next_wipe(fl, date.today())
    if wipe:
        fl.append(knowledge.Fact(0, "WIPE", wipe, "computed", True))
    return fl


# ── Sidekick (owner) mode ────────────────────────────────────────────────────
def is_sidekick_trigger(message: discord.Message) -> bool:
    if message.author.id != config.SIDEKICK_USER_ID:
        return False
    if bot.user and bot.user in message.mentions:
        return True
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and ref.author == bot.user:
            return True
    return message.content.strip().lower().startswith("cdn")


async def sidekick_answer(message: discord.Message, context: str) -> str | None:
    content = message.content
    if bot.user:
        content = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
    fact_text = "\n".join(f"{f.tag}: {f.text}" for f in facts_with_wipe())
    system = (f"You are CDN_Captain, the personal AI sidekick of the owner of the CDNDayz "
              f"DayZ community. You are talking directly to your owner. Be direct, helpful, "
              f"and conversational.\n\nServer knowledge:\n{fact_text}\n\n"
              f"Recent channel context:\n{context}")
    try:
        resp = await client.messages.create(
            model=config.ANSWER_MODEL, max_tokens=1000, system=system,
            messages=[{"role": "user", "content": content or "(no text)"}])
        return resp.content[0].text.strip()
    except Exception as exc:
        log(f"Sidekick error: {exc}", "error")
        return None


# ── Events ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global _bot_paused, _started
    print()
    log(f"CDN_Captain {config.CURRENT_VERSION} — logged in as {bot.user}", "ok")
    if _started:
        return
    _started = True
    await db.init_db()
    await knowledge.init_facts_db()
    _bot_paused = await db.get_paused()
    if _bot_paused:
        log("Bot is PAUSED — silent until resumed", "warn")
    await knowledge.load_manual_facts()
    total = await knowledge.reload_facts()
    last = await knowledge.last_crawl_time()
    log(f"Knowledge ready — {total} facts loaded "
        f"(last crawl: {'never' if not last else datetime.fromtimestamp(last).strftime('%Y-%m-%d')})", "ok")

    if last is None or (time.time() - last) > config.CRAWL_INTERVAL_SECONDS:
        log("Fact DB empty or stale — starting ingest in the background", "crawl")
        asyncio.create_task(_startup_ingest())
    asyncio.create_task(crawler.ingest_loop(client, bot))
    asyncio.create_task(_kb_health_loop())
    log("Online and listening — answers only when facts support it", "ok")


async def _startup_ingest():
    try:
        await crawler.run_ingest(client, bot)
    except Exception as exc:
        log(f"Startup ingest failed: {exc}", "error")


async def _kb_health_loop():
    alerted = False
    while not bot.is_closed():
        await asyncio.sleep(1800)
        n = len(knowledge.facts())
        last = await knowledge.last_crawl_time()
        stale = last is not None and (time.time() - last) > config.CRAWL_STALE_ALERT_SECONDS
        if n == 0 or stale:
            log(f"KB health problem — {n} facts, stale={stale}", "error")
            if not alerted:
                await notify_owner("⚠️ CDN_Captain knowledge base problem: "
                                   f"{n} facts loaded, crawl stale={stale}. "
                                   "Check knowledge.txt or run `!cdn crawl`.")
                alerted = True
        else:
            alerted = False


@bot.event
async def on_message(message: discord.Message):
    global _bot_paused
    if message.author.bot:
        return
    if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
        return
    parent_id = getattr(getattr(message.channel, "parent", None), "id", None)
    if message.channel.id in config.IGNORED_CHANNEL_IDS or parent_id in config.IGNORED_CHANNEL_IDS:
        return

    await bot.process_commands(message)

    # Command messages end here — never fall through into the answering pipeline
    # (otherwise "!cdn ask ..." would trigger a second, duplicate answer).
    if message.content.lstrip().startswith("!cdn"):
        return

    if mentions_admin(message) and not is_admin_author(message):
        try:
            await message.reply(build_admin_tag_response(message), mention_author=True)
        except discord.HTTPException:
            pass
        return

    content = message.content.strip()
    channel_name = getattr(message.channel, "name", "unknown")
    images = get_image_attachments(message)
    log(f"#{channel_name} · {message.author.display_name}: \"{content[:55]}\""
        f"{f' +{len(images)} image(s)' if images else ''}", "msg")

    # Sidekick / pause control
    if is_sidekick_trigger(message):
        low = content.lower()
        if any(p in low for p in RESUME_PHRASES):
            _bot_paused = False
            await db.set_paused(False)
            await message.reply("Back on watch.", mention_author=True)
            return
        if any(p in low for p in PAUSE_PHRASES):
            _bot_paused = True
            await db.set_paused(True)
            await message.reply("Going quiet now. Ping me when you want me back.", mention_author=True)
            return
        ctx = await _channel_context(message)
        ans = await sidekick_answer(message, ctx)
        if ans:
            await send_with_retry(lambda: message.reply(ans, mention_author=True))
        return

    if _bot_paused:
        return

    # ── Free pre-checks ──────────────────────────────────────────────────────
    if (time.time() - message.created_at.timestamp()) > config.MAX_MESSAGE_AGE_SECONDS:
        return
    if not images:
        if not content or not is_question(content):
            return
        if is_directed_at_someone(message):
            return
    if time.time() - user_last_answered[message.author.id] < config.USER_COOLDOWN_SECONDS:
        return
    if not images and await is_recently_answered(message.channel.id, content):
        log("Stayed silent — similar question answered here recently", "skip")
        return

    recent = await _recent_messages(message)
    if is_two_person_convo(recent) and not images:
        log("Stayed silent — two players mid-conversation", "skip")
        return

    # ── Local retrieval gate: no facts, no API call, no cost ─────────────────
    fact_list = facts_with_wipe()
    retrieved = retrieval.retrieve(content or "error screenshot help", fact_list)
    if not retrieved and not images:
        log("Stayed silent — no matching facts (0 API calls)", "skip")
        return

    image_blocks = await download_image_blocks(images) if images else None
    if images and not image_blocks:
        log("All screenshot downloads failed — skipping", "warn")
        return

    # Follow-up replay guard: only replay grounded, not-marked-wrong answers
    prior = None
    if message.reference and message.reference.resolved:
        ref = message.reference.resolved
        if isinstance(ref, discord.Message) and ref.author == bot.user:
            candidate = await db.get_by_message_id(ref.id)
            if db.is_replayable(candidate):
                prior = candidate

    user_last_answered[message.author.id] = time.time()
    answer = await answering.generate_answer(
        client,
        question=content,
        facts=retrieved,
        context=build_context(recent, exclude_id=message.id),
        image_blocks=image_blocks,
        prior=prior,
        channel_name=channel_name,
    )
    if answer is None:
        return

    try:
        sent = await send_with_retry(lambda: message.reply(_build_reply_text(answer.text), mention_author=True))
        for emoji in (config.FEEDBACK_UP_EMOJI, config.FEEDBACK_DOWN_EMOJI):
            try:
                await sent.add_reaction(emoji)
            except discord.HTTPException:
                pass
        await db.log_answer(
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id, channel_name=channel_name,
            author_id=message.author.id, author_name=message.author.display_name,
            question=content, answer=answer.text,
            grounded=int(answer.grounded), message_id=sent.id,
        )
        log(f"Replied ({len(answer.text.split())} words, cited {answer.cited})", "ok")
    except discord.HTTPException as exc:
        log(f"Couldn't send reply: {exc}", "error")


async def _recent_messages(message: discord.Message) -> list[discord.Message]:
    out: list[discord.Message] = []
    try:
        async for m in message.channel.history(limit=config.CONTEXT_MESSAGE_LIMIT + 3):
            if m.id != message.id:
                out.append(m)
            if len(out) >= config.CONTEXT_MESSAGE_LIMIT:
                break
    except Exception as exc:
        log(f"Could not read channel history: {exc}", "warn")
    out.reverse()
    return out


async def _channel_context(message: discord.Message) -> str:
    return build_context(await _recent_messages(message), exclude_id=message.id)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    emoji = str(payload.emoji)
    if bot.user and payload.user_id == bot.user.id:
        return
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if not guild:
        return
    member = payload.member or guild.get_member(payload.user_id)
    if not member or member.bot:
        return

    if emoji in (config.FEEDBACK_UP_EMOJI, config.FEEDBACK_DOWN_EMOJI):
        rec = await db.get_by_message_id(payload.message_id)
        if rec is None:
            return
        vote = 1 if emoji == config.FEEDBACK_UP_EMOJI else -1
        up, down = await db.record_feedback_vote(payload.message_id, payload.user_id, vote)
        if vote < 0:
            log(f"Answer downvoted ({down}👎/{up}👍) — \"{rec['question'][:60]}\"", "warn")
            if down == config.FEEDBACK_DOWNVOTE_ALERT_THRESHOLD:
                db.append_jsonl(config.FLAGGED_LOG_PATH, {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "question": rec["question"][:500], "answer": rec["answer"][:1000],
                    "downvotes": down, "upvotes": up,
                })
                await notify_owner(f"⚠️ An answer reached {down} 👎 and may be wrong:\n"
                                   f"Q: {rec['question'][:200]}\nReview knowledge.txt.")
        return

    if emoji not in ("✅", "❌"):
        return
    is_admin = (member.name.lower() in config.PROTECTED_ADMINS
                or member.display_name.lower() in config.PROTECTED_ADMINS
                or member.guild_permissions.administrator)
    if not is_admin:
        return
    question = await db.mark_feedback(payload.message_id, correct=(emoji == "✅"))
    if question is None:
        return
    log(f"Answer {'confirmed' if emoji == '✅' else 'marked wrong'} by {member.display_name}", "ok")
    if emoji == "❌":
        try:
            channel = bot.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                await msg.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


# ── Commands (admin/owner only) ──────────────────────────────────────────────
def _is_admin_ctx(ctx: commands.Context) -> bool:
    if ctx.author.id == config.SIDEKICK_USER_ID:
        return True
    return isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    raise error


@bot.command(name="help")
@commands.check(_is_admin_ctx)
async def cdn_help(ctx):
    embed = discord.Embed(
        title=f"👋 {config.BOT_NAME} {config.CURRENT_VERSION}",
        description=("I read every channel and only answer when my local fact database "
                     "supports an answer. No facts = silence (and $0 spent)."),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Commands",
                    value="`!cdn help` · `!cdn ask <q>` · `!cdn facts` · `!cdn crawl` · "
                          "`!cdn status` · `!cdn history`", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="ask")
@commands.check(_is_admin_ctx)
async def cdn_ask(ctx, *, question: str):
    retrieved = retrieval.retrieve(question, facts_with_wipe())
    if not retrieved:
        await ctx.reply("No facts in my database match that question.", mention_author=True)
        return
    ans = await answering.generate_answer(
        client, question=question, facts=retrieved,
        context="(direct command)", channel_name=getattr(ctx.channel, "name", "unknown"))
    reply_text = _truncate_for_discord(ans.text) if ans else "My facts don't fully answer that."
    await ctx.reply(reply_text, mention_author=True)


@bot.command(name="facts")
@commands.check(_is_admin_ctx)
async def cdn_facts(ctx):
    import io
    fl = knowledge.facts()
    if not fl:
        await ctx.reply("No facts loaded. Try `!cdn crawl`.", mention_author=True)
        return
    body = "\n".join(f"[{f.id}]{'*' if f.manual else ''} {f.tag}: {f.text}  ({f.source})" for f in fl)
    buf = io.BytesIO(f"CDN_Captain facts — {len(fl)} total (* = manual)\n\n{body}".encode())
    await ctx.reply(f"📋 **{len(fl)} facts** loaded:", file=discord.File(buf, "cdn_facts.txt"),
                    mention_author=True)


@bot.command(name="crawl")
@commands.check(_is_admin_ctx)
async def cdn_crawl(ctx):
    msg = await ctx.send("🔍 Ingesting cdndayz.com — this takes a minute...")
    try:
        summary = await crawler.run_ingest(client, bot)
        await msg.edit(content=f"✅ {summary}")
    except Exception as exc:
        await msg.edit(content=f"❌ Ingest failed: {redact(str(exc))}")


@bot.command(name="status")
@commands.check(_is_admin_ctx)
async def cdn_status(ctx):
    n = len(knowledge.facts())
    manual = sum(1 for f in knowledge.facts() if f.manual)
    last = await knowledge.last_crawl_time()
    crawl_str = ("never" if not last
                 else f"{int((time.time() - last) / 3600)}h ago")
    up = int(time.time() - _bot_start_time)
    embed = discord.Embed(title=f"📊 {config.BOT_NAME} Status",
                          color=discord.Color.green() if n else discord.Color.red())
    embed.add_field(name="Facts", value=f"{n} loaded ({manual} manual)", inline=True)
    embed.add_field(name="Last crawl", value=crawl_str, inline=True)
    embed.add_field(name="Uptime", value=f"{up // 3600}h {(up % 3600) // 60}m", inline=True)
    embed.add_field(name="Model", value=config.ANSWER_MODEL, inline=False)
    embed.add_field(name="Paused", value=str(_bot_paused), inline=True)
    await ctx.send(embed=embed)


@bot.command(name="history")
@commands.check(_is_admin_ctx)
async def cdn_history(ctx):
    records = await db.recent_history(ctx.channel.id, limit=10)
    if not records:
        await ctx.send("No answers logged for this channel yet.")
        return
    lines = []
    for r in records:
        age = int(time.time() - r["timestamp"])
        ts = f"{age // 60}m ago" if age < 3600 else f"{age // 3600}h ago"
        fb = " ✅" if r["correct"] == 1 else (" ❌" if r["correct"] == 0 else "")
        lines.append(f"**[{ts}]** {r['author']}: *{r['question'][:80]}*{fb}")
    await ctx.send(embed=discord.Embed(title=f"📜 Recent answers in #{ctx.channel.name}",
                                       description="\n".join(lines),
                                       color=discord.Color.blurple()))


if __name__ == "__main__":
    problems = config.validate_config()
    if problems:
        log("Cannot start — fix these configuration problems:", "error")
        for p in problems:
            log(f"  • {p}", "error")
        sys.exit(1)
    bot.run(config.DISCORD_TOKEN)
