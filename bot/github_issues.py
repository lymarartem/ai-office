"""GitHub Issues — создание задач в репозитории из чата AI Office.

Команда /issue превращает сообщение в issue на GitHub. Если GITHUB_TOKEN
или GITHUB_REPO не заданы — функция вернёт ошибку, система не падает.
"""

import logging

import requests

from config import GITHUB_TOKEN, GITHUB_REPO

logger = logging.getLogger(__name__)

_API = "https://api.github.com"


def is_configured() -> bool:
    return bool(GITHUB_TOKEN and GITHUB_REPO)


def create_issue(title: str, body: str = "") -> dict:
    """Создаёт issue в GitHub. Возвращает {ok, url, number} или {ok: False, error}."""
    if not is_configured():
        return {"ok": False, "error": "GITHUB_TOKEN или GITHUB_REPO не заданы"}
    try:
        resp = requests.post(
            f"{_API}/repos/{GITHUB_REPO}/issues",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept":        "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": title, "body": body},
            timeout=20,
        )
        if resp.status_code == 201:
            d = resp.json()
            logger.info(f"[GitHub] Создан issue #{d['number']}")
            return {"ok": True, "url": d["html_url"], "number": d["number"]}
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}: {resp.text[:150]}",
        }
    except Exception as e:
        logger.error(f"[GitHub] Ошибка: {e}")
        return {"ok": False, "error": str(e)}


def list_open_issues(limit: int = 5) -> dict:
    """Возвращает последние открытые issue репозитория."""
    if not is_configured():
        return {"ok": False, "error": "GitHub не настроен"}
    try:
        resp = requests.get(
            f"{_API}/repos/{GITHUB_REPO}/issues",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept":        "application/vnd.github+json",
            },
            params={"state": "open", "per_page": limit},
            timeout=20,
        )
        if resp.status_code == 200:
            items = [
                {"number": i["number"], "title": i["title"], "url": i["html_url"]}
                for i in resp.json()
                if "pull_request" not in i  # отфильтровываем PR
            ]
            return {"ok": True, "issues": items}
        return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
