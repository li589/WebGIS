from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import sys

from app.services.deployment_config import apply_startup_overrides

# 尝试加载 dotenv；ImportError 表示 python-dotenv 未安装（环境变量已通过其他方式设置），
# 其他异常（如文件权限/编码问题）记录警告但不阻塞启动
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass
except Exception as exc:
    logging.warning("Failed to load .env file: %s", exc)


BACKEND_ROOT = Path(__file__).resolve().parents[2]

# ② 部署配置真源：deployment.config.json 逐键覆盖环境变量（优先于 .env）。
#    文件存在但损坏/校验失败 → 此处抛错拒启（fail-closed，错误信息含 .bak 恢复指引）。
#    deployment_config 仅依赖标准库，无循环导入；Celery worker/beat 同链生效。
DEPLOYMENT_OVERRIDES_APPLIED: list[str] = apply_startup_overrides()

# ③ 运行时根派生（去硬编码 H1）：显式 BACKEND_RUNTIME_ROOT
#    > <BACKEND_DATA_ROOT>/_runtime > 仓库 .data/_runtime（开发兜底）。
#    不再默认指向任何实验室盘符；production 空数据根由 assert_data_root_policy 拒启。
_data_root_env = os.getenv("BACKEND_DATA_ROOT", "").strip()
_RUNTIME_ROOT = Path(
    os.getenv("BACKEND_RUNTIME_ROOT", "").strip()
    or (_data_root_env and str(Path(_data_root_env) / "_runtime"))
    or str(BACKEND_ROOT / ".data" / "_runtime")
)
DEFAULT_WORKFLOW_STATE_DIR = _RUNTIME_ROOT / "workflow_state"
DEFAULT_LOG_DIR = _RUNTIME_ROOT / "logs"
DEFAULT_ARTIFACT_DIR = _RUNTIME_ROOT / "artifacts"
DEFAULT_CACHE_DIR = _RUNTIME_ROOT / "cache"
DEFAULT_PYTHON_PROVIDER_ROOT = (
    BACKEND_ROOT.parent / "algorithms" / "providers" / "Python"
)
DEFAULT_PYTHON_PROVIDER_WORKSPACE = _RUNTIME_ROOT / "python_provider"

# ---- 命名常量（提取自原内联魔数，便于维护与审阅）----
# 结果内联返回上限：小于此字节数的产物直接内联在响应中
_RESULT_INLINE_MAX_BYTES = 128 * 1024  # 128 KB
# 远端单文件下载上限（NAS 上大 HDF/GeoTIFF 可调高，例如 8 GiB）
_DOWNLOAD_MAX_BYTES = 512 * 1024 * 1024  # 512 MB
# Celery broker visibility_timeout（秒）：必须大于最长 task_time_limit
# （workflow 任务 time_limit=7500），否则 acks_late 下长任务会被重投
_BROKER_VISIBILITY_TIMEOUT = 8100  # seconds
# solo 池看门狗阈值（秒）：运行时长超此值的 run 标记为 failed
_WORKFLOW_STUCK_WATCHDOG_SECONDS = 8100  # seconds
# GEE 本地单次写入上限
_GEE_MAX_LOCAL_WRITE_BYTES = 10 * 1024 * 1024  # 10 MB


def _parse_csv_env(name: str, default: str = "") -> list[str]:
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _default_ui_restart_enabled() -> bool:
    raw = os.getenv("BACKEND_UI_RESTART_ENABLED")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    env = (os.getenv("BACKEND_ENV") or "production").lower()
    return env in {"development", "dev"}


def _default_gee_api_account_management_enabled() -> bool:
    """Production default OFF; development ON unless explicitly overridden."""
    raw = os.getenv("BACKEND_GEE_API_ACCOUNT_MANAGEMENT_ENABLED")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    env = (os.getenv("BACKEND_ENV") or "production").lower()
    return env in {"development", "dev"}


# ===========================================================================
# 嵌套配置分组（只读视图）
#
# 设计说明（P2-10）：
# `Settings` 仍保留全部扁平字段（向后兼容 `settings.redis_url` 等访问，
# 且 `dataclasses.replace` 可继续工作）。以下嵌套 dataclass 仅作为**便利
# 分组视图**，通过 `Settings` 的 `@property` 按需构造，不参与序列化/替换。
# 所有字段值与对应扁平字段同源，修改扁平字段后属性自动反映最新值。
# ===========================================================================


@dataclass(frozen=True)
class RedisConfig:
    """Redis 连接配置（分组视图）。"""

    url: str


@dataclass(frozen=True)
class CeleryConfig:
    """Celery broker / worker 配置（分组视图）。"""

    broker_url: str
    result_backend: str
    task_always_eager: bool
    task_soft_time_limit: int
    task_time_limit: int
    broker_visibility_timeout: int
    broker_socket_timeout: int
    broker_socket_connect_timeout: int
    worker_concurrency: int
    worker_prefetch_multiplier: int
    worker_pool: str
    worker_max_tasks_per_child: int


@dataclass(frozen=True)
class GeeConfig:
    """GEE 引擎配置（分组视图）。"""

    enabled: bool
    module_root: str
    storage_backend: str
    local_storage_root: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool
    account_cooldown_seconds: int
    max_parallel_exports: int
    max_parallel_uploads: int
    max_parallel_downloads: int
    max_local_write_bytes: int
    credentials_encryption_key: str
    credentials_db_path: str
    api_account_management_enabled: bool
    queue_realtime: str
    queue_standard: str
    queue_heavy: str
    queue_batch: str


@dataclass(frozen=True)
class WeatherConfig:
    """天气工作流引擎与 Open-Meteo 同步配置（分组视图）。"""

    default_model: str
    cache_ttl_seconds: int
    refresh_forecast_hours: int
    schedule_enabled: bool
    workflow_enabled: bool
    default_latitude: float
    default_longitude: float
    default_place_name: str
    open_meteo_sync_enabled: bool
    open_meteo_sync_cron_minute: str
    open_meteo_sync_cron_hour: str
    open_meteo_sync_domains: str
    open_meteo_sync_variables: str
    open_meteo_sync_compose_project: str
    open_meteo_sync_compose_dir: str
    queue_realtime: str
    queue_standard: str
    queue_heavy: str
    queue_batch: str


@dataclass(frozen=True)
class AuthConfig:
    """用户鉴权 / 会话 / API Key 配置（分组视图）。"""

    api_key: str
    api_keys_enabled: bool
    user_auth_enabled: bool
    admin_username: str
    admin_password: str
    session_cookie_name: str
    session_ttl_hours: int
    dev_auth_prefill: bool
    dev_default_api_key: str
    api_key_role: str
    demo_data_transfer_enabled: bool
    login_rate_limit_per_minute: int


@dataclass(frozen=True)
class StorageConfig:
    """存储根 / 产物 / 缓存 / 对象存储配置（分组视图）。"""

    backend: str
    data_root: str
    output_root: str
    workflow_state_dir: str
    python_provider_root: str
    python_provider_workspace: str
    log_dir: str
    log_level: str
    result_artifact_dir: str
    cache_dir: str
    cache_default_ttl_seconds: int
    object_store_backend: str
    object_store_public_base: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool


@dataclass(frozen=True)
class Settings:
    # 平台品牌为 SGFS（星地融合），但后端服务保留 CGDA 技术标识（仓库本名），
    # About 页「后端服务」/ 常规配置「服务名称」均取此值。
    service_name: str = os.getenv(
        "BACKEND_SERVICE_NAME",
        "Comprehensive Geographic Data Analysis System (CGDA) Backend",
    )
    # 发布就绪修复（P0-1）：默认 environment 反转为 "production"（fail-secure）。
    # 此前默认 "development" 会在未配置 API Key 时静默放行所有写接口（见 app/api/deps.py）。
    # 本地联调请在 Code/backend/.env 显式设置 BACKEND_ENV=development 以保留开发旁路。
    environment: str = os.getenv("BACKEND_ENV", "production")
    # 仅当后端位于受信反代（Nginx gateway）之后时才信任
    # X-Forwarded-For / X-Real-IP；默认 false，写限流用 request.client.host，防伪造。
    trust_proxy: bool = os.getenv("BACKEND_TRUST_PROXY", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    host: str = os.getenv("BACKEND_HOST", "127.0.0.1")
    port: int = int(os.getenv("BACKEND_PORT", "8000"))
    reload: bool = os.getenv("BACKEND_RELOAD", "true").lower() == "true"
    # 多进程部署：uvicorn workers 数（默认 1，保留开发热重载）。多 worker 下必须依赖
    # Redis 集中限流/会话（见 app/api/rate_limit.py），且 lifespan 初始化须幂等
    # （bootstrap_auth 等已做并发竞争兜底）。生产可设 BACKEND_FASTAPI_WORKERS=2+。
    fastapi_workers: int = max(1, int(os.getenv("BACKEND_FASTAPI_WORKERS", "1")))
    workflow_executor: str = os.getenv("BACKEND_WORKFLOW_EXECUTOR", "sync")
    redis_url: str = os.getenv("BACKEND_REDIS_URL", "redis://127.0.0.1:6379/0")
    celery_broker_url: str = os.getenv("BACKEND_CELERY_BROKER_URL", redis_url)
    celery_result_backend: str = os.getenv("BACKEND_CELERY_RESULT_BACKEND", redis_url)
    celery_task_always_eager: bool = (
        os.getenv("BACKEND_CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true"
    )
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
    cache_default_ttl_seconds: int = int(
        os.getenv("BACKEND_CACHE_DEFAULT_TTL_SECONDS", "1800")
    )
    object_store_backend: str = os.getenv("BACKEND_OBJECT_STORE_BACKEND", "local")
    object_store_public_base: str = os.getenv(
        "BACKEND_OBJECT_STORE_PUBLIC_BASE", "/artifacts"
    )
    minio_endpoint: str = os.getenv("BACKEND_MINIO_ENDPOINT", "")
    minio_access_key: str = os.getenv("BACKEND_MINIO_ACCESS_KEY", "")
    minio_secret_key: str = os.getenv("BACKEND_MINIO_SECRET_KEY", "")
    minio_bucket: str = os.getenv("BACKEND_MINIO_BUCKET", "workflow-artifacts")
    minio_secure: bool = os.getenv("BACKEND_MINIO_SECURE", "false").lower() == "true"
    result_inline_max_bytes: int = int(
        os.getenv("BACKEND_RESULT_INLINE_MAX_BYTES", str(_RESULT_INLINE_MAX_BYTES))
    )
    max_active_runs: int = int(os.getenv("BACKEND_MAX_ACTIVE_RUNS", "8"))
    max_active_weather_tile_runs: int = int(
        os.getenv("BACKEND_MAX_ACTIVE_WEATHER_TILE_RUNS", "16")
    )
    # Phase C：按角色并发控制——用户级工作流并发上限（在全局容量池之上的额外约束）。
    # admin 不受用户级限制；standard / demo 回退到此默认值，可被用户独立配置覆盖。
    max_concurrent_workflows_standard: int = int(
        os.getenv("BACKEND_MAX_CONCURRENT_WORKFLOWS_STANDARD", "3")
    )
    max_concurrent_workflows_demo: int = int(
        os.getenv("BACKEND_MAX_CONCURRENT_WORKFLOWS_DEMO", "1")
    )
    max_requested_outputs: int = int(os.getenv("BACKEND_MAX_REQUESTED_OUTPUTS", "6"))
    provider_max_hotspots: int = int(os.getenv("BACKEND_PROVIDER_MAX_HOTSPOTS", "200"))
    provider_max_series_points: int = int(
        os.getenv("BACKEND_PROVIDER_MAX_SERIES_POINTS", "240")
    )
    provider_table_chunk_size: int = int(
        os.getenv("BACKEND_PROVIDER_TABLE_CHUNK_SIZE", "100")
    )
    provider_series_chunk_size: int = int(
        os.getenv("BACKEND_PROVIDER_SERIES_CHUNK_SIZE", "120")
    )
    weather_default_model: str = os.getenv(
        "BACKEND_WEATHER_DEFAULT_MODEL", "ecmwf_ifs025"
    )
    weather_cache_ttl_seconds: int = int(
        os.getenv("BACKEND_WEATHER_CACHE_TTL_SECONDS", "3600")
    )
    weather_refresh_forecast_hours: int = int(
        os.getenv("BACKEND_WEATHER_REFRESH_FORECAST_HOURS", "6")
    )
    weather_schedule_enabled: bool = (
        os.getenv("BACKEND_WEATHER_SCHEDULE_ENABLED", "true").lower() == "true"
    )
    # Phase 2: Open-Meteo 本地数据自动同步（Celery Beat）
    # ECMWF IFS 每 6 小时更新初始场（00/06/12/18 UTC），同步在更新后 1-2 小时触发
    open_meteo_sync_enabled: bool = (
        os.getenv("BACKEND_OPEN_METEO_SYNC_ENABLED", "true").lower() == "true"
    )
    # cron 表达式（UTC），默认每 6 小时在 30 分触发（避开 ECMWF 发布时刻）
    open_meteo_sync_cron_minute: str = os.getenv(
        "BACKEND_OPEN_METEO_SYNC_CRON_MINUTE", "30"
    )
    open_meteo_sync_cron_hour: str = os.getenv(
        "BACKEND_OPEN_METEO_SYNC_CRON_HOUR", "*/6"
    )
    # 同步的气象模型（逗号分隔），支持 ecmwf_ifs025, gfs_global, icon_global, etc.
    open_meteo_sync_domains: str = os.getenv("OPEN_METEO_SYNC_DOMAINS", "ecmwf_ifs025")
    # 同步变量列表（逗号分隔）；与 Code/infra/data-sync/.env 保持一致即可
    open_meteo_sync_variables: str = os.getenv(
        "OPEN_METEO_SYNC_VARIABLES",
        "temperature_2m,temperature_80m,temperature_120m,temperature_180m,temperature_850hPa,temperature_500hPa,temperature_200hPa,apparent_temperature,relative_humidity_2m,dew_point_2m,precipitation,rain,weather_code,cloud_cover,pressure_msl,surface_pressure,visibility,wind_u_component_10m,wind_v_component_10m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,wind_u_component_80m,wind_v_component_80m,wind_speed_80m,wind_direction_80m,wind_u_component_120m,wind_v_component_120m,wind_speed_120m,wind_direction_120m,wind_u_component_180m,wind_v_component_180m,wind_speed_180m,wind_direction_180m,wind_u_component_850hPa,wind_v_component_850hPa,wind_speed_850hPa,wind_direction_850hPa,wind_u_component_500hPa,wind_v_component_500hPa,wind_speed_500hPa,wind_direction_500hPa,wind_u_component_200hPa,wind_v_component_200hPa,wind_speed_200hPa,wind_direction_200hPa",
    )
    # docker compose 项目名（数据同步栈；与 -p 一致）
    open_meteo_sync_compose_project: str = os.getenv(
        "BACKEND_OPEN_METEO_SYNC_COMPOSE_PROJECT", "data-sync"
    )
    # docker compose 工作目录（Code/infra/data-sync；仅 sync run，API 在 backend）
    open_meteo_sync_compose_dir: str = os.getenv(
        "BACKEND_OPEN_METEO_SYNC_COMPOSE_DIR",
        os.path.normpath(
            os.path.join(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                ),
                "..",
                "infra",
                "data-sync",
            )
        ),
    )
    weather_default_latitude: float = float(
        os.getenv("BACKEND_WEATHER_DEFAULT_LATITUDE", "23.1291")
    )
    weather_default_longitude: float = float(
        os.getenv("BACKEND_WEATHER_DEFAULT_LONGITUDE", "113.2644")
    )
    weather_default_place_name: str = os.getenv(
        "BACKEND_WEATHER_DEFAULT_PLACE_NAME", "Guangzhou"
    )
    # 地图默认视口（与天气默认点同源缺省；机构可经 BACKEND_MAP_DEFAULT_* 覆盖）
    map_default_longitude: float = float(
        os.getenv(
            "BACKEND_MAP_DEFAULT_LONGITUDE",
            os.getenv("BACKEND_WEATHER_DEFAULT_LONGITUDE", "113.2644"),
        )
    )
    map_default_latitude: float = float(
        os.getenv(
            "BACKEND_MAP_DEFAULT_LATITUDE",
            os.getenv("BACKEND_WEATHER_DEFAULT_LATITUDE", "23.1291"),
        )
    )
    map_default_zoom: float = float(os.getenv("BACKEND_MAP_DEFAULT_ZOOM", "4.8"))
    map_default_tile_source: str = os.getenv(
        "BACKEND_MAP_DEFAULT_TILE_SOURCE", "gaode-street"
    )
    # 可选机构 AOI 预设 JSON 数组：[{"label":"...","west":..,"south":..,"east":..,"north":..}]
    map_aoi_presets_json: str = os.getenv("BACKEND_MAP_AOI_PRESETS", "")
    workflow_queue_realtime: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_REALTIME", "realtime"
    )
    workflow_queue_standard: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_STANDARD", "standard"
    )
    workflow_queue_heavy: str = os.getenv("BACKEND_WORKFLOW_QUEUE_HEAVY", "heavy")
    workflow_queue_batch: str = os.getenv("BACKEND_WORKFLOW_QUEUE_BATCH", "batch")
    workflow_queue_download_realtime: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_DOWNLOAD_REALTIME", "download-realtime"
    )
    workflow_queue_download_standard: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_DOWNLOAD_STANDARD", "download-standard"
    )
    workflow_queue_analysis_standard: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_ANALYSIS_STANDARD", workflow_queue_standard
    )
    workflow_queue_analysis_heavy: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_ANALYSIS_HEAVY", workflow_queue_heavy
    )
    workflow_queue_analysis_batch: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_ANALYSIS_BATCH", workflow_queue_batch
    )
    workflow_queue_algorithm_realtime: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_ALGORITHM_REALTIME", workflow_queue_realtime
    )
    workflow_queue_algorithm_standard: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_ALGORITHM_STANDARD", workflow_queue_analysis_standard
    )
    workflow_queue_algorithm_heavy: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_ALGORITHM_HEAVY", workflow_queue_analysis_heavy
    )
    workflow_queue_algorithm_batch: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_ALGORITHM_BATCH", workflow_queue_analysis_batch
    )
    api_key: str = os.getenv("BACKEND_API_KEY", "")
    api_keys_enabled: bool = (
        os.getenv(
            "BACKEND_API_KEYS_ENABLED",
            "true" if os.getenv("BACKEND_API_KEY", "").strip() else "false",
        ).lower()
        == "true"
    )
    cors_origins: list[str] = field(
        default_factory=lambda: _parse_csv_env(
            "BACKEND_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:5174,http://localhost:5174,http://127.0.0.1:5175,http://localhost:5175,http://127.0.0.1:5176,http://localhost:5176,http://127.0.0.1:4173,http://localhost:4173",
        )
    )

    # ---- 数据源配置 ----
    # 存储后端类型：local（本地文件系统）或 minio（MinIO 对象存储）
    storage_backend: str = os.getenv("BACKEND_STORAGE_BACKEND", "local")
    # 本地模式数据根目录（逻辑数据集的根路径，必须通过环境变量配置）
    data_root: str = os.getenv("BACKEND_DATA_ROOT", "")
    # 产物输出根目录（算法产物的写入路径，必须通过环境变量配置）
    output_root: str = os.getenv("BACKEND_OUTPUT_ROOT", "")
    # 前端设置页「重启后端」（FastAPI+Worker+Beat）；默认仅 development 开启
    ui_restart_enabled: bool = _default_ui_restart_enabled()

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
        str(_RUNTIME_ROOT / "gee"),
    )
    # GEE MinIO 配置（仅当 gee_storage_backend=minio 时使用）
    gee_minio_endpoint: str = os.getenv("BACKEND_GEE_MINIO_ENDPOINT", "")
    gee_minio_access_key: str = os.getenv("BACKEND_GEE_MINIO_ACCESS_KEY", "")
    gee_minio_secret_key: str = os.getenv("BACKEND_GEE_MINIO_SECRET_KEY", "")
    gee_minio_bucket: str = os.getenv("BACKEND_GEE_MINIO_BUCKET", "gee-exports")
    gee_minio_secure: bool = (
        os.getenv("BACKEND_GEE_MINIO_SECURE", "false").lower() == "true"
    )
    # GEE 运行时资源控制
    gee_account_cooldown_seconds: int = int(
        os.getenv("BACKEND_GEE_ACCOUNT_COOLDOWN_SECONDS", "300")
    )
    gee_max_parallel_exports: int = int(
        os.getenv("BACKEND_GEE_MAX_PARALLEL_EXPORTS", "2")
    )
    gee_max_parallel_uploads: int = int(
        os.getenv("BACKEND_GEE_MAX_PARALLEL_UPLOADS", "4")
    )
    gee_max_parallel_downloads: int = int(
        os.getenv("BACKEND_GEE_MAX_PARALLEL_DOWNLOADS", "4")
    )
    gee_max_local_write_bytes: int = int(
        os.getenv("BACKEND_GEE_MAX_LOCAL_WRITE_BYTES", str(_GEE_MAX_LOCAL_WRITE_BYTES))
    )
    # GEE 队列（独立队列，避免与 algorithm 队列混用）
    workflow_queue_gee_realtime: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_GEE_REALTIME", "gee-realtime"
    )
    workflow_queue_gee_standard: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_GEE_STANDARD", "gee-standard"
    )
    workflow_queue_gee_heavy: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_GEE_HEAVY", "gee-heavy"
    )
    workflow_queue_gee_batch: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_GEE_BATCH", "gee-batch"
    )
    # GEE 凭证配置（Service Account 模式）
    # 凭证加密密钥（32 字节 hex 字符串，用于 AES-GCM 加密 service_account JSON）
    gee_credentials_encryption_key: str = os.getenv(
        "BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY", ""
    )
    # 凭证存储路径（SQLite 文件路径，默认复用 workflow_state 目录）
    gee_credentials_db_path: str = os.getenv(
        "BACKEND_GEE_CREDENTIALS_DB_PATH",
        str(_RUNTIME_ROOT / "workflow_state" / "gee_credentials.sqlite3"),
    )
    # 是否允许通过 API 添加 service_account（生产默认 False；development 默认 True）
    gee_api_account_management_enabled: bool = (
        _default_gee_api_account_management_enabled()
    )

    # ---- 天气工作流引擎配置 ----
    # 是否启用天气工作流桥接（False 时 weather_bridge_service.supports 永远返回 False）
    weather_workflow_enabled: bool = (
        os.getenv("BACKEND_WEATHER_WORKFLOW_ENABLED", "true").lower() == "true"
    )
    # 天气工作流队列（独立队列，避免与 algorithm/gee 队列混用）
    workflow_queue_weather_realtime: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_WEATHER_REALTIME", "weather-realtime"
    )
    workflow_queue_weather_standard: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_WEATHER_STANDARD", "weather-standard"
    )
    workflow_queue_weather_heavy: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_WEATHER_HEAVY", "weather-heavy"
    )
    workflow_queue_weather_batch: str = os.getenv(
        "BACKEND_WORKFLOW_QUEUE_WEATHER_BATCH", "weather-batch"
    )

    # ---- Provider 工作流引擎配置 ----
    # C5 修复：与其他 bridge 对齐 enabled flag，False 时 provider_workflow_service.supports 永远返回 False
    provider_workflow_enabled: bool = (
        os.getenv("BACKEND_PROVIDER_WORKFLOW_ENABLED", "true").lower() == "true"
    )
    # M8 修复：python_provider bridge 也对齐 enabled flag
    python_provider_enabled: bool = (
        os.getenv("BACKEND_PYTHON_PROVIDER_ENABLED", "true").lower() == "true"
    )

    # ---- 下载链真实抓取器配置 ----
    # 数据源根目录（local:// scheme 的基础路径，用于 wind-field/precipitation 等图层的真实数据定位）
    download_source_root: str = os.getenv("BACKEND_DOWNLOAD_SOURCE_ROOT", "")
    # 图层 → source_uri 模板映射（JSON 字符串），支持 {layer_id} {hour} 占位符
    # 示例：{"wind-field": "file:///data/wind/{hour}.json", "precipitation": "http://example.com/precip/{hour}.tif"}
    download_source_uri_map: str = os.getenv("BACKEND_DOWNLOAD_SOURCE_URI_MAP", "")
    # 是否启用真实抓取（False 时仍走 demo:// 占位路径，保持向后兼容）
    download_real_fetch_enabled: bool = (
        os.getenv("BACKEND_DOWNLOAD_REAL_FETCH_ENABLED", "true").lower() == "true"
    )

    # ---- 底图代理配置 ----
    # 天地图 API Key（从 https://console.tianditu.gov.cn/ 获取）
    tianditu_api_key: str = os.getenv("BACKEND_TIANDITU_API_KEY", "")
    # 百度地图 API Key（从 https://lbsyun.baidu.com/ 获取，百度 tile 服务需要 ak 认证）
    baidu_api_key: str = os.getenv("BACKEND_BAIDU_API_KEY", "")
    # 是否启用底图代理（False 时前端直接访问外部 tile 服务器）
    tile_proxy_enabled: bool = (
        os.getenv("BACKEND_TILE_PROXY_ENABLED", "true").lower() == "true"
    )
    # 底图代理缓存 TTL（秒）
    tile_proxy_cache_ttl_seconds: int = int(
        os.getenv("BACKEND_TILE_PROXY_CACHE_TTL_SECONDS", "86400")
    )

    # ---- Celery 任务超时配置 ----
    # 软超时（秒）：任务超过此时间未完成则抛出 SoftTimeLimitExceeded，
    # 可被 except SoftTimeLimitExceeded 捕获，用于优雅清理资源后退出
    celery_task_soft_time_limit: int = int(
        os.getenv("BACKEND_CELERY_TASK_SOFT_TIME_LIMIT", "300")
    )
    # 硬超时（秒）：任务超过此时间无论处于什么状态都会被 SIGKILL 强制终止
    celery_task_time_limit: int = int(
        os.getenv("BACKEND_CELERY_TASK_TIME_LIMIT", "360")
    )
    # 发布就绪修复（P0-7）：broker visibility_timeout（秒）。
    # 必须大于最长 task_time_limit（workflow 任务 time_limit=7500），否则 acks_late
    # 下长任务会在 visibility 超时（Redis 默认 3600）后被重投到另一 worker，导致并发重复执行。
    celery_broker_visibility_timeout: int = int(
        os.getenv(
            "BACKEND_CELERY_BROKER_VISIBILITY_TIMEOUT",
            str(_BROKER_VISIBILITY_TIMEOUT),
        )
    )
    # broker 连接/读取超时（秒）：给 broker 操作定上界，避免 broker 挂起时
    # 工作线程无限期阻塞（同根修复线程池阻塞无寿命上界问题）。
    celery_broker_socket_timeout: int = int(
        os.getenv("BACKEND_CELERY_BROKER_SOCKET_TIMEOUT", "30")
    )
    celery_broker_socket_connect_timeout: int = int(
        os.getenv("BACKEND_CELERY_BROKER_SOCKET_CONNECT_TIMEOUT", "10")
    )
    # 发布就绪修复（P1-4）：solo 池看门狗阈值（秒）。worker_pool=solo 时 time_limit
    # 无法强杀卡死任务，run 会永远停在 running。看门狗周期任务把"运行时长超此阈值"
    # 的 run 标记为 failed（仅纠正状态，不释放被卡 worker）。默认 8100 > workflow
    # 任务 time_limit=7500，避免误杀合法长任务。
    workflow_stuck_watchdog_seconds: int = int(
        os.getenv(
            "BACKEND_WORKFLOW_STUCK_WATCHDOG_SECONDS",
            str(_WORKFLOW_STUCK_WATCHDOG_SECONDS),
        )
    )
    # Celery worker 并发度：每个 worker 进程的最大并发任务数。
    # launch.py 启动 7 个 worker，默认占满 CPU 会严重过订阅；建议物理核数/worker 数。
    celery_worker_concurrency: int = int(
        os.getenv("BACKEND_CELERY_WORKER_CONCURRENCY", "2")
    )
    # Celery 预取倍数：worker 预先从队列拉取的任务数。
    # 配合 acks_late 时应设为 1，避免长任务预取占槽阻塞短任务。
    celery_worker_prefetch_multiplier: int = int(
        os.getenv("BACKEND_CELERY_PREFETCH_MULTIPLIER", "1")
    )
    # Celery worker 池模式（C3）：solo=单进程串行（Windows 开发兜底，规避
    # Celery 5.4 prefork fast_trace_task thread-local bug）；prefork=多进程并行
    # （生产 Linux 推荐，concurrency 生效）。默认按平台自适应；可用
    # BACKEND_CELERY_WORKER_POOL 显式覆盖（solo/prefork/threads/gevent）。
    celery_worker_pool: str = os.getenv(
        "BACKEND_CELERY_WORKER_POOL",
        "solo" if sys.platform.startswith("win") else "prefork",
    )
    # Celery worker 单进程最大任务数（防内存泄漏兜底）。
    # worker 进程处理此数量任务后自动回收重启。0=不限制。
    # 注意：按任务数回收，不会 kill 正在运行的任务。用户要求"运行中内存超
    # 设定值不 kill"，故不启用 max_memory_per_child（后者会 recycle 运行中任务）。
    celery_worker_max_tasks_per_child: int = int(
        os.getenv("BACKEND_CELERY_WORKER_MAX_TASKS_PER_CHILD", "0")
    )
    # 单任务内存预算（MB，声明值，0=不限制）。
    # 仅作调度准入参考与启动时资源分配依据；任务运行中超过此值不会被 kill
    # （只要不超过系统总可用内存）。用于多任务并发时的资源规划。
    task_memory_budget_mb: int = int(os.getenv("BACKEND_TASK_MEMORY_BUDGET_MB", "0"))
    # 单任务 CPU 预算核数（声明值，0=不限制）。
    # 同上，仅作调度准入参考；不硬限制运行中任务的 CPU 使用。
    task_cpu_budget_cores: int = int(os.getenv("BACKEND_TASK_CPU_BUDGET_CORES", "0"))
    # 工作流就绪节点并行度：同一工作流内无依赖关系的就绪节点并行执行数。
    # 1=串行（兼容旧行为）；>1 时同层就绪节点用线程池并行执行。
    # 注意：节点内算法若已用 ProcessPoolExecutor，实际进程数 = 节点并行度 ×
    # 每节点进程数，须与 algorithm_max_parallel_workers 协调避免过订阅。
    workflow_node_parallelism: int = int(
        os.getenv("BACKEND_WORKFLOW_NODE_PARALLELISM", "1")
    )
    # 算法包单任务最大并行进程数（原 CGDA_MAX_PARALLEL_WORKERS env 纳入 Settings）。
    # 0=自动（按 CPU/内存自适应）；>0 时硬上限。启动 worker 时注入子进程 env。
    algorithm_max_parallel_workers: int = int(
        os.getenv("BACKEND_ALGORITHM_MAX_PARALLEL_WORKERS", "0")
    )

    # ---- Phase 1 工程治理开关 ----
    # 远端数据源就绪检查时是否短超时 probe（stat）；默认只校验凭证可解析
    remote_readiness_probe: bool = (
        os.getenv("BACKEND_REMOTE_READINESS_PROBE", "false").lower() == "true"
    )
    # 远端单文件下载上限（字节）。NAS 上大 HDF/GeoTIFF 可调高，例如 8589934592（8 GiB）
    remote_max_bytes: int = int(
        os.getenv("BACKEND_REMOTE_MAX_BYTES", str(_DOWNLOAD_MAX_BYTES))
    )
    # 图层远端数据源覆盖（JSON）。将 SMB/SFTP URI 插到对应 layer 的候选列表最前，不改本地已跑通路径。
    # 例: {"ref-smap-sm-202512-l3":{"SMAP_L3_DEC2025":["smb://nas/share/SMAP/x.h5?cred=nas-lab"]}}
    remote_layer_data_uris: str = os.getenv("BACKEND_REMOTE_LAYER_DATA_URIS", "")
    # 每个 API Key 保留的历史版本上限
    api_key_history_limit: int = int(os.getenv("BACKEND_API_KEY_HISTORY_LIMIT", "20"))

    # ---- User login / session auth ----
    # 前端登录与会话鉴权；生产默认开启。关闭后仅保留 X-API-Key 写鉴权（旧联调路径）。
    user_auth_enabled: bool = (
        os.getenv("BACKEND_USER_AUTH_ENABLED", "true").lower() == "true"
    )
    admin_username: str = os.getenv("BACKEND_ADMIN_USERNAME", "")
    admin_password: str = os.getenv("BACKEND_ADMIN_PASSWORD", "")
    session_cookie_name: str = os.getenv("BACKEND_SESSION_COOKIE_NAME", "cgda_session")
    session_ttl_hours: int = int(os.getenv("BACKEND_SESSION_TTL_HOURS", "24"))
    # development：登录页与 API Key 设置预填默认凭据（勿在生产开启）
    dev_auth_prefill: bool = os.getenv(
        "BACKEND_DEV_AUTH_PREFILL", ""
    ).strip().lower() in {"1", "true", "yes", "on"} or (
        os.getenv("BACKEND_DEV_AUTH_PREFILL", "").strip() == ""
        and (os.getenv("BACKEND_ENV") or "production").lower() in {"development", "dev"}
    )
    # No hardcoded default secret — set BACKEND_DEV_DEFAULT_API_KEY explicitly
    # for local bootstrap, or leave empty to skip seeding backend_auth.
    dev_default_api_key: str = os.getenv("BACKEND_DEV_DEFAULT_API_KEY", "")
    # 服务密钥 backend_auth 绑定角色（脚本/CI）；默认 standard
    api_key_role: str = os.getenv("BACKEND_API_KEY_ROLE", "standard")
    # demo 角色数据上传/下载开关（默认关闭，管理员可开启）
    demo_data_transfer_enabled: bool = (
        os.getenv("BACKEND_DEMO_DATA_TRANSFER_ENABLED", "false").lower() == "true"
    )
    login_rate_limit_per_minute: int = int(
        os.getenv("BACKEND_LOGIN_RATE_LIMIT_PER_MINUTE", "10")
    )
    # 每个远程存储 profile 保留的密钥历史上限
    remote_storage_history_limit: int = int(
        os.getenv("BACKEND_REMOTE_STORAGE_HISTORY_LIMIT", "20")
    )

    # ---- SSH 远程同步 ----
    ssh_hpc_host: str = os.getenv("BACKEND_SSH_HPC_HOST", "127.0.0.1")
    ssh_hpc_port: int = int(os.getenv("BACKEND_SSH_HPC_PORT", "2222"))
    # 去硬编码批 1：不再默认实验室账号；空 = 未配置（与 FileBrowser URL 一致）
    ssh_hpc_user: str = os.getenv("BACKEND_SSH_HPC_USER", "")
    ssh_hpc_key_path: str = os.getenv("BACKEND_SSH_HPC_KEY_PATH", "~/.ssh/seahpc_key")
    ssh_win11_alias: str = os.getenv("BACKEND_SSH_WIN11_ALIAS", "win11-lab")
    ssh_win11_user: str = os.getenv("BACKEND_SSH_WIN11_USER", "")

    # ---- Earthdata 凭据 ----
    earthdata_username: str = os.getenv("BACKEND_EARTHDATA_USERNAME", "")
    earthdata_password: str = os.getenv("BACKEND_EARTHDATA_PASSWORD", "")

    # ---- FileBrowser ----
    # 发布就绪修复（P0-2/P1-7）：移除硬编码的外部免费动态 DNS 端点默认值与默认用户名。
    # 这些端点曾默认指向 *.personaltunnel.dpdns.org（可被第三方注册的免费 DDNS），
    # 叠加未鉴权路由会让后端主动向外部域名发起连接并外发凭据。现默认为空 = 功能禁用，
    # 需管理员在 .env / 设置界面显式配置内部地址后方可使用。
    filebrowser_nas_url: str = os.getenv("BACKEND_FILEBROWSER_NAS_URL", "")
    filebrowser_win11_url: str = os.getenv("BACKEND_FILEBROWSER_WIN11_URL", "")
    filebrowser_user: str = os.getenv("BACKEND_FILEBROWSER_USER", "")
    filebrowser_password: str = os.getenv("BACKEND_FILEBROWSER_PASSWORD", "")

    # ---- P0-10 产品边界开关 ----
    # demo:// 占位数据源：仅 development 默认可用（联调/展演示）；production 默认直接
    # fail，除非显式设 BACKEND_DEMO_SOURCES_ENABLED=true（如临时展演示以生产模式运行时）。
    demo_sources_enabled: bool = os.getenv(
        "BACKEND_DEMO_SOURCES_ENABLED", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    # 未实现执行器的占位节点模板（executable=False 的 stub）：仅 development 默认在节点
    # 面板可见；production 默认隐藏，除非显式设 BACKEND_NODE_STUBS_VISIBLE=true。
    node_stubs_visible: bool = os.getenv(
        "BACKEND_NODE_STUBS_VISIBLE", ""
    ).strip().lower() in {"1", "true", "yes", "on"}

    # ---- SpatiaLite 空间扩展（mod_spatialite）----
    # 总开关：False 时所有连接都不尝试加载（彻底禁用空间特性）。
    # 默认 True：扩展不可用时 spatialite_loader.load_into 会 warn 并降级，
    # state/metadata DB（workflow/api_keys/gee_credentials，高风险区）不受影响。
    spatialite_enabled: bool = (
        os.getenv("BACKEND_SPATIALITE_ENABLED", "true").lower() == "true"
    )
    # 扩展文件路径覆盖（可选；空=自动探测）。
    spatialite_path: str = os.getenv("BACKEND_SPATIALITE_PATH", "")
    # 空间叠加层数据库路径（独立 SQLite 文件，与 workflow_state 分离；删除即回滚）。
    spatialite_db_path: str = os.getenv(
        "BACKEND_SPATIALITE_DB_PATH",
        str(BACKEND_ROOT / ".data" / "spatial.sqlite"),
    )

    # ===============================================================
    # 嵌套配置分组属性（便利只读视图）
    #
    # 这些 property 从上方扁平字段构造分组 dataclass，不引入新的状态。
    # 扁平字段仍是唯一真源；`dataclasses.replace` 仅作用于扁平字段。
    # ===============================================================

    @property
    def redis(self) -> RedisConfig:
        """Redis 连接配置分组视图。"""
        return RedisConfig(url=self.redis_url)

    @property
    def celery(self) -> CeleryConfig:
        """Celery broker / worker 配置分组视图。"""
        return CeleryConfig(
            broker_url=self.celery_broker_url,
            result_backend=self.celery_result_backend,
            task_always_eager=self.celery_task_always_eager,
            task_soft_time_limit=self.celery_task_soft_time_limit,
            task_time_limit=self.celery_task_time_limit,
            broker_visibility_timeout=self.celery_broker_visibility_timeout,
            broker_socket_timeout=self.celery_broker_socket_timeout,
            broker_socket_connect_timeout=self.celery_broker_socket_connect_timeout,
            worker_concurrency=self.celery_worker_concurrency,
            worker_prefetch_multiplier=self.celery_worker_prefetch_multiplier,
            worker_pool=self.celery_worker_pool,
            worker_max_tasks_per_child=self.celery_worker_max_tasks_per_child,
        )

    @property
    def gee(self) -> GeeConfig:
        """GEE 引擎配置分组视图。"""
        return GeeConfig(
            enabled=self.gee_enabled,
            module_root=self.gee_module_root,
            storage_backend=self.gee_storage_backend,
            local_storage_root=self.gee_local_storage_root,
            minio_endpoint=self.gee_minio_endpoint,
            minio_access_key=self.gee_minio_access_key,
            minio_secret_key=self.gee_minio_secret_key,
            minio_bucket=self.gee_minio_bucket,
            minio_secure=self.gee_minio_secure,
            account_cooldown_seconds=self.gee_account_cooldown_seconds,
            max_parallel_exports=self.gee_max_parallel_exports,
            max_parallel_uploads=self.gee_max_parallel_uploads,
            max_parallel_downloads=self.gee_max_parallel_downloads,
            max_local_write_bytes=self.gee_max_local_write_bytes,
            credentials_encryption_key=self.gee_credentials_encryption_key,
            credentials_db_path=self.gee_credentials_db_path,
            api_account_management_enabled=self.gee_api_account_management_enabled,
            queue_realtime=self.workflow_queue_gee_realtime,
            queue_standard=self.workflow_queue_gee_standard,
            queue_heavy=self.workflow_queue_gee_heavy,
            queue_batch=self.workflow_queue_gee_batch,
        )

    @property
    def weather(self) -> WeatherConfig:
        """天气工作流引擎与 Open-Meteo 同步配置分组视图。"""
        return WeatherConfig(
            default_model=self.weather_default_model,
            cache_ttl_seconds=self.weather_cache_ttl_seconds,
            refresh_forecast_hours=self.weather_refresh_forecast_hours,
            schedule_enabled=self.weather_schedule_enabled,
            workflow_enabled=self.weather_workflow_enabled,
            default_latitude=self.weather_default_latitude,
            default_longitude=self.weather_default_longitude,
            default_place_name=self.weather_default_place_name,
            open_meteo_sync_enabled=self.open_meteo_sync_enabled,
            open_meteo_sync_cron_minute=self.open_meteo_sync_cron_minute,
            open_meteo_sync_cron_hour=self.open_meteo_sync_cron_hour,
            open_meteo_sync_domains=self.open_meteo_sync_domains,
            open_meteo_sync_variables=self.open_meteo_sync_variables,
            open_meteo_sync_compose_project=self.open_meteo_sync_compose_project,
            open_meteo_sync_compose_dir=self.open_meteo_sync_compose_dir,
            queue_realtime=self.workflow_queue_weather_realtime,
            queue_standard=self.workflow_queue_weather_standard,
            queue_heavy=self.workflow_queue_weather_heavy,
            queue_batch=self.workflow_queue_weather_batch,
        )

    @property
    def auth(self) -> AuthConfig:
        """用户鉴权 / 会话 / API Key 配置分组视图。"""
        return AuthConfig(
            api_key=self.api_key,
            api_keys_enabled=self.api_keys_enabled,
            user_auth_enabled=self.user_auth_enabled,
            admin_username=self.admin_username,
            admin_password=self.admin_password,
            session_cookie_name=self.session_cookie_name,
            session_ttl_hours=self.session_ttl_hours,
            dev_auth_prefill=self.dev_auth_prefill,
            dev_default_api_key=self.dev_default_api_key,
            api_key_role=self.api_key_role,
            demo_data_transfer_enabled=self.demo_data_transfer_enabled,
            login_rate_limit_per_minute=self.login_rate_limit_per_minute,
        )

    @property
    def storage(self) -> StorageConfig:
        """存储根 / 产物 / 缓存 / 对象存储配置分组视图。"""
        return StorageConfig(
            backend=self.storage_backend,
            data_root=self.data_root,
            output_root=self.output_root,
            workflow_state_dir=self.workflow_state_dir,
            python_provider_root=self.python_provider_root,
            python_provider_workspace=self.python_provider_workspace,
            log_dir=self.log_dir,
            log_level=self.log_level,
            result_artifact_dir=self.result_artifact_dir,
            cache_dir=self.cache_dir,
            cache_default_ttl_seconds=self.cache_default_ttl_seconds,
            object_store_backend=self.object_store_backend,
            object_store_public_base=self.object_store_public_base,
            minio_endpoint=self.minio_endpoint,
            minio_access_key=self.minio_access_key,
            minio_secret_key=self.minio_secret_key,
            minio_bucket=self.minio_bucket,
            minio_secure=self.minio_secure,
        )


settings = Settings()
