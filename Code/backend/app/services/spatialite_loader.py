"""跨平台 mod_spatialite 加载器。

为现有 SQLite 元数据层引入 SpatiaLite 空间扩展能力，作为从「纯 SQLite 元数据」
过渡到「服务端空间 SQL」的隔离数据平面（不迁 Postgres、不动高风险区 state DB）。

设计约束（见计划 toasty-aurora-curie.md）：
- **统一加载**：所有池化连接都尝试加载（`_sqlite_pool` + `workflow_timer_service` 等）。
- **优雅降级**：扩展缺失 / stdlib 不支持 load_extension / 加载失败 → 仅 warn 返回 False，
  绝不抛异常，state/metadata DB（workflow/api_keys/gee_credentials，AGENTS.md 高风险区）
  必须能正常打开。
- **安全**：加载后立即 `enable_load_extension(False)`，防止后续滥用 load_extension。
- **跨平台**：Windows 走 gaia-gis 预编译包（`Env/Python312/Extras/spatialite/`）+ OSGeo4W 探测；
  Linux 走 `apt install libsqlite3-mod-spatialite`（`/usr/lib/x86_64-linux-gnu/mod_spatialite.so`）。

关键区分：
- ``load_into(conn)`` —— 仅启用空间 SQL 函数（ST_*/GeomFromText/BuildMBR...），对所有连接调。
- ``init_spatial_metadata(conn)`` —— 填充 ``spatial_ref_sys`` 等元数据表，**只对 spatial.sqlite 调一次**，
  绝不复用到 state DB（否则会往无关库写元数据表，污染高风险区）。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 仓库根：services → app → backend → Code → repo
_REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class _ProbeResult:
    """mod_spatialite 可用性探测结果（缓存）。"""

    available: bool
    path: Path | None
    reason: str = ""


_probe_cache: _ProbeResult | None = None
_dll_search_registered: bool = False  # Windows 依赖目录是否已注册进 DLL 搜索路径
# 不可用 / 加载失败只 warn 一次，避免每个新连接刷屏
_unavailable_warned: bool = False
_load_fail_warned: bool = False


def _resolve_extension_path() -> Path | None:
    """按平台搜索顺序解析 mod_spatialite 文件路径。

    顺序：
    1. env ``BACKEND_SPATIALITE_PATH``（文件或目录；目录则自动找 mod_spatialite.{dll,so}）
    2. Windows: ``Env/Python312/Extras/spatialite/mod_spatialite.dll`` → ``%OSGEO4W_ROOT%/bin/mod_spatialite.dll``
    3. Linux: ``/usr/lib/x86_64-linux-gnu/mod_spatialite.so`` → ``/usr/lib/mod_spatialite.so``
       → 裸名 ``mod_spatialite.so``（让 dlopen 走默认搜索路径）
    """
    env_override = os.getenv("BACKEND_SPATIALITE_PATH", "").strip()
    if env_override:
        p = Path(env_override)
        if p.is_file():
            return p
        # 容许指向目录
        for cand in (p / "mod_spatialite.dll", p / "mod_spatialite.so"):
            if cand.is_file():
                return cand

    if sys.platform == "win32":
        candidates = [
            # gaia-gis 预编译包主路径（手动放置）
            _REPO_ROOT
            / "Env"
            / "Python312"
            / "Extras"
            / "spatialite"
            / "mod_spatialite.dll",
            # OSGeo4W 自动探测
            Path(os.environ.get("OSGEO4W_ROOT", "")) / "bin" / "mod_spatialite.dll",
        ]
        for c in candidates:
            try:
                if c and c.is_file():
                    return c
            except (OSError, ValueError):
                continue
        return None

    if sys.platform.startswith("linux"):
        for c in (
            Path("/usr/lib/x86_64-linux-gnu/mod_spatialite.so"),
            Path("/usr/lib/mod_spatialite.so"),
        ):
            if c.is_file():
                return c
        # 兜底：返回裸名，让 OS 动态链接器按默认路径解析；失败由 load_into 兜住
        return Path("mod_spatialite.so")

    return None


def _ensure_dll_search(ext_dir: Path) -> None:
    """Windows：把 mod_spatialite 的依赖目录注册进 DLL 搜索路径（一次性）。

    mod_spatialite.dll 依赖 GEOS/PROJ/RT-Topo/freexl/iconv。Windows 的 LoadLibrary
    默认不会从 DLL 自身所在目录解析这些依赖，需把该目录加入搜索路径。

    实测：sqlite 内部 ``LoadLibrary`` 不一定受 ``os.add_dll_directory`` 影响，故**主路径
    用 PATH prepend** 把同目录置于搜索最前，确保用 gaia-gis bundle 自带的全套同源依赖；
    ``os.add_dll_directory`` 仅作为补充（对部分 sqlite/Python 组合有帮助，且互不冲突）。
    """
    global _dll_search_registered
    if _dll_search_registered or sys.platform != "win32":
        return
    _dll_search_registered = True
    # 主路径：PATH prepend（让 mod_spatialite 的 GEOS/PROJ 等依赖同目录优先命中）
    cur = os.environ.get("PATH", "")
    if str(ext_dir) not in cur.split(os.pathsep):
        os.environ["PATH"] = f"{ext_dir}{os.pathsep}{cur}"
        logger.info("Prepended SpatiaLite dep dir to PATH: %s", ext_dir)
    # 补充：add_dll_directory（不冲突，部分组合下也有帮助）
    try:
        os.add_dll_directory(str(ext_dir))
    except Exception:  # noqa: BLE001
        pass


def _probe() -> _ProbeResult:
    """探测 mod_spatialite 可用性（缓存）。先探 stdlib 是否支持 load_extension，再解析路径。"""
    global _probe_cache
    if _probe_cache is not None:
        return _probe_cache

    # 1. 探测 Python stdlib 是否编译了 loadable extension 支持
    try:
        tmp = sqlite3.connect(":memory:")
        tmp.enable_load_extension(True)
        tmp.enable_load_extension(False)
        tmp.close()
    except Exception as e:  # noqa: BLE001
        _probe_cache = _ProbeResult(False, None, f"stdlib no load_extension: {e}")
        return _probe_cache

    # 2. 解析扩展文件路径
    p = _resolve_extension_path()
    _probe_cache = _ProbeResult(
        available=p is not None,
        path=p,
        reason="" if p is not None else "extension file not found",
    )
    return _probe_cache


def is_available() -> bool:
    """mod_spatialite 是否可用（已探测）。"""
    return _probe().available


def _enabled() -> bool:
    """总开关：运行时读 ``BACKEND_SPATIALITE_ENABLED``，缺失回退到 settings 冻结默认值。

    注意：``app.core.config.Settings`` 是 ``@dataclass(frozen=True)``，其字段默认值在
    模块**首次导入时**由 ``os.getenv`` 求值并冻结。若 ``config.py`` 早于环境变量被导入，
    重建 ``Settings()`` 不会重新读取 env。故本函数**优先读
    ``os.getenv``**，使运行时（含启动脚本 / 容器 env / 测试 monkeypatch）可即时切换开关；
    仅在 env 未显式设置时，才回退到 settings 的冻结默认值（默认 True）。
    """
    env = os.getenv("BACKEND_SPATIALITE_ENABLED")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from app.core.config import settings

        return bool(getattr(settings, "spatialite_enabled", True))
    except Exception:  # noqa: BLE001
        return True


def load_into(conn: sqlite3.Connection) -> bool:
    """把 mod_spatialite 装载进连接。

    - **幂等（无状态）**：本连接已装载时 ``SELECT spatialite_version()`` 探测成功即返回 True。
      注：``sqlite3.Connection`` 是 C 扩展类型，**不能挂载自定义属性、也不能弱引用**，
      故用一次极轻量空间函数探测代替「已加载」状态位——无状态存储、无 ``id()`` 复用歧义、
      无内存泄漏，且对任意平台一致。
    - 优雅降级：扩展缺失 / stdlib 不支持 / 加载失败 → warn 返回 False，**永不抛**。
    - 安全：加载后立即 ``enable_load_extension(False)``。

    Returns:
        True 表示已加载（本调用或之前）；False 表示未加载（关闭开关 / 不可用 / 失败）。
    """
    if not _enabled():
        return False

    global _unavailable_warned, _load_fail_warned

    # 1. 扩展全局不可用（路径缺失 / stdlib 不支持）→ 直接降级。
    #    _probe 结果已缓存，后续冷连接仅做一次字典查找，零 I/O、零失败 SQL。
    probe = _probe()
    if not probe.available:
        if not _unavailable_warned:
            logger.warning(
                "SpatiaLite extension not available (%s); spatial features disabled",
                probe.reason or "unknown",
            )
            _unavailable_warned = True
        return False

    # 2. 本连接已加载？一次极廉价的空间函数探测（比 re-enable + re-load 更快且无副作用）
    try:
        conn.execute("SELECT spatialite_version()")
        return True
    except sqlite3.OperationalError:
        pass  # 未加载 → 继续加载
    except Exception:  # noqa: BLE001
        # 连接已关闭等异常不应阻塞调用方
        return False

    # 3. 未加载 → 真正加载
    ext_path = probe.path
    assert ext_path is not None  # available=True 时 path 必非空

    try:
        if sys.platform == "win32" and ext_path.parent != Path("."):
            _ensure_dll_search(ext_path.parent)
        conn.enable_load_extension(True)
        try:
            conn.load_extension(str(ext_path))
        except sqlite3.OperationalError as e:
            # 同名扩展已加载（SpatiaLite 视为 idempotent）会回显 already loaded，视为成功
            if "already" in str(e).lower():
                pass
            else:
                raise
        conn.enable_load_extension(False)  # 立即关闭，防后续滥用
        return True
    except sqlite3.OperationalError as e:
        if not _load_fail_warned:
            logger.warning(
                "SpatiaLite load_extension failed (%s); spatial features disabled", e
            )
            _load_fail_warned = True
        try:
            conn.enable_load_extension(False)
        except Exception:  # noqa: BLE001
            pass
        return False
    except Exception as e:  # noqa: BLE001
        if not _load_fail_warned:
            logger.warning(
                "SpatiaLite load_into unexpected error: %s", e, exc_info=True
            )
            _load_fail_warned = True
        try:
            conn.enable_load_extension(False)
        except Exception:  # noqa: BLE001
            pass
        return False


def init_spatial_metadata(conn: sqlite3.Connection) -> bool:
    """对新空间库运行 ``SELECT InitSpatialMetaData(1)``（填充 spatial_ref_sys 等元数据表）。

    已初始化的库会抛 'already initialized'，吞掉返回 True。
    **只对 spatial.sqlite 调用**，绝不复用到 state DB（避免污染高风险区）。

    Returns:
        True 表示已初始化或本次初始化成功；False 表示扩展不可用或初始化失败。
    """
    if not load_into(conn):
        return False
    try:
        conn.execute("SELECT InitSpatialMetaData(1)")
        return True
    except sqlite3.OperationalError as e:
        if "already" in str(e).lower():
            return True
        logger.warning("InitSpatialMetaData failed: %s", e)
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("InitSpatialMetaData unexpected error: %s", e, exc_info=True)
        return False


def reset_probe_cache() -> None:
    """重置探测缓存（仅供测试：monkeypatch env 后重新探测）。

    注意：不重置连接「已加载」状态——sqlite3.Connection 不可弱引用，本模块改用
    无状态探测（SELECT spatialite_version()），故无需清除；测试中每个连接都是独立的
    :memory: 实例，重新探测即可。
    """
    global _probe_cache, _dll_search_registered, _unavailable_warned, _load_fail_warned
    _probe_cache = None
    _dll_search_registered = False
    _unavailable_warned = False
    _load_fail_warned = False
