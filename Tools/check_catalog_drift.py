#!/usr/bin/env python3
"""Gate: FE LAYER_LIBRARY catalogId must be a subset of BE catalog seed layer_id.

Usage (repo root or Code/frontend):
    python Tools/check_catalog_drift.py
    npm run check:catalog   # from Code/frontend

Exit 0 when every FE catalogId (except allowlisted FE-only) exists in
layer_descriptors.json ∪ weather_descriptors.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# FE-only entries not expected in BE seeds (admin chrome / retired shells).
FE_ONLY_ALLOWLIST = frozenset(
    {
        "admin-boundary",
        "admin-boundary-cn",
        "smap-soil",  # retired shell; FE filters from library
    }
)


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


def _fe_catalog_ids(root: Path) -> set[str]:
    catalog_ts = root / "Code" / "frontend" / "src" / "stores" / "layers" / "catalog.ts"
    text = catalog_ts.read_text(encoding="utf-8")
    return set(re.findall(r"catalogId:\s*'([^']+)'", text))


def _be_layer_ids(root: Path) -> set[str]:
    seeds_dir = root / "Code" / "backend" / "app" / "catalog_seeds"
    ids: set[str] = set()
    for name in ("layer_descriptors.json", "weather_descriptors.json"):
        path = seeds_dir / name
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", data)
        for item in items:
            lid = item.get("layer_id")
            if isinstance(lid, str) and lid:
                ids.add(lid)
    return ids


def main() -> int:
    root = _repo_root()
    fe = _fe_catalog_ids(root)
    be = _be_layer_ids(root)
    missing = sorted(fe - be - FE_ONLY_ALLOWLIST)
    if missing:
        print("Catalog drift: FE LAYER_LIBRARY catalogId not in BE seeds:")
        for cid in missing:
            print(f"  - {cid}")
        print(f"\nFE={len(fe)} BE={len(be)} missing={len(missing)}")
        return 1
    orphan_note = sorted(be - fe)
    print(
        f"Catalog OK: FE catalogIds subset of BE seeds "
        f"(FE={len(fe)} BE={len(be)} allowlist={len(FE_ONLY_ALLOWLIST)} "
        f"BE-only={len(orphan_note)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
