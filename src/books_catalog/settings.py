from __future__ import annotations

import argparse
import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    spreadsheet_id: str
    sheet_name: str
    output_dir: Path
    drive_folder_id: str | None
    force_refresh: bool
    max_rows: int
    include_only_checked: bool
    enable_playwright_fallback: bool
    request_delay_seconds: float
    ozon_browser_mode: str
    service_account_info: dict[str, Any] | None
    service_account_file: str | None


def str_to_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "да", "истина"}


def load_service_account_info() -> dict[str, Any] | None:
    encoded = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "").strip()
    if not encoded:
        return None
    decoded = base64.b64decode(encoded).decode("utf-8")
    return json.loads(decoded)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update ARTSTUDIO books Google Sheet and generate PDF catalog.")
    parser.add_argument("--spreadsheet-id", default=os.getenv("SPREADSHEET_ID"))
    parser.add_argument("--sheet-name", default=os.getenv("SHEET_NAME", "Лист1"))
    parser.add_argument("--output-dir", default=os.getenv("OUTPUT_DIR", "output"))
    parser.add_argument("--drive-folder-id", default=os.getenv("DRIVE_FOLDER_ID") or None)
    parser.add_argument("--force-refresh", action="store_true", default=str_to_bool(os.getenv("FORCE_REFRESH")))
    parser.add_argument("--max-rows", type=int, default=int(os.getenv("MAX_ROWS", "0") or 0))
    parser.add_argument("--include-only-checked", action="store_true", default=str_to_bool(os.getenv("INCLUDE_ONLY_CHECKED")))
    parser.add_argument("--enable-playwright-fallback", action="store_true", default=str_to_bool(os.getenv("ENABLE_PLAYWRIGHT_FALLBACK")))
    parser.add_argument("--request-delay-seconds", type=float, default=float(os.getenv("REQUEST_DELAY_SECONDS", "0.7") or 0.7))
    return parser.parse_args()


def get_settings() -> Settings:
    load_dotenv()
    args = parse_args()
    spreadsheet_id = args.spreadsheet_id
    if not spreadsheet_id:
        raise RuntimeError("SPREADSHEET_ID is required.")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ozon_browser_mode = (os.getenv("OZON_BROWSER_MODE", "fallback") or "fallback").strip().lower()
    if ozon_browser_mode not in {"never", "fallback", "always"}:
        raise RuntimeError("OZON_BROWSER_MODE must be one of: never, fallback, always")
    return Settings(
        spreadsheet_id=spreadsheet_id,
        sheet_name=args.sheet_name,
        output_dir=output_dir,
        drive_folder_id=args.drive_folder_id,
        force_refresh=args.force_refresh,
        max_rows=args.max_rows,
        include_only_checked=args.include_only_checked,
        enable_playwright_fallback=args.enable_playwright_fallback,
        request_delay_seconds=args.request_delay_seconds,
        ozon_browser_mode=ozon_browser_mode,
        service_account_info=load_service_account_info(),
        service_account_file=os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or None,
    )
