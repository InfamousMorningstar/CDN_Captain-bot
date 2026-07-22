FROM python:3.12-slim

WORKDIR /app

# System deps required by Playwright's Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (cached layer unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium and its system dependencies via Playwright
RUN playwright install --with-deps chromium

# Source is bind-mounted at runtime — no COPY needed for bot files.
# This keeps the image lean and lets the watchdog's self-updater
# write new bot.py / watchdog.py directly to the mounted directory.

ENV PYTHONUNBUFFERED=1

CMD ["python", "watchdog.py"]
