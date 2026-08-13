#!/usr/bin/env python3
"""X1 codegen: generate frontend catalog-seeds.generated.json from backend JSON.

This script is the build-time code generation step that eliminates the
multi-source-of-truth problem in the layer catalog. It reads the backend
``catalog_seeds/*.json`` files (the single source of truth) and produces
a frontend-ready JSON file with camelCase field names and expanded
``presentation`` fields.

Usage (repo root):
    python Tools/generate_catalog_seeds.py
    # or from Code/frontend:
    npm run gen:catalog

Reads:
  - Code/backend/app/catalog_seeds/layer_descriptors.json
  - Code/backend/app/catalog_seeds/weather_descriptors.json
  - Code/backend/app/catalog_seeds/layer_categories.json

Writes:
  - Code/frontend/src/stores/layers/catalog-seeds.generated.json

Field mapping summary:
  LayerDescriptor.layer_id        → LayerCatalogItem.catalogId
  LayerDescriptor.display_name    → LayerCatalogItem.name
  LayerDescriptor.sub_category    → LayerCatalogItem.subCategory
  LayerDescriptor.presentation.*  → LayerCatalogItem.* (expanded to top level)
  LayerDescriptor.sources[]       → LayerCatalogItem.sources[] (source_id → id)
  LayerDescriptor.merged_into     → LayerCatalogItem.mergedInto
  LayerDescriptor.is_merged_group → LayerCatalogItem.isMergedGroup
  LayerDescriptor.members         → LayerCatalogItem.members
  LayerDescriptor.is_admin_boundary → LayerCatalogItem.isAdminBoundary
  LayerDescriptor.data_owner      → LayerCatalogItem.dataOwner
  LayerDescriptor.temporal_coverage → LayerCatalogItem.temporalCoverage
  LayerDescriptor.source_reference → LayerCatalogItem.sourceReference

  LayerCategoryDef.accent_color   → LayerCategory.accentColor
  LayerCategoryDef.chip_tone      → LayerCategory.chipTone
  LayerCategoryDef.sub_categories → LayerCategory.subCategories

  LayerSourceDef.source_id        → LayerSource.id
  LayerSourceDef.url_template     → LayerSource.urlTemplate
  LayerSourceDef.needs_auth       → LayerSource.needsAuth
  LayerSourceDef.needs_backend_transform → LayerSource.needsBackendTransform
  LayerSourceDef.coord_sys        → LayerSource.coordSys
  LayerSourceDef.update_frequency → LayerSource.updateFrequency
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


# ── Path resolution ──────────────────────────────────────────────────────────

def _repo_root() -> Path:
    """Resolve repo root from script location or cwd."""
    here = Path(__file__).resolve().parent
    if (here / "Code" / "frontend").is_dir():
        return here
    if here.name == "Tools":
        return here.parent
    # Fallback: assume cwd is repo root
    cwd = Path.cwd()
    if (cwd / "Code" / "frontend").is_dir():
        return cwd
    return here


# ── Transformation functions ─────────────────────────────────────────────────

def transform_source(src: dict[str, Any]) -> dict[str, Any]:
    """Transform backend LayerSourceDef → frontend LayerSource.

    Key mapping: ``source_id`` → ``id`` (the critical X1 field rename).
    Runtime-only fields (runReadiness, backendStatus, supportsTime) are
    intentionally omitted — they are injected by catalog-runtime.ts.
    """
    result: dict[str, Any] = {
        "id": src["source_id"],
        "name": src.get("name", ""),
        "description": src.get("description", ""),
        "urlTemplate": src.get("url_template", ""),
        "needsAuth": src.get("needs_auth", False),
        "needsBackendTransform": src.get("needs_backend_transform", False),
        "coordSys": src.get("coord_sys", "EPSG:4326"),
        "updateFrequency": src.get("update_frequency", ""),
    }
    attribution = src.get("attribution")
    if attribution is not None:
        result["attribution"] = attribution
    return result


def transform_descriptor(desc: dict[str, Any]) -> dict[str, Any]:
    """Transform backend LayerDescriptor → frontend LayerCatalogItem.

    The ``presentation`` block is expanded to top-level fields.
    All snake_case keys are converted to camelCase.
    """
    pres = desc.get("presentation") or {}

    # Build the LayerCatalogItem with presentation fields expanded
    item: dict[str, Any] = {
        # Core identity
        "catalogId": desc["layer_id"],
        "name": desc.get("display_name", desc["layer_id"]),
        "category": desc.get("category", "research-group"),
    }

    # Sub-category (optional — omit when null for clean TypeScript optional field)
    sub_category = desc.get("sub_category")
    if sub_category is not None:
        item["subCategory"] = sub_category

    item.update({
        # Presentation fields (expanded from presentation block)
        "metricLabel": pres.get("metric_label", "主指标"),
        "metricUnit": pres.get("metric_unit", ""),
        "metricPrecision": pres.get("metric_precision", 1),
        "updateLabel": pres.get("update_label", ""),
        "sourceLabel": pres.get("source_label", ""),
        "accentColor": pres.get("accent_color", "#67d4ff"),
        "accentGlow": pres.get("accent_glow", "rgba(103, 212, 255, 0.28)"),
        "chipTone": pres.get("chip_tone", "rgba(103, 212, 255, 0.16)"),
        # Sources (transformed from LayerSourceDef[])
        "sources": [transform_source(s) for s in desc.get("sources", [])],
        # X1 externalization fields
        "isMergedGroup": desc.get("is_merged_group", False),
        "members": desc.get("members", []),
        "isAdminBoundary": desc.get("is_admin_boundary", False),
    })

    # Optional metadata fields (omit if not present for clean JSON)
    merged_into = desc.get("merged_into")
    if merged_into is not None:
        item["mergedInto"] = merged_into

    data_owner = desc.get("data_owner")
    if data_owner is not None:
        item["dataOwner"] = data_owner

    temporal_coverage = desc.get("temporal_coverage")
    if temporal_coverage is not None:
        item["temporalCoverage"] = temporal_coverage

    source_reference = desc.get("source_reference")
    if source_reference is not None:
        item["sourceReference"] = source_reference

    return item


def transform_category(cat: dict[str, Any]) -> dict[str, Any]:
    """Transform backend LayerCategoryDef → frontend LayerCategory."""
    result: dict[str, Any] = {
        "id": cat["id"],
        "name": cat.get("name", cat["id"]),
        "icon": cat.get("icon", ""),
        "accentColor": cat.get("accent_color", "#67d4ff"),
        "chipTone": cat.get("chip_tone", "rgba(103, 212, 255, 0.16)"),
    }
    sub_categories = cat.get("sub_categories")
    if sub_categories is not None:
        result["subCategories"] = sub_categories
    return result


# ── Main codegen logic ───────────────────────────────────────────────────────

def main() -> int:
    root = _repo_root()
    seeds_dir = root / "Code" / "backend" / "app" / "catalog_seeds"

    # Input files
    layer_path = seeds_dir / "layer_descriptors.json"
    weather_path = seeds_dir / "weather_descriptors.json"
    categories_path = seeds_dir / "layer_categories.json"

    # Validate inputs exist
    missing = [p for p in (layer_path, weather_path, categories_path) if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: Backend seed file not found: {p}", file=sys.stderr)
        return 1

    # Read backend JSON
    print("Reading backend catalog seeds...")
    with open(layer_path, "r", encoding="utf-8") as f:
        layer_descriptors = json.load(f)
    with open(weather_path, "r", encoding="utf-8") as f:
        weather_descriptors = json.load(f)
    with open(categories_path, "r", encoding="utf-8") as f:
        categories_raw = json.load(f)

    print(f"  layer_descriptors.json: {len(layer_descriptors)} entries")
    print(f"  weather_descriptors.json: {len(weather_descriptors)} entries")
    print(f"  layer_categories.json: {len(categories_raw)} categories")

    # Transform descriptors → LayerCatalogItem[]
    # Weather descriptors come first (matching current LAYER_LIBRARY ordering convention)
    items: list[dict[str, Any]] = []
    for desc in weather_descriptors:
        try:
            items.append(transform_descriptor(desc))
        except KeyError as exc:
            print(f"  WARNING: Skipping weather descriptor {desc.get('layer_id', '?')}: missing {exc}", file=sys.stderr)

    for desc in layer_descriptors:
        try:
            items.append(transform_descriptor(desc))
        except KeyError as exc:
            print(f"  WARNING: Skipping layer descriptor {desc.get('layer_id', '?')}: missing {exc}", file=sys.stderr)

    # Transform categories → LayerCategory[]
    categories: list[dict[str, Any]] = []
    for cat in categories_raw:
        try:
            categories.append(transform_category(cat))
        except KeyError as exc:
            print(f"  WARNING: Skipping category {cat.get('id', '?')}: missing {exc}", file=sys.stderr)

    # Build output structure
    output = {
        "categories": categories,
        "items": items,
    }

    # Write output
    output_path = root / "Code" / "frontend" / "src" / "stores" / "layers" / "catalog-seeds.generated.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # Summary
    merged_count = sum(1 for i in items if i.get("isMergedGroup"))
    multi_source_count = sum(1 for i in items if len(i.get("sources", [])) > 1)
    # ASCII-only: Windows consoles often use GBK and choke on ✓ / →
    print(
        f"\n[OK] Generated {len(items)} items "
        f"({merged_count} merged groups, {multi_source_count} multi-source)"
    )
    print(f"  + {len(categories)} categories")
    print(f"  -> {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
