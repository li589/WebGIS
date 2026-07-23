from __future__ import annotations

from typing import Any, Callable

from contracts.data import DataBundle, DataRequest
from interfaces.datasource import DataAsset
from service.platform_scheduler_adapter import (
    _resolve_optional_callable,
    _resolve_required_callable,
)
from service.platform_templates import PlatformDataSourceAdapterTemplate


DiscoverAssetsFn = Callable[[DataRequest], list[DataAsset]]
ResolveBundleFn = Callable[[DataRequest], DataBundle]
AcquireBundleFn = Callable[[DataBundle], DataBundle]
MaterializeBundleFn = Callable[[DataBundle], DataBundle]


class PlatformDataSourceAdapter(PlatformDataSourceAdapterTemplate):
    def __init__(
        self,
        *,
        platform_client: Any = None,
        discover_assets_fn: DiscoverAssetsFn | None = None,
        resolve_bundle_fn: ResolveBundleFn | None = None,
        acquire_bundle_fn: AcquireBundleFn | None = None,
        materialize_bundle_fn: MaterializeBundleFn | None = None,
    ) -> None:
        super().__init__(platform_client=platform_client)
        self._discover_assets_fn = discover_assets_fn or _resolve_optional_callable(
            platform_client,
            "discover_assets",
        )
        self._resolve_bundle_fn = resolve_bundle_fn or _resolve_required_callable(
            platform_client,
            "resolve_bundle",
            "resolve_bundle_fn",
        )
        self._acquire_bundle_fn = acquire_bundle_fn or _resolve_optional_callable(
            platform_client,
            "acquire_bundle",
        )
        self._materialize_bundle_fn = (
            materialize_bundle_fn
            or _resolve_optional_callable(
                platform_client,
                "materialize_bundle",
            )
        )

    def discover_assets(self, request: DataRequest) -> list[DataAsset]:
        if self._discover_assets_fn is None:
            return []
        return list(self._discover_assets_fn(request))

    def resolve_bundle(self, request: DataRequest) -> DataBundle:
        return self._resolve_bundle_fn(request)

    def acquire_bundle(self, bundle: DataBundle) -> DataBundle:
        if self._acquire_bundle_fn is None:
            return bundle
        return self._acquire_bundle_fn(bundle)

    def materialize_bundle(self, bundle: DataBundle) -> DataBundle:
        if self._materialize_bundle_fn is None:
            bundle.is_materialized = True
            return bundle
        return self._materialize_bundle_fn(bundle)
