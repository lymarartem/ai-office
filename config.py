import os
import logging
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

logger = logging.getLogger(__name__)

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

# LLM-бэкенд — Groq (OpenAI-совместимый API)
LLM_API_URL     = "https://api.groq.com/openai/v1/chat/completions"
MODEL_CEO       = "llama-3.3-70b-versatile"
MODEL_DEVELOPER = "llama-3.3-70b-versatile"
MODEL_MARKETING = "llama-3.3-70b-versatile"
MODEL_DESIGNER  = "llama-3.3-70b-versatile"
MODEL_TERMINAL  = "llama-3.3-70b-versatile"
MODEL_BROWSER   = "llama-3.3-70b-versatile"

_required = {
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
