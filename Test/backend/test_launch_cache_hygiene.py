"""Unit tests for launch.cache_hygiene (no disk wipe of real trees)."""

from __future__ import annotations

import argparse
from unittest.mock import patch

from launch.cache_hygiene import prepare_launch_caches, should_prepare_caches


def _ns(**kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "clean_cache": False,
        "no_clean_cache": False,
        "vite": False,
        "frontend_only": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_no_clean_cache_disables_all() -> None:
    assert should_prepare_caches(_ns(no_clean_cache=True), "all") == (False, False)
    assert should_prepare_caches(_ns(no_clean_cache=True, vite=True), "all") == (
        False,
        False,
    )


def test_explicit_clean_cache_forces_both() -> None:
    assert should_prepare_caches(_ns(clean_cache=True), "docker") == (True, True)
    assert should_prepare_caches(_ns(clean_cache=True, no_clean_cache=True), "all") == (
        False,
        False,
    )


def test_backend_components_pycache_only() -> None:
    for comp in ("all", "backend", "fastapi", "beat", "worker", "worker:weather"):
        assert should_prepare_caches(_ns(), comp) == (True, False)


def test_frontend_and_vite_flags() -> None:
    assert should_prepare_caches(_ns(), "frontend") == (False, True)
    assert should_prepare_caches(_ns(vite=True), "gateway") == (False, True)
    assert should_prepare_caches(_ns(vite=True), "all") == (True, True)
    assert should_prepare_caches(_ns(frontend_only=True), "all") == (False, True)


def test_static_gateway_and_docker_skip() -> None:
    assert should_prepare_caches(_ns(), "gateway") == (False, False)
    assert should_prepare_caches(_ns(), "docker") == (False, False)


def test_leaving_hmr_clears_vite() -> None:
    assert should_prepare_caches(_ns(), "gateway", was_gateway_hmr=True) == (
        False,
        True,
    )
    assert should_prepare_caches(_ns(vite=True), "gateway", was_gateway_hmr=True) == (
        False,
        True,
    )


def test_prepare_launch_caches_noop_when_both_false() -> None:
    with patch("launch.cache_hygiene.shutil.rmtree") as rmtree:
        assert prepare_launch_caches(pycache=False, vite=False) == 0
        rmtree.assert_not_called()


def test_prepare_launch_caches_vite_only_mocked(tmp_path) -> None:
    vite_cache = tmp_path / "node_modules" / ".vite"
    vite_cache.mkdir(parents=True)
    fe_vite = tmp_path / ".vite"
    fe_vite.mkdir()
    with (
        patch("launch.cache_hygiene.VITE_CACHE_DIR", vite_cache),
        patch("launch.cache_hygiene.FRONTEND_DIR", tmp_path),
    ):
        assert prepare_launch_caches(pycache=False, vite=True) == 0
    assert not vite_cache.exists()
    assert not fe_vite.exists()
