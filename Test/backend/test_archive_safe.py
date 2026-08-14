"""archive_safe：无界面 RAR/ZIP/TAR/GZ/7Z、路径穿越、危险成员与炸弹防护。"""

from __future__ import annotations

import gzip
import shutil
import struct
import tarfile
import zlib
import zipfile
from pathlib import Path

import pytest

from app.data_io.services.archive_safe import (
    ArchiveSecurityError,
    _find_7z,
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


# ─── TAR 族（tar / tar.gz / tgz / tar.bz2 / tar.xz） ────────────────────────


def _build_tar(path: Path, members: dict[str, bytes], *, mode: str = "w") -> None:
    with tarfile.open(path, mode) as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            import io

            tf.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize(
    ("filename", "mode"),
    [
        ("pack.tar", "w"),
        ("pack.tar.gz", "w:gz"),
        ("pack.tgz", "w:gz"),
        ("pack.tar.bz2", "w:bz2"),
        ("pack.tar.xz", "w:xz"),
    ],
)
def test_safe_extract_tar_family(tmp_path: Path, filename: str, mode: str) -> None:
    archive = tmp_path / filename
    _build_tar(
        archive,
        {"data/dem.tif": b"TIFDATA-0123456789", "data/meta.geojson": b"{}"},
        mode=mode,
    )
    files = safe_extract_archive(archive, tmp_path / "out")
    names = sorted(p.name for p in files)
    assert names == ["dem.tif", "meta.geojson"]
    assert (tmp_path / "out" / "data" / "dem.tif").read_bytes() == b"TIFDATA-0123456789"


def test_tar_rejects_symlink_member(tmp_path: Path) -> None:
    archive = tmp_path / "link.tar"
    with tarfile.open(archive, "w") as tf:
        info = tarfile.TarInfo("escape.sh")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        info.size = 0
        tf.addfile(info)
    with pytest.raises(ArchiveSecurityError, match="链接成员"):
        safe_extract_archive(archive, tmp_path / "out")


def test_tar_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "trav.tar"
    _build_tar(archive, {"../escape.txt": b"pwn"})
    with pytest.raises(ArchiveSecurityError, match="非法|穿越"):
        safe_extract_archive(archive, tmp_path / "out")


def test_tar_rejects_exe_member(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    _build_tar(archive, {"run.bat": b"@echo off"}, mode="w:gz")
    with pytest.raises(ArchiveSecurityError, match="危险成员"):
        safe_extract_archive(archive, tmp_path / "out")


# ─── 纯 GZIP 单文件 ──────────────────────────────────────────────────────────


def test_safe_extract_gzip_single_file(tmp_path: Path) -> None:
    archive = tmp_path / "smap_l3.h5.gz"
    payload = b"HDF5-DATA" * 64
    with gzip.open(archive, "wb") as fh:
        fh.write(payload)
    files = safe_extract_archive(archive, tmp_path / "out")
    assert len(files) == 1
    assert files[0].name == "smap_l3.h5"
    assert files[0].read_bytes() == payload


def test_gzip_rejects_dangerous_suffix(tmp_path: Path) -> None:
    archive = tmp_path / "evil.js.gz"
    with gzip.open(archive, "wb") as fh:
        fh.write(b"alert(1)")
    with pytest.raises(ArchiveSecurityError, match="危险成员"):
        safe_extract_archive(archive, tmp_path / "out")


# ─── 7Z（依赖 7-Zip CLI，无则跳过端到端） ──────────────────────────────────


@pytest.mark.skipif(_find_7z() is None, reason="本机无 7-Zip CLI")
def test_safe_extract_7z_roundtrip(tmp_path: Path) -> None:
    seven = _find_7z()
    import subprocess

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "ndvi.tif").write_bytes(b"TIF-0123456789ABCDEF")
    archive = tmp_path / "pack.7z"
    subprocess.run(
        [seven, "a", str(archive), str(src_dir / "ndvi.tif")],
        capture_output=True,
        check=True,
        timeout=60,
    )
    files = safe_extract_archive(archive, tmp_path / "out")
    assert any(p.name == "ndvi.tif" for p in files)
    content = next(p for p in files if p.name == "ndvi.tif").read_bytes()
    assert content == b"TIF-0123456789ABCDEF"


def test_7z_without_cli_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "pack.7z"
    archive.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 16)
    monkeypatch.setattr(
        "app.data_io.services.archive_safe._find_7z", lambda: None
    )
    with pytest.raises(ValueError, match="7-Zip"):
        safe_extract_archive(archive, tmp_path / "out")
