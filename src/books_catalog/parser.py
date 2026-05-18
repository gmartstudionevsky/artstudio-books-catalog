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
    return f"https://{p.netloc}{p.path}"

def resolve_short_url(url: str) -> str:
    if not urlparse(url).path.startswith("/t/"):
        return url
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        return r.url
    except:
        return url

def call_composer_api(url: str) -> dict | None:
    """Основной рабочий способ в 2026 году"""
    try:
        payload = {
            "url": url,
            "params": {},
            "pageType": "product"
        }
        r = requests.post(
            "https://www.ozon.ru/api/composer-api.bx/page/json/v2",
            json=payload,
            headers={
                **HEADERS,
                "Content-Type": "application/json",
                "x-o3-app-name": "site",
                "referer": url,
            },
            timeout=15
        )
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def extract_from_composer(data: dict) -> dict:
    result = {}
    widgets = data.get("widgetStates", {}) or {}

    for key, value in widgets.items():
        try:
            widget = json.loads(value)
            
            # Основные данные товара
            if "webSale" in key or "product" in key.lower():
                info = widget.get("cellTrackingInfo", {}).get("product", {}) or widget.get("product", {})
                if info:
                    result.update({
                        "title": info.get("title") or info.get("name"),
                        "price": info.get("price") or info.get("finalPrice"),
                        "old_price": info.get("originalPrice"),
                        "brand": info.get("brand"),
                        "rating": info.get("rating"),
                        "reviews": info.get("reviewsCount"),
                    })

            # Изображения
            if "gallery" in key.lower() or "images" in key.lower():
                imgs = widget.get("images", []) or widget.get("gallery", [])
                if isinstance(imgs, list):
                    for img in imgs:
                        if isinstance(img, str) and img.startswith("http"):
                            result.setdefault("images", []).append(img)
                        elif isinstance(img, dict):
                            src = img.get("url") or img.get("src")
                            if src and src.startswith("http"):
                                result.setdefault("images", []).append(src)

            # Характеристики и описание
            if "productDescription" in key or "characteristics" in key:
                result["description"] = widget.get("description") or widget.get("text")

        except:
            continue

    return result

def fetch_with_playwright(url: str) -> dict:
    """Улучшенный stealth Playwright"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )
        
        # Stealth
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru']});
        """)

        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        # Human-like behavior
        page.wait_for_timeout(1500)
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(800)
        page.evaluate("window.scrollBy(0, 600)")
        page.wait_for_timeout(1200)

        data = page.evaluate("""() => ({
            title: document.querySelector('h1')?.innerText?.trim(),
            price: document.querySelector('[data-testid*="price"], .price, [class*="price"]')?.innerText,
            images: Array.from(document.querySelectorAll('img')).map(img => ({
                src: img.src || img.currentSrc,
                srcset: img.getAttribute('srcset')
            })).filter(i => i.src && i.src.includes('ozon')),
            html: document.documentElement.outerHTML.substring(0, 80000)
        })""")

        browser.close()
        return data

def parse_ozon_product(url: str, enable_browser: bool = True, browser_mode: str = "fallback", debug_dir: str | None = None) -> ParsedBook:
    original_url = url
    canonical = normalize_ozon_url(resolve_short_url(url))
    
    result = ParsedBook(url=canonical, source="Ozon")
    raw: dict[str, Any] = {"original_url": original_url, "canonical": canonical}

    # 1. Попытка через Composer API (самый надёжный)
    composer_data = call_composer_api(canonical)
    if composer_data:
        extracted = extract_from_composer(composer_data)
        result.title = extracted.get("title") or ""
        result.price = str(extracted.get("price") or "")
        result.description = extracted.get("description") or ""
        result.images = extracted.get("images", [])[:2]
        raw["composer_used"] = True
        raw["composer"] = extracted

    # 2. Fallback на статический запрос
    if not result.title or not result.price:
        try:
            html = requests.get(canonical, headers=HEADERS, timeout=20).text
            soup = BeautifulSoup(html, "lxml")
            
            if soup.title:
                result.title = re.sub(r"\s+на OZON.*$", "", soup.title.string or "", flags=re.I).strip()
            
            # Попытка вытащить из meta
            for meta in soup.select('meta[property^="og:"], meta[property^="product:"]'):
                prop = meta.get("property", "")
                content = meta.get("content", "")
                if "title" in prop:
                    result.title = result.title or content
                if "image" in prop and content.startswith("http"):
                    result.images.append(content)
        except Exception as e:
            raw["static_error"] = str(e)

    # 3. Browser fallback
    needs_browser = not (result.title and result.price) or len(result.images) < 1
    if enable_browser and (browser_mode == "always" or (browser_mode == "fallback" and needs_browser)):
        try:
            pw_data = fetch_with_playwright(canonical)
            if not result.title:
                result.title = pw_data.get("title") or ""
            if not result.price:
                result.price = pw_data.get("price") or ""
            if len(result.images) < 2:
                for img in pw_data.get("images", []):
                    src = img.get("src") or ""
                    if src.startswith("http") and src not in result.images:
                        result.images.append(src)
            raw["playwright_used"] = True
        except Exception as e:
            raw["browser_error"] = str(e)

    # Финализация
    result.images = list(dict.fromkeys([i for i in result.images if "ozon" in i.lower()]))[:2]  # deduplicate
    
    if not result.title:
        result.status = "NEEDS_REVIEW"
        result.error = "Не удалось извлечь название"
    elif not result.price and not result.images:
        result.status = "Частично"
        result.error = "Нет цены и изображений"
    else:
        result.status = "OK"

    result.raw = raw
    return result


# Остальные функции (parse_book, is_safe_url и т.д.) оставь как были
# Только обнови parse_book, чтобы он вызывал новый parse_ozon_product
