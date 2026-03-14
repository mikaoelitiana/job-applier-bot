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
COLUMNS = ["Company", "Title", "Status", "Job Posting Link", "Contact", "Application Date", "Interview Stage", "Interviewer", "Notes"]


@dataclass
class ApplicationRecord:
    job_title: str
    url: str
    company: str
    status: str
    application_date: str = ""
    notes: str = ""


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


def _find_first_empty_row(sheet: gspread.Worksheet) -> int:
    """Find the first row where Company, Title, and Job Posting Link are all empty.
    
    Returns the 1-indexed row number. Skips header row (row 1).
    """
    all_values = sheet.get_all_values()
    
    for idx, row in enumerate(all_values[1:], start=2):  # Skip header, 1-indexed
        company, title, status, link, contact, date = row[:6] if len(row) >= 6 else ["", "", "", "", "", ""]
        if not company.strip() and not title.strip() and not link.strip():
            return idx
    
    # No empty row found — append at the end
    return len(all_values) + 1


def append_application(record: ApplicationRecord) -> None:
    """Write one row to the configured Google Sheet at the first empty row."""
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

        application_date = record.application_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        row = [
            record.company,
            record.job_title,
            record.status,
            record.url,
            "",
            application_date,
            "",
            "",
            record.notes,
        ]

        # Find first empty row and insert there
        target_row = _find_first_empty_row(sheet)
        sheet.insert_row(row, target_row)
        logger.info("Wrote application to sheet at row %d: %s at %s", target_row, record.job_title, record.url)

    except Exception:
        logger.exception("Failed to write to Google Sheet")
        raise
