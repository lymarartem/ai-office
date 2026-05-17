"""
Distributed Agent Layer.
Каждый агент доступен как HTTP микросервис.
Позволяет запускать агентов на разных машинах.
"""
import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Реестр агентов: локальных и удалённых
_local_agents:  dict = {}
_remote_agents: dict = {}  # {"name": "http://remote-host:8081"}


class RespondRequest(BaseModel):
    message: str
    history: Optional[list] = None


class AgentInfo(BaseModel):
    name:   str
    model:  str
    status: str = "online"


def register_local(agent) -> None:
    _local_agents[agent.name] = agent
    logger.info(f"[Distributed] Локальный агент зарегистрирован: {agent.name}")


def register_remote(name: str, url: str) -> None:
    _remote_agents[name] = url
    logger.info(f"[Distributed] Удалённый агент зарегистрирован: {name} → {url}")


def make_agent_router() -> APIRouter:
    router = APIRouter(prefix="/agents", tags=["agents"])

    @router.get("/")
    async def list_agents():
        local  = [{"name": name, "type": "local"}  for name in _local_agents]
        remote = [{"name": name, "type": "remote", "url": url}
                  for name, url in _remote_agents.items()]
        return {"agents": local + remote, "total": len(local) + len(remote)}

    @router.get("/{agent_name}/health")
    async def agent_health(agent_name: str):
        if agent_name in _local_agents:
            agent = _local_agents[agent_name]
            from bot.self_healing import get_breaker
            breaker = get_breaker(agent.name)
            return {
                "name":    agent.name,
                "model":   agent.model,
                "status":  "online",
                "circuit": breaker.state.value,
            }
        if agent_name in _remote_agents:
            import httpx
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(f"{_remote_agents[agent_name]}/health")
                    return r.json()
            except Exception as e:
                return {"name": agent_name, "status": "offline", "error": str(e)}
        return {"error": f"Агент '{agent_name}' не найден"}, 404

    @router.post("/{agent_name}/respond")
    async def agent_respond(agent_name: str, req: RespondRequest):
        if agent_name in _local_agents:
            agent    = _local_agents[agent_name]
            response = await agent.respond(
                message=req.message, history=req.history
            )
            return {"agent": agent_name, "response": response}

        if agent_name in _remote_agents:
            import httpx
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.post(
                        f"{_remote_agents[agent_name]}/agents/{agent_name}/respond",
                        json=req.dict(),
                    )
                    return r.json()
            except Exception as e:
                return {"error": f"Remote agent error: {e}"}, 503

        return {"error": f"Агент '{agent_name}' не найден"}, 404

    return router


async def call_agent(name: str, message: str, history: list = None) -> str:
    """Вызов агента — локального или удалённого."""
    if name in _local_agents:
        return await _local_agents[name].respond(message=message, history=history)

    if name in _remote_agents:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{_remote_agents[name]}/agents/{name}/respond",
                    json={"message": message, "history": history or []},
                )
                return r.json().get("response", "❌ Нет ответа от удалённого агента")
        except Exception as e:
            return f"❌ Remote agent '{name}' недоступен: {e}"

    return f"❌ Агент '{name}' не найден"