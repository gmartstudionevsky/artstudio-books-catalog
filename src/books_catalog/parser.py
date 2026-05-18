from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import ParsedBook

# =============================================
# Headers & Utils
# =============================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="135", "Not-A-Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

OZON_ANTIBOT_MARKERS = ["проверка безопасности", "подтвердите, что вы не робот", "captcha", "access denied", "unusual traffic"]


def is_ozon_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in {"ozon.ru", "www.ozon.ru"}


def normalize_ozon_url(url: str) -> str:
    p = urlparse(url)
    return f"https://{p.netloc.rstrip('/')}{p.path}"


def resolve_short_url(url: str) -> str:
    """Раскрывает короткие ссылки https://ozon.ru/t/XXXXX"""
    if not urlparse(url).path.startswith("/t/"):
        return url
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        return r.url
    except:
        return url


def call_composer_api(url: str) -> dict | None:
    """Главный рабочий метод 2026 года"""
    try:
        payload = {"url": url, "pageType": "product"}
        r = requests.post(
            "https://www.ozon.ru/api/composer-api.bx/page/json/v2",
            json=payload,
            headers={
                **HEADERS,
                "Content-Type": "application/json",
                "x-o3-app-name": "site",
                "referer": url,
            },
            timeout=18
        )
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None


def extract_from_composer(data: dict) -> dict:
    result: dict[str, Any] = {}
    widgets = data.get("widgetStates", {}) or {}

    for key, value_str in widgets.items():
        try:
            widget = json.loads(value_str)

            # Основные данные
            if any(x in key.lower() for x in ["webSale", "product", "sale"]):
                info = widget.get("cellTrackingInfo", {}).get("product", {}) or widget.get("product", {})
                if info:
                    result.update({
                        "title": info.get("title") or info.get("name"),
                        "price": info.get("price") or info.get("finalPrice") or info.get("currentPrice"),
                        "brand": info.get("brand"),
                    })

            # Изображения
            if any(x in key.lower() for x in ["gallery", "image", "photo"]):
                imgs = widget.get("images", []) or widget.get("gallery", [])
                if isinstance(imgs, list):
                    for img in imgs:
                        if isinstance(img, str) and img.startswith("http"):
                            result.setdefault("images", []).append(img)
                        elif isinstance(img, dict):
                            src = img.get("url") or img.get("src") or img.get("original")
                            if src and src.startswith("http"):
                                result.setdefault("images", []).append(src)

            # Описание
            if "description" in key.lower():
                result["description"] = widget.get("description") or widget.get("text")

        except:
            continue

    return result


def fetch_with_playwright(url: str) -> dict:
    """Stealth Playwright fallback"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1800)

        # Скроллинг
        page.evaluate("window.scrollBy(0, 700)")
        page.wait_for_timeout(900)
        page.evaluate("window.scrollBy(0, 600)")

        data = page.evaluate("""() => ({
            title: document.querySelector('h1')?.innerText?.trim() || '',
            price: document.querySelector('[data-testid*="price"], .price')?.innerText || '',
            images: Array.from(document.querySelectorAll('img[src*="ozon"]')).map(i => i.src || i.currentSrc)
        })""")

        browser.close()
        return data


# =============================================
# Основная функция парсинга
# =============================================

def parse_ozon_product(
    url: str,
    enable_browser: bool = True,
    browser_mode: str = "fallback",
    debug_dir: str | None = None
) -> ParsedBook:
    
    canonical = normalize_ozon_url(resolve_short_url(url))
    result = ParsedBook(url=canonical, source="Ozon")
    raw: dict[str, Any] = {"original_url": url, "canonical": canonical}

    # 1. Composer API (самый надёжный)
    composer_data = call_composer_api(canonical)
    if composer_data:
        extracted = extract_from_composer(composer_data)
        result.title = extracted.get("title") or ""
        result.price = str(extracted.get("price") or "")
        result.description = extracted.get("description") or ""
        result.images = extracted.get("images", [])[:3]
        raw["method"] = "composer_api"

    # 2. Browser fallback
    if enable_browser and (browser_mode == "always" or (browser_mode == "fallback" and (not result.title or not result.price))):
        try:
            pw = fetch_with_playwright(canonical)
            if not result.title:
                result.title = pw.get("title", "")
            if not result.price:
                result.price = pw.get("price", "")
            if len(result.images) < 2:
                result.images.extend([i for i in pw.get("images", []) if i and i not in result.images])
            raw["method"] = "playwright"
            raw["playwright_used"] = True
        except Exception as e:
            raw["browser_error"] = str(e)

    # Финализация
    result.images = list(dict.fromkeys([img for img in result.images if "ozon" in img.lower()]))[:2]

    if not result.title:
        result.status = "NEEDS_REVIEW"
        result.error = "Не удалось получить название товара"
    elif not result.price:
        result.status = "Частично"
        result.error = "Название есть, цена не найдена"
    else:
        result.status = "OK"

    result.raw = raw
    return result


# =============================================
# Общая функция (используется в main.py)
# =============================================

def parse_book(
    url: str,
    enable_playwright_fallback: bool = False,
    delay_seconds: float = 0.0,
    ozon_browser_mode: str = "fallback",
    debug_dir: str | None = None,
) -> ParsedBook:
    
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    if is_ozon_url(url):
        return parse_ozon_product(
            url,
            enable_browser=enable_playwright_fallback,
            browser_mode=ozon_browser_mode,
            debug_dir=debug_dir
        )

    # Для других сайтов — простой парсинг
    result = ParsedBook(url=url, source=urlparse(url).netloc)
    try:
        html = requests.get(url, headers=HEADERS, timeout=20).text
        soup = BeautifulSoup(html, "lxml")
        result.title = (soup.title.string or "").strip()
        result.status = "OK" if result.title else "NEEDS_REVIEW"
    except Exception as e:
        result.status = "ERROR"
        result.error = str(e)
    
    return result


def parsed_to_debug_dict(parsed: ParsedBook) -> dict[str, Any]:
    data = asdict(parsed)
    if isinstance(data.get("raw"), dict) and len(str(data["raw"])) > 3000:
        data["raw"] = "<trimmed_for_size>"
    return data
