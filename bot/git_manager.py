import logging
import subprocess
import os

logger = logging.getLogger(__name__)

# Railway / cloud environments often do not have git installed
GIT_DISABLED = bool(os.getenv("RAILWAY_ENVIRONMENT"))


def _run(cmd: list) -> tuple[int, str, str]:
    if GIT_DISABLED:
        return 1, "", "Git disabled in Railway"

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd="."
        )

        return (
            r.returncode,
            r.stdout.strip(),
            r.stderr.strip()
        )

    except FileNotFoundError:
        logger.warning("Git executable not found")
        return 1, "", "git executable not found"

    except Exception as e:
        logger.error(f"Git command failed: {e}")
        return 1, "", str(e)


def init_if_needed() -> None:
    if GIT_DISABLED:
        logger.warning("⚠️ Git disabled on Railway")
        return

    code, _, _ = _run(
        ["git", "rev-parse", "--is-inside-work-tree"]
    )

    if code != 0:
        _run(["git", "init"])
        _run(["git", "add", "."])
        _run(
            ["git", "commit", "-m", "chore: initial commit"]
        )

        logger.info("Git repo initialized")

    else:
        logger.info("Git repo already exists")


def is_repo() -> bool:
    if GIT_DISABLED:
        return False

    code, _, _ = _run(
        ["git", "rev-parse", "--is-inside-work-tree"]
    )

    return code == 0


def current_branch() -> str:
    if GIT_DISABLED:
        return "railway"

    _, out, _ = _run(
        ["git", "branch", "--show-current"]
    )

    return out or "main"


def create_branch(name: str) -> tuple[bool, str]:
    if GIT_DISABLED:
        return False, "Git disabled"

    code, out, err = _run(
        ["git", "checkout", "-b", name]
    )

    if code != 0:
        logger.error(f"create_branch failed: {err}")

    return code == 0, err


def checkout(branch: str) -> tuple[bool, str]:
    if GIT_DISABLED:
        return False, "Git disabled"

    code, out, err = _run(
        ["git", "checkout", branch]
    )

    if code != 0:
        logger.error(f"checkout failed: {err}")

    return code == 0, err


def add_and_commit(files: list, message: str) -> tuple[bool, str]:
    if GIT_DISABLED:
        return False, "Git disabled"

    for f in files:
        _run(["git", "add", f])

    code, out, err = _run(
        ["git", "commit", "-m", message]
    )

    if code != 0:
        logger.error(f"commit failed: {err}")

    return code == 0, out or err


def merge(branch: str) -> tuple[bool, str]:
    if GIT_DISABLED:
        return False, "Git disabled"

    code, out, err = _run(
        [
            "git",
            "merge",
            branch,
            "--no-ff",
            "-m",
            f"Merge {branch}"
        ]
    )

    if code != 0:
        logger.error(f"merge failed: {err}")

    return code == 0, out or err


def revert_last() -> tuple[bool, str]:
    if GIT_DISABLED:
        return False, "Git disabled"

    code, out, err = _run(
        ["git", "revert", "HEAD", "--no-edit"]
    )

    if code != 0:
        logger.error(f"revert failed: {err}")

    return code == 0, out or err


def delete_branch(name: str) -> None:
    if GIT_DISABLED:
        return

    _run(["git", "branch", "-d", name])


def log(n: int = 5) -> str:
    if GIT_DISABLED:
        return "Git disabled on Railway"

    _, out, _ = _run(
        ["git", "log", "--oneline", f"-{n}"]
    )

    return out


def status() -> str:
    if GIT_DISABLED:
        return "Git disabled on Railway"

    _, out, _ = _run(
        ["git", "status", "--short"]
    )

    return out or "clean"