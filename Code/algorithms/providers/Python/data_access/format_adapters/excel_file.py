from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter

_SPREADSHEET_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_CELL_REF_PATTERN = re.compile(r"([A-Z]+)")


class ExcelFormatAdapter(LocalFileFormatAdapter):
    name = "excel"
    supported_formats = ("excel",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        workbook = _load_xlsx_workbook(local_path)
        first_sheet = (
            workbook["worksheets"][0]
            if workbook["worksheets"]
            else {"headers": (), "rows": ()}
        )
        return {
            "path": str(local_path),
            "sheet_names": workbook["sheet_names"],
            "worksheets": workbook["worksheets"],
            "headers": first_sheet.get("headers", ()),
            "rows": first_sheet.get("rows", ()),
        }


def _load_xlsx_workbook(local_path: Path) -> dict[str, object]:
    with zipfile.ZipFile(local_path) as archive:
        shared_strings = _read_shared_strings(archive)
        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet_names = tuple(
            str(sheet.attrib.get("name", f"Sheet{index + 1}"))
            for index, sheet in enumerate(
                workbook_root.findall("s:sheets/s:sheet", _SPREADSHEET_NS)
            )
        )
        worksheets: list[dict[str, object]] = []
        for index, sheet_name in enumerate(sheet_names, start=1):
            worksheet_path = f"xl/worksheets/sheet{index}.xml"
            if worksheet_path not in archive.namelist():
                continue
            rows = _read_sheet_rows(archive.read(worksheet_path), shared_strings)
            headers = tuple(
                "" if value is None else str(value)
                for value in (rows[0] if rows else ())
            )
            row_dicts = tuple(
                {
                    headers[column_index]: "" if value is None else str(value)
                    for column_index, value in enumerate(row_values)
                    if column_index < len(headers) and headers[column_index]
                }
                for row_values in rows[1:]
            )
            worksheets.append(
                {
                    "name": sheet_name,
                    "headers": headers,
                    "rows": row_dicts,
                }
            )
        return {
            "sheet_names": sheet_names,
            "worksheets": tuple(worksheets),
        }


def _read_shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("s:si", _SPREADSHEET_NS):
        text_parts = [
            node.text or "" for node in item.findall(".//s:t", _SPREADSHEET_NS)
        ]
        values.append("".join(text_parts))
    return tuple(values)


def _read_sheet_rows(
    raw_xml: bytes, shared_strings: tuple[str, ...]
) -> tuple[tuple[str | None, ...], ...]:
    root = ET.fromstring(raw_xml)
    rows: list[tuple[str | None, ...]] = []
    for row in root.findall("s:sheetData/s:row", _SPREADSHEET_NS):
        values: list[str | None] = []
        current_column = 1
        for cell in row.findall("s:c", _SPREADSHEET_NS):
            cell_ref = cell.attrib.get("r", "")
            target_column = _column_index_from_ref(cell_ref)
            while current_column < target_column:
                values.append(None)
                current_column += 1
            values.append(_read_cell_value(cell, shared_strings))
            current_column += 1
        rows.append(tuple(values))
    return tuple(rows)


def _read_cell_value(cell: ET.Element, shared_strings: tuple[str, ...]) -> str | None:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text_parts = [
            node.text or "" for node in cell.findall(".//s:t", _SPREADSHEET_NS)
        ]
        return "".join(text_parts)
    value_node = cell.find("s:v", _SPREADSHEET_NS)
    if value_node is None or value_node.text is None:
        return None
    raw_value = value_node.text
    if cell_type == "s":
        index = int(raw_value)
        return shared_strings[index]
    return raw_value


def _column_index_from_ref(cell_ref: str) -> int:
    match = _CELL_REF_PATTERN.match(cell_ref)
    if match is None:
        return 1
    column_letters = match.group(1)
    value = 0
    for character in column_letters:
        value = (value * 26) + (ord(character) - ord("A") + 1)
    return value
