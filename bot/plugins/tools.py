import math
import logging
from bot.plugins.registry import registry

logger = logging.getLogger(__name__)


@registry.register(
    name="web_search",
    description="Поиск актуальной информации в интернете через DuckDuckGo",
    example='web_search("AI trends 2026")',
)
def web_search(query: str, max_results: int = 3) -> str:
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=int(max_results)):
                results.append(
                    f"*{r['title']}*\n{r['body'][:200]}\n{r['href']}"
                )
        return "\n\n".join(results) if results else "Результатов не найдено."
    except Exception as e:
        return f"❌ Поиск недоступен: {e}"


@registry.register(
    name="calculate",
    description="Безопасное вычисление математических выражений",
    example='calculate("sqrt(144) * pi")',
)
def calculate(expression: str) -> str:
    safe_globals = {
        "__builtins__": {},
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "pow": pow, "len": len,
        "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "pi": math.pi, "e": math.e, "inf": math.inf,
        "floor": math.floor, "ceil": math.ceil,
    }
    blocked = ["__", "import", "open", "exec", "eval", "os", "sys"]
    for b in blocked:
        if b in expression:
            return f"❌ Заблокировано: `{b}`"
    try:
        result = eval(expression, safe_globals, {})
        return f"= {result}"
    except Exception as e:
        return f"❌ Ошибка: {e}"


@registry.register(
    name="run_code",
    description="Запуск Python кода в изолированной среде (Docker или subprocess)",
    example='run_code("import sys; print(sys.version)")',
)
async def run_code(code: str) -> str:
    from bot.isolated_runner import execute, format_result
    result = await execute(code, language="python")
    return format_result(result)


@registry.register(
    name="run_shell",
    description="Выполнение безопасной shell-команды",
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
    allowed = {".py", ".md", ".json", ".txt", ".yml", ".yaml", ".toml", ".env.example"}
    p = Path(path)
    if p.suffix not in allowed:
        return f"❌ Тип файла не разрешён: {p.suffix}"
    if ".." in str(p):
        return "❌ Path traversal запрещён."
    if not p.exists():
        return f"❌ Файл не найден: {path}"
    try:
        content = p.read_text(encoding="utf-8")
        return content[:3000] + ("..." if len(content) > 3000 else "")
    except Exception as e:
        return f"❌ Ошибка чтения: {e}"


@registry.register(
    name="write_file",
    description="Запись содержимого в файл проекта (только .py, .md, .json)",
    example='write_file("notes.md", "# Заметки\n\nТекст")',
)
def write_file(path: str, content: str) -> str:
    from pathlib import Path
    allowed = {".py", ".md", ".json", ".txt"}
    p = Path(path)
    if p.suffix not in allowed:
        return f"❌ Запись в {p.suffix} не разрешена."
    if ".." in str(p):
        return "❌ Path traversal запрещён."
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"✅ Записано {len(content)} символов в `{path}`"
    except Exception as e:
        return f"❌ Ошибка записи: {e}"


@registry.register(
    name="list_files",
    description="Список файлов в директории проекта",
    example='list_files("bot/")',
)
def list_files(path: str = ".") -> str:
    from pathlib import Path
    p = Path(path)
    if ".." in str(p):
        return "❌ Path traversal запрещён."
    if not p.exists():
        return f"❌ Директория не найдена: {path}"
    try:
        items = []
        for item in sorted(p.iterdir()):
            if item.name.startswith("."):
                continue
            prefix = "📁" if item.is_dir() else "📄"
            items.append(f"{prefix} {item.name}")
        return "\n".join(items[:50]) if items else "Директория пуста."
    except Exception as e:
        return f"❌ Ошибка: {e}"


@registry.register(
    name="git_info",
    description="Информация о git: ветка, статус, лог",
    example='git_info()',
)
def git_info() -> str:
    from bot.git_manager import current_branch, log, status, is_repo
    if not is_repo():
        return "Git репо не найдено."
    return (
        f"Ветка: {current_branch()}\n"
        f"Статус: {status() or 'clean'}\n"
        f"Лог:\n{log(5)}"
    )


@registry.register(
    name="docker_status",
    description="Статус Docker: доступен ли, список образов и контейнеров",
    example='docker_status()',
)
def docker_status() -> str:
    try:
        import docker
        client = docker.from_env(timeout=3)
        client.ping()
        images = client.images.list()
        containers = client.containers.list()
        return (
            f"✅ Docker работает\n"
            f"Образов: {len(images)}\n"
            f"Контейнеров: {len(containers)}"
        )
    except Exception as e:
        return f"❌ Docker недоступен: {e}"