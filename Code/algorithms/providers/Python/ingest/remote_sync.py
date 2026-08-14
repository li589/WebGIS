r"""远程数据同步模块。

从 ``Tools/sync_server_data.py`` 提取的核心逻辑，提供可 import 的 SSH/SFTP 和
FileBrowser 数据同步函数，供工作流 ``ssh_sync`` 节点调用。

支持三种服务器类型：
    - ``hpc``  —— SSH/SFTP 直连或 Cloudflare 隧道（paramiko）
    - ``win11`` —— 经 ``~/.ssh/config`` 别名桥接的 SSH/SFTP（paramiko）
    - ``nas``  —— FileBrowser REST API（HTTP，需 User-Agent 头）

用法::

    from ingest.remote_sync import sync_dataset, ServerConfig

    config = ServerConfig.for_hpc_tunnel()
    result = sync_dataset(
        server_config=config,
        remote_path="/public/shared_data/Chenhaojun/FY3D_output/matfinalfinal/",
        local_path=r"I:\Geograph_DataSet\Soil_Moisture\FY3D",
    )

约束：
    - 远程数据只读，绝不删除远端文件
    - 增量同步：按文件大小判断，跳过本地已存在且大小一致的文件
    - 断点续传：本地存在但小于远程的文件自动追加续传
"""

from __future__ import annotations

import json
import logging
import posixpath
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# ─── 常量 ────────────────────────────────────────────────────────────────────

CHUNK_SIZE: int = 262144  # 256 KB
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".mat", ".h5", ".hdf5", ".hdf", ".nc", ".tif", ".txt"}
)
_FILEBROWSER_USER_AGENT: str = "CGDA-RemoteSync/1.0"


# ─── 数据类 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """远程文件条目。"""

    path: str  # 远程绝对路径
    name: str  # 文件名
    size: int  # 字节大小
    is_dir: bool  # 是否目录


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """服务器连接配置。

    对于 ``server_type="hpc"`` 或 ``"win11"``，使用 SSH/SFTP（paramiko）。
    对于 ``server_type="nas"``，使用 FileBrowser REST API。
    """

    server_type: str  # "hpc" | "win11" | "nas"
    host: str
    port: int
    username: str
    password: str = ""
    key_filename: str = ""
    # 私钥 PEM 字符串（远程存储 profile 解析产物；与 key_filename 二选一）
    private_key_pem: str = ""
    # SSH 配置别名（win11 跳板机用）
    ssh_alias: str = ""
    # FileBrowser URL（nas 用）
    filebrowser_url: str = ""
    # 代理命令（跳板机）
    proxy_command: str = ""

    @staticmethod
    def for_hpc_tunnel(
        host: str = "127.0.0.1",
        port: int = 2222,
        username: str = "likr6008",
        key_filename: str = "",
    ) -> ServerConfig:
        """Cloudflare 隧道方式连接 HPC。"""
        key = key_filename or str(Path.home() / ".ssh" / "seahpc_key")
        return ServerConfig(
            server_type="hpc",
            host=host,
            port=port,
            username=username,
            key_filename=key,
        )

    @staticmethod
    def for_hpc_direct(
        host: str = "172.16.98.184",
        port: int = 22,
        username: str = "likr6008",
        key_filename: str = "",
    ) -> ServerConfig:
        """校园网内直连 HPC。"""
        return ServerConfig(
            server_type="hpc",
            host=host,
            port=port,
            username=username,
            key_filename=key_filename,
        )

    @staticmethod
    def for_win11(
        ssh_alias: str = "win11-lab",
        username: str = "qiujianqiu",
    ) -> ServerConfig:
        """经 SSH 配置别名连接 Win11 跳板机。"""
        return ServerConfig(
            server_type="win11",
            host=ssh_alias,
            port=22,
            username=username,
            ssh_alias=ssh_alias,
        )

    @staticmethod
    def for_nas(
        filebrowser_url: str = "https://nasfile.personaltunnel.dpdns.org",
        username: str = "user",
        password: str = "",
    ) -> ServerConfig:
        """FileBrowser API 连接 NAS。"""
        return ServerConfig(
            server_type="nas",
            host=filebrowser_url,
            port=443,
            username=username,
            password=password,
            filebrowser_url=filebrowser_url,
        )


@dataclass
class SyncResult:
    """同步操作结果。"""

    total_files: int = 0
    skipped: int = 0
    downloaded: int = 0
    failed: int = 0
    downloaded_bytes: int = 0
    resumed: int = 0
    local_path: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0

    def add(self, other: SyncResult) -> None:
        self.total_files += other.total_files
        self.skipped += other.skipped
        self.downloaded += other.downloaded
        self.failed += other.failed
        self.downloaded_bytes += other.downloaded_bytes
        self.resumed += other.resumed
        self.errors.extend(other.errors)


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _format_size(size_bytes: int) -> str:
    if size_bytes < 0:
        return f"{size_bytes} B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(size_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


def _extension_allowed(
    filename: str, file_filter: frozenset[str] | None = None
) -> bool:
    exts = file_filter or ALLOWED_EXTENSIONS
    return Path(filename).suffix.lower() in exts


def _classify_local(local_path: Path, remote_size: int) -> tuple[str, int]:
    """比较本地文件与远程文件大小。

    Returns:
        (状态, 本地大小)。状态: "equal" / "missing" / "partial" / "larger"
    """
    if not local_path.exists():
        return ("missing", 0)
    local_size = local_path.stat().st_size
    if local_size == remote_size:
        return ("equal", local_size)
    if local_size < remote_size:
        return ("partial", local_size)
    return ("larger", local_size)


# ─── SFTP 实现 ───────────────────────────────────────────────────────────────


def _get_paramiko() -> Any:
    """延迟导入 paramiko。"""
    try:
        import paramiko

        return paramiko
    except ImportError:
        raise ImportError(
            "paramiko is required for SSH/SFTP sync. Install with: pip install paramiko"
        )


def _load_private_key_pem(pem: str):
    """从 PEM 字符串加载 paramiko PKey（RSA/Ed25519/ECDSA 逐类型尝试）。"""
    import io

    paramiko = _get_paramiko()
    errors: list[Exception] = []
    for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
        try:
            return key_cls.from_private_key(io.StringIO(pem))
        except Exception as exc:  # noqa: BLE001 — 逐类型尝试加载
            errors.append(exc)
    raise ValueError("私钥 PEM 格式不受支持（支持 RSA/Ed25519/ECDSA）") from (
        errors[-1] if errors else None
    )


def _sftp_connect(config: ServerConfig) -> tuple[Any, Any]:
    """建立 SSH/SFTP 连接，返回 (ssh_client, sftp_client)。"""
    paramiko = _get_paramiko()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict[str, Any] = {
        "hostname": config.host,
        "port": config.port,
        "username": config.username,
        "timeout": 20,
        "look_for_keys": True,
        "allow_agent": False,
    }

    if config.key_filename:
        connect_kwargs["key_filename"] = config.key_filename
        connect_kwargs["look_for_keys"] = False
    elif config.private_key_pem:
        connect_kwargs["pkey"] = _load_private_key_pem(config.private_key_pem)
        connect_kwargs["look_for_keys"] = False
    elif config.password:
        connect_kwargs["password"] = config.password
        connect_kwargs["look_for_keys"] = False

    if config.proxy_command:
        connect_kwargs["sock"] = paramiko.ProxyCommand(config.proxy_command)

    client.connect(**connect_kwargs)
    sftp = client.open_sftp()
    logger.info(
        "SSH/SFTP 连接成功: %s@%s:%d", config.username, config.host, config.port
    )
    return client, sftp


def _sftp_list_dir(sftp: Any, path: str) -> list[RemoteFile]:
    """列出远程目录下的文件和子目录。"""
    entries = sftp.listdir_attr(path)
    result: list[RemoteFile] = []
    for entry in entries:
        full = posixpath.join(path, entry.filename)
        mode = entry.st_mode or 0
        is_dir = stat.S_ISDIR(mode)
        size = entry.st_size if not is_dir else 0
        result.append(
            RemoteFile(path=full, name=entry.filename, size=size, is_dir=is_dir)
        )
    return result


def _sftp_walk(
    sftp: Any,
    remote_dir: str,
    file_filter: frozenset[str] | None = None,
) -> Iterator[tuple[str, str, int]]:
    """递归遍历远程目录，yield (remote_path, rel_path, size)。"""
    try:
        entries = sftp.listdir_attr(remote_dir)
    except OSError as exc:
        logger.error("无法列出远程目录 %s: %s", remote_dir, exc)
        return

    for entry in entries:
        full = posixpath.join(remote_dir, entry.filename)
        mode = entry.st_mode or 0
        if stat.S_ISDIR(mode):
            yield from _sftp_walk(sftp, full, file_filter)
        elif stat.S_ISREG(mode) and _extension_allowed(entry.filename, file_filter):
            rel = posixpath.relpath(full, remote_dir)
            yield (full, rel, entry.st_size or 0)


def _sftp_download_file(
    sftp: Any,
    remote_path: str,
    local_path: Path,
    remote_size: int,
    resume_offset: int = 0,
    progress_callback: Callable[[int, int], None] | None = None,
) -> bool:
    """下载（或断点续传）单个 SFTP 文件。

    Args:
        sftp: SFTPClient 实例
        remote_path: 远程绝对路径
        local_path: 本地目标路径
        remote_size: 远程文件大小
        resume_offset: 续传偏移（0=全新下载）
        progress_callback: 回调(downloaded_bytes, total_bytes)

    Returns:
        下载成功返回 True
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "ab" if resume_offset > 0 else "wb"

    try:
        with sftp.open(remote_path, "rb") as rfile:
            rfile.seek(resume_offset)
            with open(local_path, mode) as lfile:
                downloaded = resume_offset
                while True:
                    data = rfile.read(CHUNK_SIZE)
                    if not data:
                        break
                    lfile.write(data)
                    downloaded += len(data)
                    if progress_callback:
                        progress_callback(downloaded, remote_size)
        return True
    except Exception as exc:
        logger.error("下载失败 %s: %s", remote_path, exc)
        return False


# ─── FileBrowser 实现 ────────────────────────────────────────────────────────


def filebrowser_login(
    url: str,
    username: str,
    password: str,
) -> str:
    """登录 FileBrowser，返回 JWT token。

    FileBrowser REST API: POST /api/login
    Cloudflare 隧道要求 User-Agent 头。
    """
    login_url = f"{url.rstrip('/')}/api/login"
    body = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = Request(
        login_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _FILEBROWSER_USER_AGENT,
        },
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        token = resp.read().decode("utf-8").strip().strip('"')
    logger.info("FileBrowser 登录成功: %s", url)
    return token


def _filebrowser_list_dir(
    url: str,
    token: str,
    path: str,
) -> list[RemoteFile]:
    """列出 FileBrowser 目录下的文件和子目录。

    FileBrowser REST API: GET /api/resources/{path}
    使用 isDir 布尔字段判断目录（非 type 字段）。
    根目录返回 {"items": [...]} 字典，子目录返回列表。
    """
    # 安全：对 path 做 URL 编码，防止路径注入和 URL 拼接攻击
    # safe="/" 保留路径分隔符，其余特殊字符编码
    encoded_path = quote(path.lstrip("/"), safe="/")
    api_url = f"{url.rstrip('/')}/api/resources/{encoded_path}"
    req = Request(
        api_url,
        headers={
            "X-Auth": token,
            "User-Agent": _FILEBROWSER_USER_AGENT,
        },
        method="GET",
    )
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    # FileBrowser 根目录返回 dict，子目录返回 list
    items = data.get("items", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []

    result: list[RemoteFile] = []
    for item in items:
        name = item.get("name", "")
        full = posixpath.join(path, name)
        is_dir = item.get("isDir", False)
        size = item.get("size", 0) if not is_dir else 0
        result.append(RemoteFile(path=full, name=name, size=size, is_dir=is_dir))
    return result


def _filebrowser_walk(
    url: str,
    token: str,
    path: str,
    file_filter: frozenset[str] | None = None,
) -> Iterator[tuple[str, str, int]]:
    """递归遍历 FileBrowser 目录，yield (remote_path, rel_path, size)。"""
    items = _filebrowser_list_dir(url, token, path)
    for item in items:
        if item.is_dir:
            yield from _filebrowser_walk(url, token, item.path, file_filter)
        elif _extension_allowed(item.name, file_filter):
            rel = posixpath.relpath(item.path, path)
            yield (item.path, rel, item.size)


def _filebrowser_download(
    url: str,
    token: str,
    remote_path: str,
    local_path: Path,
    remote_size: int,
    resume_offset: int = 0,
    progress_callback: Callable[[int, int], None] | None = None,
) -> bool:
    """下载单个 FileBrowser 文件。

    FileBrowser REST API: GET /api/raw/{path}
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    raw_url = f"{url.rstrip('/')}/api/raw/{remote_path.lstrip('/')}"

    headers = {
        "X-Auth": token,
        "User-Agent": _FILEBROWSER_USER_AGENT,
    }
    if resume_offset > 0:
        headers["Range"] = f"bytes={resume_offset}-"

    req = Request(raw_url, headers=headers, method="GET")

    mode = "ab" if resume_offset > 0 else "wb"
    try:
        with urlopen(req, timeout=300) as resp:
            with open(local_path, mode) as lfile:
                downloaded = resume_offset
                while True:
                    data = resp.read(CHUNK_SIZE)
                    if not data:
                        break
                    lfile.write(data)
                    downloaded += len(data)
                    if progress_callback:
                        progress_callback(downloaded, remote_size)
        return True
    except (HTTPError, URLError) as exc:
        logger.error("FileBrowser 下载失败 %s: %s", remote_path, exc)
        return False


# ─── 统一同步入口 ────────────────────────────────────────────────────────────


def sync_dataset(
    server_config: ServerConfig,
    remote_path: str,
    local_path: str | Path,
    *,
    date_range: tuple[str, str] | None = None,
    file_filter: frozenset[str] | None = None,
    progress_callback: Callable[[int, int, int], None] | None = None,
    dry_run: bool = False,
) -> SyncResult:
    """从远程服务器同步数据到本地。

    根据 ``server_config.server_type`` 自动选择 SFTP 或 FileBrowser 方式。
    增量同步：跳过本地已存在且大小一致的文件；支持断点续传。

    Args:
        server_config: 服务器连接配置
        remote_path: 远程目录路径
        local_path: 本地目标目录
        date_range: 可选日期过滤 (start_yyyymmdd, end_yyyymmdd)，用于按文件名筛选
        file_filter: 文件扩展名过滤集合（默认 .mat/.h5/.hdf5/.hdf/.nc/.tif/.txt）
        progress_callback: 回调(current_file, total_files, downloaded_bytes)
        dry_run: 仅预览不实际下载

    Returns:
        SyncResult 统计信息
    """
    local_path = Path(local_path)
    local_path.mkdir(parents=True, exist_ok=True)
    result = SyncResult(local_path=str(local_path))

    st = server_config.server_type

    if st in ("hpc", "win11"):
        ssh_client, sftp = _sftp_connect(server_config)
        try:
            for rpath, rel, rsize in _sftp_walk(sftp, remote_path, file_filter):
                result.total_files += 1
                _sync_one_file(
                    sftp,
                    rpath,
                    local_path / rel,
                    rsize,
                    result,
                    progress_callback,
                    dry_run,
                    download_func=lambda rp, lp, rs, off, cb: _sftp_download_file(
                        sftp, rp, lp, rs, off, cb
                    ),
                    date_range=date_range,
                    rel=rel,
                )
        finally:
            sftp.close()
            ssh_client.close()

    elif st == "nas":
        token = filebrowser_login(
            server_config.filebrowser_url,
            server_config.username,
            server_config.password,
        )
        for rpath, rel, rsize in _filebrowser_walk(
            server_config.filebrowser_url, token, remote_path, file_filter
        ):
            result.total_files += 1
            _sync_one_file(
                None,
                rpath,
                local_path / rel,
                rsize,
                result,
                progress_callback,
                dry_run,
                download_func=lambda rp, lp, rs, off, cb: _filebrowser_download(
                    server_config.filebrowser_url, token, rp, lp, rs, off, cb
                ),
                date_range=date_range,
                rel=rel,
            )
    else:
        raise ValueError(f"Unknown server_type: {st}")

    logger.info(
        "同步完成: total=%d skipped=%d downloaded=%d failed=%d (%s)",
        result.total_files,
        result.skipped,
        result.downloaded,
        result.failed,
        _format_size(result.downloaded_bytes),
    )
    return result


def _sync_one_file(
    sftp: Any,
    remote_path: str,
    local_path: Path,
    remote_size: int,
    result: SyncResult,
    progress_callback: Callable[[int, int, int], None] | None,
    dry_run: bool,
    download_func: Callable[..., bool],
    date_range: tuple[str, str] | None,
    rel: str,
) -> None:
    """同步单个文件的内部辅助。"""
    # 日期过滤（按文件名中的 YYYYMMDD 筛选）
    if date_range and not _date_matches(rel, date_range):
        return

    status, local_size = _classify_local(local_path, remote_size)

    if status == "equal":
        result.skipped += 1
        logger.debug("跳过（大小一致）: %s", rel)
        return

    if dry_run:
        result.downloaded += 1
        result.downloaded_bytes += remote_size
        logger.info("[DRY-RUN] 待下载: %s (%s)", rel, _format_size(remote_size))
        return

    resume_offset = local_size if status == "partial" else 0
    if status == "partial":
        result.resumed += 1

    def _file_cb(downloaded: int, total: int) -> None:
        if progress_callback:
            progress_callback(result.downloaded + 1, result.total_files, downloaded)

    ok = download_func(remote_path, local_path, remote_size, resume_offset, _file_cb)
    if ok:
        result.downloaded += 1
        result.downloaded_bytes += remote_size
    else:
        result.failed += 1
        result.errors.append(remote_path)


def _date_matches(filename: str, date_range: tuple[str, str]) -> bool:
    """检查文件名中是否包含 date_range 范围内的日期（YYYYMMDD）。"""
    import re

    start, end = date_range
    # 提取文件名中所有 8 位数字（潜在日期）
    dates = re.findall(r"(20\d{6})", filename)
    for d in dates:
        if start <= d <= end:
            return True
    # 如果文件名中没有日期，保留文件
    return len(dates) == 0
