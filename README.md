<div align="center">

# 🤖 CDN_Captain

**AI-powered Discord bot that silently monitors every channel and answers questions automatically.**  
Powered by Claude Sonnet · Sourced from cdndayz.com · Stays completely invisible unless it has a real, confident answer.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3%2B-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Claude AI](https://img.shields.io/badge/Claude-Sonnet-D97706?style=for-the-badge&logo=anthropic&logoColor=white)](https://anthropic.com)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)

[🌐 Website](https://InfamousMorningstar.github.io/CDN_Captain-bot-) · [📦 Download .exe](https://github.com/InfamousMorningstar/CDN_Captain-bot-/releases/latest) · [📋 Changelog](#)

</div>

---

## What is CDN_Captain?

CDN_Captain is a fully autonomous AI assistant for the **CDNDayz DayZ community server**. It watches every channel and thread, detects unanswered questions, and responds only when it has a **confident, sourced answer** from the website or reference channel. If it doesn't know — it says nothing.

No noise. No guessing. No "open a ticket." Either an instant, accurate answer, or total silence.

---

## ✅ Features

### 🌐 Knowledge & Crawling
| Feature | Detail |
|---|---|
| **Full Site Crawl** | Crawls every page on cdndayz.com (up to 200 pages) using a real headless Chromium browser — renders JavaScript so dynamic content like wipe schedules is never missed |
| **Auto-Refresh** | Re-crawls automatically every hour — always current, zero manual action |
| **Reference Channel** | Reads up to 120 messages from the server's reference channel as a second knowledge source, refreshed every 30 minutes |
| **Structured Knowledge** | After every crawl, Claude extracts all concrete facts (rules, error codes, distances, donation tiers) into a clean indexed fact list |
| **Wipe Schedule Parser** | After every crawl, a dedicated AI pass calculates the exact next wipe date and time from today |
| **Change Detection** | Every re-crawl diffs against the previous content — if a page meaningfully changes, an alert is posted to a designated staff channel |
| **Full Site Index** | Claude receives a map of every crawled page alongside content, so it can reason across the entire website — not just the top results |

### 🧠 Intelligence
| Feature | Detail |
|---|---|
| **Split Model Routing** | Uses a stronger Claude model for user-facing answers and a cheaper model for background extraction, wipe parsing, and owner-mode replies |
| **Semantic Understanding** | Expands keywords before searching — "trader" also searches "exclusion zone, safe zone, market" so the right content surfaces even when phrasing differs |
| **TF-IDF Scoring** | Scores page relevance using term frequency-inverse document frequency, with exact hex error code matching getting a massive ranking bonus |
| **Auto Question Detection** | Detects questions, error reports, problem statements, and server-topic messages — not just messages ending in `?` |
| **Confidence Scoring** | Claude rates its own answer 1–10 before sending. Below 6 = silent instead of uncertain |

### 💬 Conversation Awareness
| Feature | Detail |
|---|---|
| **Deep Context** | Reads the last 75 messages for full context — knows who is talking to whom, follows reply chains |
| **Follow-up Awareness** | If someone replies to a bot answer with a follow-up, the bot retrieves the original Q&A from memory and answers in full context |
| **Two-Person Detection** | Stays out of active back-and-forth conversations between two people (within the last 2 minutes) |
| **Smart Silence** | No guessing, no vague suggestions, no "I don't know", no "open a ticket" — either useful or completely invisible |
| **🖼️ Screenshot Reading** | Reads and diagnoses error screenshots using Claude's vision — including error codes, message text, and instructions. Supports multiple screenshots per message |

### 🛡️ Admin & Safety
| Feature | Detail |
|---|---|
| **Admin Reaction Feedback** | Admins react ❌ to mark an answer wrong (bot deletes it automatically) or ✅ to confirm correct. Only protected admins trigger this |
| **Admin Tag Protection** | If a non-admin tags a protected admin, the bot intercepts with a polite redirect to the website and ticket system. Admins can tag each other normally |
| **Spam Protection** | 30-second per-user cooldown — won't flood any channel |
| **Answer Deduplication** | Won't repeat the same answer in the same channel within 5 minutes |
| **Rate Limit Retry** | All replies use exponential backoff — no answer is ever silently dropped |
| **Sidekick Mode** | Owner-only personal assistant — bypasses all filters, answers anything, toggleable via natural language |
| **Tamper-proof Pause** | Bot pause state is HMAC-signed with the Discord token — can't be faked by editing the database |

### 💾 Persistence
| Feature | Detail |
|---|---|
| **SQLite Memory** | Every Q&A is stored permanently in `memory.db` — survives restarts, powers dedup, history, follow-ups, and feedback |
| **Persistent Pause State** | Pause/resume state survives bot restarts — stored with cryptographic signature |
| **Auto-restart Watchdog** | `watchdog.py` automatically restarts the bot on crash, up to 10 times per 5-minute window |

---

## 💬 Commands

All commands use the `!cdn` prefix.

| Command | Description |
|---|---|
| `!cdn help` | Shows a help card with bot info and current knowledge base stats |
| `!cdn ask <question>` | Force the bot to answer any question, bypassing all auto-filters |
| `!cdn ping` | Health check — latency, uptime, memory usage, crawl age, DB size, structured facts count, and wipe schedule |
| `!cdn history` | Shows the last 10 answers the bot gave in the current channel, including confidence scores and admin feedback |
| `!cdn crawl` | Manually trigger a fresh re-crawl of cdndayz.com |
| `!cdn status` | Shows crawl age, reference channel age, model, context size, and auto-crawl schedule |

---

## 👍 Admin Feedback

Any protected admin (`5pntjoe`, `strikezx`) can react to a CDN_Captain reply:

| Reaction | Effect |
|---|---|
| ❌ | Marks the answer as **wrong** in the database and **deletes the bot's reply** from the channel |
| ✅ | Marks the answer as **correct** in the database |

Feedback is stored permanently and visible via `!cdn history`.

---

## 📋 Required Bot Permissions

| Permission | Why |
|---|---|
| View Channels | Monitor channels for questions |
| Send Messages | Reply to questions |
| Read Message History | Load conversation context (75 messages) |
| Embed Links | Send formatted embeds for commands |
| Manage Messages | Delete wrong answers when admin reacts ❌ |

> If certain channels are restricted, manually grant the CDN_Captain role access.

---

## 🖥️ Installation

### Optional cost controls

You can override the Anthropic models in `.env`:

```env
ANTHROPIC_MAIN_MODEL=claude-sonnet-4-6
ANTHROPIC_CHEAP_MODEL=claude-3-5-haiku-latest
```

Keep the stronger model on `ANTHROPIC_MAIN_MODEL` for normal server answers. Set `ANTHROPIC_CHEAP_MODEL` to your lowest-cost Anthropic model for background tasks.

### Option A — Download the .exe (Recommended)

1. Go to [**Releases**](https://github.com/InfamousMorningstar/CDN_Captain-bot-/releases/latest) and download `CDN_Captain.exe`
2. Double-click it — the installer opens
3. Enter your **Anthropic API key** ([get one here](https://console.anthropic.com))
4. Click **Install & Start Bot**

The installer will:
- Auto-download and install Python if not found
- Download all bot files from this repo
- Install all Python dependencies
- Install the Playwright Chromium browser
- Write your credentials to `.env`
- Launch the bot automatically

Everything installs to `~/CDN_Captain/` in your home directory.

---

### Option B — Run from Source

**Prerequisites:** Python 3.10+, pip

```bash
# 1. Clone the repo
git clone https://github.com/InfamousMorningstar/CDN_Captain-bot-.git
cd CDN_Captain-bot-

# 2. Run the setup script (installs all dependencies)
setup.bat

# 3. Create your .env file
# (setup.bat will prompt you if it doesn't exist)
```

Create a `.env` file in the project folder:

```env
DISCORD_TOKEN=your_discord_bot_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

Start the bot with auto-restart (recommended):

```bash
python watchdog.py
```

Or run directly (no watchdog):

```bash
python bot.py
```

---

## ⚙️ Configuration

All configuration is at the top of `bot.py`:

| Variable | Default | Description |
|---|---|---|
| `USER_COOLDOWN_SECONDS` | `30` | Seconds between responses to the same user |
| `CONTEXT_MESSAGE_LIMIT` | `75` | How many messages to load as conversation context |
| `MAX_PAGES_TO_CRAWL` | `200` | Maximum pages to crawl per run |
| `CRAWL_CONCURRENCY` | `4` | Parallel browser tabs during crawl |
| `AUTO_CRAWL_INTERVAL` | `3600` | Seconds between automatic re-crawls (1 hour) |
| `TOP_PAGES_FOR_ANSWER` | `12` | How many top-scored pages to feed Claude |
| `CHARS_PER_PAGE` | `5000` | Max characters extracted per crawled page |
| `REFERENCE_CHANNEL_ID` | *(set)* | Discord channel ID for the reference channel |
| `REFERENCE_CHANNEL_MSG_LIMIT` | `120` | Max messages to read from reference channel |
| `REF_CHANNEL_CACHE_TTL` | `1800` | Seconds before re-fetching reference channel (30 min) |
| `CHANGE_ALERT_CHANNEL_ID` | `None` | Channel ID for website change alerts (set to enable) |
| `PROTECTED_ADMINS` | `{"5pntjoe", "strikezx"}` | Usernames protected from direct tagging |
| `ANSWER_DEDUP_TTL` | `300` | Seconds before the same question can be answered again |
| `SIDEKICK_USER_ID` | *(set)* | Discord user ID for the bot's owner (sidekick mode) |

### Change Alert Setup

To receive alerts when cdndayz.com updates, set this in `bot.py`:

```python
CHANGE_ALERT_CHANNEL_ID = 123456789012345678  # your staff channel ID
```

Leave as `None` to disable.

---

## 🔨 Building the .exe

The `.exe` bundles the installer GUI with a pre-embedded Discord token so admins only need to enter their Anthropic API key.

```bash
# 1. Open build_exe.bat and set your Discord token
# 2. Run it
build_exe.bat
```

The output `CDN_Captain.exe` is ready to distribute.

> **Never commit `build_exe.bat` with a real token inside it.** Add it to `.gitignore` or always use a placeholder.

---

## 🏗️ Architecture

```
CDN_Captain
├── bot.py              — Main bot: Discord events, Claude integration, all logic
├── watchdog.py         — Crash recovery: auto-restarts bot.py on failure
├── launcher.py         — GUI installer: tkinter app for end-user setup
├── build_exe.bat       — Bundles launcher.py into a standalone .exe
├── setup.bat           — Source install: Python packages + Playwright
├── requirements.txt    — Python dependencies
└── memory.db           — (runtime) SQLite: Q&A history, admin feedback, state
```

**Request flow:**

```
Discord message
    │
    ├─ mentions admin?          → intercept with redirect
    ├─ sidekick trigger?        → owner-only personal assistant path
    ├─ bot paused?              → silent
    ├─ message too old?         → skip
    ├─ not a question?          → skip
    ├─ directed at someone?     → skip
    ├─ user on cooldown?        → skip
    ├─ duplicate question?      → skip (DB check)
    │
    ├─ fetch 75 messages context
    ├─ check two-person convo
    ├─ fetch reply chain
    ├─ crawl website (cached)
    ├─ fetch reference channel (cached)
    ├─ download images if any
    ├─ TF-IDF score all pages → top 12 pages
    │
    └─ Claude call (single, decides + answers)
            │
            ├─ CONFIDENCE ≥ 6  → reply + log to DB
            └─ CONFIDENCE < 6  → silent
```

---

## 🔑 API Keys

| Key | Where to get it |
|---|---|
| Discord Bot Token | [discord.com/developers](https://discord.com/developers/applications) → Your App → Bot → Reset Token |
| Anthropic API Key | [console.anthropic.com](https://console.anthropic.com) → API Keys → Create Key |

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">

Powered by [Claude AI](https://anthropic.com) · Knowledge sourced from [cdndayz.com](https://cdndayz.com)

</div>
