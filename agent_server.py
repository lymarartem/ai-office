"""
Автономный сервер для запуска агентов на удалённых машинах.
Запускай на каждой машине: python agent_server.py

Пример:
  Машина 1 (основная): python main.py
  Машина 2 (удалённая): python agent_server.py --agents developer --port 8081
  
  В .env основной машины добавь:
  REMOTE_DEVELOPER=http://192.168.1.100:8081
"""
import argparse
import asyncio
import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

app   = FastAPI(title="AI Office Remote Agent Server")
_agents: dict = {}


class RespondRequest(BaseModel):
    message: str
    history: list = []


@app.get("/")
async def root():
    return {"service": "AI Office Remote Agent Server", "agents": list(_agents.keys())}


@app.get("/agents/")
async def list_agents():
    return JSONResponse([
        {"name": name, "model": getattr(a, "model", "?"), "type": "remote_local"}
        for name, a in _agents.items()
    ])


@app.get("/agents/{agent_name}/health")
async def health(agent_name: str):
    agent = _agents.get(agent_name)
    if not agent:
        return JSONResponse({"error": "not found"}, status_code=404)
    from bot.self_healing import get_breaker
    cb = get_breaker(agent.name)
    return JSONResponse({
        "name":    agent.name,
        "model":   agent.model,
        "status":  "online",
        "circuit": cb.state.value,
    })


@app.post("/agents/{agent_name}/respond")
async def respond(agent_name: str, req: RespondRequest):
    agent = _agents.get(agent_name)
    if not agent:
        return JSONResponse({"error": f"Agent '{agent_name}' not found"}, status_code=404)
    try:
        response = await agent.respond(message=req.message, history=req.history)
        return JSONResponse({"agent": agent_name, "response": response})
    except Exception as e:
        logger.error(f"Agent error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


def load_agents(agent_names: list[str]) -> None:
    agent_map = {
        "developer": ("agents.developer",    "DeveloperAgent"),
        "marketing":  ("agents.marketing",   "MarketingAgent"),
        "designer":   ("agents.designer",    "DesignerAgent"),
        "terminal":   ("agents.terminal",    "TerminalAgent"),
        "browser":    ("agents.browser",     "BrowserAgent"),
        "claude":     ("agents.claude_agent","ClaudeAgent"),
    }
    for name in agent_names:
        if name not in agent_map:
            logger.warning(f"Неизвестный агент: {name}")
            continue
        module_path, class_name = agent_map[name]
        try:
            import importlib
            module = importlib.import_module(module_path)
            cls    = getattr(module, class_name)
            agent  = cls()

            # Регистрируем под ДВУМЯ именами:
            # "developer" — для registry health check
            # "Дэн (Dev)" — для respond endpoint
            _agents[name]       = agent  # "developer"
            _agents[agent.name] = agent  # "Дэн (Dev)"

            logger.info(f"✅ Агент загружен: {agent.name} (ключ: {name})")
        except Exception as e:
            logger.error(f"❌ Не удалось загрузить {name}: {e}")


async def main(agents: list[str], port: int, host: str) -> None:
    load_agents(agents)
    if not _agents:
        logger.error("Нет загруженных агентов. Укажи: --agents developer marketing")
        sys.exit(1)

    logger.info(
        f"\n🤖 Remote Agent Server запущен\n"
        f"🌐 http://{host}:{port}\n"
        f"Агенты: {list(_agents.keys())}\n"
        f"API: POST /agents/{{name}}/respond"
    )

    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Office Remote Agent Server")
    parser.add_argument(
        "--agents", nargs="+",
        default=["developer"],
        choices=["developer", "marketing", "designer", "terminal", "browser", "claude"],
        help="Какие агенты запустить",
    )
    parser.add_argument("--port", type=int, default=8081, help="Порт сервера")
    parser.add_argument("--host", default="0.0.0.0", help="Хост")
    args = parser.parse_args()

    asyncio.run(main(args.agents, args.port, args.host))