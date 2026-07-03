"""
存储后端抽象基类。

定义统一的文件存储接口，支持本地文件系统、MinIO 等多种后端实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """存储后端抽象基类"""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """检查路径是否存在

        Args:
            path: 存储路径（逻辑路径，相对于后端根目录）

        Returns:
            路径存在返回 True，否则返回 False
        """

    @abstractmethod
    def list_dir(self, path: str) -> list[str]:
        """列出目录下所有文件和子目录名称（不含递归）

        Args:
            path: 目录路径

        Returns:
            文件和子目录名称列表（相对路径，不含前缀斜杠）
        """

    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """读取文件内容

        Args:
            path: 文件路径

        Returns:
            文件二进制内容

        Raises:
            FileNotFoundError: 文件不存在
        """

    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> str:
        """写入文件内容

        Args:
            path: 文件路径
            data: 二进制数据

        Returns:
            写入后的标准化 URI
        """

    @abstractmethod
    def get_uri(self, path: str) -> str:
        """获取文件的标准化 URI

        Args:
            path: 存储路径

        Returns:
            标准化 URI（file:// 或 s3:// 前缀）
        """

    @abstractmethod
    def resolve_path(self, *parts: str) -> str:
        """拼接逻辑路径

        将多个路径片段拼接为一个规范化路径字符串。

        Args:
            *parts: 路径片段

        Returns:
            拼接后的路径字符串
        """

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """读取文本文件

        Args:
            path: 文件路径
            encoding: 字符编码，默认 UTF-8

        Returns:
            文件文本内容
        """
        return self.read_bytes(path).decode(encoding)

    def write_text(self, path: str, text: str, encoding: str = "utf-8") -> str:
        """写入文本文件

        Args:
            path: 文件路径
            text: 文本内容
            encoding: 字符编码，默认 UTF-8

        Returns:
            写入后的标准化 URI
        """
        return self.write_bytes(path, text.encode(encoding))
