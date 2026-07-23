from __future__ import annotations

from data_access.contracts import ResourceRef, normalize_format
from data_access.format_adapters.base import FormatAdapter
from data_access.format_adapters.csv_file import CsvFormatAdapter
from data_access.format_adapters.excel_file import ExcelFormatAdapter
from data_access.format_adapters.hdf_file import HdfFormatAdapter
from data_access.format_adapters.json_file import JsonFormatAdapter
from data_access.format_adapters.mat_file import MatFormatAdapter
from data_access.format_adapters.netcdf_file import NetcdfFormatAdapter
from data_access.format_adapters.shp_file import ShapefileFormatAdapter
from data_access.format_adapters.text import TextFormatAdapter
from data_access.format_adapters.tiff_file import TiffFormatAdapter
from data_access.format_adapters.xml_file import XmlFormatAdapter


class FormatRegistry:
    def __init__(
        self, adapters: tuple[FormatAdapter, ...] | list[FormatAdapter] = ()
    ) -> None:
        self._adapters = tuple(adapters)

    def register(self, adapter: FormatAdapter) -> "FormatRegistry":
        return FormatRegistry((*self._adapters, adapter))

    def registered_names(self) -> tuple[str, ...]:
        return tuple(adapter.name for adapter in self._adapters)

    def registered_formats(self) -> tuple[str, ...]:
        formats: set[str] = set()
        for adapter in self._adapters:
            formats.update(
                normalize_format(value) for value in adapter.supported_formats
            )
        return tuple(sorted(value for value in formats if value is not None))

    def find_for_resource(self, resource: ResourceRef) -> FormatAdapter:
        for adapter in self._adapters:
            if adapter.can_handle(resource):
                return adapter
        raise LookupError(f"No format adapter registered for resource '{resource.uri}'")

    def load(self, resource: ResourceRef):
        return self.find_for_resource(resource).load(resource)

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: str | None = None,
    ) -> ResourceRef:
        return self.find_for_resource(resource).materialize(
            resource, target_dir=target_dir
        )

    def probe(self, resource: ResourceRef) -> bool:
        try:
            adapter = self.find_for_resource(resource)
        except LookupError:
            return False
        return adapter.probe(resource)


def build_default_format_registry() -> FormatRegistry:
    return FormatRegistry(
        (
            CsvFormatAdapter(),
            ExcelFormatAdapter(),
            HdfFormatAdapter(),
            JsonFormatAdapter(),
            MatFormatAdapter(),
            NetcdfFormatAdapter(),
            ShapefileFormatAdapter(),
            TextFormatAdapter(),
            TiffFormatAdapter(),
            XmlFormatAdapter(),
        )
    )
