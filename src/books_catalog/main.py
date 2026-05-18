from __future__ import annotations

import argparse
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


def build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--single-url")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--output-json")
    return p


def should_parse(row: BookRow, force_refresh: bool) -> bool:
    if not row.url:
        return False
    if force_refresh:
        return True
    return not (row.title and row.status in {"OK", "SKIPPED"})


def enrich_row(
    row: BookRow,
    force_refresh: bool,
    enable_playwright_fallback: bool,
    delay_seconds: float,
    ozon_browser_mode: str,
) -> dict[str, Any]:
    if not should_parse(row, force_refresh=force_refresh):
        row.set_value("Статус парсинга", row.status or "SKIPPED")
        return {"row": row.row_number, "url": row.url, "status": "SKIPPED"}

    parsed = parse_book(
        row.url,
        enable_playwright_fallback=enable_playwright_fallback,
        delay_seconds=delay_seconds,
        ozon_browser_mode=ozon_browser_mode,
    )
    row.setdefault_nonempty("Источник", parsed.source, force=force_refresh)
    row.setdefault_nonempty("Название", parsed.title, force=force_refresh)
    row.setdefault_nonempty("Цена", parsed.price, force=force_refresh)
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
    row.set_value("Статус парсинга", parsed.status)
    if parsed.error:
        row.set_value("Комментарий", parsed.error)
    row.mark_updated()
    return {"row": row.row_number, "status": parsed.status, "parsed": parsed_to_debug_dict(parsed)}


def run_single_url(url: str, output_json: str | None, debug: bool) -> None:
    debug_dir = "output/debug" if debug else None
    parsed = parse_book(url, enable_playwright_fallback=True, debug_dir=debug_dir)
    data = parsed_to_debug_dict(parsed)
    data["source_url"] = url
    if output_json:
        p = Path(output_json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    cli_args, _ = build_cli().parse_known_args()
    if cli_args.single_url:
        run_single_url(cli_args.single_url, cli_args.output_json, cli_args.debug)
        return

    settings = get_settings()
    sheets = SheetsClient(settings)
    values = sheets.read_values()
    headers, rows, migrated = normalize_values(values)
    rows_to_process = rows[: settings.max_rows] if settings.max_rows and settings.max_rows > 0 else rows

    parse_log: list[dict[str, Any]] = []
    for row in rows_to_process:
        parse_log.append(
            enrich_row(
                row,
                settings.force_refresh,
                settings.enable_playwright_fallback,
                settings.request_delay_seconds,
                settings.ozon_browser_mode,
            )
        )

    sheets.write_values(serialize_rows(headers, rows))
    sheets.apply_formatting()

    html_path, pdf_path = generate_pdf(rows, output_dir=settings.output_dir, include_only_checked=settings.include_only_checked)
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
