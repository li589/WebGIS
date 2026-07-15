#!/usr/bin/env python3
"""精选下载脚本：从远程服务器下载中国区域测试数据。

按时间分辨率精选：
  - 日数据（SMAP）：~30 天，约 1 GB
  - 月数据（CMFD）：3 个月，约 1 GB
  - 年数据（精选）：3 年，约 30 GB
  - 静态/小文件（omega .mat、ISMN/FLUX）：约 200 MB

下载到 I:\Geograph_DataSet\ 对应英文目录。
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

# ─── 精选下载列表 ────────────────────────────────────────────────────────────

# 格式: (server, remote_path, local_subdir, description)
DOWNLOAD_LIST: list[tuple[str, str, str, str]] = [
    # ── 1. SMAP 日数据（2023年1月，约30天）── 目标: SMAP\
    # 文件来自 /Wangc/SWAP L3/ 目录，每个约 31 MB
    ("nas", "/Wangc/SWAP L3/SMAP_L3_SM_P_20230110_R18290_001.h5", "SMAP", "SMAP L3 SM 2023-01-10"),
    ("nas", "/Wangc/SWAP L3/SMAP_L3_SM_P_20230118_R18290_001.h5", "SMAP", "SMAP L3 SM 2023-01-18"),
    ("nas", "/Wangc/SWAP L3/SMAP_L3_SM_P_20230126_R18290_001.h5", "SMAP", "SMAP L3 SM 2023-01-26"),
    ("nas", "/Wangc/SWAP L3/SMAP_L3_SM_P_20230129_R18290_001.h5", "SMAP", "SMAP L3 SM 2023-01-29"),
    # SMAP L3 SM P E (被动+主动, 50 MB each) - 补充数据
    ("nas", "/Chenhaojun/Data/smap缺的日期/SMAP_L3_SM_P_E_20220920_R19240_001.h5", "SMAP", "SMAP L3 SM P_E 2022-09-20"),

    # ── 2. CMFD 月数据（中国区域气象驱动数据）── 目标: Weather\
    ("nas", "/Wangc/CMFD/Data_forcing_01mo_010deg/lrad_CMFD_V0106_B-01_01mo_010deg_197901-201812.nc", "Weather", "CMFD 月均长波辐射 1979-2018"),
    ("nas", "/Wangc/CMFD/Data_forcing_01mo_010deg/srad_CMFD_V0106_B-01_01mo_010deg_197901-201812.nc", "Weather", "CMFD 月均短波辐射 1979-2018"),

    # ── 3. 年数据（精选3年：2018-2020）──
    # Human Footprint（人类足迹）→ HumanFootprint\
    ("nas", "/Wangc/HFP/Human_p/hfp2018.tif", "HumanFootprint", "Human Footprint 2018"),
    ("nas", "/Wangc/HFP/Human_p/hfp2019.tif", "HumanFootprint", "Human Footprint 2019"),
    ("nas", "/Wangc/HFP/Human_p/hfp2020.tif", "HumanFootprint", "Human Footprint 2020"),

    # ERA5 SMCI（土壤水分气候指数）→ Weather\
    ("nas", "/Wangc/ERES5/SMCI/ERA5_2018_SMCI-T7.nc", "Weather", "ERA5 SMCI 2018"),
    ("nas", "/Wangc/ERES5/SMCI/ERA5_2019_SMCI-T7.nc", "Weather", "ERA5 SMCI 2019"),
    ("nas", "/Wangc/ERES5/SMCI/ERA5_2020_SMCI-T7.nc", "Weather", "ERA5 SMCI 2020"),

    # MCD12Q1 China（土地覆盖，中国区域）→ LandCover\
    ("nas", "/LiuSJ/Data/MCD12Q1_China/MCD12Q1_2019.tif", "LandCover", "MCD12Q1 China 2019"),
    ("nas", "/LiuSJ/Data/MCD12Q1_China/MCD12Q1_2020.tif", "LandCover", "MCD12Q1 China 2020"),
    ("nas", "/LiuSJ/Data/MCD12Q1_China/MCD12Q1_2021.tif", "LandCover", "MCD12Q1 China 2021"),

    # ESACCI-BIOMASS（生物量，1年测试）→ Biomass\
    ("nas", "/Wangc/Biomass/2018/ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc", "Biomass", "ESACCI BIOMASS AGB 2020"),

    # CLCD（中国土地覆盖动态）→ LandCover\
    ("nas", "/Wangc/CLCD/CLCD_v01_1997.tif", "LandCover", "CLCD China 1997"),

    # china1km 降水/温度（中国1km分辨率）→ Precipitation\ / Weather\
    ("nas", "/Wangxd/china1km/pre_tif/pre_2002_01.tif", "Precipitation", "China 1km precip 2002-01"),
    ("nas", "/Wangxd/china1km/pre_tif/pre_2002_02.tif", "Precipitation", "China 1km precip 2002-02"),
    ("nas", "/Wangxd/china1km/pre_tif/pre_2002_03.tif", "Precipitation", "China 1km precip 2002-03"),
    ("nas", "/Wangxd/china1km/tmp_tif/tmp_2002_01.tif", "Weather", "China 1km temp 2002-01"),
    ("nas", "/Wangxd/china1km/tmp_tif/tmp_2002_02.tif", "Weather", "China 1km temp 2002-02"),
    ("nas", "/Wangxd/china1km/tmp_tif/tmp_2002_03.tif", "Weather", "China 1km temp 2002-03"),

    # ── 4. 静态/小文件 ──
    # omega 反演结果 .mat → InversionResults\
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_017.mat", "InversionResults", "omega SMAP avg DOY 017"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_018.mat", "InversionResults", "omega SMAP avg DOY 018"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_019.mat", "InversionResults", "omega SMAP avg DOY 019"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_020.mat", "InversionResults", "omega SMAP avg DOY 020"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_021.mat", "InversionResults", "omega SMAP avg DOY 021"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_022.mat", "InversionResults", "omega SMAP avg DOY 022"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_023.mat", "InversionResults", "omega SMAP avg DOY 023"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_024.mat", "InversionResults", "omega SMAP avg DOY 024"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_025.mat", "InversionResults", "omega SMAP avg DOY 025"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_026.mat", "InversionResults", "omega SMAP avg DOY 026"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_027.mat", "InversionResults", "omega SMAP avg DOY 027"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_028.mat", "InversionResults", "omega SMAP avg DOY 028"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_029.mat", "InversionResults", "omega SMAP avg DOY 029"),
    ("nas", "/Liuzheng/omega_final/smap_avg_ω/doy_030.mat", "InversionResults", "omega SMAP avg DOY 030"),
    # omega FY avg
    ("nas", "/Liuzheng/omega_final/fy_avg_ω/doy_025.mat", "InversionResults", "omega FY avg DOY 025"),
    ("nas", "/Liuzheng/omega_final/fy_avg_ω/doy_026.mat", "InversionResults", "omega FY avg DOY 026"),
    ("nas", "/Liuzheng/omega_final/fy_avg_ω/doy_027.mat", "InversionResults", "omega FY avg DOY 027"),
    ("nas", "/Liuzheng/omega_final/fy_avg_ω/doy_028.mat", "InversionResults", "omega FY avg DOY 028"),
    ("nas", "/Liuzheng/omega_final/fy_avg_ω/doy_029.mat", "InversionResults", "omega FY avg DOY 029"),
    ("nas", "/Liuzheng/omega_final/fy_avg_ω/doy_030.mat", "InversionResults", "omega FY avg DOY 030"),

    # ISMN/FLUX 站点匹配数据 → Station\
    ("nas", "/Liuzheng/ISMN和FLUXz站点匹配/ISMN_vs_Fluxnet2015.csv", "Station", "ISMN vs FLUXNET site matching"),

    # Landscape Metrics → InversionResults\
    ("nas", "/Liuzheng/Data/Landscape_Metrics_LandOnly_9KM_2020.mat", "InversionResults", "Landscape Metrics 9KM 2020"),
    ("nas", "/Liuzheng/Data/Forest_Ratio_9KM_2020.mat", "InversionResults", "Forest Ratio 9KM 2020"),

    # Aridity Index → Others\
    ("nas", "/Liuzheng/Data/AI/AridityIndex_MSWEP-prcp_div_GLEAM-Ep_1980-2020.tif", "Others", "Aridity Index 1980-2020"),
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
        body = json.dumps({"username": self.username, "password": self.password}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", "User-Agent": BROWSER_UA},
            method="POST",
        )
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=30) as resp:
            self._token = resp.read().decode("utf-8").strip().strip('"')

    def download_file(self, remote_path: str, local_path: Path, chunk_size: int = 65536) -> int:
        if self._token is None:
            self.login()
        encoded = urllib.parse.quote(remote_path.strip("/"), safe="/")
        url = f"{self.base_url}/api/raw/{encoded}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=300) as resp:
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
    # 按服务器分组
    by_server: dict[str, list[tuple[str, str, str]]] = {}
    for server, remote_path, local_subdir, desc in DOWNLOAD_LIST:
        by_server.setdefault(server, []).append((remote_path, local_subdir, desc))

    total = len(DOWNLOAD_LIST)
    print(f"精选下载计划: {total} 个文件")
    print(f"目标目录: {LOCAL_ROOT}")
    print()

    # 预览
    for server, items in by_server.items():
        print(f"  [{server}] {len(items)} 个文件")
    print()

    total_downloaded = 0
    total_skipped = 0
    total_failed = 0
    total_bytes = 0

    for server_key, items in by_server.items():
        cfg = SERVERS[server_key]
        client = FileBrowserClient(cfg["base_url"], cfg["username"], cfg["password"])
        print(f"[{server_key}] 登录中...")
        client.login()
        print(f"[{server_key}] 登录成功，开始下载 {len(items)} 个文件...")

        for i, (remote_path, local_subdir, desc) in enumerate(items, 1):
            # 构建本地路径：保留远程文件名
            filename = Path(remote_path).name
            local_path = LOCAL_ROOT / local_subdir / filename

            # 检查是否已存在
            if local_path.exists():
                print(f"  [{i}/{len(items)}] SKIP (exists): {filename} -> {local_subdir}\\")
                total_skipped += 1
                continue

            try:
                print(f"  [{i}/{len(items)}] {desc}")
                print(f"    {server_key}:{remote_path}")
                print(f"    -> {local_path}")
                start = time.time()
                size = client.download_file(remote_path, local_path)
                elapsed = time.time() - start
                speed = size / elapsed if elapsed > 0 else 0
                print(f"    OK: {_format_size(size)} in {elapsed:.1f}s ({_format_size(int(speed))}/s)")
                total_downloaded += 1
                total_bytes += size
                time.sleep(REQUEST_DELAY)
            except Exception as exc:
                print(f"    FAILED: {exc}")
                total_failed += 1
                # 清理可能的半下载文件
                if local_path.exists():
                    try:
                        local_path.unlink()
                    except OSError:
                        pass

    print()
    print("=" * 60)
    print(f"下载完成: {total_downloaded} 成功, {total_skipped} 跳过, {total_failed} 失败")
    print(f"总下载量: {_format_size(total_bytes)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
