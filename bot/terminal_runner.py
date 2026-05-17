"""
Terminal command execution с human approval и безопасностью.
"""
import asyncio
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.event_bus import bus, Events

logger = logging.getLogger(__name__)

MAX_OUTPUT  = 4000
TIMEOUT_SEC = 30

# Команды которые можно запускать без подтверждения
WHITELIST = {
    "ls", "dir", "pwd", "cat", "echo", "python", "python3",
    "pip", "pip3", "pytest", "git log", "git status", "git branch",
    "git diff", "git show", "find", "grep", "which", "where",
    "whoami", "hostname", "date", "uname", "systeminfo",
}

# Команды которые НИКОГДА нельзя запускать
BLACKLIST = {
    "rm -rf /", "format", "mkfs", "dd if=", ":(){ :|:& };:",
    "chmod 777 /", "sudo rm", "del /f /s /q c:\\",
    "> /dev/sda", "shred",
}

# Ожидающие выполнения команды: {exec_id: {cmd, cwd, agent_bot, chat_id}}
_pending: dict = {}


def _classify(cmd: str) -> str:
    """Классифицирует команду: safe / needs_approval / blocked."""
    cmd_lower = cmd.lower().strip()

    for blocked in BLACKLIST:
        if blocked in cmd_lower:
            return "blocked"

    for safe in WHITELIST:
        if cmd_lower.startswith(safe):
            return "safe"

    return "needs_approval"


def _run_command(cmd: str, cwd: str = ".") -> dict:
    start = time.time()
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=TIMEOUT_SEC, cwd=cwd,
        )
        duration = round(time.time() - start, 2)
        return {
            "success":   result.returncode == 0,
            "stdout":    result.stdout[:MAX_OUTPUT],
            "stderr":    result.stderr[:MAX_OUTPUT],
            "exit_code": result.returncode,
            "duration":  duration,
            "cmd":       cmd,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False, "stdout": "",
            "stderr":  f"❌ Timeout {TIMEOUT_SEC}с",
            "exit_code": -1, "duration": TIMEOUT_SEC, "cmd": cmd,
        }
    except Exception as e:
        return {
            "success": False, "stdout": "",
            "stderr": str(e), "exit_code": -1,
            "duration": round(time.time() - start, 2), "cmd": cmd,
        }


async def execute(
    cmd: str,
    terminal_bot,
    chat_id: int,
    cwd: str = ".",
    context: str = "",
) -> dict | None:
    """
    Выполняет команду с проверкой безопасности.
    Если нужно подтверждение — отправляет кнопки и возвращает None.
    """
    classification = _classify(cmd)

    if classification == "blocked":
        await terminal_bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚫 *Терм (Terminal):* Команда заблокирована по соображениям безопасности.\n"
                f"`{cmd}`"
            ),
            parse_mode="Markdown",
        )
        return None

    if classification == "needs_approval":
        exec_id = f"exec_{datetime.now().strftime('%H%M%S_%f')}"
        _pending[exec_id] = {
            "cmd":     cmd,
            "cwd":     cwd,
            "chat_id": chat_id,
            "context": context,
        }
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("▶️ Выполнить", callback_data=f"exec_approve:{exec_id}"),
            InlineKeyboardButton("🚫 Отменить",  callback_data=f"exec_cancel:{exec_id}"),
        ]])
        await terminal_bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ *Терм (Terminal):* Требует подтверждения\n\n"
                f"```\n{cmd}\n```\n"
                f"_Рабочая директория: `{cwd}`_"
                + (f"\n_{context}_" if context else "")
            ),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return None

    # safe — выполняем сразу
    return await _do_execute(cmd, terminal_bot, chat_id, cwd)


async def execute_approved(exec_id: str, terminal_bot) -> None:
    """Выполняет одобренную команду."""
    info = _pending.pop(exec_id, None)
    if not info:
        return
    await _do_execute(
        info["cmd"], terminal_bot, info["chat_id"], info["cwd"]
    )


async def cancel_execution(exec_id: str, terminal_bot, chat_id: int) -> None:
    _pending.pop(exec_id, None)
    await terminal_bot.send_message(
        chat_id=chat_id,
        text="🚫 *Терм:* Выполнение отменено.",
        parse_mode="Markdown",
    )


async def _do_execute(
    cmd: str, terminal_bot, chat_id: int, cwd: str
) -> dict:
    await terminal_bot.send_message(
        chat_id=chat_id,
        text=f"⚙️ *Терм:* Выполняю...\n```\n{cmd}\n```",
        parse_mode="Markdown",
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_command, cmd, cwd)

    icon = "✅" if result["success"] else "❌"
    parts = [f"{icon} *Терм [{result['duration']}с]:*\n```\n{cmd}\n```"]

    if result["stdout"]:
        parts.append(f"```\n{result['stdout'][:1500]}\n```")
    if result["stderr"]:
        parts.append(f"⚠️ stderr:\n```\n{result['stderr'][:500]}\n```")

    await terminal_bot.send_message(
        chat_id=chat_id,
        text="\n".join(parts),
        parse_mode="Markdown",
    )

    await bus.publish("terminal_executed", {
        "cmd":      cmd,
        "success":  result["success"],
        "duration": result["duration"],
    })

    logger.info(f"[Terminal] {icon} `{cmd}` за {result['duration']}с")
    return result


def format_help() -> str:
    safe_list = ", ".join(sorted(WHITELIST))
    return (
        f"🖥 *Terminal Agent — Терм*\n\n"
        f"*Безопасные команды* (без подтверждения):\n"
        f"`{safe_list}`\n\n"
        f"*Остальные команды* — требуют кнопку ▶️ Выполнить\n\n"
        f"*Пример:*\n"
        f"`/run pytest -v`\n"
        f"`/run git log --oneline -5`\n"
        f"`/run python -c \"print(2**32)\"`"
    )