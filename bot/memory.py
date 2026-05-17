import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

MEMORY_FILE = Path("team_memory.json")
MAX_MEMORIES = 30


def load() -> list:
    if not MEMORY_FILE.exists():
        return []
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Ошибка чтения памяти: {e}")
        return []


def save(decision: str, source: str = "discussion") -> None:
    memories = load()
    memories.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": source,
        "decision": decision.strip(),
    })
    if len(memories) > MAX_MEMORIES:
        memories = memories[-MAX_MEMORIES:]
    MEMORY_FILE.write_text(
        json.dumps(memories, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"💾 Сохранено: {decision[:70]}...")


def as_context() -> str:
    memories = load()
    if not memories:
        return ""
    lines = "\n".join(
        f"[{m['date']}] {m['decision']}" for m in memories
    )
    return (
        "Договорённости и решения команды из прошлых обсуждений "
        "(это реальные решения — следуй им):\n" + lines
    )


def clear() -> int:
    count = len(load())
    MEMORY_FILE.write_text("[]", encoding="utf-8")
    return count