from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.weatherengine.constants import WEATHER_LAYER_SPECS
from shared.contracts.api_contracts import (
    LayerCapabilities,
    LayerCatalogResponse,
    LayerCategoryDef,
    LayerCategoryResponse,
    LayerDescriptor,
    LayerSourceType,
)

logger = logging.getLogger(__name__)

_SEEDS_DIR = Path(__file__).resolve().parent.parent / "catalog_seeds"
_cached_descriptors: list[LayerDescriptor] | None = None
_cached_categories: list[dict[str, Any]] | None = None
_cached_descriptors_mtime: float | None = None


def reload_catalog_seeds() -> None:
    """Clear in-memory catalog seed caches (for tests / hot reload)."""
    global _cached_descriptors, _cached_categories, _cached_descriptors_mtime
    _cached_descriptors = None
    _cached_categories = None
    _cached_descriptors_mtime = None


def _seed_files_mtime() -> float:
    """Max mtime of catalog seed JSON files; 0 if none exist."""
    stamp = 0.0
    for name in (
        "weather_descriptors.json",
        "layer_descriptors.json",
        "layer_categories.json",
    ):
        path = _SEEDS_DIR / name
        if path.exists():
            stamp = max(stamp, path.stat().st_mtime)
    return stamp


def merge_remote_data_access_candidates(
    sources: dict[str, list[str]],
    remote_by_dataset: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Prepend remote URIs ahead of local candidates (dedupe, preserve order)."""
    if not remote_by_dataset:
        return sources
    merged: dict[str, list[str]] = {k: list(v) for k, v in sources.items()}
    for dataset, uris in remote_by_dataset.items():
        extras = [str(u).strip() for u in uris if str(u).strip()]
        if not extras:
            continue
        existing = merged.get(dataset, [])
        seen = set(extras)
        merged[dataset] = extras + [c for c in existing if c not in seen]
    return merged


def _normalize_remote_layer_overlay(parsed: object) -> dict[str, dict[str, list[str]]]:
    """Normalize overlay JSON → {layer_id: {dataset: [uri...]}}."""
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, dict[str, list[str]]] = {}
    for layer_id, datasets in parsed.items():
        if not isinstance(datasets, dict):
            continue
        cleaned: dict[str, list[str]] = {}
        for dataset_name, uris in datasets.items():
            if isinstance(uris, str):
                uri_list = [uris]
            elif isinstance(uris, list):
                uri_list = [str(u) for u in uris if str(u).strip()]
            else:
                continue
            if uri_list:
                cleaned[str(dataset_name)] = uri_list
        if cleaned:
            result[str(layer_id)] = cleaned
    return result


def _load_db_remote_layer_data_uris() -> dict[str, dict[str, list[str]]]:
    """Load DB-persisted overlay (settings UI). Empty on any failure."""
    try:
        from app.services.config_service import _research_data_repo

        raw = _research_data_repo().get_json("remote_layer_data_uris", None)
        return _normalize_remote_layer_overlay(raw)
    except Exception as exc:  # noqa: BLE001
        logger.debug("research_data remote_layer_data_uris unavailable: %s", exc)
        return {}


def _parse_remote_layer_data_uris() -> dict[str, dict[str, list[str]]]:
    """Merge layer URI overlays: DB overrides env (plan: DB 优先于 env)."""
    env_overlay = _normalize_remote_layer_overlay({})
    raw = (settings.remote_layer_data_uris or "").strip()
    if raw:
        try:
            env_overlay = _normalize_remote_layer_overlay(json.loads(raw))
        except json.JSONDecodeError as exc:
            logger.warning("Invalid BACKEND_REMOTE_LAYER_DATA_URIS JSON: %s", exc)
            env_overlay = {}

    db_overlay = _load_db_remote_layer_data_uris()
    if not db_overlay:
        return env_overlay
    if not env_overlay:
        return db_overlay

    # Deep merge: DB layer/dataset wins; env fills gaps
    merged: dict[str, dict[str, list[str]]] = {
        k: dict(v) for k, v in env_overlay.items()
    }
    for layer_id, datasets in db_overlay.items():
        if layer_id not in merged:
            merged[layer_id] = dict(datasets)
            continue
        for dataset_name, uris in datasets.items():
            merged[layer_id][dataset_name] = list(uris)
    return merged


def _apply_remote_layer_data_uris(
    items: list[LayerDescriptor],
) -> list[LayerDescriptor]:
    """Inject SMB/SFTP URIs into matching layers (DB overlay preferred over env)."""
    overlay = _parse_remote_layer_data_uris()
    if not overlay:
        return items
    updated: list[LayerDescriptor] = []
    for item in items:
        remote_by_dataset = overlay.get(item.layer_id)
        if not remote_by_dataset:
            updated.append(item)
            continue
        sources = merge_remote_data_access_candidates(
            dict(item.default_data_access_sources or {}),
            remote_by_dataset,
        )
        notes = list(item.run_readiness_notes or [])
        note = (
            f"已注入远端数据源候选（remote_layer_data_uris / {item.layer_id}）："
            + ", ".join(f"{ds}×{len(uris)}" for ds, uris in remote_by_dataset.items())
        )
        if note not in notes:
            notes.insert(0, note)
        updated.append(
            item.model_copy(
                update={
                    "default_data_access_sources": sources,
                    "run_readiness_notes": notes,
                }
            )
        )
    return updated


def _layer_capabilities(
    *,
    render_strategy: str,
    data_domain: str,
    paint_mode: str | None = None,
    primary_metric: str | None = None,
    supports_particle_flow: bool = False,
    supports_map_layer: bool = True,
    supports_viewport_refresh: bool | None = None,
    viewport_refresh_mode: str | None = None,
    legend_ticks: list[float | int | str] | None = None,
    notes: list[str] | None = None,
    delivery_modes: list[str] | None = None,
    result_interfaces: list[str] | None = None,
) -> LayerCapabilities:
    if supports_viewport_refresh is None:
        supports_viewport_refresh = render_strategy in {
            "weather_tile",
            "workflow_map_layer",
        }
    if viewport_refresh_mode is None and supports_viewport_refresh:
        viewport_refresh_mode = (
            "tile" if render_strategy == "weather_tile" else "workflow"
        )
    if delivery_modes is None:
        delivery_modes = (
            ["tile_cache", "point_query"]
            if render_strategy == "weather_tile"
            else ["workflow_result"]
        )
    if result_interfaces is None:
        result_interfaces = (
            ["map_layer", "weather_point"]
            if render_strategy == "weather_tile"
            else ["json", "text", "table", "map_layer"]
        )
    return LayerCapabilities(
        render_strategy=render_strategy,
        paint_mode=paint_mode,
        data_domain=data_domain,
        primary_metric=primary_metric,
        supports_particle_flow=supports_particle_flow,
        supports_map_layer=supports_map_layer,
        supports_viewport_refresh=supports_viewport_refresh,
        viewport_refresh_mode=viewport_refresh_mode,
        legend_ticks=legend_ticks or [],
        notes=notes or [],
        delivery_modes=delivery_modes,
        result_interfaces=result_interfaces,
    )


def _weather_capabilities(layer_id: str) -> LayerCapabilities:
    spec = WEATHER_LAYER_SPECS.get(layer_id)
    if not spec:
        return _layer_capabilities(
            render_strategy="weather_tile",
            data_domain="weather",
            paint_mode="grid_fill",
        )
    return _layer_capabilities(
        render_strategy="weather_tile",
        data_domain="weather",
        paint_mode=spec.paint_mode,
        primary_metric=spec.primary_metric,
        supports_particle_flow=spec.paint_mode == "particle_flow",
        legend_ticks=list(spec.legend_ticks),
        notes=list(spec.notes),
    )


def _load_seed_descriptors() -> list[LayerDescriptor]:
    """Load layer descriptors from catalog_seeds JSON files (weather_descriptors.json & layer_descriptors.json)."""
    global _cached_descriptors, _cached_descriptors_mtime
    current_mtime = _seed_files_mtime()
    if (
        _cached_descriptors is not None
        and _cached_descriptors_mtime is not None
        and _cached_descriptors_mtime >= current_mtime
    ):
        return _cached_descriptors

    seed_files = [
        _SEEDS_DIR / "weather_descriptors.json",
        _SEEDS_DIR / "layer_descriptors.json",
    ]

    default_extent = {
        "west": 109.6,
        "south": 20.1,
        "east": 117.4,
        "north": 25.6,
        "crs": "EPSG:4326",
    }

    descriptors: list[LayerDescriptor] = []
    for seeds_file in seed_files:
        if not seeds_file.exists():
            logger.warning("Catalog seed file not found: %s", seeds_file)
            continue

        try:
            with open(seeds_file, encoding="utf-8") as f:
                raw_items = json.load(f)

            for item in raw_items:
                item_copy = dict(item)
                if "extent" not in item_copy or not item_copy["extent"]:
                    item_copy["extent"] = default_extent
                if "supported_map_modes" in item_copy:
                    item_copy["supported_map_modes"] = [
                        "2d"
                        if mode in ("2d", "mode_2d")
                        else "3d"
                        if mode in ("3d", "mode_3d")
                        else mode
                        for mode in item_copy["supported_map_modes"]
                    ]
                gran = item_copy.get("time_granularity")
                if gran not in ("hour", "day", "month"):
                    item_copy["time_granularity"] = "month" if gran == "year" else "day"

                # 自动为天气图层注入 weather_capabilities
                if (
                    item_copy.get("source_type") in ("weather", LayerSourceType.weather)
                    and "capabilities" not in item_copy
                ):
                    item_copy["capabilities"] = _weather_capabilities(
                        item_copy["layer_id"]
                    )

                try:
                    descriptors.append(LayerDescriptor.model_validate(item_copy))
                except Exception as item_exc:
                    # 单条失败不应让整文件回退到旧缓存口径；否则尾部新增图层会静默丢失。
                    logger.exception(
                        "Skipping invalid catalog seed item %s in %s: %s",
                        item_copy.get("layer_id"),
                        seeds_file,
                        item_exc,
                    )
        except Exception as exc:
            logger.exception(
                "Failed to load catalog seeds from %s: %s", seeds_file, exc
            )

    _cached_descriptors = descriptors
    _cached_descriptors_mtime = current_mtime
    return descriptors


def get_layer_categories() -> list[dict[str, Any]]:
    """Get category definitions from catalog_seeds/layer_categories.json with caching."""
    global _cached_categories
    if _cached_categories is not None:
        return _cached_categories

    categories_file = _SEEDS_DIR / "layer_categories.json"
    if not categories_file.exists():
        return []
    try:
        with open(categories_file, encoding="utf-8") as f:
            _cached_categories = json.load(f)
            return _cached_categories
    except Exception as exc:
        logger.exception(
            "Failed to load category seeds from %s: %s", categories_file, exc
        )
        return []


def get_layer_category_response() -> LayerCategoryResponse:
    """X1: 返回 LayerCategoryResponse（Pydantic 模型），供 /layers/categories 端点使用。"""
    raw = get_layer_categories()
    items: list[LayerCategoryDef] = []
    for cat in raw:
        try:
            items.append(LayerCategoryDef.model_validate(cat))
        except Exception as exc:
            logger.warning("Skipping invalid category entry %s: %s", cat.get("id"), exc)
    return LayerCategoryResponse(items=items)


def get_layer_catalog() -> LayerCatalogResponse:
    items = _load_seed_descriptors()
    return LayerCatalogResponse(items=_apply_remote_layer_data_uris(items))


def get_layer_descriptor(layer_id: str) -> LayerDescriptor | None:
    catalog = get_layer_catalog()
    for item in catalog.items:
        if item.layer_id == layer_id:
            return item
    return None
