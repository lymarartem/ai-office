import os
import logging
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

logger = logging.getLogger(__name__)

GEMINI_API_KEY              = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY                = os.getenv("GROQ_API_KEY")
CEO_BOT_TOKEN               = os.getenv("CEO_BOT_TOKEN")
DEVELOPER_BOT_TOKEN         = os.getenv("DEVELOPER_BOT_TOKEN")
MARKETING_BOT_TOKEN         = os.getenv("MARKETING_BOT_TOKEN")
DESIGNER_BOT_TOKEN          = os.getenv("DESIGNER_BOT_TOKEN")
TERMINAL_BOT_TOKEN          = os.getenv("TERMINAL_BOT_TOKEN")
BROWSER_BOT_TOKEN           = os.getenv("BROWSER_BOT_TOKEN")
GROUP_CHAT_ID               = os.getenv("GROUP_CHAT_ID")
OWNER_TELEGRAM_ID           = os.getenv("OWNER_TELEGRAM_ID")
DASHBOARD_PORT              = int(os.getenv("DASHBOARD_PORT", "8080"))
DISCUSSION_INTERVAL_MINUTES = int(os.getenv("DISCUSSION_INTERVAL_MINUTES", "180"))

# GitHub Issues — опционально (если не задано, команда /issue сообщит об этом)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO  = os.getenv("GITHUB_REPO", "")  # формат: owner/repo

# Hybrid LLM: Gemini primary + Groq fallback. Оба OpenAI-совместимые.
PRIMARY_API_URL  = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
PRIMARY_MODEL    = "gemini-2.0-flash"

FALLBACK_API_URL = "https://api.groq.com/openai/v1/chat/completions"
FALLBACK_MODEL   = "llama-3.3-70b-versatile"

# Backward compat — агенты импортят MODEL_* как primary
MODEL_CEO       = PRIMARY_MODEL
MODEL_DEVELOPER = PRIMARY_MODEL
MODEL_MARKETING = PRIMARY_MODEL
MODEL_DESIGNER  = PRIMARY_MODEL
MODEL_TERMINAL  = PRIMARY_MODEL
MODEL_BROWSER   = PRIMARY_MODEL

# Backward compat — старый код мог импортить LLM_API_URL
LLM_API_URL = PRIMARY_API_URL

_required = {
    "GEMINI_API_KEY":       GEMINI_API_KEY,
    "GROQ_API_KEY":         GROQ_API_KEY,
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
