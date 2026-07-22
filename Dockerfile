FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium + system deps for the weekly Playwright crawl
RUN playwright install --with-deps chromium

COPY config.py logging_util.py db.py knowledge.py retrieval.py answering.py crawler.py bot.py knowledge.txt ./

ENV PYTHONUNBUFFERED=1

# facts.db / memory.db / *.jsonl live in /data (mount a volume there)
ENV FACTS_DB_PATH=/data/facts.db \
    MEMORY_DB_PATH=/data/memory.db \
    SUPPRESSED_LOG_PATH=/data/suppressed_answers.jsonl \
    FLAGGED_LOG_PATH=/data/flagged_answers.jsonl
VOLUME /data

CMD ["python", "bot.py"]
