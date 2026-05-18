import math
import logging
from bot.plugins.registry import registry

logger = logging.getLogger(__name__)


@registry.register(
    name="web_search",
    description="Поиск информации через DuckDuckGo",
    example='web_search("AI trends 2026")',
)
def web_search(query: str, max_results: int = 3) -> str:
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=int(max_results)):
                results.append(f"*{r['title']}*\n{r['body'][:200]}\n{r['href']}")
        return "\n\n".join(results) if results else "Результатов не найдено."
    except Exception as e:
        return f"❌ Поиск недоступен: {e}"


@registry.register(
    name="browse_url",
    description="Открыть URL и получить содержимое страницы",
    example='browse_url("https://example.com")',
)
async def browse_url(url: str) -> str:
    from bot.browser_runner import get_content
    result = await get_content(url)
    if not result["success"]:
        return f"❌ Не удалось открыть {url}: {result.get('error', '?')}"
    content = result["content"][:2000]
    title   = result["title"]
    return f"*{title}*\n{url}\n\n{content}"


@registry.register(
    name="check_url",
    description="Проверить доступность URL",
    example='check_url("https://example.com")',
)
async def check_url(url: str) -> str:
    from bot.browser_runner import check_url as _check
    result = await _check(url)
    if result["success"]:
        status = result["status"]
        ok     = "✅" if result["ok"] else "⚠️"
        return (
            f"{ok} *{result['title']}*\n"
            f"URL: {url}\n"
            f"Status: {status} | {result['duration']}с"
        )
    return f"❌ Недоступен: {url}\n{result.get('error', '?')}"


@registry.register(
    name="calculate",
    description="Безопасные математические вычисления",
    example='calculate("sqrt(144) * pi")',
)
def calculate(expression: str) -> str:
    safe_globals = {
        "__builtins__": {},
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "pow": pow, "sqrt": math.sqrt,
        "log": math.log, "log10": math.log10,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "pi": math.pi, "e": math.e, "floor": math.floor, "ceil": math.ceil,
    }
    blocked = ["__", "import", "open", "exec", "eval", "os", "sys"]
    for b in blocked:
        if b in expression:
            return f"❌ Заблокировано: `{b}`"
    try:
        return f"= {eval(expression, safe_globals, {})}"
    except Exception as e:
        return f"❌ Ошибка: {e}"


@registry.register(
    name="run_code",
    description="Запуск Python в изолированной среде (Docker/subprocess)",
    example='run_code("print(2**32)")',
)
async def run_code(code: str) -> str:
    from bot.isolated_runner import execute, format_result
    result = await execute(code, language="python")
    return format_result(result)


@registry.register(
    name="run_shell",
    description="Выполнение shell-команды из whitelist",
    example='run_shell("git log --oneline -3")',
)
async def run_shell(cmd: str) -> str:
    from bot.terminal_runner import _classify, _run_command
    import asyncio
    if _classify(cmd) == "blocked":
        return f"❌ Команда заблокирована: `{cmd}`"
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_command, cmd, ".")
    out = result.get("stdout", "") or result.get("stderr", "")
    return f"```\n{out[:1000]}\n```" if out else "Нет вывода."


@registry.register(
    name="read_file",
    description="Чтение файла проекта",
    example='read_file("config.py")',
)
def read_file(path: str) -> str:
    from pathlib import Path
    allowed = {".py", ".md", ".json", ".txt", ".yml", ".yaml", ".toml"}
    p = Path(path)
    if p.suffix not in allowed or ".." in str(p):
        return f"❌ Файл недоступен: {path}"
    if not p.exists():
        return f"❌ Не найден: {path}"
    content = p.read_text(encoding="utf-8")
    return content[:3000] + ("..." if len(content) > 3000 else "")


@registry.register(
    name="write_file",
    description="Запись в файл проекта (.py, .md, .json, .txt)",
    example='write_file("notes.md", "# Заметки")',
)
def write_file(path: str, content: str) -> str:
    from pathlib import Path
    allowed = {".py", ".md", ".json", ".txt"}
    p = Path(path)
    if p.suffix not in allowed or ".." in str(p):
        return f"❌ Запись недоступна: {path}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"✅ Записано {len(content)} символов → `{path}`"


@registry.register(
    name="list_files",
    description="Список файлов в директории",
    example='list_files("bot/")',
)
def list_files(path: str = ".") -> str:
    from pathlib import Path
    p = Path(path)
    if ".." in str(p) or not p.exists():
        return f"❌ Директория недоступна: {path}"
    items = [
        f"{'📁' if i.is_dir() else '📄'} {i.name}"
        for i in sorted(p.iterdir())
        if not i.name.startswith(".")
    ]
    return "\n".join(items[:50]) or "Пусто."


@registry.register(
    name="git_info",
    description="Git: ветка, статус, последние коммиты",
    example='git_info()',
)
def git_info() -> str:
    from bot.git_manager import current_branch, log, status, is_repo
    if not is_repo():
        return "Git репо не найдено."
    return f"Ветка: {current_branch()}\nСтатус: {status() or 'clean'}\nЛог:\n{log(5)}"


@registry.register(
    name="agent_status",
    description="Статус всех агентов в реестре (локальных и удалённых)",
    example='agent_status()',
)
def agent_status() -> str:
    from bot.agent_registry import registry as reg
    status = reg.status()
    lines  = []
    for name, info in status.items():
        icon = "🟢" if info["status"] == "online" else "🔴"
        lat  = f" {info.get('latency_ms', 0)}ms" if info["type"] == "remote" else ""
        lines.append(f"{icon} *{name}* [{info['type']}]{lat}")
    return "\n".join(lines) if lines else "Нет агентов в реестре."


@registry.register(
    name="docker_status",
    description="Статус Docker: доступен ли, образы, контейнеры",
    example='docker_status()',
)
def docker_status() -> str:
    try:
        import docker
        client = docker.from_env(timeout=3)
        client.ping()
        return (
            f"✅ Docker работает\n"
            f"Образов: {len(client.images.list())}\n"
            f"Контейнеров: {len(client.containers.list())}"
        )
    except Exception as e:
        return f"❌ Docker недоступен: {e}"