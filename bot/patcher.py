import difflib
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PATCHES_DIR = Path("patches")
PATCHES_DIR.mkdir(exist_ok=True)


def generate_diff(original: str, modified: str, filepath: str) -> str:
    return "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
    ))


def save(pid: str, file_changes: list) -> Path:
    """
    file_changes: [{"path": str, "original": str, "content": str}]
    Сохраняет .json и .patch файлы.
    """
    patch_data = {
        "pid": pid,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "files": [],
    }
    diffs = []

    for fc in file_changes:
        original = fc.get("original", "")
        modified = fc["content"]
        diff = generate_diff(original, modified, fc["path"])
        diffs.append(diff)
        patch_data["files"].append({
            "path": fc["path"],
            "original": original,
            "content": modified,
            "diff": diff,
        })

    (PATCHES_DIR / f"{pid}.json").write_text(
        json.dumps(patch_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    patch_file = PATCHES_DIR / f"{pid}.patch"
    patch_file.write_text("\n".join(diffs), encoding="utf-8")
    logger.info(f"Patch saved: {patch_file}")
    return patch_file


def load(pid: str) -> dict | None:
    f = PATCHES_DIR / f"{pid}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def apply(pid: str) -> tuple[bool, list]:
    """Применяет патч к реальным файлам."""
    data = load(pid)
    if not data:
        return False, []
    applied = []
    for fc in data["files"]:
        target = Path(fc["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(fc["content"], encoding="utf-8")
        applied.append(fc["path"])
        logger.info(f"Applied: {fc['path']}")
    return True, applied


def read_original(filepath: str) -> str:
    """Читает текущее содержимое файла (до патча)."""
    p = Path(filepath)
    return p.read_text(encoding="utf-8") if p.exists() else ""