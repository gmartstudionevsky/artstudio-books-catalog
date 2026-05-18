from __future__ import annotations

import json
import ipaddress
import re
from dataclasses import asdict
from html import unescape
from pathlib import Path
from time import sleep
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .models import ParsedBook

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

OZON_ANTIBOT_MARKERS = [
    "доступ ограничен",
    "проверка безопасности",
    "подтвердите, что вы не робот",
    "captcha",
    "access denied",
    "forbidden",
    "unusual traffic",
    "bot",
]
WHITESPACE_RE = re.compile(r"\s+")
PRICE_NUM_RE = re.compile(r"(\d[\d\s\u00A0\u2009\u202F]{0,15})(?:\s*(?:₽|руб\.?|р\.))", re.IGNORECASE)


def is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        pass
    return True


def clean_text(value: Any, max_len: int | None = None) -> str:
    if value is None:
        return ""
    text = unescape(str(value)).replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    text = WHITESPACE_RE.sub(" ", text).strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def normalize_price(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    m = PRICE_NUM_RE.search(text)
    candidate = m.group(1) if m else text
    digits = re.sub(r"\D", "", candidate)
    if digits:
        return f"{int(digits):,}".replace(",", " ") + " ₽"
    return ""


def is_ozon_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in {"ozon.ru", "www.ozon.ru"}


def extract_product_id_from_ozon_url(url: str) -> str:
    m = re.search(r"-(\d{6,})", urlparse(url).path)
    return m.group(1) if m else ""


def normalize_ozon_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme or "https", p.netloc, p.path, "", "", ""))


def cleanup_ozon_title(text: str) -> str:
    t = clean_text(text)
    t = re.sub(r"\s*купить\s+на\s+ozon.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*[-|]\s*ozon.*$", "", t, flags=re.IGNORECASE)
    return clean_text(t)


def detect_ozon_antibot(text: str) -> bool:
    low = clean_text(text).lower()
    return any(marker in low for marker in OZON_ANTIBOT_MARKERS)


def extract_best_from_srcset(srcset: str) -> str:
    parts = [p.strip() for p in srcset.split(",") if p.strip()]
    if not parts:
        return ""
    best = parts[-1].split()[0]
    return best


def filter_image(url: str) -> bool:
    low = url.lower()
    bad = ["logo", "icon", "avatar", "sprite", "pixel", "payment", "delivery"]
    return not any(x in low for x in bad)


def fetch_static(url: str, timeout: int = 25) -> str:
    s = requests.Session()
    s.headers.update(HEADERS)
    for i in range(3):
        r = s.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code < 500:
            r.raise_for_status()
            return r.text
        sleep(1 + i)
    r.raise_for_status()
    return ""


def fetch_rendered_ozon(url: str, timeout_ms: int = 35000) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=HEADERS["User-Agent"],
            locale="ru-RU",
            viewport={"width": 1440, "height": 2200},
            timezone_id="Europe/Moscow",
        )
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        data = page.evaluate(
            """() => ({
              title: document.title,
              h1: document.querySelector('h1')?.innerText || '',
              bodyText: document.body?.innerText || '',
              widgets: Array.from(document.querySelectorAll('[data-widget]')).map(n=>({w:n.getAttribute('data-widget'),t:n.innerText?.slice(0,1200)||''})),
              meta: Object.fromEntries(Array.from(document.querySelectorAll('meta[property],meta[name]')).map(m=>[(m.getAttribute('property')||m.getAttribute('name')||''), m.getAttribute('content')||''])),
              images: Array.from(document.querySelectorAll('img')).map(i=>({src:i.getAttribute('src')||'',currentSrc:i.currentSrc||'',srcset:i.getAttribute('srcset')||'',alt:i.getAttribute('alt')||''}))
            })"""
        )
        data["html"] = page.content()
        browser.close()
        return data


def parse_ozon_product(url: str, enable_browser: bool = True, debug_dir: str | None = None) -> ParsedBook:
    source_url = url
    canonical_url = normalize_ozon_url(url)
    result = ParsedBook(url=canonical_url, source="Ozon")
    raw: dict[str, Any] = {"source_url": source_url, "canonical_url": canonical_url, "product_id": extract_product_id_from_ozon_url(url)}
    html = ""
    try:
        html = fetch_static(canonical_url)
    except Exception as exc:
        raw["static_error"] = f"{type(exc).__name__}: {exc}"
    soup = BeautifulSoup(html, "lxml") if html else BeautifulSoup("", "lxml")
    og_title = clean_text((soup.find("meta", property="og:title") or {}).get("content", ""))
    og_desc = clean_text((soup.find("meta", property="og:description") or {}).get("content", ""), 700)
    og_img = clean_text((soup.find("meta", property="og:image") or {}).get("content", ""))
    price_meta = clean_text((soup.find("meta", property="product:price:amount") or {}).get("content", ""))

    result.title = cleanup_ozon_title(og_title)
    result.description = og_desc
    result.price = normalize_price(price_meta)
    if og_img and filter_image(og_img):
        result.images.append(og_img)

    page_data = {}
    if enable_browser:
        try:
            page_data = fetch_rendered_ozon(canonical_url)
        except Exception as exc:
            raw["browser_error"] = f"{type(exc).__name__}: {exc}"
    if page_data:
        body_text = page_data.get("bodyText", "")
        if detect_ozon_antibot(body_text):
            result.status = "Ozon anti-bot"
            result.error = "Ozon вернул страницу проверки/антибот, данные не извлечены"
        if not result.title:
            result.title = cleanup_ozon_title(page_data.get("h1") or page_data.get("meta", {}).get("og:title") or page_data.get("title", ""))
        if not result.description:
            result.description = clean_text(page_data.get("meta", {}).get("og:description", ""), 700)
        if not result.price:
            result.price = normalize_price(" ".join([w.get("t", "") for w in page_data.get("widgets", []) if "price" in w.get("w", "").lower()]))
        for img in page_data.get("images", []):
            candidate = img.get("currentSrc") or extract_best_from_srcset(img.get("srcset", "")) or img.get("src")
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            if candidate.startswith("/"):
                candidate = urljoin(canonical_url, candidate)
            if candidate.startswith("http") and filter_image(candidate) and candidate not in result.images:
                result.images.append(candidate)
    if debug_dir:
        d = Path(debug_dir)
        d.mkdir(parents=True, exist_ok=True)
        if html:
            (d / "ozon_static.html").write_text(html, encoding="utf-8")
        if page_data.get("html"):
            (d / "ozon_rendered.html").write_text(page_data["html"], encoding="utf-8")
        (d / "ozon_debug.json").write_text(json.dumps(page_data or raw, ensure_ascii=False, indent=2), encoding="utf-8")
    result.images = [i for i in result.images if i.startswith("http")][:2]
    missing = [k for k, v in {"title": result.title, "price": result.price, "description": result.description, "images": result.images}.items() if not v]
    if result.status != "Ozon anti-bot":
        if missing:
            result.status = "Частично"
            result.error = f"Не хватает полей: {', '.join(missing)}"
        else:
            result.status = "OK"
    result.raw = raw
    return result


def parse_book(url: str, enable_playwright_fallback: bool = False, delay_seconds: float = 0.0, debug_dir: str | None = None) -> ParsedBook:
    if delay_seconds > 0:
        sleep(delay_seconds)
    if is_ozon_url(url):
        return parse_ozon_product(url, enable_browser=True, debug_dir=debug_dir)
    result = ParsedBook(url=url, source=urlparse(url).netloc)
    try:
        html = fetch_static(url)
        soup = BeautifulSoup(html, "lxml")
        result.title = clean_text((soup.title.string if soup.title else ""), 160)
        result.description = clean_text(soup.get_text(" "), 550)
        result.status = "OK" if result.title else "NEEDS_REVIEW"
    except Exception as exc:
        result.status = "ERROR"
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def parsed_to_debug_dict(parsed: ParsedBook) -> dict[str, Any]:
    data = asdict(parsed)
    if len(str(data.get("raw", ""))) > 2500:
        data["raw"] = "<trimmed>"
    return data
