from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .models import ParsedBook

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.ozon.ru/",
    "Sec-Ch-Ua": '"Chromium";v="135", "Not-A-Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

def is_ozon_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in {"ozon.ru", "www.ozon.ru"}

def resolve_to_full_url(url: str) -> str:
    """Надёжно раскрываем короткую ссылку ozon.ru/t/..."""
    if not urlparse(url).path.startswith("/t/"):
        return url
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        return r.url if r.status_code < 400 else url
    except:
        return url

def call_composer_api(url: str) -> dict | None:
    """Рабочий вызов composer-api.bx (2026)"""
    try:
        payload = {
            "url": url,
            "pageType": "product",
            "params": {}
        }
        r = requests.post(
            "https://www.ozon.ru/api/composer-api.bx/page/json/v2",
            json=payload,
            headers={
                **HEADERS,
                "Content-Type": "application/json",
                "x-o3-app-name": "site",
            },
            timeout=20
        )
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def extract_from_composer(data: dict) -> dict:
    result: dict[str, Any] = {"images": []}
    widgets = data.get("widgetStates", {}) or {}

    for key, val in widgets.items():
        try:
            w = json.loads(val)
            # Название + цена
            if any(x in key.lower() for x in ["websale", "product", "sale", "header"]):
                info = w.get("cellTrackingInfo", {}).get("product", {}) or w.get("product", {}) or w
                if isinstance(info, dict):
                    result["title"] = info.get("title") or info.get("name") or result.get("title")
                    result["price"] = info.get("price") or info.get("finalPrice") or info.get("currentPrice") or result.get("price")

            # Изображения
            if any(x in key.lower() for x in ["gallery", "image", "photo", "media"]):
                imgs = w.get("images", []) or w.get("gallery", [])
                if isinstance(imgs, list):
                    for item in imgs:
                        if isinstance(item, str) and item.startswith("http"):
                            result["images"].append(item)
                        elif isinstance(item, dict):
                            src = item.get("url") or item.get("src") or item.get("original")
                            if src and isinstance(src, str) and src.startswith("http"):
                                result["images"].append(src)

            # Описание
            if "description" in key.lower():
                result["description"] = w.get("description") or w.get("text") or result.get("description")
        except:
            continue
    return result

def fetch_with_playwright(url: str) -> dict:
    """Максимальный stealth Playwright"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-dev-shm-usage"
            ]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )

        # Максимальный stealth
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru']});
            Object.defineProperty(window, 'chrome', {get: () => ({runtime: {}})});
        """)

        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)

        # Human-like поведение
        page.wait_for_timeout(1800)
        page.mouse.move(300, 400)
        page.wait_for_timeout(600)
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(900)
        page.evaluate("window.scrollBy(0, 700)")
        page.wait_for_timeout(1200)

        data = page.evaluate("""() => ({
            title: document.querySelector('h1')?.innerText?.trim() || '',
            price: document.querySelector('[data-testid*="price"], .price, [class*="price"]')?.innerText?.trim() || '',
            images: Array.from(document.querySelectorAll('img')).map(i => i.src || i.currentSrc)
                .filter(src => src && src.includes('ozon') && src.length > 50)
        })""")

        browser.close()
        return data


def parse_ozon_product(url: str, enable_browser: bool = True, browser_mode: str = "always", debug_dir: str | None = None) -> ParsedBook:
    full_url = resolve_to_full_url(url)
    result = ParsedBook(url=full_url, source="Ozon")
    raw: dict[str, Any] = {"original_url": url, "full_url": full_url}

    # 1. Composer API
    composer_data = call_composer_api(full_url)
    if composer_data:
        ext = extract_from_composer(composer_data)
        result.title = ext.get("title", "")
        result.price = str(ext.get("price", ""))
        result.description = ext.get("description", "")
        result.images = ext.get("images", [])[:3]
        raw["method"] = "composer_api"

    # 2. Playwright (основной надёжный метод)
    if enable_browser and (browser_mode == "always" or (browser_mode == "fallback" and not result.title)):
        try:
            pw = fetch_with_playwright(full_url)
            if not result.title:
                result.title = pw.get("title", "")
            if not result.price:
                result.price = pw.get("price", "")
            if len(result.images) < 2:
                result.images.extend([i for i in pw.get("images", []) if i not in result.images][:2])
            raw["method"] = raw.get("method") or "playwright"
            raw["playwright_used"] = True
        except Exception as e:
            raw["browser_error"] = str(e)

    # Финализация
    result.images = list(dict.fromkeys([i for i in result.images if "ozon" in i.lower()]))[:2]

    if not result.title:
        result.status = "NEEDS_REVIEW"
        result.error = "Не удалось получить название (антибот)"
    elif not result.price:
        result.status = "Частично"
        result.error = "Название есть, цена не найдена"
    else:
        result.status = "OK"

    result.raw = raw

    # Debug (всегда сохраняем при наличии debug_dir)
    if debug_dir:
        d = Path(debug_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "ozon_debug.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def parse_book(
    url: str,
    enable_playwright_fallback: bool = True,
    delay_seconds: float = 1.5,
    ozon_browser_mode: str = "always",
    debug_dir: str | None = None,
) -> ParsedBook:
    
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    if is_ozon_url(url):
        return parse_ozon_product(url, enable_playwright_fallback, ozon_browser_mode, debug_dir)

    # Для других сайтов
    result = ParsedBook(url=url, source=urlparse(url).netloc)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "lxml")
        result.title = (soup.title.string or "").strip()
        result.status = "OK" if result.title else "NEEDS_REVIEW"
    except Exception as e:
        result.status = "ERROR"
        result.error = str(e)
    return result


def parsed_to_debug_dict(parsed: ParsedBook) -> dict[str, Any]:
    data = asdict(parsed)
    if len(str(data.get("raw"))) > 3000:
        data["raw"] = "<trimmed>"
    return data
