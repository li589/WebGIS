from __future__ import annotations

import json

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class JsonFormatAdapter(LocalFileFormatAdapter):
    name = "json"
    supported_formats = ("json",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        with local_path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        return {
            "path": str(local_path),
            "document": document,
        }
