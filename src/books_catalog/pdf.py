from __future__ import annotations

import base64
import ipaddress
import mimetypes
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from .classifier import infer_topic
from .models import BookRow
from .parser import HEADERS as REQUEST_HEADERS


def price_as_number(price: str) -> int:
    digits = re.sub(r"\D", "", price or "")
    return int(digits) if digits else 0


def is_safe_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
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


def image_to_data_uri(url: str, timeout: int = 15) -> str:
    if not url:
        return ""
    if not is_safe_image_url(url):
        return ""
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout, stream=True)
        response.raise_for_status()
        max_bytes = 8 * 1024 * 1024
        content = b""
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            content += chunk
            if len(content) > max_bytes:
                return url
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        if not content_type or not content_type.startswith("image/"):
            content_type = mimetypes.guess_type(url)[0] or "image/jpeg"
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
    except Exception:
        return url



def normalize_topic(topic: str, title: str) -> str:
    base = (topic or "").strip()
    if base and base.lower() not in {"", "без тематики", "coffee table / общее"}:
        return base
    inferred = infer_topic(title or "", "")
    return inferred or "Без тематики"


def topic_sort_key(topic: str) -> tuple[int, str]:
    normalized = (topic or "").strip()
    priority = [
        "Петербург",
        "Архитектура и город",
        "Искусство",
        "Театр и сцена",
        "Дизайн и lifestyle",
        "История и наследие",
        "Фотоальбом",
        "Coffee table / общее",
        "Без тематики",
    ]
    first = normalized.split("/")[0].strip() if "/" in normalized else normalized
    try:
        rank = priority.index(first)
    except ValueError:
        rank = len(priority)
    return (rank, normalized.lower())

def prepare_pdf_books(rows: list[BookRow], include_only_checked: bool = False) -> list[dict[str, Any]]:
    books: list[dict[str, Any]] = []
    for row in rows:
        if not row.url:
            continue
        if include_only_checked and not row.include_in_pdf:
            continue
        if not row.title and row.status not in {"OK", "SKIPPED"}:
            continue
        image1 = image_to_data_uri(row.data.get("Картинка 1", ""))
        image2 = image_to_data_uri(row.data.get("Картинка 2", ""))
        books.append(
            {
                "url": row.url,
                "source": row.data.get("Источник", ""),
                "title": row.data.get("Название", "Без названия"),
                "price": row.data.get("Цена", ""),
                "price_num": price_as_number(row.data.get("Цена", "")),
                "topic": normalize_topic(row.data.get("Тематика", ""), row.data.get("Название", "")),
                "include_in_pdf": row.data.get("Включить в PDF", ""),
                "include_in_pdf_bool": str(row.data.get("Включить в PDF", "")).strip().lower() in {"true", "1", "yes", "y", "да"},
                "image1": image1,
                "image2": image2,
            }
        )
    books.sort(key=lambda item: (topic_sort_key(item["topic"]), item["title"].lower()))
    return books


def group_by_topic(books: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for book in books:
        grouped[book["topic"] or "Без тематики"].append(book)
    return dict(sorted(grouped.items(), key=lambda kv: topic_sort_key(kv[0])))


def render_html(rows: list[BookRow], output_dir: Path, include_only_checked: bool = False) -> Path:
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    books = prepare_pdf_books(rows, include_only_checked=include_only_checked)
    grouped = group_by_topic(books)
    total_budget = sum(book["price_num"] for book in books)
    html = env.get_template("catalog.html.j2").render(
        books=books,
        grouped=grouped,
        total_count=len(books),
        total_budget=f"{total_budget:,}".replace(",", " ") + " ₽" if total_budget else "не определен",
        high_priority_count=sum(1 for book in books if book.get("include_in_pdf_bool")),
        topic_count=len(grouped),
    )
    html_path = output_dir / "books_catalog.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


def html_to_pdf(html_path: Path, output_pdf: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ru-RU")
        # NOTE:
        # For local file:// HTML `networkidle` can hang/timeout when the page
        # references remote assets (e.g. image URLs that keep retrying or stay pending).
        # We only need the DOM and styles applied for PDF generation.
        page.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("load", timeout=10000)
        except Exception:
            pass
        page.emulate_media(media="screen")
        page.pdf(
            path=str(output_pdf),
            format="A4",
            print_background=True,
            margin={"top": "12mm", "right": "12mm", "bottom": "14mm", "left": "12mm"},
        )
        browser.close()


def generate_pdf(rows: list[BookRow], output_dir: Path, include_only_checked: bool = False) -> tuple[Path, Path]:
    html_path = render_html(rows, output_dir=output_dir, include_only_checked=include_only_checked)
    pdf_path = output_dir / "books_catalog.pdf"
    html_to_pdf(html_path, pdf_path)
    return html_path, pdf_path
