#!/usr/bin/env python
"""把所有 overlay 的 bounds.json 一次性导入 spatial.sqlite 的 overlays(geom) 表。

源数据：overlay_registry.list_overlay_ids()（内置 + 导入层）+ read_bounds(layer_id)["bounds"]。
日界线处理：由 SpatialRepository.upsert_overlay_bounds 内部调 overlay_safe_wgs84_bounds，
east 可 > 180（unwrap 约定），与天气引擎/前端一致。

用法（仓库根）：
    Env/Python312/python.exe Tools/import_overlay_bounds_to_spatialite.py

注意：mod_spatialite 不可用时仍会导入（geom 写 NULL），后续可重跑补 geom。
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "Code" / "backend"))
sys.path.insert(0, str(_REPO / "Code"))

from app.data_io.services.paths import IMPORTS_DIR  # noqa: E402
from app.services.overlay_registry import list_overlay_ids, get_overlay_spec, read_bounds  # noqa: E402
from app.services.spatial_repository import SpatialRepository  # noqa: E402


def _source_of(layer_id: str, overlay_dir: Path) -> str:
    """判断内置还是导入层：overlay_dir 落在 IMPORTS_DIR 下则为 imported。"""
    try:
        if overlay_dir.resolve().is_relative_to(IMPORTS_DIR.resolve()):
            return "imported"
    except (AttributeError, OSError):
        # is_relative_to 仅 3.9+；退化为字符串前缀比较
        if str(overlay_dir.resolve()).startswith(str(IMPORTS_DIR.resolve())):
            return "imported"
    return "builtin"


def main() -> int:
    repo = SpatialRepository()
    ids = list_overlay_ids()
    ok = 0
    skipped = 0
    failed = 0
    for lid in ids:
        spec = get_overlay_spec(lid)
        try:
            data = read_bounds(lid)
            b = data.get("bounds")
            if not b or len(b) < 4:
                skipped += 1
                continue
            w, s, e, n = (float(x) for x in b[:4])
            repo.upsert_overlay_bounds(
                lid,
                source=_source_of(lid, spec.overlay_dir) if spec else "builtin",
                name=lid,
                type_=getattr(spec, "category", None) if spec else None,
                minzoom=None,
                maxzoom=None,
                w=w,
                s=s,
                e=e,
                n=n,
            )
            ok += 1
        except Exception as ex:  # noqa: BLE001
            failed += 1
            print(f"  SKIP {lid}: {ex}", file=sys.stderr)
    total = repo.count()
    print(f"imported ok={ok} skipped={skipped} failed={failed} total_in_db={total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
