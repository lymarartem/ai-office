"""Agent Analytics — сбор и форматирование метрик системы AI Office.

Источник данных — уже существующие подсистемы: шина событий (вся активность),
граф файлов, Caveman Mode, circuit breakers. Ничего отдельно собирать не нужно.
Используется агентом-аналитиком для отчётов по команде /stats.
"""

import logging
from collections import Counter
from datetime import datetime

from bot.event_bus import bus, Events

logger = logging.getLogger(__name__)

_start = datetime.now()


def _fmt_uptime(delta) -> str:
    total = int(delta.total_seconds())
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}ч {m}м" if h else f"{m}м"


def collect() -> dict:
    """Собирает срез метрик системы."""
    log = bus.get_log(500)
    by_type = Counter(e["type"] for e in log)

    agent_calls = Counter()
    tests_pass = tests_fail = 0
    for e in log:
        d = e.get("data", {})
        if e["type"] == Events.AGENT_RESPONDED:
            agent_calls[d.get("agent", "?")] += 1
        elif e["type"] == Events.TESTS_COMPLETED:
            if d.get("passed"):
                tests_pass += 1
            else:
                tests_fail += 1

    try:
        from bot.file_graph import graph
        fg = graph.stats()
    except Exception:
        fg = {}

    try:
        from bot.caveman import caveman
        cv = caveman.stats()
    except Exception:
        cv = {}

    breakers = {}
    try:
        from bot.self_healing import all_breakers
        for n, cb in all_breakers().items():
            breakers[n] = {
                "status":   cb.status,
                "calls":    cb.total_calls,
                "failures": cb.total_failures,
            }
    except Exception:
        pass

    return {
        "uptime":       _fmt_uptime(datetime.now() - _start),
        "events_total": len(log),
        "by_type":      dict(by_type.most_common(6)),
        "agent_calls":  dict(agent_calls.most_common()),
        "tests":        {"pass": tests_pass, "fail": tests_fail},
        "file_graph":   fg,
        "caveman":      cv,
        "breakers":     breakers,
    }


def _bar(n: int, maxn: int, width: int = 10) -> str:
    if maxn <= 0:
        return "▱" * width
    filled = round(n / maxn * width)
    return "▰" * filled + "▱" * (width - filled)


def format_report(m: dict) -> str:
    """Текстовый отчёт с псевдо-графиками для Telegram."""
    lines = ["📊 *AI Office — Аналитика*", f"⏱ Аптайм: `{m['uptime']}`", ""]

    calls = m["agent_calls"]
    if calls:
        lines.append("*Активность агентов:*")
        mx = max(calls.values())
        for name, n in calls.items():
            lines.append(f"`{_bar(n, mx)}` {name} — {n}")
        lines.append("")

    if m["events_total"]:
        lines.append(f"*События:* всего `{m['events_total']}`")
        # подчёркивания в именах событий ломают Markdown — заменяем на пробел
        parts = " · ".join(
            f"{t.replace('_', ' ')}:{c}" for t, c in m["by_type"].items()
        )
        lines.append(parts)
        lines.append("")

    t = m["tests"]
    if t["pass"] or t["fail"]:
        lines.append(f"*Тесты:* ✅ {t['pass']}  ❌ {t['fail']}")

    fg = m["file_graph"]
    if fg:
        lines.append(
            f"*Граф файлов:* {fg.get('files', 0)} файлов, "
            f"{fg.get('edges', 0)} связей"
        )

    cv = m["caveman"]
    if cv and cv.get("calls"):
        lines.append(
            f"*Caveman:* {cv.get('label', '')} — "
            f"экономия ~{cv.get('saved_est', 0)} токенов"
        )

    br = m["breakers"]
    if br:
        bad = [n for n, b in br.items() if b["status"] != "CLOSED"]
        if bad:
            lines.append(f"*Здоровье:* ⚠️ проблемы — {', '.join(bad)}")
        else:
            lines.append(f"*Здоровье:* 🟢 все {len(br)} breakers в норме")

    return "\n".join(lines)


def build_analysis_prompt(m: dict) -> str:
    """Промпт для агента-аналитика — просим интерпретировать метрики."""
    return (
        "Метрики системы AI Office за последнее время:\n"
        f"{m}\n\n"
        "Дай короткое аналитическое резюме (2-3 предложения): что происходит, "
        "есть ли аномалии или узкие места, что стоит улучшить. "
        "Не пересказывай цифры дословно — делай вывод."
    )
