"""进程内 matplotlib 出图互斥锁（P3，2026-08-23）。

pyplot 是**全局状态机**（当前 figure/axes 栈、rcParams）；工作流节点级并行
（``workflow/executor.py`` ThreadPoolExecutor 拓扑分层）下，两个出图节点
同层并发时 figure 创建 / 绘制 / ``plt.close`` 会互相污染——串图、关错图、
"figure has been closed" 异常 race。

多 worker 进程天然隔离（各自进程空间），本锁只需**进程内**互斥。出图是
毫秒~秒级 CPU+IO 操作，串行化的性能代价可忽略；出图节点在同一拓扑层
本来就罕见。

用法：出图函数/方法加 ``@locked_plot``（覆盖创建→绘制→保存→close 全程，
仅锁 save/close 不够——figure 栈操作本身就是竞态点）。锁内严禁再调用
其他被 ``@locked_plot`` 修饰的函数（非重入锁，会自死锁）。
"""

from __future__ import annotations

import functools
import threading
from typing import Any, Callable

plot_lock = threading.Lock()


def locked_plot(func: Callable[..., Any]) -> Callable[..., Any]:
    """出图函数/方法装饰器：进程内串行化 pyplot 全局状态访问。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with plot_lock:
            return func(*args, **kwargs)

    return wrapper
