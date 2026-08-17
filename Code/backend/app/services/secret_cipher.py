"""共享 AES-GCM 密文原语 —— 全部凭据存储的唯一加解密实现点。

收敛前各仓库内联了五份语义相近但分支不一致的 AESGCM 代码：
api_keys / gee_credentials / weather_providers（三分支明文回退）、
remote_storage_credentials（无通用异常回退）、portal_credentials（``plain`` IV 标记）。

统一语义：
- ``aesgcm_encrypt`` / ``aesgcm_decrypt``：裸原语，任何错误直接抛出。
- ``encrypt_secret``：三分支（无 key / cryptography 缺失 / 加密错误），
  ``require_encryption=True`` 时 fail-closed 抛 RuntimeError，否则仅 development
  允许 ``(plaintext, "")`` 明文回退。
- ``decrypt_secret``：空 IV 在生产拒绝（fail-closed）；无 key + 非空 IV 在生产
  同样拒绝（F10 补强，旧行为中 ②③④ 会把密文当明文返回）；development 保持
  明文 round-trip。解密失败统一记录日志后抛出。

版本前缀（``v1:``）、空串短路、``plain`` 标记等存储层约定保留在各自仓库中，
不进入本模块。
"""

from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)


def aesgcm_encrypt(key_hex: str, plaintext: str) -> tuple[str, str]:
    """AES-GCM-256 加密，随机 12-byte IV，返回 ``(ciphertext_b64, iv_b64)``。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key_bytes = bytes.fromhex(key_hex)
    iv = os.urandom(12)
    ct = AESGCM(key_bytes).encrypt(iv, plaintext.encode("utf-8"), None)
    return base64.b64encode(ct).decode("ascii"), base64.b64encode(iv).decode("ascii")


def aesgcm_decrypt(key_hex: str, ciphertext_b64: str, iv_b64: str) -> str:
    """AES-GCM-256 解密，认证失败（密钥轮换/篡改）抛 ``InvalidTag``。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key_bytes = bytes.fromhex(key_hex)
    pt = AESGCM(key_bytes).decrypt(
        base64.b64decode(iv_b64), base64.b64decode(ciphertext_b64), None
    )
    return pt.decode("utf-8")


def encrypt_secret(
    plaintext: str,
    *,
    key: str,
    require_encryption: bool,
    label: str = "secret",
) -> tuple[str, str]:
    """统一三分支密文写入。

    - 无 key：``require_encryption`` → RuntimeError；否则 dev 明文 ``(plaintext, "")``。
    - cryptography 包缺失：同上（RuntimeError / 明文回退）。
    - 加密异常：``require_encryption`` → RuntimeError（链上原始异常）；
      否则 dev 明文回退（记 error 日志）。
    """
    if not key:
        if require_encryption:
            raise RuntimeError(
                "Cannot store secrets without "
                "BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY outside development."
            )
        logger.error(
            "%s encryption key not set, storing plaintext (development only)", label
        )
        return plaintext, ""
    try:
        return aesgcm_encrypt(key, plaintext)
    except ImportError:
        if require_encryption:
            raise RuntimeError(
                "cryptography package required to encrypt secrets"
            ) from None
        logger.warning("cryptography not installed, storing plaintext")
        return plaintext, ""
    except RuntimeError:
        raise
    except Exception as e:
        if require_encryption:
            raise RuntimeError(f"Encryption failed for {label}: {e}") from e
        logger.error("Encryption failed for %s, storing plaintext: %s", label, e)
        return plaintext, ""


def decrypt_secret(
    ciphertext: str,
    iv: str,
    *,
    key: str,
    require_encryption: bool,
    label: str = "secret",
) -> str:
    """统一密文读取（含空 IV / 无 key 的 fail-closed 策略）。

    - 空 IV：生产环境抛 RuntimeError（``empty-IV``）；dev 返回密文原样（明文回退）。
    - 无 key + 非空 IV：生产环境抛 RuntimeError；dev 返回密文原样。
    - 解密失败：记录日志后原样抛出（含密钥轮换后的 ``InvalidTag``）。
    """
    from app.services.effective_config import refuse_empty_iv_outside_development

    refuse_empty_iv_outside_development(iv)
    if not key or not iv:
        if require_encryption:
            raise RuntimeError(
                "Cannot decrypt secret without encryption key outside development."
            )
        return ciphertext
    try:
        return aesgcm_decrypt(key, ciphertext, iv)
    except Exception as e:
        logger.error("Decryption failed for %s: %s", label, e)
        raise
