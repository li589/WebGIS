"""Download additional SMAP L3 SM P files for 2023-01 (2 weeks coverage).

Already have: 20230110, 20230118, 20230126, 20230129
Need ~10 more files for 2 weeks coverage.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://nasfile.personaltunnel.dpdns.org"
USERNAME = "user"
PASSWORD = "remotefangwen123"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
LOCAL_ROOT = Path(r"I:\Geograph_DataSet\SMAP")

# Additional SMAP files to download (skip existing ones)
# Pick ~10 files spread across January for 2-week coverage
SMAP_DATES = [
    "20230101",
    "20230103",
    "20230105",
    "20230107",
    "20230109",
    "20230112",
    "20230114",
    "20230115",
    "20230120",
    "20230122",
    "20230124",
    "20230127",
    "20230130",
    "20230131",
]


def login() -> str:
    url = f"{BASE_URL}/api/login"
    body = json.dumps({"username": USERNAME, "password": PASSWORD}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return resp.read().decode("utf-8").strip().strip('"')


def download_file(remote_path: str, local_path: Path, token: str) -> int:
    encoded = urllib.parse.quote(remote_path.strip("/"), safe="/")
    url = f"{BASE_URL}/api/raw/{encoded}"
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "X-Auth": token}, method="GET"
    )
    local_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=300) as resp:
        with open(local_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
    return downloaded


def main():
    token = login()
    print(f"SMAP 2周数据下载: {len(SMAP_DATES)} 个候选文件")

    # List remote directory to get exact filenames
    list_url = f"{BASE_URL}/api/resources/Wangc/SWAP%20L3"
    req = urllib.request.Request(
        list_url, headers={"User-Agent": UA, "X-Auth": token}, method="GET"
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else data

    # Build filename map
    remote_files = {}
    for item in items:
        name = item.get("name", "")
        if name.endswith(".h5") and not item.get("isDir", False):
            for date in SMAP_DATES:
                if date in name:
                    remote_files[date] = (name, item.get("size", 0))
                    break

    print(f"找到 {len(remote_files)} 个匹配文件\n")

    total_ok = 0
    total_skip = 0
    total_fail = 0
    total_bytes = 0

    for date in SMAP_DATES:
        if date not in remote_files:
            print(f"  {date}: 未找到")
            total_fail += 1
            continue

        filename, remote_size = remote_files[date]
        local_path = LOCAL_ROOT / filename

        if local_path.exists() and local_path.stat().st_size >= remote_size:
            print(f"  {date}: SKIP (已存在) {filename}")
            total_skip += 1
            continue

        print(f"  {date}: 下载 {filename} ({remote_size / 1024 / 1024:.1f} MB)")
        try:
            start = time.time()
            size = download_file(f"/Wangc/SWAP L3/{filename}", local_path, token)
            elapsed = time.time() - start
            speed = size / elapsed if elapsed > 0 else 0
            print(
                f"    OK: {size / 1024 / 1024:.1f} MB in {elapsed:.1f}s ({speed / 1024 / 1024:.1f} MB/s)"
            )
            total_ok += 1
            total_bytes += size
            time.sleep(0.2)
        except Exception as e:
            print(f"    FAILED: {e}")
            total_fail += 1
            if local_path.exists():
                try:
                    local_path.unlink()
                except OSError:
                    pass

    print(f"\n{'=' * 50}")
    print(f"SMAP 下载完成: {total_ok} 成功, {total_skip} 跳过, {total_fail} 失败")
    print(f"总下载量: {total_bytes / 1024 / 1024:.1f} MB")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
