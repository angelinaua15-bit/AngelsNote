import hashlib
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
BOT_SECRET = os.environ.get("BOT_SECRET", "")
DEFAULT_TZ = "Europe/Kyiv"
# 1 = only the first person who presses /start can use the bot
PRIVATE = os.environ.get("PRIVATE", "1") == "1"


def derived(name: str) -> str:
    return hashlib.sha256(f"{BOT_SECRET}:{name}".encode()).hexdigest()[:40]


WEBHOOK_SECRET = derived("webhook")
CRON_SECRET = derived("cron")
