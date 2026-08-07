"""Python provider result builder: post-submit result ref construction.

Extracted from the original ``python_provider_bridge_service.py`` god class.
Owns all "after ``service.submit_job()`` returns" concerns:

- :meth:`build_result_refs` assembles the canonical json result_ref
  (always emitted), the text summary ref (when ``ResultKind.text`` is
  requested), and artifact refs for manifest / metadata / log artifacts.
- :meth:`_build_artifact_ref` resolves artifact URIs to local files
  (spilling to object storage via ``result_storage_service`` when the
  file exists locally) or returns external URL-backed refs.
- :meth:`_uri_to_local_path` converts ``file://`` / bare-path URIs to
  :class:`Path` instances, with Windows drive-letter normalization.
- When ``map_layer`` is requested, science ``.mat`` products are committed
  as imported overlays so the frontend can paint them immediately.

The bridge service calls :meth:`build_result_refs` after a successful
``submit_job``; this module is unaware of validation, dispatch, or
diagnostics — those live in :mod:`python_provider_request_builder` and
the bridge service itself.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from app.core.config import settings
from app.services.result_storage import result_storage_service
from shared.contracts.api_contracts import (
    ResultKind,
    WeatherLayerRenderHint,
    WorkflowResultReference,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)

# Product type → GeoTIFF extract config for map_layer publishing.
_MAPPABLE_PRODUCTS: dict[str, dict[str, Any]] = {
    "omega_sf_omega_pixel": {
        "variable": "omega_pix_map",
        "grid_preset": "ease2-global-9km",
        "label": "OMEGA",
        "palette": "cividis",
    },
    "omega_sf_sm_block_dir": {
        "variable": "SM",
        "grid_preset": "ease2-global-9km",
        "label": "SM",
        "palette": "ylgnbu",
        "from_block_dir": True,
    },
    "omega_sf_vod_block_dir": {
        "variable": "VOD",
        "grid_preset": "ease2-global-9km",
        "label": "VOD",
        "palette": "viridis",
        "from_block_dir": True,
    },
    "omega_sf_omega_block_dir": {
        "variable": "OMEGA",
        "grid_preset": "ease2-global-9km",
        "label": "OMEGA",
        "palette": "cividis",
        "from_block_dir": True,
    },
}

_BLOCK_MAT_RE = re.compile(r"^\d{8}_\d{8}\.mat$", re.IGNORECASE)

# MIME types for the three standard algorithm artifact kinds. Indexed by
# the artifact_name key used in result_dto.artifacts.
_ARTIFACT_MIME_TYPES: dict[str, str] = {
    "manifest": "application/json",
    "metadata": "application/json",
    "log": "text/plain",
}


def as_dict(value: Any) -> dict[str, Any]:
    """Coerce arbitrary input to ``dict``; return ``{}`` on non-dict input.

    Module-level utility shared by the bridge service (for parsing
    ``job_result`` / ``result_dto`` from the provider response) and the
    result builder (for parsing ``artifacts`` / ``manifest_summary``).
    """
    if isinstance(value, dict):
        return dict(value)
    return {}


class PythonProviderResultBuilder:
    """Builds workflow result_refs from a Python provider job result."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_result_refs(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        request_payload: dict[str, Any],
        job_result: dict[str, Any],
        result_dto: dict[str, Any],
    ) -> list[WorkflowResultReference]:
        """Assemble result_refs for the json / text / artifact kinds.

        Always emits a json result_ref (the canonical algorithm result
        carrying ``algorithm_request`` + ``job_result`` + ``result_dto``).
        Text and artifact refs are emitted based on
        ``payload.requested_outputs`` and ``result_dto.artifacts``.
        """
        requested_output_kinds = {
            item.value if isinstance(item, ResultKind) else str(item)
            for item in payload.requested_outputs
        }

        result_refs: list[WorkflowResultReference] = [
            WorkflowResultReference(
                result_id=f"algorithm-result-{run_id[-8:]}",
                result_kind=ResultKind.json,
                title="Algorithm Task Result",
                mime_type="application/json",
                inline_data={
                    "workflow": {
                        "run_id": run_id,
                        "command_type": payload.command_type.value,
                        "layer_id": payload.layer_id,
                    },
                    "algorithm_request": request_payload,
                    "job_result": job_result,
                    "result_dto": result_dto,
                },
                updated_at=requested_at,
            )
        ]

        if ResultKind.text.value in requested_output_kinds:
            summary = self._build_text_summary(
                request_payload=request_payload,
                job_result=job_result,
                result_dto=result_dto,
            )
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"algorithm-summary-{run_id[-8:]}",
                    result_kind=ResultKind.text,
                    title="Algorithm Task Summary",
                    mime_type="text/plain",
                    inline_data={"text": summary},
                    updated_at=requested_at,
                )
            )

        result_refs.extend(
            self._build_artifact_refs(
                run_id=run_id,
                requested_at=requested_at,
                result_dto=result_dto,
            )
        )

        # Multi-output support: create individual file-kind result_refs for
        # each product in result_dto.products (e.g. SM / VOD / OMEGA).
        result_refs.extend(
            self._build_product_refs(
                run_id=run_id,
                requested_at=requested_at,
                result_dto=result_dto,
            )
        )

        # When map_layer is requested, convert science products to imported
        # overlays and emit map_layer refs the frontend can paint.
        if ResultKind.map_layer.value in requested_output_kinds:
            time_start: str | None = None
            time_end: str | None = None
            tr = getattr(payload, "time_range", None)
            if tr is not None:
                start_at = getattr(tr, "start_at", None)
                end_at = getattr(tr, "end_at", None)
                if start_at is not None:
                    time_start = str(start_at).replace("-", "")[:8]
                if end_at is not None:
                    time_end = str(end_at).replace("-", "")[:8]
            result_refs.extend(
                self._build_product_map_layer_refs(
                    run_id=run_id,
                    requested_at=requested_at,
                    payload=payload,
                    result_dto=result_dto,
                    time_start=time_start,
                    time_end=time_end,
                )
            )

        return result_refs

    # ------------------------------------------------------------------
    # Text summary
    # ------------------------------------------------------------------

    def _build_text_summary(
        self,
        *,
        request_payload: dict[str, Any],
        job_result: dict[str, Any],
        result_dto: dict[str, Any],
    ) -> str:
        """Build a one-line human-readable summary of the algorithm result."""
        entry_name = (
            request_payload.get("workflow_name")
            or request_payload.get("module_name")
            or "workflow_definition"
        )
        manifest_summary = as_dict(result_dto.get("manifest_summary"))
        return (
            f"算法任务 {entry_name} 已执行完成，"
            f"job_status={job_result.get('status')}，"
            f"manifest_loaded={bool(result_dto.get('manifest_loaded'))}，"
            f"products={manifest_summary.get('product_count', 0)}。"
        )

    # ------------------------------------------------------------------
    # Artifact refs (manifest / metadata / log)
    # ------------------------------------------------------------------

    def _build_artifact_refs(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        result_dto: dict[str, Any],
    ) -> list[WorkflowResultReference]:
        """Iterate the three standard artifact kinds and build refs for each.

        Skips artifact kinds that are absent from ``result_dto.artifacts``
        or whose URIs resolve to nothing.
        """
        artifacts = as_dict(result_dto.get("artifacts"))
        artifact_refs: list[WorkflowResultReference] = []
        for artifact_name in ("manifest", "metadata", "log"):
            artifact_view = as_dict(artifacts.get(artifact_name))
            if not artifact_view:
                continue
            artifact_ref = self._build_artifact_ref(
                run_id=run_id,
                requested_at=requested_at,
                artifact_name=artifact_name,
                artifact_view=artifact_view,
            )
            if artifact_ref is not None:
                artifact_refs.append(artifact_ref)
        return artifact_refs

    # ------------------------------------------------------------------
    # Product refs (multi-output: SM / VOD / OMEGA)
    # ------------------------------------------------------------------

    def _build_product_refs(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        result_dto: dict[str, Any],
    ) -> list[WorkflowResultReference]:
        """Build individual file-kind result_refs for each product output.

        Iterates ``result_dto.products`` (populated from the algorithm
        manifest) and creates a separate ref for each product with a
        resolvable URI. This enables the frontend to link directly to
        individual output layers (e.g. SM, VOD, OMEGA) rather than only
        the aggregate json result.
        """
        products = result_dto.get("products")
        if not isinstance(products, list):
            return []
        product_refs: list[WorkflowResultReference] = []
        for idx, product in enumerate(products):
            if not isinstance(product, dict):
                continue
            ref = self._build_product_ref(
                run_id=run_id,
                requested_at=requested_at,
                product=product,
                index=idx,
            )
            if ref is not None:
                product_refs.append(ref)
        return product_refs

    def _build_product_ref(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        product: dict[str, Any],
        index: int,
    ) -> WorkflowResultReference | None:
        """Build a single product result_ref.

        Resolution order for the product URI:
        1. ``download_url``
        2. ``preview_url``
        3. ``uri``

        If the URI resolves to a local file that exists, the file is
        spilled to object storage via ``result_storage_service``. Otherwise
        an external URL-backed ref is returned.
        """
        uri = str(
            product.get("download_url")
            or product.get("preview_url")
            or product.get("uri")
            or ""
        ).strip()
        if not uri:
            return None

        product_type = str(product.get("type") or "raster")
        variable = str(product.get("variable") or "")
        tags = as_dict(product.get("tags"))
        layer_label = str(tags.get("layer") or variable or product_type)
        kind_tag = str(tags.get("kind") or "").lower()

        # Chart / table analysis products → structured result_refs for InfoPanel
        if (
            product_type in {"chart_spec", "table_spec"}
            or kind_tag in {"chart", "table"}
            or uri.lower().endswith((".chart.json", ".table.json"))
        ):
            analysis_ref = self._build_analysis_spec_ref(
                run_id=run_id,
                requested_at=requested_at,
                product=product,
                index=index,
                uri=uri,
                product_type=product_type,
                kind_tag=kind_tag,
                layer_label=layer_label,
            )
            if analysis_ref is not None:
                return analysis_ref

        # Title must be US-ASCII (Celery metadata constraint)
        title = f"Algorithm Output: {layer_label}"
        mime_type = self._infer_product_mime_type(uri, product_type)

        local_path = self._uri_to_local_path(uri)
        if local_path is not None and local_path.exists() and local_path.is_file():
            payload = local_path.read_bytes()
            return result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"algorithm-product-{index}-{run_id[-8:]}",
                result_kind=ResultKind.file,
                title=title,
                mime_type=mime_type,
                updated_at=requested_at,
                payload=payload,
            )

        # External URL-backed ref
        resource_backend = str(product.get("storage_backend") or "external")
        resource_key = str(product.get("object_key") or uri)
        return WorkflowResultReference(
            result_id=f"algorithm-product-{index}-{run_id[-8:]}",
            result_kind=ResultKind.file,
            title=title,
            mime_type=mime_type,
            resource_url=uri,
            resource_backend=resource_backend,
            resource_key=resource_key,
            updated_at=requested_at,
        )

    def _build_analysis_spec_ref(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        product: dict[str, Any],
        index: int,
        uri: str,
        product_type: str,
        kind_tag: str,
        layer_label: str,
    ) -> WorkflowResultReference | None:
        """Emit ResultKind.chart / table from chart_spec / table_spec JSON products."""
        is_table = (
            product_type == "table_spec"
            or kind_tag == "table"
            or uri.lower().endswith(".table.json")
        )
        result_kind = ResultKind.table if is_table else ResultKind.chart
        title = (
            f"Analysis Table: {layer_label}"
            if is_table
            else f"Analysis Chart: {layer_label}"
        )
        # Strip non-ASCII for Celery safety
        title = title.encode("ascii", "ignore").decode("ascii") or (
            "Analysis Table" if is_table else "Analysis Chart"
        )

        local_path = self._uri_to_local_path(uri)
        payload: dict[str, Any] | None = None
        if local_path is not None and local_path.exists() and local_path.is_file():
            try:
                raw = json.loads(local_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    payload = raw
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load analysis JSON %s: %s", uri, exc)

        if payload is None:
            # Fall back to file artifact if JSON cannot be inlined
            return None

        # Oversized series: spill via chunked reference (chart only)
        series = (
            payload.get("series") if isinstance(payload.get("series"), list) else []
        )
        flat_y = payload.get("y") if isinstance(payload.get("y"), list) else []
        point_count = 0
        if series:
            for s in series:
                if isinstance(s, dict) and isinstance(s.get("y"), list):
                    point_count = max(point_count, len(s["y"]))
        else:
            point_count = len(flat_y)

        chunk_limit = int(getattr(settings, "provider_series_chunk_size", 500) or 500)
        if result_kind is ResultKind.chart and point_count > chunk_limit:
            items = []
            if series and isinstance(series[0], dict):
                xs = list(series[0].get("x") or [])
                ys = list(series[0].get("y") or [])
                for i, y in enumerate(ys):
                    items.append({"label": xs[i] if i < len(xs) else i, "value": y})
            else:
                xs = list(payload.get("x") or [])
                for i, y in enumerate(flat_y):
                    items.append({"label": xs[i] if i < len(xs) else i, "value": y})
            chunked_ref, _diag = result_storage_service.build_chunked_reference(
                run_id=run_id,
                result_kind=ResultKind.chart,
                title=title,
                mime_type="application/json",
                updated_at=requested_at,
                items=iter(items),
                chunk_size=chunk_limit,
                manifest_payload={
                    "chart_type": payload.get("chart_type") or "line",
                    "series_name": payload.get("series_name") or layer_label,
                    "point_count": point_count,
                    "schema_version": payload.get("schema_version") or "1",
                },
            )
            return chunked_ref

        return WorkflowResultReference(
            result_id=f"analysis-{result_kind.value}-{index}-{uuid4().hex[:8]}",
            result_kind=result_kind,
            title=title,
            mime_type="application/json",
            inline_data=payload,
            updated_at=requested_at,
        )

    @staticmethod
    def _infer_product_mime_type(uri: str, product_type: str) -> str:
        """Infer MIME type from URI extension or product type."""
        lower_uri = uri.lower()
        if lower_uri.endswith((".tif", ".tiff")):
            return "image/tiff"
        if lower_uri.endswith(".nc"):
            return "application/x-netcdf"
        if lower_uri.endswith((".h5", ".hdf5")):
            return "application/x-hdf5"
        if lower_uri.endswith((".hdf", ".he5")):
            return "application/x-hdf"
        if lower_uri.endswith(".mat"):
            return "application/x-matlab-data"
        if lower_uri.endswith(".json"):
            return "application/json"
        if lower_uri.endswith(".csv"):
            return "text/csv"
        if lower_uri.endswith(".png"):
            return "image/png"
        if "raster" in product_type.lower() or "omega" in product_type.lower():
            return "image/tiff"
        return "application/octet-stream"

    def _build_artifact_ref(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        artifact_name: str,
        artifact_view: dict[str, Any],
    ) -> WorkflowResultReference | None:
        """Build a single artifact ref, preferring local-file spill when available.

        Resolution order for the artifact URI:
        1. ``download_url``
        2. ``preview_url``
        3. ``uri``

        If the URI resolves to a local file that exists, the file is
        spilled to object storage via ``result_storage_service`` and a
        file-kind ref is returned. Otherwise, an external URL-backed ref
        is returned carrying ``resource_url`` / ``resource_backend`` /
        ``resource_key``.
        """
        title = f"Algorithm {artifact_name}"
        uri = str(
            artifact_view.get("download_url")
            or artifact_view.get("preview_url")
            or artifact_view.get("uri")
            or ""
        ).strip()
        if not uri:
            return None

        local_path = self._uri_to_local_path(uri)
        if local_path is not None and local_path.exists() and local_path.is_file():
            payload = local_path.read_bytes()
            return result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"algorithm-{artifact_name}-{local_path.stem}",
                result_kind=ResultKind.file,
                title=title,
                mime_type=_ARTIFACT_MIME_TYPES[artifact_name],
                updated_at=requested_at,
                payload=payload,
            )

        parsed = urlparse(uri)
        resource_backend = str(
            artifact_view.get("storage_backend") or parsed.scheme or "external"
        )
        resource_key = str(artifact_view.get("object_key") or parsed.path or uri)
        if resource_backend == "file" and not resource_key.startswith("/"):
            resource_key = f"/{resource_key.lstrip('/')}"
        return WorkflowResultReference(
            result_id=f"algorithm-{artifact_name}-{run_id[-8:]}",
            result_kind=ResultKind.file,
            title=title,
            mime_type=_ARTIFACT_MIME_TYPES[artifact_name],
            resource_url=uri,
            resource_backend=resource_backend,
            resource_key=resource_key,
            updated_at=requested_at,
        )

    # ------------------------------------------------------------------
    # Map layer publishing (science products → imported overlays)
    # ------------------------------------------------------------------

    def _build_product_map_layer_refs(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        payload: WorkflowSubmitRequest,
        result_dto: dict[str, Any],
        time_start: str | None = None,
        time_end: str | None = None,
        canonical_viirs8_only: bool = False,
    ) -> list[WorkflowResultReference]:
        """Commit mappable products as overlays and emit map_layer refs."""
        products = result_dto.get("products")
        if not isinstance(products, list):
            return []

        refs: list[WorkflowResultReference] = []
        has_omega_block_series = any(
            isinstance(product, dict)
            and product.get("type") == "omega_sf_omega_block_dir"
            for product in products
        )
        for idx, product in enumerate(products):
            if not isinstance(product, dict):
                continue
            # SF workflow 的 omega_pixel 是静态诊断产物；存在块级 OMEGA
            # 时间序列时不可再发布一次同标签地图层，否则一个 run 会变成四层。
            if has_omega_block_series and product.get("type") == "omega_sf_omega_pixel":
                continue
            ref = self._build_product_map_layer_ref(
                run_id=run_id,
                requested_at=requested_at,
                payload=payload,
                product=product,
                index=idx,
                time_start=time_start,
                time_end=time_end,
                canonical_viirs8_only=canonical_viirs8_only,
            )
            if ref is not None:
                refs.append(ref)
        return refs

    def _build_product_map_layer_ref(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        payload: WorkflowSubmitRequest,
        product: dict[str, Any],
        index: int,
        time_start: str | None = None,
        time_end: str | None = None,
        canonical_viirs8_only: bool = False,
    ) -> WorkflowResultReference | None:
        product_type = str(product.get("type") or "")
        config = _MAPPABLE_PRODUCTS.get(product_type)
        if config is None:
            return None

        uri = str(
            product.get("download_url")
            or product.get("preview_url")
            or product.get("uri")
            or ""
        ).strip()
        local_path = self._uri_to_local_path(uri) if uri else None
        if local_path is None:
            return None

        source_path = local_path
        if config.get("from_block_dir"):
            if not local_path.is_dir():
                return None
            try:
                from app.data_io.services.raster_timeseries import (
                    upsert_block_dir_timeseries,
                )

                registered_ts = upsert_block_dir_timeseries(
                    local_path,
                    variable_id=str(product.get("variable") or config["variable"]),
                    label=str(config["label"]),
                    run_id=run_id,
                    grid_preset=str(config["grid_preset"]),
                    palette=str(config.get("palette") or "cividis"),
                    native_step="8d",
                    time_start=time_start,
                    time_end=time_end,
                    canonical_viirs8_only=canonical_viirs8_only,
                )
            except Exception:
                logger.exception(
                    "Failed to publish TS map_layer for product type=%s path=%s",
                    product_type,
                    local_path,
                )
                return None

            overlay_id = str(registered_ts.get("layer_id") or "").strip()
            if not overlay_id:
                return None
            bounds = registered_ts.get("bounds")
            cog_bbox = None
            if (
                isinstance(bounds, (list, tuple))
                and len(bounds) == 4
                and all(isinstance(v, (int, float)) for v in bounds)
            ):
                cog_bbox = {
                    "west": float(bounds[0]),
                    "south": float(bounds[1]),
                    "east": float(bounds[2]),
                    "north": float(bounds[3]),
                    "crs": "EPSG:4326",
                }
            label = str(config["label"])
            tags = as_dict(product.get("tags"))
            layer_tag = str(tags.get("layer") or label)
            render_hint = WeatherLayerRenderHint(
                layer_id=payload.layer_id or overlay_id,
                paint_mode="grid_fill",
                palette=str(config.get("palette") or "cividis"),
                primary_metric=str(product.get("variable") or config["variable"]),
                unit_label=layer_tag,
                opacity=0.8,
                notes=[
                    f"product={product_type}",
                    f"overlay={overlay_id}",
                    "native_step=8d",
                ],
            )
            return WorkflowResultReference(
                result_id=f"algorithm-map-{index}-{run_id[-8:]}",
                result_kind=ResultKind.map_layer,
                title=f"Algorithm Map Layer: {layer_tag}",
                mime_type="application/json",
                inline_data={
                    "render_hint": render_hint.model_dump(mode="json"),
                    "layer_assets": {
                        "overlay_layer_id": overlay_id,
                        # FE may append ?palette=&min_value=&max_value=&nodata_mode=
                        "cog_url": f"/overlay-preview/{overlay_id}",
                        "cog_preview_url": f"/overlay-preview/{overlay_id}",
                        "cog_bbox": cog_bbox,
                        "product_tag": layer_tag,
                        "source_path": str(local_path),
                        "time_list": registered_ts.get("time_list") or [],
                        "default_time": registered_ts.get("default_time"),
                        "native_step": registered_ts.get("native_step") or "8d",
                    },
                },
                updated_at=requested_at,
            )
        elif not local_path.is_file():
            return None

        variable = str(product.get("variable") or config["variable"])
        # omega_pixel ProductRef historically used variable=OMEGA; force the
        # actual MAT key so extract does not KeyError.
        if product_type == "omega_sf_omega_pixel":
            variable = "omega_pix_map"

        try:
            from app.data_io.services.raster_commit import (
                commit_science_raster_variable,
            )

            registered = commit_science_raster_variable(
                source_path,
                variable_id=variable,
                source_name=f"{run_id}_{config['label']}",
                upload_id=f"wf-{run_id[-8:]}-{index}",
                grid_preset=str(config["grid_preset"]),
                auto_confirm=True,
            )
        except Exception:
            logger.exception(
                "Failed to publish map_layer for product type=%s path=%s",
                product_type,
                source_path,
            )
            return None

        overlay_id = str(registered.get("layer_id") or "").strip()
        if not overlay_id:
            return None

        bounds = registered.get("bounds")
        cog_bbox = None
        if (
            isinstance(bounds, (list, tuple))
            and len(bounds) == 4
            and all(isinstance(v, (int, float)) for v in bounds)
        ):
            cog_bbox = {
                "west": float(bounds[0]),
                "south": float(bounds[1]),
                "east": float(bounds[2]),
                "north": float(bounds[3]),
                "crs": "EPSG:4326",
            }

        label = str(config["label"])
        tags = as_dict(product.get("tags"))
        layer_tag = str(tags.get("layer") or label)
        render_hint = WeatherLayerRenderHint(
            layer_id=payload.layer_id or overlay_id,
            paint_mode="grid_fill",
            palette=str(config.get("palette") or "cividis"),
            primary_metric=variable,
            unit_label=layer_tag,
            opacity=0.8,
            notes=[f"product={product_type}", f"overlay={overlay_id}"],
        )

        return WorkflowResultReference(
            result_id=f"algorithm-map-{index}-{run_id[-8:]}",
            result_kind=ResultKind.map_layer,
            title=f"Algorithm Map Layer: {layer_tag}",
            mime_type="application/json",
            inline_data={
                "render_hint": render_hint.model_dump(mode="json"),
                "layer_assets": {
                    "overlay_layer_id": overlay_id,
                    # FE may append ?palette=&min_value=&max_value=&nodata_mode=
                    "cog_url": f"/overlay-preview/{overlay_id}",
                    "cog_preview_url": f"/overlay-preview/{overlay_id}",
                    "cog_bbox": cog_bbox,
                    "product_tag": layer_tag,
                    "source_path": str(source_path),
                },
            },
            updated_at=requested_at,
        )

    @staticmethod
    def _latest_block_mat(directory: Path) -> Path | None:
        """Pick the newest YYYYMMDD_YYYYMMDD.mat under a block output dir."""
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and _BLOCK_MAT_RE.match(path.name)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda p: p.name)[-1]

    # ------------------------------------------------------------------
    # URI → local path resolution
    # ------------------------------------------------------------------

    def _uri_to_local_path(self, uri: str) -> Path | None:
        """Convert a ``file://`` or bare-path URI to a :class:`Path`.

        Returns ``None`` for non-file schemes (http, https, s3, etc.).
        Handles Windows drive-letter quirk where ``file:///C:/path``
        parses to ``/C:/path`` (leading slash stripped), and where a bare
        ``D:/path`` is mis-parsed by ``urlparse`` as scheme ``D``.
        """
        raw = (uri or "").strip()
        if not raw:
            return None
        # Windows absolute path: "D:\\..." or "D:/..." — urlparse treats
        # the drive letter as a scheme; detect before urlparse.
        if len(raw) >= 3 and raw[1] == ":" and raw[0].isalpha():
            return Path(raw)
        parsed = urlparse(raw)
        if parsed.scheme not in {"", "file"}:
            return None
        if parsed.scheme == "file":
            raw_path = unquote(f"{parsed.netloc}{parsed.path}")
        else:
            raw_path = unquote(raw)
        if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        if not raw_path:
            return None
        return Path(raw_path)


# Module-level singleton: result builder is stateless apart from the
# result_storage_service singleton, so a single shared instance mirrors
# the original bridge service behaviour.
python_provider_result_builder = PythonProviderResultBuilder()
