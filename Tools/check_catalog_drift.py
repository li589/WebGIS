#!/usr/bin/env python3
"""Gate: FE LAYER_LIBRARY catalogId ⊆ BE seeds; shared ids share display_name.

Usage (repo root or Code/frontend):
    python Tools/check_catalog_drift.py
    npm run check:catalog   # from Code/frontend

Exit 0 when:
  1. every FE catalogId (except allowlisted FE-only) exists in
     layer_descriptors.json ∪ weather_descriptors.json;
  2. for every id present in both FE and BE, FE `name` equals BE `display_name`.
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


def _fe_catalog_entries(root: Path) -> dict[str, str]:
    """Parse LAYER_LIBRARY blocks: catalogId -> name (first name field in block)."""
    catalog_ts = root / "Code" / "frontend" / "src" / "stores" / "layers" / "catalog.ts"
    text = catalog_ts.read_text(encoding="utf-8")
    # Split on object starts inside LAYER_LIBRARY array
    blocks = re.split(r"\n  \{\n", text)
    out: dict[str, str] = {}
    for block in blocks:
        m_id = re.search(r"catalogId:\s*'([^']+)'", block)
        m_name = re.search(r"name:\s*'([^']+)'", block)
        if m_id and m_name:
            out[m_id.group(1)] = m_name.group(1)
    return out


def _be_layer_entries(root: Path) -> dict[str, str]:
    seeds_dir = root / "Code" / "backend" / "app" / "catalog_seeds"
    out: dict[str, str] = {}
    for name in ("layer_descriptors.json", "weather_descriptors.json"):
        path = seeds_dir / name
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", data)
        for item in items:
            lid = item.get("layer_id")
            if isinstance(lid, str) and lid:
                dn = item.get("display_name")
                out[lid] = dn if isinstance(dn, str) else ""
    return out


def main() -> int:
    root = _repo_root()
    fe = _fe_catalog_entries(root)
    be = _be_layer_entries(root)
    fe_ids = set(fe)
    be_ids = set(be)

    missing = sorted(fe_ids - be_ids - FE_ONLY_ALLOWLIST)
    if missing:
        print("Catalog drift: FE LAYER_LIBRARY catalogId not in BE seeds:")
        for cid in missing:
            print(f"  - {cid}")
        print(f"\nFE={len(fe_ids)} BE={len(be_ids)} missing={len(missing)}")
        return 1

    name_mismatches: list[tuple[str, str, str]] = []
    for cid in sorted(fe_ids & be_ids):
        fe_name = fe[cid]
        be_name = be[cid]
        if fe_name != be_name:
            name_mismatches.append((cid, fe_name, be_name))

    if name_mismatches:
        print("Catalog drift: FE name ≠ BE display_name for shared layer_id:")
        for cid, fe_name, be_name in name_mismatches:
            print(f"  - {cid}: FE={fe_name!r} BE={be_name!r}")
        print(f"\nmismatches={len(name_mismatches)}")
        return 1

    orphan_note = sorted(be_ids - fe_ids)
    print(
        f"Catalog OK: FE catalogIds subset of BE seeds and display names aligned "
        f"(FE={len(fe_ids)} BE={len(be_ids)} allowlist={len(FE_ONLY_ALLOWLIST)} "
        f"BE-only={len(orphan_note)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
