"""
存储后端工厂函数。

根据环境变量配置自动选择和初始化存储后端。

存储后端配置：

BACKEND_STORAGE_BACKEND: 存储后端类型
    - "local": 本地文件系统（默认）
    - "minio": MinIO 对象存储

本地文件系统模式（BACKEND_STORAGE_BACKEND=local）：
    BACKEND_DATA_ROOT: 数据根目录（默认 ~/.geodata）
    BACKEND_OUTPUT_ROOT: 产物输出目录（默认 ~/.geooutput）

MinIO 模式（BACKEND_STORAGE_BACKEND=minio）：
    BACKEND_MINIO_ENDPOINT: MinIO 服务地址，如 "127.0.0.1:9000"
    BACKEND_MINIO_ACCESS_KEY: Access Key
    BACKEND_MINIO_SECRET_KEY: Secret Key
    BACKEND_MINIO_BUCKET: 存储桶名，默认 "geodata"
    BACKEND_MINIO_SECURE: 是否使用 HTTPS，默认 false
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from storage.base import StorageBackend
from storage.local_fs import LocalFileSystemStorage


def _get_minio_storage_class():
    """延迟导入 MinIOStorage，避免 minio 包未安装时阻塞"""
    from storage.minio_storage import MinIOStorage

    return MinIOStorage


def _resolve_local_data_root() -> Path:
    """解析本地数据根目录

    Returns:
        数据根目录 Path 对象
    """
    root_env = os.environ.get("BACKEND_DATA_ROOT", "")
    if root_env:
        root = Path(root_env).expanduser().resolve()
    else:
        root = Path.home() / ".geodata"

    # 自动创建目录（如果不存在）
    root.mkdir(parents=True, exist_ok=True)
    return root


def _get_minio_config() -> dict:
    """从环境变量获取 MinIO 配置

    Returns:
        MinIO 配置字典

    Raises:
        ValueError: 缺少必要的环境变量
    """
    endpoint = os.environ.get("BACKEND_MINIO_ENDPOINT", "").strip()
    access_key = os.environ.get("BACKEND_MINIO_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("BACKEND_MINIO_SECRET_KEY", "").strip()
    bucket = os.environ.get("BACKEND_MINIO_BUCKET", "geodata").strip()
    secure_str = os.environ.get("BACKEND_MINIO_SECURE", "false").strip().lower()
    secure = secure_str in ("true", "1", "yes", "on")

    # 检查必要参数
    missing: list[str] = []
    if not endpoint:
        missing.append("BACKEND_MINIO_ENDPOINT")
    if not access_key:
        missing.append("BACKEND_MINIO_ACCESS_KEY")
    if not secret_key:
        missing.append("BACKEND_MINIO_SECRET_KEY")

    if missing:
        raise ValueError(
            f"MinIO 模式缺少必要配置: {', '.join(missing)}\n"
            f"请在环境变量中设置以下变量:\n"
            f"  BACKEND_MINIO_ENDPOINT   - MinIO 服务地址，如 127.0.0.1:9000\n"
            f"  BACKEND_MINIO_ACCESS_KEY - Access Key\n"
            f"  BACKEND_MINIO_SECRET_KEY - Secret Key\n"
            f"可选配置:\n"
            f"  BACKEND_MINIO_BUCKET     - 存储桶名，默认 'geodata'\n"
            f"  BACKEND_MINIO_SECURE     - 是否使用 HTTPS，默认 false"
        )

    return {
        "endpoint": endpoint,
        "access_key": access_key,
        "secret_key": secret_key,
        "bucket": bucket or "geodata",
        "secure": secure,
    }


def get_storage_backend() -> StorageBackend:
    """获取存储后端实例

    根据环境变量 BACKEND_STORAGE_BACKEND 自动选择后端类型：
    - "local": 使用本地文件系统
    - "minio": 使用 MinIO 对象存储

    自动降级机制：
    - 如果指定了 local 模式但路径不存在，fallback 到 minio 模式

    Returns:
        存储后端实例

    Raises:
        ValueError: 配置无效或缺少必要环境变量
    """
    backend_type = os.environ.get("BACKEND_STORAGE_BACKEND", "local").strip().lower()

    # 本地文件系统模式
    if backend_type == "local":
        try:
            root = _resolve_local_data_root()
            return LocalFileSystemStorage(root)
        except Exception as e:
            # 自动降级：如果本地路径不可用且 MinIO 配置存在，尝试 MinIO
            minio_available = (
                os.environ.get("BACKEND_MINIO_ENDPOINT", "").strip()
                and os.environ.get("BACKEND_MINIO_ACCESS_KEY", "").strip()
                and os.environ.get("BACKEND_MINIO_SECRET_KEY", "").strip()
            )
            if minio_available:
                print(
                    f"[警告] 本地存储后端初始化失败: {e}\n"
                    f"[提示] 自动切换到 MinIO 存储后端",
                    file=sys.stderr,
                )
                return _create_minio_backend()
            raise

    # MinIO 对象存储模式
    if backend_type == "minio":
        try:
            return _create_minio_backend()
        except Exception as e:
            print(
                f"[警告] MinIO 存储后端初始化失败: {e}\n"
                f"[提示] 自动回退到本地文件系统",
                file=sys.stderr,
            )
            return LocalFileSystemStorage(_resolve_local_data_root())

    # 未知类型，默认使用本地
    print(
        f"[警告] 未知存储后端类型 '{backend_type}'，默认使用本地文件系统",
        file=sys.stderr,
    )
    return LocalFileSystemStorage(_resolve_local_data_root())


def _create_minio_backend() -> "MinIOStorage":  # noqa: F821  # MinIOStorage 经工厂延迟解析，注解为前向引用字符串
    """创建 MinIO 存储后端实例

    Returns:
        MinIOStorage 实例
    """
    try:
        MinIOStorage = _get_minio_storage_class()
    except (ImportError, ModuleNotFoundError):
        raise ImportError(
            "MinIO storage backend requires the 'minio' package. Install: pip install minio"
        )
    config = _get_minio_config()
    return MinIOStorage(
        endpoint=config["endpoint"],
        access_key=config["access_key"],
        secret_key=config["secret_key"],
        bucket=config["bucket"],
        secure=config["secure"],
    )


def get_output_storage_backend() -> StorageBackend:
    """获取产物输出存储后端

    产物输出使用独立的根目录配置。

    Returns:
        产物输出存储后端实例
    """
    backend_type = os.environ.get("BACKEND_STORAGE_BACKEND", "local").strip().lower()

    if backend_type == "minio":
        # MinIO 模式下，产物也写入同一存储桶的不同前缀
        return _create_minio_backend()

    # 本地模式：使用 OUTPUT_ROOT 配置
    output_root_env = os.environ.get("BACKEND_OUTPUT_ROOT", "")
    if output_root_env:
        root = Path(output_root_env).expanduser().resolve()
    else:
        root = Path.home() / ".geooutput"

    root.mkdir(parents=True, exist_ok=True)
    return LocalFileSystemStorage(root)
