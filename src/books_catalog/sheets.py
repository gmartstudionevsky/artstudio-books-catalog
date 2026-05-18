from __future__ import annotations

import re
from typing import Any

from googleapiclient.discovery import build
from tenacity import retry, stop_after_attempt, wait_exponential

from .auth import build_credentials
from .models import BookRow, HEADERS
from .settings import Settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class SheetsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        credentials = build_credentials(settings, SCOPES)
        self.service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(5))
    def read_values(self) -> list[list[str]]:
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.settings.spreadsheet_id,
                range=f"'{self.settings.sheet_name}'!A1:Z1000",
                valueRenderOption="FORMATTED_VALUE",
            )
            .execute()
        )
        return result.get("values", [])

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(5))
    def write_values(self, values: list[list[Any]]) -> None:
        body = {"values": values}
        (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.settings.spreadsheet_id,
                range=f"'{self.settings.sheet_name}'!A1",
                valueInputOption="USER_ENTERED",
                body=body,
            )
            .execute()
        )

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(5))
    def apply_formatting(self) -> None:
        spreadsheet = (
            self.service.spreadsheets()
            .get(spreadsheetId=self.settings.spreadsheet_id, includeGridData=False)
            .execute()
        )
        sheet_id = None
        for sheet in spreadsheet.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == self.settings.sheet_name:
                sheet_id = props.get("sheetId")
                break
        if sheet_id is None:
            return

        requests = [
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.149, "green": 0.176, "blue": 0.212},
                            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": HEADERS.index("Приоритет закупки"),
                        "endColumnIndex": HEADERS.index("Приоритет закупки") + 1,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": "высокий"},
                                {"userEnteredValue": "средний"},
                                {"userEnteredValue": "низкий"},
                                {"userEnteredValue": "не брать"},
                            ],
                        },
                        "showCustomUi": True,
                        "strict": False,
                    },
                }
            },
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": HEADERS.index("Включить в PDF"),
                        "endColumnIndex": HEADERS.index("Включить в PDF") + 1,
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True, "strict": False},
                }
            },
            {
                "autoResizeDimensions": {
                    "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": len(HEADERS)}
                }
            },
        ]
        (
            self.service.spreadsheets()
            .batchUpdate(spreadsheetId=self.settings.spreadsheet_id, body={"requests": requests})
            .execute()
        )


def row_has_known_headers(row: list[str]) -> bool:
    normalized = {str(cell).strip().lower() for cell in row}
    return "ссылка" in normalized or "название" in normalized or "статус парсинга" in normalized


def extract_links_from_values(values: list[list[str]]) -> list[str]:
    links: list[str] = []
    for row in values:
        for cell in row:
            match = URL_RE.search(str(cell))
            if match:
                links.append(match.group(0).strip())
                break
    # preserve order, remove duplicates
    seen = set()
    result = []
    for url in links:
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def normalize_values(values: list[list[str]]) -> tuple[list[str], list[BookRow], bool]:
    """Return headers, rows, migrated flag.

    If the current sheet is just a raw list of links, migrate it to HEADERS + links.
    """
    if not values:
        return HEADERS, [], True

    first = values[0]
    if not row_has_known_headers(first):
        links = extract_links_from_values(values)
        rows = []
        for idx, link in enumerate(links, start=2):
            data = {header: "" for header in HEADERS}
            data["Ссылка"] = link
            data["Включить в PDF"] = "TRUE"
            rows.append(BookRow(row_number=idx, data=data, changed=True))
        return HEADERS, rows, True

    existing_headers = [str(cell).strip() for cell in first]
    headers = existing_headers[:]
    for required in HEADERS:
        if required not in headers:
            headers.append(required)

    rows: list[BookRow] = []
    for idx, row in enumerate(values[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue
        data = {header: "" for header in headers}
        for col_idx, header in enumerate(existing_headers):
            if col_idx < len(row):
                data[header] = str(row[col_idx]).strip()
        if not data.get("Ссылка"):
            # recover link from any cell if column name was different
            for cell in row:
                match = URL_RE.search(str(cell))
                if match:
                    data["Ссылка"] = match.group(0).strip()
                    break
        if not data.get("Включить в PDF"):
            data["Включить в PDF"] = "TRUE"
        rows.append(BookRow(row_number=idx, data=data))
    return headers, rows, headers != existing_headers


def serialize_rows(headers: list[str], rows: list[BookRow]) -> list[list[str]]:
    # Ensure canonical headers first, then any extra user columns.
    ordered_headers = HEADERS + [h for h in headers if h not in HEADERS]
    result = [ordered_headers]
    for row in rows:
        result.append([row.data.get(header, "") for header in ordered_headers])
    return result
