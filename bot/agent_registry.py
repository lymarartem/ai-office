"""
Service registry для multi-machine агентов.
Регистрация, health-checking, load balancing, failover.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30   # секунд
REQUEST_TIMEOUT = 5   # секунд


class AgentStatus(Enum):
    ONLINE  = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


@dataclass
class RemoteAgent:
    name:        str
    url:         str
    status:      AgentStatus = AgentStatus.UNKNOWN
    latency_ms:  float = 0.0
    last_check:  float = field(default_factory=time.time)
    fail_count:  int   = 0
    total_calls: int   = 0
    model:       str   = "unknown"


class AgentRegistry:
    """
    Реестр всех агентов (локальных и удалённых).
    Автоматически проверяет здоровье удалённых агентов.
    """

    def __init__(self):
        self._local:   dict[str, object]      = {}
        self._remote:  dict[str, RemoteAgent] = {}
        self._running  = False

    # ── Регистрация ───────────────────────────────────────────────

    def register_local(self, agent) -> None:
        self._local[agent.name] = agent
        logger.info(f"[Registry] Локальный: {agent.name}")

    def register_remote(self, name: str, url: str) -> None:
        self._remote[name] = RemoteAgent(name=name, url=url)
        logger.info(f"[Registry] Удалённый: {name} → {url}")

    def unregister(self, name: str) -> None:
        self._remote.pop(name, None)
        self._local.pop(name, None)

    # ── Health checking ───────────────────────────────────────────

    async def start_health_checks(self) -> None:
        self._running = True
        asyncio.create_task(self._health_loop())
        logger.info("[Registry] Health checks запущены")

    async def _health_loop(self) -> None:
        while self._running:
            await asyncio.sleep(CHECK_INTERVAL)
            for name, agent in list(self._remote.items()):
                await self._check_agent(agent)

    async def _check_agent(self, agent: RemoteAgent) -> None:
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                r = await client.get(f"{agent.url}/agents/{agent.name}/health")
            latency = round((time.time() - start) * 1000, 1)

            if r.status_code == 200:
                data          = r.json()
                agent.status  = AgentStatus.ONLINE
                agent.latency_ms = latency
                agent.fail_count = 0
                agent.model   = data.get("model", "unknown")
                logger.debug(f"[Registry] ✅ {agent.name} — {latency}ms")
            else:
                agent.fail_count += 1
                agent.status = AgentStatus.OFFLINE

        except Exception as e:
            agent.fail_count += 1
            agent.status = AgentStatus.OFFLINE
            logger.warning(f"[Registry] ❌ {agent.name}: {e}")
        finally:
            agent.last_check = time.time()

    # ── Вызов агентов ─────────────────────────────────────────────

    async def call(
        self,
        name: str,
        message: str,
        history: list = None,
    ) -> str:
        # Локальный агент
        if name in self._local:
            self._local[name]  # type check
            agent = self._local[name]
            return await agent.respond(message=message, history=history)

        # Удалённый агент
        remote = self._remote.get(name)
        if not remote:
            return f"❌ Агент '{name}' не найден в реестре."

        if remote.status == AgentStatus.OFFLINE:
            return f"❌ Агент '{name}' сейчас офлайн."

        remote.total_calls += 1
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{remote.url}/agents/{name}/respond",
                    json={"message": message, "history": history or []},
                )
                result = r.json().get("response", "❌ Нет ответа")
                remote.status = AgentStatus.ONLINE
                return result
        except Exception as e:
            remote.fail_count += 1
            remote.status = AgentStatus.OFFLINE
            logger.error(f"[Registry] Remote call {name} failed: {e}")
            return f"❌ Агент '{name}' недоступен: {e}"

    # ── Статус и балансировка ─────────────────────────────────────

    def get_best_agent(self, candidates: list[str]) -> Optional[str]:
        """Возвращает наиболее доступного агента из списка кандидатов."""
        # Локальные всегда приоритетнее
        for name in candidates:
            if name in self._local:
                return name

        # Из удалённых — с минимальной латентностью
        online = [
            self._remote[n] for n in candidates
            if n in self._remote and self._remote[n].status == AgentStatus.ONLINE
        ]
        if online:
            return min(online, key=lambda a: a.latency_ms).name

        return None

    def status(self) -> dict:
        result = {}
        for name, agent in self._local.items():
            result[name] = {
                "type":   "local",
                "status": "online",
                "model":  getattr(agent, "model", "unknown"),
            }
        for name, agent in self._remote.items():
            result[name] = {
                "type":       "remote",
                "url":        agent.url,
                "status":     agent.status.value,
                "latency_ms": agent.latency_ms,
                "fail_count": agent.fail_count,
                "total_calls": agent.total_calls,
                "model":      agent.model,
            }
        return result

    def all_names(self) -> list[str]:
        return list(self._local.keys()) + list(self._remote.keys())

    def stop(self) -> None:
        self._running = False


# Глобальный реестр
registry = AgentRegistry()