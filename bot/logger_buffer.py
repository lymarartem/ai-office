import logging
from collections import deque
from datetime import datetime

MAX_LOGS = 200

# Circular buffer для хранения логов в памяти
_buffer: deque = deque(maxlen=MAX_LOGS)


class BufferHandler(logging.Handler):
    """Logging handler который пишет в in-memory buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        _buffer.append({
            "time":    datetime.now().strftime("%H:%M:%S"),
            "level":   record.levelname,
            "name":    record.name.split(".")[-1],
            "message": self.format(record),
        })


def get_logs(n: int = 50) -> list:
    return list(_buffer)[-n:]


def setup() -> None:
    """Подключает BufferHandler к root logger."""
    handler = BufferHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)