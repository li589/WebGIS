"""
存储抽象层模块。

提供统一的文件存储接口，支持本地文件系统（LocalFileSystemStorage）
和 MinIO 对象存储（MinIOStorage）两种后端实现。

使用工厂函数 get_storage_backend() 自动根据环境变量选择后端。

环境变量配置：

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

from storage.base import StorageBackend
from storage.factory import get_output_storage_backend, get_storage_backend
from storage.local_fs import LocalFileSystemStorage

# 延迟导入 MinIOStorage，避免 minio 包未安装时阻塞整个模块
try:
    from storage.minio_storage import MinIOStorage
except ImportError:
    MinIOStorage = None  # type: ignore

__all__ = [
    "StorageBackend",
    "LocalFileSystemStorage",
    "MinIOStorage",
    "get_storage_backend",
    "get_output_storage_backend",
]
