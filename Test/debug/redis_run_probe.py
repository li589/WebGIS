"""探测 Redis 中的 workflow run 键，确认 run 状态是否以 Redis 为主存。

用法: python redis_run_probe.py
"""
import json
import os
import sys

sys.path.insert(0, r"D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend")
from redis import Redis  # noqa: E402


def main() -> None:
    env = {}
    with open(r"D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\.env", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    url = env.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    print("redis url:", url)
    r = Redis.from_url(url, decode_responses=True)
    run_id = "run-1a0f754b7f0a"
    pat = f"*{run_id}*"
    keys = list(r.scan_iter(match=pat, count=200))
    print(f"keys matching {pat}: {len(keys)}")
    for k in keys[:20]:
        t = r.type(k)
        print(f"  {k} ({t})")
        if t == "string":
            v = r.get(k)
            print("    ", (v or "")[:300])
    # 也扫一下 workflow run 常见前缀
    for prefix in ("workflow:run:", "cgda:workflow:", "workflow_run:"):
        ks = list(r.scan_iter(match=f"{prefix}*", count=50))
        print(f"prefix {prefix}: {len(ks)} keys (first 5: {ks[:5]})")


if __name__ == "__main__":
    main()
