#!/usr/bin/env python3
"""支持断点续传的健壮下载脚本。

特性:
  - HTTP Range 断点续传
  - 超时 3600s（适配大文件）
  - 重试逻辑（指数退避，max_attempts=3）
  - 自动检测本地部分文件并续传
  - 进度显示

用法:
  python download_resumable.py           # 下载所有待下载文件
  python download_resumable.py hfp       # 只下载 hfp2018
  python download_resumable.py era5      # 只下载 ERA5
  python download_resumable.py biomass   # 只下载 BIOMASS
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
    "win11": {
        "base_url": "https://win11file.personaltunnel.dpdns.org",
        "username": "user",
        "password": "remotefangwen123",
    },
}

LOCAL_ROOT = Path(r"I:\Geograph_DataSet")
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
REQUEST_DELAY = 0.12
DOWNLOAD_TIMEOUT = 3600  # 60 分钟
CHUNK_SIZE = 262144  # 256 KB
MAX_RETRIES = 3
INITIAL_BACKOFF = 2  # 秒

# ─── 待下载文件列表 ────────────────────────────────────────────────────────────
# (server, remote_path, local_subdir, description, tag)
PENDING_LIST: list[tuple[str, str, str, str, str]] = [
    # hfp2018 重下（不完整 46.7%）
    ("nas", "/Wangc/HFP/Human_p/hfp2018.tif", "HumanFootprint", "Human Footprint 2018 (re-download)", "hfp"),
    # ERA5 SMCI（3 年，每个 ~2.8 GB）
    ("nas", "/Wangc/ERES5/SMCI/ERA5_2018_SMCI-T7.nc", "Weather", "ERA5 SMCI 2018", "era5"),
    ("nas", "/Wangc/ERES5/SMCI/ERA5_2019_SMCI-T7.nc", "Weather", "ERA5 SMCI 2019", "era5"),
    ("nas", "/Wangc/ERES5/SMCI/ERA5_2020_SMCI-T7.nc", "Weather", "ERA5 SMCI 2020", "era5"),
    # ESACCI-BIOMASS（17.3 GB，可选）
    ("nas", "/Wangc/Biomass/2018/ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc", "Biomass", "ESACCI BIOMASS AGB 2020", "biomass"),
]


# ─── FileBrowser 客户端（支持断点续传）─────────────────────────────────────────

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
        body = json.dumps({"username": self.username, "password": self.password}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", "User-Agent": BROWSER_UA},
            method="POST",
        )
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=30) as resp:
            self._token = resp.read().decode("utf-8").strip().strip('"')

    def get_remote_size(self, remote_path: str) -> int | None:
        """获取远程文件大小（字节）。"""
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

    def download_with_resume(self, remote_path: str, local_path: Path,
                              remote_size: int | None = None) -> int:
        """支持断点续传的下载。返回本次下载的字节数。"""
        if self._token is None:
            self.login()

        encoded = urllib.parse.quote(remote_path.strip("/"), safe="/")
        url = f"{self.base_url}/api/raw/{encoded}"
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # 检查本地已有大小
        existing_size = local_path.stat().st_size if local_path.exists() else 0

        if remote_size is not None and existing_size >= remote_size:
            print(f"    已完成: {existing_size} / {remote_size} 字节")
            return 0

        # 构造 Range 请求
        headers = self._headers()
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"
            print(f"    断点续传: 从 {existing_size} 字节开始")
        else:
            print(f"    全新下载")

        req = urllib.request.Request(url, headers=headers, method="GET")
        downloaded_this_session = 0

        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=DOWNLOAD_TIMEOUT) as resp:
            # 检查响应状态
            status = resp.status
            if status == 206:
                # Partial Content - 断点续传成功
                mode = "ab"
            elif status == 200:
                # 完整内容 - 服务器不支持 Range 或从头开始
                if existing_size > 0:
                    print(f"    服务器不支持断点续传，从头下载")
                    existing_size = 0
                mode = "wb"
            else:
                raise RuntimeError(f"意外的 HTTP 状态: {status}")

            with open(local_path, mode) as f:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded_this_session += len(chunk)
                    # 每 50 MB 打印一次进度
                    if downloaded_this_session % (50 * 1024 * 1024) < CHUNK_SIZE:
                        current = existing_size + downloaded_this_session
                        pct = (current / remote_size * 100) if remote_size else 0
                        print(f"    进度: {current / 1024 / 1024:.1f} MB"
                              + (f" / {remote_size / 1024 / 1024:.1f} MB ({pct:.1f}%)" if remote_size else ""))

        return downloaded_this_session


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


def download_with_retry(client: FileBrowserClient, remote_path: str,
                         local_path: Path, desc: str) -> bool:
    """带重试逻辑的下载。"""
    # 先获取远程文件大小
    remote_size = client.get_remote_size(remote_path)
    if remote_size:
        print(f"    远程大小: {_format_size(remote_size)}")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # 检查是否已完成
            existing = local_path.stat().st_size if local_path.exists() else 0
            if remote_size and existing >= remote_size:
                print(f"    已完成（本地 {existing} 字节 >= 远程 {remote_size} 字节）")
                return True

            print(f"    尝试 {attempt}/{MAX_RETRIES}")
            start = time.time()
            downloaded = client.download_with_resume(remote_path, local_path, remote_size)
            elapsed = time.time() - start

            # 验证完整性
            final_size = local_path.stat().st_size
            if remote_size and final_size < remote_size:
                print(f"    不完整: {final_size} / {remote_size} 字节，将重试")
                if attempt < MAX_RETRIES:
                    backoff = INITIAL_BACKOFF * (2 ** (attempt - 1))
                    print(f"    等待 {backoff}s 后重试...")
                    time.sleep(backoff)
                continue

            speed = downloaded / elapsed if elapsed > 0 and downloaded > 0 else 0
            print(f"    OK: 本次下载 {_format_size(downloaded)}, "
                  f"总大小 {_format_size(final_size)}, 耗时 {elapsed:.1f}s")
            if speed > 0:
                print(f"    速度: {_format_size(int(speed))}/s")
            return True

        except (TimeoutError, OSError, RuntimeError) as exc:
            print(f"    失败: {exc}")
            if attempt < MAX_RETRIES:
                backoff = INITIAL_BACKOFF * (2 ** (attempt - 1))
                print(f"    等待 {backoff}s 后重试...")
                time.sleep(backoff)
            else:
                print(f"    已达最大重试次数，放弃")
                return False
    return False


def main() -> None:
    filter_tag = sys.argv[1].lower() if len(sys.argv) > 1 else None
    items = PENDING_LIST
    if filter_tag:
        items = [it for it in PENDING_LIST if it[4] == filter_tag]
        print(f"过滤: '{filter_tag}', 匹配 {len(items)} 个文件")
    else:
        print(f"下载全部: {len(items)} 个文件")

    print(f"目标目录: {LOCAL_ROOT}")
    print(f"超时: {DOWNLOAD_TIMEOUT}s, 重试: {MAX_RETRIES}, 断点续传: 支持")
    print()

    total_ok = 0
    total_skip = 0
    total_fail = 0

    # 按服务器分组
    by_server: dict[str, list] = {}
    for item in items:
        by_server.setdefault(item[0], []).append(item)

    for server_key, server_items in by_server.items():
        cfg = SERVERS[server_key]
        client = FileBrowserClient(cfg["base_url"], cfg["username"], cfg["password"])
        print(f"[{server_key}] 登录中...")
        client.login()
        print(f"[{server_key}] 登录成功，开始下载 {len(server_items)} 个文件...")
        print()

        for i, (_, remote_path, local_subdir, desc, _) in enumerate(server_items, 1):
            filename = Path(remote_path).name
            local_path = LOCAL_ROOT / local_subdir / filename

            print(f"  [{i}/{len(server_items)}] {desc}")
            print(f"    {server_key}:{remote_path}")
            print(f"    -> {local_path}")

            # 检查是否已完成（远程大小对比）
            remote_size = client.get_remote_size(remote_path)
            if local_path.exists() and remote_size:
                local_size = local_path.stat().st_size
                if local_size >= remote_size:
                    print(f"    SKIP (已完成: {_format_size(local_size)})")
                    total_skip += 1
                    print()
                    continue
                else:
                    print(f"    本地不完整: {_format_size(local_size)} / {_format_size(remote_size)}")

            ok = download_with_retry(client, remote_path, local_path, desc)
            if ok:
                total_ok += 1
            else:
                total_fail += 1
            print()
            time.sleep(REQUEST_DELAY)

    print("=" * 60)
    print(f"下载完成: {total_ok} 成功, {total_skip} 跳过, {total_fail} 失败")
    print("=" * 60)


if __name__ == "__main__":
    main()
