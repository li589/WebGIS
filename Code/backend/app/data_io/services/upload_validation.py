"""上传文件名 / 魔数校验：拒绝可执行与伪装载荷。"""

from __future__ import annotations

from pathlib import Path

# 允许的导入扩展名（小写，无点）
ALLOWED_EXTENSIONS = frozenset(
    {
        # vector
        "shp",
        "dbf",
        "shx",
        "prj",
        "cpg",
        "sbn",
        "sbx",
        "qix",
        "zip",
        "rar",
        "geojson",
        "json",
        # raster
        "tif",
        "tiff",
        "nc",
        "hdf",
        "h5",
        "he5",
        "mat",
        # document
        "csv",
        "xlsx",
        "xls",
        "txt",
    }
)

# 明确拒绝的可执行 / 脚本扩展（即使魔数匹配也不收）
DENIED_EXTENSIONS = frozenset(
    {
        "exe",
        "dll",
        "so",
        "dylib",
        "bat",
        "cmd",
        "ps1",
        "sh",
        "bash",
        "py",
        "pyc",
        "pyo",
        "js",
        "mjs",
        "cjs",
        "vbs",
        "wsf",
        "jar",
        "war",
        "class",
        "com",
        "msi",
        "scr",
        "php",
        "asp",
        "aspx",
        "cgi",
        "pl",
        "rb",
        "wasm",
    }
)

# 魔数嗅探（前缀）
_MAGIC_PREFIXES: list[tuple[bytes, frozenset[str]]] = [
    (b"PK\x03\x04", frozenset({"zip", "xlsx", "shp"})),  # zip 容器；xlsx 也是 zip
    (b"PK\x05\x06", frozenset({"zip", "xlsx"})),
    (b"PK\x07\x08", frozenset({"zip"})),
    (b"Rar!\x1a\x07", frozenset({"rar"})),
    (b"II*\x00", frozenset({"tif", "tiff"})),
    (b"MM\x00*", frozenset({"tif", "tiff"})),
    # BigTIFF（大栅格常见，如全球/区域 EASE Grid 产品）
    (b"II+\x00", frozenset({"tif", "tiff"})),
    (b"MM\x00+", frozenset({"tif", "tiff"})),
    (b"\x89HDF\r\n\x1a\n", frozenset({"hdf", "h5", "he5"})),
    (b"\x89HDF", frozenset({"hdf", "h5", "he5"})),
    (b"CDF\x01", frozenset({"nc"})),
    (b"CDF\x02", frozenset({"nc"})),
    (b"\x0e\x03\x13\x01", frozenset({"mat"})),  # MATLAB Level 5 常见头
]


class UploadValidationError(ValueError):
    """上传未通过校验。"""


def sanitize_filename(filename: str) -> str:
    name = Path(filename or "").name.strip()
    if not name or name in {".", ".."}:
        raise UploadValidationError("文件名无效")
    if any(ch in name for ch in ("\x00", "/", "\\")):
        raise UploadValidationError("文件名含非法字符")
    return name


def extension_of(filename: str) -> str:
    parts = filename.lower().rsplit(".", 1)
    return parts[1] if len(parts) == 2 else ""


def validate_upload_filename(filename: str) -> str:
    safe = sanitize_filename(filename)
    ext = extension_of(safe)
    if not ext:
        raise UploadValidationError("缺少文件扩展名")
    if ext in DENIED_EXTENSIONS:
        raise UploadValidationError(f"拒绝可执行/脚本类型: .{ext}")
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(f"不支持的文件类型: .{ext}")
    return safe


def sniff_magic(path: Path, *, declared_ext: str | None = None) -> None:
    """对常见二进制格式做魔数校验；文本/geojson 等跳过。"""
    ext = (declared_ext or extension_of(path.name)).lower()
    # 文本类与 sidecar 不做魔数强制
    if ext in {
        "geojson",
        "json",
        "csv",
        "txt",
        "prj",
        "cpg",
        "dbf",
        "shx",
        "shp",
        "sbn",
        "sbx",
        "qix",
        "xls",
    }:
        return
    if not path.exists() or path.stat().st_size == 0:
        raise UploadValidationError("上传文件为空")

    head = path.read_bytes()[:64]
    # 可执行伪装
    if head.startswith(b"MZ") or head.startswith(b"\x7fELF"):
        raise UploadValidationError("检测到可执行文件内容，已拒绝")
    if head.startswith(b"#!"):
        raise UploadValidationError("检测到脚本 shebang，已拒绝")

    if ext in {"zip", "xlsx", "rar", "tif", "tiff", "nc", "hdf", "h5", "he5", "mat"}:
        matched = False
        for magic, exts in _MAGIC_PREFIXES:
            if head.startswith(magic) and ext in exts:
                matched = True
                break
        # xlsx 是 zip；mat 头多样，放宽
        if ext == "xlsx" and head.startswith(b"PK"):
            matched = True
        if ext == "mat":
            # Level 4/5 头不统一，仅拒绝明显可执行
            matched = True
        if not matched:
            raise UploadValidationError(f"文件内容与扩展名 .{ext} 不匹配")
