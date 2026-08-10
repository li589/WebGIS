"""空间数据仓库（独立 spatial.sqlite，承载几何列 + R*Tree 索引）。

与现有 state/metadata DB（workflow_state / api_keys / gee_credentials 等）**完全隔离**：
- 独立 SQLite 文件（``settings.spatialite_db_path``，默认 ``Code/backend/.data/spatial.sqlite``），
  删除即回滚，不影响其他 DB。
- 只对本库调用 ``init_spatial_metadata``（填充 spatial_ref_sys 元数据表），绝不复用到 state DB。

本轮承载 ``overlays(geom POLYGON 4326)`` 表 + ``idx_overlays_geom`` R*Tree 索引，
用于服务端视口相交查询（替代前端 O(N) 浏览器侧过滤）。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from app.services._sqlite_pool import SQLiteConnectionPool
from app.services import spatialite_loader
from app.services.geo_math import overlay_safe_wgs84_bounds

logger = logging.getLogger(__name__)

_repo_lock = threading.Lock()
_repo_singleton: SpatialRepository | None = None
_repo_singleton_path: str | None = None


class SpatialRepository:
    """overlays(geom) 空间表仓库。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        # 懒导入 settings：conftest 测试会 reassign app.core.config.settings，
        # 模块级 import 会绑定到旧对象，故在 __init__ 内取最新值。
        from app.core.config import settings

        self._db_path = Path(db_path or settings.spatialite_db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool = SQLiteConnectionPool(self._db_path)
        self._initialize_schema()

    # ── schema bootstrap（幂等）─────────────────────────────────────────────
    def _initialize_schema(self) -> None:
        """建表 + 几何列 + R*Tree 索引。SpatiaLite 不可用时仅建无几何的基础表。"""
        with self._pool.connection() as conn:
            ok = spatialite_loader.init_spatial_metadata(conn)
            if not ok:
                logger.warning(
                    "SpatiaLite unavailable; overlays table created without geom column "
                    "(spatial queries will fall back to bounds.json)"
                )
            # 1. 基础表（不带 geom 列）
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS overlays (
                    layer_id   TEXT PRIMARY KEY,
                    source     TEXT NOT NULL,
                    name       TEXT,
                    type       TEXT,
                    minzoom    INTEGER,
                    maxzoom    INTEGER,
                    updated_at TEXT NOT NULL
                )
                """
            )
            if not ok:
                return
            # 2. 几何列（幂等：已存在会抛 'already ...'，吞掉）
            try:
                conn.execute(
                    "SELECT AddGeometryColumn('overlays','geom',4326,'POLYGON','XY')"
                )
            except sqlite3.OperationalError as e:
                if "already" not in str(e).lower():
                    raise
            # 3. R*Tree 空间索引
            try:
                conn.execute("SELECT CreateSpatialIndex('overlays','geom')")
            except sqlite3.OperationalError as e:
                if "already" not in str(e).lower():
                    raise

    def _overlay_columns(self, conn: sqlite3.Connection) -> set[str]:
        return {
            row[1] for row in conn.execute("PRAGMA table_info(overlays)").fetchall()
        }

    # ── 写 ───────────────────────────────────────────────────────────────────
    def upsert_overlay_bounds(
        self,
        layer_id: str,
        *,
        source: str,
        name: str | None,
        type_: str | None,
        minzoom: int | None,
        maxzoom: int | None,
        w: float,
        s: float,
        e: float,
        n: float,
    ) -> None:
        """upsert 一条 overlay 边界。

        经纬度先经 ``overlay_safe_wgs84_bounds`` 处理日界线（east 可 > 180，unwrap 约定），
        再构造 WKT POLYGON 用 ``GeomFromText(?, 4326)`` 入库。

        三态写路径（避免缺列 / bindings 崩溃）：
        1. 有 geom 且扩展已加载 → GeomFromText + wkt
        2. 有 geom 未加载 → geom 写 NULL（参数不含 wkt）
        3. 无 geom 列 → 纯属性 upsert
        """
        w2, s2, e2, n2 = overlay_safe_wgs84_bounds(w, s, e, n)
        wkt = f"POLYGON(({w2} {s2},{e2} {s2},{e2} {n2},{w2} {n2},{w2} {s2}))"
        now = datetime.now(UTC).isoformat()
        base_params: tuple[Any, ...] = (
            layer_id,
            source,
            name,
            type_,
            minzoom,
            maxzoom,
            now,
        )
        with self._pool.connection() as conn:
            loaded = spatialite_loader.load_into(conn)
            has_geom = "geom" in self._overlay_columns(conn)
            if not has_geom:
                conn.execute(
                    """
                    INSERT INTO overlays
                        (layer_id, source, name, type, minzoom, maxzoom, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(layer_id) DO UPDATE SET
                        source     = excluded.source,
                        name       = excluded.name,
                        type       = excluded.type,
                        minzoom    = excluded.minzoom,
                        maxzoom    = excluded.maxzoom,
                        updated_at = excluded.updated_at
                    """,
                    base_params,
                )
                return
            if loaded:
                conn.execute(
                    """
                    INSERT INTO overlays
                        (layer_id, source, name, type, minzoom, maxzoom, updated_at, geom)
                    VALUES (?, ?, ?, ?, ?, ?, ?, GeomFromText(?, 4326))
                    ON CONFLICT(layer_id) DO UPDATE SET
                        source     = excluded.source,
                        name       = excluded.name,
                        type       = excluded.type,
                        minzoom    = excluded.minzoom,
                        maxzoom    = excluded.maxzoom,
                        updated_at = excluded.updated_at,
                        geom       = excluded.geom
                    """,
                    (*base_params, wkt),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO overlays
                        (layer_id, source, name, type, minzoom, maxzoom, updated_at, geom)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(layer_id) DO UPDATE SET
                        source     = excluded.source,
                        name       = excluded.name,
                        type       = excluded.type,
                        minzoom    = excluded.minzoom,
                        maxzoom    = excluded.maxzoom,
                        updated_at = excluded.updated_at
                    """,
                    base_params,
                )

    # ── 查 ───────────────────────────────────────────────────────────────────
    def is_spatial_ready(self) -> bool:
        """扩展可用 + geom 列存在 + 表非空且 geom 非空 → 可信任空间查询结果（含空命中）。

        用 ``COUNT(geom)``（非 ``COUNT(*)``）：若 DB 是在扩展不可用时导入（geom 全为
        NULL），则 COUNT(geom)=0 → 返回 False，上层回退 bounds.json，避免「表有行但空间
        查询因 geom 为 NULL 而静默丢结果」的隐患。
        """
        if not spatialite_loader.is_available():
            return False
        with self._pool.connection() as conn:
            if not spatialite_loader.load_into(conn):
                return False
            cols = self._overlay_columns(conn)
            if "geom" not in cols:
                return False
            try:
                row = conn.execute("SELECT COUNT(geom) FROM overlays").fetchone()
            except sqlite3.OperationalError:
                return False
            return bool(row and int(row[0]) > 0)

    def query_intersects(
        self,
        w: float,
        s: float,
        e: float,
        n: float,
        *,
        zoom: int | None = None,
    ) -> list[dict[str, Any]]:
        """视口相交查询。返回 [{"layer_id","minzoom","maxzoom"}]。

        首选空间 DB（``ST_Intersects(geom, BuildMBR(...))`` 走 R*Tree）；扩展不可用、
        geom 列缺失时返回 ``[]``。调用方应先用 ``is_spatial_ready()`` 区分
        「可信空命中」与「需 bounds.json 回退」。
        """
        with self._pool.connection() as conn:
            if not spatialite_loader.is_available():
                return []
            # 容错：geom 列可能因初始化时扩展不可用而未建
            cols = self._overlay_columns(conn)
            if "geom" not in cols:
                return []
            # 视口与存储几何用同一套日界线展开约定（overlay_safe_wgs84_bounds），
            # 保证空间查询与回退路径（bounds.json）在同一空间比较，日界线视口行为一致。
            vw, vs_, ve, vn = overlay_safe_wgs84_bounds(w, s, e, n)
            sql = (
                "SELECT layer_id, minzoom, maxzoom FROM overlays "
                "WHERE ST_Intersects(geom, BuildMBR(?, ?, ?, ?, 4326))"
            )
            params: list[Any] = [vw, vs_, ve, vn]
            if zoom is not None:
                sql += (
                    " AND (? >= minzoom OR minzoom IS NULL)"
                    " AND (? <= maxzoom OR maxzoom IS NULL)"
                )
                params += [zoom, zoom]
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as ex:
                logger.warning("spatial query_intersects failed: %s", ex)
                return []
            return [dict(r) for r in rows]

    def count(self) -> int:
        """overlays 表行数（用于判断是否需要回退到 bounds.json）。"""
        with self._pool.connection() as conn:
            try:
                row = conn.execute("SELECT COUNT(*) FROM overlays").fetchone()
            except sqlite3.OperationalError:
                return 0
            return int(row[0]) if row else 0


def get_spatial_repository(db_path: str | Path | None = None) -> SpatialRepository:
    """懒单例：同路径复用同一仓库（避免每请求新建 pool + schema）。"""
    global _repo_singleton, _repo_singleton_path
    from app.core.config import settings

    path = str(Path(db_path or settings.spatialite_db_path).resolve())
    with _repo_lock:
        if _repo_singleton is not None and _repo_singleton_path == path:
            return _repo_singleton
        _repo_singleton = SpatialRepository(db_path=path)
        _repo_singleton_path = path
        return _repo_singleton


def reset_spatial_repository() -> None:
    """清空单例（仅供测试）。"""
    global _repo_singleton, _repo_singleton_path
    with _repo_lock:
        _repo_singleton = None
        _repo_singleton_path = None
