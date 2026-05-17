import json
import logging
from pathlib import Path
from typing import Optional

from config import OWNER_TELEGRAM_ID

logger = logging.getLogger(__name__)

PERMS_FILE = Path("permissions.json")

# Роли и что им разрешено
ROLES = {
    "owner": {
        "approve", "reject", "revise",
        "deploy", "rollback",
        "manage_users", "view_dashboard",
    },
    "admin": {
        "approve", "reject", "revise",
        "view_dashboard",
    },
    "member": set(),  # только чат
}


def _load() -> dict:
    if not PERMS_FILE.exists():
        return {}
    try:
        return json.loads(PERMS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    PERMS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_role(user_id: int) -> str:
    if user_id == OWNER_TELEGRAM_ID:
        return "owner"
    data = _load()
    return data.get(str(user_id), "member")


def set_role(user_id: int, role: str) -> bool:
    if role not in ROLES:
        return False
    data = _load()
    data[str(user_id)] = role
    _save(data)
    logger.info(f"Роль {user_id} → {role}")
    return True


def remove_user(user_id: int) -> bool:
    data = _load()
    if str(user_id) not in data:
        return False
    del data[str(user_id)]
    _save(data)
    return True


def can(user_id: int, action: str) -> bool:
    role = get_role(user_id)
    return action in ROLES.get(role, set())


def all_users() -> list:
    data = _load()
    users = [{"id": OWNER_TELEGRAM_ID, "role": "owner"}]
    for uid, role in data.items():
        users.append({"id": int(uid), "role": role})
    return users


def format_denied(action: str) -> str:
    return (
        f"🚫 *Нет прав* для действия `{action}`.\n"
        f"Обратись к владельцу: `/myrole` — узнать свою роль."
    )