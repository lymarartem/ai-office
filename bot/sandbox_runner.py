import asyncio
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARS = 2000

BLOCKED_IMPORTS = [
    "os.system", "subprocess", "shutil.rmtree",
    "open('/", "__import__", "eval(", "exec(",
]


def _is_safe(code: str) -> tuple[bool, str]:
    """Проверяет код на опасные конструкции."""
    for pattern in BLOCKED_IMPORTS:
        if pattern in code:
            return False, f"Заблокировано: `{pattern}`"
    return True, ""


def _run_python(code: str) -> dict:
    """Запускает Python код в subprocess с ограничениями."""
    safe, reason = _is_safe(code)
    if not safe:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"❌ Небезопасный код: {reason}",
            "duration": 0,
            "language": "python",
        }

    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=tempfile.gettempdir(),
        )
        duration = round(time.time() - start, 2)
        stdout = result.stdout[:MAX_OUTPUT_CHARS]
        stderr = result.stderr[:MAX_OUTPUT_CHARS]
        return {
            "success": result.returncode == 0,
            "stdout":  stdout,
            "stderr":  stderr,
            "exit_code": result.returncode,
            "duration":  duration,
            "language":  "python",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"❌ Timeout: превышено {TIMEOUT_SECONDS}с",
            "duration": TIMEOUT_SECONDS,
            "language": "python",
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"❌ Ошибка запуска: {e}",
            "duration": 0,
            "language": "python",
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def execute(code: str, language: str = "python") -> dict:
    """Async обёртка для sandbox выполнения."""
    logger.info(f"[Sandbox] Запуск {language}: {code[:60]}...")

    loop = asyncio.get_event_loop()

    if language == "python":
        result = await loop.run_in_executor(None, _run_python, code)
    else:
        result = {
            "success": False,
            "stdout": "",
            "stderr": f"Язык {language} не поддерживается. Доступно: python",
            "duration": 0,
            "language": language,
        }

    # Публикуем событие
    from bot.event_bus import bus, Events
    await bus.publish(Events.SANDBOX_EXECUTED, {
        "language": language,
        "success":  result["success"],
        "duration": result.get("duration", 0),
        "code_preview": code[:100],
    })

    logger.info(
        f"[Sandbox] {'✅' if result['success'] else '❌'} "
        f"за {result.get('duration', 0)}с"
    )
    return result


def format_result(result: dict) -> str:
    icon = "✅" if result["success"] else "❌"
    parts = [f"{icon} *Sandbox [{result['language']}]* — {result.get('duration', 0)}с"]
    if result["stdout"]:
        parts.append(f"```\n{result['stdout'][:500]}\n```")
    if result["stderr"]:
        parts.append(f"⚠️ stderr:\n```\n{result['stderr'][:300]}\n```")
    return "\n".join(parts)