import pytest

from webgis_gee.config.settings import Settings
from webgis_gee.runtime.exceptions import StorageOperationError
from webgis_gee.storage.factory import create_storage_backend
from webgis_gee.storage.local import LocalStorageBackend
from webgis_gee.storage.minio import MinioStorageBackend


class FakeObject:
    def __init__(self, object_name: str) -> None:
        self.object_name = object_name


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


class FakeStat:
    def __init__(self, size: int) -> None:
        self.size = size
        self.etag = "etag"
        self.last_modified = "now"


class FakeMinioClient:
    def __init__(self) -> None:
        self.bucket_created = False
        self.objects: dict[str, bytes] = {}

    def bucket_exists(self, bucket: str) -> bool:
        return self.bucket_created

    def make_bucket(self, bucket: str) -> None:
        self.bucket_created = True

    def put_object(self, bucket: str, object_name: str, data, length: int) -> None:
        self.objects[object_name] = data.read(length)

    def get_object(self, bucket: str, object_name: str) -> FakeResponse:
        return FakeResponse(self.objects[object_name])

    def stat_object(self, bucket: str, object_name: str) -> FakeStat:
        return FakeStat(len(self.objects[object_name]))

    def remove_object(self, bucket: str, object_name: str) -> None:
        self.objects.pop(object_name, None)

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = True):
        return [FakeObject(name) for name in self.objects if name.startswith(prefix)]


def test_local_storage_backend_roundtrip(tmp_path) -> None:
    backend = LocalStorageBackend(base_path=str(tmp_path))

    uri = backend.put("demo/result.txt", b"hello")

    assert uri.startswith("file://")
    assert backend.exists("demo/result.txt")
    assert backend.get("demo/result.txt") == b"hello"
    assert backend.list("demo") == ["demo/result.txt"]


def test_local_storage_backend_rejects_path_escape(tmp_path) -> None:
    backend = LocalStorageBackend(base_path=str(tmp_path))

    with pytest.raises(StorageOperationError, match="path escapes storage root"):
        backend.put("../escape.txt", b"bad")


def test_minio_storage_backend_roundtrip() -> None:
    client = FakeMinioClient()
    backend = MinioStorageBackend(
        endpoint="localhost:9000",
        access_key="access",
        secret_key="secret",
        bucket="gee",
        client=client,
    )

    uri = backend.put("exports/demo.json", b"{}")

    assert uri == "s3://gee/exports/demo.json"
    assert backend.exists("exports/demo.json")
    assert backend.get("exports/demo.json") == b"{}"
    assert backend.list("exports") == ["exports/demo.json"]


def test_storage_factory_returns_local_backend(tmp_path) -> None:
    settings = Settings(storage_backend="local", local_storage_root=str(tmp_path))

    backend = create_storage_backend(settings)

    assert isinstance(backend, LocalStorageBackend)
