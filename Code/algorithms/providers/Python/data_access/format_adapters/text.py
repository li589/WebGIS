from __future__ import annotations

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class TextFormatAdapter(LocalFileFormatAdapter):
    name = "text"
    supported_formats = ("txt",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        text = local_path.read_text(encoding="utf-8")
        return {
            "path": str(local_path),
            "text": text,
            "lines": tuple(text.splitlines()),
        }
