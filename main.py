import asyncio
import contextlib
import logging
import os

from telegram.ext import Application

from agents.ceo import CEOAgent
from agents.developer import DeveloperAgent
from agents.marketing import MarketingAgent
from agents.designer import DesignerAgent
from agents.terminal import TerminalAgent
from agents.browser import BrowserAgent
from bot.handlers import (
    make_orchestrator_handler,
    make_approval_callback_handler,
    make_run_handler,
    make_sandbox_handler,
    make_rollback_handler,
    make_goals_handler,
    make_health_handler,
    make_search_handler,
    make_permissions_handler,
    make_myrole_handler,
    make_git_handler,
    make_queue_handler,
    make_proposals_handler,
    make_clear_handler,
    make_memory_handler,
    make_clear_memory_handler,
    set_terminal_bot,
    make_browse_handler,
    make_filegraph_handler,
    make_caveman_handler,
)
from bot.file_graph import start_file_graph_watcher
from bot.file_reactor import reactor as file_reactor
from bot.autonomous import run_autonomous_loop
from bot.task_queue import queue
from bot.dashboard import start_server, app as dashboard_app
from bot.self_healing import monitor
from bot.event_bus import bus, Events
from bot.distributed import make_agent_router
from bot.agent_registry import registry as agent_registry
from bot.docker_sandbox import ensure_image
from bot.browser_runner import close as close_browser
from bot.plugins.tools import *
import bot.git_manager as git
import bot.logger_buffer as log_buffer
from config import (
    CEO_BOT_TOKEN,
    DEVELOPER_BOT_TOKEN,
    MARKETING_BOT_TOKEN,
    DESIGNER_BOT_TOKEN,
    TERMINAL_BOT_TOKEN,
    BROWSER_BOT_TOKEN,
    GROUP_CHAT_ID,
    DISCUSSION_INTERVAL_MINUTES,
    DASHBOARD_PORT,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log_buffer.setup()
logger = logging.getLogger(__name__)


async def main() -> None:
    git.init_if_needed()
    await queue.start()
    asyncio.create_task(ensure_image())

    # Агенты
    ceo      = CEOAgent()
    developer = DeveloperAgent()
    marketing = MarketingAgent()
    designer  = DesignerAgent()
    terminal  = TerminalAgent()
    browser   = BrowserAgent()
    ceo.set_team(developer, marketing, designer)

    # Регистрируем в глобальном реестре
    for agent in [ceo, developer, marketing, designer, terminal, browser]:
        agent_registry.register_local(agent)

    # Подключаем удалённых агентов из .env
    # Формат: REMOTE_DEVELOPER=http://192.168.1.100:8081
    for key, val in os.environ.items():
        if key.startswith("REMOTE_") and val.startswith("http"):
            name = key.replace("REMOTE_", "").lower()
            agent_registry.register_remote(name, val)
            logger.info(f"🌐 Удалённый агент: {name} → {val}")

    await agent_registry.start_health_checks()

    dashboard_app.include_router(make_agent_router())

    # Telegram apps
    ceo_app      = Application.builder().token(CEO_BOT_TOKEN).build()
    dev_app      = Application.builder().token(DEVELOPER_BOT_TOKEN).build()
    mkt_app      = Application.builder().token(MARKETING_BOT_TOKEN).build()
    des_app      = Application.builder().token(DESIGNER_BOT_TOKEN).build()
    terminal_app = Application.builder().token(TERMINAL_BOT_TOKEN).build()
    browser_app  = Application.builder().token(BROWSER_BOT_TOKEN).build()

    set_terminal_bot(terminal_app.bot)

    agents_and_bots = [
        (ceo,      ceo_app.bot),
        (developer, dev_app.bot),
        (marketing, mkt_app.bot),
        (designer,  des_app.bot),
        (terminal,  terminal_app.bot),
        (browser,   browser_app.bot),
    ]

    # Handlers
    ceo_app.add_handler(make_orchestrator_handler(agents_and_bots))
    ceo_app.add_handler(make_approval_callback_handler(agents_and_bots))
    ceo_app.add_handler(make_run_handler(agents_and_bots))
    ceo_app.add_handler(make_sandbox_handler())
    ceo_app.add_handler(make_browse_handler(agents_and_bots))
    ceo_app.add_handler(make_rollback_handler(agents_and_bots))
    ceo_app.add_handler(make_goals_handler())
    ceo_app.add_handler(make_health_handler())
    ceo_app.add_handler(make_search_handler())
    ceo_app.add_handler(make_permissions_handler())
    ceo_app.add_handler(make_myrole_handler())
    ceo_app.add_handler(make_git_handler())
    ceo_app.add_handler(make_filegraph_handler())
    ceo_app.add_handler(make_caveman_handler())
    ceo_app.add_handler(make_queue_handler(queue))
    ceo_app.add_handler(make_proposals_handler())
    ceo_app.add_handler(make_clear_handler())
    ceo_app.add_handler(make_memory_handler())
    ceo_app.add_handler(make_clear_memory_handler())

    all_apps = [ceo_app, dev_app, mkt_app, des_app, terminal_app, browser_app]

    async with contextlib.AsyncExitStack() as stack:
        for app in all_apps:
            await stack.enter_async_context(app)

        await ceo_app.start()
        await ceo_app.updater.start_polling(drop_pending_updates=True)
        await bus.publish(Events.AGENT_ONLINE, {"agent": "Алекс (CEO)"})

        for app, name in [
            (dev_app,      "Дэн (Dev)"),
            (mkt_app,      "Марк (Marketing)"),
            (des_app,      "Соня (Design)"),
            (terminal_app, "Терм (Terminal)"),
            (browser_app,  "Браузер (Browser)"),
        ]:
            await app.start()
            await bus.publish(Events.AGENT_ONLINE, {"agent": name})
            logger.info(f"✅ {name} — онлайн")

        # Фаза D — Live File Graph + реакция команды на изменения
        loop = asyncio.get_running_loop()
        start_file_graph_watcher(".", loop)
        file_reactor.setup(ceo_app.bot, GROUP_CHAT_ID)

        monitor.register(
            "autonomous",
            lambda: run_autonomous_loop(
                agents_and_bots[:4], GROUP_CHAT_ID, DISCUSSION_INTERVAL_MINUTES
            ),
        )
        monitor.register("dashboard", lambda: start_server(DASHBOARD_PORT))
        await monitor.start()

        logger.info(
            f"\n🏢 AI Office — Группа B запущена!\n"
            f"🌐 Dashboard: http://localhost:{DASHBOARD_PORT}\n\n"
            f"Агенты: CEO, Dev, Marketing, Design, Terminal, Browser\n\n"
            f"Новые команды:\n"
            f"  /browse <url>      — Browser Agent открывает URL\n"
            f"  /run <команда>     — Terminal Agent выполняет\n"
            f"  /sandbox <код>     — изолированный Python\n\n"
            f"Multi-machine:\n"
            f"  На другой машине: python agent_server.py --agents developer --port 8081\n"
            f"  В .env: REMOTE_DEVELOPER=http://IP:8081"
        )

        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Остановка...")
        finally:
            monitor.stop()
            queue.stop()
            agent_registry.stop()
            await close_browser()
            await ceo_app.updater.stop()
            for app in all_apps:
                await app.stop()
            logger.info("Все агенты остановлены.")


if __name__ == "__main__":
    asyncio.run(main())