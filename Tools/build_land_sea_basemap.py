#!/usr/bin/env python3
"""生成「海陆双色」底图（只有海陆分界，没有国界、没有地名）。

用途：顶栏「底图」菜单里新增的「海陆底图」叠加项。用户录屏/出图时不想要
国界线和地名，只要海陆轮廓做参照。

为什么不重新跑一遍矢量化：
  同目录已有 world-land-merc-4096.png，它的 **alpha 通道就是陆地掩膜**
  （Land=(NE 全球国家面 − 中国标准省界) ∪ 中国标准省界，已按 EPSG:3857
  烤制）。直接拿 alpha 当选区重新上色，像素级对齐、零风险，也不必再读
  geopandas / Natural Earth —— 更不会碰到已有产物。

输出：
  Code/frontend/public/data/boundaries/world-landsea-merc-4096.png
  - 4096²，RGBA，**全不透明**（陆地/海洋各一色）
  - 文件名带 merc + 尺寸：改颜色后必须换名，否则浏览器吃旧缓存（踩过）

用法（项目虚拟环境）：
  Env/Python312/python.exe Tools/build_land_sea_basemap.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = REPO_ROOT / "Code" / "frontend" / "public" / "data" / "boundaries"
SRC = BASE / "world-land-merc-4096.png"
OUT = BASE / "world-landsea-merc-4096.png"

#: 陆地：暖米白（与高德陆地 #fcf9f2 同族，略深一点，便于和海洋分开）
LAND_RGB = (0xEF, 0xEC, 0xE4)
#: 海洋：低饱和柔蓝。两边都浅，数据色带（如 ylgnbu 最浅档 #ffffd9）压上去仍清楚
SEA_RGB = (0xD6, 0xE4, 0xEE)


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"缺少陆地掩膜：{SRC}\n先跑 Tools/build_world_land_mask.py 生成它")
    src = Image.open(SRC).convert("RGBA")
    alpha = np.array(src)[..., 3]
    size = src.size
    print(f"读入 {SRC.name}  {size[0]}x{size[1]}  陆地像元 {(alpha > 127).sum():,}")

    rgba = np.zeros((size[1], size[0], 4), dtype="uint8")
    sea_mask = alpha <= 127
    rgba[..., 0] = np.where(sea_mask, SEA_RGB[0], LAND_RGB[0])
    rgba[..., 1] = np.where(sea_mask, SEA_RGB[1], LAND_RGB[1])
    rgba[..., 2] = np.where(sea_mask, SEA_RGB[2], LAND_RGB[2])
    rgba[..., 3] = 255  # 必须全不透明：它要盖住底图上的地名与国界

    Image.fromarray(rgba, "RGBA").save(OUT, optimize=True)
    print(f"写出 {OUT.name}  {OUT.stat().st_size / 1024 / 1024:.2f} MB  陆地 {LAND_RGB} / 海洋 {SEA_RGB}")
    print("  ⇒ 前端 image source coordinates 必须用 ±85.05112877980659")


if __name__ == "__main__":
    main()
