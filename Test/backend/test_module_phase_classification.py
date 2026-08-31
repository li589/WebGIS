"""N4 阶段分类声明化测试：模块 phase 声明优先、substring 匹配回退。

bridge ``_classify_stage`` 先查 modules.registry 的 ``template_overrides
phase`` 声明（stage 名即模块名/别名时命中），未声明或未注册的 stage
回退历史 substring 匹配。
"""

from __future__ import annotations

import pytest

from app.services.python_provider_bridge_service import (
    _STAGE_PHASE_CACHE,
    _classify_stage,
    _declared_module_phase,
)

DECLARED_PHASES = {
    "omega_sf_fenkuai": "inversion",
    "omega_avg_daily": "inversion",
    "omega_block": "inversion",
    "inversion_daily": "inversion",
    "ssh_sync": "download",
    "nsidc_smap_download": "download",
    "gldas_download": "download",
    "fy_preprocess": "preprocess",
}


@pytest.fixture(autouse=True)
def _clear_stage_cache():
    _STAGE_PHASE_CACHE.clear()
    yield
    _STAGE_PHASE_CACHE.clear()


def test_registry_phase_declarations() -> None:
    # 经 bridge 的 provider-root 上下文导入 registry（直接 import 会被
    # backend conftest 的 sys.path 顺序遮蔽 provider 顶层包）。
    for name, phase in DECLARED_PHASES.items():
        assert _declared_module_phase(name) == phase, name


def test_alias_resolves_phase() -> None:
    assert _declared_module_phase("omega_sf_fenkuai_pipeline") == "inversion"


def test_declared_phase_takes_priority() -> None:
    # substring 路径下 omega_avg_daily 无关键字命中会归 processing；
    # 声明化后应返回 inversion，证明声明优先于 substring。
    assert _classify_stage("omega_avg_daily") == "inversion"
    assert _classify_stage("ssh_sync") == "download"
    assert _classify_stage("fy_preprocess") == "preprocess"


def test_undeclared_stage_falls_back_to_substring() -> None:
    # 未声明 phase 的 stage 走 substring 匹配（历史行为不变）。
    assert _classify_stage("data_export") == "output"
    assert _classify_stage("gldas_nc4_to_mat") == "processing"
    assert _classify_stage("fy_download:nas") == "download"
