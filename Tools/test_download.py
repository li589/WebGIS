#!/usr/bin/env python3
"""测试下载单个文件到 I: 盘。"""

import sys

sys.path.insert(
    0, r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Tools"
)
from download_curated import FileBrowserClient, LOCAL_ROOT, SERVERS

client = FileBrowserClient(
    SERVERS["nas"]["base_url"], SERVERS["nas"]["username"], SERVERS["nas"]["password"]
)
client.login()
print("Login OK")

# Test 1: small .mat file (~3.2 MB)
remote = "/Liuzheng/omega_final/smap_avg_ω/doy_017.mat"
local = LOCAL_ROOT / "InversionResults" / "doy_017.mat"
print(f"Downloading: {remote}")
print(f"-> {local}")
size = client.download_file(remote, local)
print(f"OK: {size} bytes ({size/1024/1024:.1f} MB)")

# Test 2: SMAP .h5 file (~31 MB)
remote2 = "/Wangc/SWAP L3/SMAP_L3_SM_P_20230110_R18290_001.h5"
local2 = LOCAL_ROOT / "SMAP" / "SMAP_L3_SM_P_20230110_R18290_001.h5"
print(f"\nDownloading: {remote2}")
print(f"-> {local2}")
size2 = client.download_file(remote2, local2)
print(f"OK: {size2} bytes ({size2/1024/1024:.1f} MB)")

print("\nTest passed!")
