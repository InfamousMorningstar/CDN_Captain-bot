"""Coloured console logging with secret redaction. Optional plain-text LOG_FILE mirror."""
from datetime import datetime, timezone

import config

_RST, _BOLD = "\033[0m", "\033[1m"
_GRN, _YLW, _RED, _CYN, _BLU, _GRY, _WHT = (
    "\033[92m", "\033[93m", "\033[91m", "\033[96m", "\033[94m", "\033[90m", "\033[97m",
)

_LEVEL = {
    "ok":    ("✓", _GRN, _WHT),
    "warn":  ("!", _YLW, _YLW),
    "error": ("✗", _RED, _RED),
    "info":  ("•", _CYN, _WHT),
    "skip":  ("·", _GRY, _GRY),
    "msg":   ("►", _BLU, _CYN),
    "crawl": ("↻", _YLW, _WHT),
}


def redact(text: str) -> str:
    """Strip known secrets from any string before it reaches a log/console."""
    for secret in (config.DISCORD_TOKEN, config.ANTHROPIC_API_KEY):
        if secret and secret in text:
            text = text.replace(secret, "***redacted***")
    return text


def log(msg: str, level: str = "info") -> None:
    msg = redact(msg)
    icon, icol, tcol = _LEVEL.get(level, ("·", _GRY, _WHT))
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  {_GRY}{ts}{_RST}  {icol}{icon}{_RST}  {tcol}{msg}{_RST}")
    if config.LOG_FILE:
        try:
            with open(config.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} [{level.upper():<5}] {msg}\n")
        except Exception:
            pass  # logging must never crash the bot
