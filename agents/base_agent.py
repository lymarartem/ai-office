import asyncio
import json
import logging
import re
import requests

from config import (
    GEMINI_API_KEY, GROQ_API_KEY,
    PRIMARY_API_URL, FALLBACK_API_URL,
    FALLBACK_MODEL,
)
import bot.memory as memory
import bot.vector_memory as vmem
import bot.planning as planning
from bot.self_healing import get_breaker, retry
from bot.event_bus import bus, Events
from bot.rate_limiter import gemini_limiter, groq_limiter

logger = logging.getLogger(__name__)

# Паттерн для вызова инструмента агентом
# Агент пишет: [TOOL:tool_name("arg1", "arg2")]
TOOL_PATTERN = re.compile(r'\[TOOL:(\w+)\(([^)]*)\)\]')


class BaseAgent:
    def __init__(self, name: str, role_prompt: str, model: str):
        self.name        = name
        self.role_prompt = role_prompt
        self.model       = model
        self._breaker    = get_breaker(name)

    @retry(max_attempts=3, backoff=2.0)
    async def respond(self, message: str, history: list = None) -> str:
        if not self._breaker.can_call():
            logger.warning(f"[{self.name}] Circuit OPEN — fallback")
            return f"⚠️ _{self.name} перегружен, попробуй позже._"

        # Контекст
        team_memory   = memory.as_context()
        goals_context = planning.build_goals_context()
        vector_ctx    = vmem.build_context(message)

        # Инструменты не инжектим в промпт — Llama 3.3 ломает формат [TOOL:...]
        # и текст утекает в чат. Tool-вызовы остаются доступны через прямые команды.

        system = self.role_prompt
        for extra in (team_memory, goals_context, vector_ctx):
            if extra:
                system += f"\n\n{extra}"

        # Caveman Mode — режим экономии токенов
        from bot.caveman import caveman
        if caveman.is_on():
            system += f"\n\n{caveman.prompt()}"

        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        # Hybrid: пробуем Gemini (primary), при сбое — Groq (fallback).
        # Каждый со своим rate limiter, чтобы не упираться в 429.
        loop = asyncio.get_event_loop()
        max_tok = caveman.max_tokens()

        try:
            await gemini_limiter.acquire()
            result = await loop.run_in_executor(
                None, self._call_provider,
                PRIMARY_API_URL, GEMINI_API_KEY, self.model, messages, max_tok,
            )
        except Exception as primary_err:
            logger.warning(
                f"[{self.name}] Gemini не ответил ({primary_err}), fallback → Groq"
            )
            try:
                await groq_limiter.acquire()
                result = await loop.run_in_executor(
                    None, self._call_provider,
                    FALLBACK_API_URL, GROQ_API_KEY, FALLBACK_MODEL, messages, max_tok,
                )
            except Exception as fb_err:
                self._breaker.on_failure(fb_err)
                raise

        try:
            self._breaker.on_success()

            # Чистим само-префикс ("Дэн (Dev):" в начале) — Llama любит подписываться сама
            prefix_pat = re.compile(
                rf"^(?:{re.escape(self.name)}\s*:\s*)+", re.IGNORECASE
            )
            result = prefix_pat.sub("", result).strip()

            # Tool-вызовы из чата отключены — Llama ломает формат (передаёт \n как
            # литералы), sandbox падает и ошибки утекают в чат. Tools доступны
            # через прямые команды /run, /sandbox.
            # result = await self._process_tools(result)

            # Статистика режима экономии
            caveman.record(result)

            # Сохраняем в vector memory
            vmem.store_memory(
                f"[{self.name}] {result[:200]}",
                source=f"agent_{self.name.split()[0].lower()}",
            )

            # Публикуем событие
            await bus.publish(Events.AGENT_RESPONDED, {
                "agent":    self.name,
                "message":  message[:100],
                "response": result[:100],
            })

            return result

        except Exception as e:
            self._breaker.on_failure(e)
            raise

    async def _process_tools(self, text: str) -> str:
        """Находит вызовы инструментов в тексте и выполняет их."""
        from bot.plugins.registry import registry

        matches = TOOL_PATTERN.findall(text)
        if not matches:
            return text

        result = text
        for tool_name, args_str in matches:
            try:
                # Парсим аргументы
                args = []
                if args_str.strip():
                    for arg in args_str.split(","):
                        arg = arg.strip().strip('"\'')
                        args.append(arg)

                tool_result = await registry.call(tool_name, *args)
                placeholder = f'[TOOL:{tool_name}({args_str})]'
                result = result.replace(
                    placeholder,
                    f"\n\n🔧 *{tool_name}:*\n{tool_result}\n"
                )
                logger.info(f"[{self.name}] Tool {tool_name} выполнен")
            except Exception as e:
                logger.error(f"[{self.name}] Tool error: {e}")

        return result

    def _call_provider(
        self, url: str, key: str, model: str, messages: list, max_tokens: int = 400
    ) -> str:
        """Универсальный вызов OpenAI-совместимого endpoint (Gemini или Groq)."""
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       model,
                "messages":    messages,
                "max_tokens":  max_tokens,
                "temperature": 0.85,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()