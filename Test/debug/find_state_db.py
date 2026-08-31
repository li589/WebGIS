"""定位后端实际使用的 workflow_state 目录与 run 存储。

用法: python find_state_db.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_variant_routing import _req, login


def main() -> None:
    if not login():
        return
    for path in ("/runtime/status", "/config/deployment"):
        code, body, _ = _req("GET", path)
        print(f"== {path} ({code}) ==")
        s = json.dumps(body, ensure_ascii=False)
        for m in re.finditer(r'"[^"]*(?:state|root|dir|path)[^"]*"\s*:\s*"[^"]*"', s, re.I):
            t = m.group(0)
            if any(k in t for k in ("I:", "D:", "workflow_state", "data_root", "runtime")):
                print(" ", t[:220])
        if code != 200:
            print(" ", s[:300])


if __name__ == "__main__":
    main()
