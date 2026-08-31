"""存量 remote_sources 文件级条目 → 数据集授权迁移（plan §5，阶段 3/6）。

迁移规则（kind=portal 且 remote_path 非空）：
1. 内置映射表（_BUILTIN_DATASET_HINTS）按 portal+路径正则推断 dataset_key；
2. 通用短名规则（remote_path 首段为 CMR 短名形态）；
3. fallback：推断失败保留 legacy（不打断现有访问），前端标「待人工归并」。

其他形态：
- ``remote_path=''`` 的 portal 条目 → 原地升级 ``access_mode='site_compatible'``；
- ``kind=storage_profile`` 条目 → ``access_mode='site_compatible'``（整源全放行语义）。

幂等：KV 标记 ``remote_source_migration_v2_done``；条目 archived 幂等。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_MIGRATION_KV_KEY = "remote_source_migration_v2_done"

# 内置映射表：portal_id -> [(路径正则, dataset_key, path_prefix)]
# path_prefix 为门户 base_url 下的路径前缀（http_open_data 归属判断用）。
_BUILTIN_DATASET_HINTS: dict[str, list[tuple[str, str, str]]] = {
    "nasa_gldas": [
        (
            r"(?:data/)?GLDAS(?:_NOAH025_3H)?",
            "GLDAS_NOAH025_3H",
            "data/GLDAS_NOAH025_3H",
        ),
    ],
    "nasa_ges_disc": [
        (
            r"(?:data/)?GLDAS(?:_NOAH025_3H)?",
            "GLDAS_NOAH025_3H",
            "data/GLDAS_NOAH025_3H",
        ),
    ],
    "nsidc_data": [
        (r"SPL3SMP_E", "SPL3SMP_E", "SPL3SMP_E"),
    ],
    "esa_copernicus": [
        # 任务_产品级模式（S1A_IW_GRDH / S2A_MSIL1C …）——dataset_key 动态取组
        (r"(S\d[AB]_[A-Z0-9]+(?:_[A-Z0-9]+)?)", "", ""),
    ],
    "esa_download": [
        (r"(S\d[AB]_[A-Z0-9]+(?:_[A-Z0-9]+)?)", "", ""),
    ],
    "cma_nsmc": [
        (r"(FY3[BD])[^/]*?(MWRI[AD]?)", "", ""),
    ],
    "cma_data": [
        (r"(FY3[BD])[^/]*?(MWRI[AD]?)", "", ""),
    ],
    "noaa_nomads": [
        (r"(gfs|gefs|gdas|nam|rap|hrrr)", "", ""),
    ],
}

# 通用短名形态（CMR short_name）：大写字母开头、≥6 位、大写/数字/下划线
_GENERIC_SHORTNAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{5,}$")


def _infer_dataset(portal_id: str, remote_path: str) -> tuple[str, str] | None:
    """推断 (dataset_key, path_prefix)；失败返回 None。

    内置映射优先（动态组取正则 group(1)），回退通用短名规则。
    """
    path = str(remote_path or "").strip().lstrip("/").replace("\\", "/")
    if not path:
        return None
    for pattern, fixed_key, fixed_prefix in _BUILTIN_DATASET_HINTS.get(portal_id, []):
        m = re.search(pattern, path, re.IGNORECASE)
        if m:
            key = fixed_key or (
                m.group(1) + (m.group(2) or "")
                if m.groups() and len(m.groups()) > 1
                else m.group(1)
            )
            # 双组模式（FY3D_MWRID 型）：拼两组
            if not fixed_key and len(m.groups()) >= 2 and m.group(2):
                key = f"{m.group(1)}_{m.group(2)}"
            prefix = fixed_prefix or (m.group(1) if m.groups() else path.split("/")[0])
            return key.upper(), prefix
    # 通用短名规则：首段为 CMR 短名形态
    first = path.split("/")[0]
    if _GENERIC_SHORTNAME_RE.match(first):
        return first, first
    return None


def migrate_legacy_remote_sources(
    *, dry_run: bool = False, safe: bool = False
) -> dict[str, Any]:
    """执行存量迁移；返回 MigrationReport。

    - ``dry_run``：只报告不落库。
    - ``safe``：推断失败的条目所在门户自动升级为 site_compatible
      （等价旧「整源」行为），避免迁移后访问中断。
    """
    from app.services.remote_dataset_grants import get_remote_dataset_grants
    from app.services.remote_source_registry import get_remote_source_registry

    sources = get_remote_source_registry()
    grants = get_remote_dataset_grants()

    report: dict[str, Any] = {
        "dry_run": dry_run,
        "total": 0,
        "migrated_to_grants": 0,
        "upgraded_site_compatible": 0,
        "kept_legacy": 0,
        "already_done": False,
        "details": [],
        "safe_mode": safe,
    }

    # 幂等标记（dry_run 不消费标记）
    if not dry_run and _kv_get(sources, _MIGRATION_KV_KEY):
        report["already_done"] = True
        return report

    entries = sources.list_entries()
    report["total"] = len(entries)

    for entry in entries:
        rid = str(entry.get("remote_source_id"))
        kind = str(entry.get("kind"))
        portal_id = str(entry.get("ref_id"))
        remote_path = str(entry.get("remote_path") or "").strip()
        access_mode = str(entry.get("access_mode") or "legacy")
        archived = bool(entry.get("archived"))

        # 幂等：已处理条目跳过
        if access_mode == "site_compatible" or archived:
            continue

        detail: dict[str, Any] = {"remote_source_id": rid, "kind": kind}

        if kind == "storage_profile":
            # 整源访问本就是全放行语义 → site_compatible
            detail["action"] = "site_compatible"
            report["upgraded_site_compatible"] += 1
            if not dry_run:
                _set_access_mode(sources, rid, "site_compatible")
        elif kind == "portal" and not remote_path:
            # 「整源」引用 → 站点兼容开关条目
            detail["action"] = "site_compatible"
            detail["portal_id"] = portal_id
            report["upgraded_site_compatible"] += 1
            if not dry_run:
                _set_access_mode(sources, rid, "site_compatible")
        elif kind == "portal":
            inferred = _infer_dataset(portal_id, remote_path)
            if inferred:
                dataset_key, path_prefix = inferred
                detail["action"] = "grant"
                detail["portal_id"] = portal_id
                detail["dataset_key"] = dataset_key
                detail["path_prefix"] = path_prefix
                report["migrated_to_grants"] += 1
                if not dry_run:
                    grants.upsert(
                        portal_id=portal_id,
                        dataset_key=dataset_key,
                        dataset_title=remote_path,
                        path_prefix=path_prefix,
                        migrated_from=rid,
                    )
                    _set_access_mode(sources, rid, "legacy", archived=True)
            else:
                detail["action"] = "kept_legacy"
                detail["portal_id"] = portal_id
                report["kept_legacy"] += 1
                if safe and not dry_run:
                    # safe 模式：该门户升级整源放行，访问不中断
                    _set_access_mode(sources, rid, "site_compatible")
                    detail["action"] = "site_compatible(safe)"
                    report["kept_legacy"] -= 1
                    report["upgraded_site_compatible"] += 1
        else:
            detail["action"] = "skipped"
        report["details"].append(detail)

    if not dry_run:
        _kv_set(sources, _MIGRATION_KV_KEY, "1")
        logger.info(
            "[RemoteSourceMigration] done: %d grants, %d site_compatible, %d legacy",
            report["migrated_to_grants"],
            report["upgraded_site_compatible"],
            report["kept_legacy"],
        )
    return report


def _kv_sources_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS remote_source_migration_kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def _kv_get(sources, key: str) -> str | None:
    try:
        with sources._connect() as conn:  # noqa: SLF001 — 同模块内部使用
            _kv_sources_table(conn)
            row = conn.execute(
                "SELECT value FROM remote_source_migration_kv WHERE key = ?",
                (key,),
            ).fetchone()
            return str(row[0]) if row else None
    except Exception:  # noqa: BLE001
        return None


def _kv_set(sources, key: str, value: str) -> None:
    with sources._connect() as conn:  # noqa: SLF001
        _kv_sources_table(conn)
        conn.execute(
            "INSERT INTO remote_source_migration_kv (key, value)"
            " VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def _set_access_mode(sources, rid: str, mode: str, *, archived: bool = False) -> None:
    with sources._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE remote_sources SET access_mode = ?, archived = ?, updated_at = ?"
            " WHERE remote_source_id = ?",
            (mode, 1 if archived else 0, datetime.now(UTC).isoformat(), rid),
        )
        conn.commit()
