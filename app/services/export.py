"""Research export helpers, including a formatted Excel workbook."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

HEADER_FILL = PatternFill("solid", fgColor="115E59")
HEADER_FONT = Font(bold=True, color="FFFFFF")
LABEL_FONT = Font(bold=True, color="0F766E")
WRAP = Alignment(wrap_text=True, vertical="top")
THIN = Border(
    left=Side(style="thin", color="D1D5DB"),
    right=Side(style="thin", color="D1D5DB"),
    top=Side(style="thin", color="D1D5DB"),
    bottom=Side(style="thin", color="D1D5DB"),
)


def _published(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        published = value
    else:
        try:
            published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return str(value)
    if published.tzinfo is not None:
        published = published.replace(tzinfo=None)
    return published.strftime("%Y-%m-%d %H:%M")


def export_rows(results: list[dict]) -> list[dict]:
    rows = []
    for item in results:
        rows.append(
            {
                "Title": item.get("title") or "",
                "Source": item.get("source") or "",
                "Link": item.get("url") or "",
                "Date of Publish": _published(item.get("published_date")),
                "Author": item.get("author") or "",
                "Official": "Yes" if item.get("is_official") else "No",
                "Type": "Social mention" if item.get("is_social_mention") else (item.get("content_type") or "article"),
                "Excerpt": item.get("excerpt") or item.get("description") or "",
                "Full text": item.get("content") or "",
            }
        )
    return rows


def _style_header(sheet: Worksheet, columns: int) -> None:
    for col in range(1, columns + 1):
        cell = sheet.cell(1, col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = THIN
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.row_dimensions[1].height = 22


def _write_table(sheet: Worksheet, headers: list[str], rows: list[list[Any]], widths: list[int]) -> None:
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    _style_header(sheet, len(headers))
    for r_idx in range(2, sheet.max_row + 1):
        sheet.row_dimensions[r_idx].height = 48
        for c_idx in range(1, len(headers) + 1):
            cell = sheet.cell(r_idx, c_idx)
            cell.alignment = WRAP
            cell.border = THIN
            header = headers[c_idx - 1]
            value = cell.value
            if header in {"URL", "Link"} and value:
                cell.hyperlink = str(value)
                cell.font = Font(color="0F766E", underline="single")
    for idx, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(idx)].width = width


def build_excel_workbook(payload: dict[str, Any]) -> bytes:
    results = list(payload.get("results") or [])
    topic = payload.get("topic") or ""
    tab = (payload.get("tab") or payload.get("content_type") or "websites").lower()
    if tab in {"news", "website", "web"}:
        tab_label = "Websites"
    elif tab == "social":
        tab_label = "Social"
    else:
        tab_label = "Social" if all(item.get("is_social_mention") for item in results) else "Websites"

    articles = [item for item in results if not item.get("is_social_mention")]
    social = [item for item in results if item.get("is_social_mention")]
    official_count = sum(1 for item in results if item.get("is_official"))

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary["A1"] = "Research Data Fetcher"
    summary["A1"].font = Font(bold=True, size=16, color="115E59")
    summary.merge_cells("A1:B1")
    facts = [
        ("Topic", topic),
        ("Tab", tab_label),
        ("Exported", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Total results", len(results)),
        ("Articles", len(articles)),
        ("Social mentions", len(social)),
        ("Official sources", official_count),
    ]
    summary.append([])
    for label, value in facts:
        summary.append([label, value])
        summary.cell(summary.max_row, 1).font = LABEL_FONT
    summary.column_dimensions["A"].width = 22
    summary.column_dimensions["B"].width = 80
    summary.row_dimensions[1].height = 24

    if articles or tab_label == "Websites":
        sheet = wb.create_sheet("Articles")
        rows = [
            [
                item.get("title") or "",
                "Yes" if item.get("is_official") else "No",
                item.get("source") or "",
                item.get("author") or "",
                _published(item.get("published_date")),
                item.get("url") or "",
                item.get("excerpt") or item.get("description") or "",
                item.get("content") or "",
                item.get("content_type") or "article",
            ]
            for item in articles
        ]
        _write_table(
            sheet,
            ["Title", "Official", "Source", "Author", "Published", "URL", "Excerpt", "Full text", "Type"],
            rows,
            [36, 12, 14, 18, 18, 42, 80, 100, 14],
        )

    if social or tab_label == "Social":
        sheet = wb.create_sheet("Social mentions")
        rows = [
            [
                item.get("source") or "",
                item.get("title") or "",
                item.get("url") or "",
                item.get("excerpt") or item.get("description") or item.get("content") or "",
                _published(item.get("published_date")),
            ]
            for item in social
        ]
        _write_table(
            sheet,
            ["Platform", "Title", "URL", "Snippet", "Date"],
            rows,
            [16, 40, 42, 90, 18],
        )

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def excel_filename(payload: dict[str, Any], stamp: str) -> str:
    tab = (payload.get("tab") or payload.get("content_type") or "websites").lower()
    if tab == "social":
        label = "social"
    else:
        label = "websites"
    return f"research_{label}_{stamp}.xlsx"
