from __future__ import annotations

from typing import Any, Callable

from contracts.product import ProductManifest, ProductRef
from interfaces.product_sink import RasterProduct, TableProduct
from service.platform_scheduler_adapter import _resolve_required_callable
from service.platform_templates import PlatformProductSinkTemplate


PersistRasterFn = Callable[[RasterProduct], ProductRef]
PersistTableFn = Callable[[TableProduct], ProductRef]
PersistManifestFn = Callable[[ProductManifest], str]


class PlatformProductSink(PlatformProductSinkTemplate):
    def __init__(
        self,
        *,
        platform_client: Any = None,
        persist_raster_fn: PersistRasterFn | None = None,
        persist_table_fn: PersistTableFn | None = None,
        persist_manifest_fn: PersistManifestFn | None = None,
    ) -> None:
        super().__init__(platform_client=platform_client)
        self._persist_raster_fn = persist_raster_fn or _resolve_required_callable(
            platform_client,
            "persist_raster",
            "persist_raster_fn",
        )
        self._persist_table_fn = persist_table_fn or _resolve_required_callable(
            platform_client,
            "persist_table",
            "persist_table_fn",
        )
        self._persist_manifest_fn = persist_manifest_fn or _resolve_required_callable(
            platform_client,
            "persist_manifest",
            "persist_manifest_fn",
        )

    def persist_raster(self, product: RasterProduct) -> ProductRef:
        return self._persist_raster_fn(product)

    def persist_table(self, product: TableProduct) -> ProductRef:
        return self._persist_table_fn(product)

    def persist_manifest(self, manifest: ProductManifest) -> str:
        return self._persist_manifest_fn(manifest)
