import asyncio
import json
import logging
import random
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)

import bot.memory as memory
import bot.approval as approval
import bot.permissions as perms
import bot.vector_memory as vmem
import bot.planning as planning
import bot.terminal_runner as terminal_runner
from bot.pipeline import Pipeline, run_tests
from bot.dashboard import track_call
from bot.self_healing import all_breakers, monitor
from bot.isolated_runner import execute as sandbox_execute, format_result

logger = logging.getLogger(__name__)

PASS_SIGNAL = "PASS"
MAX_HISTORY_TURNS = 10

chat_histories: dict = defaultdict(list)
_awaiting_revise: dict = {}
_awaiting_clarification: dict = {}
_pipelines: dict = {}

# Terminal bot instance (устанавливается в main.py)
_terminal_bot = None


def set_terminal_bot(bot) -> None:
    global _terminal_bot
    _terminal_bot = bot


def _trim(history: list) -> list:
    limit = MAX_HISTORY_TURNS * 2
    return history[-limit:] if len(history) > limit else history


def _approval_keyboard(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{pid}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject:{pid}"),
        InlineKeyboardButton("✏️ Revise",  callback_data=f"revise:{pid}"),
    ]])


async def _ceo_route(ceo_agent, message: str) -> dict:
    prompt = (
        f"Сообщение: {message}\n\n"
        f"Ты CEO. Реши:\n"
        f"1. Нужно ли уточнение?\n"
        f"2. Каких агентов вызвать? (developer, marketing, designer, terminal)\n\n"
        f"Правила:\n"
        f"- Код/техн → developer\n"
        f"- Запуск команд/тестов/скриптов → terminal\n"
        f"- Продвижение → marketing\n"
        f"- Дизайн → designer\n"
        f"- Общий → developer, marketing, designer\n\n"
        f"Верни ТОЛЬКО JSON:\n"
        f'{{"needs_clarification": false, "agents": ["developer"]}}\n'
        f'или {{"needs_clarification": true, "question": "Вопрос"}}'
    )
    try:
        raw   = await ceo_agent.respond(message=prompt)
        clean = raw.strip().strip("```json").strip("```").strip()
        return json.loads(clean)
    except Exception as e:
        logger.error(f"Route error: {e}")
        return {"needs_clarification": False,
                "agents": ["developer", "marketing", "designer"]}


async def _create_proposal_with_tests(
    ceo_agent, ceo_bot, chat_id: int, data: dict
) -> None:
    await ceo_bot.send_message(
        chat_id=chat_id,
        text="🧪 *Pre-tests* — запускаю...",
        parse_mode="Markdown",
    )
    loop = asyncio.get_event_loop()
    passed, output = await loop.run_in_executor(None, run_tests, ".")

    pid = approval.create(
        agent_name=ceo_agent.name,
        title=data.get("title", "Без названия"),
        what=data.get("what", "—"),
        why=data.get("why", "—"),
        risks=data.get("risks", "—"),
        files=data.get("files", []),
        pre_test_passed=passed,
        pre_test_output=output,
    )
    p = approval.get(pid)
    vmem.store_proposal_context(pid, p["title"], p["what"], p["why"])

    icon = "✅" if passed else "❌"
    await ceo_bot.send_message(
        chat_id=chat_id,
        text=f"🧪 *Pre-tests:* {icon}\n```\n{output[:300]}\n```",
        parse_mode="Markdown",
    )
    await ceo_bot.send_message(
        chat_id=chat_id,
        text=approval.format_proposal(p),
        parse_mode="Markdown",
        reply_markup=_approval_keyboard(pid),
    )


class TaskContext:
    def __init__(self, user_message: str):
        self.user_message = user_message
        self._responses: list = []

    def add(self, agent_name: str, response: str) -> None:
        self._responses.append({"name": agent_name, "text": response})
        track_call(agent_name)

    def build_prompt(self) -> str:
        if not self._responses:
            return self.user_message
        lines = "\n".join(f"[{r['name']}]: {r['text']}" for r in self._responses)
        return (
            f"{self.user_message}\n\nКоллеги уже ответили:\n{lines}\n\n"
            f"Твоя очередь — добавь своё. Не повторяй чужое."
        )

    def build_reaction_prompt(self, agent_name: str) -> str:
        lines = "\n".join(f"[{r['name']}]: {r['text']}" for r in self._responses)
        return (
            f"Вопрос: {self.user_message}\n\nКоманда:\n{lines}\n\n"
            f"Ты — {agent_name}. Возразить? Да: 1-2 предложения. "
            f"Нет: одно слово {PASS_SIGNAL}"
        )

    def build_proposal_prompt(self) -> str:
        lines = "\n".join(f"[{r['name']}]: {r['text']}" for r in self._responses)
        return (
            f"Обсуждение:\n{lines}\n\n"
            f"Есть предложение по изменению кода/архитектуры?\n"
            f"Если да: "
            f'{{"has_proposal":true,"title":"...","what":"...","why":"...","risks":"...","files":[...]}}\n'
            f'Если нет: {{"has_proposal":false}}\nТолько JSON.'
        )

    def as_assistant_entry(self) -> str:
        return "\n".join(f"[{r['name']}]: {r['text']}" for r in self._responses)


async def _run_agents(
    chat_id: int,
    full_user_msg: str,
    selected_agents: list,
    all_agents_map: dict,
    ceo_agent,
    ceo_bot,
    history: list,
) -> None:
    task_ctx = TaskContext(full_user_msg)

    for agent_key in selected_agents:
        pair = all_agents_map.get(agent_key)
        if not pair:
            continue
        agent, bot = pair
        await asyncio.sleep(random.uniform(1.5, 3.0))
        try:
            response = await agent.respond(
                message=task_ctx.build_prompt(), history=history[:-1]
            )
            task_ctx.add(agent.name, response)
            await bot.send_message(
                chat_id=chat_id, text=response, parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"[{agent_key}] Ошибка: {e}")

    entry = task_ctx.as_assistant_entry()
    if entry:
        chat_histories[chat_id].append({"role": "assistant", "content": entry})
        chat_histories[chat_id] = _trim(chat_histories[chat_id])
        vmem.store_memory(entry, source="group_chat")

    active_pairs = [all_agents_map[k] for k in selected_agents if k in all_agents_map]
    if len(active_pairs) >= 2:
        reactors = random.sample(active_pairs, k=min(2, len(active_pairs)))
        await asyncio.sleep(2.0)
        for agent, bot in reactors:
            await asyncio.sleep(random.uniform(1.0, 2.5))
            try:
                reaction = await agent.respond(
                    message=task_ctx.build_reaction_prompt(agent.name),
                    history=chat_histories[chat_id],
                )
                if reaction.strip().upper() == PASS_SIGNAL:
                    continue
                await bot.send_message(
                    chat_id=chat_id, text=f"↩️ {reaction}", parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Reaction error: {e}")

    await asyncio.sleep(2.0)
    try:
        raw   = await ceo_agent.respond(message=task_ctx.build_proposal_prompt())
        clean = raw.strip().strip("```json").strip("```").strip()
        data  = json.loads(clean)
        if data.get("has_proposal"):
            await _create_proposal_with_tests(ceo_agent, ceo_bot, chat_id, data)
    except Exception as e:
        logger.debug(f"Proposal не сгенерирован: {e}")


def make_orchestrator_handler(agents_and_bots: list) -> MessageHandler:
    ceo_agent, ceo_bot = agents_and_bots[0]
    all_agents_map = {
        "developer": agents_and_bots[1],
        "marketing": agents_and_bots[2],
        "designer":  agents_and_bots[3],
        "terminal":  agents_and_bots[4],
    }

    async def handle_message(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message is None:
            return
        if update.message.chat.type not in ("group", "supergroup"):
            return
        if update.message.from_user and update.message.from_user.is_bot:
            return

        text = update.message.text
        if not text or not text.strip():
            return

        user_id   = update.message.from_user.id
        user_name = update.message.from_user.first_name or "Коллега"
        chat_id   = update.message.chat_id

        if user_id in _awaiting_revise:
            pid = _awaiting_revise.pop(user_id)
            approval.update(pid, "revised", feedback=text)
            p = approval.get(pid)
            memory.save(
                f"Предложение {pid} '{p['title']}' на ревизии: {text}",
                source="human_revise",
            )
            await update.message.reply_text(
                f"✏️ *{pid}* на доработке.\n💬 {text}", parse_mode="Markdown"
            )
            return

        full_user_msg = f"{user_name}: {text}"

        if chat_id in _awaiting_clarification:
            state    = _awaiting_clarification.pop(chat_id)
            combined = f"{state['original']}\nУточнение: {text}"
            history  = chat_histories[chat_id]
            history.append({"role": "user", "content": combined})
            chat_histories[chat_id] = _trim(history)
            await _run_agents(
                chat_id=chat_id, full_user_msg=combined,
                selected_agents=state["agents"], all_agents_map=all_agents_map,
                ceo_agent=ceo_agent, ceo_bot=ceo_bot,
                history=chat_histories[chat_id],
            )
            return

        history = chat_histories[chat_id]
        history.append({"role": "user", "content": full_user_msg})
        chat_histories[chat_id] = _trim(history)

        routing = await _ceo_route(ceo_agent, full_user_msg)

        if routing.get("needs_clarification"):
            _awaiting_clarification[chat_id] = {
                "original": full_user_msg,
                "agents":   ["developer", "marketing", "designer"],
            }
            await ceo_bot.send_message(
                chat_id=chat_id,
                text=f"🤔 {routing.get('question', 'Можешь уточнить?')}",
                parse_mode="Markdown",
            )
            return

        selected = routing.get("agents", ["developer", "marketing", "designer"])
        await _run_agents(
            chat_id=chat_id, full_user_msg=full_user_msg,
            selected_agents=selected, all_agents_map=all_agents_map,
            ceo_agent=ceo_agent, ceo_bot=ceo_bot,
            history=chat_histories[chat_id],
        )

    return MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)


def make_approval_callback_handler(agents_and_bots: list) -> CallbackQueryHandler:
    ceo_agent, ceo_bot = agents_and_bots[0]
    dev_agent, _       = agents_and_bots[1]

    async def handle_callback(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query   = update.callback_query
        user_id = query.from_user.id
        await query.answer()

        data    = query.data
        chat_id = query.message.chat_id

        # Terminal execution callbacks
        if data.startswith("exec_approve:"):
            exec_id = data.split(":", 1)[1]
            await query.edit_message_reply_markup(reply_markup=None)
            await terminal_runner.execute_approved(exec_id, _terminal_bot)
            return

        if data.startswith("exec_cancel:"):
            exec_id = data.split(":", 1)[1]
            await query.edit_message_reply_markup(reply_markup=None)
            await terminal_runner.cancel_execution(exec_id, _terminal_bot, chat_id)
            return

        action, pid = data.split(":", 1)

        if action == "deploy":
            if not perms.can(user_id, "deploy"):
                await query.message.reply_text(
                    perms.format_denied("deploy"), parse_mode="Markdown"
                )
                return
            pipeline = _pipelines.get(pid) or Pipeline(pid, dev_agent, ceo_bot, chat_id)
            await query.edit_message_reply_markup(reply_markup=None)
            await pipeline.deploy()
            return

        if action == "cancel_deploy":
            await query.edit_message_text("🗑 Deploy отменён.")
            return

        p = approval.get(pid)
        if not p:
            await query.edit_message_text(f"❓ {pid} не найден.")
            return

        if action == "approve":
            if not perms.can(user_id, "approve"):
                await query.message.reply_text(
                    perms.format_denied("approve"), parse_mode="Markdown"
                )
                return
            approval.update(pid, "approved")
            memory.save(f"ОДОБРЕНО: {p['title']} — {p['what']}", source="human_approved")
            vmem.store_decision(f"ОДОБРЕНО: {p['title']}", proposal_id=pid)
            await query.edit_message_text(
                approval.format_proposal(approval.get(pid)), parse_mode="Markdown"
            )
            await query.message.reply_text(
                f"✅ *{pid} одобрено.* Запускаю pipeline...", parse_mode="Markdown"
            )
            pipeline = Pipeline(pid, dev_agent, ceo_bot, chat_id)
            _pipelines[pid] = pipeline
            asyncio.create_task(pipeline.run(p))

        elif action == "reject":
            if not perms.can(user_id, "reject"):
                await query.message.reply_text(
                    perms.format_denied("reject"), parse_mode="Markdown"
                )
                return
            approval.update(pid, "rejected")
            memory.save(f"ОТКЛОНЕНО: {p['title']}", source="human_rejected")
            vmem.store_decision(f"ОТКЛОНЕНО: {p['title']}", proposal_id=pid)
            await query.edit_message_text(
                approval.format_proposal(approval.get(pid)), parse_mode="Markdown"
            )
            await query.message.reply_text(
                f"❌ *{pid} отклонено.*", parse_mode="Markdown"
            )

        elif action == "revise":
            if not perms.can(user_id, "revise"):
                await query.message.reply_text(
                    perms.format_denied("revise"), parse_mode="Markdown"
                )
                return
            _awaiting_revise[user_id] = pid
            await query.message.reply_text(
                f"✏️ *Ревизия {pid}.* Напиши фидбэк:", parse_mode="Markdown"
            )

    return CallbackQueryHandler(handle_callback)


def make_run_handler(agents_and_bots: list) -> CommandHandler:
    """/run <команда> — Terminal Agent выполняет команду."""
    _, terminal_bot = agents_and_bots[4]

    async def run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        user_id = update.message.from_user.id
        if not perms.can(user_id, "approve"):
            await update.message.reply_text(
                "🚫 Нет прав для выполнения команд.", parse_mode="Markdown"
            )
            return
        if not context.args:
            await update.message.reply_text(
                terminal_runner.format_help(), parse_mode="Markdown"
            )
            return
        cmd     = " ".join(context.args)
        chat_id = update.message.chat_id
        await terminal_runner.execute(
            cmd=cmd,
            terminal_bot=terminal_bot,
            chat_id=chat_id,
        )

    return CommandHandler("run", run_cmd)


def make_sandbox_handler() -> CommandHandler:
    """/sandbox <код> — запуск в изолированной среде."""

    async def sandbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        if not context.args:
            await update.message.reply_text(
                "Использование: `/sandbox print('hello')`", parse_mode="Markdown"
            )
            return
        code    = " ".join(context.args)
        result  = await sandbox_execute(code, language="python")
        await update.message.reply_text(
            format_result(result), parse_mode="Markdown"
        )

    return CommandHandler("sandbox", sandbox_cmd)
def make_browse_handler(agents_and_bots: list) -> CommandHandler:
    """/browse <url> — Browser Agent открывает страницу и присылает скриншот."""
    _, browser_bot = agents_and_bots[5]

    async def browse_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        if not context.args:
            await update.message.reply_text(
                "Использование: `/browse https://example.com`",
                parse_mode="Markdown",
            )
            return

        url     = context.args[0]
        chat_id = update.message.chat_id

        await browser_bot.send_message(
            chat_id=chat_id,
            text=f"🌐 *Браузер:* Открываю `{url}`...",
            parse_mode="Markdown",
        )

        from bot.browser_runner import screenshot, get_content
        import os

        # Скриншот
        shot = await screenshot(url)
        if shot["success"]:
            await browser_bot.send_photo(
                chat_id=chat_id,
                photo=open(shot["path"], "rb"),
                caption=f"📸 *{shot['title']}*\n{url} | {shot['duration']}с",
                parse_mode="Markdown",
            )
            os.unlink(shot["path"])
        else:
            await browser_bot.send_message(
                chat_id=chat_id,
                text=f"❌ Скриншот не удался: {shot.get('error', '?')}",
            )

        # Контент
        content = await get_content(url)
        if content["success"]:
            text = content["content"][:800]
            await browser_bot.send_message(
                chat_id=chat_id,
                text=f"📄 *Контент:*\n{text}...",
                parse_mode="Markdown",
            )

    return CommandHandler("browse", browse_cmd)

def make_rollback_handler(agents_and_bots: list) -> CommandHandler:
    _, ceo_bot   = agents_and_bots[0]
    dev_agent, _ = agents_and_bots[1]

    async def rollback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        user_id = update.message.from_user.id
        if not perms.can(user_id, "rollback"):
            await update.message.reply_text(
                perms.format_denied("rollback"), parse_mode="Markdown"
            )
            return
        args = context.args
        if not args:
            await update.message.reply_text(
                "Укажи ID: `/rollback P001`", parse_mode="Markdown"
            )
            return
        pid      = args[0].upper()
        chat_id  = update.message.chat_id
        pipeline = _pipelines.get(pid) or Pipeline(pid, dev_agent, ceo_bot, chat_id)
        _pipelines[pid] = pipeline
        await pipeline.rollback()

    return CommandHandler("rollback", rollback)


def make_goals_handler() -> CommandHandler:

    async def goals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        args = context.args

        if args and args[0] == "progress" and len(args) >= 3:
            gid      = args[1].upper()
            progress = int(args[2])
            note     = " ".join(args[3:]) if len(args) > 3 else None
            if planning.update_progress(gid, progress, note):
                g = planning.get_goal(gid)
                await update.message.reply_text(
                    planning.format_goal(g), parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(f"❓ Цель {gid} не найдена.")
            return

        if args and args[0] == "done" and len(args) == 2:
            gid = args[1].upper()
            if planning.complete_goal(gid):
                await update.message.reply_text(
                    f"✅ Цель *{gid}* выполнена!", parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(f"❓ Цель {gid} не найдена.")
            return

        goals = planning.active_goals()
        if not goals:
            await update.message.reply_text(
                "🎯 Активных целей нет.\n\n"
                "`/goals progress G001 75 'заметка'` — прогресс\n"
                "`/goals done G001` — закрыть",
                parse_mode="Markdown",
            )
            return
        for g in goals:
            await update.message.reply_text(
                planning.format_goal(g), parse_mode="Markdown"
            )

    return CommandHandler("goals", goals_cmd)


def make_health_handler() -> CommandHandler:

    async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        breakers = all_breakers()
        cb_lines = "\n".join(
            f"  • {n}: {cb.status} (calls:{cb.total_calls} fails:{cb.total_failures})"
            for n, cb in breakers.items()
        ) or "  нет данных"
        comp_status = monitor.get_status()
        comp_lines  = "\n".join(
            f"  • {n}: {'🟢 running' if s['state'] == 'running' else '🔴 ' + s['state']}"
            f" (рестартов: {s['restarts']})"
            for n, s in comp_status.items()
        ) or "  нет данных"
        vcounts = vmem.count()

        # Docker status
        from bot.docker_sandbox import _check_docker
        docker_icon = "✅" if _check_docker() else "❌"

        await update.message.reply_text(
            f"🏥 *Health Report*\n\n"
            f"*Circuit Breakers:*\n{cb_lines}\n\n"
            f"*Компоненты:*\n{comp_lines}\n\n"
            f"*Docker:* {docker_icon}\n\n"
            f"*Vector Memory:*\n"
            f"  memories: {vcounts['memories']}\n"
            f"  decisions: {vcounts['decisions']}\n"
            f"  proposals: {vcounts['proposals']}",
            parse_mode="Markdown",
        )

    return CommandHandler("health", health)


def make_search_handler() -> CommandHandler:

    async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        if not context.args:
            await update.message.reply_text(
                "Использование: `/search запрос`", parse_mode="Markdown"
            )
            return
        query   = " ".join(context.args)
        results = vmem.search_all(query, n=5)
        if not results:
            await update.message.reply_text("🔍 Ничего не найдено.")
            return
        lines = "\n\n".join(
            f"📄 *{r['collection']}* [{r['meta'].get('date', '')[:10]}]\n{r['text'][:200]}"
            for r in results
        )
        await update.message.reply_text(
            f"🔍 *Результаты:* _{query}_\n\n{lines}",
            parse_mode="Markdown",
        )

    return CommandHandler("search", search_cmd)


def make_permissions_handler() -> CommandHandler:

    async def manage_perms(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message is None:
            return
        user_id = update.message.from_user.id
        args    = context.args

        if not args:
            users = perms.all_users()
            lines = "\n".join(f"• `{u['id']}` → *{u['role']}*" for u in users)
            await update.message.reply_text(
                f"👥 *Пользователи:*\n\n{lines}\n\n"
                f"Роли: `owner` `admin` `member`\n"
                f"Добавить: `/perms add 123 admin`\n"
                f"Удалить: `/perms remove 123`",
                parse_mode="Markdown",
            )
            return

        if not perms.can(user_id, "manage_users"):
            await update.message.reply_text(
                perms.format_denied("manage_users"), parse_mode="Markdown"
            )
            return

        if args[0] == "add" and len(args) == 3:
            uid, role = int(args[1]), args[2]
            if perms.set_role(uid, role):
                await update.message.reply_text(
                    f"✅ `{uid}` → *{role}*", parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Неизвестная роль.")
        elif args[0] == "remove" and len(args) == 2:
            uid = int(args[1])
            if perms.remove_user(uid):
                await update.message.reply_text(f"✅ `{uid}` удалён.", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Не найден.")

    return CommandHandler("perms", manage_perms)


def make_myrole_handler() -> CommandHandler:

    async def myrole(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        user_id = update.message.from_user.id
        role    = perms.get_role(user_id)
        actions = perms.ROLES.get(role, set())
        await update.message.reply_text(
            f"👤 Роль: *{role}*\n"
            f"Разрешено: `{', '.join(sorted(actions)) or 'только чат'}`",
            parse_mode="Markdown",
        )

    return CommandHandler("myrole", myrole)


def make_git_handler() -> CommandHandler:

    async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        import bot.git_manager as git
        await update.message.reply_text(
            f"🌿 *Git*\nВетка: `{git.current_branch()}`\n"
            f"```\n{git.status() or 'clean'}\n```\n"
            f"```\n{git.log(5)}\n```",
            parse_mode="Markdown",
        )

    return CommandHandler("git", git_status)


def make_queue_handler(task_queue) -> CommandHandler:

    async def queue_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        tasks = task_queue.all()
        if not tasks:
            await update.message.reply_text("📋 Очередь пуста.")
            return
        lines = "\n".join(
            f"• `{t.id}` {t.name} → *{t.status.value}*"
            + (f"\n  ❌ {t.error}" if t.error else "")
            for t in tasks[-10:]
        )
        await update.message.reply_text(
            f"📋 *Tasks ({len(tasks)}):*\n\n{lines}", parse_mode="Markdown"
        )

    return CommandHandler("queue", queue_status)


def make_proposals_handler() -> CommandHandler:

    async def show_proposals(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message is None:
            return
        args = context.args
        proposals = (
            approval.all_proposals() if args and args[0] == "all"
            else approval.pending()
        )
        if not proposals:
            await update.message.reply_text("📋 Нет предложений.")
            return
        for p in proposals[-10:]:
            await update.message.reply_text(
                approval.format_proposal(p),
                parse_mode="Markdown",
                reply_markup=(
                    _approval_keyboard(p["id"]) if p["status"] == "pending" else None
                ),
            )

    return CommandHandler("proposals", show_proposals)


def make_clear_handler() -> CommandHandler:

    async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        chat_id = update.message.chat_id
        count   = len(chat_histories.get(chat_id, []))
        chat_histories[chat_id] = []
        await update.message.reply_text(f"🗑 История очищена. {count} сообщений.")

    return CommandHandler("clear", clear)


def make_memory_handler() -> CommandHandler:

    async def show_memory(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message is None:
            return
        memories = memory.load()
        if not memories:
            await update.message.reply_text("🧠 Памяти пока нет.")
            return
        lines = "\n\n".join(
            f"📌 [{m['date']}] _{m['source']}_\n{m['decision']}" for m in memories
        )
        await update.message.reply_text(
            f"🧠 *Память ({len(memories)}):*\n\n{lines}", parse_mode="Markdown"
        )

    return CommandHandler("memory", show_memory)


def make_clear_memory_handler() -> CommandHandler:

    async def clear_memory(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message is None:
            return
        count = memory.clear()
        await update.message.reply_text(f"🗑 Память очищена. {count} решений.")

    return CommandHandler("clearmemory", clear_memory)