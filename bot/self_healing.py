import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED   = "closed"    # работает нормально
    OPEN     = "open"      # заблокирован после сбоев
    HALF     = "half_open" # пробный режим


@dataclass
class CircuitBreaker:
    name:            str
    max_failures:    int   = 3
    reset_timeout:   float = 60.0
    state:           CircuitState = CircuitState.CLOSED
    failure_count:   int   = 0
    last_failure:    float = 0.0
    success_count:   int   = 0
    total_calls:     int   = 0
    total_failures:  int   = 0

    def can_call(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure > self.reset_timeout:
                self.state = CircuitState.HALF
                logger.info(f"[CB:{self.name}] HALF_OPEN — пробный вызов")
                return True
            return False
        return True  # HALF_OPEN

    def on_success(self) -> None:
        self.total_calls += 1
        self.success_count += 1
        if self.state == CircuitState.HALF:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info(f"[CB:{self.name}] CLOSED — восстановлен")

    def on_failure(self, error: Exception) -> None:
        self.total_calls    += 1
        self.total_failures += 1
        self.failure_count  += 1
        self.last_failure    = time.time()
        if self.failure_count >= self.max_failures:
            self.state = CircuitState.OPEN
            logger.error(
                f"[CB:{self.name}] OPEN — {self.failure_count} сбоев подряд. "
                f"Пауза {self.reset_timeout}с"
            )

    @property
    def status(self) -> str:
        icons = {
            CircuitState.CLOSED: "🟢",
            CircuitState.OPEN:   "🔴",
            CircuitState.HALF:   "🟡",
        }
        return f"{icons[self.state]} {self.state.value}"


# Глобальные circuit breakers
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]


def all_breakers() -> dict[str, CircuitBreaker]:
    return _breakers


def retry(max_attempts: int = 3, backoff: float = 2.0, exceptions=(Exception,)):
    """Декоратор: повтор async-функции с экспоненциальным backoff."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_err = e
                    wait = backoff ** attempt
                    logger.warning(
                        f"[Retry] {func.__name__} попытка {attempt + 1}/{max_attempts} "
                        f"— {e} — жду {wait:.1f}с"
                    )
                    await asyncio.sleep(wait)
            raise last_err
        return wrapper
    return decorator


class HealthMonitor:
    """Мониторит состояние системы и восстанавливает упавшие компоненты."""

    def __init__(self, check_interval: int = 60):
        self.interval  = check_interval
        self._tasks:   dict[str, asyncio.Task] = {}
        self._running  = False
        self._alerts:  deque = deque(maxlen=50)

    def register(self, name: str, coro_factory: Callable) -> None:
        """Регистрирует компонент для мониторинга."""
        self._tasks[name] = {"factory": coro_factory, "task": None, "restarts": 0}

    async def start(self) -> None:
        self._running = True
        for name, info in self._tasks.items():
            await self._launch(name, info)
        asyncio.create_task(self._monitor_loop())
        logger.info(f"HealthMonitor запущен. Компонентов: {len(self._tasks)}")

    async def _launch(self, name: str, info: dict) -> None:
        try:
            task = asyncio.create_task(info["factory"]())
            info["task"] = task
            logger.info(f"[Health] ✅ {name} запущен")
        except Exception as e:
            logger.error(f"[Health] ❌ {name} не запустился: {e}")

    async def _monitor_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.interval)
            for name, info in self._tasks.items():
                task = info.get("task")
                if task and task.done():
                    err = task.exception() if not task.cancelled() else "cancelled"
                    info["restarts"] += 1
                    alert = (
                        f"[Health] ⚠️ {name} упал "
                        f"(рестарт #{info['restarts']}): {err}"
                    )
                    logger.error(alert)
                    self._alerts.append({
                        "time":    __import__("datetime").datetime.now().strftime("%H:%M:%S"),
                        "name":    name,
                        "error":   str(err),
                        "restart": info["restarts"],
                    })
                    await self._launch(name, info)

    def get_alerts(self) -> list:
        return list(self._alerts)

    def get_status(self) -> dict:
        status = {}
        for name, info in self._tasks.items():
            task = info.get("task")
            if task is None:
                state = "not_started"
            elif task.done():
                state = "dead"
            elif task.cancelled():
                state = "cancelled"
            else:
                state = "running"
            status[name] = {
                "state":    state,
                "restarts": info["restarts"],
            }
        return status

    def stop(self) -> None:
        self._running = False
        for info in self._tasks.values():
            task = info.get("task")
            if task and not task.done():
                task.cancel()


# Глобальный монитор
monitor = HealthMonitor(check_interval=60)