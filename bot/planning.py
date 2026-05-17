import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GOALS_FILE = Path("goals.json")


def _load() -> dict:
    if not GOALS_FILE.exists():
        return {}
    try:
        return json.loads(GOALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    GOALS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def create_goal(
    title: str,
    description: str,
    milestones: list[str] = None,
    agent: str = "CEO",
) -> str:
    goals = _load()
    gid = f"G{len(goals) + 1:03d}"
    goals[gid] = {
        "id":          gid,
        "title":       title,
        "description": description,
        "agent":       agent,
        "status":      "active",
        "progress":    0,
        "milestones":  [
            {"text": m, "done": False} for m in (milestones or [])
        ],
        "created":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "updated":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes":       [],
    }
    _save(goals)
    logger.info(f"Цель {gid} создана: {title}")
    return gid


def get_goal(gid: str) -> Optional[dict]:
    return _load().get(gid)


def all_goals() -> list:
    return list(_load().values())


def active_goals() -> list:
    return [g for g in _load().values() if g["status"] == "active"]


def complete_milestone(gid: str, milestone_idx: int) -> bool:
    goals = _load()
    if gid not in goals:
        return False
    ms = goals[gid]["milestones"]
    if milestone_idx >= len(ms):
        return False
    ms[milestone_idx]["done"] = True
    done = sum(1 for m in ms if m["done"])
    goals[gid]["progress"] = int(done / len(ms) * 100) if ms else 0
    goals[gid]["updated"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
    if all(m["done"] for m in ms):
        goals[gid]["status"] = "completed"
    _save(goals)
    return True


def update_progress(gid: str, progress: int, note: str = None) -> bool:
    goals = _load()
    if gid not in goals:
        return False
    goals[gid]["progress"] = max(0, min(100, progress))
    goals[gid]["updated"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
    if note:
        goals[gid]["notes"].append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "text": note,
        })
    if progress >= 100:
        goals[gid]["status"] = "completed"
    _save(goals)
    return True


def complete_goal(gid: str) -> bool:
    return update_progress(gid, 100)


def format_goal(g: dict) -> str:
    status_icon = {"active": "🎯", "completed": "✅", "paused": "⏸"}.get(g["status"], "❓")
    bar_filled  = int(g["progress"] / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    ms_lines = ""
    if g["milestones"]:
        ms_lines = "\n" + "\n".join(
            f"  {'✅' if m['done'] else '⬜'} {m['text']}"
            for m in g["milestones"]
        )

    last_note = ""
    if g["notes"]:
        n = g["notes"][-1]
        last_note = f"\n💬 _{n['text']}_"

    return (
        f"{status_icon} *{g['id']}: {g['title']}*\n"
        f"`{bar}` {g['progress']}%\n"
        f"{g['description']}"
        f"{ms_lines}"
        f"{last_note}\n"
        f"_Обновлено: {g['updated']}_"
    )


def build_goals_context() -> str:
    goals = active_goals()
    if not goals:
        return ""
    lines = "\n".join(
        f"[{g['id']}] {g['title']} — {g['progress']}% — {g['status']}"
        for g in goals
    )
    return f"Активные цели команды:\n{lines}"