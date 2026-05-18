from __future__ import annotations

import re


def infer_topic(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    rules = [
        ("Петербург", ["петербург", "санкт-петербург", "невский", "ленинград", "spb", "saint petersburg"]),
        ("Архитектура и город", ["архитект", "urban", "город", "city", "building", "здание", "дворец", "интерьер"]),
        ("Искусство", ["искусств", "art", "painting", "museum", "музей", "живопис", "худож", "картина"]),
        ("Театр и сцена", ["театр", "theatre", "theater", "ballet", "балет", "опера", "сцена", "мариин"]),
        ("Дизайн и lifestyle", ["design", "дизайн", "fashion", "style", "стиль", "lifestyle", "интерьер", "декор"]),
        ("История и наследие", ["истор", "history", "heritage", "наслед", "император", "романов"]),
        ("Фотоальбом", ["фото", "photo", "photography", "альбом", "иллюстрац"]),
    ]
    matched = [name for name, tokens in rules if any(token in text for token in tokens)]
    if matched:
        return " / ".join(matched[:2])
    return "Coffee table / общее"


def infer_place(topic: str, title: str, description: str) -> str:
    text = f"{topic} {title} {description}".lower()
    if any(t in text for t in ["петербург", "театр", "искусство", "архитект"]):
        return "лаунж / ресепшен"
    if any(t in text for t in ["дизайн", "lifestyle", "фотоальбом"]):
        return "лаунж"
    return "лаунж / библиотека"


def infer_scores(topic: str, description: str) -> tuple[int, int, str]:
    text = f"{topic} {description}".lower()
    visual = 3
    context = 3
    if any(t in text for t in ["фото", "альбом", "иллюстрац", "art", "искусств", "дизайн", "архитект"]):
        visual += 1
    if any(t in text for t in ["петербург", "невский", "театр", "архитект", "искусств", "heritage"]):
        context += 1
    if any(t in text for t in ["детектив", "роман", "триллер", "эзотер", "саморазвит"]):
        context -= 1
    visual = min(max(visual, 1), 5)
    context = min(max(context, 1), 5)
    if context >= 4 and visual >= 4:
        priority = "высокий"
    elif context >= 3 and visual >= 3:
        priority = "средний"
    else:
        priority = "низкий"
    return visual, context, priority


def summarize_description(description: str, max_chars: int = 430) -> str:
    text = re.sub(r"\s+", " ", description or "").strip()
    if not text:
        return "Описание не найдено автоматически; требуется ручная проверка карточки."
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
