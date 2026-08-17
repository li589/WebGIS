"""部署/数据源配置真源：``deployment.config.json``。

本模块在 ``app.core.config`` 模块加载期被调用（dotenv 之后、Settings 实例化之前），
因此**只允许标准库导入**（禁止模块级 import app.*，否则循环导入）；
``env_file_upsert`` 等应用期依赖一律函数内延迟导入。

加载顺序（见 config.py 模块头）：
  ① load_dotenv(Code/backend/.env)
  ② 本模块解析 deployment.config.json → schema 校验 → 逐键 os.environ 覆盖
     （优先于 .env；文件损坏/校验失败 → 抛 DeploymentConfigError 拒启，fail-closed）
  ③ Settings() 实例化，天然读到覆盖值

保存走 apply_deployment_config()（配置中心 API 调用）：
  备份轮换(.bak.1-.3) → backend/.env 镜像 → data-sync/.env 双写（限同步键）
  → JSON 原子写；任一步失败按字节快照整体回滚，拒绝半应用状态。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
CONFIG_FILENAME = "deployment.config.json"
BACKUP_KEEP = 3

# Code/backend（与 config.BACKEND_ROOT 同值；本模块不能 import config，故自行计算）
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

GROUP_ORDER = ("data", "runtime", "caches", "imports", "docker")
GROUP_LABELS = {
    "data": "数据根与导入导出",
    "runtime": "运行时与日志",
    "caches": "缓存",
    "imports": "导入配额",
    "docker": "Docker / Open-Meteo",
}


class DeploymentConfigError(RuntimeError):
    """部署配置文件损坏/校验失败（fail-closed 拒启）。"""


@dataclass(frozen=True)
class KeySpec:
    group: str
    key: str
    env_key: str
    kind: str  # path | path_file | int | str | password | url | level
    label: str
    restart_level: str = "restart-backend"  # restart-backend | restart-full
    must_exist: bool = False  # 要求目录已存在（data_root / output_root）
    min_value: int | None = None
    max_value: int | None = None
    choices: tuple[str, ...] = ()
    double_write_sync: bool = False  # 同时写 Code/infra/data-sync/.env
    settings_field: str | None = None  # Settings 字段名（运行值投影；None=仅 env 消费）


_SPECS: tuple[KeySpec, ...] = (
    # ---- data：数据根与导入导出 ----
    KeySpec(
        "data",
        "data_root",
        "BACKEND_DATA_ROOT",
        "path",
        "地理数据根目录（部署机数据盘挂载点）",
        must_exist=True,
        settings_field="data_root",
    ),
    KeySpec(
        "data",
        "output_root",
        "BACKEND_OUTPUT_ROOT",
        "path",
        "产出结果/报告/分析图表输出根",
        must_exist=True,
        settings_field="output_root",
    ),
    KeySpec(
        "data",
        "project_backup_root",
        "BACKEND_PROJECTBACKUP_ROOT",
        "path",
        "项目备份根（算法 dataset_config 消费）",
    ),
    # ---- runtime：运行时与日志 ----
    KeySpec(
        "runtime",
        "runtime_root",
        "BACKEND_RUNTIME_ROOT",
        "path",
        "运行时根（未设时派生自 <data_root>/_runtime）",
    ),
    KeySpec(
        "runtime",
        "workflow_state_dir",
        "BACKEND_WORKFLOW_STATE_DIR",
        "path",
        "工作流状态目录（节点/任务状态）",
        settings_field="workflow_state_dir",
    ),
    KeySpec(
        "runtime",
        "log_dir",
        "BACKEND_LOG_DIR",
        "path",
        "后端日志目录",
        settings_field="log_dir",
    ),
    KeySpec(
        "runtime",
        "log_level",
        "BACKEND_LOG_LEVEL",
        "level",
        "日志级别",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        settings_field="log_level",
    ),
    KeySpec(
        "runtime",
        "result_artifact_dir",
        "BACKEND_RESULT_ARTIFACT_DIR",
        "path",
        "工作流产物/工件目录",
        settings_field="result_artifact_dir",
    ),
    KeySpec(
        "runtime",
        "python_provider_workspace",
        "BACKEND_PYTHON_PROVIDER_WORKSPACE",
        "path",
        "Python 算法工作区",
        settings_field="python_provider_workspace",
    ),
    KeySpec(
        "runtime",
        "spatialite_db_path",
        "BACKEND_SPATIALITE_DB_PATH",
        "path_file",
        "SpatiaLite 叠加层数据库文件路径",
        settings_field="spatialite_db_path",
    ),
    # ---- caches：缓存 ----
    KeySpec(
        "caches",
        "cache_dir",
        "BACKEND_CACHE_DIR",
        "path",
        "通用缓存目录（天气文件缓存等）",
        settings_field="cache_dir",
    ),
    KeySpec(
        "caches",
        "static_cache_root",
        "BACKEND_STATIC_CACHE_ROOT",
        "path",
        "静态物化缓存根（远程/HTTP 下载节点）",
    ),
    KeySpec(
        "caches",
        "static_cache_ttl_seconds",
        "BACKEND_STATIC_CACHE_TTL_SECONDS",
        "int",
        "静态缓存 TTL 秒（0=永不过期）",
        min_value=0,
    ),
    KeySpec(
        "caches",
        "download_source_root",
        "BACKEND_DOWNLOAD_SOURCE_ROOT",
        "path",
        "真实数据保存与下载位置（下载源根）",
        settings_field="download_source_root",
    ),
    KeySpec(
        "caches",
        "cache_default_ttl_seconds",
        "BACKEND_CACHE_DEFAULT_TTL_SECONDS",
        "int",
        "默认缓存 TTL 秒",
        min_value=0,
        settings_field="cache_default_ttl_seconds",
    ),
    KeySpec(
        "caches",
        "tile_proxy_cache_ttl_seconds",
        "BACKEND_TILE_PROXY_CACHE_TTL_SECONDS",
        "int",
        "瓦片代理缓存 TTL 秒",
        min_value=0,
        settings_field="tile_proxy_cache_ttl_seconds",
    ),
    # ---- imports：导入配额 ----
    KeySpec(
        "imports",
        "max_imports_total_bytes",
        "BACKEND_MAX_IMPORTS_TOTAL_BYTES",
        "int",
        "导入永久层总配额（字节）",
        min_value=1,
    ),
    KeySpec(
        "imports",
        "imports_soft_reserve_bytes",
        "BACKEND_IMPORTS_SOFT_RESERVE_BYTES",
        "int",
        "导入软预留（字节，0=禁用）",
        min_value=0,
    ),
    # ---- docker：Docker / Open-Meteo ----
    KeySpec(
        "docker",
        "minio_root_user",
        "MINIO_ROOT_USER",
        "str",
        "MinIO root 用户（compose 注入）",
        restart_level="restart-full",
    ),
    KeySpec(
        "docker",
        "minio_root_password",
        "MINIO_ROOT_PASSWORD",
        "password",
        "MinIO root 密码（留空保持不变）",
        restart_level="restart-full",
    ),
    KeySpec(
        "docker",
        "open_meteo_host_port",
        "OPEN_METEO_HOST_PORT",
        "int",
        "Open-Meteo 宿主端口",
        min_value=1,
        max_value=65535,
        restart_level="restart-full",
    ),
    KeySpec(
        "docker",
        "open_meteo_data_volume",
        "OPEN_METEO_DATA_VOLUME",
        "str",
        "Open-Meteo 共享 named volume 名",
        restart_level="restart-full",
        double_write_sync=True,
    ),
    KeySpec(
        "docker",
        "open_meteo_sync_domains",
        "OPEN_METEO_SYNC_DOMAINS",
        "str",
        "同步气象模型（逗号分隔；visibility 需 gfs_global）",
        double_write_sync=True,
        settings_field="open_meteo_sync_domains",
    ),
    KeySpec(
        "docker",
        "open_meteo_sync_variables",
        "OPEN_METEO_SYNC_VARIABLES",
        "str",
        "同步变量列表（逗号分隔）",
        double_write_sync=True,
        settings_field="open_meteo_sync_variables",
    ),
    KeySpec(
        "docker",
        "open_meteo_local_url",
        "BACKEND_OPEN_METEO_LOCAL_URL",
        "url",
        "Open-Meteo 本地 API URL",
    ),
)

SPEC_BY_FIELD: dict[tuple[str, str], KeySpec] = {(s.group, s.key): s for s in _SPECS}

_STARTUP_APPLIED: list[str] = []


def deployment_config_path() -> Path:
    override = os.getenv("BACKEND_DEPLOYMENT_CONFIG", "").strip()
    if override:
        return Path(override)
    return _BACKEND_ROOT / CONFIG_FILENAME


def data_sync_env_path() -> Path:
    override = os.getenv("BACKEND_OPEN_METEO_SYNC_COMPOSE_DIR", "").strip()
    base = Path(override) if override else _BACKEND_ROOT.parent / "infra" / "data-sync"
    return base / ".env"


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _corrupt_message(path: Path, reason: str) -> str:
    bak = path.with_name(f"{path.name}.bak.1")
    hint = (
        f"；可用备份 {bak} 覆盖恢复后重启"
        if bak.is_file()
        else "（无可用备份：请修复或删除该文件后重启）"
    )
    return f"部署配置文件无效，拒绝启动（fail-closed）: {path} — {reason}{hint}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeploymentConfigError(_corrupt_message(path, f"无法读取: {exc}")) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeploymentConfigError(
            _corrupt_message(path, f"JSON 解析失败: {exc}")
        ) from exc
    if not isinstance(payload, dict):
        raise DeploymentConfigError(_corrupt_message(path, "顶层必须为 JSON 对象"))
    return payload


def load_deployment_config() -> dict[str, Any] | None:
    """读取并解析部署配置文件；文件不存在返回 None，损坏抛错（fail-closed）。"""
    path = deployment_config_path()
    if not path.is_file():
        return None
    return _read_json(path)


def _validate_field(
    spec: KeySpec, value: Any, result: ValidationResult, *, create_dirs: bool
) -> None:
    label = f"{spec.group}.{spec.key}"
    if value is None:
        return
    if spec.kind in {"path", "path_file"}:
        if not isinstance(value, str):
            result.errors.append(f"{label} 必须为字符串路径")
            return
        raw = value.strip()
        if not raw:
            return  # 空串 = 未设置，不覆盖
        path = Path(raw).expanduser()
        if not path.is_absolute():
            result.errors.append(f"{label} 必须为绝对路径: {raw}")
            return
        if spec.kind == "path_file":
            if path.exists() and path.is_dir():
                result.errors.append(f"{label} 指向目录，应为文件路径: {raw}")
                return
            if not path.parent.exists():
                result.warnings.append(f"{label} 父目录不存在: {raw}")
            result.normalized.setdefault(spec.group, {})[spec.key] = str(path)
            return
        if path.exists():
            if not path.is_dir():
                result.errors.append(f"{label} 存在但不是目录: {raw}")
                return
        elif spec.must_exist:
            result.errors.append(f"{label} 目录不存在（须先在部署机创建）: {raw}")
            return
        elif create_dirs:
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                result.errors.append(f"无法创建 {label}: {raw} ({exc})")
                return
        else:
            result.warnings.append(f"{label} 目录不存在，应用时将自动创建: {raw}")
        result.normalized.setdefault(spec.group, {})[spec.key] = str(path)
        return
    if spec.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            result.errors.append(f"{label} 必须为整数，当前为 {value!r}")
            return
        if spec.min_value is not None and value < spec.min_value:
            result.errors.append(f"{label} 不能小于 {spec.min_value}: {value}")
            return
        if spec.max_value is not None and value > spec.max_value:
            result.errors.append(f"{label} 不能大于 {spec.max_value}: {value}")
            return
        result.normalized.setdefault(spec.group, {})[spec.key] = value
        return
    # str / password / url / level
    if not isinstance(value, str):
        result.errors.append(f"{label} 必须为字符串，当前为 {value!r}")
        return
    raw = value.strip()
    if not raw:
        return  # 空串 = 未设置（password：留空保持不变）
    if spec.kind == "level":
        upper = raw.upper()
        if upper not in spec.choices:
            result.errors.append(f"{label} 必须为 {list(spec.choices)} 之一: {raw}")
            return
        result.normalized.setdefault(spec.group, {})[spec.key] = upper
        return
    if spec.kind == "url" and not raw.startswith(("http://", "https://")):
        result.errors.append(f"{label} 必须为 http(s) URL: {raw}")
        return
    result.normalized.setdefault(spec.group, {})[spec.key] = raw


def validate_payload(payload: Any, *, create_dirs: bool = False) -> ValidationResult:
    """全量校验部署配置 payload。

    create_dirs=False（preview）：纯只读，缺失缓存目录仅告警；
    create_dirs=True（apply）：允许自动创建缓存类目录（对齐
    config_service.update_data_source_paths 语义）。
    """
    result = ValidationResult()
    if not isinstance(payload, dict):
        result.errors.append("部署配置必须为 JSON 对象")
        return result
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        result.errors.append(
            f"schema_version 必须为 {SCHEMA_VERSION}，当前为 {version!r}"
        )
    known_top = set(GROUP_ORDER) | {"schema_version", "notes"}
    for key in payload:
        if key not in known_top:
            result.errors.append(f"未知顶层键: {key!r}")
    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        result.errors.append("notes 必须为字符串")
    for group in GROUP_ORDER:
        group_value = payload.get(group)
        if group_value is None:
            continue
        if not isinstance(group_value, dict):
            result.errors.append(f"分组 {group} 必须为对象")
            continue
        for key, value in group_value.items():
            spec = SPEC_BY_FIELD.get((group, key))
            if spec is None:
                result.errors.append(f"分组 {group} 中未知键: {key!r}")
                continue
            _validate_field(spec, value, result, create_dirs=create_dirs)
    return result


def format_env_value(spec: KeySpec, value: Any) -> str:
    if spec.kind == "int":
        return str(int(value))
    return str(value)


def _linked_output_root_value(
    normalized: dict[str, dict[str, Any]], env_values: dict[str, str]
) -> str | None:
    """data_root 变更时产物根联动派生（"所有数据都存在数据根下"语义）。

    触发条件：payload 设置了 data.data_root 且未显式设置 data.output_root，
    且新 data_root 与当前生效值（.env 镜像优先，其次运行值）不同——即数据根
    正在迁移（首次设置亦视为迁移）。派生值 = <新数据根>/ProjectOutput，与旧
    设置页"产物根留空 = 默认 data_root/ProjectOutput"语义一致。

    派生值只写 .env 镜像、不写入 deployment.config.json（保持隐式：后续换根
    继续跟随）；显式设置 output_root 时本函数不介入。
    """
    data_group = normalized.get("data", {})
    if "data_root" not in data_group or "output_root" in data_group:
        return None
    root_spec = SPEC_BY_FIELD[("data", "data_root")]
    out_spec = SPEC_BY_FIELD[("data", "output_root")]
    new_root = format_env_value(root_spec, data_group["data_root"])
    current_root = env_values.get(root_spec.env_key, "").strip() or _runtime_value(
        root_spec
    )
    if current_root == new_root:
        return None
    derived = str(Path(new_root) / "ProjectOutput")
    # .env 已是该派生值则无需写（避免无变化时误报 pending_restart）
    if env_values.get(out_spec.env_key, "").strip() == derived:
        return None
    return derived


def apply_startup_overrides() -> list[str]:
    """config.py 加载期调用：deployment.json 逐键覆盖 os.environ（优先于 .env）。

    返回被覆盖的 env 键清单（供启动日志审计）。文件损坏/校验失败抛
    DeploymentConfigError → config 导入失败 → 进程拒启（fail-closed）。
    """
    global _STARTUP_APPLIED
    path = deployment_config_path()
    if not path.is_file():
        _STARTUP_APPLIED = []
        return []
    payload = _read_json(path)
    result = validate_payload(payload)
    if not result.ok:
        reason = "schema 校验失败: " + "; ".join(result.errors[:5])
        raise DeploymentConfigError(_corrupt_message(path, reason))
    applied: list[str] = []
    for group in GROUP_ORDER:
        for key, value in result.normalized.get(group, {}).items():
            spec = SPEC_BY_FIELD[(group, key)]
            os.environ[spec.env_key] = format_env_value(spec, value)
            applied.append(spec.env_key)
    _STARTUP_APPLIED = applied
    return applied


def startup_status() -> dict[str, Any]:
    return {
        "path": str(deployment_config_path()),
        "exists": deployment_config_path().is_file(),
        "applied_env_keys": list(_STARTUP_APPLIED),
    }


def key_metadata() -> list[dict[str, Any]]:
    """键元数据（API/前端共享：分组、env 键、校验约束、生效方式）。"""
    return [
        {
            "group": s.group,
            "group_label": GROUP_LABELS[s.group],
            "key": s.key,
            "env_key": s.env_key,
            "kind": s.kind,
            "label": s.label,
            "restart_level": s.restart_level,
            "must_exist": s.must_exist,
            "sensitive": s.kind == "password",
            "double_write_sync": s.double_write_sync,
        }
        for s in _SPECS
    ]


def rotate_backups(path: Path) -> list[str]:
    """轮换备份：.bak.(i-1)→.bak.i，当前文件复制为 .bak.1，保留 BACKUP_KEEP 份。"""
    rotated: list[str] = []
    for i in range(BACKUP_KEEP, 1, -1):
        src = path.with_name(f"{path.name}.bak.{i - 1}")
        dst = path.with_name(f"{path.name}.bak.{i}")
        if src.exists():
            os.replace(src, dst)
    if path.exists():
        first = path.with_name(f"{path.name}.bak.1")
        shutil.copyfile(path, first)
        rotated.append(first.name)
    return rotated


def list_backups() -> list[dict[str, Any]]:
    path = deployment_config_path()
    out: list[dict[str, Any]] = []
    for i in range(1, BACKUP_KEEP + 1):
        bak = path.with_name(f"{path.name}.bak.{i}")
        if bak.is_file():
            stat = bak.stat()
            out.append(
                {
                    "name": bak.name,
                    "path": str(bak),
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
    return out


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _read_bytes_or_none(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _restore(path: Path, old: bytes | None) -> None:
    if old is not None:
        _atomic_write_bytes(path, old)
    elif path.exists():
        with contextlib.suppress(OSError):
            path.unlink()


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """导出/回显脱敏：password 类键替换为掩码。"""
    redacted = json.loads(json.dumps(payload, ensure_ascii=False))
    for group, keys in redacted.items():
        if not isinstance(keys, dict):
            continue
        for key in list(keys):
            spec = SPEC_BY_FIELD.get((group, key))
            if spec is not None and spec.kind == "password" and keys[key]:
                keys[key] = "••••"
    return redacted


def apply_deployment_config(payload: dict[str, Any]) -> dict[str, Any]:
    """校验 → 备份 → 双 .env 镜像 → JSON 原子写；任一步失败整体回滚。

    只写非空键（空串/null = 未设置，不覆盖；password 留空 = 保持不变）。
    不修改当前进程 os.environ：变更经重启生效（返回 pending_restart=True）。
    """
    result = validate_payload(payload, create_dirs=True)
    if not result.ok:
        raise DeploymentConfigError(
            "部署配置校验失败，未做任何修改: " + "; ".join(result.errors)
        )

    env_updates: dict[str, str] = {}
    sync_updates: dict[str, str] = {}
    restart_full = False
    for group in GROUP_ORDER:
        for key, value in result.normalized.get(group, {}).items():
            spec = SPEC_BY_FIELD[(group, key)]
            formatted = format_env_value(spec, value)
            env_updates[spec.env_key] = formatted
            if spec.double_write_sync:
                sync_updates[spec.env_key] = formatted
            if spec.restart_level == "restart-full":
                restart_full = True

    from app.services.env_file_upsert import read_env_file_values

    env_path = _BACKEND_ROOT / ".env"
    linked_output = _linked_output_root_value(
        result.normalized, read_env_file_values(env_path)
    )
    if linked_output is not None:
        try:
            Path(linked_output).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DeploymentConfigError(
                f"无法创建派生产物根 {linked_output}: {exc}"
            ) from exc
        env_updates[SPEC_BY_FIELD[("data", "output_root")].env_key] = linked_output
        result.warnings.append(
            f"data.output_root 未显式设置，已随 data_root 联动派生为 {linked_output}"
            "（仅写 .env 镜像；再次换根时将继续跟随）"
        )

    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        **{g: result.normalized.get(g, {}) for g in GROUP_ORDER},
    }
    if isinstance(payload.get("notes"), str):
        doc["notes"] = payload["notes"]
    json_bytes = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    json_path = deployment_config_path()
    sync_path = data_sync_env_path()
    snapshots = {
        json_path: _read_bytes_or_none(json_path),
        env_path: _read_bytes_or_none(env_path),
        sync_path: _read_bytes_or_none(sync_path),
    }
    backups = rotate_backups(json_path)

    from app.services.env_file_upsert import upsert_env_keys

    try:
        if env_updates:
            upsert_env_keys(env_updates, path=env_path)
        if sync_updates:
            upsert_env_keys(sync_updates, path=sync_path)
        _atomic_write_bytes(json_path, json_bytes)
    except BaseException as exc:
        for path, old in snapshots.items():
            _restore(path, old)
        logger.exception("Deployment config apply failed; all files rolled back")
        raise DeploymentConfigError(
            f"应用部署配置失败，已整体回滚（无半应用状态）: {exc}"
        ) from exc

    return {
        "applied_env_keys": sorted(env_updates),
        "sync_env_keys": sorted(sync_updates),
        "config_path": str(json_path),
        "env_path": str(env_path),
        "sync_env_path": str(sync_path) if sync_updates else None,
        "restart_level": "restart-full" if restart_full else "restart-backend",
        "pending_restart": bool(env_updates),
        "warnings": result.warnings,
        "backups": backups,
    }


def _runtime_value(spec: KeySpec) -> str:
    """当前运行进程实际消费的值（Settings 字段优先，其次 os.environ）。"""
    if spec.settings_field:
        from app.core import config  # 运行期调用（非模块加载期），可安全导入

        value = getattr(config.settings, spec.settings_field, None)
    else:
        value = os.environ.get(spec.env_key, "")
    return "" if value is None else str(value)


def _mask(spec: KeySpec, value: str) -> str:
    if spec.kind == "password" and value:
        return "••••"
    return value


def get_deployment_status() -> dict[str, Any]:
    """配置中心状态：每键三方对比（运行值 / .env / deployment.json）+ 备份列表。

    三方对比即漂移检测（§3.6C）：手改 .env 绕过中心、或保存后未重启，
    均会体现为 source/pending 字段。
    """
    from app.services.env_file_upsert import read_env_file_values

    payload = load_deployment_config()
    env_path = _BACKEND_ROOT / ".env"
    env_values = read_env_file_values(env_path)

    keys: list[dict[str, Any]] = []
    pending_restart = False
    for spec in _SPECS:
        raw_group = (payload or {}).get(spec.group)
        raw_config = raw_group.get(spec.key) if isinstance(raw_group, dict) else None
        config_value = "" if raw_config is None else str(raw_config)
        env_value = env_values.get(spec.env_key, "")
        runtime_value = _runtime_value(spec)
        if config_value:
            source = "config"
        elif env_value:
            source = "env"
        else:
            source = "default"
        desired = config_value or env_value
        pending = bool(desired) and runtime_value != desired
        if pending:
            pending_restart = True
        keys.append(
            {
                "group": spec.group,
                "group_label": GROUP_LABELS[spec.group],
                "key": spec.key,
                "env_key": spec.env_key,
                "kind": spec.kind,
                "label": spec.label,
                "restart_level": spec.restart_level,
                "must_exist": spec.must_exist,
                "sensitive": spec.kind == "password",
                "double_write_sync": spec.double_write_sync,
                "runtime_value": _mask(spec, runtime_value),
                "env_value": _mask(spec, env_value),
                "config_value": _mask(spec, config_value),
                "source": source,
                "pending": pending,
            }
        )

    return {
        "path": str(deployment_config_path()),
        "exists": payload is not None,
        "schema_version": (payload or {}).get("schema_version", SCHEMA_VERSION),
        "applied_env_keys": startup_status()["applied_env_keys"],
        "keys": keys,
        "backups": list_backups(),
        "pending_restart": pending_restart,
        "env_path": str(env_path),
        "sync_env_path": str(data_sync_env_path()),
        "notes": (payload or {}).get("notes", ""),
    }


def preview_deployment_config(payload: dict[str, Any]) -> dict[str, Any]:
    """纯只读预览：全量校验 + 与当前运行值的 diff（不写任何文件、不建目录）。"""
    result = validate_payload(payload)
    diff: list[dict[str, Any]] = []
    restart_full = False
    for group in GROUP_ORDER:
        for key, value in result.normalized.get(group, {}).items():
            spec = SPEC_BY_FIELD[(group, key)]
            new_value = format_env_value(spec, value)
            old_value = _runtime_value(spec)
            if old_value == new_value:
                continue
            if spec.restart_level == "restart-full":
                restart_full = True
            diff.append(
                {
                    "group": group,
                    "key": key,
                    "env_key": spec.env_key,
                    "old": _mask(spec, old_value),
                    "new": _mask(spec, new_value),
                    "restart_level": spec.restart_level,
                }
            )
    from app.services.env_file_upsert import read_env_file_values

    linked_output = _linked_output_root_value(
        result.normalized, read_env_file_values(_BACKEND_ROOT / ".env")
    )
    if linked_output is not None:
        out_spec = SPEC_BY_FIELD[("data", "output_root")]
        old_output = _runtime_value(out_spec)
        if old_output != linked_output:
            diff.append(
                {
                    "group": "data",
                    "key": "output_root",
                    "env_key": out_spec.env_key,
                    "old": _mask(out_spec, old_output),
                    "new": linked_output,
                    "restart_level": "restart-backend",
                    "derived": True,
                }
            )
        result.warnings.append(
            f"data.output_root 未显式设置，将随 data_root 联动派生为 {linked_output}"
            "（应用时自动创建目录；仅写 .env 镜像，不写入 deployment.config.json）"
        )
    restart_level = "none"
    if diff:
        restart_level = "restart-full" if restart_full else "restart-backend"
    return {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "diff": diff,
        "restart_level": restart_level,
    }
