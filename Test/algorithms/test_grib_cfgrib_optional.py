"""GRIB read via cfgrib against the in-repo synthetic fixture.

fixture        : Test/algorithms/fixtures/grib2_t2m_2x2.grib2（2×2 t2m，含 1 处缺测）
regenerate     : Env/Python312/python.exe Test/algorithms/fixtures/generate_grib2_fixture.py
fixture 丢失时测试必须失败（红）而非跳过——详见模块级再生成指引。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

pytest.importorskip("cfgrib")
pytest.importorskip("xarray")

from data_access.universal_reader import UniversalDataReader  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "grib2_t2m_2x2.grib2"
# fixture 值经 GRIB float32 编码（274.15 → 274.1499938964844），比较须用近似
EXPECTED = [274.15, 275.15, 276.15]


def test_fixture_present() -> None:
    assert FIXTURE.is_file(), (
        f"{FIXTURE} 缺失：在仓库根执行 "
        "Env/Python312/python.exe Test/algorithms/fixtures/generate_grib2_fixture.py 重新生成"
    )


def test_universal_reader_grib_t2m() -> None:
    reader = UniversalDataReader(FIXTURE)
    assert reader.format == "grib"
    data = reader.read_variable("t2m")
    assert data.var_name == "t2m"
    assert data.values is not None
    flat = data.values.ravel().tolist()
    assert len(flat) == 4
    for expected, actual in zip(EXPECTED, flat[:3], strict=True):
        assert actual == pytest.approx(expected, abs=1e-2)
    assert math.isnan(flat[3])


def test_universal_reader_grib_list_variables() -> None:
    reader = UniversalDataReader(FIXTURE)
    assert "t2m" in reader.list_variables()


def test_universal_reader_grib_magic_opaque_suffix(tmp_path: Path) -> None:
    """NOMADS filter 脚本等无扩展名产物须走 magic 头探测（GRIB…）而非后缀。"""
    opaque = tmp_path / "filter_gfs_0p25.pl"
    opaque.write_bytes(FIXTURE.read_bytes())
    reader = UniversalDataReader(opaque)
    assert reader.format == "grib"
    data = reader.read_variable("t2m")
    assert data.values is not None
    assert data.values.size == 4


def test_universal_reader_grib_bbox_crop() -> None:
    """bbox 经纬标签裁剪：仅含 (60N, 100E) 一格中心 → 1 值 274.15。"""
    reader = UniversalDataReader(FIXTURE)
    data = reader.read_variable("t2m", bbox=(100.0, 59.5, 100.5, 60.5))
    assert data.values is not None
    assert data.values.size == 1
    assert float(data.values.ravel()[0]) == pytest.approx(274.15, abs=1e-2)


def test_format_registry_grib_adapter() -> None:
    from data_access import build_default_format_registry, build_resource_ref

    registry = build_default_format_registry()
    resource = build_resource_ref(
        uri=FIXTURE.resolve().as_uri(),
        source_kind="local",
        local_path=str(FIXTURE),
        format="grib2",
    )
    loaded = registry.load(resource)
    assert loaded["variable_names"] == ("t2m",)
    assert "grib" in registry.registered_formats()


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def put(self, artifact, payload=None) -> object:  # noqa: ANN001
        self.items[artifact.artifact_id] = payload
        return artifact


def _node_ctx(workspace: Path):
    from types import SimpleNamespace

    from workflow.schemas import NodeExecutionContext

    request = SimpleNamespace(
        job_id="job-grib",
        datasource_selection={},
        region=None,
        time_range=SimpleNamespace(start="2023-01-01", end="2023-01-02"),
    )
    runtime = SimpleNamespace(run_id="run-grib", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
    )


def test_variable_extract_node_grib(tmp_path: Path) -> None:
    import contracts.job  # noqa: F401 — 打断 contracts ↔ workflow 循环导入
    import numpy as np
    from modules import registry as module_registry

    ctx = _node_ctx(tmp_path)
    module = module_registry.get_module("variable_extract")
    outputs = module.execute(
        inputs={"path": str(FIXTURE)},
        params={"variable": "t2m"},
        ctx=ctx,
    )
    assert outputs["array"]["var_name"] == "t2m"
    assert outputs["array"]["shape"] == [2, 2]
    with np.load(outputs["array"]["path"]) as payload:
        values = np.asarray(payload["values"])
        assert values.shape == (2, 2)
        assert float(values.ravel()[0]) == pytest.approx(274.15, abs=1e-2)


def test_format_convert_node_grib_to_mat(tmp_path: Path) -> None:
    import contracts.job  # noqa: F401
    import numpy as np
    from scipy.io import loadmat

    from modules import registry as module_registry

    ctx = _node_ctx(tmp_path)
    module = module_registry.get_module("format_convert")
    outputs = module.execute(
        inputs={"path": str(FIXTURE)},
        params={"target_format": "mat", "variable": "t2m"},
        ctx=ctx,
    )
    mat_path = Path(outputs["path"])
    assert mat_path.suffix == ".mat"
    payload = loadmat(mat_path)
    values = np.asarray(payload["values"])
    assert values.shape == (2, 2)
    assert float(values.ravel()[0]) == pytest.approx(274.15, abs=1e-2)
