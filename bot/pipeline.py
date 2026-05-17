import asyncio
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import bot.patcher as patcher
import bot.git_manager as git

logger = logging.getLogger(__name__)

SANDBOX_DIR = Path("sandbox")
BACKUPS_DIR = Path("backups")
SANDBOX_DIR.mkdir(exist_ok=True)
BACKUPS_DIR.mkdir(exist_ok=True)


def run_tests(path: str = ".") -> tuple[bool, str]:
    """Запускает pytest и возвращает (passed, output)."""
    test_files = (
        list(Path(path).glob("test_*.py"))
        + list(Path(path).glob("tests/*.py"))
    )
    if not test_files:
        return True, "Тестов не найдено."

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--tb=short", "-q"],
        capture_output=True, text=True, cwd=path,
    )
    output = (result.stdout + result.stderr)[-500:].strip()
    return result.returncode == 0, output


def syntax_check(filepath: str, content: str) -> tuple[bool, str]:
    """Проверяет синтаксис Python файла."""
    if not filepath.endswith(".py"):
        return True, ""
    tmp = Path("sandbox") / "_syntax_check.py"
    tmp.write_text(content, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(tmp)],
        capture_output=True, text=True,
    )
    tmp.unlink(missing_ok=True)
    return result.returncode == 0, result.stderr.strip()


class Pipeline:
    """Approve → Patch → Sandbox → Tests → Git branch → Deploy → Rollback"""

    def __init__(self, pid: str, dev_agent, ceo_bot, chat_id: int):
        self.pid        = pid
        self.dev_agent  = dev_agent
        self.ceo_bot    = ceo_bot
        self.chat_id    = chat_id
        self.branch     = f"feature/{pid.lower()}"
        self.backup_dir = BACKUPS_DIR / pid
        self.sandbox    = SANDBOX_DIR / pid

    # ── Public ───────────────────────────────────────────────────

    async def run(self, proposal: dict) -> None:
        await self._send(
            f"🚀 *Pipeline {self.pid}*\n"
            f"`Patch → Sandbox → Tests → Git → Deploy`"
        )

        patch_data = await self._stage_patch(proposal)
        if not patch_data:
            return

        sandbox_ok = await self._stage_sandbox(patch_data)
        if not sandbox_ok:
            return

        tests_ok = await self._stage_tests()
        if not tests_ok:
            await self._send(
                f"❌ *Tests failed* — deploy заблокирован.\n"
                f"Откат: `/rollback {self.pid}`"
            )
            return

        git_ok = await self._stage_git(patch_data)
        if not git_ok:
            return

        await self._request_deploy(patch_data)

    async def deploy(self) -> None:
        await self._send(f"🚀 *[5/5] Deploy* — применяю изменения...")

        # Бэкап оригиналов
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        data = patcher.load(self.pid)
        if not data:
            await self._send(f"❌ Патч `{self.pid}` не найден.")
            return

        backed = []
        for fc in data["files"]:
            src = Path(fc["path"])
            if src.exists():
                dst = self.backup_dir / fc["path"]
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                backed.append(fc["path"])

        # Применяем патч
        ok, applied = patcher.apply(self.pid)

        # Git merge
        main = "main" if Path(".git/refs/heads/main").exists() else "master"
        git.checkout(main)
        merged, merge_msg = git.merge(self.branch)
        git.delete_branch(self.branch)

        files_str = "\n".join(f"  • `{f}`" for f in applied)
        await self._send(
            f"✅ *Deployed!*\n\n"
            f"Файлы:\n{files_str}\n\n"
            f"Git: `{merge_msg[:100]}`\n"
            f"Бэкап: `backups/{self.pid}/`\n"
            f"Откат: `/rollback {self.pid}`"
        )

    async def rollback(self) -> None:
        await self._send(f"⏪ *Rollback {self.pid}...*")

        # Файловый откат
        if self.backup_dir.exists():
            restored = []
            for bf in self.backup_dir.rglob("*"):
                if bf.is_file():
                    rel = bf.relative_to(self.backup_dir)
                    target = Path(rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(bf, target)
                    restored.append(str(rel))

            files_str = "\n".join(f"  • `{f}`" for f in restored)
            await self._send(f"✅ Файлы восстановлены:\n{files_str}")
        else:
            # Git revert если нет бэкапа
            ok, msg = git.revert_last()
            if ok:
                await self._send(f"✅ Git revert выполнен:\n`{msg}`")
            else:
                await self._send(f"❌ Rollback не удался: `{msg}`")

    # ── Stages ───────────────────────────────────────────────────

    async def _stage_patch(self, proposal: dict) -> dict | None:
        await self._send("📝 *[1/5] Patch* — генерирую real diff...")

        files_hint = ", ".join(proposal.get("files") or []) or "не указаны"
        prompt = (
            f"Одобренное предложение:\n"
            f"Что: {proposal['what']}\n"
            f"Зачем: {proposal['why']}\n"
            f"Файлы: {files_hint}\n\n"
            f"Сгенерируй конкретные изменения. Верни ТОЛЬКО JSON:\n"
            f'{{\n'
            f'  "description": "Что изменено",\n'
            f'  "files": [\n'
            f'    {{\n'
            f'      "path": "путь/файл.py",\n'
            f'      "content": "полное содержимое файла"\n'
            f'    }}\n'
            f'  ]\n'
            f'}}'
        )

        try:
            raw = await self.dev_agent.respond(message=prompt)
            clean = raw.strip().strip("```json").strip("```").strip()
            data = json.loads(clean)

            # Читаем оригиналы и генерируем real diff
            file_changes = []
            for fc in data.get("files", []):
                original = patcher.read_original(fc["path"])
                file_changes.append({
                    "path": fc["path"],
                    "original": original,
                    "content": fc["content"],
                })

            patch_file = patcher.save(self.pid, file_changes)

            files_str = "\n".join(f"  • `{fc['path']}`" for fc in file_changes)
            await self._send(
                f"✅ *Patch готов* — `{patch_file.name}`\n"
                f"_{data.get('description', '')}_\n\n"
                f"Файлы:\n{files_str}"
            )
            return patcher.load(self.pid)

        except Exception as e:
            logger.error(f"Patch stage error: {e}")
            await self._send(f"❌ *Patch failed:* `{e}`")
            return None

    async def _stage_sandbox(self, patch_data: dict) -> bool:
        await self._send("🏖 *[2/5] Sandbox* — проверяю в изоляции...")

        self.sandbox.mkdir(parents=True, exist_ok=True)
        errors = []

        for fc in patch_data.get("files", []):
            # Syntax check
            ok, err = syntax_check(fc["path"], fc["content"])
            if not ok:
                errors.append(f"`{fc['path']}`: {err}")
                continue

            # Записываем в sandbox
            target = self.sandbox / fc["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(fc["content"], encoding="utf-8")

        if errors:
            await self._send("❌ *Sandbox failed*\n" + "\n".join(errors))
            return False

        await self._send("✅ *Sandbox OK* — синтаксис чистый")
        return True

    async def _stage_tests(self) -> bool:
        await self._send("🧪 *[3/5] Tests* — запускаю pytest...")

        loop = asyncio.get_event_loop()
        passed, output = await loop.run_in_executor(None, run_tests, ".")

        if passed:
            await self._send(f"✅ *Tests passed*\n```\n{output[:300]}\n```")
        else:
            await self._send(f"❌ *Tests failed*\n```\n{output[:300]}\n```")
        return passed

    async def _stage_git(self, patch_data: dict) -> bool:
        await self._send(f"🌿 *[4/5] Git* — создаю ветку `{self.branch}`...")

        if not git.is_repo():
            await self._send("⚠️ Git репо не найдено — пропускаю git этап.")
            return True

        # Создаём ветку
        ok, err = git.create_branch(self.branch)
        if not ok:
            await self._send(f"❌ *Git branch failed:* `{err}`")
            return False

        # Применяем файлы и коммитим
        _, applied = patcher.apply(self.pid)
        ok, msg = git.add_and_commit(
            applied,
            f"feat: {patch_data.get('description', self.pid)} [{self.pid}]",
        )
        if not ok:
            await self._send(f"❌ *Git commit failed:* `{msg}`")
            return False

        log_str = git.log(3)
        await self._send(
            f"✅ *Git OK*\n"
            f"Ветка: `{self.branch}`\n"
            f"```\n{log_str}\n```"
        )
        return True

    async def _request_deploy(self, patch_data: dict) -> None:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🚀 Deploy", callback_data=f"deploy:{self.pid}"),
            InlineKeyboardButton("🗑 Cancel",  callback_data=f"cancel_deploy:{self.pid}"),
        ]])
        files_str = "\n".join(
            f"  • `{fc['path']}`" for fc in patch_data["files"]
        )
        await self.ceo_bot.send_message(
            chat_id=self.chat_id,
            text=(
                f"🟢 *Patch + Sandbox + Tests + Git — всё ок.*\n\n"
                f"Ветка: `{self.branch}`\n"
                f"Файлы:\n{files_str}\n\n"
                f"⚠️ Бэкап создастся в `backups/{self.pid}/`"
            ),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    async def _send(self, text: str) -> None:
        try:
            await self.ceo_bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"[Pipeline] send error: {e}")