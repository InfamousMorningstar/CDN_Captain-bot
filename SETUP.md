# Beautiful_Joe — Setup Guide

## 1. Prerequisites

- Python 3.10 or higher installed on your computer
- Your **Discord Bot Token** (from Discord Developer Portal)
- Your **Anthropic API Key** (from console.anthropic.com)

---

## 2. Install Dependencies

Open a terminal in the folder containing `bot.py` and run:

```bash
pip install -r requirements.txt
```

---

## 3. Create Your `.env` File

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Then open `.env` and replace the placeholder values:

```
DISCORD_TOKEN=paste_your_discord_token_here
ANTHROPIC_API_KEY=paste_your_anthropic_key_here
ANTHROPIC_MAIN_MODEL=claude-sonnet-4-6
ANTHROPIC_CHEAP_MODEL=claude-3-5-haiku-latest
```

`ANTHROPIC_MAIN_MODEL` handles the real user-facing answers.
`ANTHROPIC_CHEAP_MODEL` handles the cheaper background tasks and is the main cost-saving knob.

---

## 4. Enable Required Intents in Discord Developer Portal

This is **critical** — the bot cannot read messages without this step.

1. Go to https://discord.com/developers/applications
2. Select your bot application
3. Click **Bot** in the left sidebar
4. Scroll to **Privileged Gateway Intents**
5. Enable **MESSAGE CONTENT INTENT**
6. Save changes

---

## 5. Generate the Invite Link (for the Server Admin)

The server admin needs this link to add Beautiful_Joe to their server.

1. In the Discord Developer Portal, go to your app → **OAuth2 → URL Generator**
2. Under **Scopes**, check:
   - `bot`
   - `applications.commands`
3. Under **Bot Permissions**, check:
   - `View Channels`
   - `Read Message History`
   - `Send Messages`
   - `Add Reactions`
4. Copy the generated URL and send it to the server admin

---

## 6. Run the Bot

```bash
python bot.py
```

You should see:

```
✅  Beautiful_Joe#XXXX (Beautiful_Joe) is online!
   Watching 1 server(s)
   → YourServerName (123456789)
```

The bot will now monitor all channels it has access to and automatically answer questions.

---

## 7. How It Works

- **Auto-detect:** Beautiful_Joe watches every message in every channel it can see. If a message ends with `?` or starts with a question word (what, how, why, when, who, can, etc.), it triggers a response.
- **Context:** Before answering, it fetches the latest content from cdndayz.com (cached for 10 minutes) and the last 15 messages from the channel.
- **Claude:** Both sources are sent to Claude, which generates a friendly, accurate answer.
- **Cooldown:** Each user has a 30-second cooldown to prevent spam.

---

## 8. Commands

| Command | Description |
|---|---|
| `!joe help` | Show the help card |
| `!joe ask <question>` | Force an answer for any question |

---

## 9. Keeping the Bot Running 24/7

Since you're running locally, the bot only works while your computer is on and the terminal is open.

To keep it running in the background on Windows:

```bash
start /B python bot.py
```

Or use a tool like **PM2** (Node.js-based process manager that works with Python):

```bash
npm install -g pm2
pm2 start bot.py --interpreter python3 --name beautiful-joe
pm2 save
pm2 startup
```

---

## Troubleshooting

**Bot is online but not responding:**
- Make sure **Message Content Intent** is enabled in the Developer Portal (Step 4)
- Check that the bot has View Channels + Read Message History permissions in the server

**`DISCORD_TOKEN is not set` error:**
- Make sure you created `.env` (not just `.env.example`) and filled in the values

**`anthropic` or `discord` not found:**
- Run `pip install -r requirements.txt` again
