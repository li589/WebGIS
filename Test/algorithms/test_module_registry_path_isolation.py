"""Registry 扫描不得依赖外部 sys.path：provider root 须由 registry 自注入。

工况回放：backend worker 在 path 上下文退出后才触发
``_ensure_default_modules_loaded``，此时 provider root 已移出 sys.path，
``modules/ndvi.py`` 顶层 ``from output import OutputCoordinator`` 抛
ImportError，``ndvi_daily`` 被 compat ``PipelineBackedModule`` shim 遮蔽
（worker-standard.log 中 "Failed to load module ndvi" 累计 100+ 次），
原生端口签名与执行行为因此长期失效。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROVIDER_ROOT = (
    Path(__file__).resolve().parents[2]
    / "Code"
    / "algorithms"
    / "providers"
    / "Python"
)

_CODE = """
import sys
sys.path.insert(0, {root!r})
import workflow
sys.path.remove({root!r})
import modules.registry
m = modules.registry.get_module("ndvi_daily")
print(m.__class__.__module__)
"""


def test_native_ndvi_module_loads_without_provider_root_on_path() -> None:
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _CODE.format(root=str(_PROVIDER_ROOT))],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "modules.ndvi", (
        f"ndvi_daily 被非原生实现顶班: {proc.stdout!r} {proc.stderr[-500:]}"
    )
