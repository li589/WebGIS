"""
本地文件系统存储后端实现。

使用 pathlib.Path 提供跨平台的文件系统操作能力。
"""

from __future__ import annotations

import os
from pathlib import Path

from storage.base import StorageBackend


class LocalFileSystemStorage(StorageBackend):
    """本地文件系统存储后端"""

    def __init__(self, root: Path) -> None:
        """初始化本地文件系统存储后端

        Args:
            root: 数据根目录
        """
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        """返回根目录路径"""
        return self._root

    def _to_absolute(self, path: str) -> Path:
        """将逻辑路径转换为绝对路径，并进行安全检查

        Args:
            path: 逻辑路径

        Returns:
            绝对路径

        Raises:
            ValueError: 路径包含不安全的路径遍历尝试
        """
        # 规范化路径：处理正斜杠、反斜杠分隔符
        normalized = Path(path.replace("\\", "/"))

        # 安全检查：防止路径遍历攻击
        # 如果标准化后的路径以 ".." 开头，则可能存在安全风险
        parts = normalized.parts
        if ".." in parts:
            raise ValueError(f"路径不安全，包含非法遍历序列: {path}")

        # 转换为相对于 root 的绝对路径
        absolute = (self._root / normalized).resolve()

        # 确保结果路径在 root 目录范围内
        try:
            absolute.relative_to(self._root)
        except ValueError:
            raise ValueError(f"路径越界，超出根目录范围: {path}")

        return absolute

    def resolve_path(self, *parts: str) -> str:
        """拼接逻辑路径

        Args:
            *parts: 路径片段

        Returns:
            规范化后的路径字符串
        """
        joined = "/".join(p.strip("/").replace("\\", "/") for p in parts if p.strip("/"))
        return joined

    def exists(self, path: str) -> bool:
        """检查路径是否存在

        Args:
            path: 逻辑路径

        Returns:
            路径存在返回 True
        """
        try:
            return self._to_absolute(path).exists()
        except ValueError:
            # 路径不合法（包含 .. 等）也视为不存在
            return False

    def list_dir(self, path: str) -> list[str]:
        """列出目录下所有文件和子目录

        Args:
            path: 目录逻辑路径

        Returns:
            文件和子目录名称列表

        Raises:
            NotADirectoryError: 路径不是目录
        """
        abs_path = self._to_absolute(path)
        if not abs_path.is_dir():
            raise NotADirectoryError(f"路径不是目录: {path}")

        result: list[str] = []
        for item in abs_path.iterdir():
            result.append(item.name)
        return sorted(result)

    def read_bytes(self, path: str) -> bytes:
        """读取文件内容

        Args:
            path: 文件逻辑路径

        Returns:
            文件二进制内容

        Raises:
            FileNotFoundError: 文件不存在
        """
        abs_path = self._to_absolute(path)
        if not abs_path.is_file():
            raise FileNotFoundError(f"文件不存在: {path}")
        return abs_path.read_bytes()

    def write_bytes(self, path: str, data: bytes) -> str:
        """写入文件内容

        自动创建父目录。

        Args:
            path: 文件逻辑路径
            data: 二进制数据

        Returns:
            写入后的标准化 URI
        """
        abs_path = self._to_absolute(path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)
        return self.get_uri(path)

    def get_uri(self, path: str) -> str:
        """获取标准化 file:// URI

        Args:
            path: 逻辑路径

        Returns:
            file:// URI
        """
        # 将逻辑路径转换为绝对路径，确保 URI 正确
        abs_path = self._to_absolute(path)
        # 使用 pathlib 生成规范化的 file:// URI
        uri = abs_path.as_uri()
        return uri
