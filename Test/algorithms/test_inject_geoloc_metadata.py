"""GEOLOCATION metadata 须插在默认 Metadata 之外，否则 gdalwarp -geoloc 失败。"""

from __future__ import annotations

import sys
from pathlib import Path

PROVIDER_ROOT = (
    Path(__file__).resolve().parents[2] / "Code" / "algorithms" / "providers" / "Python"
)
sys.path.insert(0, str(PROVIDER_ROOT))

# 先完整初始化 contracts 链，避免 utils ↔ runner 环导入
import contracts  # noqa: F401, E402

from algorithms.fy import build_geoloc_metadata_block  # noqa: E402
from utils.fy_executor import inject_geoloc_metadata_to_vrt  # noqa: E402


_SAMPLE_VRT = """\
<VRTDataset rasterXSize="4" rasterYSize="3">
  <Metadata>
    <MDI key="Foo">bar</MDI>
    <MDI key="Version_Of_Software">V 1.0.0</MDI>
  </Metadata>
  <GCPList Projection="GEOGCS[&quot;WGS 84&quot;]">
    <GCP Id="" Pixel="0.5" Line="0.5" X="10" Y="20" />
  </GCPList>
  <VRTRasterBand dataType="Float32" band="1">
    <NoDataValue>-32767</NoDataValue>
  </VRTRasterBand>
</VRTDataset>
"""


def test_inject_geoloc_outside_default_metadata(tmp_path: Path) -> None:
    src = tmp_path / "src.vrt"
    dst = tmp_path / "dst.vrt"
    src.write_text(_SAMPLE_VRT, encoding="utf-8")
    block = build_geoloc_metadata_block(
        lon_vrt_path=str(tmp_path / "lon.vrt"),
        lat_vrt_path=str(tmp_path / "lat.vrt"),
    )
    inject_geoloc_metadata_to_vrt(src, dst, block)
    text = dst.read_text(encoding="utf-8")

    # 默认 Metadata 必须先完整关闭，再出现 GEOLOCATION 域
    close_default = text.index("</Metadata>")
    geoloc = text.index('domain="GEOLOCATION"')
    assert close_default < geoloc, "GEOLOCATION must not nest inside default Metadata"
    # 且 GEOLOCATION 块自身也有闭合标签
    assert text.count('domain="GEOLOCATION"') == 1
    assert text.count("<GCPList") == 1


def test_inject_geoloc_without_gcplist(tmp_path: Path) -> None:
    src = tmp_path / "src.vrt"
    dst = tmp_path / "dst.vrt"
    src.write_text(
        """\
<VRTDataset rasterXSize="2" rasterYSize="2">
  <Metadata>
    <MDI key="Foo">bar</MDI>
  </Metadata>
  <VRTRasterBand dataType="Float32" band="1"/>
</VRTDataset>
""",
        encoding="utf-8",
    )
    block = build_geoloc_metadata_block("lon.vrt", "lat.vrt")
    inject_geoloc_metadata_to_vrt(src, dst, block)
    text = dst.read_text(encoding="utf-8")
    assert text.index("</Metadata>") < text.index('domain="GEOLOCATION"')
