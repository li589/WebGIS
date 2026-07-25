#!/usr/bin/env python3
"""从 NASA NSIDC 下载 SMAP L3 SMAP_E (SPL3SMP_E) V6 土壤湿度数据。

数据产品:
    SMAP L3 Soil Moisture Passive Enhanced (SPL3SMP_E) Version 6
    NSIDC 页面: https://nsidc.org/data/spl3smp_e/versions/6

主路径使用 earthaccess 库（NASA 官方推荐）；若未安装 earthaccess，
自动回退到 requests + CMR + HTTP Basic Auth 的手动实现，并打印 pip 安装提示。

主要特性:
    - 日期范围 / 单日下载（--start-date/--end-date 或 --date）
    - 增量下载：跳过本地已存在文件（按文件名 + 大小判断）
    - --dry-run 预览模式：列出待下载文件但不实际下载
    - --max-files：限制单次下载文件数量
    - 断点续传（HTTP Range）
    - 失败自动重试（最多 3 次，指数退避）
    - 下载进度显示与统计信息
    - 日志记录到 I:\\Geograph_DataSet\\_runtime\\logs
    - Earthdata 认证测试 + 下载前磁盘空间检查

凭据策略:
    优先读取环境变量 EARTHDATA_USERNAME / EARTHDATA_PASSWORD；
    若未设置，回退到内置默认值并打印警告（建议改用环境变量以避免硬编码）。

用法示例:
    python download_smap_nsidc.py --date 2023-01-10
    python download_smap_nsidc.py --start-date 2023-01-01 --end-date 2023-01-31
    python download_smap_nsidc.py --start-date 2023-01-01 --end-date 2023-01-31 --dry-run
    python download_smap_nsidc.py --date 2023-01-10 --max-files 2
    python download_smap_nsidc.py --date 2023-01-10 --output-dir D:\\tmp\\smap
    python download_smap_nsidc.py --test-auth

环境变量:
    EARTHDATA_USERNAME  Earthdata 用户名
    EARTHDATA_PASSWORD  Earthdata 密码
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# ─── 常量 ────────────────────────────────────────────────────────────────────

DEFAULT_OUTPUT_DIR = Path(r"I:\Geograph_DataSet\Soil_Moisture\SMAP")
LOG_DIR = Path(r"I:\Geograph_DataSet\_runtime\logs")

# 回退默认凭据（建议通过环境变量 EARTHDATA_USERNAME / EARTHDATA_PASSWORD 覆盖）
DEFAULT_USERNAME = "Rejoyce"
DEFAULT_PASSWORD = "Diandian143"

SHORT_NAME = "SPL3SMP_E"  # SMAP L3 Soil Moisture Passive Enhanced
VERSION = "6"

MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0  # 秒，指数退避基数
CHUNK_SIZE = 262144  # 256 KB 流式下载块
REQUEST_TIMEOUT = 60  # 普通请求超时（秒）
DOWNLOAD_TIMEOUT = 3600  # 下载流超时（秒）
MIN_DISK_FREE_GB = 5.0  # 下载前最低可用空间（GB）
PROGRESS_INTERVAL = 2.0  # 进度打印间隔（秒）

# 尝试导入 earthaccess（可选依赖）
try:
    import earthaccess  # type: ignore

    _HAS_EARTHACCESS = True
except ImportError:  # pragma: no cover
    earthaccess = None  # type: ignore
    _HAS_EARTHACCESS = False

logger = logging.getLogger("download_smap_nsidc")


# ─── 数据类 ──────────────────────────────────────────────────────────────────


@dataclass
class DownloadConfig:
    """下载任务配置。"""

    short_name: str = SHORT_NAME
    version: str = VERSION
    start_date: str | None = None
    end_date: str | None = None
    single_date: str | None = None
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    dry_run: bool = False
    max_files: int | None = None
    username: str = ""
    password: str = ""
    test_auth_only: bool = False

    def temporal_range(self) -> tuple[str, str]:
        """返回 (start, end) 的 YYYY-MM-DD 字符串。"""
        if self.single_date:
            return self.single_date, self.single_date
        assert self.start_date and self.end_date, "必须提供日期范围"
        return self.start_date, self.end_date


# ─── 通用工具 ────────────────────────────────────────────────────────────────


def format_size(size_bytes: float) -> str:
    """将字节数格式化为易读字符串。"""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


def load_credentials() -> tuple[str, str]:
    """从环境变量读取 Earthdata 凭据；未设置则回退到默认值并打印警告。"""
    username = os.environ.get("EARTHDATA_USERNAME")
    password = os.environ.get("EARTHDATA_PASSWORD")
    if username and password:
        return username, password
    print(
        "[警告] 未设置环境变量 EARTHDATA_USERNAME / EARTHDATA_PASSWORD，"
        "回退到内置默认凭据。建议在系统环境变量中配置以避免硬编码。"
    )
    logger.warning("使用内置默认凭据（环境变量 EARTHDATA_USERNAME/PASSWORD 未设置）")
    return DEFAULT_USERNAME, DEFAULT_PASSWORD


def setup_logging(log_dir: Path = LOG_DIR) -> Path:
    """配置日志：同时输出到控制台和文件，返回日志文件路径。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"download_smap_nsidc_{ts}.log"

    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return log_file


def check_disk_space(path: Path, min_gb: float = MIN_DISK_FREE_GB) -> tuple[bool, float]:
    """检查 path 所在磁盘可用空间，返回 (是否充足, 可用 GB)。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024**3)
        return free_gb >= min_gb, free_gb
    except OSError as exc:
        logger.error("磁盘空间检查失败: %s", exc)
        return False, 0.0


# ─── 认证测试 ────────────────────────────────────────────────────────────────


def test_earthdata_auth(username: str, password: str) -> bool:
    """测试 Earthdata 登录是否可用。"""
    logger.info("测试 Earthdata 认证（用户: %s）...", username)
    if _HAS_EARTHACCESS:
        try:
            earthaccess.login(username=username, password=password, persist=True)
            logger.info("earthaccess 认证成功")
            return True
        except Exception as exc:
            logger.error("earthaccess 认证失败: %s", exc)
            return False

    # 回退路径：请求 Earthdata 受保护资源验证基本认证
    try:
        import requests  # type: ignore
        from requests.auth import HTTPBasicAuth  # type: ignore

        session = requests.Session()
        session.auth = HTTPBasicAuth(username, password)
        resp = session.get(
            "https://urs.earthdata.nasa.gov/profile",
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code == 200:
            logger.info("Earthdata 认证成功（requests 回退路径）")
            return True
        logger.error("Earthdata 认证失败，HTTP %s", resp.status_code)
        return False
    except Exception as exc:
        logger.error("Earthdata 认证失败: %s", exc)
        return False


# ─── Granule 搜索 ────────────────────────────────────────────────────────────


def _granule_url(granule: Any) -> str | None:
    """从 earthaccess DataGranule 提取 .h5 下载 URL。"""
    for access in ("external", "direct", None):
        try:
            if access is None:
                links = granule.data_links()
            else:
                links = granule.data_links(access=access)
        except Exception:
            continue
        if not links:
            continue
        for link in links:
            if link.lower().endswith(".h5"):
                return link
        return links[0]
    return None


def search_granules(cfg: DownloadConfig) -> list[dict[str, Any]]:
    """搜索 granule，返回统一的 [{name, url, size_mb}, ...] 列表。"""
    start, end = cfg.temporal_range()
    logger.info(
        "搜索 %s V%s，时间范围 %s ~ %s", cfg.short_name, cfg.version, start, end
    )
    if _HAS_EARTHACCESS:
        return _search_via_earthaccess(cfg, start, end)
    logger.warning("未安装 earthaccess，使用 requests + CMR 回退搜索路径。")
    logger.warning("安装命令: pip install earthaccess")
    return _search_via_cmr(cfg, start, end)


def _search_via_earthaccess(
    cfg: DownloadConfig, start: str, end: str
) -> list[dict[str, Any]]:
    """使用 earthaccess 搜索 granule。"""
    try:
        earthaccess.login(username=cfg.username, password=cfg.password, persist=True)
    except Exception as exc:
        logger.error("earthaccess 登录失败: %s", exc)
        raise

    results = earthaccess.search_data(
        short_name=cfg.short_name,
        version=cfg.version,
        temporal=(start, end),
    )

    granules: list[dict[str, Any]] = []
    for g in results:
        url = _granule_url(g)
        if not url:
            continue
        name = url.split("/")[-1]
        size_mb: float | None = None
        try:
            size_mb = float(g.size())  # earthaccess 返回 MB
        except Exception:
            pass
        granules.append({"name": name, "url": url, "size_mb": size_mb})

    logger.info("earthaccess 搜索到 %d 个 granule", len(granules))
    return granules


def _search_via_cmr(
    cfg: DownloadConfig, start: str, end: str
) -> list[dict[str, Any]]:
    """使用 CMR UMM-JSON API 搜索 granule（earthaccess 不可用时回退）。"""
    import requests  # type: ignore

    cmr_url = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
    temporal = f"{start}T00:00:00Z,{end}T23:59:59Z"
    granules: list[dict[str, Any]] = []
    page_num = 1
    session = requests.Session()

    while True:
        params = {
            "short_name": cfg.short_name,
            "version": cfg.version,
            "temporal": temporal,
            "page_size": 2000,
            "page_num": page_num,
        }
        resp = session.get(cmr_url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break

        for item in items:
            umm = item.get("umm", {})
            related = umm.get("RelatedUrls", []) or []
            url: str | None = None
            # 优先 .h5 的 GET DATA 链接
            for r in related:
                if r.get("Type", "").startswith("GET DATA") and r.get(
                    "URL", ""
                ).lower().endswith(".h5"):
                    url = r.get("URL")
                    break
            if url is None:
                for r in related:
                    if r.get("Type", "").startswith("GET DATA"):
                        url = r.get("URL")
                        break
            if not url:
                continue

            name = url.split("/")[-1]
            size_mb: float | None = None
            dg = umm.get("DataGranule", {}) or {}
            sa = dg.get("ArchiveAndDistributionSize")
            if isinstance(sa, dict):
                try:
                    sz = float(sa.get("Size", 0))
                    unit = str(sa.get("Unit", "MB")).upper()
                    if unit == "GB":
                        size_mb = sz * 1024
                    elif unit == "KB":
                        size_mb = sz / 1024
                    else:
                        size_mb = sz
                except (TypeError, ValueError):
                    pass
            granules.append({"name": name, "url": url, "size_mb": size_mb})

        if len(items) < 2000:
            break
        page_num += 1
        if page_num > 50:  # 安全上限
            break

    logger.info("CMR 搜索到 %d 个 granule", len(granules))
    return granules


# ─── 下载 ────────────────────────────────────────────────────────────────────


def get_download_session(cfg: DownloadConfig) -> Any:
    """返回带 Earthdata 认证的 requests.Session。"""
    if _HAS_EARTHACCESS:
        try:
            auth = earthaccess.login(
                username=cfg.username, password=cfg.password, persist=True
            )
            session = auth.get_session()
            logger.debug("使用 earthaccess 认证 session 进行下载")
            return session
        except Exception as exc:
            logger.warning(
                "earthaccess session 获取失败，回退到 HTTPBasicAuth: %s", exc
            )

    import requests  # type: ignore
    from requests.auth import HTTPBasicAuth  # type: ignore

    session = requests.Session()
    session.auth = HTTPBasicAuth(cfg.username, cfg.password)
    session.headers.update({"User-Agent": "download_smap_nsidc/1.0 (Python)"})
    return session


def download_single(
    session: Any,
    url: str,
    local_path: Path,
) -> tuple[bool, int]:
    """流式下载单个文件，支持断点续传。返回 (是否成功, 本次下载字节数)。"""
    local_path.parent.mkdir(parents=True, exist_ok=True)
    existing = local_path.stat().st_size if local_path.exists() else 0

    headers: dict[str, str] = {}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        logger.info("  断点续传: 从 %s 开始", format_size(existing))

    resp = session.get(
        url,
        headers=headers,
        stream=True,
        timeout=DOWNLOAD_TIMEOUT,
        allow_redirects=True,
    )

    if resp.status_code == 416:  # Range Not Satisfiable —— 文件已完成
        resp.close()
        logger.info("  本地文件已完成，跳过")
        return True, 0

    if resp.status_code not in (200, 206):
        resp.close()
        raise RuntimeError(f"HTTP {resp.status_code} 下载失败: {url}")

    # 206 = 断点续传追加；200 = 全新写入
    mode = "ab" if resp.status_code == 206 else "wb"
    if mode == "wb" and existing > 0:
        existing = 0  # 服务器不支持 Range，从头开始

    content_length = int(resp.headers.get("Content-Length", 0))
    total = content_length + existing
    downloaded = 0
    last_report = time.time()

    try:
        with open(local_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_report >= PROGRESS_INTERVAL:
                    cur = existing + downloaded
                    pct = (cur / total * 100) if total else 0.0
                    logger.info(
                        "  下载中 %s: %s / %s (%.1f%%)",
                        local_path.name,
                        format_size(cur),
                        format_size(total) if total else "?",
                        pct,
                    )
                    last_report = now
    finally:
        resp.close()

    return True, downloaded


def download_with_retry(
    session: Any,
    url: str,
    local_path: Path,
    expected_size_mb: float | None,
) -> bool:
    """带重试（指数退避）的下载封装。返回是否最终成功。"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            ok, _ = download_single(session, url, local_path)
            if ok:
                # 完整性软校验：本地大小必须 > 0
                final_size = local_path.stat().st_size if local_path.exists() else 0
                if final_size <= 0:
                    raise RuntimeError("下载后文件大小为 0")
                return True
        except Exception as exc:
            logger.warning("  尝试 %d/%d 失败: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                backoff = INITIAL_BACKOFF * (2 ** (attempt - 1))
                logger.info("  等待 %.1fs 后重试...", backoff)
                time.sleep(backoff)
            else:
                logger.error("  已达最大重试次数，放弃: %s", local_path.name)
                return False
    return False


# ─── 主流程 ──────────────────────────────────────────────────────────────────


def run_download(cfg: DownloadConfig) -> None:
    """执行搜索 + 过滤 + 下载的完整流程。"""
    start, end = cfg.temporal_range()
    logger.info("=" * 60)
    logger.info("SMAP L3 SMAP_E 下载任务")
    logger.info("产品: %s V%s", cfg.short_name, cfg.version)
    logger.info("时间范围: %s ~ %s", start, end)
    logger.info("目标目录: %s", cfg.output_dir)
    logger.info("earthaccess 可用: %s", _HAS_EARTHACCESS)
    logger.info("dry-run: %s, max_files: %s", cfg.dry_run, cfg.max_files)
    logger.info("=" * 60)

    # 1) 认证测试
    if not test_earthdata_auth(cfg.username, cfg.password):
        logger.error("Earthdata 认证失败，终止任务。")
        sys.exit(2)

    # 2) 磁盘空间检查
    ok, free_gb = check_disk_space(cfg.output_dir)
    logger.info("可用磁盘空间: %.2f GB", free_gb)
    if not ok and not cfg.dry_run:
        logger.error("磁盘空间不足（需 >= %.1f GB），终止任务。", MIN_DISK_FREE_GB)
        sys.exit(3)

    # 3) 搜索 granule
    granules = search_granules(cfg)
    if not granules:
        logger.warning("未搜索到任何 granule，任务结束。")
        return

    # 4) 增量过滤：跳过本地已存在文件（按文件名 + 大小判断）
    todo: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for g in granules:
        local_path = cfg.output_dir / g["name"]
        if local_path.exists() and local_path.stat().st_size > 0:
            skipped.append(g)
            logger.info(
                "  跳过已存在: %s (%s)",
                g["name"],
                format_size(local_path.stat().st_size),
            )
        else:
            todo.append(g)

    logger.info(
        "共 %d 个 granule，跳过 %d 个已存在，待下载 %d 个",
        len(granules),
        len(skipped),
        len(todo),
    )

    # 5) 应用 --max-files 限制
    if cfg.max_files is not None and len(todo) > cfg.max_files:
        logger.info("应用 --max-files=%d 限制，截断待下载列表", cfg.max_files)
        todo = todo[: cfg.max_files]

    # 6) dry-run 预览
    if cfg.dry_run:
        logger.info("[dry-run] 将下载以下 %d 个文件:", len(todo))
        for g in todo:
            sz = g.get("size_mb")
            size_hint = f" (~{sz:.1f} MB)" if sz else ""
            logger.info("  - %s%s", g["name"], size_hint)
        logger.info("[dry-run] 预览完成，未实际下载任何文件。")
        return

    # 7) 下载
    session = get_download_session(cfg)
    ok_cnt = 0
    fail_cnt = 0
    total_bytes = 0
    t0 = time.time()

    for i, g in enumerate(todo, 1):
        local_path = cfg.output_dir / g["name"]
        logger.info("[%d/%d] %s", i, len(todo), g["name"])
        success = download_with_retry(
            session, g["url"], local_path, g.get("size_mb")
        )
        if success:
            ok_cnt += 1
            size = local_path.stat().st_size
            total_bytes += size
            logger.info("  完成: %s", format_size(size))
        else:
            fail_cnt += 1
        time.sleep(0.2)

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info(
        "下载完成: 成功 %d, 失败 %d, 跳过(已存在) %d",
        ok_cnt,
        fail_cnt,
        len(skipped),
    )
    logger.info("总下载量: %s, 耗时 %.1fs", format_size(total_bytes), elapsed)
    logger.info("=" * 60)


# ─── 参数解析 ────────────────────────────────────────────────────────────────


def _parse_date(value: str) -> str:
    """校验并返回 YYYY-MM-DD 字符串。"""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"日期格式无效: {value}（应为 YYYY-MM-DD）"
        )


def parse_args(argv: list[str] | None = None) -> DownloadConfig:
    """解析命令行参数，返回 DownloadConfig。"""
    parser = argparse.ArgumentParser(
        description="从 NASA NSIDC 下载 SMAP L3 SMAP_E (SPL3SMP_E) V6 土壤湿度数据",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--date", help="单日下载 (YYYY-MM-DD)")
    parser.add_argument("--start-date", help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="结束日期 (YYYY-MM-DD)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"下载目标目录（默认 {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际下载")
    parser.add_argument(
        "--max-files", type=int, default=None, help="限制单次下载文件数量"
    )
    parser.add_argument(
        "--test-auth", action="store_true", help="仅测试 Earthdata 认证后退出"
    )
    parser.add_argument("--username", default=None, help="Earthdata 用户名（覆盖环境变量）")
    parser.add_argument("--password", default=None, help="Earthdata 密码（覆盖环境变量）")
    args = parser.parse_args(argv)

    # 日期组合校验
    if args.date and (args.start_date or args.end_date):
        parser.error("--date 不能与 --start-date/--end-date 同时使用")
    if args.test_auth:
        cfg_start = cfg_end = cfg_single = None
    elif args.date:
        cfg_single = _parse_date(args.date)
        cfg_start = cfg_end = None
    elif args.start_date and args.end_date:
        s = _parse_date(args.start_date)
        e = _parse_date(args.end_date)
        if s > e:
            parser.error("--start-date 不能晚于 --end-date")
        cfg_start, cfg_end, cfg_single = s, e, None
    elif args.start_date or args.end_date:
        parser.error("--start-date 与 --end-date 必须同时提供")
    else:
        parser.error("必须提供 --date 或 --start-date/--end-date（除非使用 --test-auth）")

    # 凭据：CLI > 环境变量 > 默认值
    username, password = load_credentials()
    if args.username:
        username = args.username
    if args.password:
        password = args.password

    return DownloadConfig(
        start_date=cfg_start,
        end_date=cfg_end,
        single_date=cfg_single,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        max_files=args.max_files,
        username=username,
        password=password,
        test_auth_only=args.test_auth,
    )


def main(argv: list[str] | None = None) -> int:
    """主入口。"""
    cfg = parse_args(argv)
    log_file = setup_logging()
    logger.info("日志文件: %s", log_file)

    if not _HAS_EARTHACCESS:
        logger.warning("未安装 earthaccess，将使用 requests + CMR 回退路径。")
        logger.warning("安装命令: pip install earthaccess")

    if cfg.test_auth_only:
        ok = test_earthdata_auth(cfg.username, cfg.password)
        return 0 if ok else 2

    try:
        run_download(cfg)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("下载任务异常: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
