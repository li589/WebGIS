#!/usr/bin/env python3
"""X1: Verify catalog-seeds.generated.json is in sync with backend JSON.

After X1 externalization, the frontend catalog fallback is generated from
backend JSON via ``generate_catalog_seeds.py``. This script verifies the
generated JSON is up-to-date and consistent with the backend seeds —
replacing the old cross-file text-parsing drift checker.

Usage (repo root or Code/frontend):
    python Tools/check_catalog_drift.py
    npm run check:catalog   # from Code/frontend

Exit 0 when:
  1. catalog-seeds.generated.json exists and is valid JSON;
  2. generated item count == backend layer + weather descriptor count;
  3. every generated catalogId exists in backend layer_id set (and vice versa);
  4. every generated item name matches backend display_name;
  5. generated category count == backend category count;
  6. every generated category id exists in backend category set.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    """Resolve repo root from script location or cwd."""
    here = Path(__file__).resolve().parent
    if (here / "Code" / "frontend").is_dir():
        return here
    if here.name == "Tools":
        return here.parent
    if here.name == "scripts":
        return here.parents[2]
    cwd = Path.cwd()
    if (cwd / "Code" / "frontend").is_dir():
        return cwd
    return here


def _load_backend_descriptors(root: Path) -> dict[str, dict[str, Any]]:
    """Load all backend layer + weather descriptors: layer_id → descriptor."""
    seeds_dir = root / "Code" / "backend" / "app" / "catalog_seeds"
    out: dict[str, dict[str, Any]] = {}
    for name in ("layer_descriptors.json", "weather_descriptors.json"):
        path = seeds_dir / name
        if not path.exists():
            print(f"ERROR: Backend seed file not found: {path}", file=sys.stderr)
            sys.exit(1)
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", [])
        for item in items:
            lid = item.get("layer_id")
            if isinstance(lid, str) and lid:
                out[lid] = item
    return out


def _load_backend_categories(root: Path) -> dict[str, dict[str, Any]]:
    """Load backend layer_categories.json: id → category."""
    cat_path = root / "Code" / "backend" / "app" / "catalog_seeds" / "layer_categories.json"
    if not cat_path.exists():
        print(f"ERROR: Backend category file not found: {cat_path}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(cat_path.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data if "id" in c}


def _load_generated(root: Path) -> dict[str, Any]:
    """Load catalog-seeds.generated.json."""
    gen_path = root / "Code" / "frontend" / "src" / "stores" / "layers" / "catalog-seeds.generated.json"
    if not gen_path.exists():
        print(
            "ERROR: catalog-seeds.generated.json not found.\n"
            "  Run: npm run gen:catalog  (from Code/frontend)\n"
            "  Or:  python Tools/generate_catalog_seeds.py  (from repo root)",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.loads(gen_path.read_text(encoding="utf-8"))


def main() -> int:
    root = _repo_root()

    # Load data
    be_descriptors = _load_backend_descriptors(root)
    be_categories = _load_backend_categories(root)
    generated = _load_generated(root)

    gen_items: list[dict[str, Any]] = generated.get("items", [])
    gen_categories: list[dict[str, Any]] = generated.get("categories", [])

    be_ids = set(be_descriptors)
    gen_ids = {item["catalogId"] for item in gen_items if "catalogId" in item}

    be_cat_ids = set(be_categories)
    gen_cat_ids = {c["id"] for c in gen_categories if "id" in c}

    errors: list[str] = []

    # 1. Item count check
    if len(gen_items) != len(be_descriptors):
        errors.append(
            f"Item count mismatch: generated={len(gen_items)} backend={len(be_descriptors)}"
        )

    # 2. Item ID set check (bidirectional)
    missing_in_gen = sorted(be_ids - gen_ids)
    extra_in_gen = sorted(gen_ids - be_ids)
    if missing_in_gen:
        errors.append(
            f"Backend layer_ids missing from generated JSON ({len(missing_in_gen)}): "
            + ", ".join(missing_in_gen[:10])
        )
    if extra_in_gen:
        errors.append(
            f"Generated catalogIds not in backend JSON ({len(extra_in_gen)}): "
            + ", ".join(extra_in_gen[:10])
        )

    # 3. Display name check
    name_mismatches: list[str] = []
    for item in gen_items:
        cid = item.get("catalogId", "")
        gen_name = item.get("name", "")
        be_desc = be_descriptors.get(cid)
        if be_desc:
            be_name = be_desc.get("display_name", "")
            if gen_name != be_name:
                name_mismatches.append(f"  {cid}: generated={gen_name!r} backend={be_name!r}")
    if name_mismatches:
        errors.append(
            f"Display name mismatches ({len(name_mismatches)}):\n"
            + "\n".join(name_mismatches[:10])
        )

    # 4. Category count check
    if len(gen_categories) != len(be_categories):
        errors.append(
            f"Category count mismatch: generated={len(gen_categories)} backend={len(be_categories)}"
        )

    # 5. Category ID set check
    cat_missing = sorted(be_cat_ids - gen_cat_ids)
    cat_extra = sorted(gen_cat_ids - be_cat_ids)
    if cat_missing:
        errors.append(
            f"Backend category ids missing from generated JSON: {', '.join(cat_missing)}"
        )
    if cat_extra:
        errors.append(
            f"Generated category ids not in backend JSON: {', '.join(cat_extra)}"
        )

    # 6. Category name check
    cat_name_mismatches: list[str] = []
    for gen_cat in gen_categories:
        cat_id = gen_cat.get("id", "")
        be_cat = be_categories.get(cat_id)
        if be_cat:
            gen_name = gen_cat.get("name", "")
            be_name = be_cat.get("name", "")
            if gen_name != be_name:
                cat_name_mismatches.append(
                    f"  {cat_id}: generated={gen_name!r} backend={be_name!r}"
                )
    if cat_name_mismatches:
        errors.append(
            f"Category name mismatches ({len(cat_name_mismatches)}):\n"
            + "\n".join(cat_name_mismatches)
        )

    # Report
    if errors:
        print("Catalog drift detected:")
        for err in errors:
            print(f"  ✗ {err}")
        print(
            f"\nGenerated: {len(gen_items)} items, {len(gen_categories)} categories | "
            f"Backend: {len(be_descriptors)} descriptors, {len(be_categories)} categories"
        )
        print("\nFix: run `npm run gen:catalog` (from Code/frontend) to regenerate.")
        return 1

    print(
        f"Catalog OK: {len(gen_items)} items + {len(gen_categories)} categories "
        f"in sync with backend seeds."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
