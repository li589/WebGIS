"""安全解压：路径穿越、zip/rar/tar/gz/7z bomb、符号链接、可执行载荷与 GUI/SFX 工具隔离。

RAR 仅允许无界面控制台 UnRAR：
`Code/backend/vendor/unrar/{win-x64,linux-x64}` 或系统 PATH 的 `unrar`。
禁止调用 WinRAR GUI / 自解压安装包；不把运行时依赖放在仓库根 `Tools/`。
解压全程不依赖本机 WinRAR；不执行用户上传的 SFX。
7z 依赖 7-Zip CLI（`7z`/`7za`，PATH 或常见安装位置），无 GUI。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 解压安全上限（与业务配额独立，专防炸弹）
MAX_ARCHIVE_MEMBERS = 5_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
MAX_SINGLE_MEMBER_BYTES = 512 * 1024 * 1024  # 512 MiB
# 压缩比：未压缩声明大小 / 压缩后大小；过高视为炸弹
MAX_COMPRESSION_RATIO = 100.0
MIN_COMPRESSED_FOR_RATIO = 10 * 1024  # 过小文件不做比率判断

# 解压后拒绝的危险扩展名（防投放恶意代码）
_DENIED_MEMBER_SUFFIXES = frozenset(
    {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bat",
        ".cmd",
        ".com",
        ".msi",
        ".msp",
        ".scr",
        ".ps1",
        ".psm1",
        ".vbs",
        ".vbe",
        ".js",
        ".jse",
        ".wsf",
        ".wsh",
        ".sh",
        ".bash",
        ".zsh",
        ".csh",
        ".jar",
        ".apk",
        ".dmg",
        ".app",
        ".hta",
        ".cpl",
        ".sys",
        ".drv",
        ".efi",
    }
)

_RAR4_MAGIC = b"Rar!\x1a\x07\x00"
_RAR5_MAGIC = b"Rar!\x1a\x07\x01"
_MZ_MAGIC = b"MZ"

_UNRAR_PROBE_TIMEOUT_SEC = 4.0
_UNRAR_EXTRACT_TIMEOUT_SEC = 600.0

# unrar v 输出中“数字尺寸”行（Size Packed ...）
_UNRAR_SIZE_LINE = re.compile(
    r"^\s*(\d+)\s+(\d+)\s+(\d+%|<--|->)\s+",
)


class ArchiveSecurityError(ValueError):
    """压缩包未通过安全校验。"""


def _sanitize_member_name(name: str) -> str:
    """规范化成员路径，拒绝绝对路径、盘符与 .. 穿越。"""
    raw = (name or "").replace("\\", "/").strip()
    if not raw or raw.endswith("/"):
        return ""
    while raw.startswith("./"):
        raw = raw[2:]
    if raw.startswith("/") or raw.startswith("../") or "/../" in f"/{raw}/":
        raise ArchiveSecurityError(f"非法压缩包路径: {name}")
    if len(raw) >= 2 and raw[1] == ":":
        raise ArchiveSecurityError(f"非法压缩包路径: {name}")
    if raw.startswith("//") or ".." in Path(raw).parts:
        raise ArchiveSecurityError(f"非法压缩包路径: {name}")
    return raw


def _reject_dangerous_member(safe_name: str) -> None:
    suffix = Path(safe_name).suffix.lower()
    if suffix in _DENIED_MEMBER_SUFFIXES:
        raise ArchiveSecurityError(
            f"拒绝危险成员（可执行/脚本）: {safe_name}。"
            "请仅打包矢量/栅格数据（如 shp/dbf/geojson/tif），勿包含程序文件。"
        )
    lower = safe_name.lower().replace("\\", "/")
    for bad in _DENIED_MEMBER_SUFFIXES:
        if lower.endswith(bad):
            raise ArchiveSecurityError(f"拒绝危险成员: {safe_name}")


def _is_symlink_zipinfo(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return (mode & 0o170000) == 0o120000


def _check_ratio(archive_size: int, declared_total: int) -> None:
    if (
        archive_size >= MIN_COMPRESSED_FOR_RATIO
        and declared_total / archive_size > MAX_COMPRESSION_RATIO
    ):
        raise ArchiveSecurityError(
            f"压缩比异常（疑似压缩炸弹，比率 > {MAX_COMPRESSION_RATIO:g}），已拒绝"
        )


def _assert_under_dest(path: Path, dest: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(dest.resolve())
    except ValueError as exc:
        raise ArchiveSecurityError(f"路径穿越: {path}") from exc
    return resolved


def safe_extract_zip(archive: Path, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total_uncompressed = 0
    archive_size = max(1, archive.stat().st_size)

    with zipfile.ZipFile(archive, "r") as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            raise ArchiveSecurityError(
                f"压缩包成员过多（{len(infos)} > {MAX_ARCHIVE_MEMBERS}），已拒绝"
            )

        declared_total = 0
        for info in infos:
            if info.is_dir():
                continue
            if _is_symlink_zipinfo(info):
                raise ArchiveSecurityError(f"拒绝符号链接成员: {info.filename}")
            size = int(info.file_size or 0)
            if size < 0:
                raise ArchiveSecurityError(f"非法成员大小: {info.filename}")
            if size > MAX_SINGLE_MEMBER_BYTES:
                raise ArchiveSecurityError(
                    f"单文件过大（>{MAX_SINGLE_MEMBER_BYTES // (1024 * 1024)} MiB）: {info.filename}"
                )
            safe_name = _sanitize_member_name(info.filename)
            if safe_name:
                _reject_dangerous_member(safe_name)
            declared_total += size

        if declared_total > MAX_UNCOMPRESSED_BYTES:
            raise ArchiveSecurityError(
                f"解压后体积过大（>{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MiB），已拒绝"
            )
        _check_ratio(archive_size, declared_total)

        for info in infos:
            if info.is_dir():
                continue
            safe_name = _sanitize_member_name(info.filename)
            if not safe_name:
                continue
            target = _assert_under_dest(dest / safe_name, dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with zf.open(info, "r") as src, target.open("wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    total_uncompressed += len(chunk)
                    if written > MAX_SINGLE_MEMBER_BYTES:
                        raise ArchiveSecurityError(f"单文件解压超限: {info.filename}")
                    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                        raise ArchiveSecurityError("累计解压体积超限，已中止")
                    out.write(chunk)
            extracted.append(target)

    return extracted


def _backend_root() -> Path:
    # Code/backend/app/data_io/services/archive_safe.py → Code/backend
    return Path(__file__).resolve().parents[3]


def _subprocess_no_window_kwargs() -> dict:
    """Windows 下禁止弹出控制台/GUI 窗口（绝不允许 WinRAR 安装器界面）。"""
    if sys.platform != "win32":
        return {}
    kwargs: dict = {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
    }
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startupinfo
    except Exception:
        pass
    return kwargs


def _probe_console_unrar(tool: str) -> bool:
    """确认 tool 是无界面 UnRAR CLI（拒绝 WinRAR GUI / SFX 安装包）。"""
    path = Path(tool)
    if not path.is_file():
        return False
    name = path.name.lower()
    if name in {"winrar.exe", "rar.exe", "winrar", "unrarw64.exe", "unrarw.exe"}:
        return False
    # 文件名像自解压安装包
    if "unrarw" in name or name.endswith("sfx.exe"):
        return False
    try:
        proc = subprocess.run(
            [tool],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_UNRAR_PROBE_TIMEOUT_SEC,
            check=False,
            **_subprocess_no_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = f"{proc.stdout or ''}{proc.stderr or ''}"
    if "UNRAR" not in text.upper():
        return False
    if "Usage:" not in text and "usage:" not in text.lower():
        if "Roshal" not in text and "freeware" not in text.lower():
            return False
    # SFX 安装器常带 Setup / Install 字样
    lowered = text.lower()
    if "setup" in lowered and "extracting" in lowered and "usage:" not in lowered:
        return False
    return True


def _find_unrar_tool() -> str | None:
    """优先 backend/vendor 控制台 UnRAR，其次系统 PATH（须通过探测）。"""
    vendor = _backend_root() / "vendor" / "unrar"
    candidates: list[str | None] = []
    if sys.platform == "win32":
        candidates.extend(
            [
                str(vendor / "win-x64" / "UnRAR.exe"),
                str(vendor / "win-x64" / "unrar.exe"),
            ]
        )
    else:
        candidates.extend(
            [
                str(vendor / "linux-x64" / "unrar"),
                str(vendor / "unrar"),
            ]
        )
    for which_name in ("unrar", "UnRAR"):
        candidates.append(shutil.which(which_name))

    seen: set[str] = set()
    for cand in candidates:
        if not cand:
            continue
        key = os.path.normcase(os.path.abspath(cand))
        if key in seen:
            continue
        seen.add(key)
        if not os.path.isfile(cand):
            continue
        if _probe_console_unrar(cand):
            return cand
    return None


def _validate_rar_magic(archive: Path) -> None:
    """拒绝 SFX/PE 与非 RAR 载荷；仅接受标准 RAR4/RAR5 文件头。"""
    try:
        with archive.open("rb") as fh:
            head = fh.read(16)
    except OSError as exc:
        raise ValueError(f"无法读取压缩包: {exc}") from exc
    if head.startswith(_MZ_MAGIC):
        raise ArchiveSecurityError(
            "拒绝 RAR 自解压程序（SFX/.exe）。"
            "服务端不会执行或弹出解压界面；请用普通 .rar（非自解压）或 .zip 重新打包后上传。"
        )
    if head.startswith(_RAR4_MAGIC) or head.startswith(_RAR5_MAGIC):
        return
    raise ArchiveSecurityError(
        "不是有效的 RAR 文件（缺少标准 RAR 文件头）。"
        "请确认扩展名与内容一致，或改为 ZIP。勿上传自解压 .exe。"
    )


def _run_unrar(
    tool: str, args: list[str], *, timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [tool, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        **_subprocess_no_window_kwargs(),
    )


def _collect_extracted_files(dest: Path) -> list[Path]:
    extracted: list[Path] = []
    total = 0
    for path in sorted(dest.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ArchiveSecurityError(f"拒绝符号链接: {path.name}")
        _assert_under_dest(path, dest)
        rel = path.relative_to(dest.resolve()).as_posix()
        _reject_dangerous_member(rel)
        size = path.stat().st_size
        total += size
        if size > MAX_SINGLE_MEMBER_BYTES or total > MAX_UNCOMPRESSED_BYTES:
            raise ArchiveSecurityError("解压体积超限，已中止")
        if len(extracted) >= MAX_ARCHIVE_MEMBERS:
            raise ArchiveSecurityError("压缩包成员过多，已拒绝")
        extracted.append(path)
    return extracted


def _parse_declared_total_from_unrar_v(stdout: str) -> int | None:
    """从 `unrar v` 输出解析声明的未压缩总大小；失败返回 None。"""
    total = 0
    found = 0
    for line in (stdout or "").splitlines():
        m = _UNRAR_SIZE_LINE.match(line)
        if not m:
            continue
        try:
            size = int(m.group(1))
        except ValueError:
            continue
        total += size
        found += 1
    return total if found else None


def _precheck_rar_members(tool: str, archive: Path) -> None:
    """列目录 + 体积/炸弹预检；全程无界面，-p- 禁止密码交互。"""
    # 注意：勿对 lb/v 使用 -idq，否则会吞掉文件名/尺寸输出
    listed = _run_unrar(
        tool,
        ["lb", "-p-", str(archive)],
        timeout=_UNRAR_PROBE_TIMEOUT_SEC * 3,
    )
    combined = f"{listed.stdout or ''}{listed.stderr or ''}"
    if listed.returncode != 0:
        detail = combined.strip()[:300]
        low = detail.lower()
        if "password" in low or "encrypted" in low or "crypt" in low:
            raise ArchiveSecurityError("拒绝加密 RAR（服务端不接受密码包）")
        raise ValueError(f"UnRAR 无法列出压缩包内容: {detail or listed.returncode}")

    names = [ln.strip() for ln in (listed.stdout or "").splitlines() if ln.strip()]
    if len(names) > MAX_ARCHIVE_MEMBERS:
        raise ArchiveSecurityError(
            f"压缩包成员过多（{len(names)} > {MAX_ARCHIVE_MEMBERS}），已拒绝"
        )
    if not names:
        raise ValueError("RAR 内无文件")

    for name in names:
        safe_name = _sanitize_member_name(name)
        if safe_name:
            _reject_dangerous_member(safe_name)

    verbose = _run_unrar(
        tool,
        ["v", "-c-", "-p-", str(archive)],
        timeout=_UNRAR_PROBE_TIMEOUT_SEC * 3,
    )
    vtext = f"{verbose.stdout or ''}{verbose.stderr or ''}"
    if "encrypted" in vtext.lower() or "password" in vtext.lower():
        # 部分版本在成功列出时仍提示加密头
        if verbose.returncode != 0:
            raise ArchiveSecurityError("拒绝加密 RAR（服务端不接受密码包）")

    declared = _parse_declared_total_from_unrar_v(verbose.stdout or "")
    if declared is not None:
        if declared > MAX_UNCOMPRESSED_BYTES:
            raise ArchiveSecurityError("解压后体积过大，已拒绝")
        archive_size = max(1, archive.stat().st_size)
        # 单文件上限粗检：若仅一个成员且超限
        if len(names) == 1 and declared > MAX_SINGLE_MEMBER_BYTES:
            raise ArchiveSecurityError(f"单文件过大: {names[0]}")
        _check_ratio(archive_size, declared)


def _extract_rar_with_unrar_cli(archive: Path, dest: Path, tool: str) -> list[Path]:
    """用控制台 UnRAR 解压到 dest（先 lb/v 做安全预检）。"""
    dest.mkdir(parents=True, exist_ok=True)
    _precheck_rar_members(tool, archive)

    out_dir = str(dest.resolve())
    if not out_dir.endswith(("\\", "/")):
        out_dir = out_dir + os.sep
    # -p-：无密码且禁止交互；失败即拒（加密包）
    proc = _run_unrar(
        tool,
        ["x", "-y", "-o+", "-p-", "-idq", str(archive), out_dir],
        timeout=_UNRAR_EXTRACT_TIMEOUT_SEC,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:400]
        low = detail.lower()
        if "password" in low or "encrypted" in low:
            raise ArchiveSecurityError("拒绝加密 RAR（服务端不接受密码包）")
        raise ValueError(f"UnRAR 解压失败（code={proc.returncode}）: {detail}")

    extracted = _collect_extracted_files(dest)
    if not extracted:
        raise ValueError("RAR 解压结果为空")
    return extracted


def _find_7z() -> str | None:
    """仅查找 7z CLI（非 GUI）。探测顺序：vendor → PATH → 平台常见安装位置。

    Windows vendor: ``Code/backend/vendor/7zip/win-x64/7z.exe``（与 vendor/unrar 对称）。
    Linux: ``apt install p7zip-full``（/usr/bin/7z）或 p7zip（7za）。
    """
    vendor = _backend_root() / "vendor" / "7zip"
    candidates: list[str | None] = []
    if sys.platform == "win32":
        candidates.extend(
            [
                str(vendor / "win-x64" / "7z.exe"),
                r"C:\Program Files\7-Zip\7z.exe",
                r"C:\Program Files (x86)\7-Zip\7z.exe",
            ]
        )
    else:
        candidates.extend(
            [
                str(vendor / "linux-x64" / "7z"),
                "/usr/bin/7z",
                "/usr/bin/7za",
                "/usr/local/bin/7z",
                "/usr/local/bin/7za",
            ]
        )
    candidates.extend([shutil.which("7z"), shutil.which("7za")])
    for cand in candidates:
        if not cand or not os.path.isfile(cand):
            continue
        name = Path(cand).name.lower()
        if name in {"7zfm.exe", "7zg.exe"}:
            continue
        return cand
    return None


def _extract_via_7z(archive: Path, dest: Path, *, fmt_label: str) -> list[Path]:
    """7-Zip CLI 提取（RAR 回退与 .7z 主路径共用；无界面）。先 list 再解压。"""
    seven = _find_7z()
    if not seven:
        raise ValueError("未找到 7-Zip CLI")
    dest.mkdir(parents=True, exist_ok=True)

    listed = subprocess.run(
        [seven, "l", "-slt", str(archive)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_UNRAR_PROBE_TIMEOUT_SEC * 3,
        check=False,
        **_subprocess_no_window_kwargs(),
    )
    if listed.returncode != 0:
        detail = (listed.stderr or listed.stdout or "").strip()[:300]
        raise ValueError(f"7-Zip 无法列出 {fmt_label}: {detail or listed.returncode}")

    names: list[str] = []
    declared_total = 0
    current_path: str | None = None
    current_size = 0
    current_folder = False
    archive_name = archive.name

    def _flush_7z_entry() -> None:
        nonlocal current_path, current_size, current_folder, declared_total
        if current_path and current_path != archive_name and not current_folder:
            names.append(current_path)
            declared_total += current_size
        current_path = None
        current_size = 0
        current_folder = False

    for line in (listed.stdout or "").splitlines():
        if line.startswith("Path = "):
            _flush_7z_entry()
            current_path = line[7:].strip()
        elif line.startswith("Size = "):
            try:
                current_size = int(line[7:].strip() or "0")
            except ValueError:
                current_size = 0
        elif line.startswith("Folder = "):
            current_folder = line[9:].strip() in {"+", "true", "True", "1"}
    _flush_7z_entry()

    for name in names:
        safe_name = _sanitize_member_name(name)
        if safe_name:
            _reject_dangerous_member(safe_name)
    if names:
        if len(names) > MAX_ARCHIVE_MEMBERS:
            raise ArchiveSecurityError("压缩包成员过多，已拒绝")
        if declared_total > MAX_UNCOMPRESSED_BYTES:
            raise ArchiveSecurityError("解压后体积过大，已拒绝")
        _check_ratio(max(1, archive.stat().st_size), declared_total)

    proc = subprocess.run(
        [seven, "x", "-y", "-p-", f"-o{dest}", str(archive)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_UNRAR_EXTRACT_TIMEOUT_SEC,
        check=False,
        **_subprocess_no_window_kwargs(),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:400]
        raise ValueError(
            f"7-Zip 解压 {fmt_label} 失败（code={proc.returncode}）: {detail}"
        )
    extracted = _collect_extracted_files(dest)
    if not extracted:
        raise ValueError(f"{fmt_label} 解压结果为空")
    return extracted


def safe_extract_7z(archive: Path, dest: Path) -> list[Path]:
    return _extract_via_7z(archive, dest, fmt_label="7z")


def safe_extract_rar(archive: Path, dest: Path) -> list[Path]:
    _validate_rar_magic(archive)
    dest.mkdir(parents=True, exist_ok=True)

    tool = _find_unrar_tool()
    errors: list[str] = []
    if tool:
        logger.info("RAR extract using console UnRAR: %s", tool)
        try:
            return _extract_rar_with_unrar_cli(archive, dest, tool)
        except ArchiveSecurityError:
            raise
        except Exception as exc:
            errors.append(f"UnRAR({tool}): {exc}")
    else:
        errors.append(
            "未找到可用的控制台 UnRAR（请使用 Code/backend/vendor/unrar/win-x64 或 linux-x64，"
            "或在 Linux 安装: apt install unrar）。禁止使用 WinRAR GUI / unrarw64 安装包。"
        )

    try:
        return _extract_via_7z(archive, dest, fmt_label="RAR")
    except ArchiveSecurityError:
        raise
    except Exception as exc:
        errors.append(f"7z: {exc}")

    raise ValueError(
        "无法在服务端无界面解压 RAR（"
        + "；".join(errors)
        + "）。请改为 ZIP，或确保服务器具备控制台 unrar"
        "（本仓库：Code/backend/vendor/unrar；Linux 生产可用 apt install unrar）。"
        "不会调用 WinRAR 图形界面。"
    )


def safe_extract_tar(archive: Path, dest: Path) -> list[Path]:
    """tar / tar.gz / tgz / tar.bz2 / tar.xz（tarfile ``r:*`` 透明解压压缩层）。"""
    import tarfile

    dest.mkdir(parents=True, exist_ok=True)
    archive_size = max(1, archive.stat().st_size)
    extracted: list[Path] = []
    total_uncompressed = 0

    with tarfile.open(archive, "r:*") as tf:
        members = tf.getmembers()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ArchiveSecurityError(
                f"压缩包成员过多（{len(members)} > {MAX_ARCHIVE_MEMBERS}），已拒绝"
            )

        declared_total = 0
        for member in members:
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                raise ArchiveSecurityError(f"拒绝链接成员: {member.name}")
            if not member.isfile():
                raise ArchiveSecurityError(f"拒绝非常规文件成员: {member.name}")
            if member.size > MAX_SINGLE_MEMBER_BYTES:
                raise ArchiveSecurityError(
                    f"单文件过大（>{MAX_SINGLE_MEMBER_BYTES // (1024 * 1024)} MiB）"
                    f": {member.name}"
                )
            safe_name = _sanitize_member_name(member.name)
            if safe_name:
                _reject_dangerous_member(safe_name)
            declared_total += member.size

        if declared_total > MAX_UNCOMPRESSED_BYTES:
            raise ArchiveSecurityError(
                f"解压后体积过大（>{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MiB），已拒绝"
            )
        _check_ratio(archive_size, declared_total)

        for member in members:
            if not member.isfile():
                continue
            safe_name = _sanitize_member_name(member.name)
            if not safe_name:
                continue
            target = _assert_under_dest(dest / safe_name, dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tf.extractfile(member)
            if source is None:
                continue
            written = 0
            with source, target.open("wb") as out:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    total_uncompressed += len(chunk)
                    if written > MAX_SINGLE_MEMBER_BYTES:
                        raise ArchiveSecurityError(f"单文件解压超限: {member.name}")
                    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                        raise ArchiveSecurityError("累计解压体积超限，已中止")
                    out.write(chunk)
            extracted.append(target)

    return extracted


def safe_extract_gzip(archive: Path, dest: Path) -> list[Path]:
    """纯 gzip 单文件（非 tar.gz）。解压为去掉 .gz 后缀的文件，流式限额。"""
    import gzip

    dest.mkdir(parents=True, exist_ok=True)
    out_name = (
        archive.name[: -len(".gz")]
        if archive.name.lower().endswith(".gz")
        else f"{archive.name}.out"
    )
    if not out_name.strip():
        out_name = "extracted.bin"
    _reject_dangerous_member(out_name)

    target = _assert_under_dest(dest / _sanitize_member_name(out_name), dest)
    written = 0
    with gzip.open(archive, "rb") as src, target.open("wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_SINGLE_MEMBER_BYTES:
                raise ArchiveSecurityError(f"单文件解压超限: {out_name}")
            out.write(chunk)
    if written == 0:
        target.unlink(missing_ok=True)
        raise ValueError("gzip 内容为空")
    return [target]


def safe_extract_archive(archive: Path, dest: Path) -> list[Path]:
    name_lower = archive.name.lower()
    suffix = archive.suffix.lower()
    if suffix == ".zip":
        return safe_extract_zip(archive, dest)
    if suffix == ".rar":
        return safe_extract_rar(archive, dest)
    if suffix == ".7z":
        return safe_extract_7z(archive, dest)
    if name_lower.endswith(
        (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
    ):
        return safe_extract_tar(archive, dest)
    if suffix == ".gz":
        return safe_extract_gzip(archive, dest)
    if suffix in {".exe", ".sfx"}:
        raise ArchiveSecurityError(
            "拒绝自解压/可执行包。请上传标准 .zip 或 .rar（非 SFX）。"
        )
    raise ValueError(f"不支持的压缩格式: {suffix}")
