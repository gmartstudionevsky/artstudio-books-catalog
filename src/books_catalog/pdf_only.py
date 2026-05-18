from __future__ import annotations

import json
from pathlib import Path

from .drive import upload_pdf_to_drive
from .pdf import generate_pdf
from .settings import get_settings
from .sheets import SheetsClient, normalize_values


def main() -> None:
    settings = get_settings()
    sheets = SheetsClient(settings)
    values = sheets.read_values()
    _, rows, migrated = normalize_values(values)

    html_path, pdf_path = generate_pdf(rows, output_dir=settings.output_dir, include_only_checked=settings.include_only_checked)
    drive_link = upload_pdf_to_drive(settings, pdf_path)

    summary = {
        "spreadsheet_id": settings.spreadsheet_id,
        "sheet_name": settings.sheet_name,
        "migrated": migrated,
        "rows_total": len(rows),
        "html": str(html_path),
        "pdf": str(pdf_path),
        "drive_link": drive_link,
        "mode": "pdf_only",
    }
    summary_path = Path(settings.output_dir) / "run_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
