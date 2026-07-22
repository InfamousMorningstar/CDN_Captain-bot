# CDN_Captain v2

Retrieval-first Discord helper bot for the CDNDayz community.

## How it works
1. **Weekly ingest:** crawls cdndayz.com (Playwright), extracts facts with Claude
   Haiku from *changed pages only*, stores them in `facts.db`. Your hand-written
   `knowledge.txt` always overrides crawled facts.
2. **Free retrieval gate:** every message is scored locally against the fact DB.
   No matching facts → the bot stays silent and spends $0.
3. **One small answer call:** Haiku 4.5 answers from the matched facts only and must
   cite fact IDs. Citations are verified in code; an independent grounding check is
   enforced. Anything unverifiable is suppressed and logged to
   `suppressed_answers.jsonl` as a knowledge gap to backfill.

## Run locally
    pip install -r requirements.txt
    playwright install chromium
    cp .env.example .env   # fill in DISCORD_TOKEN + ANTHROPIC_API_KEY
    python bot.py

## Run on TrueNAS (Docker)
    docker build -t cdn-captain .
    docker run -d --name cdn-captain \
      --env-file .env \
      -v /mnt/pool/cdn-captain:/data \
      --restart unless-stopped \
      cdn-captain

First boot with an empty `/data` triggers a full site ingest (~a minute, well under
$1 of API credit), then it refreshes weekly. `!cdn crawl` forces a refresh.

## Commands (admin/owner)
`!cdn help` · `!cdn ask <q>` · `!cdn facts` · `!cdn crawl` · `!cdn status` · `!cdn history`

## Feedback loop
- Anyone: 👍/👎 on an answer. 3× 👎 alerts the owner and logs the answer.
- Admins: ✅ confirms an answer, ❌ marks it wrong **and deletes it**.
- `suppressed_answers.jsonl` + `flagged_answers.jsonl` = your TODO list for
  `knowledge.txt` additions.

## Tests
    python -m pytest tests/ -v                       # offline, free
    RUN_GOLDEN_LIVE=1 python tests/run_golden_live.py  # live pipeline, costs tokens
