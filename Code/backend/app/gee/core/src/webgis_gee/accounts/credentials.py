from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GeeCredentialsLoader:
    """加载 service_account JSON 并构造 ee.Credentials 对象。"""

    @staticmethod
    def load_service_account_credentials(
        service_account_json: dict[str, Any] | str,
        project_id: Optional[str] = None,
    ) -> Any:
        """根据 service_account JSON 构造可用于 ee.Initialize(credentials=...) 的对象。

        Args:
            service_account_json: dict 或 JSON 字符串，含 client_email/private_key/private_key_id
            project_id: 可选 GCP project_id，目前仅用于日志，ee 内部会从凭证推导

        Returns:
            ee.Credentials 对象、google.oauth2.service_account.Credentials 或 dict（回退）

        Raises:
            ValueError: JSON 格式错误或缺少必要字段
            ImportError: 缺少 earthengine-api 依赖
        """
        if isinstance(service_account_json, str):
            try:
                sa_dict = json.loads(service_account_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid service_account JSON: {e}") from e
        else:
            sa_dict = dict(service_account_json)

        required = ("client_email", "private_key", "private_key_id")
        missing = [k for k in required if k not in sa_dict or not sa_dict[k]]
        if missing:
            raise ValueError(f"service_account JSON missing required fields: {missing}")

        try:
            import ee
        except ImportError as e:  # pragma: no cover - 依赖检查
            raise ImportError("earthengine-api not installed") from e

        email = sa_dict["client_email"]
        key = sa_dict["private_key"]

        # 优先用 ee.ServiceAccountCredentials（earthengine-api 内置实现）
        try:
            creds = ee.ServiceAccountCredentials(email, key)
            if project_id:
                logger.debug(
                    "Loaded service account credentials for %s (project=%s)",
                    email,
                    project_id,
                )
            return creds
        except Exception as exc:
            logger.warning(
                "ee.ServiceAccountCredentials failed (%s); falling back to google.oauth2",
                exc,
            )

        # 回退：用 google.oauth2.service_account 构造，再转 ee.Credentials
        try:
            from google.oauth2 import service_account  # type: ignore
            from google.auth.transport.requests import Request  # type: ignore

            scopes = ["https://www.googleapis.com/auth/earthengine"]
            google_creds = service_account.Credentials.from_service_account_info(
                sa_dict, scopes=scopes
            )
            google_creds.refresh(Request())
            ee_creds = ee.Credentials(google_creds.token, None)
            return ee_creds
        except ImportError:
            logger.warning(
                "google-auth not installed; returning raw service_account dict "
                "(ee.Initialize may fail if it cannot self-resolve)"
            )
            return sa_dict

    @staticmethod
    def load_service_account_from_file(key_path: str | Path) -> tuple[Any, str, str]:
        """从文件加载，返回 (credentials, account_email, project_id)。"""
        path = Path(key_path)
        if not path.exists():
            raise FileNotFoundError(f"service_account key file not found: {key_path}")
        sa_dict = json.loads(path.read_text(encoding="utf-8"))
        email = sa_dict.get("client_email", path.stem)
        project_id = sa_dict.get("project_id", "")
        creds = GeeCredentialsLoader.load_service_account_credentials(sa_dict)
        return creds, email, project_id

    @staticmethod
    def test_credentials(
        credentials: Any, project_id: Optional[str] = None
    ) -> tuple[bool, str]:
        """测试凭证是否可用，返回 (success, message)。

        注意：此方法会调用 ee.Initialize 并请求一个简单 API，可能产生网络请求。
        测试完成后会 ee.Reset() 以避免污染后续运行时状态。
        """
        try:
            import ee
        except ImportError as e:  # pragma: no cover
            return False, f"earthengine-api not installed: {e}"

        try:
            ee.Initialize(credentials=credentials, project=project_id)
            _ = ee.Number(1).getInfo()
            return True, "GEE credentials valid"
        except Exception as e:
            return False, f"GEE credentials test failed: {e}"
        finally:
            try:
                ee.Reset()
            except Exception:
                pass
