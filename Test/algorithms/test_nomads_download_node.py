"""NOMADS GRIB2 下载节点与 ingest 层测试（离线 mock，不触网）。

覆盖：起报时间规整、URL 模板占位符、fxx 规整、herbie 主路径（member × fxx
笛卡尔积）、legacy 直连回退、use 语义（auto 回退/缺库报错）、节点执行。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ingest.nomads_download import (
    NomadsDownloadResult,
    _coerce_fxx_list,
    download_nomads_grib,
    expand_url_template,
    normalize_cycle,
)


class TestNormalizeCycle(unittest.TestCase):
    def test_full_datetime(self) -> None:
        dt = normalize_cycle("2026-01-02 12:00")
        self.assertEqual(
            dt, datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        )

    def test_date_only_defaults_midnight(self) -> None:
        self.assertEqual(normalize_cycle("2026-01-02").hour, 0)

    def test_iso_t_separator(self) -> None:
        self.assertEqual(
            normalize_cycle("2026-01-02T06:00").hour, 6
        )

    def test_latest_gives_recent_utc(self) -> None:
        dt = normalize_cycle("latest")
        self.assertIsNotNone(dt.tzinfo)
        self.assertLessEqual(dt, datetime.now(timezone.utc))

    def test_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_cycle("not-a-date")


class TestExpandUrlTemplate(unittest.TestCase):
    def test_placeholders(self) -> None:
        cycle = datetime(2026, 1, 2, 6, tzinfo=timezone.utc)
        url = expand_url_template(
            "https://x/gfs.{yyyymmdd}/{hh}/atmos/gfs.t{hh}z.f{fxx3}", cycle, 12
        )
        self.assertEqual(
            url, "https://x/gfs.20260102/06/atmos/gfs.t06z.f012"
        )

    def test_fxx2_variant(self) -> None:
        cycle = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.assertIn(".f03.", expand_url_template("a.f{fxx2}.grib2", cycle, 3))


class TestCoerceFxxList(unittest.TestCase):
    def test_int(self) -> None:
        self.assertEqual(_coerce_fxx_list(6), [6])

    def test_list(self) -> None:
        self.assertEqual(_coerce_fxx_list([0, 6, 12]), [0, 6, 12])

    def test_comma_string(self) -> None:
        self.assertEqual(_coerce_fxx_list("0, 6,12"), [0, 6, 12])

    def test_empty_string_defaults_zero(self) -> None:
        self.assertEqual(_coerce_fxx_list(""), [0])

    def test_invalid_string_raises(self) -> None:
        with self.assertRaises(ValueError):
            _coerce_fxx_list("abc")

    def test_bool_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _coerce_fxx_list(True)  # type: ignore[arg-type]


class TestDownloadNomadsGrib(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target_dir = Path(self._tmp.name) / "nomads"

    def _fake_herbie(self, target_dir: Path):
        """回放 herbie 物化：按调用序写文件并返回路径。"""

        def _impl(cycle, *, model, product, fxx, member, search_string, target_dir, overwrite):  # noqa: ANN001
            name = f"{model}_m{member or 'det'}_f{fxx:03d}.grib2"
            path = target_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"grib-payload")
            return path

        return _impl

    def test_herbie_main_path_member_fxx_product(self) -> None:
        with patch(
            "ingest.nomads_download.download_via_herbie",
            side_effect=self._fake_herbie(self.target_dir),
        ) as mocked:
            result = download_nomads_grib(
                "2026-01-02 00:00",
                "gefs",
                product="pgrb2b.0p25",
                fxx=[0, 6],
                members=["p01", "p02"],
                target_dir=self.target_dir,
                use="herbie",
                min_disk_free_gb=0.0,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.downloaded, 4)
        self.assertEqual(len(result.files), 4)
        self.assertEqual(mocked.call_count, 4)
        # 抽查一次调用参数
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["model"], "gefs")
        self.assertEqual(kwargs["product"], "pgrb2b.0p25")

    def test_herbie_partial_failure_recorded(self) -> None:
        calls = {"n": 0}

        def _flaky(cycle, **kwargs):  # noqa: ANN001
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("network down")
            return Path(self.target_dir) / "ok.grib2" if False else _write(kwargs)

        def _write(kwargs):  # noqa: ANN001
            path = self.target_dir / f"f{kwargs['fxx']:03d}.grib2"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
            return path

        with patch("ingest.nomads_download.download_via_herbie", side_effect=_flaky):
            result = download_nomads_grib(
                "2026-01-02 00:00",
                "gfs",
                fxx=[0, 6],
                target_dir=self.target_dir,
                use="herbie",
                min_disk_free_gb=0.0,
            )
        self.assertFalse(result.success)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.downloaded, 1)
        self.assertTrue(any("network down" in e for e in result.errors))

    def test_legacy_direct_urls(self) -> None:
        def _fake_legacy(url: str, target: Path, **kwargs) -> int:  # noqa: ANN003
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"legacy-grib")
            return target.stat().st_size

        with patch(
            "ingest.nomads_download.download_via_legacy",
            side_effect=_fake_legacy,
        ) as mocked:
            result = download_nomads_grib(
                "2026-01-02 06:00",
                "gfs",
                fxx=[0, 6],
                target_dir=self.target_dir,
                use="legacy",
                legacy_url="https://nomads/gfs.{yyyymmdd}/{hh}/gfs.t{hh}z.f{fxx3}",
                min_disk_free_gb=0.0,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.downloaded, 2)
        self.assertEqual(mocked.call_count, 2)
        urls = [c.args[0] for c in mocked.call_args_list]
        self.assertIn("https://nomads/gfs.20260102/06/gfs.t06z.f000", urls)
        self.assertIn("https://nomads/gfs.20260102/06/gfs.t06z.f006", urls)

    def test_legacy_without_url_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "legacy_url"):
            download_nomads_grib(
                "2026-01-02 00:00", target_dir=self.target_dir, use="legacy"
            )

    def test_use_herbie_without_herbie_raises(self) -> None:
        with patch("ingest.nomads_download._HAS_HERBIE", False):
            with self.assertRaisesRegex(RuntimeError, "herbie is not installed"):
                download_nomads_grib(
                    "2026-01-02 00:00", target_dir=self.target_dir, use="herbie"
                )

    def test_auto_without_herbie_falls_back_to_legacy(self) -> None:
        def _fake_legacy(url: str, target: Path, **kwargs) -> int:  # noqa: ANN003
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"g")
            return 1

        with patch("ingest.nomads_download._HAS_HERBIE", False):
            with patch(
                "ingest.nomads_download.download_via_legacy",
                side_effect=_fake_legacy,
            ):
                result = download_nomads_grib(
                    "2026-01-02 00:00",
                    target_dir=self.target_dir,
                    use="auto",
                    legacy_url="https://nomads/f{fxx3}",
                    min_disk_free_gb=0.0,
                )
        self.assertEqual(result.use, "legacy")
        self.assertTrue(result.success)

    def test_auto_without_herbie_and_without_url_raises(self) -> None:
        with patch("ingest.nomads_download._HAS_HERBIE", False):
            with self.assertRaisesRegex(RuntimeError, "herbie is not installed"):
                download_nomads_grib(
                    "2026-01-02 00:00", target_dir=self.target_dir, use="auto"
                )

    def test_invalid_use_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid use"):
            download_nomads_grib(
                "2026-01-02 00:00", target_dir=self.target_dir, use="bogus"
            )

    def test_insufficient_disk_raises(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "disk space"):
            download_nomads_grib(
                "2026-01-02 00:00",
                target_dir=self.target_dir,
                use="legacy",
                legacy_url="https://x/f",
                min_disk_free_gb=1e9,
            )


# ─── 节点层 ───────────────────────────────────────────────────────────────────


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def put(self, artifact, payload=None) -> object:
        self.items[artifact.artifact_id] = payload
        return artifact


def _ctx(workspace: Path):
    from workflow.schemas import NodeExecutionContext

    request = SimpleNamespace(
        job_id="job-nomads-1",
        datasource_selection={},
        region=None,
        time_range=None,
    )
    runtime = SimpleNamespace(run_id="run-nomads-1", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
    )


class TestNomadsDownloadNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import contracts.job  # noqa: F401
        from modules import registry as module_registry

        cls.registry = module_registry

    def test_module_registered(self) -> None:
        names = set(self.registry.list_modules())
        self.assertIn("nomads_grib_download", names)
        module = self.registry.get_module("nomads_grib_download")
        self.assertEqual(module.name, "nomads_grib_download")
        port_names = {p.name for p in module.output_ports}
        self.assertIn("path", port_names)
        self.assertIn("manifest", port_names)

    def test_execute_default_target_dir_and_params(self) -> None:
        module = self.registry.get_module("nomads_grib_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            fake = NomadsDownloadResult(
                model="gfs",
                date="2026-01-02 00:00",
                use="herbie",
                downloaded=2,
                target_dir=str(Path(tmp) / "nomads"),
            )
            with patch(
                "ingest.nomads_download.download_nomads_grib", return_value=fake
            ) as mocked:
                out = module.execute(
                    inputs={},
                    params={
                        "date": "2026-01-02 00:00",
                        "model": "gfs",
                        "fxx": [0, 6],
                        "search_string": ":TMP:2 m:",
                        "members": "p01, p02",
                    },
                    ctx=_ctx(workspace),
                )
            mocked.assert_called_once()
            call = mocked.call_args
            self.assertEqual(call.args[0], "2026-01-02 00:00")
            self.assertEqual(call.args[1], "gfs")
            self.assertEqual(
                call.kwargs["target_dir"], str(workspace / "data_access" / "nomads")
            )
            self.assertEqual(call.kwargs["members"], ["p01", "p02"])
            self.assertEqual(call.kwargs["fxx"], [0, 6])
            self.assertEqual(out["path"], fake.target_dir)
            self.assertIn("manifest", out)

    def test_execute_requires_date(self) -> None:
        module = self.registry.get_module("nomads_grib_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "requires date"):
                module.execute(inputs={}, params={}, ctx=_ctx(workspace))

    def test_execute_failure_raises(self) -> None:
        module = self.registry.get_module("nomads_grib_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            fake = NomadsDownloadResult(
                model="gfs",
                date="2026-01-02 00:00",
                downloaded=1,
                failed=1,
                errors=["boom"],
            )
            with patch(
                "ingest.nomads_download.download_nomads_grib", return_value=fake
            ):
                with self.assertRaisesRegex(RuntimeError, "1 failures"):
                    module.execute(
                        inputs={},
                        params={"date": "2026-01-02 00:00"},
                        ctx=_ctx(workspace),
                    )

    def test_execute_invalid_use(self) -> None:
        module = self.registry.get_module("nomads_grib_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "invalid use"):
                module.execute(
                    inputs={},
                    params={"date": "latest", "use": "bogus"},
                    ctx=_ctx(workspace),
                )


if __name__ == "__main__":
    unittest.main()
