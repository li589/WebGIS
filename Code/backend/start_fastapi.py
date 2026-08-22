"""FastAPI 启动脚本，确保 shared / webgis_gee 模块在 Python 路径中。

多进程说明：``BACKEND_FASTAPI_WORKERS``（settings.fastapi_workers，默认 1）控制
uvicorn worker 数。Windows 下 uvicorn 多进程使用 ``multiprocessing`` spawn，子进程
会重新导入本模块顶层代码（sys.path 注入，无害），因此必须调用
``multiprocessing.freeze_support()`` 且把 ``uvicorn.run`` 放在
``if __name__ == "__main__":`` 保护内，避免子进程递归启动。

多 worker 下 lifespan（bootstrap_auth / effective_config / seeds 同步）会并发执行，
相关初始化均为幂等实现；限流与会话依赖 Redis 集中存储（见 app/api/rate_limit.py、
app/services/session_service.py），不可用时自动降级并告警。
"""

import multiprocessing
import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parent
code_path = backend_root.parent
gee_src = backend_root / "app" / "gee" / "core" / "src"

for p in (str(code_path), str(gee_src)):
    if p not in sys.path:
        sys.path.insert(0, p)

import uvicorn
from app.core.config import settings


def main() -> None:
    env = (settings.environment or "").lower()
    # A-4：BACKEND_RELOAD 默认 true 仅服务开发热重载；production 一律禁用
    # （watchfiles 常驻开销 + 部署目录文件变动会不可控地重启 worker）
    reload = settings.reload and settings.fastapi_workers <= 1
    if env not in {"development", "dev", "test", "testing"} and reload:
        reload = False
        print(
            "[start_fastapi] production 环境忽略 BACKEND_RELOAD=true（热重载已禁用）",
            flush=True,
        )
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=reload,
        workers=settings.fastapi_workers,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
