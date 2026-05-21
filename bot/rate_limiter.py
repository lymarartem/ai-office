"""Rate limiter для LLM API — token bucket.

Groq free тариф: 30 RPM (requests per minute) для llama-3.3-70b-versatile.
Чтобы не упираться в 429 (что роняет circuit breakers и уводит систему
в death spiral retry → пауза → снова retry), мы сами тормозим исходящие
вызовы до 25 RPM — с запасом, гарантированно проходит.

Реализован как классический token bucket: токены пополняются плавно
(0.42 токена/сек), запрос ждёт пока появится хотя бы один.
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class TokenBucket:
    def __init__(self, rate_per_min: int = 25):
        self.capacity: float = float(rate_per_min)
        self.tokens: float = float(rate_per_min)
        self.refill_per_sec: float = rate_per_min / 60.0
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()
        self._total_acquired = 0
        self._total_waited = 0.0

    async def acquire(self) -> None:
        """Берёт один токен. Если их нет — ждёт до пополнения."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self.tokens = min(
                    self.capacity, self.tokens + elapsed * self.refill_per_sec
                )
                self._last_refill = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    self._total_acquired += 1
                    return

                need = 1.0 - self.tokens
                wait = need / self.refill_per_sec

            if wait > 0.2:
                logger.info(f"[RateLimit] жду {wait:.1f}с до следующего токена")
            self._total_waited += wait
            await asyncio.sleep(wait + 0.05)

    def stats(self) -> dict:
        return {
            "acquired":     self._total_acquired,
            "total_wait_s": round(self._total_waited, 1),
            "tokens_now":   round(self.tokens, 1),
            "rate_per_min": int(self.capacity),
        }


# Лимитеры по провайдерам
# Gemini Free: 15 RPM — берём 12 с запасом
gemini_limiter = TokenBucket(rate_per_min=12)
# Groq Free: 30 RPM на бумаге, но TPM = 6000 — это реальный потолок при больших
# промптах (batch на 4 агентов ≈ 2000 токенов = всего 3 req/min по TPM).
# Снижаем до 15 RPM чтобы держаться в пределах TPM.
groq_limiter   = TokenBucket(rate_per_min=15)

# Backward compat — старый код мог импортить llm_limiter
llm_limiter = gemini_limiter
