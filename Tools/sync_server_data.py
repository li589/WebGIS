#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从校园网服务器同步数据到本地 I 盘。

本脚本通过 SSH/SFTP 从校园网 HPC 服务器（172.16.98.184，账号 likr6008）把
多源地理数据集增量同步到本地 ``I:\\Geograph_DataSet\\`` 目录。

支持三种 SSH 访问方式：
    1. direct  —— 校园网内直连 ``likr6008@172.16.98.184:22``（使用原始 RSA 私钥）
    2. tunnel  —— Cloudflare 隧道，连接 ``127.0.0.1:2222``（需先启动 cloudflared）
    3. jump    —— 跳板机桥接：经 ``win11-lab``（~/.ssh/config 别名）转发到目标机

主要特性：
    * 服务器数据只读，绝不删除远端文件
    * 增量同步：按相对路径 + 文件大小判断，跳过本地已存在且大小一致的文件
    * 断点续传：本地存在但小于远程的文件自动追加续传
    * 文件过滤：仅下载 .mat / .h5 / .hdf5 / .hdf / .nc / .tif / .txt
    * --dry-run 预览模式、--source 选择数据源、--access 选择访问方式
    * --compare 仅比对本地与远程大小、--test 仅测试连接
    * 进度显示（可选 tqdm）与日志文件记录

用法示例::

    # 默认走 Cloudflare 隧道，同步全部数据源
    python sync_server_data.py

    # 校园网内直连，仅同步 FY-3D
    python sync_server_data.py --access direct --source fy3d

    # 预览将要同步的文件（不实际下载）
    python sync_server_data.py --dry-run

    # 跳板机方式同步多个数据源
    python sync_server_data.py --access jump --source fy3d fy3b ndvi_daily

    # 仅比对本地与远程文件大小差异
    python sync_server_data.py --compare --source gldas_temp

    # 仅测试连接是否通畅
    python sync_server_data.py --access tunnel --test

依赖::

    pip install paramiko
    pip install tqdm        # 可选，用于进度条
"""

from __future__ import annotations

import argparse
import logging
import os
import posixpath
import stat
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

try:
    import paramiko
except ImportError:  # pragma: no cover  —— 仅在实际连接时才报错
    paramiko = None  # type: ignore[assignment]

try:
    from tqdm import tqdm
except ImportError:  # tqdm 为可选依赖
    tqdm = None  # type: ignore[assignment]


def _require_paramiko() -> None:
    """确保 paramiko 已安装；否则给出清晰提示并退出。"""
    if paramiko is None:  # pragma: no cover
        sys.stderr.write("[FATAL] 未安装 paramiko，请执行: pip install paramiko\n")
        raise SystemExit(1)


# ─────────────────────────────── 常量 ───────────────────────────────

# 本地数据根目录
LOCAL_BASE: Path = Path(r"I:\Geograph_DataSet")

# 允许下载的文件扩展名（大小写不敏感）
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".mat", ".h5", ".hdf5", ".hdf", ".nc", ".tif", ".txt"}
)

# SSH 私钥文件
SEAHPC_KEY: Path = Path.home() / ".ssh" / "seahpc_key"
ORIGINAL_KEY: Path = Path(
    r"D:\Workspace\mat2py\tmp\likr6008_10.10.10.254_RsaKeyExpireTime_2026-08-23_20-23-34.txt"
)

# Cloudflare 隧道未就绪时的提示
CLOUDFLARED_HINT: str = (
    "Cloudflare 隧道未就绪。请先在另一个终端启动 cloudflared，例如:\n"
    "    cloudflared access tcp --hostname <你的隧道域名> "
    "--listener 127.0.0.1:2222\n"
    "确认本地 127.0.0.1:2222 可连通后，再运行本脚本。"
)

# 跳板机 ProxyCommand（依赖 ~/.ssh/config 中的 win11-lab 别名）
JUMP_PROXY_COMMAND: str = "ssh -W 172.16.98.184:22 win11-lab"

# 下载分块大小（字节）
CHUNK_SIZE: int = 262144  # 256 KB

# 全局开关：是否禁用进度条（由 --no-progress 设置）
_NO_PROGRESS: bool = False


# ─────────────────────────────── 配置数据类 ───────────────────────────────


@dataclass(frozen=True)
class AccessConfig:
    """SSH 访问方式配置。

    Attributes:
        name: 访问方式标识（direct / tunnel / jump）。
        host: 目标主机。
        port: 目标端口。
        username: 登录用户名。
        key_filename: 本地私钥文件路径。
        description: 人类可读的描述。
        proxy_command: 非空时使用 paramiko.ProxyCommand 作为传输通道（跳板机方式）。
    """

    name: str
    host: str
    port: int
    username: str
    key_filename: Path
    description: str
    proxy_command: str = ""


@dataclass(frozen=True)
class DataSource:
    """单个同步数据源配置。

    Attributes:
        source_id: 数据源短标识（命令行 --source 使用）。
        description: 中文描述。
        remote_path: 服务器端绝对路径（目录）。
        local_subpath: 本地子路径（相对于 ``LOCAL_BASE``）。
    """

    source_id: str
    description: str
    remote_path: str
    local_subpath: str


@dataclass
class SyncStats:
    """单次同步的统计信息。"""

    total_files: int = 0
    skipped: int = 0           # 本地已存在且大小一致
    downloaded: int = 0        # 本次成功下载/续传
    to_download: int = 0       # dry-run 模式下待下载文件数
    failed: int = 0
    downloaded_bytes: int = 0
    to_download_bytes: int = 0
    resumed: int = 0           # 其中断点续传的文件数

    def add(self, other: "SyncStats") -> None:
        """累加另一份统计。"""
        self.total_files += other.total_files
        self.skipped += other.skipped
        self.downloaded += other.downloaded
        self.to_download += other.to_download
        self.failed += other.failed
        self.downloaded_bytes += other.downloaded_bytes
        self.to_download_bytes += other.to_download_bytes
        self.resumed += other.resumed


# ─────────────────────────── 访问方式与数据源表 ───────────────────────────

ACCESS_METHODS: dict[str, AccessConfig] = {
    "direct": AccessConfig(
        name="direct",
        host="172.16.98.184",
        port=22,
        username="likr6008",
        key_filename=ORIGINAL_KEY,
        description="校园网内直连 172.16.98.184:22（使用原始 RSA 私钥）",
    ),
    "tunnel": AccessConfig(
        name="tunnel",
        host="127.0.0.1",
        port=2222,
        username="likr6008",
        key_filename=SEAHPC_KEY,
        description="Cloudflare 隧道 127.0.0.1:2222（需先启动 cloudflared）",
    ),
    "jump": AccessConfig(
        name="jump",
        host="172.16.98.184",
        port=22,
        username="likr6008",
        key_filename=ORIGINAL_KEY,
        description="经 win11-lab 跳板机桥接到 172.16.98.184:22",
        proxy_command=JUMP_PROXY_COMMAND,
    ),
}

DATA_SOURCES: list[DataSource] = [
    DataSource(
        source_id="fy3d",
        description="FY-3D 亮温",
        remote_path="/public/shared_data/Chenhaojun/FY3D_output/matfinalfinal/",
        local_subpath="Soil_Moisture/FY3D/",
    ),
    DataSource(
        source_id="fy3b",
        description="FY-3B 亮温",
        remote_path="/public/shared_data/Chenhaojun/FY3Bmat/",
        local_subpath="Soil_Moisture/FY3B/",
    ),
    DataSource(
        source_id="smap_mat",
        description="SMAP 逐日 MAT",
        remote_path="/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAPdata/MAT/",
        local_subpath="Soil_Moisture/SMAP_Origin_Data/",
    ),
    DataSource(
        source_id="ndvi_daily",
        description="NDVI 逐日",
        remote_path="/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/VNP13C1002/4.Daily/",
        local_subpath="Ecological_Vegetation/NDVI/daily/",
    ),
    DataSource(
        source_id="ndvi_clim",
        description="NDVI 气候态",
        remote_path="/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAP_ancillary/NDVI_clim/",
        local_subpath="Ecological_Vegetation/NDVI/climatology/",
    ),
    DataSource(
        source_id="auxiliary",
        description="辅助数据",
        remote_path="/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAP_ancillary/",
        local_subpath="Soil_Moisture/SMAP_Auxiliary_Data/",
    ),
    DataSource(
        source_id="ddca_sm",
        description="DDCA SM",
        remote_path="/share/home/user03/Chenhaojun/YH/SM/",
        local_subpath="Soil_Moisture/DDCA/SM/",
    ),
    DataSource(
        source_id="gldas_temp",
        description="GLDAS 温度",
        remote_path="/share/home/user03/Chenhaojun/GLDASmat/",
        local_subpath="Meteorological/Weather/GLDAS/",
    ),
    DataSource(
        source_id="h_yearly",
        description="h 年文件",
        remote_path="/share/home/user03/Chenhaojun/YH/H/",
        local_subpath="Soil_Moisture/DDCA/H/",
    ),
]

DATA_SOURCES_BY_ID: dict[str, DataSource] = {s.source_id: s for s in DATA_SOURCES}


# ─────────────────────────────── 工具函数 ───────────────────────────────


def format_size(size_bytes: int) -> str:
    """把字节数格式化为人类可读字符串。"""
    if size_bytes < 0:
        return f"{size_bytes} B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(size_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


def extension_allowed(filename: str) -> bool:
    """判断文件扩展名是否在允许列表内。"""
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def classify_local(local_path: Path, remote_size: int) -> tuple[str, int]:
    """比较本地文件与远程文件大小。

    Returns:
        (状态, 本地大小) 元组。状态取值:
            - ``"equal"``   : 本地不存在差异（大小一致），可跳过
            - ``"missing"`` : 本地不存在，需全新下载
            - ``"partial"`` : 本地小于远程，可断点续传
            - ``"larger"``  : 本地大于远程（异常/已更新），需重新下载
    """
    if not local_path.exists():
        return ("missing", 0)
    local_size = local_path.stat().st_size
    if local_size == remote_size:
        return ("equal", local_size)
    if local_size < remote_size:
        return ("partial", local_size)
    return ("larger", local_size)


class _NoProgress:
    """tqdm 不可用或被禁用时的简易进度回退。"""

    def __init__(self, total: int, desc: str, initial: int = 0) -> None:
        self.total = total
        self.desc = desc
        self.n = initial
        self._last = 0.0

    def update(self, n: int = 1) -> None:
        self.n += n
        now = time.time()
        if now - self._last > 1.0:
            self._last = now
            print(f"    {self.desc}: {format_size(self.n)} / {format_size(self.total)}",
                  flush=True)

    def close(self) -> None:
        pass

    def __enter__(self) -> "_NoProgress":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def make_pbar(total: int, desc: str, *, unit: str = "B",
              initial: int = 0) -> object:
    """创建进度条上下文管理器（优先 tqdm，否则回退到 _NoProgress）。"""
    if tqdm is not None and not _NO_PROGRESS:
        kwargs: dict = dict(
            total=total, initial=initial, desc=desc, unit=unit, leave=False
        )
        if unit == "B":
            kwargs.update(unit_scale=True, unit_divisor=1024)
        return tqdm(**kwargs)
    return _NoProgress(total, desc, initial=initial)


def setup_logging(log_file: Path, verbose: bool) -> logging.Logger:
    """配置并返回 logger，同时输出到控制台与日志文件。"""
    logger = logging.getLogger("sync_server_data")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.info("日志文件: %s", log_file)
    return logger


def default_log_file() -> Path:
    """生成默认日志文件路径（Tools/logs/sync_server_data_<时间戳>.log）。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(__file__).resolve().parent / "logs" / f"sync_server_data_{ts}.log"


# ─────────────────────────────── 同步器 ───────────────────────────────


class ServerDataSynchronizer:
    """服务器到本地的 SFTP 同步器。

    服务器端数据视为只读：本类的所有方法均不会删除或修改远端文件。
    """

    def __init__(
        self,
        access: AccessConfig,
        sources: list[DataSource],
        logger: logging.Logger,
        *,
        dry_run: bool = False,
        compare_only: bool = False,
        test_only: bool = False,
        connect_timeout: int = 20,
    ) -> None:
        self.access = access
        self.sources = sources
        self.log = logger
        self.dry_run = dry_run
        self.compare_only = compare_only
        self.test_only = test_only
        self.connect_timeout = connect_timeout

        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None

    # ── 连接管理 ──────────────────────────────────────────────

    def connect(self) -> None:
        """根据访问方式建立 SSH/SFTP 连接。"""
        _require_paramiko()
        self.log.info("正在连接 [%s] %s", self.access.name, self.access.description)
        self.log.info(
            "目标 %s@%s:%d，密钥: %s",
            self.access.username, self.access.host, self.access.port,
            self.access.key_filename,
        )

        if not self.access.key_filename.exists():
            msg = f"私钥文件不存在: {self.access.key_filename}"
            if self.access.name == "tunnel":
                msg += "\n  (Cloudflare 隧道方式需要 ~/.ssh/seahpc_key)"
            self.log.error(msg)
            raise FileNotFoundError(msg)

        client = paramiko.SSHClient()
        # 已知校园网内网主机，自动接受 host key（与 SyncData.py 行为一致）
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = {
            "hostname": self.access.host,
            "port": self.access.port,
            "username": self.access.username,
            "timeout": self.connect_timeout,
            "key_filename": str(self.access.key_filename),
            "look_for_keys": False,
            "allow_agent": False,
        }

        # 跳板机方式：通过系统 ssh -W 建立 TCP 转发通道
        if self.access.proxy_command:
            self.log.info("使用 ProxyCommand: %s", self.access.proxy_command)
            try:
                connect_kwargs["sock"] = paramiko.ProxyCommand(
                    self.access.proxy_command
                )
            except Exception as exc:
                msg = (
                    f"ProxyCommand 初始化失败: {exc}\n"
                    "请确认 ~/.ssh/config 中已配置 win11-lab 别名且可登录。"
                )
                self.log.error(msg)
                raise

        try:
            client.connect(**connect_kwargs)
        except paramiko.AuthenticationException as exc:
            msg = f"SSH 认证失败: {exc}（请检查私钥 {self.access.key_filename}）"
            self.log.error(msg)
            raise
        except paramiko.SSHException as exc:
            if self.access.name == "tunnel":
                self.log.error("连接失败: %s", exc)
                self.log.error(CLOUDFLARED_HINT)
            else:
                self.log.error("连接失败: %s", exc)
            raise
        except OSError as exc:
            if self.access.name == "tunnel":
                self.log.error("无法连接 127.0.0.1:2222: %s", exc)
                self.log.error(CLOUDFLARED_HINT)
            else:
                self.log.error("网络错误: %s", exc)
            raise

        self.ssh_client = client
        self.sftp = client.open_sftp()
        self.log.info("连接成功。")

    def close(self) -> None:
        """关闭 SFTP 与 SSH 连接。"""
        for obj in (self.sftp, self.ssh_client):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        self.sftp = None
        self.ssh_client = None

    # ── 远程遍历 ──────────────────────────────────────────────

    def walk_remote(self, remote_dir: str) -> Iterator[
        tuple[str, str, paramiko.SFTPAttributes]
    ]:
        """递归遍历远程目录。

        Yields:
            ``(remote_path, rel_path, attr)`` 三元组，仅包含扩展名合规的普通文件。
            ``rel_path`` 相对于 ``remote_dir``。
        """
        if self.sftp is None:
            raise RuntimeError("SFTP 未连接")
        try:
            entries = self.sftp.listdir_attr(remote_dir)
        except IOError as exc:
            self.log.error("无法列出远程目录 %s: %s", remote_dir, exc)
            return

        for entry in entries:
            full = posixpath.join(remote_dir, entry.filename)
            mode = entry.st_mode or 0
            if stat.S_ISDIR(mode):
                yield from self.walk_remote(full)
            elif stat.S_ISREG(mode) and extension_allowed(entry.filename):
                rel = posixpath.relpath(full, remote_dir)
                yield (full, rel, entry)
            # 其余（符号链接、特殊文件、不合规扩展名）跳过

    # ── 文件传输 ──────────────────────────────────────────────

    def download_file(
        self,
        remote_path: str,
        local_path: Path,
        remote_size: int,
        status: str,
        rel: str,
    ) -> bool:
        """下载（或断点续传）单个文件。

        Args:
            remote_path: 远程绝对路径。
            local_path: 本地目标路径。
            remote_size: 远程文件大小。
            status: ``classify_local`` 返回的状态。
            rel: 相对路径，仅用于日志展示。

        Returns:
            下载成功返回 True。
        """
        if self.sftp is None:
            raise RuntimeError("SFTP 未连接")

        # 计算续传偏移
        if status == "partial":
            resume_offset = local_path.stat().st_size
            self.log.info(
                "断点续传: %s  (本地 %s / 远程 %s)",
                rel, format_size(resume_offset), format_size(remote_size),
            )
        else:
            resume_offset = 0
            if status == "larger":
                self.log.warning(
                    "本地大于远程，重新下载: %s  (本地 %s / 远程 %s)",
                    rel, format_size(local_path.stat().st_size),
                    format_size(remote_size),
                )
            else:
                self.log.info("下载: %s  (%s)", rel, format_size(remote_size))

        local_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "ab" if resume_offset > 0 else "wb"
        short_name = rel if len(rel) <= 40 else "..." + rel[-37:]

        try:
            with self.sftp.open(remote_path, "rb") as rfile:
                rfile.seek(resume_offset)
                with open(local_path, mode) as lfile:
                    with make_pbar(
                        remote_size, f"  {short_name}", initial=resume_offset
                    ) as pbar:
                        while True:
                            data = rfile.read(CHUNK_SIZE)
                            if not data:
                                break
                            lfile.write(data)
                            pbar.update(len(data))  # type: ignore[union-attr]
        except Exception as exc:
            self.log.error("下载失败 %s: %s", rel, exc)
            return False

        # 完整性校验
        final_size = local_path.stat().st_size
        if final_size != remote_size:
            self.log.warning(
                "大小不匹配，保留本地文件待下次续传: %s  (本地 %d / 远程 %d)",
                rel, final_size, remote_size,
            )
            return False

        self.log.debug("完成: %s", rel)
        return True

    # ── 单数据源同步 ──────────────────────────────────────────

    def sync_source(self, src: DataSource) -> SyncStats:
        """同步单个数据源。"""
        stats = SyncStats()
        local_root = LOCAL_BASE / src.local_subpath
        self.log.info("=" * 64)
        self.log.info("数据源: %s  (%s)", src.source_id, src.description)
        self.log.info("远程: %s", src.remote_path)
        self.log.info("本地: %s", local_root)

        files = list(self.walk_remote(src.remote_path))
        stats.total_files = len(files)
        self.log.info("发现 %d 个匹配文件", len(files))
        if not files:
            return stats

        with make_pbar(len(files), f"[{src.source_id}]", unit="file") as pbar:
            for remote_path, rel, attr in files:
                local_path = local_root / rel.replace("/", os.sep)
                remote_size = attr.st_size or 0
                status, _local_size = classify_local(local_path, remote_size)

                if status == "equal":
                    stats.skipped += 1
                    self.log.debug("跳过(已完成): %s", rel)
                elif self.dry_run:
                    stats.to_download += 1
                    stats.to_download_bytes += remote_size
                    self.log.info(
                        "[DRY-RUN] 将下载: %s  (%s)  [状态: %s]",
                        rel, format_size(remote_size), status,
                    )
                else:
                    ok = self.download_file(
                        remote_path, local_path, remote_size, status, rel
                    )
                    if ok:
                        stats.downloaded += 1
                        stats.downloaded_bytes += remote_size
                        if status == "partial":
                            stats.resumed += 1
                    else:
                        stats.failed += 1

                pbar.update(1)  # type: ignore[union-attr]

        return stats

    # ── 仅比对大小 ────────────────────────────────────────────

    def compare_source(self, src: DataSource, stats: SyncStats) -> None:
        """仅比对本地与远程文件大小，输出差异报告，不下载。"""
        local_root = LOCAL_BASE / src.local_subpath
        self.log.info("=" * 64)
        self.log.info("比对: %s  (%s)", src.source_id, src.description)
        self.log.info("远程: %s", src.remote_path)
        self.log.info("本地: %s", local_root)

        files = list(self.walk_remote(src.remote_path))
        stats.total_files += len(files)
        self.log.info("发现 %d 个匹配文件", len(files))

        missing = partial = larger = equal = 0
        for remote_path, rel, attr in files:
            local_path = local_root / rel.replace("/", os.sep)
            remote_size = attr.st_size or 0
            status, local_size = classify_local(local_path, remote_size)
            if status == "equal":
                equal += 1
            elif status == "missing":
                missing += 1
                self.log.info("  [缺失] %s  (远程 %s)", rel, format_size(remote_size))
            elif status == "partial":
                partial += 1
                self.log.info(
                    "  [不完整] %s  (本地 %s / 远程 %s)",
                    rel, format_size(local_size), format_size(remote_size),
                )
            else:  # larger
                larger += 1
                self.log.warning(
                    "  [本地偏大] %s  (本地 %s / 远程 %s)",
                    rel, format_size(local_size), format_size(remote_size),
                )

        self.log.info(
            "比对结果: 一致=%d  缺失=%d  不完整=%d  本地偏大=%d",
            equal, missing, partial, larger,
        )
        stats.skipped += equal
        stats.to_download += missing + partial + larger

    # ── 连接测试 ──────────────────────────────────────────────

    def test_connection(self) -> bool:
        """测试连接并校验所选数据源的远程根目录是否可达。"""
        if self.ssh_client is None or self.sftp is None:
            self.log.error("尚未建立连接")
            return False

        try:
            _, stdout, stderr = self.ssh_client.exec_command("whoami && pwd")
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            self.log.info("远程身份: %s", out or "(无输出)")
            if err:
                self.log.debug("远程 stderr: %s", err)
        except Exception as exc:
            self.log.error("执行远程命令失败: %s", exc)
            return False

        ok = True
        for src in self.sources:
            try:
                attr = self.sftp.stat(src.remote_path)
                if stat.S_ISDIR(attr.st_mode or 0):
                    self.log.info("[OK] 数据源 %s 远程目录存在: %s",
                                  src.source_id, src.remote_path)
                else:
                    self.log.warning("[!] %s 不是目录: %s",
                                     src.source_id, src.remote_path)
                    ok = False
            except IOError:
                self.log.error("[X] 数据源 %s 远程目录不存在: %s",
                               src.source_id, src.remote_path)
                ok = False
        return ok

    # ── 主流程 ────────────────────────────────────────────────

    def run(self) -> int:
        """执行同步主流程，返回退出码。"""
        self.connect()

        if self.test_only:
            success = self.test_connection()
            self.log.info("连接测试: %s", "通过" if success else "失败")
            return 0 if success else 1

        overall = SyncStats()
        try:
            for src in self.sources:
                if self.compare_only:
                    self.compare_source(src, overall)
                else:
                    stats = self.sync_source(src)
                    overall.add(stats)
        finally:
            self.close()

        self._report(overall)
        return 0 if overall.failed == 0 else 1

    def _report(self, stats: SyncStats) -> None:
        """输出最终统计摘要。"""
        self.log.info("=" * 64)
        self.log.info("同步完成摘要")
        self.log.info("-" * 64)
        self.log.info("匹配文件总数: %d", stats.total_files)
        self.log.info("跳过(已完成):  %d", stats.skipped)
        self.log.info("成功下载:      %d  (其中断点续传 %d)",
                      stats.downloaded, stats.resumed)
        self.log.info("下载字节量:    %s", format_size(stats.downloaded_bytes))
        if self.dry_run:
            self.log.info("待下载文件:    %d", stats.to_download)
            self.log.info("待下载字节量:  %s", format_size(stats.to_download_bytes))
        self.log.info("失败:          %d", stats.failed)
        self.log.info("=" * 64)
        if self.dry_run:
            self.log.info("（dry-run 模式，未实际下载任何文件）")


# ─────────────────────────────── 命令行 ───────────────────────────────


def list_sources() -> None:
    """打印所有可用数据源。"""
    print(f"共 {len(DATA_SOURCES)} 个数据源，本地根目录: {LOCAL_BASE}")
    print("-" * 72)
    print(f"{'source_id':<14}{'描述':<18}{'本地子路径'}")
    print("-" * 72)
    for s in DATA_SOURCES:
        print(f"{s.source_id:<14}{s.description:<18}{s.local_subpath}")
    print("-" * 72)
    print(f"访问方式: {', '.join(ACCESS_METHODS)}")
    print(f"允许扩展名: {', '.join(sorted(ALLOWED_EXTENSIONS))}")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="sync_server_data.py",
        description="从校园网服务器同步数据到本地 I 盘",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
        "  python sync_server_data.py --access direct --source fy3d\n"
        "  python sync_server_data.py --dry-run --source fy3d fy3b\n"
        "  python sync_server_data.py --compare\n"
        "  python sync_server_data.py --access tunnel --test\n",
    )
    parser.add_argument(
        "--access",
        choices=list(ACCESS_METHODS.keys()),
        default="tunnel",
        help="SSH 访问方式：direct（直连）/ tunnel（Cloudflare 隧道，默认）"
        " / jump（跳板机桥接）",
    )
    parser.add_argument(
        "--source",
        nargs="+",
        metavar="ID",
        help="只同步指定数据源（空格分隔，如 --source fy3d fy3b）；"
        "不指定则同步全部。可用 --list-sources 查看",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式：只列出将要同步的文件，不实际下载",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="仅比对本地与远程文件大小差异，不下载",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="仅测试 SSH/SFTP 连接及远程目录可达性后退出",
    )
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="列出全部数据源后退出",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="日志文件路径（默认 Tools/logs/sync_server_data_<时间戳>.log）",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=20,
        help="SSH 连接超时秒数（默认 20）",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="禁用进度条（适合日志重定向场景）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="输出 DEBUG 级别日志",
    )
    return parser.parse_args(argv)


def resolve_sources(source_ids: Optional[list[str]]) -> list[DataSource]:
    """根据命令行 --source 解析数据源列表，校验合法性。

    Raises:
        ValueError: 当传入未知的数据源标识时。
    """
    if not source_ids:
        return list(DATA_SOURCES)
    unknown = [s for s in source_ids if s not in DATA_SOURCES_BY_ID]
    if unknown:
        raise ValueError(
            f"未知数据源: {unknown}\n"
            f"可用数据源: {list(DATA_SOURCES_BY_ID)}\n"
            f"使用 --list-sources 查看详情。"
        )
    return [DATA_SOURCES_BY_ID[s] for s in source_ids]


def main(argv: Optional[list[str]] = None) -> int:
    """主入口。"""
    global _NO_PROGRESS
    args = parse_args(argv)

    if args.list_sources:
        list_sources()
        return 0

    # 互斥模式校验
    mode_flags = [args.dry_run, args.compare, args.test]
    if sum(bool(f) for f in mode_flags) > 1:
        sys.stderr.write("[ERROR] --dry-run / --compare / --test 不可同时使用\n")
        return 2

    _NO_PROGRESS = args.no_progress

    log_file = args.log_file if args.log_file else default_log_file()
    logger = setup_logging(log_file, args.verbose)

    logger.info("CGDA 服务器数据同步  (访问方式=%s)", args.access)
    logger.info("本地根目录: %s", LOCAL_BASE)

    try:
        sources = resolve_sources(args.source)
    except ValueError as exc:
        logger.error("[ERROR] %s", exc)
        return 2

    selected = ", ".join(s.source_id for s in sources)
    logger.info("待处理数据源(%d): %s", len(sources), selected)

    access = ACCESS_METHODS[args.access]
    _require_paramiko()
    syncer = ServerDataSynchronizer(
        access=access,
        sources=sources,
        logger=logger,
        dry_run=args.dry_run,
        compare_only=args.compare,
        test_only=args.test,
        connect_timeout=args.connect_timeout,
    )

    try:
        return syncer.run()
    except KeyboardInterrupt:
        logger.warning("用户中断，正在关闭连接...")
        syncer.close()
        return 130
    except (FileNotFoundError, paramiko.SSHException, OSError) as exc:
        logger.error("同步终止: %s", exc)
        syncer.close()
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("未预期的错误: %s", exc)
        syncer.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
