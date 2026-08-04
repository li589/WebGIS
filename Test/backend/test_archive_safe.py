"""archive_safe：无界面 RAR/ZIP、路径穿越、危险成员与炸弹防护。"""

from __future__ import annotations

import shutil
import struct
import zlib
import zipfile
from pathlib import Path

import pytest

from app.data_io.services.archive_safe import (
    ArchiveSecurityError,
    _find_unrar_tool,
    _probe_console_unrar,
    safe_extract_archive,
    safe_extract_rar,
    safe_extract_zip,
)


def _build_rar3_store(members: dict[str, bytes]) -> bytes:
    """最小 RAR3 store 包（仅测试用，不依赖本机 WinRAR）。"""
    out = bytearray(b"Rar!\x1a\x07\x00")
    main_after = struct.pack("<BHHHI", 0x73, 0x0000, 13, 0, 0)
    out += struct.pack("<H", zlib.crc32(main_after) & 0xFFFF) + main_after
    for name, data in members.items():
        name_b = name.replace("\\", "/").encode("utf-8")
        head_size = 32 + len(name_b)
        after = (
            struct.pack(
                "<BHHIIBIIBBHI",
                0x74,
                0x0000,
                head_size,
                len(data),
                len(data),
                2,
                zlib.crc32(data) & 0xFFFFFFFF,
                0,
                20,
                0x30,
                len(name_b),
                0x20,
            )
            + name_b
        )
        out += struct.pack("<H", zlib.crc32(after) & 0xFFFF) + after + data
    end_after = struct.pack("<BHH", 0x7B, 0x4000, 7)
    out += struct.pack("<H", zlib.crc32(end_after) & 0xFFFF) + end_after
    return bytes(out)


def test_find_console_unrar_not_sfx():
    tool = _find_unrar_tool()
    assert tool, "后端应提供 Code/backend/vendor/unrar/{win-x64,linux-x64} 控制台 UnRAR"
    assert _probe_console_unrar(tool)
    tool_posix = Path(tool).resolve().as_posix().lower()
    assert "winrar" not in Path(tool).name.lower()
    assert "unrarw" not in Path(tool).name.lower()
    assert "tools/unrar" not in tool_posix, "运行时 UnRAR 不得依赖 Tools/"
    assert "vendor/unrar" in tool_posix or shutil.which(Path(tool).name) == tool


def test_reject_sfx_pe_as_rar(tmp_path: Path):
    sfx = tmp_path / "pack.rar"
    sfx.write_bytes(b"MZ" + b"\x00" * 64)
    with pytest.raises(ArchiveSecurityError, match="自解压|SFX|可执行"):
        safe_extract_rar(sfx, tmp_path / "out")


def test_reject_non_rar_magic(tmp_path: Path):
    bad = tmp_path / "pack.rar"
    bad.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    with pytest.raises(ArchiveSecurityError, match="不是有效的 RAR"):
        safe_extract_rar(bad, tmp_path / "out")


def test_safe_extract_rar_shp_sidecar(tmp_path: Path):
    archive = tmp_path / "layer.rar"
    archive.write_bytes(
        _build_rar3_store(
            {
                "layer/a.shp": b"shp-demo",
                "layer/a.dbf": b"dbf-demo",
                "layer/a.shx": b"shx-demo",
            }
        )
    )
    dest = tmp_path / "out"
    files = safe_extract_rar(archive, dest)
    names = {p.name for p in files}
    assert names == {"a.shp", "a.dbf", "a.shx"}
    assert (dest / "layer" / "a.shp").read_bytes() == b"shp-demo"


def test_reject_exe_member_in_rar(tmp_path: Path):
    archive = tmp_path / "evil.rar"
    archive.write_bytes(_build_rar3_store({"payload.exe": b"MZFAKE"}))
    with pytest.raises(ArchiveSecurityError, match="危险成员"):
        safe_extract_rar(archive, tmp_path / "out")


def test_reject_path_traversal_in_rar(tmp_path: Path):
    archive = tmp_path / "trav.rar"
    archive.write_bytes(_build_rar3_store({"../escape.txt": b"pwn"}))
    with pytest.raises(ArchiveSecurityError, match="非法|穿越"):
        safe_extract_rar(archive, tmp_path / "out")


def test_safe_extract_archive_dispatches(tmp_path: Path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("x.geojson", '{"type":"FeatureCollection","features":[]}')
    files = safe_extract_archive(z, tmp_path / "zout")
    assert len(files) == 1

    r = tmp_path / "a.rar"
    r.write_bytes(_build_rar3_store({"y.geojson": b"{}"}) )
    files = safe_extract_archive(r, tmp_path / "rout")
    assert files[0].name == "y.geojson"


def test_reject_zip_exe_member(tmp_path: Path):
    z = tmp_path / "e.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("bin/tool.exe", b"MZ")
    with pytest.raises(ArchiveSecurityError, match="危险成员"):
        safe_extract_zip(z, tmp_path / "out")
