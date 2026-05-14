# 🤖 CDN_Captain — Discord Bot

> An AI-powered assistant that silently monitors every channel and answers questions automatically using cdndayz.com and the server's reference channel. It only speaks when it genuinely has a confident, sourced answer — and stays completely invisible otherwise.

---

## ✅ What It Can Do

| Feature | Details |
|---|---|
| 📡 **Full Channel Monitoring** | Watches every text channel and thread it has access to in real time |
| 🧠 **Auto Question Detection** | Detects questions, error reports, problem statements, and server-topic messages — not just messages ending in `?` |
| 🌐 **Full Website Crawl** | Crawls every page on cdndayz.com (up to 200 pages) using a real headless browser that renders JavaScript — dynamic content like wipe schedules is never missed |
| 🔄 **Auto-Refresh** | Re-crawls the website automatically every hour so information is always current without any manual action |
| 📋 **Reference Channel** | Reads up to 120 messages from the reference channel as a second knowledge source, refreshed every 30 minutes |
| 🤖 **Powered by Claude AI** | Uses Anthropic's Claude Sonnet — one of the most capable AI models available — to reason about questions and produce accurate, complete answers |
| 🧩 **Semantic Understanding** | Expands keywords before searching (e.g. "trader" also searches "exclusion zone", "safe zone", "market") so the right content surfaces even when phrasing differs |
| 📖 **Full Site Index** | Claude is given a map of every crawled page alongside the content, so it can reason across the entire website — not just the top results |
| 🗂️ **Structured Knowledge** | After every crawl, Claude extracts all concrete facts (rules, error codes, distances, donation tiers, server info) into a clean fact list. These are always passed to Claude first for faster, more precise answers |
| 📅 **Wipe Schedule Parser** | After every crawl, a dedicated pass calculates the exact next wipe date and time from today. Wipe questions always get a precise, calculated answer |
| 🔔 **Change Detection** | Every re-crawl diffs new content against old. If a page meaningfully changes (new rule, updated schedule, etc.), an alert is posted to a designated staff channel |
| 🖼️ **Screenshot Reading** | Reads and diagnoses error screenshots using Claude's vision — including error codes, message text, and any instructions visible in the image. Supports multiple screenshots in one message |
| 💬 **Deep Conversation Awareness** | Reads the last 75 messages for full context — knows who is talking to whom, and follows reply chains to understand what a message is replying to |
| 🔗 **Follow-up Awareness** | If someone replies to a bot answer with a follow-up question, the bot retrieves the original Q&A from its memory and answers in full context |
| 🎯 **Confidence Scoring** | Claude rates its own answer 1–10 before sending. If confidence is below 6, the bot stays silent instead of sending an uncertain answer |
| 🔇 **Smart Silence** | Returns nothing at all when it doesn't have a confident, sourced answer — no guessing, no vague suggestions, no "I don't know", no "open a ticket" |
| 👥 **Two-Person Convo Detection** | Stays out of active back-and-forth conversations between two people — but only if those messages are within the last 2 minutes |
| 🚫 **Admin Tag Protection** | If a non-admin tags a protected admin (`5pntjoe`, `strikezx`), the bot intercepts with a polite redirect to the website and ticket system. Admins can tag each other. Does NOT trigger when someone simply replies to an admin's message |
| ⏱️ **Spam Protection** | 30-second cooldown per user — won't flood the channel |
| 🔁 **Answer Deduplication** | If the bot itself already answered the same question in the last 5 minutes in the same channel, it won't repeat itself. If a human answered (even incorrectly), the bot will still step in with the correct answer |
| 💾 **Persistent Memory** | Every Q&A is stored permanently in a local SQLite database (`memory.db`). Survives restarts. Powers deduplication, history, follow-up awareness, and feedback tracking |
| 👍 **Admin Reaction Feedback** | Admins can react ❌ to any bot reply to mark it as wrong (bot deletes it automatically) or ✅ to confirm it's correct. Only protected admins trigger this |
| 🎨 **Tone Matching** | Casual channels (general, lounge, banter) get a relaxed, friendly tone. Help and rules channels get a clear, professional tone |
| 📌 **Channel Awareness** | Knows which channel it's active in and factors that into its responses |
| 🔢 **Strict Error Code Matching** | Only ever responds about the exact error code mentioned — never substitutes a similar one |
| 🔁 **Rate Limit Retry** | All replies use exponential backoff — no answer is ever silently dropped due to Discord rate limits |
| 🐕 **Auto-Restart Watchdog** | The bot runs inside a watchdog script that automatically restarts it if it crashes, up to 10 times per 5-minute window |

---

## 🧠 How It Decides Whether to Answer

CDN_Captain uses a single Claude AI call that **both** decides whether to answer **and** generates the response. Before sending, Claude rates its own confidence 1–10. Below 6 = silent.

It will answer if:
- The website or reference channel directly answers the question
- A rule or policy applies to the specific scenario described — even if exact numbers differ (e.g. someone asks about building 420m from a trader; the bot knows the 1,000m rule and correctly tells them they're in violation)
- A screenshot contains diagnosable content related to DayZ or the server
- It can reason from the available info to give a genuinely useful, confident response

It stays **completely silent** if:
- The topic isn't covered by its sources at all
- Confidence in the answer is below 6/10
- Two people are actively chatting (within the last 2 minutes)
- It's pure casual chat or banter with no question being asked
- A human already gave a complete answer moments ago
- The message has nothing to do with DayZ or this server

---

## 💬 Commands

| Command | Description |
|---|---|
| `!cdn help` | Shows a help card with bot info and knowledge base stats |
| `!cdn ask <question>` | Force the bot to answer any question, bypassing all filters |
| `!cdn ping` | Health check — shows latency, uptime, memory, crawl age, DB size, structured facts count, and wipe schedule |
| `!cdn history` | Shows the last 10 answers the bot gave in the current channel, including confidence scores and admin feedback |
| `!cdn crawl` | Manually trigger a fresh re-crawl of cdndayz.com |
| `!cdn status` | Shows crawl age, reference channel age, model, context size, and auto-crawl schedule |

---

## 👍 Admin Feedback (Reaction System)

Any protected admin (`5pntjoe`, `strikezx`) can react to a CDN_Captain reply to give feedback:

| Reaction | Effect |
|---|---|
| ❌ | Marks the answer as **wrong** in the database and **deletes the bot's reply** from the channel |
| ✅ | Marks the answer as **correct** in the database |

This feedback is stored permanently and visible via `!cdn history`.

---

## 🔔 Change Detection Setup

To receive alerts when the website updates, set `CHANGE_ALERT_CHANNEL_ID` in `bot.py` to the ID of your staff or log channel:

```python
CHANGE_ALERT_CHANNEL_ID = 123456789012345678  # your channel ID here
```

Leave it as `None` to disable alerts.

---

## 📋 Required Bot Permissions

For CDN_Captain to work correctly, it needs the following permissions in your server:

- **View Channels**
- **Send Messages**
- **Read Message History**
- **Embed Links**
- **Manage Messages** *(required to delete wrong answers when admin reacts ❌)*

> If certain channels are restricted, manually grant the CDN_Captain role access to those channels.

---

## 🖥️ Hosting & Running

CDN_Captain runs locally on a Windows machine. Use the watchdog for automatic crash recovery:

```
python watchdog.py
```

To run without the watchdog (not recommended):
```
python bot.py
```

As long as the machine is on and the script is running, the bot is active. If the machine is turned off or the script is closed, the bot goes offline.

The bot creates a `memory.db` file in the same folder on first run — this is its persistent memory and should not be deleted.

---

*Powered by [Claude AI](https://anthropic.com) · Knowledge sourced from [cdndayz.com](https://cdndayz.com)*
