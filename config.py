"""Load .env + defaults for the freebuff GitHub-account farm toolset."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Directories
ACCOUNTS_FILE = ROOT / "accounts.txt"          # GitHub accounts: email:password:username
TOKENS_FILE = ROOT / "tokens.txt"              # freebuff authTokens (one per line)
FAILED_FILE = ROOT / "accounts.failed.txt"     # accounts that failed verification
STATE_FILE = ROOT / "state.json"               # batch state (resume support)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        os.environ.setdefault(key, val)


_load_dotenv(ROOT / ".env")


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def env_int(key: str, default: int) -> int:
    try:
        return int(env(key, str(default)) or default)
    except ValueError:
        return default


# IMAP (Gmail app password) — used to auto-collect GitHub verification codes
IMAP_HOST = env("IMAP_HOST", "imap.gmail.com")
IMAP_USER = env("IMAP_USER", "you@gmail.com")
IMAP_APP_PASSWORD = env("IMAP_APP_PASSWORD") or env("IMAP_PASS")

# Browser
DISPLAY = env("DISPLAY", ":99")
HEADLESS = env("HEADLESS", "true").lower() in ("1", "true", "yes", "on")