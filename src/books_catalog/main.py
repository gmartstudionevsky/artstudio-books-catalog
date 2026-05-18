from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .classifier import infer_place, infer_scores, infer_topic, summarize_description
from .drive import upload_pdf_to_drive
from .models import BookRow
from .parser import parse_book, parsed_to_debug_dict
from .pdf import generate_pdf
from .settings import get_settings
from .sheets import SheetsClient, normalize_values, serialize_rows


def should_parse(row: BookRow, force_refresh: bool) -> bool:
    if not row.url:
        return False
    if force_refresh:
        return True
    if row.title and row.status in {"OK", "SKIPPED"}:
        return False
    return True


def enrich_row(row: BookRow, force_refresh: bool, enable_playwright_fallback: bool, delay_seconds: float) -> dict[str, Any]:
    if not should_parse(row, force_refresh=force_refresh):
        row.set_value("Статус парсинга", row.status or "SKIPPED")
        return {"row": row.row_number, "url": row.url, "status": "SKIPPED"}

    parsed = parse_book(
        row.url,
        enable_playwright_fallback=enable_playwright_fallback,
        delay_seconds=delay_seconds,
    )
    row.setdefault_nonempty("Источник", parsed.source, force=force_refresh)
    row.setdefault_nonempty("Название", parsed.title, force=force_refresh)
    row.setdefault_nonempty("Автор", parsed.author, force=force_refresh)
    row.setdefault_nonempty("Цена", parsed.price, force=force_refresh)
    row.setdefault_nonempty("Наличие", parsed.availability, force=force_refresh)
    row.setdefault_nonempty("Краткое описание", summarize_description(parsed.description), force=force_refresh)
    if parsed.images:
        row.setdefault_nonempty("Картинка 1", parsed.images[0], force=force_refresh)
    if len(parsed.images) > 1:
        row.setdefault_nonempty("Картинка 2", parsed.images[1], force=force_refresh)

    topic = infer_topic(row.data.get("Название", ""), row.data.get("Краткое описание", ""))
    row.setdefault_nonempty("Тематика", topic, force=force_refresh)
    place = infer_place(row.data.get("Тематика", topic), row.data.get("Название", ""), row.data.get("Краткое описание", ""))
    row.setdefault_nonempty("Подходит для", place, force=force_refresh)
    visual, context, priority = infer_scores(row.data.get("Тематика", ""), row.data.get("Краткое описание", ""))
    row.setdefault_nonempty("Визуальная ценность", visual, force=force_refresh)
    row.setdefault_nonempty("Контекст ARTSTUDIO", context, force=force_refresh)
    row.setdefault_nonempty("Приоритет закупки", priority, force=force_refresh)
    row.setdefault_nonempty("Включить в PDF", "TRUE", force=False)
    row.set_value("Статус парсинга", parsed.status)
    if parsed.error:
        existing_comment = row.data.get("Комментарий", "")
        if parsed.error not in existing_comment:
            row.set_value("Комментарий", f"{existing_comment} | {parsed.error}".strip(" |"))
    row.mark_updated()
    return {"row": row.row_number, "status": parsed.status, "parsed": parsed_to_debug_dict(parsed)}


def main() -> None:
    settings = get_settings()
    sheets = SheetsClient(settings)
    values = sheets.read_values()
    headers, rows, migrated = normalize_values(values)

    if settings.max_rows and settings.max_rows > 0:
        rows_to_process = rows[: settings.max_rows]
    else:
        rows_to_process = rows

    parse_log: list[dict[str, Any]] = []
    for row in rows_to_process:
        parse_log.append(
            enrich_row(
                row,
                force_refresh=settings.force_refresh,
                enable_playwright_fallback=settings.enable_playwright_fallback,
                delay_seconds=settings.request_delay_seconds,
            )
        )

    serialized = serialize_rows(headers, rows)
    sheets.write_values(serialized)
    sheets.apply_formatting()

    html_path, pdf_path = generate_pdf(
        rows,
        output_dir=settings.output_dir,
        include_only_checked=settings.include_only_checked,
    )
    drive_link = upload_pdf_to_drive(settings, pdf_path)

    summary = {
        "spreadsheet_id": settings.spreadsheet_id,
        "sheet_name": settings.sheet_name,
        "migrated": migrated,
        "rows_total": len(rows),
        "rows_processed": len(rows_to_process),
        "html": str(html_path),
        "pdf": str(pdf_path),
        "drive_link": drive_link,
        "log": parse_log,
    }
    summary_path = Path(settings.output_dir) / "run_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
