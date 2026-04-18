"""
CDN_Captain Watchdog
Keeps the bot running — restarts it if it crashes, and silently auto-updates
bot.py and watchdog.py from GitHub whenever a new release is published.
Run this instead of bot.py directly.
"""

import subprocess
import sys
import time
import os
import json
import urllib.request
from datetime import datetime, timezone

# ─────────────────────────────────────────────
#  Version & update config
# ─────────────────────────────────────────────
CURRENT_VERSION     = "v1.2.3"
GITHUB_API          = "https://api.github.com/repos/InfamousMorningstar/CDN_Captain-bot/releases/latest"
RAW_BASE_TMPL       = "https://raw.githubusercontent.com/InfamousMorningstar/CDN_Captain-bot/{tag}"
UPDATE_FILES        = ["bot.py", "watchdog.py", "requirements.txt"]
UPDATE_CHECK_EVERY  = 3600   # re-check for updates every hour (seconds)

# ─────────────────────────────────────────────
#  Watchdog config
# ─────────────────────────────────────────────
BOT_SCRIPT      = "bot.py"
RESTART_DELAY   = 5     # seconds between crash restarts
MAX_RESTARTS    = 10    # max restarts within RESTART_WINDOW before giving up
RESTART_WINDOW  = 300   # 5-minute crash window
LOG_FILE        = "watchdog.log"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(BASE_DIR, "watchdog.pid")

# ─────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────
def log(msg: str) -> None:
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(os.path.join(BASE_DIR, LOG_FILE), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ─────────────────────────────────────────────
#  Auto-updater
# ─────────────────────────────────────────────
def _read_github_token() -> str:
    """Read GITHUB_TOKEN from the .env file in BASE_DIR, if present."""
    env_path = os.path.join(BASE_DIR, ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GITHUB_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _fetch_latest_release() -> dict | None:
    """Hit the GitHub Releases API and return the JSON payload, or None on failure."""
    try:
        headers = {
            "Accept":     "application/vnd.github+json",
            "User-Agent": f"CDN-Captain-Watchdog/{CURRENT_VERSION}",
        }
        token = _read_github_token()
        if token:
            headers["Authorization"] = f"token {token}"
        req = urllib.request.Request(GITHUB_API, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log(f"⚠️  Could not reach GitHub to check for updates: {exc}")
        return None


def check_and_apply_update() -> bool:
    """
    Compare the latest GitHub release tag against CURRENT_VERSION.
    If newer: download all UPDATE_FILES from GitHub raw, replace local copies,
    run pip install if requirements.txt changed, and return True if watchdog.py
    itself was updated (so the caller can restart the watchdog process).
    Returns False when already up to date or on any failure.
    """
    data = _fetch_latest_release()
    if not data:
        return False

    latest_tag = data.get("tag_name", "").strip()
    if not latest_tag or latest_tag == CURRENT_VERSION:
        return False   # already on the latest version

    log(f"⬆️  New version available: {latest_tag}  (running {CURRENT_VERSION})")
    log("   Downloading updates in the background — bot will restart once ready...")

    watchdog_updated      = False
    requirements_updated  = False

    raw_base = RAW_BASE_TMPL.format(tag=latest_tag)
    for fname in UPDATE_FILES:
        url  = f"{raw_base}/{fname}"
        dest = os.path.join(BASE_DIR, fname)
        tmp  = dest + ".new"
        bak  = dest + ".bak"

        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                content = resp.read()

            # Verify watchdog.py actually contains the expected version before
            # applying it — guards against CDN serving a stale/cached file which
            # would cause an infinite update-restart loop.
            if fname == "watchdog.py":
                content_str = content.decode("utf-8", errors="replace")
                expected = f'CURRENT_VERSION     = "{latest_tag}"'
                if expected not in content_str:
                    log(f"   ⚠️  Downloaded watchdog.py does not contain {latest_tag} "
                        f"(CDN may be stale) — aborting update to prevent loop")
                    # Clean up temp if it exists
                    if os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                    return False

            # Write to a temp file first — never leave a half-written script
            with open(tmp, "wb") as f:
                f.write(content)

            # Rotate: old → .bak, new → current
            if os.path.exists(bak):
                os.remove(bak)
            if os.path.exists(dest):
                os.rename(dest, bak)
            os.rename(tmp, dest)

            log(f"   ✔ {fname} updated")

            if fname == "watchdog.py":
                watchdog_updated = True
            if fname == "requirements.txt":
                requirements_updated = True

        except Exception as exc:
            log(f"   ⚠️  Could not update {fname}: {exc}")
            # Clean up temp file so a bad download doesn't corrupt the install
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # Re-run pip if dependencies changed
    if requirements_updated:
        log("   Installing any new dependencies...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r",
                 os.path.join(BASE_DIR, "requirements.txt"), "--quiet"],
                check=False,
            )
            log("   ✔ Dependencies up to date")
        except Exception as exc:
            log(f"   ⚠️  pip install failed: {exc}")

    log(f"✅ Updated to {latest_tag}")
    return watchdog_updated


# ─────────────────────────────────────────────
#  Main loop
# ─────────────────────────────────────────────
def main() -> None:
    python   = sys.executable
    script   = os.path.join(BASE_DIR, BOT_SCRIPT)
    restarts: list[float] = []
    last_update_check     = 0.0

    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log(f"  CDN_Captain Watchdog  ·  {CURRENT_VERSION}")
    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Write PID so the installer can kill this process before launching a new one
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    while True:
        now = time.time()

        # ── Update check (on startup and every UPDATE_CHECK_EVERY seconds) ──
        if now - last_update_check >= UPDATE_CHECK_EVERY:
            last_update_check = now
            watchdog_changed = check_and_apply_update()
            if watchdog_changed:
                # watchdog.py itself was replaced — spawn the new version and exit
                log("🔄 Watchdog updated — restarting with new version...")
                subprocess.Popen([python, os.path.join(BASE_DIR, "watchdog.py")])
                sys.exit(0)

        # ── Crash-loop guard ─────────────────────────────────────────────────
        restarts = [t for t in restarts if now - t < RESTART_WINDOW]
        if len(restarts) >= MAX_RESTARTS:
            log(f"❌ Too many crashes ({MAX_RESTARTS} in {RESTART_WINDOW}s) — stopping.")
            log("   Fix the error above and restart the watchdog manually.")
            sys.exit(1)

        # ── Start the bot ────────────────────────────────────────────────────
        attempt = len(restarts) + 1
        log(f"🚀 Starting bot.py  (run #{attempt} in window)...")
        start_time = time.time()

        try:
            proc        = subprocess.run([python, script], check=False)
            exit_code   = proc.returncode
            run_seconds = int(time.time() - start_time)

            if exit_code == 0:
                log(f"✅ Bot exited cleanly after {run_seconds}s — watchdog stopping.")
                break
            else:
                log(f"⚠️  Bot crashed (exit code {exit_code}) after {run_seconds}s")
                restarts.append(time.time())
                log(f"   Restarting in {RESTART_DELAY}s...  ({len(restarts)}/{MAX_RESTARTS} crashes in window)")
                time.sleep(RESTART_DELAY)

        except KeyboardInterrupt:
            log("🛑 Stopped by user (Ctrl+C)")
            break
        except Exception as exc:
            log(f"❌ Watchdog error: {exc}")
            restarts.append(time.time())
            time.sleep(RESTART_DELAY)

    # Clean up PID file on exit
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass


if __name__ == "__main__":
    main()
