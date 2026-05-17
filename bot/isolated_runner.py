"""
Unified isolated execution.
Приоритет: Docker → subprocess с ограничениями.
"""
import asyncio
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bot.docker_sandbox import run_docker, _check_docker
from bot.event_bus import bus, Events

logger = logging.getLogger(__name__)

SUBPROCESS_TIMEOUT = 10
MAX_OUTPUT         = 3000

BLOCKED_PATTERNS = [
    "os.system", "shutil.rmtree", "__import__('os')",
    "import subprocess", "open('/etc')", "open('/sys')",
]


def _subprocess_run(code: str) -> dict:
    for pattern in BLOCKED_PATTERNS:
        if pattern in code:
            return {
                "success": False, "stdout": "",
                "stderr": f"❌ Заблокировано: `{pattern}`",
                "runtime": "subprocess", "duration": 0,
            }

    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp = f.name

    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True,
            timeout=SUBPROCESS_TIMEOUT,
            cwd=tempfile.gettempdir(),
        )
        return {
            "success":  result.returncode == 0,
            "stdout":   result.stdout[:MAX_OUTPUT],
            "stderr":   result.stderr[:MAX_OUTPUT],
            "exit_code": result.returncode,
            "duration": round(time.time() - start, 2),
            "runtime":  "subprocess",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False, "stdout": "",
            "stderr": f"❌ Timeout {SUBPROCESS_TIMEOUT}с",
            "duration": SUBPROCESS_TIMEOUT, "runtime": "subprocess",
        }
    except Exception as e:
        return {
            "success": False, "stdout": "",
            "stderr": str(e), "duration": 0, "runtime": "subprocess",
        }
    finally:
        Path(tmp).unlink(missing_ok=True)


async def execute(code: str, language: str = "python") -> dict:
    """Запускает код: Docker если доступен, иначе subprocess."""
    logger.info(f"[Isolated] Запуск {language} ({len(code)} байт)")

    if _check_docker():
        result = await run_docker(code, language)
    else:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _subprocess_run, code)

    result["language"] = language

    await bus.publish(Events.SANDBOX_EXECUTED, {
        "language": language,
        "runtime":  result.get("runtime", "unknown"),
        "success":  result["success"],
        "duration": result.get("duration", 0),
        "preview":  code[:80],
    })

    icon = "✅" if result["success"] else "❌"
    logger.info(
        f"[Isolated] {icon} {result.get('runtime')} "
        f"за {result.get('duration', 0)}с"
    )
    return result


def format_result(result: dict) -> str:
    icon    = "✅" if result["success"] else "❌"
    runtime = result.get("runtime", "?")
    dur     = result.get("duration", 0)
    lang    = result.get("language", "python")

    parts = [f"{icon} *Sandbox [{lang} / {runtime}]* — {dur}с"]

    if result.get("stdout"):
        out = result["stdout"][:800]
        parts.append(f"```\n{out}\n```")

    if result.get("stderr"):
        err = result["stderr"][:400]
        parts.append(f"⚠️ stderr:\n```\n{err}\n```")

    return "\n".join(parts)