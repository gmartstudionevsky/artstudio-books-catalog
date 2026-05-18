from __future__ import annotations

import json
import re
from dataclasses import asdict
from html import unescape
from time import sleep
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import ParsedBook

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

PRICE_RE = re.compile(r"(?:(?:Цена|price|стоимость)[^0-9]{0,20})?([0-9][0-9\s]{1,8})(?:\s?₽|\s?руб|\s?р\.)", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: Any, max_len: int | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = ", ".join(clean_text(v) for v in value if v)
    text = unescape(str(value))
    text = WHITESPACE_RE.sub(" ", text).strip()
    if max_len and len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def normalize_price(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return f"{int(value):,}".replace(",", " ") + " ₽"
    text = clean_text(value)
    match = PRICE_RE.search(text)
    if match:
        digits = re.sub(r"\D", "", match.group(1))
        if digits:
            return f"{int(digits):,}".replace(",", " ") + " ₽"
    # JSON-LD often returns pure numeric strings.
    digits_only = re.sub(r"\D", "", text)
    if digits_only and 2 <= len(digits_only) <= 7:
        return f"{int(digits_only):,}".replace(",", " ") + " ₽"
    return text[:60]


def source_name(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "").lower()
    if "ozon" in host:
        return "Ozon"
    if "labirint" in host:
        return "Лабиринт"
    if "book24" in host:
        return "Book24"
    if "chitai-gorod" in host:
        return "Читай-город"
    if "alpinabook" in host:
        return "Альпина"
    return host or "Источник"


def iter_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = parsed if isinstance(parsed, list) else [parsed]
        while stack:
            obj = stack.pop(0)
            if isinstance(obj, dict):
                objects.append(obj)
                graph = obj.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
            elif isinstance(obj, list):
                stack.extend(obj)
    return objects


def find_best_structured_object(objects: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred_types = {"book", "product", "creativework"}
    for obj in objects:
        obj_type = obj.get("@type", "")
        if isinstance(obj_type, list):
            type_values = {str(x).lower() for x in obj_type}
        else:
            type_values = {str(obj_type).lower()}
        if type_values & preferred_types:
            return obj
    for obj in objects:
        if obj.get("name") and (obj.get("image") or obj.get("description") or obj.get("offers")):
            return obj
    return None


def extract_author(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return ", ".join(filter(None, [extract_author(v) for v in value]))
    if isinstance(value, dict):
        return clean_text(value.get("name"))
    return clean_text(value)


def extract_images(value: Any, base_url: str) -> list[str]:
    images: list[str] = []

    def add(candidate: Any) -> None:
        if not candidate:
            return
        if isinstance(candidate, dict):
            candidate = candidate.get("url") or candidate.get("contentUrl")
        if isinstance(candidate, list):
            for item in candidate:
                add(item)
            return
        text = str(candidate).strip()
        if not text or text.startswith("data:"):
            return
        if text.startswith("//"):
            text = "https:" + text
        elif text.startswith("/"):
            text = urljoin(base_url, text)
        if text.startswith("http") and text not in images:
            images.append(text)

    add(value)
    return images


def extract_og(soup: BeautifulSoup, prop: str) -> str:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    if tag and tag.get("content"):
        return clean_text(tag.get("content"))
    return ""


def parse_from_soup(url: str, soup: BeautifulSoup) -> ParsedBook:
    result = ParsedBook(url=url, source=source_name(url))
    structured = find_best_structured_object(iter_json_ld(soup))

    if structured:
        offers = structured.get("offers") or {}
        if isinstance(offers, list) and offers:
            offers = offers[0]
        if not isinstance(offers, dict):
            offers = {}
        result.title = clean_text(structured.get("name"), 160)
        result.author = extract_author(structured.get("author") or structured.get("creator"))
        result.description = clean_text(structured.get("description"), 550)
        result.price = normalize_price(offers.get("price") or offers.get("lowPrice") or offers.get("highPrice"))
        availability = clean_text(offers.get("availability") or structured.get("availability"))
        if availability:
            result.availability = "есть" if "instock" in availability.lower() or "in stock" in availability.lower() else availability
        result.images.extend(extract_images(structured.get("image"), url))

    # OpenGraph fallback.
    if not result.title:
        result.title = clean_text(extract_og(soup, "og:title") or (soup.title.string if soup.title else ""), 160)
    if not result.description:
        result.description = clean_text(extract_og(soup, "og:description") or extract_og(soup, "description"), 550)
    og_image = extract_og(soup, "og:image")
    result.images.extend([img for img in extract_images(og_image, url) if img not in result.images])

    # Meta itemprop fallback.
    if not result.price:
        price_tag = soup.find(attrs={"itemprop": "price"}) or soup.find("meta", attrs={"property": "product:price:amount"})
        if price_tag:
            result.price = normalize_price(price_tag.get("content") or price_tag.get_text())
    if not result.price:
        body_text = clean_text(soup.get_text(" "), 5000)
        match = PRICE_RE.search(body_text)
        if match:
            result.price = normalize_price(match.group(0))

    if not result.images:
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original")
            alt = clean_text(img.get("alt"))
            src_text = str(src or "")
            if not src_text:
                continue
            score = 0
            if any(token in src_text.lower() for token in ["cover", "product", "book", "item", "img"]):
                score += 1
            if any(token in alt.lower() for token in ["книга", "book", "облож", "cover"]):
                score += 1
            if score > 0:
                result.images.extend([img_url for img_url in extract_images(src_text, url) if img_url not in result.images])
            if len(result.images) >= 2:
                break

    if not result.title:
        result.status = "NEEDS_REVIEW"
        result.error = "Не удалось определить название. Возможно, сайт отдал динамическую страницу или капчу."
    result.images = result.images[:2]
    result.raw = {"structured": structured or {}, "og_title": extract_og(soup, "og:title")}
    return result


def fetch_static(url: str, timeout: int = 25) -> str:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_rendered(url: str, timeout_ms: int = 35000) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="ru-RU")
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        html = page.content()
        browser.close()
        return html


def parse_book(url: str, enable_playwright_fallback: bool = False, delay_seconds: float = 0.0) -> ParsedBook:
    if delay_seconds > 0:
        sleep(delay_seconds)
    result = ParsedBook(url=url, source=source_name(url))
    try:
        html = fetch_static(url)
        soup = BeautifulSoup(html, "lxml")
        parsed = parse_from_soup(url, soup)
        if parsed.status == "NEEDS_REVIEW" and enable_playwright_fallback:
            rendered = fetch_rendered(url)
            parsed = parse_from_soup(url, BeautifulSoup(rendered, "lxml"))
        return parsed
    except Exception as exc:  # noqa: BLE001
        result.status = "ERROR"
        result.error = f"{type(exc).__name__}: {exc}"
        return result


def parsed_to_debug_dict(parsed: ParsedBook) -> dict[str, Any]:
    data = asdict(parsed)
    if len(str(data.get("raw", ""))) > 1000:
        data["raw"] = "<trimmed>"
    return data
