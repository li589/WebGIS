#!/usr/bin/env python3
"""Gate: FE LAYER_LIBRARY catalogId ⊆ BE seeds; shared ids share display_name + presentation.

Usage (repo root or Code/frontend):
    python Tools/check_catalog_drift.py
    npm run check:catalog   # from Code/frontend

Exit 0 when:
  1. every FE catalogId (except allowlisted FE-only) exists in
     layer_descriptors.json ∪ weather_descriptors.json;
  2. for every id present in both FE and BE, FE `name` equals BE `display_name`;
  3. X1: for every id present in both, FE presentation fields
     (accentColor / metricLabel / metricUnit / metricPrecision / updateLabel /
     sourceLabel) match BE `presentation` block;
  4. X1: FE `LAYER_CATEGORIES` ids ⊆ BE `layer_categories.json` ids,
     and shared ids have matching `name`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# FE-only entries not expected in BE seeds (admin chrome / retired shells / FE-only merged groups).
FE_ONLY_ALLOWLIST = frozenset(
    {
        "admin-boundary",
        "admin-boundary-cn",
        "soil-moisture",
    }
)

# X1: presentation fields to cross-check (FE field name → BE JSON key)
PRESENTATION_FIELD_MAP = {
    "accentColor": "accent_color",
    "metricLabel": "metric_label",
    "metricUnit": "metric_unit",
    "updateLabel": "update_label",
    "sourceLabel": "source_label",
}
# numeric fields compared with int() coercion
PRESENTATION_NUMERIC_FIELDS = {"metricPrecision": "metric_precision"}


def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    if (here / "Code" / "frontend").is_dir():
        return here
    # Tools/ → repo root
    if here.name == "Tools":
        return here.parent
    # Code/frontend/scripts → repo root
    if here.name == "scripts":
        return here.parents[2]
    return here


def _fe_catalog_entries(root: Path) -> dict[str, dict[str, str]]:
    """Parse LAYER_LIBRARY blocks: catalogId → {name, accentColor, metricLabel, ...}."""
    catalog_ts = root / "Code" / "frontend" / "src" / "stores" / "layers" / "catalog.ts"
    text = catalog_ts.read_text(encoding="utf-8")
    # Find the LAYER_LIBRARY array, skipping the type annotation's LayerCatalogItem[]
    start = text.find("export const LAYER_LIBRARY")
    eq_bracket = text.find("= [", start)
    arr_start = text.index("[", eq_bracket)
    # Find matching close bracket
    depth = 0
    end = arr_start
    for i, ch in enumerate(text[arr_start:], arr_start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    arr_text = text[arr_start:end]

    # Split on block boundaries (compatible with \r\n)
    blocks = re.split(r"\r?\n  \{\r?\n", arr_text)
    out: dict[str, dict[str, str]] = {}
    for block in blocks:
        m_id = re.search(r"catalogId:\s*'([^']+)'", block)
        if not m_id:
            continue
        cid = m_id.group(1)
        entry: dict[str, str] = {}
        for fe_field in (
            "name",
            "accentColor",
            "metricLabel",
            "metricUnit",
            "updateLabel",
            "sourceLabel",
        ):
            m = re.search(rf"{fe_field}:\s*'([^']*)'", block)
            if m:
                entry[fe_field] = m.group(1)
        for fe_field in ("metricPrecision",):
            m = re.search(rf"{fe_field}:\s*(\d+)", block)
            if m:
                entry[fe_field] = m.group(1)
        out[cid] = entry
    return out


def _be_layer_entries(root: Path) -> dict[str, dict[str, object]]:
    """Load BE seeds: layer_id → {display_name, presentation dict}."""
    seeds_dir = root / "Code" / "backend" / "app" / "catalog_seeds"
    out: dict[str, dict[str, object]] = {}
    for name in ("layer_descriptors.json", "weather_descriptors.json"):
        path = seeds_dir / name
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", data)
        for item in items:
            lid = item.get("layer_id")
            if isinstance(lid, str) and lid:
                out[lid] = {
                    "display_name": item.get("display_name", ""),
                    "presentation": item.get("presentation") or {},
                }
    return out


def _fe_categories(root: Path) -> dict[str, str]:
    """Parse LAYER_CATEGORIES: id → name."""
    catalog_ts = root / "Code" / "frontend" / "src" / "stores" / "layers" / "catalog.ts"
    text = catalog_ts.read_text(encoding="utf-8")
    start = text.find("export const LAYER_CATEGORIES")
    eq_bracket = text.find("= [", start)
    arr_start = text.index("[", eq_bracket)
    depth = 0
    end = arr_start
    for i, ch in enumerate(text[arr_start:], arr_start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    arr_text = text[arr_start:end]
    blocks = re.split(r"\r?\n  \{\r?\n", arr_text)
    out: dict[str, str] = {}
    for block in blocks:
        m_id = re.search(r"id:\s*'([^']+)'", block)
        m_name = re.search(r"name:\s*'([^']*)'", block)
        if m_id and m_name:
            out[m_id.group(1)] = m_name.group(1)
    return out


def _be_categories(root: Path) -> dict[str, str]:
    """Load BE layer_categories.json: id → name."""
    cat_path = root / "Code" / "backend" / "app" / "catalog_seeds" / "layer_categories.json"
    data = json.loads(cat_path.read_text(encoding="utf-8"))
    return {c["id"]: c.get("name", "") for c in data if "id" in c}


def main() -> int:
    root = _repo_root()
    fe = _fe_catalog_entries(root)
    be = _be_layer_entries(root)
    fe_ids = set(fe)
    be_ids = set(be)

    # 1. Missing in BE
    missing = sorted(fe_ids - be_ids - FE_ONLY_ALLOWLIST)
    if missing:
        print("Catalog drift: FE LAYER_LIBRARY catalogId not in BE seeds:")
        for cid in missing:
            print(f"  - {cid}")
        print(f"\nFE={len(fe_ids)} BE={len(be_ids)} missing={len(missing)}")
        return 1

    # 2. Display name mismatches
    name_mismatches: list[tuple[str, str, str]] = []
    for cid in sorted(fe_ids & be_ids):
        fe_name = fe[cid].get("name", "")
        be_name = be[cid].get("display_name", "")
        if fe_name != be_name:
            name_mismatches.append((cid, fe_name, be_name))
    if name_mismatches:
        print("Catalog drift: FE name ≠ BE display_name for shared layer_id:")
        for cid, fe_name, be_name in name_mismatches:
            print(f"  - {cid}: FE={fe_name!r} BE={be_name!r}")
        print(f"\nmismatches={len(name_mismatches)}")
        return 1

    # 3. X1: Presentation field mismatches
    pres_mismatches: list[str] = []
    for cid in sorted(fe_ids & be_ids):
        fe_entry = fe[cid]
        be_pres = be[cid].get("presentation", {})
        if not isinstance(be_pres, dict):
            be_pres = {}
        for fe_field, be_field in PRESENTATION_FIELD_MAP.items():
            fe_val = fe_entry.get(fe_field)
            be_val = be_pres.get(be_field)
            if fe_val is not None and be_val is not None and fe_val != be_val:
                pres_mismatches.append(
                    f"  - {cid}.{fe_field}: FE={fe_val!r} BE={be_val!r}"
                )
            elif fe_val is not None and be_val is None:
                pres_mismatches.append(
                    f"  - {cid}.{fe_field}: FE={fe_val!r} BE=missing"
                )
        for fe_field, be_field in PRESENTATION_NUMERIC_FIELDS.items():
            fe_val = fe_entry.get(fe_field)
            be_val = be_pres.get(be_field)
            if fe_val is not None and be_val is not None:
                try:
                    if int(fe_val) != int(be_val):
                        pres_mismatches.append(
                            f"  - {cid}.{fe_field}: FE={fe_val} BE={be_val}"
                        )
                except (ValueError, TypeError):
                    pass
    if pres_mismatches:
        print("Catalog drift: FE presentation field ≠ BE presentation for shared layer_id:")
        for m in pres_mismatches:
            print(m)
        print(f"\npresentation_mismatches={len(pres_mismatches)}")
        return 1

    # 4. X1: Category drift check
    fe_cats = _fe_categories(root)
    be_cats = _be_categories(root)
    cat_missing = sorted(set(fe_cats) - set(be_cats))
    cat_name_mismatches: list[tuple[str, str, str]] = []
    for cid in sorted(set(fe_cats) & set(be_cats)):
        if fe_cats[cid] != be_cats[cid]:
            cat_name_mismatches.append((cid, fe_cats[cid], be_cats[cid]))
    if cat_missing or cat_name_mismatches:
        if cat_missing:
            print("Category drift: FE LAYER_CATEGORIES id not in BE layer_categories.json:")
            for cid in cat_missing:
                print(f"  - {cid}")
        if cat_name_mismatches:
            print("Category drift: FE category name ≠ BE category name:")
            for cid, fe_name, be_name in cat_name_mismatches:
                print(f"  - {cid}: FE={fe_name!r} BE={be_name!r}")
        return 1

    orphan_note = sorted(be_ids - fe_ids)
    print(
        f"Catalog OK: FE catalogIds subset of BE seeds, display names aligned, "
        f"presentation aligned, categories aligned "
        f"(FE={len(fe_ids)} BE={len(be_ids)} allowlist={len(FE_ONLY_ALLOWLIST)} "
        f"BE-only={len(orphan_note)} categories={len(fe_cats)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
