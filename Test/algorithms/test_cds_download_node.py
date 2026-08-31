"""CDS 下载节点与 ingest 层测试（离线 mock，不触网）。

覆盖：API key 解析链、request 规整、cdsapi 主路径、增量跳过、legacy 直链
回退、use=auto 无 cdsapi 报错、节点注册与执行（门户凭据解析、默认目录）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ingest.cds_download import (
    CdsDownloadResult,
    coerce_request,
    default_filename,
    download_cds_dataset,
    load_cds_api_key,
)


class TestLoadCdsApiKey(unittest.TestCase):
    def test_explicit_param_wins(self) -> None:
        with patch.dict(
            "os.environ",
            {"BACKEND_CDS_API_KEY": "env-key", "CDSAPI_KEY": "cdsapi-key"},
            clear=True,
        ):
            self.assertEqual(load_cds_api_key("explicit-key"), "explicit-key")

    def test_backend_env_over_cdsapi_env(self) -> None:
        with patch.dict(
            "os.environ",
            {"BACKEND_CDS_API_KEY": "env-key", "CDSAPI_KEY": "cdsapi-key"},
            clear=True,
        ):
            self.assertEqual(load_cds_api_key(), "env-key")

    def test_falls_back_to_cdsapi_key_env(self) -> None:
        with patch.dict("os.environ", {"CDSAPI_KEY": "cdsapi-key"}, clear=True):
            self.assertEqual(load_cds_api_key(), "cdsapi-key")

    def test_missing_raises(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "CDS API key is required"):
                load_cds_api_key()


class TestCoerceRequest(unittest.TestCase):
    def test_dict_passthrough_copy(self) -> None:
        req = {"product_type": "reanalysis"}
        out = coerce_request(req)
        self.assertEqual(out, req)
        self.assertIsNot(out, req)

    def test_json_string_parsed(self) -> None:
        out = coerce_request('{"variable": ["2m_temperature"]}')
        self.assertEqual(out, {"variable": ["2m_temperature"]})

    def test_empty_string_gives_empty_dict(self) -> None:
        self.assertEqual(coerce_request(""), {})

    def test_invalid_json_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid request JSON"):
            coerce_request("{not json")

    def test_non_object_json_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON object"):
            coerce_request("[1, 2]")


class TestDefaultFilename(unittest.TestCase):
    def test_deterministic_and_slugged(self) -> None:
        req = {"variable": ["t2m"]}
        name1 = default_filename("reanalysis-era5-single-levels", req)
        name2 = default_filename("reanalysis-era5-single-levels", req)
        self.assertEqual(name1, name2)
        self.assertTrue(name1.startswith("reanalysis-era5-single-levels_"))
        self.assertTrue(name1.endswith(".zip"))
        self.assertNotIn("/", name1)

    def test_request_change_alters_digest(self) -> None:
        self.assertNotEqual(
            default_filename("ds", {"a": 1}), default_filename("ds", {"a": 2})
        )

    def test_unarchived_extension_follows_data_format(self) -> None:
        nc = default_filename(
            "ds", {"data_format": "netcdf", "download_format": "unarchived"}
        )
        grib = default_filename(
            "ds", {"data_format": "grib", "download_format": "unarchived"}
        )
        self.assertTrue(nc.endswith(".nc"))
        self.assertTrue(grib.endswith(".grib"))

    def test_unarchived_without_data_format_defaults_to_grib(self) -> None:
        name = default_filename("ds", {"download_format": "unarchived"})
        self.assertTrue(name.endswith(".grib"))

    def test_zip_download_format_keeps_zip_suffix(self) -> None:
        name = default_filename(
            "ds", {"data_format": "netcdf", "download_format": "zip"}
        )
        self.assertTrue(name.endswith(".zip"))

    def test_undeclared_download_format_keeps_zip_suffix(self) -> None:
        name = default_filename("ds", {"data_format": "netcdf"})
        self.assertTrue(name.endswith(".zip"))


class _FakeCdsapiClient:
    """回放 retrieve：把内容写入 target。"""

    instances: list["_FakeCdsapiClient"] = []
    calls: list[tuple[str, dict, str]] = []

    def __init__(self, url: str = "", key: str = "", **kwargs):
        self.url = url
        self.key = key
        _FakeCdsapiClient.instances.append(self)

    def retrieve(self, name: str, request: dict, target: str) -> None:
        _FakeCdsapiClient.calls.append((name, dict(request), target))
        Path(target).write_bytes(b"cds-payload")


class TestDownloadCdsDataset(unittest.TestCase):
    def setUp(self) -> None:
        _FakeCdsapiClient.instances = []
        _FakeCdsapiClient.calls = []
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target_dir = Path(self._tmp.name) / "cds"

    def test_cdsapi_main_path(self) -> None:
        with patch("ingest.cds_download.cdsapi.Client", _FakeCdsapiClient):
            result = download_cds_dataset(
                "reanalysis-era5-single-levels",
                {"variable": ["2m_temperature"]},
                self.target_dir,
                api_key="test-key",
            )
        self.assertTrue(result.success)
        self.assertFalse(result.skipped)
        self.assertEqual(result.downloaded_bytes, len(b"cds-payload"))
        self.assertEqual(len(_FakeCdsapiClient.calls), 1)
        name, req, target = _FakeCdsapiClient.calls[0]
        self.assertEqual(name, "reanalysis-era5-single-levels")
        self.assertEqual(req, {"variable": ["2m_temperature"]})
        self.assertTrue(Path(target).exists())
        # Client 收到密钥与默认端点
        self.assertEqual(_FakeCdsapiClient.instances[0].key, "test-key")

    def test_existing_target_skipped(self) -> None:
        with patch("ingest.cds_download.cdsapi.Client", _FakeCdsapiClient):
            first = download_cds_dataset(
                "ds", {}, self.target_dir, api_key="k", filename="f.zip"
            )
            self.assertFalse(first.skipped)
            second = download_cds_dataset(
                "ds", {}, self.target_dir, api_key="k", filename="f.zip"
            )
        self.assertTrue(second.skipped)
        self.assertEqual(len(_FakeCdsapiClient.calls), 1)

    def test_force_redownloads(self) -> None:
        with patch("ingest.cds_download.cdsapi.Client", _FakeCdsapiClient):
            download_cds_dataset(
                "ds", {}, self.target_dir, api_key="k", filename="f.zip"
            )
            download_cds_dataset(
                "ds", {}, self.target_dir, api_key="k", filename="f.zip", force=True
            )
        self.assertEqual(len(_FakeCdsapiClient.calls), 2)

    def test_legacy_direct_url(self) -> None:
        def _fake_retry(session, url, target, **kwargs):  # noqa: ANN001, ANN003
            Path(target).write_bytes(b"legacy-payload")
            return True

        with patch(
            "ingest.cds_download.download_resumable_with_retry",
            side_effect=_fake_retry,
        ) as mocked:
            result = download_cds_dataset(
                "ds",
                {},
                self.target_dir,
                use="legacy",
                direct_url="https://example.test/static.zip",
                filename="s.zip",
            )
        self.assertTrue(result.success)
        self.assertEqual(result.downloaded_bytes, len(b"legacy-payload"))
        mocked.assert_called_once()
        self.assertIn("static.zip", mocked.call_args[0][1])
        self.assertEqual(Path(result.target).read_bytes(), b"legacy-payload")

    def test_legacy_without_direct_url_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "direct_url"):
            download_cds_dataset("ds", {}, self.target_dir, use="legacy")

    def test_auto_without_cdsapi_raises_with_hint(self) -> None:
        with patch("ingest.cds_download._HAS_CDSAPI", False):
            with self.assertRaisesRegex(RuntimeError, "cdsapi is not installed"):
                download_cds_dataset("ds", {}, self.target_dir, api_key="k")

    def test_missing_dataset_raises(self) -> None:
        with self.assertRaises(ValueError):
            download_cds_dataset("", {}, self.target_dir)

    def test_invalid_use_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid use"):
            download_cds_dataset("ds", {}, self.target_dir, use="bogus")

    def test_missing_api_key_raises_on_cdsapi_path(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("ingest.cds_download.cdsapi.Client", _FakeCdsapiClient):
                with self.assertRaisesRegex(ValueError, "CDS API key"):
                    download_cds_dataset("ds", {}, self.target_dir)


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
        job_id="job-cds-1",
        datasource_selection={},
        region=None,
        time_range=None,
    )
    runtime = SimpleNamespace(run_id="run-cds-1", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
    )


class TestCdsDownloadNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import contracts.job  # noqa: F401
        from modules import registry as module_registry

        cls.registry = module_registry

    def test_module_registered(self) -> None:
        names = set(self.registry.list_modules())
        self.assertIn("cds_download", names)
        module = self.registry.get_module("cds_download")
        self.assertEqual(module.name, "cds_download")
        port_names = {p.name for p in module.output_ports}
        self.assertIn("path", port_names)
        self.assertIn("manifest", port_names)

    def test_execute_passes_params_and_portal_key(self) -> None:
        module = self.registry.get_module("cds_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            fake = CdsDownloadResult(
                dataset="reanalysis-era5-single-levels",
                target=str(Path(tmp) / "out.zip"),
                downloaded_bytes=128,
                use="cdsapi",
                request={"variable": ["t2m"]},
            )
            ds = {
                "portal_credentials": {
                    "ecmwf_cds": {
                        "enabled": True,
                        "auth_type": "bearer",
                        "token": "portal-key",
                    }
                }
            }
            with patch(
                "ingest.cds_download.download_cds_dataset", return_value=fake
            ) as mocked:
                out = module.execute(
                    inputs={"datasource_selection": ds},
                    params={
                        "dataset": "reanalysis-era5-single-levels",
                        "request": '{"variable": ["t2m"]}',
                    },
                    ctx=_ctx(workspace),
                )
            mocked.assert_called_once()
            call_args = mocked.call_args
            kwargs = call_args.kwargs
            self.assertEqual(kwargs["api_key"], "portal-key")
            # 缺省 target_dir 落 workspace/data_access/cds（第 3 个位置参数）
            self.assertEqual(call_args.args[2], str(workspace / "data_access" / "cds"))
            self.assertEqual(out["path"], fake.target)
            self.assertIn("manifest", out)

    def test_execute_env_key_fallback(self) -> None:
        module = self.registry.get_module("cds_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            fake = CdsDownloadResult(dataset="ds", target=str(Path(tmp) / "o.zip"))
            with patch.dict("os.environ", {"BACKEND_CDS_API_KEY": "env-key"}):
                with patch(
                    "ingest.cds_download.download_cds_dataset", return_value=fake
                ) as mocked:
                    module.execute(
                        inputs={},
                        params={"dataset": "ds", "request": "{}"},
                        ctx=_ctx(workspace),
                    )
            self.assertEqual(mocked.call_args.kwargs["api_key"], "env-key")

    def test_execute_requires_dataset(self) -> None:
        module = self.registry.get_module("cds_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "requires dataset"):
                module.execute(inputs={}, params={}, ctx=_ctx(workspace))

    def test_execute_rejects_invalid_use(self) -> None:
        module = self.registry.get_module("cds_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "invalid use"):
                module.execute(
                    inputs={},
                    params={"dataset": "ds", "use": "bogus"},
                    ctx=_ctx(workspace),
                )


if __name__ == "__main__":
    unittest.main()
