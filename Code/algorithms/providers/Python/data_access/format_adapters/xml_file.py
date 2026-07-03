from __future__ import annotations

from typing import Any
import xml.etree.ElementTree as ET

from data_access.contracts import ResourceRef
from data_access.format_adapters.base import LocalFileFormatAdapter


class XmlFormatAdapter(LocalFileFormatAdapter):
    name = "xml"
    supported_formats = ("xml",)

    def load(self, resource: ResourceRef) -> dict[str, object]:
        local_path = self._require_local_path(resource)
        root = ET.parse(local_path).getroot()
        root_tag = _strip_namespace(root.tag)
        return {
            "path": str(local_path),
            "root_tag": root_tag,
            "document": {
                root_tag: _element_to_payload(root),
            },
        }


def _element_to_payload(element: ET.Element) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    attributes = {_strip_namespace(key): value for key, value in element.attrib.items()}
    if attributes:
        payload["attributes"] = attributes
    text = (element.text or "").strip()
    if text:
        payload["text"] = text
    children = list(element)
    if children:
        payload["children"] = [
            {
                _strip_namespace(child.tag): _element_to_payload(child),
            }
            for child in children
        ]
    return payload


def _strip_namespace(tag: str) -> str:
    return tag.split("}", 1)[-1]
