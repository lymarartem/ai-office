import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _run(cmd: list) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=".")
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def init_if_needed() -> None:
    code, _, _ = _run(["git", "rev-parse", "--is-inside-work-tree"])
    if code != 0:
        _run(["git", "init"])
        _run(["git", "add", "."])
        _run(["git", "commit", "-m", "chore: initial commit"])
        logger.info("Git repo initialized")
    else:
        logger.info("Git repo already exists")


def is_repo() -> bool:
    code, _, _ = _run(["git", "rev-parse", "--is-inside-work-tree"])
    return code == 0


def current_branch() -> str:
    _, out, _ = _run(["git", "branch", "--show-current"])
    return out or "main"


def create_branch(name: str) -> tuple[bool, str]:
    code, out, err = _run(["git", "checkout", "-b", name])
    if code != 0:
        logger.error(f"create_branch failed: {err}")
    return code == 0, err


def checkout(branch: str) -> tuple[bool, str]:
    code, out, err = _run(["git", "checkout", branch])
    if code != 0:
        logger.error(f"checkout failed: {err}")
    return code == 0, err


def add_and_commit(files: list, message: str) -> tuple[bool, str]:
    for f in files:
        _run(["git", "add", f])
    code, out, err = _run(["git", "commit", "-m", message])
    if code != 0:
        logger.error(f"commit failed: {err}")
    return code == 0, out or err


def merge(branch: str) -> tuple[bool, str]:
    code, out, err = _run(["git", "merge", branch, "--no-ff", "-m", f"Merge {branch}"])
    if code != 0:
        logger.error(f"merge failed: {err}")
    return code == 0, out or err


def revert_last() -> tuple[bool, str]:
    code, out, err = _run(["git", "revert", "HEAD", "--no-edit"])
    if code != 0:
        logger.error(f"revert failed: {err}")
    return code == 0, out or err


def delete_branch(name: str) -> None:
    _run(["git", "branch", "-d", name])


def log(n: int = 5) -> str:
    _, out, _ = _run(["git", "log", "--oneline", f"-{n}"])
    return out


def status() -> str:
    _, out, _ = _run(["git", "status", "--short"])
    return out or "clean"