from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """Common storage abstraction for local FS and MinIO."""

    @abstractmethod
    def put(self, path: str, content: bytes) -> str:
        """存储字节内容到指定路径，返回 URI。"""
        raise NotImplementedError

    @abstractmethod
    def get(self, path: str) -> bytes:
        """从指定路径读取字节内容。"""
        raise NotImplementedError

    @abstractmethod
    def exists(self, path: str) -> bool:
        """检查路径是否存在。"""
        raise NotImplementedError

    @abstractmethod
    def delete(self, path: str) -> None:
        """删除指定路径的内容。"""
        raise NotImplementedError

    @abstractmethod
    def list(self, prefix: str = "") -> list[str]:
        """列出指定前缀下的所有内容路径。"""
        raise NotImplementedError

    @abstractmethod
    def stat(self, path: str) -> dict[str, Any]:
        """获取路径的元数据（大小、修改时间等）。"""
        raise NotImplementedError

    @abstractmethod
    def build_uri(self, path: str) -> str:
        """根据路径构建 URI。"""
        raise NotImplementedError
