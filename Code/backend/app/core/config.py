from dataclasses import dataclass, field
import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOW_STATE_DIR = BACKEND_ROOT / ".data" / "workflow_state"
DEFAULT_LOG_DIR = BACKEND_ROOT / ".data" / "logs"
DEFAULT_ARTIFACT_DIR = BACKEND_ROOT / ".data" / "artifacts"
DEFAULT_CACHE_DIR = BACKEND_ROOT / ".data" / "cache"
DEFAULT_PYTHON_PROVIDER_ROOT = BACKEND_ROOT.parent / "algorithms" / "providers" / "Python"
DEFAULT_PYTHON_PROVIDER_WORKSPACE = BACKEND_ROOT / ".data" / "python_provider"


def _parse_csv_env(name: str, default: str = "") -> list[str]:
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    service_name: str = os.getenv(
        "BACKEND_SERVICE_NAME",
        "Comprehensive Geographic Data Analysis Backend",
    )
    environment: str = os.getenv("BACKEND_ENV", "development")
    host: str = os.getenv("BACKEND_HOST", "127.0.0.1")
    port: int = int(os.getenv("BACKEND_PORT", "8000"))
    reload: bool = os.getenv("BACKEND_RELOAD", "true").lower() == "true"
    workflow_executor: str = os.getenv("BACKEND_WORKFLOW_EXECUTOR", "sync")
    redis_url: str = os.getenv("BACKEND_REDIS_URL", "redis://127.0.0.1:6379/0")
    celery_broker_url: str = os.getenv("BACKEND_CELERY_BROKER_URL", redis_url)
    celery_result_backend: str = os.getenv("BACKEND_CELERY_RESULT_BACKEND", redis_url)
    celery_task_always_eager: bool = os.getenv("BACKEND_CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true"
    workflow_state_dir: str = os.getenv(
        "BACKEND_WORKFLOW_STATE_DIR",
        str(DEFAULT_WORKFLOW_STATE_DIR),
    )
    python_provider_root: str = os.getenv(
        "BACKEND_PYTHON_PROVIDER_ROOT",
        str(DEFAULT_PYTHON_PROVIDER_ROOT),
    )
    python_provider_workspace: str = os.getenv(
        "BACKEND_PYTHON_PROVIDER_WORKSPACE",
        str(DEFAULT_PYTHON_PROVIDER_WORKSPACE),
    )
    log_dir: str = os.getenv("BACKEND_LOG_DIR", str(DEFAULT_LOG_DIR))
    log_level: str = os.getenv("BACKEND_LOG_LEVEL", "INFO")
    result_artifact_dir: str = os.getenv(
        "BACKEND_RESULT_ARTIFACT_DIR",
        str(DEFAULT_ARTIFACT_DIR),
    )
    cache_dir: str = os.getenv("BACKEND_CACHE_DIR", str(DEFAULT_CACHE_DIR))
    cache_default_ttl_seconds: int = int(os.getenv("BACKEND_CACHE_DEFAULT_TTL_SECONDS", "1800"))
    object_store_backend: str = os.getenv("BACKEND_OBJECT_STORE_BACKEND", "local")
    object_store_public_base: str = os.getenv("BACKEND_OBJECT_STORE_PUBLIC_BASE", "/artifacts")
    minio_endpoint: str = os.getenv("BACKEND_MINIO_ENDPOINT", "")
    minio_access_key: str = os.getenv("BACKEND_MINIO_ACCESS_KEY", "")
    minio_secret_key: str = os.getenv("BACKEND_MINIO_SECRET_KEY", "")
    minio_bucket: str = os.getenv("BACKEND_MINIO_BUCKET", "workflow-artifacts")
    minio_secure: bool = os.getenv("BACKEND_MINIO_SECURE", "false").lower() == "true"
    result_inline_max_bytes: int = int(os.getenv("BACKEND_RESULT_INLINE_MAX_BYTES", str(128 * 1024)))
    max_active_runs: int = int(os.getenv("BACKEND_MAX_ACTIVE_RUNS", "4"))
    max_requested_outputs: int = int(os.getenv("BACKEND_MAX_REQUESTED_OUTPUTS", "6"))
    provider_max_hotspots: int = int(os.getenv("BACKEND_PROVIDER_MAX_HOTSPOTS", "200"))
    provider_max_series_points: int = int(os.getenv("BACKEND_PROVIDER_MAX_SERIES_POINTS", "240"))
    provider_table_chunk_size: int = int(os.getenv("BACKEND_PROVIDER_TABLE_CHUNK_SIZE", "100"))
    provider_series_chunk_size: int = int(os.getenv("BACKEND_PROVIDER_SERIES_CHUNK_SIZE", "120"))
    workflow_queue_realtime: str = os.getenv("BACKEND_WORKFLOW_QUEUE_REALTIME", "realtime")
    workflow_queue_standard: str = os.getenv("BACKEND_WORKFLOW_QUEUE_STANDARD", "standard")
    workflow_queue_heavy: str = os.getenv("BACKEND_WORKFLOW_QUEUE_HEAVY", "heavy")
    workflow_queue_batch: str = os.getenv("BACKEND_WORKFLOW_QUEUE_BATCH", "batch")
    workflow_queue_download_realtime: str = os.getenv("BACKEND_WORKFLOW_QUEUE_DOWNLOAD_REALTIME", "download-realtime")
    workflow_queue_download_standard: str = os.getenv("BACKEND_WORKFLOW_QUEUE_DOWNLOAD_STANDARD", "download-standard")
    workflow_queue_analysis_standard: str = os.getenv("BACKEND_WORKFLOW_QUEUE_ANALYSIS_STANDARD", workflow_queue_standard)
    workflow_queue_analysis_heavy: str = os.getenv("BACKEND_WORKFLOW_QUEUE_ANALYSIS_HEAVY", workflow_queue_heavy)
    workflow_queue_analysis_batch: str = os.getenv("BACKEND_WORKFLOW_QUEUE_ANALYSIS_BATCH", workflow_queue_batch)
    workflow_queue_algorithm_realtime: str = os.getenv("BACKEND_WORKFLOW_QUEUE_ALGORITHM_REALTIME", workflow_queue_realtime)
    workflow_queue_algorithm_standard: str = os.getenv("BACKEND_WORKFLOW_QUEUE_ALGORITHM_STANDARD", workflow_queue_analysis_standard)
    workflow_queue_algorithm_heavy: str = os.getenv("BACKEND_WORKFLOW_QUEUE_ALGORITHM_HEAVY", workflow_queue_analysis_heavy)
    workflow_queue_algorithm_batch: str = os.getenv("BACKEND_WORKFLOW_QUEUE_ALGORITHM_BATCH", workflow_queue_analysis_batch)
    api_key: str = os.getenv("BACKEND_API_KEY", "")
    cors_origins: list[str] = field(
        default_factory=lambda: _parse_csv_env(
            "BACKEND_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173",
        )
    )


settings = Settings()
