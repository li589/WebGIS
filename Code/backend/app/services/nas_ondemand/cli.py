"""nas_ondemand 命令行：L1/L5 验证与排障。

用法（在 Code/backend 目录下，用项目 Python）：
    # L1：单帧验证（第一次会连 NAS 发 GET）
    python -m app.services.nas_ondemand.cli frame --product fy_avg --var SM --date 20251201

    # 同一天再跑一次：应显示 source=local，不连 NAS
    python -m app.services.nas_ondemand.cli frame --product fy_avg --var SM --date 20251201

    # 按需补帧：写进既有工作流图层目录（不改该层 meta.json）
    python -m app.services.nas_ondemand.cli layer-frame \
        --layer-id imported-55359b8ecd3d --date 20251202

    # L5：只看缓存现状（纯本地，不连 NAS）
    python -m app.services.nas_ondemand.cli state

    # L5：容量演练，不删任何文件
    python -m app.services.nas_ondemand.cli evict --dry-run

    # 只验证白名单拦截有没有生效（纯本地，不连 NAS）
    python -m app.services.nas_ondemand.cli guard --path /Chenhaojun/omega_final/x.mat
"""

from __future__ import annotations

import argparse
import json
import sys


def _cmd_frame(args: argparse.Namespace) -> int:
    from app.services.nas_ondemand.service import ensure_frame

    try:
        result = ensure_frame(args.product, args.var, args.date, force=bool(args.force))
    except Exception as exc:  # noqa: BLE001 - CLI 要把错误原样打给用户
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _cmd_layer_frame(args: argparse.Namespace) -> int:
    from app.services.nas_ondemand.service import ensure_layer_frame

    try:
        result = ensure_layer_frame(args.layer_id, args.date, force=bool(args.force))
    except Exception as exc:  # noqa: BLE001 - CLI 要把错误原样打给用户
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _cmd_state(_args: argparse.Namespace) -> int:
    from app.services.nas_ondemand.service import cache_state

    print(json.dumps(cache_state(), indent=2, ensure_ascii=False))
    return 0


def _cmd_evict(args: argparse.Namespace) -> int:
    from app.services.nas_ondemand.cache import ensure_capacity

    result = ensure_capacity(dry_run=bool(args.dry_run))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.dry_run:
        print("\n（演练模式：以上清单只是「打算删谁」，实际未删任何文件）")
    return 0


def _cmd_guard(args: argparse.Namespace) -> int:
    """纯本地校验白名单：不发任何网络请求。"""
    from app.services.nas_ondemand import config, fetcher

    print("白名单目录：")
    for prefix in config.ALLOWED_NAS_PREFIXES:
        print(f"  允许  {prefix}")
    print()
    ok = True
    for path in args.path:
        try:
            normalized = fetcher.assert_nas_path_readable(path)
            try:
                fetcher.assert_mat_filename(normalized)
                note = "文件名合规"
            except fetcher.NasPathDenied as exc:
                note = f"但{exc}"
            print(f"  放行  {path}  →  {normalized}（{note}）")
        except fetcher.NasPathDenied as exc:
            print(f"  拦截  {path}  →  {exc}")
            ok = False
    print()
    print("拦截生效" if not ok else "以上路径均在白名单内")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.nas_ondemand.cli",
        description="NAS 按需出图：单帧验证 / 缓存查看 / 淘汰演练 / 白名单校验",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_frame = sub.add_parser("frame", help="确保某天有图（首次会连 NAS）")
    p_frame.add_argument(
        "--product", required=True, help="fy_avg|fy_raw|smap_avg|smap_raw"
    )
    p_frame.add_argument("--var", required=True, help="SM|VOD|OMEGA")
    p_frame.add_argument("--date", required=True, help="YYYYMMDD")
    p_frame.add_argument("--force", action="store_true", help="忽略本地缓存强制重取")
    p_frame.set_defaults(func=_cmd_frame)

    p_layer = sub.add_parser(
        "layer-frame", help="按需补帧：写进既有图层目录（不改该层 meta.json）"
    )
    p_layer.add_argument("--layer-id", required=True, help="imported-… 图层 ID")
    p_layer.add_argument("--date", required=True, help="YYYYMMDD")
    p_layer.add_argument("--force", action="store_true", help="忽略本地已有强制重取")
    p_layer.set_defaults(func=_cmd_layer_frame)

    p_state = sub.add_parser("state", help="查看缓存现状（纯本地）")
    p_state.set_defaults(func=_cmd_state)

    p_evict = sub.add_parser("evict", help="容量清理（默认演练）")
    p_evict.add_argument("--dry-run", action="store_true", default=True)
    p_evict.add_argument("--apply", dest="dry_run", action="store_false")
    p_evict.set_defaults(func=_cmd_evict)

    p_guard = sub.add_parser("guard", help="校验白名单拦截（纯本地，不连网）")
    p_guard.add_argument("--path", nargs="+", required=True)
    p_guard.set_defaults(func=_cmd_guard)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
