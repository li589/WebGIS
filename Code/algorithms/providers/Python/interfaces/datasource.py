"""
数据源适配器接口与实现。

提供数据发现的抽象接口，以及基于 StorageBackend 的具体实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from contracts.data import DataBundle, DataRequest

if TYPE_CHECKING:
    from storage.base import StorageBackend


@dataclass(slots=True)
class DataAsset:
    uri: str
    dataset_name: str
    variables: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class DataSourceAdapter(Protocol):
    """数据源适配器协议

    定义数据发现、解析、获取、物化等操作的接口。
    平台接入方需要实现此协议。
    """

    def discover(self, request: DataRequest) -> list[DataAsset]:
        """发现符合条件的数据资源"""
        ...

    def resolve(self, request: DataRequest) -> DataBundle:
        """解析数据请求，生成数据Bundle"""
        ...

    def acquire(self, bundle: DataBundle) -> DataBundle:
        """获取数据，将远程数据下载到本地"""
        ...

    def materialize(self, bundle: DataBundle) -> DataBundle:
        """物化数据Bundle，标记为已完成"""
        ...


class DataSourceAdapterImpl:
    """数据源适配器实现

    基于 StorageBackend 抽象层实现数据源操作，
    支持本地文件系统和 MinIO 对象存储两种后端。
    """

    def __init__(
        self,
        storage_backend: StorageBackend | None = None,
        data_root: str = "data",
    ) -> None:
        """初始化数据源适配器

        Args:
            storage_backend: 存储后端实例，如果为 None 则自动创建
            data_root: 数据根目录相对路径，默认 "data"
        """
        if storage_backend is None:
            from storage import get_storage_backend

            storage_backend = get_storage_backend()
        self._storage = storage_backend
        self._data_root = data_root

    @property
    def storage_backend(self) -> StorageBackend:
        """获取存储后端实例"""
        return self._storage

    def discover(self, request: DataRequest) -> list[DataAsset]:
        """发现符合条件的数据资源

        扫描数据根目录，根据数据集名称和变量过滤条件查找匹配的文件。

        Args:
            request: 数据请求

        Returns:
            匹配的数据资产列表
        """
        assets: list[DataAsset] = []
        dataset_dir = self._storage.resolve_path(self._data_root, request.dataset_name)

        if not self._storage.exists(dataset_dir):
            return assets

        try:
            items = self._storage.list_dir(dataset_dir)
        except (FileNotFoundError, NotADirectoryError):
            return assets

        for item in items:
            item_path = self._storage.resolve_path(dataset_dir, item)
            # 跳过子目录
            if self._storage.exists(item_path) and not self._self_is_file(item_path):
                sub_items = self._storage.list_dir(item_path)
                for sub_item in sub_items:
                    sub_path = self._storage.resolve_path(item_path, sub_item)
                    if self._self_is_file(sub_path):
                        uri = self._storage.get_uri(sub_path)
                        asset = DataAsset(
                            uri=uri,
                            dataset_name=request.dataset_name,
                            variables=request.variables,
                            metadata={
                                "path": sub_path,
                                "parent": item,
                            },
                        )
                        assets.append(asset)
            elif self._self_is_file(item_path):
                uri = self._storage.get_uri(item_path)
                asset = DataAsset(
                    uri=uri,
                    dataset_name=request.dataset_name,
                    variables=request.variables,
                    metadata={"path": item_path},
                )
                assets.append(asset)

        return assets

    def resolve(self, request: DataRequest) -> DataBundle:
        """解析数据请求，生成数据Bundle

        根据请求信息创建 DataBundle，包含可用的本地路径或远程引用。

        Args:
            request: 数据请求

        Returns:
            数据Bundle
        """
        import uuid

        assets = self.discover(request)
        local_paths: list[str] = []
        remote_refs: list[str] = []

        for asset in assets:
            if asset.uri.startswith("file://"):
                local_paths.append(asset.uri)
            else:
                remote_refs.append(asset.uri)

        return DataBundle(
            bundle_id=str(uuid.uuid4()),
            dataset_name=request.dataset_name,
            variables=request.variables,
            time_range=request.time_range,
            storage_mode="local" if local_paths else "remote",
            local_paths=local_paths,
            remote_refs=remote_refs,
            metadata={
                "assets": [
                    {"uri": a.uri, "variables": a.variables, "metadata": a.metadata}
                    for a in assets
                ],
            },
            is_materialized=False,
        )

    def acquire(self, bundle: DataBundle) -> DataBundle:
        """获取数据，将远程数据下载到本地

        对于 s3:// 等远程 URI，尝试下载到本地存储。
        对于 file:// 本地路径，直接使用。

        Args:
            bundle: 数据Bundle

        Returns:
            更新后的DataBundle
        """
        acquired_paths: list[str] = []
        failed_refs: list[str] = []

        for ref in bundle.remote_refs:
            try:
                # 从 URI 中提取路径
                if ref.startswith("s3://"):
                    local_path = self._download_from_s3(ref)
                    acquired_paths.append(local_path)
                else:
                    # 其他未知协议，保留原引用
                    failed_refs.append(ref)
            except Exception:
                failed_refs.append(ref)

        # 合并本地路径
        all_local = bundle.local_paths + acquired_paths
        # 更新 remote_refs，移除已成功获取的
        bundle.remote_refs = failed_refs
        bundle.local_paths = all_local

        if all_local:
            bundle.storage_mode = "local"

        return bundle

    def materialize(self, bundle: DataBundle) -> DataBundle:
        """物化数据Bundle

        标记Bundle为已完成状态，确保所有数据路径可访问。

        Args:
            bundle: 数据Bundle

        Returns:
            物化后的DataBundle
        """
        # 验证所有本地路径可访问
        valid_paths: list[str] = []
        for path in bundle.local_paths:
            # 从 URI 中提取逻辑路径
            logical_path = self._uri_to_logical_path(path)
            if logical_path and self._storage.exists(logical_path):
                valid_paths.append(path)

        bundle.local_paths = valid_paths
        bundle.is_materialized = True

        return bundle

    def read_data(self, path: str) -> bytes:
        """读取数据文件

        通过存储后端读取文件内容。

        Args:
            path: 文件路径（逻辑路径或 URI）

        Returns:
            文件二进制内容
        """
        logical_path = self._uri_to_logical_path(path)
        if logical_path:
            return self._storage.read_bytes(logical_path)
        return self._storage.read_bytes(path)

    def write_data(self, path: str, data: bytes) -> str:
        """写入数据文件

        通过存储后端写入文件内容。

        Args:
            path: 文件路径（逻辑路径）
            data: 二进制数据

        Returns:
            写入后的 URI
        """
        return self._storage.write_bytes(path, data)

    def _uri_to_logical_path(self, uri: str) -> str | None:
        """将 URI 转换为逻辑路径

        Args:
            uri: 文件 URI（file:// 或 s3://）

        Returns:
            逻辑路径，如果无法解析则返回 None
        """
        if uri.startswith("file://"):
            # 移除 file:// 前缀，转换为路径
            # Windows: file:///D:/path -> D:/path
            # Unix: file:///path -> /path
            path = uri[7:] if uri.startswith("file:///") else uri[5:]
            return path
        elif uri.startswith("s3://"):
            # s3://bucket/path -> path
            parts = uri[5:].split("/", 1)
            if len(parts) > 1:
                return parts[1]
            return None
        return None

    def _self_is_file(self, path: str) -> bool:
        """判断路径是否为文件

        Args:
            path: 逻辑路径

        Returns:
            是文件返回 True
        """
        # 先尝试列出目录：成功则说明是目录
        try:
            self._storage.list_dir(path)
            return False
        except Exception:
            pass

        # 无法列出目录，尝试读取文件
        try:
            self._storage.read_bytes(path)
            return True
        except Exception:
            return False

    def _download_from_s3(self, s3_uri: str) -> str:
        """从 S3 下载文件到本地临时目录

        Args:
            s3_uri: S3 URI (s3://bucket/path)

        Returns:
            本地文件 URI
        """
        # 解析 S3 URI
        if not s3_uri.startswith("s3://"):
            raise ValueError(f"非法的 S3 URI: {s3_uri}")

        parts = s3_uri[5:].split("/", 1)
        if len(parts) < 2:
            raise ValueError(f"S3 URI 缺少路径: {s3_uri}")

        object_key = parts[1]

        # 使用 MinIOStorage 读取（假设使用同一后端）
        from storage.minio_storage import MinIOStorage
        from storage.factory import _get_minio_config

        try:
            config = _get_minio_config()
            minio_storage = MinIOStorage(
                endpoint=config["endpoint"],
                access_key=config["access_key"],
                secret_key=config["secret_key"],
                bucket=config["bucket"],
                secure=config["secure"],
            )
            data = minio_storage.read_bytes(object_key)

            # 保存到本地
            import tempfile

            temp_dir = Path(tempfile.gettempdir()) / "geodata"
            temp_dir.mkdir(parents=True, exist_ok=True)
            local_path = temp_dir / Path(object_key).name
            local_path.write_bytes(data)

            return local_path.as_uri()
        except Exception as e:
            raise RuntimeError(f"从 S3 下载失败 [{s3_uri}]: {e}") from e
