"""conftest 隔离哨兵回归测试（2026-08-19 生产 DB 污染事故防线）。

哨兵位于 ``Test/backend/conftest.py`` 模块级：deployment.config.json 若定义
workflow_state_dir 等运行时键，``apply_startup_overrides()`` 会在导入
``app.core.config`` 时无条件覆写 ``os.environ``（json 为部署真源，环境变量
无法夺回），静默把 pytest 落点指回生产盘。本测试用 BACKEND_DEPLOYMENT_CONFIG
指向模拟踩踏 json，断言子进程 pytest 在 conftest 加载期即拒绝采集（fail-fast）。

踩踏 json 的 data_root/output_root 使用仓库内目录：must_exist 校验须在
CI（Ubuntu）上也通过，且子进程在哨兵处即中断，不会有任何写入副作用。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGET = _REPO_ROOT / "Test" / "backend" / "test_config_contracts.py"


def test_conftest_guard_rejects_deployment_config_stomp(tmp_path: Path) -> None:
    stomp = tmp_path / "deployment_stomp.json"
    payload = {
        "schema_version": 1,
        "data": {
            "data_root": str(_REPO_ROOT),
            "output_root": str(_REPO_ROOT / "Docs"),
        },
        # 踩踏键：与 conftest 安排的隔离值不同即可触发哨兵
        "runtime": {"workflow_state_dir": str(_REPO_ROOT / "Code")},
        "caches": {},
        "imports": {},
        "docker": {},
    }
    stomp.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    env = {
        **os.environ,
        "BACKEND_DEPLOYMENT_CONFIG": str(stomp),
        # 隔离 WorkBuddy safe-delete shim（AGENTS.md 硬约定）
        "CODEBUDDY_SESSION_ID": "",
        "CLAUDE_SESSION_ID": "",
        "CODEBUDDY_SAFE_DELETE_SANDBOX": "",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_TARGET),
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(tmp_path / "basetemp"),
        ],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        timeout=120,
    )
    out = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert result.returncode != 0, f"哨兵未拒绝踩踏配置，输出:\n{out}"
    assert "RuntimeError" in out
    assert "BACKEND_WORKFLOW_STATE_DIR" in out
