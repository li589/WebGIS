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
    weather_default_model: str = os.getenv("BACKEND_WEATHER_DEFAULT_MODEL", "best_match")
    weather_cache_ttl_seconds: int = int(os.getenv("BACKEND_WEATHER_CACHE_TTL_SECONDS", "3600"))
    weather_refresh_forecast_hours: int = int(os.getenv("BACKEND_WEATHER_REFRESH_FORECAST_HOURS", "6"))
    weather_schedule_enabled: bool = os.getenv("BACKEND_WEATHER_SCHEDULE_ENABLED", "true").lower() == "true"
    weather_default_latitude: float = float(os.getenv("BACKEND_WEATHER_DEFAULT_LATITUDE", "23.1291"))
    weather_default_longitude: float = float(os.getenv("BACKEND_WEATHER_DEFAULT_LONGITUDE", "113.2644"))
    weather_default_place_name: str = os.getenv("BACKEND_WEATHER_DEFAULT_PLACE_NAME", "Guangzhou")
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
    api_keys_enabled: bool = os.getenv(
        "BACKEND_API_KEYS_ENABLED",
        "true" if os.getenv("BACKEND_API_KEY", "").strip() else "false",
    ).lower() == "true"
    cors_origins: list[str] = field(
        default_factory=lambda: _parse_csv_env(
            "BACKEND_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173",
        )
    )

    # ---- 数据源配置 ----
    # 存储后端类型：local（本地文件系统）或 minio（MinIO 对象存储）
    storage_backend: str = os.getenv("BACKEND_STORAGE_BACKEND", "local")
    # 本地模式数据根目录（逻辑数据集的根路径）
    data_root: str = os.getenv("BACKEND_DATA_ROOT", r"I:\Geograph_DataSet")
    # 产物输出根目录（算法产物的写入路径）
    output_root: str = os.getenv("BACKEND_OUTPUT_ROOT", r"I:\GeoOutput")

    # ---- GEE 引擎配置 ----
    # 是否启用 GEE 引擎桥接（False 时 gee_bridge_service.supports 永远返回 False）
    gee_enabled: bool = os.getenv("BACKEND_GEE_ENABLED", "true").lower() == "true"
    # GEE core 模块 src 根目录（指向 webgis_gee 包所在位置）
    gee_module_root: str = os.getenv(
        "BACKEND_GEE_MODULE_ROOT",
        str(BACKEND_ROOT / "app" / "gee" / "core" / "src"),
    )
    # GEE 存储后端：local / minio（独立于平台 object_store，避免与 artifact 存储混用）
    gee_storage_backend: str = os.getenv("BACKEND_GEE_STORAGE_BACKEND", "local")
    # GEE 本地存储根目录（manifest/导出产物落盘根路径）
    gee_local_storage_root: str = os.getenv(
        "BACKEND_GEE_LOCAL_STORAGE_ROOT",
        str(BACKEND_ROOT / ".data" / "gee"),
    )
    # GEE MinIO 配置（仅当 gee_storage_backend=minio 时使用）
    gee_minio_endpoint: str = os.getenv("BACKEND_GEE_MINIO_ENDPOINT", "")
    gee_minio_access_key: str = os.getenv("BACKEND_GEE_MINIO_ACCESS_KEY", "")
    gee_minio_secret_key: str = os.getenv("BACKEND_GEE_MINIO_SECRET_KEY", "")
    gee_minio_bucket: str = os.getenv("BACKEND_GEE_MINIO_BUCKET", "gee-exports")
    gee_minio_secure: bool = os.getenv("BACKEND_GEE_MINIO_SECURE", "false").lower() == "true"
    # GEE 运行时资源控制
    gee_account_cooldown_seconds: int = int(os.getenv("BACKEND_GEE_ACCOUNT_COOLDOWN_SECONDS", "300"))
    gee_max_parallel_exports: int = int(os.getenv("BACKEND_GEE_MAX_PARALLEL_EXPORTS", "2"))
    gee_max_parallel_uploads: int = int(os.getenv("BACKEND_GEE_MAX_PARALLEL_UPLOADS", "4"))
    gee_max_parallel_downloads: int = int(os.getenv("BACKEND_GEE_MAX_PARALLEL_DOWNLOADS", "4"))
    gee_max_local_write_bytes: int = int(os.getenv("BACKEND_GEE_MAX_LOCAL_WRITE_BYTES", str(10 * 1024 * 1024)))
    # GEE 队列（独立队列，避免与 algorithm 队列混用）
    workflow_queue_gee_realtime: str = os.getenv("BACKEND_WORKFLOW_QUEUE_GEE_REALTIME", "gee-realtime")
    workflow_queue_gee_standard: str = os.getenv("BACKEND_WORKFLOW_QUEUE_GEE_STANDARD", "gee-standard")
    workflow_queue_gee_heavy: str = os.getenv("BACKEND_WORKFLOW_QUEUE_GEE_HEAVY", "gee-heavy")
    workflow_queue_gee_batch: str = os.getenv("BACKEND_WORKFLOW_QUEUE_GEE_BATCH", "gee-batch")

    # ---- 天气工作流引擎配置 ----
    # 是否启用天气工作流桥接（False 时 weather_bridge_service.supports 永远返回 False）
    weather_workflow_enabled: bool = os.getenv("BACKEND_WEATHER_WORKFLOW_ENABLED", "true").lower() == "true"
    # 天气工作流队列（独立队列，避免与 algorithm/gee 队列混用）
    workflow_queue_weather_realtime: str = os.getenv("BACKEND_WORKFLOW_QUEUE_WEATHER_REALTIME", "weather-realtime")
    workflow_queue_weather_standard: str = os.getenv("BACKEND_WORKFLOW_QUEUE_WEATHER_STANDARD", "weather-standard")
    workflow_queue_weather_heavy: str = os.getenv("BACKEND_WORKFLOW_QUEUE_WEATHER_HEAVY", "weather-heavy")
    workflow_queue_weather_batch: str = os.getenv("BACKEND_WORKFLOW_QUEUE_WEATHER_BATCH", "weather-batch")

    # ---- Provider 工作流引擎配置 ----
    # C5 修复：与其他 bridge 对齐 enabled flag，False 时 provider_workflow_service.supports 永远返回 False
    provider_workflow_enabled: bool = os.getenv("BACKEND_PROVIDER_WORKFLOW_ENABLED", "true").lower() == "true"
    # M8 修复：python_provider bridge 也对齐 enabled flag
    python_provider_enabled: bool = os.getenv("BACKEND_PYTHON_PROVIDER_ENABLED", "true").lower() == "true"


settings = Settings()
