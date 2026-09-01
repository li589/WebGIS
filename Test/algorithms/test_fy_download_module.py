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
        self.assertEqual(days, ["2025-12-30", "2025-12-31", "2026-01-01", "2026-01-02"])

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
        with (
            patch(
                "modules.fy_download._download_from_nsmc",
                side_effect=(side_effects or {}).get("nsmc"),
            ) as nsmc,
            patch(
                "modules.fy_download._fetch_from_nas",
                side_effect=(side_effects or {}).get("nas"),
            ) as nas,
        ):
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
            self.assertEqual(date_paths, ["2025.12.01", "2025.12.02", "2025.12.03"])
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
                FYDownloadModule().execute(inputs={}, params={}, ctx=_ctx(workspace))


class TestNSMCAccountRotation(unittest.TestCase):
    """NSMC 新门户链路（ingest/nsmc_portal.py）：账号轮换与限额冷却。

    2026-08-20 重写：旧 HttpSource 直链方案已废弃（404），新链路为
    NsmcPortalClient（RSA 登录 + subfile 检索 + POST 表单直下）。
    """

    def setUp(self) -> None:
        from modules.fy_download import _account_cooldown_until

        _account_cooldown_until.clear()

    def _ds(self, accounts: list[dict]) -> dict:
        return {"portal_credentials": {"nsmc": {"enabled": True, "accounts": accounts}}}

    def _fake_client(self, behavior: dict[str, str | Exception], *, datasize: int | None = None):
        """按 username 分派行为：'ok'（成功下载 2 文件）或异常。"""
        calls: list[dict] = []

        def _write_mini_hdf(dest: Path) -> int:
            import h5py
            import numpy as np

            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            with h5py.File(dest, "w") as handle:
                handle.create_dataset("probe", data=np.asarray([1], dtype="i4"))
            return dest.stat().st_size

        class _FakeClient:
            def __init__(
                self,
                *,
                session_file=None,
                username="",
                password="",
                download_interval=0.0,
                **kw,
            ):
                self.username = username
                self.download_interval = download_interval

            def ensure_session(self):
                calls.append({"username": self.username, "phase": "ensure"})

            def search_daily_files(self, template, day, max_files=100):
                calls.append(
                    {
                        "username": self.username,
                        "phase": "search",
                        "template": template,
                        "day": day,
                    }
                )
                action = behavior.get(self.username)
                if isinstance(action, Exception):
                    raise action
                # 预写一次以得到稳定 DATASIZE（与 download 内容一致）
                size = datasize
                if size is None:
                    with tempfile.TemporaryDirectory() as probe_tmp:
                        size = _write_mini_hdf(Path(probe_tmp) / "probe.HDF")
                return [
                    {
                        "ARCHIVENAME": f"FY3D_MWRID_GBAL_L1_{day.replace('-', '')}_"
                        f"0100_{i}_010KM_MS.HDF",
                        "CNETERFLAG": "1",
                        "DATASIZE": size,
                    }
                    for i in range(3)
                ]

            def download_file(self, filename, dest, center_flag="1"):
                calls.append(
                    {
                        "username": self.username,
                        "phase": "download",
                        "filename": filename,
                    }
                )
                action = behavior.get(self.username)
                if isinstance(action, Exception):
                    raise action
                _write_mini_hdf(Path(dest))
                return Path(dest)

        return _FakeClient, calls

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

    def test_nsmc_online_downloads_capped_files(self) -> None:
        """max_files_per_day 生效：检索 3 个文件但只下载前 2 个。"""
        import modules.fy_download as fy

        fake_cls, calls = self._fake_client({"a@x": "ok"})
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch("ingest.nsmc_portal.NsmcPortalClient", fake_cls):
                fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2026.08.01",
                    ds=self._ds([{"username": "a@x", "password": "p"}]),
                    target_dir=Path(tmp) / "out",
                    orbit_mode="MWRID",
                    max_files_per_day=2,
                )
        downloads = [c for c in calls if c["phase"] == "download"]
        self.assertEqual(len(downloads), 2)
        search = [c for c in calls if c["phase"] == "search"][0]
        self.assertEqual(
            search["template"], "FY3D_MWRID_GBAL_L1_YYYYMMDD_HHmm_010KM_MS.HDF"
        )

    def test_rotation_skips_limited_account_and_uses_next(self) -> None:
        import modules.fy_download as fy
        from ingest.nsmc_portal import NsmcDownloadError

        # 账号 A 检索即遇 429；账号 B 正常
        behavior = {
            "a@x": NsmcDownloadError("NSMC HTTP 429: rate limited"),
            "b@x": "ok",
        }
        fake_cls, calls = self._fake_client(behavior)
        accounts = [
            {"username": "a@x", "password": "pA"},
            {"username": "b@x", "password": "pB"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch("ingest.nsmc_portal.NsmcPortalClient", fake_cls):
                fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2026.08.01",
                    ds=self._ds(accounts),
                    target_dir=Path(tmp) / "out",
                )
        ensured = [c["username"] for c in calls if c["phase"] == "ensure"]
        self.assertEqual(ensured, ["a@x", "b@x"])
        self.assertIn("a@x", fy._account_cooldown_until)

        # 第二次：A 冷却中直接跳过，仅 B 被调用
        fake_cls2, calls2 = self._fake_client({"a@x": "ok", "b@x": "ok"})
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch("ingest.nsmc_portal.NsmcPortalClient", fake_cls2):
                fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2026.08.02",
                    ds=self._ds(accounts),
                    target_dir=Path(tmp) / "out",
                )
        ensured2 = [c["username"] for c in calls2 if c["phase"] == "ensure"]
        self.assertEqual(ensured2, ["b@x"])

    def test_all_accounts_limited_raises_diagnostic(self) -> None:
        import modules.fy_download as fy
        from ingest.nsmc_portal import NsmcDownloadError

        behavior = {
            "a@x": NsmcDownloadError("NSMC HTTP 429: rate limited"),
            "b@x": NsmcDownloadError("您下载频率过于频繁，请稍后再尝试下载"),
        }
        fake_cls, calls = self._fake_client(behavior)
        accounts = [
            {"username": "a@x", "password": "pA"},
            {"username": "b@x", "password": "pB"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch("ingest.nsmc_portal.NsmcPortalClient", fake_cls):
                with self.assertRaises(RuntimeError) as cm:
                    fy._download_from_nsmc(
                        _ctx(workspace),
                        satellite="FY3D",
                        date_path="2026.08.03",
                        ds=self._ds(accounts),
                        target_dir=Path(tmp) / "out",
                    )
        self.assertIn("all accounts exhausted", str(cm.exception))
        self.assertEqual(len([c for c in calls if c["phase"] == "ensure"]), 2)

    def test_non_limit_error_propagates_without_cooldown(self) -> None:
        import modules.fy_download as fy
        from ingest.nsmc_portal import NsmcDownloadError

        fatal = NsmcDownloadError("NSMC HTTP 500: server error")
        fake_cls, _ = self._fake_client({"a@x": fatal})
        accounts = [{"username": "a@x", "password": "p"}]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch("ingest.nsmc_portal.NsmcPortalClient", fake_cls):
                with self.assertRaises(NsmcDownloadError):
                    fy._download_from_nsmc(
                        _ctx(workspace),
                        satellite="FY3D",
                        date_path="2026.08.04",
                        ds=self._ds(accounts),
                        target_dir=Path(tmp) / "out",
                    )
        self.assertEqual(fy._account_cooldown_until, {})

    def test_fy3f_orba_template_selected(self) -> None:
        """FY3F ORBA 走 FY3F_MWRI-_ORBA_L1 模板（含连字符命名）。"""
        import modules.fy_download as fy

        fake_cls, calls = self._fake_client({"a@x": "ok"})
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch("ingest.nsmc_portal.NsmcPortalClient", fake_cls):
                fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3F",
                    date_path="2026.01.10",
                    ds=self._ds([{"username": "a@x", "password": "p"}]),
                    target_dir=Path(tmp) / "out",
                    orbit_mode="ORBA",
                )
        search = [c for c in calls if c["phase"] == "search"][0]
        self.assertEqual(
            search["template"], "FY3F_MWRI-_ORBA_L1_YYYYMMDD_HHmm_010KM_Vn.HDF"
        )
        self.assertEqual(search["day"], "2026-01-10")

    def test_unsupported_combo_rejected(self) -> None:
        import modules.fy_download as fy

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaises(ValueError) as cm:
                fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3B",
                    date_path="2026.08.05",
                    ds=self._ds([{"username": "a@x", "password": "p"}]),
                    target_dir=Path(tmp) / "out",
                    orbit_mode="MWRID",
                )
        self.assertIn("FY3B/MWRID", str(cm.exception))

    def test_captcha_required_maps_to_preheat_hint(self) -> None:
        """验证码缺失 → 可诊断 ValueError（指引 probe 预热）。"""
        import modules.fy_download as fy
        from ingest.nsmc_portal import NsmcCaptchaRequired

        class _NoCaptchaClient:
            def __init__(self, **kw):
                pass

            def ensure_session(self):
                raise NsmcCaptchaRequired("无 ddddocr")

            def search_daily_files(self, *a, **kw):
                raise AssertionError("不应到达检索")

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with patch("ingest.nsmc_portal.NsmcPortalClient", _NoCaptchaClient):
                with self.assertRaises(ValueError) as cm:
                    fy._download_from_nsmc(
                        _ctx(workspace),
                        satellite="FY3D",
                        date_path="2026.08.06",
                        ds=self._ds([{"username": "a@x", "password": "p"}]),
                        target_dir=Path(tmp) / "out",
                    )
        self.assertIn("nsmc_online_probe", str(cm.exception))

    def test_no_credentials_raises(self) -> None:
        import modules.fy_download as fy

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaises(Exception):
                fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2026.08.07",
                    ds={},
                    target_dir=Path(tmp) / "out",
                )

    def test_incomplete_local_hdf_is_redownloaded(self) -> None:
        """本地半截/假 HDF 不跳过：删掉后重新下载。"""
        import modules.fy_download as fy

        fake_cls, calls = self._fake_client({"a@x": "ok"})
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            out = Path(tmp) / "out"
            out.mkdir()
            # 与检索命名一致的第一文件写半截内容
            broken = out / "FY3D_MWRID_GBAL_L1_20260801_0100_0_010KM_MS.HDF"
            broken.write_bytes(b"NOT-A-REAL-HDF")
            with patch("ingest.nsmc_portal.NsmcPortalClient", fake_cls):
                fy._download_from_nsmc(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2026.08.01",
                    ds=self._ds([{"username": "a@x", "password": "p"}]),
                    target_dir=out,
                    max_files_per_day=2,
                )
            self.assertTrue(broken.exists())
            self.assertGreater(broken.stat().st_size, 20)
            from modules.fy_download import _hdf_file_readable

            self.assertTrue(_hdf_file_readable(broken))
        downloads = [c for c in calls if c["phase"] == "download"]
        self.assertEqual(len(downloads), 2)

    def test_size_mismatch_forces_redownload(self) -> None:
        """DATASIZE 不一致的本地文件视为不完整。"""
        import h5py
        import numpy as np

        import modules.fy_download as fy

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            out = Path(tmp) / "out"
            out.mkdir()
            name = "FY3D_MWRID_GBAL_L1_20260802_0100_0_010KM_MS.HDF"
            local = out / name
            with h5py.File(local, "w") as handle:
                handle.create_dataset("probe", data=np.asarray([1], dtype="i4"))
            wrong_size = local.stat().st_size + 999

            fake_cls, calls = self._fake_client({"a@x": "ok"}, datasize=wrong_size)
            # 覆盖 search：强制 DATASIZE=wrong_size，download 写出真实 mini hdf
            # _fake_client 已把 DATASIZE 设为 wrong_size，但 download 写的是 mini
            # → 下载后校验也会失败。改为：download 写出恰好 wrong_size 的合法 hdf 不可能；
            # 因此本测只验证「跳过前因 size mismatch 进入 download」。
            with patch("ingest.nsmc_portal.NsmcPortalClient", fake_cls):
                with self.assertRaises(Exception) as cm:
                    fy._download_from_nsmc(
                        _ctx(workspace),
                        satellite="FY3D",
                        date_path="2026.08.02",
                        ds=self._ds([{"username": "a@x", "password": "p"}]),
                        target_dir=out,
                        max_files_per_day=1,
                    )
            # 必须至少尝试过 download（说明没有因本地存在而跳过）
            self.assertTrue(any(c["phase"] == "download" for c in calls))
            self.assertIn("校验失败", str(cm.exception))


class TestLocalDownloadOkHelpers(unittest.TestCase):
    def test_coerce_byte_count_units(self) -> None:
        from modules.fy_download import _coerce_byte_count

        self.assertEqual(_coerce_byte_count(1024), 1024)
        self.assertEqual(_coerce_byte_count("2 KB"), 2048)
        self.assertEqual(_coerce_byte_count("1.5 MB"), int(1.5 * 1024**2))
        self.assertIsNone(_coerce_byte_count(""))
        self.assertIsNone(_coerce_byte_count(0))

    def test_local_ok_requires_hdf_readable(self) -> None:
        import h5py
        import numpy as np

        from modules.fy_download import _local_download_ok

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "a.HDF"
            bad.write_bytes(b"junk")
            self.assertFalse(_local_download_ok(bad))
            good = Path(tmp) / "b.HDF"
            with h5py.File(good, "w") as handle:
                handle.create_dataset("probe", data=np.asarray([1], dtype="i4"))
            self.assertTrue(_local_download_ok(good))
            self.assertFalse(_local_download_ok(good, expected_bytes=good.stat().st_size + 1))

    def test_hdf_readable_probes_mwri_bt_without_flat(self) -> None:
        """真实 FY 亮温 Dataset 无 ``.flat``；探测不得抛 AttributeError。"""
        import h5py
        import numpy as np

        from modules.fy_download import _hdf_file_readable, _local_download_ok

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "FY3D_MWRID_GBAL_L1_20251201_0100_010KM_MS.HDF"
            with h5py.File(path, "w") as handle:
                grp = handle.create_group("Calibration")
                grp.create_dataset(
                    "EARTH_OBSERVE_BT_10_to_89GHz",
                    data=np.zeros((4, 4, 2), dtype="f4"),
                )
            self.assertTrue(_hdf_file_readable(path))
            self.assertTrue(_local_download_ok(path))

    def test_purge_incomplete_orbit_hdf_for_day(self) -> None:
        import h5py
        import numpy as np

        from modules.fy_download import _purge_incomplete_orbit_hdf

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = "20251209"
            junk = root / f"FY3D_MWRID_GBAL_L1_{day}_2045_010KM_MS.HDF"
            junk.write_bytes(b"NOT-HDF")
            good = root / f"FY3D_MWRID_GBAL_L1_{day}_2211_010KM_MS.HDF"
            with h5py.File(good, "w") as handle:
                handle.create_dataset("probe", data=np.asarray([1], dtype="i4"))
            other = root / "FY3D_MWRID_GBAL_L1_20251210_0100_010KM_MS.HDF"
            other.write_bytes(b"also-junk")

            removed = _purge_incomplete_orbit_hdf(root, day)
            self.assertEqual(removed, [junk.name])
            self.assertFalse(junk.exists())
            self.assertTrue(good.exists())
            self.assertTrue(other.exists())  # 其它日期不碰


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
            self.assertIn("FY3D/FY3F", str(cm.exception))

    def test_fy3f_merged_hdf_download(self) -> None:
        """FY3F：默认 3Ffinal 目录 + 双极化合并 HDF（单文件）。"""
        import h5py
        import numpy as np

        import modules.fy_download as fy

        downloads: list[str] = []

        def _fake_download(
            url,
            token,
            remote_path,
            local_path,
            remote_size=0,
            resume_offset=0,
            progress_callback=None,
        ):
            downloads.append(remote_path)
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            with h5py.File(local_path, "w") as handle:
                handle.create_dataset("probe", data=np.asarray([1], dtype="i4"))
            return True

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            target = Path(tmp) / "out"
            with (
                patch(
                    "modules.download_nodes._resolve_profile_server_config",
                    return_value=self._server(),
                ),
                patch("ingest.remote_sync.filebrowser_login", return_value="tok"),
                patch(
                    "ingest.remote_sync._filebrowser_download",
                    side_effect=_fake_download,
                ),
            ):
                out = fy._fetch_from_nas(
                    _ctx(workspace),
                    satellite="FY3F",
                    date_path="2024.01.15",
                    ds={},
                    target_dir=target,
                )
        self.assertEqual(out, target / "FY3F_GBAL_L1_ORBA_10V10H_20240115_ORBA.hdf")
        self.assertEqual(
            downloads,
            [
                "/Chenhaojun/Data/3Ffinal/FY3F_GBAL_L1_ORBA_10V10H_20240115_ORBA.hdf",
            ],
        )

    def test_fy3f_corrupt_hdf_falls_back_to_tif_pair(self) -> None:
        """FY3F：本地/新下 HDF 损坏 → 删除并回退 TIF 对。"""
        import modules.fy_download as fy

        downloads: list[str] = []

        def _fake_download(
            url,
            token,
            remote_path,
            local_path,
            remote_size=0,
            resume_offset=0,
            progress_callback=None,
        ):
            downloads.append(remote_path)
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            if remote_path.endswith(".hdf"):
                Path(local_path).write_bytes(b"not-hdf")
                return True
            Path(local_path).write_bytes(b"tif")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            target = Path(tmp) / "out"
            with (
                patch(
                    "modules.download_nodes._resolve_profile_server_config",
                    return_value=self._server(),
                ),
                patch("ingest.remote_sync.filebrowser_login", return_value="tok"),
                patch(
                    "ingest.remote_sync._filebrowser_download",
                    side_effect=_fake_download,
                ),
            ):
                out = fy._fetch_from_nas(
                    _ctx(workspace),
                    satellite="FY3F",
                    date_path="2024.01.17",
                    ds={},
                    target_dir=target,
                )
            self.assertEqual(out.name, "FY3F_GBAL_L1_10H_20240117_ORBA_0.tif")
            self.assertFalse(
                (target / "FY3F_GBAL_L1_ORBA_10V10H_20240117_ORBA.hdf").exists()
            )

    def test_fy3f_hdf_missing_falls_back_to_tif_pair(self) -> None:
        """FY3F：合并 HDF 缺失 → 回退 10V/10H 单极化 TIF 对。"""
        import modules.fy_download as fy

        downloads: list[str] = []

        def _fake_download(
            url,
            token,
            remote_path,
            local_path,
            remote_size=0,
            resume_offset=0,
            progress_callback=None,
        ):
            downloads.append(remote_path)
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            if remote_path.endswith(".hdf"):
                return False  # 合并 HDF 下载失败（404）
            Path(local_path).write_bytes(b"tif")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            target = Path(tmp) / "out"
            with (
                patch(
                    "modules.download_nodes._resolve_profile_server_config",
                    return_value=self._server(),
                ),
                patch("ingest.remote_sync.filebrowser_login", return_value="tok"),
                patch(
                    "ingest.remote_sync._filebrowser_download",
                    side_effect=_fake_download,
                ),
            ):
                out = fy._fetch_from_nas(
                    _ctx(workspace),
                    satellite="FY3F",
                    date_path="2024.01.16",
                    ds={},
                    target_dir=target,
                )
        self.assertEqual(
            downloads,
            [
                "/Chenhaojun/Data/3Ffinal/FY3F_GBAL_L1_ORBA_10V10H_20240116_ORBA.hdf",
                "/Chenhaojun/Data/3Ffinal/FY3F_GBAL_L1_10V_20240116_ORBA_0.tif",
                "/Chenhaojun/Data/3Ffinal/FY3F_GBAL_L1_10H_20240116_ORBA_0.tif",
            ],
        )
        self.assertEqual(out.name, "FY3F_GBAL_L1_10H_20240116_ORBA_0.tif")
        self.assertFalse(
            (target / "FY3F_GBAL_L1_ORBA_10V10H_20240116_ORBA.hdf").exists()
        )

    def test_fy3d_direct_download_and_idempotent_skip(self) -> None:
        import modules.fy_download as fy

        downloads: list[str] = []

        def _fake_download(
            url,
            token,
            remote_path,
            local_path,
            remote_size=0,
            resume_offset=0,
            progress_callback=None,
        ):
            downloads.append(remote_path)
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            Path(local_path).write_bytes(b"tif-bytes")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            target = Path(tmp) / "out"
            with (
                patch(
                    "modules.download_nodes._resolve_profile_server_config",
                    return_value=self._server(),
                ),
                patch("ingest.remote_sync.filebrowser_login", return_value="tok"),
                patch(
                    "ingest.remote_sync._filebrowser_download",
                    side_effect=_fake_download,
                ),
            ):
                out = fy._fetch_from_nas(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2025.12.27",
                    ds={},
                    target_dir=target,
                )
                self.assertEqual(out, target / "FY3D_GBAL_L1_10H_20251227_MWRID_0.tif")
                # 已存在且非空 → 跳过重复下载
                fy._fetch_from_nas(
                    _ctx(workspace),
                    satellite="FY3D",
                    date_path="2025.12.27",
                    ds={},
                    target_dir=target,
                )
        self.assertEqual(
            downloads,
            [
                "/Chenhaojun/Data/fy3dhdf2425/FY3D_GBAL_L1_10V_20251227_MWRID_0.tif",
                "/Chenhaojun/Data/fy3dhdf2425/FY3D_GBAL_L1_10H_20251227_MWRID_0.tif",
            ],
        )

    def test_remote_dir_override_via_ds(self) -> None:
        import modules.fy_download as fy

        seen: dict[str, object] = {}

        def _fake_download(
            url,
            token,
            remote_path,
            local_path,
            remote_size=0,
            resume_offset=0,
            progress_callback=None,
        ):
            seen["remote"] = remote_path
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            Path(local_path).write_bytes(b"x")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with (
                patch(
                    "modules.download_nodes._resolve_profile_server_config",
                    return_value=self._server(),
                ),
                patch("ingest.remote_sync.filebrowser_login", return_value="tok"),
                patch(
                    "ingest.remote_sync._filebrowser_download",
                    side_effect=_fake_download,
                ),
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

    def test_nas_missing_date_explains_archive_availability(self) -> None:
        import modules.fy_download as fy

        def _missing(*args, **kwargs):
            return False

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("modules.download_nodes._resolve_profile_server_config", return_value=self._server()),
                patch("ingest.remote_sync.filebrowser_login", return_value="tok"),
                patch("ingest.remote_sync._filebrowser_download", side_effect=_missing),
            ):
                with self.assertRaisesRegex(RuntimeError, "requested date/file may not be available"):
                    fy._fetch_from_nas(
                        _ctx(Path(tmp) / "ws"),
                        satellite="FY3D",
                        date_path="2026.08.26",
                        ds={},
                        target_dir=Path(tmp) / "out",
                    )


if __name__ == "__main__":
    unittest.main()
