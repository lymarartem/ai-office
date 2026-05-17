import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Status(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE    = "done"
    FAILED  = "failed"


@dataclass
class Task:
    id:       str
    name:     str
    func:     Callable
    args:     tuple = field(default_factory=tuple)
    kwargs:   dict  = field(default_factory=dict)
    status:   Status = Status.PENDING
    result:   Any  = None
    error:    str  = None
    created:  str  = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    started:  str  = None
    finished: str  = None


class TaskQueue:
    def __init__(self, workers: int = 3):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._tasks: dict[str, Task] = {}
        self._n_workers = workers
        self._active = False

    async def start(self) -> None:
        self._active = True
        for i in range(self._n_workers):
            asyncio.create_task(self._worker(f"w{i}"))
        logger.info(f"TaskQueue started ({self._n_workers} workers)")

    async def push(
        self, task_id: str, name: str, func: Callable, *args, **kwargs
    ) -> Task:
        task = Task(id=task_id, name=name, func=func, args=args, kwargs=kwargs)
        self._tasks[task_id] = task
        await self._queue.put(task)
        logger.info(f"[Queue] ← {name} ({task_id})")
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def all(self) -> list:
        return list(self._tasks.values())

    def pending(self) -> list:
        return [t for t in self._tasks.values() if t.status == Status.PENDING]

    def stop(self) -> None:
        self._active = False

    async def _worker(self, name: str) -> None:
        while self._active:
            try:
                task: Task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            task.status  = Status.RUNNING
            task.started = datetime.now().strftime("%H:%M:%S")
            logger.info(f"[{name}] → {task.name}")

            try:
                if asyncio.iscoroutinefunction(task.func):
                    task.result = await task.func(*task.args, **task.kwargs)
                else:
                    loop = asyncio.get_event_loop()
                    task.result = await loop.run_in_executor(
                        None, lambda: task.func(*task.args, **task.kwargs)
                    )
                task.status = Status.DONE
            except Exception as e:
                task.status = Status.FAILED
                task.error  = str(e)
                logger.error(f"[{name}] FAILED {task.name}: {e}")
            finally:
                task.finished = datetime.now().strftime("%H:%M:%S")
                self._queue.task_done()
                logger.info(f"[{name}] ✓ {task.name} → {task.status.value}")


# Глобальный инстанс
queue = TaskQueue(workers=3)