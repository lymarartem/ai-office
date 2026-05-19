import os
import logging
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY          = os.getenv("OPENROUTER_API_KEY")
CEO_BOT_TOKEN               = os.getenv("CEO_BOT_TOKEN")
DEVELOPER_BOT_TOKEN         = os.getenv("DEVELOPER_BOT_TOKEN")
MARKETING_BOT_TOKEN         = os.getenv("MARKETING_BOT_TOKEN")
DESIGNER_BOT_TOKEN          = os.getenv("DESIGNER_BOT_TOKEN")
TERMINAL_BOT_TOKEN          = os.getenv("TERMINAL_BOT_TOKEN")
BROWSER_BOT_TOKEN           = os.getenv("BROWSER_BOT_TOKEN")
GROUP_CHAT_ID               = os.getenv("GROUP_CHAT_ID")
OWNER_TELEGRAM_ID           = os.getenv("OWNER_TELEGRAM_ID")
DASHBOARD_PORT              = int(os.getenv("DASHBOARD_PORT", "8080"))
DISCUSSION_INTERVAL_MINUTES = int(os.getenv("DISCUSSION_INTERVAL_MINUTES", "30"))

OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"
MODEL_CEO       = "meta-llama/llama-3.3-70b-instruct:free"
MODEL_DEVELOPER = "meta-llama/llama-3.3-70b-instruct:free"
MODEL_MARKETING = "meta-llama/llama-3.3-70b-instruct:free"
MODEL_DESIGNER  = "meta-llama/llama-3.3-70b-instruct:free"
MODEL_TERMINAL  = "meta-llama/llama-3.3-70b-instruct:free"
MODEL_BROWSER   = "meta-llama/llama-3.3-70b-instruct:free"

_required = {
    "OPENROUTER_API_KEY":   OPENROUTER_API_KEY,
    "CEO_BOT_TOKEN":        CEO_BOT_TOKEN,
    "DEVELOPER_BOT_TOKEN":  DEVELOPER_BOT_TOKEN,
    "MARKETING_BOT_TOKEN":  MARKETING_BOT_TOKEN,
    "DESIGNER_BOT_TOKEN":   DESIGNER_BOT_TOKEN,
    "TERMINAL_BOT_TOKEN":   TERMINAL_BOT_TOKEN,
    "BROWSER_BOT_TOKEN":    BROWSER_BOT_TOKEN,
    "GROUP_CHAT_ID":        GROUP_CHAT_ID,
    "OWNER_TELEGRAM_ID":    OWNER_TELEGRAM_ID,
}

for _key, _val in _required.items():
    if not _val:
        raise EnvironmentError(f"❌ Не найдена переменная: {_key}")

GROUP_CHAT_ID     = int(GROUP_CHAT_ID)
OWNER_TELEGRAM_ID = int(OWNER_TELEGRAM_ID)
