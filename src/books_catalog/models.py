from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


HEADERS: list[str] = [
    "Ссылка",
    "Источник",
    "Название",
    "Автор",
    "Цена",
    "Наличие",
    "Краткое описание",
    "Тематика",
    "Подходит для",
    "Визуальная ценность",
    "Контекст ARTSTUDIO",
    "Приоритет закупки",
    "Включить в PDF",
    "Картинка 1",
    "Картинка 2",
    "Статус парсинга",
    "Обновлено",
    "Комментарий",
]

BOOLEAN_TRUE = {"true", "да", "yes", "1", "истина", "✓", "x", "х"}


@dataclass
class BookRow:
    row_number: int
    data: dict[str, str]
    changed: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return (self.data.get("Ссылка") or "").strip()

    @property
    def title(self) -> str:
        return (self.data.get("Название") or "").strip()

    @property
    def status(self) -> str:
        return (self.data.get("Статус парсинга") or "").strip()

    @property
    def include_in_pdf(self) -> bool:
        raw = str(self.data.get("Включить в PDF") or "").strip().lower()
        if raw == "":
            return True
        return raw in BOOLEAN_TRUE

    def setdefault_nonempty(self, key: str, value: Any, force: bool = False) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        if force or not str(self.data.get(key) or "").strip():
            self.data[key] = text
            self.changed = True

    def set_value(self, key: str, value: Any) -> None:
        text = "" if value is None else str(value).strip()
        if str(self.data.get(key) or "").strip() != text:
            self.data[key] = text
            self.changed = True

    def mark_updated(self) -> None:
        self.set_value("Обновлено", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


@dataclass
class ParsedBook:
    url: str
    source: str = ""
    title: str = ""
    author: str = ""
    price: str = ""
    availability: str = ""
    description: str = ""
    images: list[str] = field(default_factory=list)
    status: str = "OK"
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
