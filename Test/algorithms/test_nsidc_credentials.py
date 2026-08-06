from __future__ import annotations

import unittest
from unittest.mock import patch

from ingest.nsidc_download import load_credentials


class TestNsidcCredentialResolution(unittest.TestCase):
    def test_prefers_explicit_args(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "BACKEND_EARTHDATA_USERNAME": "backend_user",
                "BACKEND_EARTHDATA_PASSWORD": "backend_pass",
            },
            clear=True,
        ):
            user, pwd = load_credentials("arg_user", "arg_pass")
        self.assertEqual(user, "arg_user")
        self.assertEqual(pwd, "arg_pass")

    def test_prefers_backend_env_over_earthdata_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "BACKEND_EARTHDATA_USERNAME": "backend_user",
                "BACKEND_EARTHDATA_PASSWORD": "backend_pass",
                "EARTHDATA_USERNAME": "earth_user",
                "EARTHDATA_PASSWORD": "earth_pass",
            },
            clear=True,
        ):
            user, pwd = load_credentials()
        self.assertEqual(user, "backend_user")
        self.assertEqual(pwd, "backend_pass")

    def test_raises_when_missing_credentials(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Earthdata credentials are required"):
                load_credentials()


if __name__ == "__main__":
    unittest.main()
