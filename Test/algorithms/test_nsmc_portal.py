"""nsmc_portal：RSA 纯 Python 实现（SPKI 解析 + PKCS#1 v1.5 加密）契约测试。

线上链路（登录/检索/下载）依赖 NSMC 真实站点与账号，不做在线测试；
此处锁定密码学原语的正确性（与 pycryptodome 交叉验证）。
"""

from __future__ import annotations

import base64
import unittest


def _skip_if_no_crypto():
    try:
        from Crypto.Cipher import PKCS1_v1_5  # noqa: F401
        from Crypto.PublicKey import RSA  # noqa: F401

        return None
    except ImportError:
        return unittest.skip("pycryptodome 不可用（交叉验证依赖）")


class TestDerWalk(unittest.TestCase):
    def test_walk_spki_structure(self) -> None:
        from ingest.nsmc_portal import _parse_spki_modulus_exponent

        from Crypto.PublicKey import RSA

        kp = RSA.generate(2048)
        der = kp.publickey().export_key("DER")
        n, e = _parse_spki_modulus_exponent(der)
        self.assertEqual((n, e), (kp.n, kp.e))


class TestRsaEncrypt(unittest.TestCase):
    def test_roundtrip_against_pycryptodome(self) -> None:
        from Crypto.Cipher import PKCS1_v1_5
        from Crypto.PublicKey import RSA

        from ingest.nsmc_portal import rsa_pkcs1_v15_encrypt

        kp = RSA.generate(2048)
        pub_b64url = (
            base64.urlsafe_b64encode(kp.publickey().export_key("DER"))
            .decode()
            .rstrip("=")
        )
        # 模拟 NSMC 服务端行为：urlsafe 字母表（-_）混合标准 base64
        cipher_text = rsa_pkcs1_v15_encrypt(pub_b64url, "pw-with-中文-123")
        decrypted = PKCS1_v1_5.new(kp).decrypt(
            base64.b64decode(cipher_text), b"SENTINEL"
        )
        self.assertEqual(decrypted.decode("utf-8"), "pw-with-中文-123")

    def test_cipher_length_matches_key_size(self) -> None:
        from Crypto.PublicKey import RSA

        from ingest.nsmc_portal import rsa_pkcs1_v15_encrypt

        kp = RSA.generate(1024)
        pub_b64url = (
            base64.urlsafe_b64encode(kp.publickey().export_key("DER"))
            .decode()
            .rstrip("=")
        )
        ct = base64.b64decode(rsa_pkcs1_v15_encrypt(pub_b64url, "x"))
        self.assertEqual(len(ct), 128)

    def test_plaintext_too_long_raises(self) -> None:
        from Crypto.PublicKey import RSA

        from ingest.nsmc_portal import rsa_pkcs1_v15_encrypt

        kp = RSA.generate(1024)
        pub_b64url = (
            base64.urlsafe_b64encode(kp.publickey().export_key("DER"))
            .decode()
            .rstrip("=")
        )
        with self.assertRaises(ValueError):
            rsa_pkcs1_v15_encrypt(pub_b64url, "a" * 200)


class TestProductTemplates(unittest.TestCase):
    def test_fy3d_fy3f_l1_templates_present(self) -> None:
        from ingest.nsmc_portal import NSMC_PRODUCT_TEMPLATES

        # FY3F 模板含连字符（FY3F_MWRI-_ORBA_L1_...），为 2026-08-20 抓取真源
        self.assertEqual(
            NSMC_PRODUCT_TEMPLATES[("FY3F", "ORBA")],
            "FY3F_MWRI-_ORBA_L1_YYYYMMDD_HHmm_010KM_Vn.HDF",
        )
        self.assertEqual(
            NSMC_PRODUCT_TEMPLATES[("FY3D", "MWRID")],
            "FY3D_MWRID_GBAL_L1_YYYYMMDD_HHmm_010KM_MS.HDF",
        )


if __name__ == "__main__":
    unittest.main()
