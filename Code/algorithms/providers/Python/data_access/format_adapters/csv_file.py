from __future__ import annotations

import csv

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class CsvFormatAdapter(LocalFileFormatAdapter):
    name = "csv"
    supported_formats = ("csv",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        with local_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = tuple(dict(row) for row in reader)
            headers = tuple(reader.fieldnames or ())
        return {
            "path": str(local_path),
            "headers": headers,
            "rows": rows,
        }
