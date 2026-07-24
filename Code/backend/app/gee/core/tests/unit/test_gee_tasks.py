import json

import pytest

from webgis_gee.application.services import WorkflowService
from webgis_gee.config.settings import Settings
from webgis_gee.domain.models import EdgeSpec, NodeSpec, WorkflowDefinition
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


class FakeEeData:
    def __init__(self, state: str) -> None:
        self._state = state

    def getTaskStatus(self, task_id: str):
        return [{"id": task_id, "state": self._state}]


class FakeEeModule:
    def __init__(self, state: str) -> None:
        self.data = FakeEeData(state)


def test_poll_export_task_reads_manifest_only_state(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    manifest_path = tmp_path / "exports" / "demo.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "workflow_id": "demo",
                "task_ref": {
                    "started": False,
                    "status": "manifest_created",
                },
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    result = service.poll_export_task(manifest_uri=f"file://{manifest_path}")

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "manifest_created"
    assert result["state"] == "LOCAL_ONLY"
    assert saved_manifest["task_status"]["status"] == "manifest_created"


def test_poll_export_task_queries_gee_status_and_updates_manifest(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    manifest_path = tmp_path / "exports" / "submitted.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "workflow_id": "demo",
                "task_ref": {
                    "started": True,
                    "status": "submitted",
                    "task_id": "task-1",
                },
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    result = service.poll_export_task(
        manifest_uri=f"file://{manifest_path}",
        gee_module=FakeEeModule("COMPLETED"),
    )

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["state"] == "COMPLETED"
    assert saved_manifest["task_ref"]["status"] == "completed"
    assert saved_manifest["task_status"]["raw"]["state"] == "COMPLETED"


def test_poll_export_task_reads_and_updates_s3_manifest() -> None:
    backend = MinioStorageBackend(
        endpoint="localhost:9000",
        access_key="access",
        secret_key="secret",
        bucket="gee",
        client=FakeMinioClient(),
    )
    service = WorkflowService(
        settings=Settings(storage_backend="minio"),
        storage_backend=backend,
    )
    manifest_uri = backend.put(
        "exports/submitted.json",
        json.dumps(
            {
                "workflow_id": "demo",
                "task_ref": {
                    "started": True,
                    "status": "submitted",
                    "task_id": "task-1",
                },
            },
            ensure_ascii=True,
        ).encode("utf-8"),
    )

    result = service.poll_export_task(
        manifest_uri=manifest_uri,
        gee_module=FakeEeModule("RUNNING"),
    )

    saved_manifest = json.loads(backend.get("exports/submitted.json").decode("utf-8"))
    assert result["status"] == "running"
    assert result["state"] == "RUNNING"
    assert saved_manifest["task_ref"]["status"] == "running"
    assert saved_manifest["task_status"]["raw"]["state"] == "RUNNING"


def test_minio_export_workflow_and_polling_share_same_storage_backend() -> None:
    backend = MinioStorageBackend(
        endpoint="localhost:9000",
        access_key="access",
        secret_key="secret",
        bucket="gee",
        client=FakeMinioClient(),
    )
    service = WorkflowService(
        settings=Settings(storage_backend="minio"),
        storage_backend=backend,
    )
    workflow = WorkflowDefinition(
        workflow_id="export-minio",
        nodes=[
            NodeSpec(
                node_id="source", node_type="literal", params={"value": "fake-image"}
            ),
            NodeSpec(
                node_id="export",
                node_type="gee_export_image",
                params={
                    "destination": "cloud_storage",
                    "bucket": "gee",
                    "file_name_prefix": "image_export",
                    "start_task": False,
                },
            ),
        ],
        edges=[
            EdgeSpec(
                source_node_id="source",
                source_port="value",
                target_node_id="export",
                target_port="image",
            )
        ],
    )

    run_result = service.execute_workflow(workflow)
    poll_result = service.poll_export_task(
        manifest_uri=run_result.outputs["export.manifest_uri"]
    )

    manifest_key = run_result.outputs["export.manifest_uri"].removeprefix("s3://gee/")
    saved_manifest = json.loads(backend.get(manifest_key).decode("utf-8"))
    assert run_result.outputs["export.manifest_uri"].startswith("s3://gee/")
    assert poll_result["status"] == "manifest_created"
    assert saved_manifest["task_status"]["state"] == "LOCAL_ONLY"


def test_poll_export_task_rejects_s3_manifest_bucket_mismatch() -> None:
    backend = MinioStorageBackend(
        endpoint="localhost:9000",
        access_key="access",
        secret_key="secret",
        bucket="gee",
        client=FakeMinioClient(),
    )
    service = WorkflowService(
        settings=Settings(storage_backend="minio"),
        storage_backend=backend,
    )

    with pytest.raises(ValueError, match="does not match configured backend bucket"):
        service.poll_export_task(manifest_uri="s3://other/exports/submitted.json")


def test_poll_export_task_rejects_file_manifest_outside_local_storage_root(
    tmp_path,
) -> None:
    storage_root = tmp_path / "storage"
    service = WorkflowService(
        settings=Settings(
            storage_backend="local", local_storage_root=str(storage_root)
        ),
    )
    outside_manifest = tmp_path / "outside.json"
    outside_manifest.write_text(
        json.dumps(
            {
                "workflow_id": "outside-demo",
                "task_ref": {"started": False, "status": "manifest_created"},
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="configured local storage root"):
        service.poll_export_task(manifest_uri=f"file://{outside_manifest}")


def test_poll_export_task_rejects_file_manifest_outside_exports_directory(
    tmp_path,
) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    manifest_path = tmp_path / "other" / "submitted.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "workflow_id": "other-demo",
                "task_ref": {"started": False, "status": "manifest_created"},
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="managed exports directory"):
        service.poll_export_task(manifest_uri=f"file://{manifest_path}")


def test_poll_export_task_rejects_s3_manifest_outside_exports_prefix() -> None:
    backend = MinioStorageBackend(
        endpoint="localhost:9000",
        access_key="access",
        secret_key="secret",
        bucket="gee",
        client=FakeMinioClient(),
    )
    service = WorkflowService(
        settings=Settings(storage_backend="minio"),
        storage_backend=backend,
    )

    with pytest.raises(ValueError, match="managed exports/ prefix"):
        service.poll_export_task(manifest_uri="s3://gee/private/submitted.json")
