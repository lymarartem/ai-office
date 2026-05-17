import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class Plugin:
    def __init__(
        self,
        name: str,
        description: str,
        func: Callable,
        example: str = "",
    ):
        self.name        = name
        self.description = description
        self.func        = func
        self.example     = example
        self.call_count  = 0
        self.error_count = 0

    async def call(self, *args, **kwargs):
        self.call_count += 1
        try:
            if asyncio.iscoroutinefunction(self.func):
                return await self.func(*args, **kwargs)
            else:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: self.func(*args, **kwargs))
        except Exception as e:
            self.error_count += 1
            logger.error(f"[Plugin:{self.name}] Error: {e}")
            return f"❌ Ошибка плагина {self.name}: {e}"


class PluginRegistry:
    def __init__(self):
        self._plugins: dict[str, Plugin] = {}

    def register(
        self,
        name: str,
        description: str,
        example: str = "",
    ) -> Callable:
        """Декоратор для регистрации плагина."""
        def decorator(func: Callable) -> Callable:
            self._plugins[name] = Plugin(
                name=name,
                description=description,
                func=func,
                example=example,
            )
            logger.info(f"[PluginRegistry] Зарегистрирован: {name}")
            return func
        return decorator

    def get(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    def all(self) -> list[Plugin]:
        return list(self._plugins.values())

    def list_for_agent(self) -> str:
        """Описание плагинов для system prompt агента."""
        if not self._plugins:
            return ""
        lines = "\n".join(
            f"- {p.name}: {p.description}. Пример: {p.example}"
            for p in self._plugins.values()
        )
        return f"Доступные инструменты:\n{lines}"

    async def call(self, name: str, *args, **kwargs):
        plugin = self.get(name)
        if not plugin:
            return f"❌ Плагин '{name}' не найден."

        from bot.event_bus import bus, Events
        await bus.publish(Events.TOOL_CALLED, {
            "tool": name, "args": str(args)[:100]
        })
        return await plugin.call(*args, **kwargs)

    def stats(self) -> list[dict]:
        return [
            {
                "name":        p.name,
                "description": p.description,
                "calls":       p.call_count,
                "errors":      p.error_count,
            }
            for p in self._plugins.values()
        ]


# Глобальный реестр
registry = PluginRegistry()