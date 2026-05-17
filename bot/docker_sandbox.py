"""
Docker-based sandbox для изолированного выполнения кода.
Если Docker недоступен — автоматически fallback на subprocess.
"""
import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Конфигурация контейнера
DOCKER_IMAGE    = "python:3.11-slim"
TIMEOUT_SECONDS = 15
MEM_LIMIT       = "128m"
CPU_PERIOD      = 100_000
CPU_QUOTA       = 50_000   # 0.5 CPU
MAX_OUTPUT      = 3000

_docker_available: bool | None = None


def _check_docker() -> bool:
    global _docker_available
    if _docker_available is not None:
        return _docker_available
    try:
        import docker
        client = docker.from_env(timeout=3)
        client.ping()
        _docker_available = True
        logger.info("✅ Docker доступен")
    except Exception as e:
        _docker_available = False
        logger.warning(f"⚠️ Docker недоступен: {e}. Используется subprocess fallback.")
    return _docker_available


def _run_in_docker(code: str, language: str = "python") -> dict:
    import docker
    client = docker.from_env()

    cmd = f'python3 -c {repr(code)}' if language == "python" else f'bash -c {repr(code)}'

    start = time.time()
    try:
        container = client.containers.run(
            image=DOCKER_IMAGE,
            command=["sh", "-c", cmd],
            mem_limit=MEM_LIMIT,
            cpu_period=CPU_PERIOD,
            cpu_quota=CPU_QUOTA,
            network_mode="none",      # нет сети
            read_only=False,
            remove=True,
            detach=False,
            stdout=True,
            stderr=True,
            timeout=TIMEOUT_SECONDS,
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
            tmpfs={"/tmp": "size=64m"},
        )
        duration = round(time.time() - start, 2)
        output = container.decode("utf-8", errors="replace")[:MAX_OUTPUT]
        return {
            "success":  True,
            "stdout":   output,
            "stderr":   "",
            "duration": duration,
            "runtime":  "docker",
            "language": language,
        }
    except Exception as e:
        duration = round(time.time() - start, 2)
        return {
            "success":  False,
            "stdout":   "",
            "stderr":   str(e)[:500],
            "duration": duration,
            "runtime":  "docker",
            "language": language,
        }


def _pull_image_if_needed() -> None:
    try:
        import docker
        client = docker.from_env()
        try:
            client.images.get(DOCKER_IMAGE)
        except Exception:
            logger.info(f"Скачиваю образ {DOCKER_IMAGE}...")
            client.images.pull(DOCKER_IMAGE)
            logger.info(f"✅ Образ {DOCKER_IMAGE} готов")
    except Exception as e:
        logger.warning(f"Не удалось подготовить Docker образ: {e}")


async def run_docker(code: str, language: str = "python") -> dict:
    if not _check_docker():
        return {"success": False, "stdout": "", "stderr": "Docker недоступен",
                "runtime": "docker", "language": language, "duration": 0}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_in_docker, code, language)


async def ensure_image() -> None:
    if _check_docker():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _pull_image_if_needed)