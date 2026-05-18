from __future__ import annotations

from typing import Iterable

from google.oauth2 import service_account
from google.auth.credentials import Credentials

from .settings import Settings


def build_credentials(settings: Settings, scopes: Iterable[str]) -> Credentials:
    scope_list = list(scopes)
    if settings.service_account_info:
        return service_account.Credentials.from_service_account_info(
            settings.service_account_info,
            scopes=scope_list,
        )
    if settings.service_account_file:
        return service_account.Credentials.from_service_account_file(
            settings.service_account_file,
            scopes=scope_list,
        )
    raise RuntimeError(
        "Google credentials are missing. Set GOOGLE_SERVICE_ACCOUNT_JSON_B64 or GOOGLE_APPLICATION_CREDENTIALS."
    )
