"""
Remote control agent powered by Anthropic Claude API.
Запустить как удалённый агент: python agent_server.py --agents claude --port 8082

В .env основной машины:
  ANTHROPIC_API_KEY=sk-ant-...
  REMOTE_CLAUDE=http://192.168.1.100:8082
"""
import logging

import anthropic

import bot.memory as memory
import bot.vector_memory as vmem
import bot.planning as planning
from bot.self_healing import get_breaker
from bot.event_bus import bus, Events
from bot.caveman import caveman

logger = logging.getLogger(__name__)

_ROLE_PROMPT = """Ты — Клод (Claude), AI-агент с расширенными аналитическими способностями в команде AI Office.
Работаешь вместе с CEO (Алекс), Developer (Дэн), Marketing (Марк) и Designer (Соня).

Специализируешься на:
- Глубоком анализе и сложных многошаговых рассуждениях
- Архитектурных решениях и код-ревью
- Исследованиях и синтезе информации
- Задачах, требующих нестандартного или критического мышления

Отвечай чётко, конкретно и по делу. Используй русский язык."""


class ClaudeAgent:
    """Agent powered by the Anthropic Claude API with prompt caching and streaming."""

    def __init__(self):
        self.name  = "Клод (Claude)"
        self.model = "claude-opus-4-7"
        self._client  = anthropic.AsyncAnthropic()
        self._breaker = get_breaker(self.name)

    async def respond(self, message: str, history: list = None) -> str:
        if not self._breaker.can_call():
            logger.warning(f"[{self.name}] Circuit OPEN — fallback")
            return f"⚠️ _{self.name} перегружен, попробуй позже._"

        system_text = _ROLE_PROMPT
        for extra in (
            memory.as_context(),
            planning.build_goals_context(),
            vmem.build_context(message),
        ):
            if extra:
                system_text += f"\n\n{extra}"

        if caveman.is_on():
            system_text += f"\n\n{caveman.prompt()}"

        messages = list(history or [])
        messages.append({"role": "user", "content": message})

        max_tok = 1024 if caveman.is_on() else 4096

        try:
            result = ""
            async with self._client.messages.stream(
                model=self.model,
                max_tokens=max_tok,
                system=[{
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=messages,
                thinking={"type": "adaptive"},
            ) as stream:
                async for chunk in stream.text_stream:
                    result += chunk

            result = result.strip()
            self._breaker.on_success()
            caveman.record(result)
            vmem.store_memory(
                f"[{self.name}] {result[:200]}",
                source="agent_claude",
            )
            await bus.publish(Events.AGENT_RESPONDED, {
                "agent":    self.name,
                "message":  message[:100],
                "response": result[:100],
            })
            return result

        except anthropic.APIError as e:
            self._breaker.on_failure(e)
            logger.error(f"[{self.name}] Anthropic API error: {e}")
            raise
        except Exception as e:
            self._breaker.on_failure(e)
            logger.error(f"[{self.name}] Error: {e}")
            raise
