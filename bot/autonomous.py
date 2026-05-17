import asyncio
import json
import logging
import random

import bot.memory as memory
import bot.approval as approval
import bot.vector_memory as vmem
import bot.planning as planning

logger = logging.getLogger(__name__)

TOPICS = [
    "Что в нашей работе сейчас самое узкое место?",
    "Какой инструмент или технологию стоит попробовать?",
    "Если бы у нас был неограниченный бюджет на месяц — что бы сделали?",
    "Что конкуренты делают лучше нас?",
    "Как сократить время от идеи до результата?",
    "Какую фичу пользователи хотят, а мы не сделали?",
    "Наш самый большой технический долг прямо сейчас?",
    "Как улучшить онбординг новых пользователей?",
    "Что мы делаем вручную, но надо автоматизировать?",
    "Какой тренд в AI стоит взять на вооружение?",
    "Что нам мешает расти быстрее?",
    "Как сделать продукт заметнее среди конкурентов?",
    "Какие метрики мы должны отслеживать, но не отслеживаем?",
    "Как мы общаемся с пользователями — что можно улучшить?",
    "Что бы мы сделали иначе, если бы начинали с нуля?",
]


async def run_autonomous_loop(
    agents_and_bots: list,
    chat_id: int,
    interval_minutes: int,
) -> None:
    logger.info(f"🤖 Автономные обсуждения активны. Интервал: {interval_minutes} мин.")
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            await _run_one_discussion(agents_and_bots, chat_id)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка в обсуждении: {e}")


async def _run_one_discussion(agents_and_bots: list, chat_id: int) -> None:
    ceo_agent, ceo_bot = agents_and_bots[0]

    # Иногда обсуждаем прогресс по целям вместо случайной темы
    active_goals = planning.active_goals()
    if active_goals and random.random() < 0.3:
        goal = random.choice(active_goals)
        topic = f"Как продвигается цель '{goal['title']}'? Прогресс: {goal['progress']}%"
    else:
        topic = random.choice(TOPICS)

    opener = await ceo_agent.respond(
        message=(
            f"Начни короткое обсуждение в рабочем чате.\n"
            f"Тема: {topic}\n"
            f"1-2 предложения. Живо, без формальщины."
        )
    )

    discussion = [{"name": ceo_agent.name, "text": opener}]
    await ceo_bot.send_message(chat_id=chat_id, text=f"💬 {opener}", parse_mode="Markdown")
    logger.info(f"🗣 Обсуждение: {topic[:50]}...")

    for agent, bot in agents_and_bots[1:]:
        await asyncio.sleep(random.uniform(2.5, 5.0))
        context = "\n".join(f"[{r['name']}]: {r['text']}" for r in discussion)
        response = await agent.respond(
            message=(
                f"В рабочем чате идёт обсуждение:\n\n{context}\n\n"
                f"Ты — {agent.name}. Ответь коротко от своей роли. 1-2 предложения."
            )
        )
        discussion.append({"name": agent.name, "text": response})
        await bot.send_message(chat_id=chat_id, text=response, parse_mode="Markdown")

    await asyncio.sleep(3.0)
    full = "\n".join(f"[{r['name']}]: {r['text']}" for r in discussion)

    # Сохраняем решение
    decision = await ceo_agent.respond(
        message=(
            f"Обсуждение:\n\n{full}\n\n"
            f"Сформулируй ОДНО конкретное решение которое команда должна запомнить. "
            f"1 предложение. Только само решение."
        )
    )
    memory.save(decision=decision, source="autonomous_discussion")
    vmem.store_decision(decision, proposal_id=None)

    # CEO проверяет — нужно ли создать цель
    try:
        goal_json = await ceo_agent.respond(
            message=(
                f"Обсуждение:\n\n{full}\n\n"
                f"Есть ли здесь долгосрочная цель которую стоит отслеживать?\n"
                f"Если да:\n"
                f'{{"has_goal": true, "title": "...", "description": "...", '
                f'"milestones": ["шаг1", "шаг2", "шаг3"]}}\n'
                f'Если нет: {{"has_goal": false}}\n'
                f"Только JSON."
            )
        )
        clean = goal_json.strip().strip("```json").strip("```").strip()
        gdata = json.loads(clean)

        if gdata.get("has_goal"):
            gid = planning.create_goal(
                title=gdata["title"],
                description=gdata.get("description", ""),
                milestones=gdata.get("milestones", []),
                agent=ceo_agent.name,
            )
            await ceo_bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🎯 *Новая цель {gid}:* {gdata['title']}\n"
                    f"_{gdata.get('description', '')}_\n\n"
                    f"Отслеживай: `/goals`"
                ),
                parse_mode="Markdown",
            )
            logger.info(f"Создана цель {gid}: {gdata['title']}")
        else:
            await ceo_bot.send_message(
                chat_id=chat_id,
                text=f"📌 *Записал:* {decision}",
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.debug(f"Goal extraction error: {e}")
        await ceo_bot.send_message(
            chat_id=chat_id,
            text=f"📌 *Записал:* {decision}",
            parse_mode="Markdown",
        )