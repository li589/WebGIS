"""硬编码清理 2026-08-20 A2/A4：SSH 工厂缺参抛错 + NSIDC 兜底目录 fail-fast。"""

from __future__ import annotations

import pytest


class TestSshFactoryRequiresExplicitArgs:
    """A2：for_hpc_tunnel/for_hpc_direct/for_win11 缺参抛 ValueError（实验室默认值已移除）。"""

    def test_hpc_tunnel_requires_host_and_username(self):
        from ingest.remote_sync import ServerConfig

        with pytest.raises(ValueError, match="for_hpc_tunnel"):
            ServerConfig.for_hpc_tunnel(host="", port=2222, username="u")
        with pytest.raises(ValueError, match="for_hpc_tunnel"):
            ServerConfig.for_hpc_tunnel(host="127.0.0.1", port=2222, username="")

    def test_hpc_direct_requires_host_and_username(self):
        from ingest.remote_sync import ServerConfig

        with pytest.raises(ValueError, match="for_hpc_direct"):
            ServerConfig.for_hpc_direct(host="", port=22, username="u")

    def test_win11_requires_alias_and_username(self):
        from ingest.remote_sync import ServerConfig

        with pytest.raises(ValueError, match="for_win11"):
            ServerConfig.for_win11(ssh_alias="", username="u")
        with pytest.raises(ValueError, match="for_win11"):
            ServerConfig.for_win11(ssh_alias="alias", username="")

    def test_explicit_args_still_work(self):
        from ingest.remote_sync import ServerConfig

        cfg = ServerConfig.for_hpc_direct(
            host="hpc.example.edu", port=22, username="alice"
        )
        assert cfg.host == "hpc.example.edu"
        assert cfg.username == "alice"
        assert cfg.server_type == "hpc"

    def test_no_lab_defaults_remain_in_source(self):
        """源码不再包含实验室账号/内网 IP 兜底默认值。"""
        from pathlib import Path

        src = (
            Path(__file__)
            .resolve()
            .parents[2]
            .joinpath(
                "Code", "algorithms", "providers", "Python", "ingest", "remote_sync.py"
            )
            .read_text(encoding="utf-8")
        )
        assert "likr6008" not in src
        assert "qiujianqiu" not in src
        assert "172.16.98.184" not in src
        assert '"win11-lab"' not in src


class TestNsicFallbackDirFailFast:
    """A4：BACKEND_DATA_ROOT 未设时独立运行兜底目录 fail-fast（禁止静默回退盘符）。"""

    def test_missing_env_raises_runtime_error(self, monkeypatch):
        from ingest import nsidc_download as nd

        monkeypatch.delenv("BACKEND_DATA_ROOT", raising=False)
        with pytest.raises(RuntimeError, match="BACKEND_DATA_ROOT"):
            nd._default_output_dir()

    def test_env_set_yields_path(self, monkeypatch, tmp_path):
        from ingest import nsidc_download as nd

        monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path))
        out = nd._default_output_dir()
        assert str(out).startswith(str(tmp_path))
        assert "Soil_Moisture" in str(out)

    def test_no_i_drive_default_in_module(self):
        """模块内不再有静默回退 I 盘的字面量默认。"""
        from pathlib import Path

        src = (
            Path(__file__)
            .resolve()
            .parents[2]
            .joinpath(
                "Code",
                "algorithms",
                "providers",
                "Python",
                "ingest",
                "nsidc_download.py",
            )
            .read_text(encoding="utf-8")
        )
        assert 'os.getenv("BACKEND_DATA_ROOT", r"I:' not in src
