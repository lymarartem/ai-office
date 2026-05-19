"""Caveman Mode — режим экономии токенов.

Глобальный переключатель: когда включён, все агенты получают добавку к
системному промпту, заставляющую отвечать предельно сжато («пещерным» стилем),
и урезанный лимит max_tokens. Это экономит выходные токены — критично при
работе на бесплатной модели с лимитами.

Уровни: off → lite → full → ultra (по нарастанию сжатия).
"""

import logging

logger = logging.getLogger(__name__)

_LEVELS = {
    "off": {
        "prompt": "",
        "max_tokens": 400,
        "label": "выключен",
    },
    "lite": {
        "prompt": (
            "📎 Режим экономии: отвечай ещё короче обычного. "
            "Только суть, без вводных слов и воды."
        ),
        "max_tokens": 300,
        "label": "lite — кратко",
    },
    "full": {
        "prompt": (
            "🪨 Режим Caveman: телеграфный стиль. Обрывки фраз, глагол + суть. "
            "Без вводных слов, без вежливости, без объяснений азов. "
            "Пример: «Redis. Закрою за день. Делал — работает.»"
        ),
        "max_tokens": 170,
        "label": "full — пещерный стиль",
    },
    "ultra": {
        "prompt": (
            "🪨 Режим Caveman ULTRA: максимальное сжатие. Ключевые слова и "
            "команды. Никаких полных предложений. 1–2 строки максимум."
        ),
        "max_tokens": 90,
        "label": "ultra — максимум сжатия",
    },
}
_ORDER = ["off", "lite", "full", "ultra"]
_BASELINE_TOKENS = 380  # типичный размер ответа без режима — для оценки экономии


class CavemanMode:
    def __init__(self):
        self.level = "off"
        self._calls = 0
        self._chars = 0

    def is_on(self) -> bool:
        return self.level != "off"

    def prompt(self) -> str:
        return _LEVELS[self.level]["prompt"]

    def max_tokens(self) -> int:
        return _LEVELS[self.level]["max_tokens"]

    def label(self) -> str:
        return _LEVELS[self.level]["label"]

    def set_level(self, level: str) -> bool:
        if level not in _LEVELS:
            return False
        self.level = level
        logger.info(f"[Caveman] Уровень: {level}")
        return True

    def toggle(self) -> str:
        self.level = "off" if self.is_on() else "full"
        logger.info(f"[Caveman] Переключён: {self.level}")
        return self.level

    def record(self, response_text: str) -> None:
        """Регистрирует ответ агента в режиме — для статистики экономии."""
        if self.is_on():
            self._calls += 1
            self._chars += len(response_text or "")

    def stats(self) -> dict:
        avg_tokens = round(self._chars / 4 / self._calls) if self._calls else 0
        saved_per = max(0, _BASELINE_TOKENS - avg_tokens)
        return {
            "level":      self.level,
            "label":      self.label(),
            "calls":      self._calls,
            "avg_tokens": avg_tokens,
            "saved_est":  saved_per * self._calls,
        }


# Глобальный инстанс
caveman = CavemanMode()
