"""SpatialRepository 单测（overlays(geom) + R*Tree 相交查询）。

mod_spatialite 不可用时整文件 skip（schema 会退化为无 geom 列，相交测试无意义）。
每测试用独立 spatial.sqlite（tmp_path），并通过 autouse fixture 还原 settings + probe 缓存。
"""

from __future__ import annotations

import pytest

from app.services import spatialite_loader
from app.services.spatial_repository import (
    SpatialRepository,
    reset_spatial_repository,
)


def _fresh_repo(path) -> SpatialRepository:
    """构造仓库前先删除残留 DB。

    本地 safe-delete shim 会拦截 os.remove / rmtree（PermissionError），
    导致 --basetemp 复用时残留 DB 跨 run 污染（geom 列已存在）。故改用
    uuid _suffix 唯一文件名，从根本上避免命中上一次遗留的库；unlink 仅作
    兜底（被 shim 拦截时静默忽略）。与生产逻辑无关。
    """
    import os
    import uuid

    unique = path.parent / f"{path.stem}_{uuid.uuid4().hex}{path.suffix}"
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    return SpatialRepository(db_path=unique)


@pytest.fixture(autouse=True)
def _restore_settings():
    """每个测试后还原 app.core.config.settings（部分测试会 reassign）。"""
    import app.core.config

    saved = app.core.config.settings
    reset_spatial_repository()
    yield
    app.core.config.settings = saved
    spatialite_loader.reset_probe_cache()
    reset_spatial_repository()


@pytest.fixture
def spatial_db(tmp_path, monkeypatch):
    """独立 spatial.sqlite + 强制可用（db_path 显式传入，避免回退到 conftest 共享库）。"""
    monkeypatch.setenv("BACKEND_SPATIALITE_ENABLED", "true")
    import app.core.config

    app.core.config.settings = app.core.config.Settings()
    spatialite_loader.reset_probe_cache()
    reset_spatial_repository()
    if not spatialite_loader.is_available():
        pytest.skip("mod_spatialite not installed; CI apt step may be missing")
    return _fresh_repo(tmp_path / "spatial.sqlite")


def test_schema_bootstrap(spatial_db):
    """geom 列存在 + R*Tree 索引表 idx_overlays_geom 存在。"""
    with spatial_db._pool.connection() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(overlays)").fetchall()}
        assert "geom" in cols
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "idx_overlays_geom" in tables


def test_insert_and_intersect(spatial_db):
    """插入两条不重叠 bbox，视口查命中正确一条。"""
    spatial_db.upsert_overlay_bounds(
        "test-a", source="test", name="A", type_="static",
        minzoom=0, maxzoom=10, w=100, s=20, e=110, n=30,
    )
    spatial_db.upsert_overlay_bounds(
        "test-b", source="test", name="B", type_="static",
        minzoom=0, maxzoom=10, w=-130, s=40, e=-120, n=50,
    )
    hits = spatial_db.query_intersects(105, 25, 108, 28)
    assert [h["layer_id"] for h in hits] == ["test-a"]


def test_antimeridian_polygon(spatial_db):
    """跨日界线：east>180（unwrap 约定）应被正确索引与命中。"""
    spatial_db.upsert_overlay_bounds(
        "am", source="test", name="AM", type_="static",
        minzoom=None, maxzoom=None, w=170, s=0, e=190, n=10,
    )
    # 视口在 175..185 跨日界线
    hits = spatial_db.query_intersects(175, 2, 185, 8)
    assert "am" in [h["layer_id"] for h in hits]


def test_zoom_range_filter(spatial_db):
    """zoom 在 [minzoom, maxzoom] 内命中，超出不命中。"""
    spatial_db.upsert_overlay_bounds(
        "z", source="test", name="Z", type_="static",
        minzoom=3, maxzoom=8, w=0, s=0, e=10, n=10,
    )
    assert [h["layer_id"] for h in spatial_db.query_intersects(1, 1, 2, 2, zoom=5)] == ["z"]
    assert [h["layer_id"] for h in spatial_db.query_intersects(1, 1, 2, 2, zoom=10)] == []


def test_query_returns_empty_when_no_overlap(spatial_db):
    spatial_db.upsert_overlay_bounds(
        "iso", source="test", name="ISO", type_="static",
        minzoom=None, maxzoom=None, w=0, s=0, e=10, n=10,
    )
    assert spatial_db.query_intersects(100, 40, 110, 50) == []


def test_intersect_empty_hits_trusts_spatialite(spatial_db):
    """表有资料但视口无交集：is_spatial_ready 仍 True，空命中应被信任（不回退）。"""
    spatial_db.upsert_overlay_bounds(
        "iso", source="test", name="ISO", type_="static",
        minzoom=None, maxzoom=None, w=0, s=0, e=10, n=10,
    )
    assert spatial_db.is_spatial_ready() is True
    assert spatial_db.query_intersects(100, 40, 110, 50) == []


def test_is_spatial_ready_false_when_empty(spatial_db):
    """表空时 is_spatial_ready False（上层应走 bounds.json 回退）。"""
    assert spatial_db.count() == 0
    assert spatial_db.is_spatial_ready() is False


def test_fallback_when_disabled_no_geom(tmp_path, monkeypatch):
    """enabled=false 时 bootstrap 不建 geom 列 → query_intersects 返回 []（触发上层回退）。"""
    monkeypatch.setenv("BACKEND_SPATIALITE_ENABLED", "false")
    import app.core.config

    app.core.config.settings = app.core.config.Settings()
    spatialite_loader.reset_probe_cache()
    reset_spatial_repository()
    repo = _fresh_repo(tmp_path / "sp.sqlite")
    with repo._pool.connection() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(overlays)").fetchall()}
        assert "geom" not in cols
    assert repo.query_intersects(0, 0, 10, 10) == []
    assert repo.is_spatial_ready() is False


def test_upsert_without_geom_column(tmp_path, monkeypatch):
    """无 geom 列时纯属性 upsert 不崩，且 count 增加。"""
    monkeypatch.setenv("BACKEND_SPATIALITE_ENABLED", "false")
    import app.core.config

    app.core.config.settings = app.core.config.Settings()
    spatialite_loader.reset_probe_cache()
    reset_spatial_repository()
    repo = _fresh_repo(tmp_path / "sp_attr.sqlite")
    repo.upsert_overlay_bounds(
        "attr-only", source="test", name="A", type_="static",
        minzoom=None, maxzoom=None, w=0, s=0, e=10, n=10,
    )
    assert repo.count() == 1
    # 再次 upsert（ON CONFLICT 更新）也不崩
    repo.upsert_overlay_bounds(
        "attr-only", source="test", name="A2", type_="static",
        minzoom=1, maxzoom=5, w=1, s=1, e=9, n=9,
    )
    assert repo.count() == 1


def test_upsert_bindings_when_not_loaded(tmp_path, monkeypatch):
    """有 geom 列但 load_into 返回 False 时，NULL 写入且参数不含多余 wkt。"""
    monkeypatch.setenv("BACKEND_SPATIALITE_ENABLED", "true")
    import app.core.config

    app.core.config.settings = app.core.config.Settings()
    spatialite_loader.reset_probe_cache()
    reset_spatial_repository()
    if not spatialite_loader.is_available():
        pytest.skip("mod_spatialite not installed; need geom column for this case")

    repo = _fresh_repo(tmp_path / "sp_null.sqlite")
    monkeypatch.setattr(spatialite_loader, "load_into", lambda _conn: False)
    repo.upsert_overlay_bounds(
        "null-geom", source="test", name="N", type_="static",
        minzoom=None, maxzoom=None, w=0, s=0, e=5, n=5,
    )
    assert repo.count() == 1
