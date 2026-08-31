"""CDSE 下载节点与 ingest 层测试（离线 mock，不触网）。

覆盖：product_ids 规整、下载 URL 构造、检索结果提取、token 交换、OData
filter 检索、主路径下载与增量跳过、legacy 直链、use 语义、节点执行
（门户凭据解析、search_results 输入 port）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ingest.cdse_download import (
    CdseProduct,
    build_download_url,
    coerce_product_ids,
    download_cdse_products,
    exchange_cdse_token,
    extract_products_from_search,
    search_by_odata_filter,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class TestCoerceProductIds(unittest.TestCase):
    def test_comma_string(self) -> None:
        self.assertEqual(coerce_product_ids(" a, b ,c "), ["a", "b", "c"])

    def test_list_filtered(self) -> None:
        self.assertEqual(coerce_product_ids(["a", " ", "b"]), ["a", "b"])

    def test_empty(self) -> None:
        self.assertEqual(coerce_product_ids(""), [])
        self.assertEqual(coerce_product_ids([]), [])

    def test_invalid_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            coerce_product_ids(42)  # type: ignore[arg-type]


class TestBuildDownloadUrl(unittest.TestCase):
    def test_format(self) -> None:
        url = build_download_url("abc-123")
        self.assertEqual(
            url,
            "https://download.dataspace.copernicus.eu"
            "/odata/v1/Products(abc-123)/$value",
        )


class TestExtractProductsFromSearch(unittest.TestCase):
    def test_search_portal_style_results(self) -> None:
        results = {
            "results": [
                {
                    "granule_id": "id-1",
                    "title": "S1A_IW_SLC.zip",
                    "size_bytes": 1024,
                },
                {"granule_id": "", "title": "skip me"},
            ]
        }
        products = extract_products_from_search(results)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].product_id, "id-1")
        self.assertEqual(products[0].name, "S1A_IW_SLC.zip")
        self.assertEqual(products[0].size_bytes, 1024)

    def test_bare_list_and_single_dict(self) -> None:
        self.assertEqual(
            len(extract_products_from_search([{"product_id": "x"}])), 1
        )
        self.assertEqual(
            len(extract_products_from_search({"granule_id": "y"})), 1
        )

    def test_json_string(self) -> None:
        products = extract_products_from_search('{"results": [{"granule_id": "z"}]}')
        self.assertEqual(len(products), 1)

    def test_invalid_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            extract_products_from_search("{bad json")

    def test_non_container_returns_empty(self) -> None:
        self.assertEqual(extract_products_from_search(42), [])


class TestTokenExchange(unittest.TestCase):
    def test_success(self) -> None:
        class _Sess:
            def post(self, url, data=None, timeout=None):  # noqa: ANN001
                _Sess.last = (url, data)
                return _FakeResponse(200, {"access_token": "tok-1"})

        sess = _Sess()
        token = exchange_cdse_token("user", "pass", session=sess)
        self.assertEqual(token, "tok-1")
        url, data = _Sess.last
        self.assertIn("identity.dataspace.copernicus.eu", url)
        self.assertEqual(data["grant_type"], "password")
        self.assertEqual(data["username"], "user")

    def test_http_error_raises(self) -> None:
        class _Sess:
            def post(self, url, data=None, timeout=None):  # noqa: ANN001
                return _FakeResponse(401, {})

        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            exchange_cdse_token("user", "bad", session=_Sess())

    def test_empty_token_raises(self) -> None:
        class _Sess:
            def post(self, url, data=None, timeout=None):  # noqa: ANN001
                return _FakeResponse(200, {"access_token": ""})

        with self.assertRaisesRegex(RuntimeError, "no access_token"):
            exchange_cdse_token("user", "pass", session=_Sess())


class TestOdataFilterSearch(unittest.TestCase):
    def test_success_parses_value_list(self) -> None:
        class _Sess:
            def get(self, url, timeout=None):  # noqa: ANN001
                _Sess.url = url
                return _FakeResponse(
                    200,
                    {
                        "value": [
                            {"Id": "id-1", "Name": "a.zip", "ContentLength": 10},
                            {"Id": "", "Name": "skip"},
                        ]
                    },
                )

        products = search_by_odata_filter("contains(Name,'S1A')", session=_Sess())
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].product_id, "id-1")
        self.assertIn("%24filter", _Sess.url)  # $filter URL-encoded

    def test_http_error_raises(self) -> None:
        class _Sess:
            def get(self, url, timeout=None):  # noqa: ANN001
                return _FakeResponse(500, {})

        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            search_by_odata_filter("x", session=_Sess())


class TestDownloadCdseProducts(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target_dir = Path(self._tmp.name) / "cdse"

    def _main_path_patches(self):
        """主路径桩：解析返回带名产品，token 交换固定值，下载写文件。"""

        def _resolve(ids):  # noqa: ANN001
            return [
                CdseProduct(product_id=p, name=f"{p}.zip", size_bytes=8)
                for p in ids
            ]

        def _download(product, target, *, bearer_token, origin, session=None, **kwargs):  # noqa: ANN001, ANN003
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"12345678")
            return 8

        return (
            patch(
                "ingest.cdse_download.resolve_cdse_products", side_effect=_resolve
            ),
            patch(
                "ingest.cdse_download.exchange_cdse_token",
                return_value="exchanged-token",
            ),
            patch(
                "ingest.cdse_download.download_product_value",
                side_effect=_download,
            ),
        )

    def test_main_path_token_exchange_and_download(self) -> None:
        p1, p2, p3 = self._main_path_patches()
        with p1 as _, p2 as exchange, p3 as dl:
            result = download_cdse_products(
                "id-1,id-2",
                target_dir=self.target_dir,
                username="user",
                password="pass",
                min_disk_free_gb=0.0,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.downloaded, 2)
        self.assertEqual(result.downloaded_bytes, 16)
        exchange.assert_called_once_with("user", "pass")
        # 下载均携带交换所得 token
        for call in dl.call_args_list:
            self.assertEqual(call.kwargs["bearer_token"], "exchanged-token")

    def test_bearer_token_skips_exchange(self) -> None:
        p1, p2, p3 = self._main_path_patches()
        with p1 as _, p2 as exchange, p3 as dl:
            download_cdse_products(
                "id-1",
                target_dir=self.target_dir,
                bearer_token="direct-token",
                min_disk_free_gb=0.0,
            )
        exchange.assert_not_called()
        self.assertEqual(dl.call_args.kwargs["bearer_token"], "direct-token")

    def test_existing_file_skipped_by_size(self) -> None:
        p1, p2, p3 = self._main_path_patches()
        target = self.target_dir / "id-1.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"12345678")
        with p1 as _, p2 as _, p3 as dl:
            result = download_cdse_products(
                "id-1",
                target_dir=self.target_dir,
                bearer_token="t",
                min_disk_free_gb=0.0,
            )
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.downloaded, 0)
        dl.assert_not_called()

    def test_search_results_input(self) -> None:
        def _download(product, target, *, bearer_token, origin, session=None, **kwargs):  # noqa: ANN001, ANN003
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"12345678")
            return 8

        with patch(
            "ingest.cdse_download.download_product_value", side_effect=_download
        ):
            result = download_cdse_products(
                target_dir=self.target_dir,
                search_results={"results": [{"granule_id": "g1", "title": "n.zip"}]},
                bearer_token="t",
                min_disk_free_gb=0.0,
            )
        self.assertEqual(result.downloaded, 1)

    def test_no_products_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "no products"):
            download_cdse_products(target_dir=self.target_dir, bearer_token="t")

    def test_missing_credentials_raises(self) -> None:
        with patch(
            "ingest.cdse_download.resolve_cdse_products",
            return_value=[CdseProduct(product_id="x", name="x.zip")],
        ):
            with self.assertRaisesRegex(ValueError, "credentials"):
                download_cdse_products(
                    "x", target_dir=self.target_dir, min_disk_free_gb=0.0
                )

    def test_legacy_direct_urls(self) -> None:
        def _retry(session, url, target, **kwargs):  # noqa: ANN001, ANN003
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"abc")
            return True

        with patch(
            "ingest.cdse_download.download_with_retry", side_effect=_retry
        ) as mocked:
            result = download_cdse_products(
                legacy_urls="https://x/a.zip, https://x/b.zip",
                target_dir=self.target_dir,
                use="legacy",
                min_disk_free_gb=0.0,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.downloaded, 2)
        self.assertEqual(mocked.call_count, 2)

    def test_legacy_without_urls_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "legacy_urls"):
            download_cdse_products(
                "id-1", target_dir=self.target_dir, use="legacy"
            )

    def test_invalid_use_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid use"):
            download_cdse_products("id-1", target_dir=self.target_dir, use="bogus")


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
        job_id="job-cdse-1",
        datasource_selection={},
        region=None,
        time_range=None,
    )
    runtime = SimpleNamespace(run_id="run-cdse-1", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
    )


class TestCdseDownloadNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import contracts.job  # noqa: F401
        from modules import registry as module_registry

        cls.registry = module_registry

    def test_module_registered(self) -> None:
        names = set(self.registry.list_modules())
        self.assertIn("cdse_download", names)
        module = self.registry.get_module("cdse_download")
        self.assertEqual(module.name, "cdse_download")
        port_names = {p.name for p in module.output_ports}
        self.assertIn("path", port_names)
        self.assertIn("manifest", port_names)

    def test_execute_uses_portal_credentials_and_search_input(self) -> None:
        module = self.registry.get_module("cdse_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()

            def _download(product_ids, odata_filter, target_dir, **kwargs):  # noqa: ANN001
                _download.captured = (product_ids, target_dir, kwargs)
                from ingest.cdse_download import CdseDownloadResult

                return CdseDownloadResult(
                    use="cdse",
                    target_dir=target_dir,
                    downloaded=1,
                    products=[CdseProduct("g1", "n.zip", 8)],
                    downloaded_bytes=8,
                )

            ds = {
                "portal_credentials": {
                    "copernicus": {
                        "enabled": True,
                        "auth_type": "basic",
                        "username": "portal-user",
                        "password": "portal-pass",
                    }
                }
            }
            with patch(
                "ingest.cdse_download.download_cdse_products",
                side_effect=_download,
            ) as mocked:
                out = module.execute(
                    inputs={
                        "datasource_selection": ds,
                        "search_results": {
                            "results": [{"granule_id": "g1", "title": "n.zip"}]
                        },
                    },
                    params={},
                    ctx=_ctx(workspace),
                )
            mocked.assert_called_once()
            args = mocked.call_args
            self.assertEqual(args.args[0], "")
            self.assertEqual(args.args[2], str(workspace / "data_access" / "cdse"))
            self.assertEqual(args.kwargs["username"], "portal-user")
            self.assertEqual(args.kwargs["password"], "portal-pass")
            self.assertEqual(
                args.kwargs["search_results"]["results"][0]["granule_id"], "g1"
            )
            self.assertIn("manifest", out)

    def test_execute_failure_raises(self) -> None:
        module = self.registry.get_module("cdse_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            from ingest.cdse_download import CdseDownloadResult

            fake = CdseDownloadResult(
                use="cdse", downloaded=1, failed=1, errors=["boom"]
            )
            with patch(
                "ingest.cdse_download.download_cdse_products", return_value=fake
            ):
                with self.assertRaisesRegex(RuntimeError, "1 failures"):
                    module.execute(
                        inputs={"search_results": {"results": [{"granule_id": "g"}]}},
                        params={},
                        ctx=_ctx(workspace),
                    )

    def test_execute_invalid_use(self) -> None:
        module = self.registry.get_module("cdse_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "invalid use"):
                module.execute(
                    inputs={},
                    params={"product_ids": "x", "use": "bogus"},
                    ctx=_ctx(workspace),
                )


if __name__ == "__main__":
    unittest.main()
