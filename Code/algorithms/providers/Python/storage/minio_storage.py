"""
MinIO 对象存储后端实现。

使用 minio Python SDK 提供 S3 兼容的对象存储操作。
"""

from __future__ import annotations

from minio import Minio
from minio.error import S3Error

from storage.base import StorageBackend


class MinIOStorage(StorageBackend):
    """MinIO / S3 兼容对象存储后端"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        """初始化 MinIO 存储后端

        Args:
            endpoint: MinIO 服务地址，如 "127.0.0.1:9000"
            access_key: Access Key
            secret_key: Secret Key
            bucket: 存储桶名称
            secure: 是否使用 HTTPS 连接，默认 False
        """
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._secure = secure
        self._client: Minio | None = None

    @property
    def bucket(self) -> str:
        """返回存储桶名称"""
        return self._bucket

    @property
    def endpoint(self) -> str:
        """返回服务端点"""
        return self._endpoint

    def _get_client(self) -> Minio:
        """获取或创建 MinIO 客户端（延迟初始化）

        Returns:
            Minio 客户端实例

        Raises:
            RuntimeError: 无法连接到 MinIO 服务
        """
        if self._client is None:
            try:
                self._client = Minio(
                    self._endpoint,
                    access_key=self._access_key,
                    secret_key=self._secret_key,
                    secure=self._secure,
                )
                # 验证连接：尝试获取存储桶信息
                self._client.bucket_exists(self._bucket)
            except S3Error as e:
                raise RuntimeError(
                    f"MinIO 连接失败: {e}\n"
                    f"请检查以下几点:\n"
                    f"  - 服务地址是否正确: {self._endpoint}\n"
                    f"  - Access Key / Secret Key 是否有效\n"
                    f"  - 存储桶 '{self._bucket}' 是否存在"
                ) from e
            except Exception as e:
                raise RuntimeError(
                    f"MinIO 连接失败: {e}\n"
                    f"服务地址: {self._endpoint}\n"
                    f"请确保 MinIO 服务正在运行且网络可达。"
                ) from e
        return self._client

    def _normalize_path(self, path: str) -> str:
        """标准化路径

        Args:
            path: 原始路径

        Returns:
            标准化后的路径（无前后斜杠）
        """
        return path.strip("/").replace("\\", "/")

    def _safe_path(self, path: str) -> str:
        """验证路径安全性

        Args:
            path: 逻辑路径

        Returns:
            标准化后的安全路径

        Raises:
            ValueError: 路径包含不安全的遍历序列
        """
        normalized = self._normalize_path(path)
        parts = normalized.split("/")
        if ".." in parts:
            raise ValueError(f"路径不安全，包含非法遍历序列: {path}")
        return normalized

    def resolve_path(self, *parts: str) -> str:
        """拼接逻辑路径

        Args:
            *parts: 路径片段

        Returns:
            拼接后的路径字符串
        """
        joined = "/".join(
            p.strip("/").replace("\\", "/") for p in parts if p.strip("/")
        )
        return joined

    def exists(self, path: str) -> bool:
        """检查对象是否存在

        Args:
            path: 对象路径

        Returns:
            对象存在返回 True
        """
        try:
            safe_path = self._safe_path(path)
            self._get_client().stat_object(self._bucket, safe_path)
            return True
        except (S3Error, RuntimeError):
            # 对象不存在时 stat_object 会抛出 S3Error
            return False
        except Exception:
            return False

    def list_dir(self, path: str) -> list[str]:
        """列出目录下的所有对象（模拟目录列表）

        在 MinIO/S3 中，所有对象都是扁平的键值对。
        此方法通过 prefix 匹配模拟目录结构：
        - 以指定 prefix 开头、以 "/" 分隔的对象键视为子目录或文件
        - 列表只返回直接子项（不含递归）

        Args:
            path: 目录路径

        Returns:
            直接子项名称列表（文件和目录）
        """
        safe_path = self._safe_path(path)
        prefix = safe_path + "/" if safe_path else ""

        try:
            client = self._get_client()
            objects = client.list_objects(
                self._bucket,
                prefix=prefix,
                recursive=False,
            )

            seen: set[str] = set()
            result: list[str] = []

            for obj in objects:
                # obj.object_name 格式如 "dir/file.txt" 或 "dir/subdir/"
                key = obj.object_name
                if not key.startswith(prefix):
                    continue

                # 提取相对于 prefix 的部分
                relative = key[len(prefix) :]
                if not relative:
                    continue

                # 获取第一层级的名称（文件或目录）
                if "/" in relative:
                    # 子目录形式: "subdir/file.txt"
                    first_part = relative.split("/")[0]
                    if first_part and first_part not in seen:
                        seen.add(first_part)
                        result.append(first_part)
                else:
                    # 直接文件: "file.txt"
                    if relative not in seen:
                        seen.add(relative)
                        result.append(relative)

            return sorted(result)
        except S3Error:
            return []
        except RuntimeError:
            # 连接失败，返回空列表
            return []

    def read_bytes(self, path: str) -> bytes:
        """读取对象内容

        Args:
            path: 对象路径

        Returns:
            对象二进制内容

        Raises:
            FileNotFoundError: 对象不存在
        """
        safe_path = self._safe_path(path)
        try:
            client = self._get_client()
            response = client.get_object(self._bucket, safe_path)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            if e.code == "NoSuchKey":
                raise FileNotFoundError(f"对象不存在: {path}") from e
            raise

    def write_bytes(self, path: str, data: bytes) -> str:
        """写入对象内容

        自动处理必要的目录前缀结构。

        Args:
            path: 对象路径
            data: 二进制数据

        Returns:
            写入后的标准化 URI
        """
        safe_path = self._safe_path(path)
        try:
            client = self._get_client()
            # 计算数据大小
            data_size = len(data)
            # 使用 put_object 上传，支持大数据
            from io import BytesIO

            client.put_object(
                self._bucket,
                safe_path,
                BytesIO(data),
                data_size,
            )
            return self.get_uri(path)
        except S3Error as e:
            raise RuntimeError(f"写入对象失败 [{path}]: {e}") from e

    def get_uri(self, path: str) -> str:
        """获取标准化 s3:// URI

        Args:
            path: 对象路径

        Returns:
            s3://{bucket}/{path} 格式的 URI
        """
        safe_path = self._safe_path(path)
        return f"s3://{self._bucket}/{safe_path}"
