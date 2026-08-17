"""构造 Test/algorithms/fixtures/grib2_t2m_2x2.grib2（离线、无版权依赖）。

用法（仓库根执行）::

    Env/Python312/python.exe Test/algorithms/fixtures/generate_grib2_fixture.py

产出 2×2 regular_ll 单变量（t2m）GRIB2：
  - 网格：lat 60→59 N（1° 步长，北→南扫描），lon 100→101 E
  - 值：[[274.15, 275.15], [276.15, NaN]]（行=纬度，列=经度）
  - 一处缺测值经 GRIB bitmap 编码 → cfgrib 读出 NaN（缺测路径回归）

参数形态复刻真实 NOMADS GFS 文件（Test/.tmp-chart-debug/nomads_smoke.grib2 的键实测）：
centre=kwbc + WMO (0,0,0) Temperature + heightAboveGround level 2。
eccodes 概念表据此解析 shortName='2t' / cfVarName='t2m'，cfgrib 以 cfVarName
命名数据变量。注意：设 paramId 无效（会被重算回 130 't'），centre 决定概念表。

eccodes 不可用时打印指引并退出 1（fixture 二进制已入库，通常无需重生成）。
"""

from __future__ import annotations

import sys
from pathlib import Path

GRID = {
    "Ni": 2,
    "Nj": 2,
    "latitudeOfFirstGridPointInDegrees": 60.0,
    "longitudeOfFirstGridPointInDegrees": 100.0,
    "latitudeOfLastGridPointInDegrees": 59.0,
    "longitudeOfLastGridPointInDegrees": 101.0,
    "iDirectionIncrementInDegrees": 1.0,
    "jDirectionIncrementInDegrees": 1.0,
}

FIXTURE = Path(__file__).with_name("grib2_t2m_2x2.grib2")


def main() -> int:
    try:
        import eccodes
    except ImportError:
        print("eccodes 未安装：pip install eccodes（或使用已入库的 fixture 二进制）")
        return 1

    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        eccodes.codes_set(gid, "centre", "kwbc")
        eccodes.codes_set(gid, "typeOfLevel", "heightAboveGround")
        eccodes.codes_set(gid, "level", 2)
        for key, value in GRID.items():
            eccodes.codes_set(gid, key, value)
        # 行=纬度（北→南），列=经度；最后一格缺测（bitmap → cfgrib 读出 NaN）
        eccodes.codes_set(gid, "bitmapPresent", 1)
        eccodes.codes_set(gid, "missingValue", 9999.0)
        eccodes.codes_set_array(
            gid,
            "values",
            [274.15, 275.15, 276.15, 9999.0],
        )
        short_name = eccodes.codes_get(gid, "shortName")
        cf_var_name = eccodes.codes_get(gid, "cfVarName")
        if (short_name, cf_var_name) != ("2t", "t2m"):
            print(
                f"eccodes 概念解析异常：shortName={short_name!r} cfVarName={cf_var_name!r}"
                "（期望 2t/t2m，可能是 eccodes 版本参数表差异）",
                file=sys.stderr,
            )
            return 1
        with open(FIXTURE, "wb") as f:
            eccodes.codes_write(gid, f)
    finally:
        eccodes.codes_release(gid)

    size = FIXTURE.stat().st_size
    print(f"written {FIXTURE} ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
