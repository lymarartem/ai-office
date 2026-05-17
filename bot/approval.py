import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROPOSALS_FILE = Path("proposals.json")


def _load() -> dict:
    if not PROPOSALS_FILE.exists():
        return {}
    try:
        return json.loads(PROPOSALS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Ошибка чтения proposals: {e}")
        return {}


def _save(data: dict) -> None:
    PROPOSALS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create(
    agent_name: str,
    title: str,
    what: str,
    why: str,
    risks: str,
    files: list = None,
    pre_test_passed: bool = None,
    pre_test_output: str = None,
) -> str:
    proposals = _load()
    pid = f"P{len(proposals) + 1:03d}"
    proposals[pid] = {
        "id":               pid,
        "agent":            agent_name,
        "title":            title,
        "what":             what,
        "why":              why,
        "risks":            risks,
        "files":            files or [],
        "status":           "pending",
        "pre_test_passed":  pre_test_passed,
        "pre_test_output":  pre_test_output,
        "created":          datetime.now().strftime("%Y-%m-%d %H:%M"),
        "decided":          None,
        "feedback":         None,
    }
    _save(proposals)
    logger.info(f"Proposal {pid} создан от {agent_name}")
    return pid


def get(pid: str) -> Optional[dict]:
    return _load().get(pid)


def update(pid: str, status: str, feedback: str = None) -> bool:
    proposals = _load()
    if pid not in proposals:
        return False
    proposals[pid]["status"]  = status
    proposals[pid]["decided"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    if feedback:
        proposals[pid]["feedback"] = feedback
    _save(proposals)
    return True


def pending() -> list:
    return [p for p in _load().values() if p["status"] == "pending"]


def all_proposals() -> list:
    return list(_load().values())


def format_proposal(p: dict) -> str:
    files_str = ", ".join(p["files"]) if p["files"] else "—"
    status_emoji = {
        "pending":  "⏳",
        "approved": "✅",
        "rejected": "❌",
        "revised":  "✏️",
    }.get(p["status"], "❓")

    # Результат pre-tests
    if p.get("pre_test_passed") is None:
        test_line = ""
    elif p["pre_test_passed"]:
        test_line = "\n🧪 *Pre-tests:* ✅ passed"
    else:
        test_line = "\n🧪 *Pre-tests:* ❌ failed"

    text = (
        f"🔔 *ПРЕДЛОЖЕНИЕ {p['id']}* {status_emoji}\n"
        f"{'━' * 22}\n"
        f"👤 *От:* {p['agent']}\n"
        f"📋 *Что:* {p['what']}\n"
        f"📁 *Файлы:* {files_str}\n"
        f"❓ *Зачем:* {p['why']}\n"
        f"⚠️ *Риски:* {p['risks']}"
        f"{test_line}\n"
        f"{'━' * 22}\n"
        f"🕐 {p['created']}"
    )

    if p.get("feedback"):
        text += f"\n💬 *Фидбэк:* {p['feedback']}"

    return text