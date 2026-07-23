"""下载剩余的精选文件。

剩余待下载:
1. omega FY avg 6 个文件 → InversionResults/fy_avg/
2. CLCD_v01_1997.tif → LandCover/
3. ERA5 SMCI 3 个文件 → Weather/ (大文件, 2.8 GB 每个)
4. ESACCI-BIOMASS → Biomass/ (16.9 GB, 超大文件)

支持断点续传：已存在且大小匹配的文件会跳过。
"""

from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ─── 配置 ────────────────────────────────────────────────────────────────────

SERVERS = {
    "nas": {
        "base_url": "https://nasfile.personaltunnel.dpdns.org",
        "username": "user",
        "password": "remotefangwen123",
    },
}
LOCAL_ROOT = Path(r"I:\Geograph_DataSet")
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
REQUEST_DELAY = 0.12

# ─── 剩余下载列表 ────────────────────────────────────────────────────────────

# 格式: (server, remote_path, local_subdir, description, tag)
# tag 用于命令行过滤: small / era5 / biomass
REMAINING_LIST: list[tuple[str, str, str, str, str]] = [
    # ── omega FY avg (小文件, ~3.3 MB each) ──
    (
        "nas",
        "/Liuzheng/omega_final/fy_avg_ω/doy_025.mat",
        "InversionResults/fy_avg",
        "omega FY avg DOY 025",
        "small",
    ),
    (
        "nas",
        "/Liuzheng/omega_final/fy_avg_ω/doy_026.mat",
        "InversionResults/fy_avg",
        "omega FY avg DOY 026",
        "small",
    ),
    (
        "nas",
        "/Liuzheng/omega_final/fy_avg_ω/doy_027.mat",
        "InversionResults/fy_avg",
        "omega FY avg DOY 027",
        "small",
    ),
    (
        "nas",
        "/Liuzheng/omega_final/fy_avg_ω/doy_028.mat",
        "InversionResults/fy_avg",
        "omega FY avg DOY 028",
        "small",
    ),
    (
        "nas",
        "/Liuzheng/omega_final/fy_avg_ω/doy_029.mat",
        "InversionResults/fy_avg",
        "omega FY avg DOY 029",
        "small",
    ),
    (
        "nas",
        "/Liuzheng/omega_final/fy_avg_ω/doy_030.mat",
        "InversionResults/fy_avg",
        "omega FY avg DOY 030",
        "small",
    ),
    # ── CLCD (中等文件, ~783 MB) ──
    ("nas", "/Wangc/CLCD/CLCD_v01_1997.tif", "LandCover", "CLCD China 1997", "small"),
    # ── ERA5 SMCI (大文件, ~2.8 GB each) ──
    (
        "nas",
        "/Wangc/ERES5/SMCI/ERA5_2018_SMCI-T7.nc",
        "Weather",
        "ERA5 SMCI 2018",
        "era5",
    ),
    (
        "nas",
        "/Wangc/ERES5/SMCI/ERA5_2019_SMCI-T7.nc",
        "Weather",
        "ERA5 SMCI 2019",
        "era5",
    ),
    (
        "nas",
        "/Wangc/ERES5/SMCI/ERA5_2020_SMCI-T7.nc",
        "Weather",
        "ERA5 SMCI 2020",
        "era5",
    ),
    # ── ESACCI-BIOMASS (超大文件, ~16.9 GB) ──
    (
        "nas",
        "/Wangc/Biomass/2018/ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc",
        "Biomass",
        "ESACCI BIOMASS AGB 2020",
        "biomass",
    ),
]


# ─── FileBrowser 客户端 ──────────────────────────────────────────────────────


class FileBrowserClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: str | None = None
        self._ssl_ctx = ssl.create_default_context()

    def _headers(self) -> dict:
        h = {"User-Agent": BROWSER_UA}
        if self._token:
            h["X-Auth"] = self._token
        return h

    def login(self) -> None:
        url = f"{self.base_url}/api/login"
        body = json.dumps(
            {"username": self.username, "password": self.password}
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": BROWSER_UA},
            method="POST",
        )
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=30) as resp:
            self._token = resp.read().decode("utf-8").strip().strip('"')

    def get_remote_size(self, remote_path: str) -> int | None:
        """查询远程文件大小。"""
        if self._token is None:
            self.login()
        encoded = urllib.parse.quote(remote_path.strip("/"), safe="/")
        url = f"{self.base_url}/api/resources/{encoded}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    return data.get("size")
        except Exception:
            return None
        return None

    def download_file(
        self, remote_path: str, local_path: Path, chunk_size: int = 65536
    ) -> int:
        if self._token is None:
            self.login()
        encoded = urllib.parse.quote(remote_path.strip("/"), safe="/")
        url = f"{self.base_url}/api/raw/{encoded}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=600) as resp:
            with open(local_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
        return downloaded


def _format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"


def main() -> None:
    # 命令行参数：可选指定只下载某类 (small/era5/biomass)
    filter_tag = sys.argv[1] if len(sys.argv) > 1 else None

    items = REMAINING_LIST
    if filter_tag:
        # 用 tag 字段过滤（第 5 个元素，索引 4）
        items = [it for it in REMAINING_LIST if it[4] == filter_tag.lower()]
        print(f"过滤: '{filter_tag}', 匹配 {len(items)} 个文件")

    total = len(items)
    print(f"剩余下载计划: {total} 个文件")
    print(f"目标目录: {LOCAL_ROOT}")
    print()

    cfg = SERVERS["nas"]
    client = FileBrowserClient(cfg["base_url"], cfg["username"], cfg["password"])
    print("[nas] 登录中...")
    client.login()
    print("[nas] 登录成功")
    print()

    total_downloaded = 0
    total_skipped = 0
    total_failed = 0
    total_bytes = 0

    for i, (server, remote_path, local_subdir, desc, _tag) in enumerate(items, 1):
        filename = Path(remote_path).name
        local_path = LOCAL_ROOT / local_subdir / filename

        # 检查本地是否已存在
        if local_path.exists():
            local_size = local_path.stat().st_size
            remote_size = client.get_remote_size(remote_path)
            if remote_size and local_size == remote_size:
                print(
                    f"  [{i}/{total}] SKIP (exists, size match): {filename} -> {local_subdir}\\"
                )
                total_skipped += 1
                continue
            elif remote_size and local_size < remote_size:
                print(
                    f"  [{i}/{total}] RESUME (partial: {_format_size(local_size)} / {_format_size(remote_size)})"
                )
                # 删除部分下载的文件，重新下载
                try:
                    local_path.unlink()
                except OSError:
                    pass
            else:
                print(f"  [{i}/{total}] SKIP (exists): {filename} -> {local_subdir}\\")
                total_skipped += 1
                continue

        try:
            print(f"  [{i}/{total}] {desc}")
            print(f"    nas:{remote_path}")
            print(f"    -> {local_path}")
            start = time.time()
            size = client.download_file(remote_path, local_path)
            elapsed = time.time() - start
            speed = size / elapsed if elapsed > 0 else 0
            print(
                f"    OK: {_format_size(size)} in {elapsed:.1f}s ({_format_size(int(speed))}/s)"
            )
            total_downloaded += 1
            total_bytes += size
            time.sleep(REQUEST_DELAY)
        except Exception as exc:
            print(f"    FAILED: {exc}")
            total_failed += 1
            if local_path.exists():
                try:
                    local_path.unlink()
                except OSError:
                    pass

    print()
    print("=" * 60)
    print(
        f"下载完成: {total_downloaded} 成功, {total_skipped} 跳过, {total_failed} 失败"
    )
    print(f"总下载量: {_format_size(total_bytes)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
