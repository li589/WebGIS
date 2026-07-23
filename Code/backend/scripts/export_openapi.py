"""导出 FastAPI OpenAPI schema 到 JSON 文件。

用法：
    python scripts/export_openapi.py [output_path]

默认输出到 Code/frontend/openapi.json。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def export_openapi(output_path: str | None = None) -> Path:
    """导出 OpenAPI schema 并返回输出文件路径。"""
    # 将 backend 目录加入 sys.path 以便导入 app
    backend_root = Path(__file__).resolve().parent.parent  # Code/backend
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    # Code 目录在 sys.path 中以便导入 shared.contracts
    code_root = backend_root.parent  # Code
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))

    # GEE 模块路径
    gee_src = str(backend_root / "app" / "gee" / "core" / "src")
    if gee_src not in sys.path:
        sys.path.insert(0, gee_src)

    from app.main import app

    schema = app.openapi()

    if output_path is None:
        output_path = str(code_root / "frontend" / "openapi.json")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"OpenAPI schema exported to {out} ({len(schema.get('paths', {}))} paths, {len(schema.get('components', {}).get('schemas', {}))} schemas)"
    )
    return out


if __name__ == "__main__":
    export_openapi(sys.argv[1] if len(sys.argv) > 1 else None)
