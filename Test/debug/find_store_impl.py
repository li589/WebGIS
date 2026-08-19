"""定位 GET /workflow-runs/{run_id} 的实现与 run 状态存储链。"""
import os
import re

ROOT = r"D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\app"


def grep(pattern: str, label: str) -> None:
    pat = re.compile(pattern)
    print(f"== {label} ==")
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if pat.search(line):
                            print(f"  {os.path.relpath(p, ROOT)}:{i}: {line.strip()[:150]}")
            except OSError:
                pass


if __name__ == "__main__":
    grep(r"def get_workflow_run|def get_run\b|GET.*workflow-runs/\{run", "router: get run")
    grep(r"class .*WorkflowState|workflow_runs.*INSERT|INSERT INTO workflow_runs", "state store")
