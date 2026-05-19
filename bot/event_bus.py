import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)

# Типы событий
class Events:
    AGENT_RESPONDED      = "agent_responded"
    PROPOSAL_CREATED     = "proposal_created"
    PROPOSAL_APPROVED    = "proposal_approved"
    PROPOSAL_REJECTED    = "proposal_rejected"
    PIPELINE_STARTED     = "pipeline_started"
    PIPELINE_STAGE       = "pipeline_stage"
    PIPELINE_DONE        = "pipeline_done"
    PIPELINE_FAILED      = "pipeline_failed"
    GOAL_CREATED         = "goal_created"
    GOAL_UPDATED         = "goal_updated"
    HEALTH_ALERT         = "health_alert"
    TOOL_CALLED          = "tool_called"
    SANDBOX_EXECUTED     = "sandbox_executed"
    AGENT_ONLINE         = "agent_online"
    DISCUSSION_STARTED   = "discussion_started"
    # Фаза D — Live File Graph
    FILE_CHANGED         = "file_changed"
    FILE_CREATED         = "file_created"
    FILE_DELETED         = "file_deleted"
    TESTS_COMPLETED      = "tests_completed"
    ERROR_FOUND          = "error_found"
    TASK_CREATED         = "task_created"


class EventBus:
    """Asyncio pub/sub event bus с WebSocket стримингом."""

    def __init__(self):
        self._handlers:    dict[str, list[Callable]] = defaultdict(list)
        self._ws_clients:  set  = set()
        self._event_log:   list = []
        self._max_log:     int  = 500

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)
        logger.debug(f"[EventBus] Subscribe: {event_type} → {handler.__name__}")

    def subscribe_all(self, handler: Callable) -> None:
        self._handlers["*"].append(handler)

    async def publish(self, event_type: str, data: dict = None) -> None:
        event = {
            "type":      event_type,
            "data":      data or {},
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "date":      datetime.now().isoformat(),
        }
        self._event_log.append(event)
        if len(self._event_log) > self._max_log:
            self._event_log = self._event_log[-self._max_log:]

        logger.info(f"[EventBus] ▶ {event_type}: {str(data)[:80]}")

        # Вызываем подписчиков
        handlers = self._handlers.get(event_type, []) + self._handlers.get("*", [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"[EventBus] Handler error: {e}")

        # Стримим WebSocket клиентам
        if self._ws_clients:
            msg = json.dumps(event, ensure_ascii=False)
            dead = set()
            for ws in self._ws_clients:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.add(ws)
            self._ws_clients -= dead

    def publish_threadsafe(self, loop, event_type: str, data: dict = None) -> None:
        """Публикация события из другого потока (например, watchdog Observer).

        Шина асинхронная и живёт в основном event loop. Сторонние потоки
        не могут вызвать await publish() напрямую — используют этот мост.
        """
        try:
            asyncio.run_coroutine_threadsafe(
                self.publish(event_type, data), loop
            )
        except Exception as e:
            logger.error(f"[EventBus] threadsafe publish error: {e}")

    def register_ws(self, ws) -> None:
        self._ws_clients.add(ws)
        logger.info(f"[EventBus] WS клиент подключён. Всего: {len(self._ws_clients)}")

    def unregister_ws(self, ws) -> None:
        self._ws_clients.discard(ws)

    def get_log(self, n: int = 50) -> list:
        return self._event_log[-n:]

    def get_log_by_type(self, event_type: str) -> list:
        return [e for e in self._event_log if e["type"] == event_type]


# Глобальный инстанс
bus = EventBus()