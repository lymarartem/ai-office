"""Live File Graph — Фаза D.

Следит за изменениями файлов проекта в реальном времени (watchdog),
строит граф зависимостей по import'ам (networkx) и публикует события
FILE_CHANGED / FILE_CREATED / FILE_DELETED в общую шину.

Позволяет агентам видеть: какой файл изменился и какие модули это затронет.
"""

import ast
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import networkx as nx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from bot.event_bus import bus, Events

logger = logging.getLogger(__name__)

# Директории, которые не отслеживаем
_IGNORE_DIRS = {
    "venv", ".venv", "__pycache__", ".git", "chroma_db",
    "node_modules", "backups", "patches", "sandbox", ".pytest_cache",
}
_MAX_HISTORY = 50


def _is_ignored(path: str) -> bool:
    parts = Path(path).parts
    return any(p in _IGNORE_DIRS for p in parts)


class FileDependencyGraph:
    """Граф зависимостей файлов проекта.

    Ребро A → B означает «B импортирует A» (A — зависимость, B — зависимый).
    """

    def __init__(self):
        self._graph = nx.DiGraph()
        self._history: list[dict] = []
        self._lock = threading.Lock()
        self._local_by_stem: dict[str, str] = {}
        self._local_by_dotted: dict[str, str] = {}
        self._root = "."

    # ── индексация проекта ────────────────────────────────────────────
    def index_project(self, root: str) -> None:
        """Полное сканирование проекта: карта модулей + полный граф зависимостей."""
        self._root = root
        root_path = Path(root).resolve()
        with self._lock:
            self._local_by_stem.clear()
            self._local_by_dotted.clear()
            self._graph.clear()

            # Проход 1 — карта локальных модулей
            py_files: list[tuple[Path, str]] = []
            for py in root_path.rglob("*.py"):
                rel = py.relative_to(root_path).as_posix()
                if _is_ignored(rel):
                    continue
                py_files.append((py, rel))
                self._local_by_stem[py.stem] = rel
                dotted = rel[:-3].replace("/", ".")
                self._local_by_dotted[dotted] = rel

            # Проход 2 — строим полный граф зависимостей по import'ам
            for py, rel in py_files:
                self._graph.add_node(rel)
                for dep in self._parse_imports(str(py)):
                    self._graph.add_edge(dep, rel)

        logger.info(
            f"[FileGraph] Проиндексировано: "
            f"{self._graph.number_of_nodes()} файлов, "
            f"{self._graph.number_of_edges()} связей"
        )

    # ── разбор импортов ───────────────────────────────────────────────
    def _resolve(self, module: str) -> str | None:
        if not module:
            return None
        if module in self._local_by_dotted:
            return self._local_by_dotted[module]
        stem = module.split(".")[0]
        return self._local_by_stem.get(stem)

    def _parse_imports(self, abs_path: str) -> list[str]:
        """Возвращает relpath'ы локальных файлов, которые импортирует abs_path."""
        try:
            src = Path(abs_path).read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except Exception:
            return []
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    rel = self._resolve(alias.name)
                    if rel:
                        deps.add(rel)
            elif isinstance(node, ast.ImportFrom):
                rel = self._resolve(node.module or "")
                if rel:
                    deps.add(rel)
        return sorted(deps)

    # ── обновление графа ──────────────────────────────────────────────
    def record_change(self, abs_path: str, kind: str) -> dict:
        """Регистрирует изменение файла, обновляет граф. Возвращает инфо о событии."""
        root_path = Path(self._root).resolve()
        try:
            rel = Path(abs_path).resolve().relative_to(root_path).as_posix()
        except ValueError:
            rel = abs_path

        deps: list[str] = []
        with self._lock:
            if kind == "deleted":
                if self._graph.has_node(rel):
                    self._graph.remove_node(rel)
            else:
                deps = self._parse_imports(abs_path)
                # очищаем старые рёбра-зависимости этого файла
                old = list(self._graph.predecessors(rel)) if self._graph.has_node(rel) else []
                for o in old:
                    self._graph.remove_edge(o, rel)
                self._graph.add_node(rel)
                for dep in deps:
                    self._graph.add_edge(dep, rel)

            entry = {
                "path": rel,
                "kind": kind,
                "deps": deps,
                "time": datetime.now().strftime("%H:%M:%S"),
            }
            self._history.append(entry)
            if len(self._history) > _MAX_HISTORY:
                self._history = self._history[-_MAX_HISTORY:]
        return entry

    # ── запросы ───────────────────────────────────────────────────────
    def affected_by(self, rel: str) -> list[str]:
        """Файлы, которые (транзитивно) зависят от rel."""
        with self._lock:
            if not self._graph.has_node(rel):
                return []
            return sorted(nx.descendants(self._graph, rel))

    def stats(self) -> dict:
        with self._lock:
            return {
                "files": self._graph.number_of_nodes(),
                "edges": self._graph.number_of_edges(),
                "changes": len(self._history),
            }

    def recent_changes(self, n: int = 10) -> list[dict]:
        with self._lock:
            return list(self._history[-n:])

    def format_summary(self) -> str:
        """Markdown-сводка для команды /filegraph."""
        st = self.stats()
        recent = self.recent_changes(8)
        lines = [
            "📊 *Live File Graph*",
            f"Файлов: `{st['files']}`  Связей: `{st['edges']}`  "
            f"Изменений: `{st['changes']}`",
            "",
        ]
        if not recent:
            lines.append("_Изменений пока не зафиксировано._")
            return "\n".join(lines)

        lines.append("*Последние изменения:*")
        icons = {"modified": "✏️", "created": "🆕", "deleted": "🗑"}
        for ch in reversed(recent):
            icon = icons.get(ch["kind"], "•")
            lines.append(f"{icon} `{ch['path']}` _{ch['time']}_")

        last = recent[-1]
        if last["kind"] != "deleted":
            affected = self.affected_by(last["path"])
            lines.append("")
            if affected:
                shown = ", ".join(f"`{a}`" for a in affected[:10])
                lines.append(
                    f"⚠️ Изменение `{last['path']}` затронет: {shown}"
                )
            else:
                lines.append(f"✅ `{last['path']}` — никто не зависит.")
        return "\n".join(lines)


# Глобальный инстанс
graph = FileDependencyGraph()


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, loop):
        self._loop = loop
        # антидребезг: путь -> время последнего события
        self._last: dict[str, float] = {}

    def _emit(self, src_path: str, kind: str, event_type: str) -> None:
        if src_path.endswith((".pyc", ".tmp", "~")) or _is_ignored(src_path):
            return
        now = time.time()
        if now - self._last.get(src_path, 0) < 1.0:
            return  # дребезг файловой системы
        self._last[src_path] = now

        entry = graph.record_change(src_path, kind)
        bus.publish_threadsafe(self._loop, event_type, {
            "path":  entry["path"],
            "kind":  kind,
            "deps":  entry["deps"],
        })
        logger.info(f"[FileGraph] {kind}: {entry['path']} (deps: {len(entry['deps'])})")

    def on_modified(self, event):
        if not event.is_directory:
            self._emit(event.src_path, "modified", Events.FILE_CHANGED)

    def on_created(self, event):
        if not event.is_directory:
            self._emit(event.src_path, "created", Events.FILE_CREATED)

    def on_deleted(self, event):
        if not event.is_directory:
            self._emit(event.src_path, "deleted", Events.FILE_DELETED)


def start_file_graph_watcher(path: str, loop) -> Observer:
    """Запускает слежение за директорией path. loop — основной asyncio loop."""
    graph.index_project(path)
    handler = _ChangeHandler(loop)
    observer = Observer()
    observer.schedule(handler, path, recursive=True)
    observer.daemon = True
    observer.start()
    logger.info(f"[FileGraph] Наблюдение запущено: {Path(path).resolve()}")
    return observer
