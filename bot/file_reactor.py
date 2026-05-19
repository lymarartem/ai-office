"""File Reactor — Фаза D, реакция команды на изменения кода.

Подписывается на события FILE_CHANGED / FILE_CREATED / FILE_DELETED из шины
и публикует в групповой чат сводку: что изменилось и какие модули это затронет
(по графу зависимостей). Изменения критичных файлов помечаются как требующие
ревью и порождают событие TASK_CREATED.

События накапливаются и отправляются пачкой раз в N секунд — без спама.
"""

import asyncio
import logging
import time

from bot.event_bus import bus, Events
from bot.file_graph import graph

logger = logging.getLogger(__name__)

# Файлы, изменение которых требует ревью перед деплоем
_CRITICAL = {
    "config.py",
    "main.py",
    "bot/handlers.py",
    "bot/event_bus.py",
    "requirements.txt",
}
_FLUSH_DELAY   = 6.0    # секунд — окно накопления событий
_AUTO_TEST     = True   # авто-прогон тестов при изменении кода
_TEST_COOLDOWN = 90.0   # не чаще, чем раз в N секунд


class FileReactor:
    def __init__(self):
        self._bot = None
        self._chat_id: int | None = None
        self._pending: dict[str, dict] = {}
        self._flush_scheduled = False
        self._last_test = 0.0

    def setup(self, bot, chat_id: int) -> None:
        """Подключает реактор: bot — экземпляр Telegram-бота, chat_id — группа."""
        self._bot = bot
        self._chat_id = chat_id
        bus.subscribe(Events.FILE_CHANGED, self.on_event)
        bus.subscribe(Events.FILE_CREATED, self.on_event)
        bus.subscribe(Events.FILE_DELETED, self.on_event)
        logger.info("[FileReactor] Подписан на события файлов")

    async def on_event(self, event: dict) -> None:
        data = event.get("data", {})
        path = data.get("path", "")
        # реагируем только на исходники Python
        if not path.endswith(".py"):
            return
        self._pending[path] = data
        if not self._flush_scheduled:
            self._flush_scheduled = True
            asyncio.create_task(self._flush_after(_FLUSH_DELAY))

    async def _flush_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        pending = dict(self._pending)
        self._pending.clear()
        self._flush_scheduled = False
        if pending and self._bot and self._chat_id:
            await self._send_summary(pending)
            if _AUTO_TEST:
                await self._run_tests_if_due()

    async def _send_summary(self, pending: dict[str, dict]) -> None:
        icons = {"modified": "✏️", "created": "🆕", "deleted": "🗑"}
        lines = ["🔔 *Команда заметила изменения в коде*", ""]

        affected: set[str] = set()
        for path, data in pending.items():
            kind = data.get("kind", "modified")
            lines.append(f"{icons.get(kind, '•')} `{path}`")
            for dep in graph.affected_by(path):
                affected.add(dep)
        affected -= set(pending)

        if affected:
            shown = ", ".join(f"`{a}`" for a in sorted(affected)[:12])
            lines.append("")
            lines.append(f"⚠️ Затронутые модули: {shown}")

        critical = sorted(p for p in pending if p in _CRITICAL)
        if critical:
            lines.append("")
            lines.append(
                "🚨 Изменены критичные файлы — нужен ревью перед деплоем: "
                + ", ".join(f"`{c}`" for c in critical)
            )
            await bus.publish(Events.TASK_CREATED, {
                "reason": "Изменены критичные файлы",
                "files":  critical,
            })

        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text="\n".join(lines),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"[FileReactor] Ошибка отправки: {e}")

    async def _run_tests_if_due(self) -> None:
        """Прогон тестов после изменения кода. С защитой от частых запусков."""
        now = time.time()
        if now - self._last_test < _TEST_COOLDOWN:
            logger.info("[FileReactor] Тесты пропущены — cooldown")
            return
        self._last_test = now

        try:
            from bot.pipeline import run_tests
        except Exception as e:
            logger.error(f"[FileReactor] run_tests недоступен: {e}")
            return

        await self._safe_send("🧪 *Terminal* — изменился код, прогоняю тесты...")

        loop = asyncio.get_running_loop()
        try:
            passed, output = await loop.run_in_executor(None, run_tests, ".")
        except Exception as e:
            logger.error(f"[FileReactor] Ошибка тестов: {e}")
            await self._safe_send(f"⚠️ Не удалось запустить тесты: `{e}`")
            return

        await bus.publish(Events.TESTS_COMPLETED, {
            "passed": passed,
            "output": output[:200],
        })
        icon = "✅ прошли" if passed else "❌ упали"
        await self._safe_send(
            f"🧪 *Тесты {icon}*\n```\n{output[:300]}\n```"
        )

    async def _safe_send(self, text: str) -> None:
        try:
            await self._bot.send_message(
                chat_id=self._chat_id, text=text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"[FileReactor] Ошибка отправки: {e}")


# Глобальный инстанс
reactor = FileReactor()
