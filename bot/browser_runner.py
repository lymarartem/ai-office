"""
Playwright-based browser automation для Browser Agent.
Headless Chromium — скриншоты, контент, клики, формы.
"""
import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Optional

from bot.event_bus import bus

logger = logging.getLogger(__name__)

_playwright = None
_browser    = None
MAX_CONTENT = 5000
TIMEOUT_MS  = 15_000

# Сайты которые нельзя открывать
BLOCKED_DOMAINS = {
    "localhost", "127.0.0.1", "192.168.", "10.0.", "169.254.",
    "0.0.0.0", "file://",
}


def _is_blocked(url: str) -> bool:
    url_lower = url.lower()
    return any(d in url_lower for d in BLOCKED_DOMAINS)


async def _get_browser():
    global _playwright, _browser
    if _browser and _browser.is_connected():
        return _browser
    try:
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        _browser    = await _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        logger.info("✅ Playwright Chromium запущен")
        return _browser
    except Exception as e:
        logger.error(f"❌ Playwright недоступен: {e}")
        return None


async def screenshot(url: str) -> dict:
    """Делает скриншот страницы. Возвращает путь к файлу."""
    if _is_blocked(url):
        return {"success": False, "error": f"URL заблокирован: {url}"}

    browser = await _get_browser()
    if not browser:
        return {"success": False, "error": "Playwright недоступен. Запусти: playwright install chromium"}

    start = time.time()
    page  = None
    try:
        page = await browser.new_page(
            viewport={"width": 1280, "height": 720}
        )
        await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)

        tmp  = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        path = tmp.name
        tmp.close()

        await page.screenshot(path=path, full_page=False)
        duration = round(time.time() - start, 2)

        title = await page.title()
        logger.info(f"[Browser] Screenshot {url} за {duration}с")

        await bus.publish("browser_screenshot", {"url": url, "duration": duration})

        return {
            "success":  True,
            "path":     path,
            "title":    title,
            "url":      url,
            "duration": duration,
        }
    except Exception as e:
        logger.error(f"[Browser] Screenshot error: {e}")
        return {"success": False, "error": str(e), "url": url}
    finally:
        if page:
            await page.close()


async def get_content(url: str) -> dict:
    """Извлекает текстовый контент страницы."""
    if _is_blocked(url):
        return {"success": False, "error": f"URL заблокирован: {url}"}

    browser = await _get_browser()
    if not browser:
        return {"success": False, "error": "Playwright недоступен"}

    start = time.time()
    page  = None
    try:
        page = await browser.new_page()
        await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)

        title   = await page.title()
        content = await page.inner_text("body")
        content = " ".join(content.split())[:MAX_CONTENT]
        duration = round(time.time() - start, 2)

        links = await page.eval_on_selector_all(
            "a[href]",
            "els => els.slice(0, 10).map(e => ({text: e.innerText.trim(), href: e.href}))"
        )

        await bus.publish("browser_content", {"url": url, "duration": duration})

        return {
            "success":  True,
            "title":    title,
            "content":  content,
            "links":    links,
            "url":      url,
            "duration": duration,
        }
    except Exception as e:
        logger.error(f"[Browser] Content error: {e}")
        return {"success": False, "error": str(e), "url": url}
    finally:
        if page:
            await page.close()


async def check_url(url: str) -> dict:
    """Проверяет доступность URL и базовую информацию."""
    if _is_blocked(url):
        return {"success": False, "error": f"URL заблокирован: {url}"}

    browser = await _get_browser()
    if not browser:
        return {"success": False, "error": "Playwright недоступен"}

    start = time.time()
    page  = None
    try:
        page     = await browser.new_page()
        response = await page.goto(url, timeout=TIMEOUT_MS)
        duration = round(time.time() - start, 2)
        title    = await page.title()

        return {
            "success":     True,
            "status":      response.status if response else 0,
            "title":       title,
            "url":         url,
            "duration":    duration,
            "ok":          response.ok if response else False,
        }
    except Exception as e:
        return {
            "success":  False,
            "error":    str(e),
            "url":      url,
            "duration": round(time.time() - start, 2),
        }
    finally:
        if page:
            await page.close()


async def run_js(url: str, script: str) -> dict:
    """Выполняет JavaScript на странице."""
    if _is_blocked(url):
        return {"success": False, "error": f"URL заблокирован"}

    browser = await _get_browser()
    if not browser:
        return {"success": False, "error": "Playwright недоступен"}

    page = None
    try:
        page   = await browser.new_page()
        await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        result = await page.evaluate(script)
        return {"success": True, "result": str(result)[:2000], "url": url}
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}
    finally:
        if page:
            await page.close()


async def close() -> None:
    global _browser, _playwright
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    logger.info("Browser закрыт")