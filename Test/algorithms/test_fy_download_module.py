"""fy_download 模块：日期范围多日循环与逐日源回退。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import contracts.job  # noqa: F401  # break modules.registry ↔ workflow.panel_schema cycle


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def put(self, artifact, payload=None) -> object:
        self.items[artifact.artifact_id] = payload
        return artifact


def _ctx(workspace: Path):
    from workflow.schemas import NodeExecutionContext

    request = SimpleNamespace(
        job_id="job-fy-1",
        datasource_selection={},
        region=None,
        time_range=None,
    )
    runtime = SimpleNamespace(run_id="run-fy-1", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
    )


class TestIterDateRange(unittest.TestCase):
    def test_single_day_without_end(self) -> None:
        from modules.fy_download import _iter_date_range

        self.assertEqual(_iter_date_range("2025-12-01", ""), ["2025-12-01"])

    def test_multi_day_inclusive(self) -> None:
        from modules.fy_download import _iter_date_range

        days = _iter_date_range("2025-12-30", "2026-01-02")
        self.assertEqual(
            days, ["2025-12-30", "2025-12-31", "2026-01-01", "2026-01-02"]
        )

    def test_dot_format_accepted(self) -> None:
        from modules.fy_download import _iter_date_range

        self.assertEqual(_iter_date_range("2025.12.01", "2025.12.03")[0], "2025-12-01")
        self.assertEqual(len(_iter_date_range("2025.12.01", "2025.12.03")), 3)

    def test_compact_yyyymmdd_accepted(self) -> None:
        """种子 {YYYYMMDD} 占位符展开后为紧凑格式（在线 run 回归）。"""
        from modules.fy_download import _iter_date_range

        self.assertEqual(
            _iter_date_range("20251227", "20251231"),
            ["2025-12-27", "2025-12-28", "2025-12-29", "2025-12-30", "2025-12-31"],
        )
        self.assertEqual(_iter_date_range("20251227", ""), ["2025-12-27"])

    def test_end_before_start_raises(self) -> None:
        from modules.fy_download import _iter_date_range

        with self.assertRaises(ValueError):
            _iter_date_range("2026-01-02", "2026-01-01")

    def test_range_cap_enforced(self) -> None:
        from modules.fy_download import _iter_date_range

        with self.assertRaises(ValueError):
            _iter_date_range("2020-01-01", "2026-01-01")

    def test_empty_start_returns_empty(self) -> None:
        from modules.fy_download import _iter_date_range

        self.assertEqual(_iter_date_range("", ""), [])


class TestFYDownloadExecute(unittest.TestCase):
    def _run(self, tmp: str, *, params: dict, side_effects=None):
        from modules.fy_download import FYDownloadModule

        workspace = Path(tmp) / "ws"
        workspace.mkdir()
        ctx = _ctx(workspace)
        module = FYDownloadModule()
        with patch(
            "modules.fy_download._download_from_nsmc",
            side_effect=(side_effects or {}).get("nsmc"),
        ) as nsmc, patch(
            "modules.fy_download._fetch_from_nas",
            side_effect=(side_effects or {}).get("nas"),
        ) as nas:
            out = module.execute(inputs={}, params=params, ctx=ctx)
        manifest = next(iter(ctx.artifact_store.items.values()))
        return out, manifest.extra, nsmc, nas

    def test_multi_day_downloads_each_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out, extra, nsmc, _ = self._run(
                tmp,
                params={
                    "start_date": "2025-12-01",
                    "end_date": "2025-12-03",
                    "data_source": "nsmc",
                },
            )
            self.assertEqual(nsmc.call_count, 3)
            date_paths = [str(c.kwargs.get("date_path")) for c in nsmc.call_args_list]
            self.assertEqual(
                date_paths, ["2025.12.01", "2025.12.02", "2025.12.03"]
            )
            self.assertEqual(extra["day_count"], 3)
            self.assertEqual(
                extra["dates"],
                ["2025-12-01", "2025-12-02", "2025-12-03"],
            )
            self.assertTrue(Path(out["path"]).is_dir())

    def test_auto_falls_back_per_day(self) -> None:
        calls = {"nsmc": 0, "nas": 0}

        def _nsmc(ctx, **kwargs):
            calls["nsmc"] += 1
            if kwargs.get("date_path") == "2025.12.02":
                raise RuntimeError("nsmc down")
            return Path(kwargs["target_dir"])

        def _nas(ctx, **kwargs):
            calls["nas"] += 1
            return Path(kwargs["target_dir"])

        with tempfile.TemporaryDirectory() as tmp:
            _, extra, _, _ = self._run(
                tmp,
                params={
                    "start_date": "2025-12-01",
                    "end_date": "2025-12-03",
                    "data_source": "auto",
                },
                side_effects={"nsmc": _nsmc, "nas": _nas},
            )
            self.assertEqual(calls, {"nsmc": 3, "nas": 1})
            self.assertEqual(extra["data_source"], "nsmc+nas")

    def test_all_sources_failed_for_day_raises(self) -> None:
        def _boom(ctx, **kwargs):
            raise RuntimeError("network unreachable")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as cm:
                self._run(
                    tmp,
                    params={
                        "start_date": "2025-12-01",
                        "end_date": "2025-12-02",
                        "data_source": "auto",
                    },
                    side_effects={"nsmc": _boom, "nas": _boom},
                )
            msg = str(cm.exception)
            self.assertIn("2025-12-01", msg)
            self.assertIn("network unreachable", msg)

    def test_missing_start_date_raises(self) -> None:
        from modules.fy_download import FYDownloadModule

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaises(ValueError):
                FYDownloadModule().execute(
                    inputs={}, params={}, ctx=_ctx(workspace)
                )


class TestNSMCAccountRotation(unittest.TestCase):
    def setUp(self) -> None:
        from modules.fy_download import _account_cooldown_until

        _account_cooldown_until.clear()

    def _ds(self, accounts: list[dict]) -> dict:
        return {
            "portal_credentials": {
                "nsmc": {"enabled": True, "accounts": accounts}
            }
        }

    def _fake_source(self, behavior: dict[str, Exception | None]):
        calls: list[dict] = []

        class _Fake:
            def locate(self, url, metadata=None):
                headers = dict((metadata or {}).get("http_headers") or {})
                calls.append(headers)
                return SimpleNamespace(url=url)

            def materialize(self, resource, target_dir=None):
                token = calls[-1].get("token", "")
                action = behavior.get(token, None)
                if isinstance(action, Exception):
                    raise action
                return SimpleNamespace(uri=f"file://{target_dir}/a.hdf")

        return _Fake(), calls

    def test_accounts_extraction_prefers_list_and_falls_back_single(self) -> None:
        from modules.fy_download import _nsmc_accounts

        listed = _nsmc_accounts(
            {
                "accounts": [
                    {"username": "u1", "token": "t1"},
                    {"username": "u2", "password": "p2"},
                    {"username": "empty"},
                    "junk",
                ],
                "token": "legacy-token",
            }
        )
        self.assertEqual(
            listed,
            [
                {"username": "u1", "token": "t1", "password": ""},
                {"username": "u2", "token": "", "password": "p2"},
            ],
        )
        single = _nsmc_accounts({"token": "legacy-token"})
        self.assertEqual(
            single, [{"username": "", "token": "legacy-token", "password": ""}]
        )

    def test_rotation_skips_limited_account_and_uses_next(self) -> None:
        import modules.fy_download as fy

        behavior = {
            "tA": ConnectionError(
                "HTTP materialize failed (transient) for http://x: "
                "HTTP Error 429: Too Many Requests"
            ),
            "tB": None,
        }
        fake, calls = self._fake_source(behavior)
        accounts = [
            {"username": "a@x", "token": "tA"},
            {"username": "b@x", "token": "tB"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch(
                "data_access.sources.http.HttpSource", return_value=fake
            ):
                out = fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2026.08.01",
                    ds=self._ds(accounts),
                    target_dir=Path(tmp) / "out",
                )
            self.assertTrue(str(out).endswith("a.hdf"))
        # tA 先试（429）→ 冷却，tB 接管
        self.assertEqual([c.get("token") for c in calls], ["tA", "tB"])
        self.assertIn("tA", fy._account_cooldown_until)

        # 第二次：tA 冷却中直接跳过，仅 tB 被调用
        fake2, calls2 = self._fake_source({"tA": None, "tB": None})
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch(
                "data_access.sources.http.HttpSource", return_value=fake2
            ):
                fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2026.08.02",
                    ds=self._ds(accounts),
                    target_dir=Path(tmp) / "out",
                )
        self.assertEqual([c.get("token") for c in calls2], ["tB"])

    def test_all_accounts_limited_raises_diagnostic(self) -> None:
        import modules.fy_download as fy

        limited = ConnectionError(
            "HTTP materialize failed (transient) for http://x: HTTP Error 429"
        )
        fake, calls = self._fake_source({"tA": limited, "tB": limited})
        accounts = [
            {"username": "a@x", "token": "tA"},
            {"username": "b@x", "token": "tB"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch(
                "data_access.sources.http.HttpSource", return_value=fake
            ):
                with self.assertRaises(RuntimeError) as cm:
                    fy._download_from_nsmc(
                        _ctx(workspace),
                        satellite="FY3D",
                        date_path="2026.08.03",
                        ds=self._ds(accounts),
                        target_dir=Path(tmp) / "out",
                    )
        self.assertIn("all accounts exhausted", str(cm.exception))
        self.assertEqual(len(calls), 2)

    def test_non_limit_error_propagates_without_cooldown(self) -> None:
        import modules.fy_download as fy

        fatal = ValueError("HTTP materialize failed for http://x: HTTP Error 404")
        fake, _ = self._fake_source({"tA": fatal})
        accounts = [{"username": "a@x", "token": "tA"}]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch(
                "data_access.sources.http.HttpSource", return_value=fake
            ):
                with self.assertRaises(ValueError):
                    fy._download_from_nsmc(
                        _ctx(workspace),
                        satellite="FY3D",
                        date_path="2026.08.04",
                        ds=self._ds(accounts),
                        target_dir=Path(tmp) / "out",
                    )
        self.assertEqual(fy._account_cooldown_until, {})

    def test_token_header_from_entry_is_honored(self) -> None:
        import modules.fy_download as fy

        fake, calls = self._fake_source({"tA": None})
        ds = self._ds([{"username": "a@x", "token": "tA"}])
        ds["portal_credentials"]["nsmc"]["token_header"] = "Authorization"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch(
                "data_access.sources.http.HttpSource", return_value=fake
            ):
                fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2026.08.05",
                    ds=ds,
                    target_dir=Path(tmp) / "out",
                )
        # _fake_source 的行为表按 "token" 头取值；此处改头后取空 → 默认 None → 成功
        self.assertEqual(calls, [{"Authorization": "tA"}])


class TestFetchFromNasFileBrowser(unittest.TestCase):
    """NAS 回退：FileBrowser 直连下载（凭据协议匹配 + 已知文件名免列举）。"""

    def _server(self):
        return SimpleNamespace(
            server_type="nas",
            host="",
            port=0,
            username="user",
            password="pwd",
            filebrowser_url="https://nas.example.org",
        )

    def test_fy3b_rejected_with_clear_error(self) -> None:
        from modules.fy_download import _fetch_from_nas

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaises(ValueError) as cm:
                _fetch_from_nas(
                    _ctx(workspace),
                    satellite="FY3B",
                    date_path="2025.12.27",
                    ds={},
                    target_dir=Path(tmp) / "out",
                )
            self.assertIn("FY3D", str(cm.exception))

    def test_fy3d_direct_download_and_idempotent_skip(self) -> None:
        import modules.fy_download as fy

        downloads: list[str] = []

        def _fake_download(url, token, remote_path, local_path, remote_size=0,
                           resume_offset=0, progress_callback=None):
            downloads.append(remote_path)
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            Path(local_path).write_bytes(b"tif-bytes")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            target = Path(tmp) / "out"
            with patch(
                "modules.download_nodes._resolve_profile_server_config",
                return_value=self._server(),
            ), patch(
                "ingest.remote_sync.filebrowser_login", return_value="tok"
            ), patch(
                "ingest.remote_sync._filebrowser_download",
                side_effect=_fake_download,
            ):
                out = fy._fetch_from_nas(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2025.12.27",
                    ds={},
                    target_dir=target,
                )
                self.assertEqual(
                    out, target / "FY3D_GBAL_L1_10H_20251227_MWRID_0.tif"
                )
                # 已存在且非空 → 跳过重复下载
                fy._fetch_from_nas(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2025.12.27",
                    ds={},
                    target_dir=target,
                )
        self.assertEqual(downloads, [
            "/Chenhaojun/Data/fy3dhdf2425/FY3D_GBAL_L1_10V_20251227_MWRID_0.tif",
            "/Chenhaojun/Data/fy3dhdf2425/FY3D_GBAL_L1_10H_20251227_MWRID_0.tif",
        ])

    def test_remote_dir_override_via_ds(self) -> None:
        import modules.fy_download as fy

        seen: dict[str, object] = {}

        def _fake_download(url, token, remote_path, local_path, remote_size=0,
                           resume_offset=0, progress_callback=None):
            seen["remote"] = remote_path
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            Path(local_path).write_bytes(b"x")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch(
                "modules.download_nodes._resolve_profile_server_config",
                return_value=self._server(),
            ), patch(
                "ingest.remote_sync.filebrowser_login", return_value="tok"
            ), patch(
                "ingest.remote_sync._filebrowser_download",
                side_effect=_fake_download,
            ):
                fy._fetch_from_nas(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2026.01.05",
                    ds={"nas_remote_path": "/alt/fy"},
                    target_dir=Path(tmp) / "out",
                )
        self.assertTrue(
            str(seen["remote"]).startswith("/alt/fy/FY3D_GBAL_L1_10"),
            msg=f"unexpected remote: {seen['remote']}",
        )


if __name__ == "__main__":
    unittest.main()
