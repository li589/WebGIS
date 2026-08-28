"""Unit tests for launch.gateway_manager helpers (no Docker required for most)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from launch.constants import VITE_BEHIND_GATEWAY_PORT
from launch.gateway_manager import (
    GATEWAY_CONTAINER,
    GATEWAY_PORT,
    gateway_compose_file,
    gateway_hmr_compose_file,
    reload_gateway_nginx,
)


def test_gateway_paths_exist() -> None:
    assert gateway_compose_file().name == "docker-compose.yml"
    assert gateway_hmr_compose_file().name == "docker-compose.hmr.yml"
    assert gateway_compose_file().is_file()
    assert gateway_hmr_compose_file().is_file()
    assert (gateway_compose_file().parent / "nginx.hmr.conf").is_file()
    assert GATEWAY_PORT == 5175
    assert VITE_BEHIND_GATEWAY_PORT == 5174


def test_reload_gateway_nginx_when_not_running() -> None:
    with patch("launch.gateway_manager.gateway_running", return_value=False):
        assert reload_gateway_nginx() is False


def test_reload_gateway_nginx_success() -> None:
    ok_run = MagicMock(returncode=0, stdout="", stderr="nginx: configuration file ok\n")

    with (
        patch("launch.gateway_manager.gateway_running", return_value=True),
        patch("launch.gateway_manager.gateway_hmr_active", return_value=False),
        patch("launch.gateway_manager.subprocess.run", return_value=ok_run) as run,
    ):
        assert reload_gateway_nginx() is True
        assert run.call_count == 2
        assert run.call_args_list[0].args[0][:4] == [
            "docker",
            "exec",
            GATEWAY_CONTAINER,
            "nginx",
        ]
        assert run.call_args_list[1].args[0] == [
            "docker",
            "exec",
            GATEWAY_CONTAINER,
            "nginx",
            "-s",
            "reload",
        ]


def test_reload_gateway_nginx_test_fail() -> None:
    bad = MagicMock(returncode=1, stdout="", stderr="nginx: [emerg] unexpected")
    with (
        patch("launch.gateway_manager.gateway_running", return_value=True),
        patch("launch.gateway_manager.subprocess.run", return_value=bad),
    ):
        assert reload_gateway_nginx() is False
