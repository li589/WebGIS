"""HttpSource SSL 策略单元测试。

NSMC 门户使用内部自签 CA（``self-signed certificate in certificate chain``），
公共信任库无法验证。策略：默认仅对 ``satellite.nsmc.org.cn`` 放宽，
其余域名严格；``CGDA_HTTP_INSECURE_HOSTS`` 可覆盖；请求级
``metadata["ssl_verify"]=false`` 可显式放宽。
"""

from __future__ import annotations

import ssl
import unittest
from unittest.mock import patch

from data_access.sources.http import ssl_context_for


class TestSslContextFor(unittest.TestCase):
    def test_nsmc_default_allowlisted(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("CGDA_HTTP_INSECURE_HOSTS", None)
            ctx = ssl_context_for("https://satellite.nsmc.org.cn/FY3D/MWRID/2025.12.27/")
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertFalse(ctx.check_hostname)

    def test_other_hosts_strict_by_default(self) -> None:
        import os

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("CGDA_HTTP_INSECURE_HOSTS", None)
            self.assertIsNone(ssl_context_for("https://example.com/data.hdf"))
            self.assertIsNone(ssl_context_for("https://n5eil01u.ecs.nsidc.org/data"))

    def test_env_override_adds_host(self) -> None:
        with patch.dict(
            "os.environ", {"CGDA_HTTP_INSECURE_HOSTS": "portal.example.org"}
        ):
            self.assertIsNotNone(ssl_context_for("https://portal.example.org/f.hdf"))
            # 未列入的域名（含 NSMC）保持严格
            self.assertIsNone(
                ssl_context_for("https://satellite.nsmc.org.cn/FY3D/x.hdf")
            )

    def test_env_empty_restores_strict(self) -> None:
        with patch.dict("os.environ", {"CGDA_HTTP_INSECURE_HOSTS": ""}):
            self.assertIsNone(
                ssl_context_for("https://satellite.nsmc.org.cn/FY3D/x.hdf")
            )

    def test_request_metadata_disables_verify(self) -> None:
        ctx = ssl_context_for(
            "https://strict.example.org/f.hdf", {"ssl_verify": "false"}
        )
        self.assertIsNotNone(ctx)

    def test_http_urls_untouched(self) -> None:
        # http（非 https）无证书校验问题；函数对非白名单主机仍返回 None
        self.assertIsNone(ssl_context_for("http://example.com/f.hdf"))

    def test_subdomain_not_allowlisted(self) -> None:
        import os

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("CGDA_HTTP_INSECURE_HOSTS", None)
            # 白名单为精确主机名匹配，不放宽任意子域
            self.assertIsNone(ssl_context_for("https://mirror.nsmc.org.cn/f.hdf"))


if __name__ == "__main__":
    unittest.main()
