import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

from src.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# Columns written to the sheet, in order — must match your sheet's header row exactly
COLUMNS = ["Company", "Title", "Status", "Job Posting Link"]


@dataclass
class ApplicationRecord:
    job_title: str
    url: str
    company: str
    status: str


def _get_client() -> gspread.Client:
    if settings.google_service_account_json:
        creds = Credentials.from_service_account_info(
            json.loads(settings.google_service_account_json),
            scopes=SCOPES,
        )
    else:
        creds = Credentials.from_service_account_file(
            settings.google_service_account_file,
            scopes=SCOPES,
        )
    return gspread.authorize(creds)


def _ensure_header(sheet: gspread.Worksheet) -> None:
    """Write the header row if the sheet is empty."""
    if sheet.row_count == 0 or not sheet.row_values(1):
        sheet.append_row(COLUMNS)


def append_application(record: ApplicationRecord) -> None:
    """Append one row to the configured Google Sheet."""
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(settings.google_sheet_id)

        try:
            sheet = spreadsheet.worksheet(settings.google_sheet_tab)
        except gspread.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(
                title=settings.google_sheet_tab, rows=1000, cols=len(COLUMNS)
            )

        _ensure_header(sheet)

        date_applied = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        row = [
            record.company,
            record.job_title,
            record.status,
            record.url,
        ]
        sheet.append_row(row)
        logger.info("Appended application to sheet: %s at %s", record.job_title, record.url)

    except Exception:
        logger.exception("Failed to append application to Google Sheet")
        raise
