from __future__ import annotations

from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .auth import build_credentials
from .settings import Settings

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def upload_pdf_to_drive(settings: Settings, pdf_path: Path) -> str | None:
    if not settings.drive_folder_id:
        return None
    credentials = build_credentials(settings, SCOPES)
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    file_metadata = {
        "name": pdf_path.name,
        "parents": [settings.drive_folder_id],
        "mimeType": "application/pdf",
    }
    media = MediaFileUpload(str(pdf_path), mimetype="application/pdf", resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink").execute()
    return file.get("webViewLink") or file.get("id")
