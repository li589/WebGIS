"""P3（2026-08-23）：pyplot 并发隔离回归测试。

pyplot 是全局状态机；工作流节点级并行（ThreadPoolExecutor 拓扑分层）下
两个出图节点同层并发会串图/关错图。修复 = ``viz_lock.plot_lock`` 进程内
互斥（``@locked_plot`` 装饰器覆盖创建→绘制→保存→close 全程）。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

plt = pytest.importorskip("matplotlib.pyplot")

from viz_lock import locked_plot, plot_lock


@locked_plot
def _slow_chart(marker: str, out_path, *, hold: float = 0.15) -> str:
    """受锁保护的慢速出图：figure 创建→绘制→保存→close 全程。"""
    fig, ax = plt.subplots(figsize=(3, 3))
    ax.set_title(marker)
    # 模拟慢绘制：期间 pyplot 全局栈必须只有本线程的 figure
    time.sleep(hold)
    in_flight = len(plt.get_fignums())
    fig.savefig(out_path)
    plt.close(fig)
    return marker, in_flight


def test_locked_chart_sees_only_own_figure(tmp_path):
    """锁内出图时全局 figure 栈只能看到自己的 figure（互斥证据）。"""
    marker, in_flight = _slow_chart("solo", tmp_path / "solo.png")
    assert marker == "solo"
    assert in_flight == 1  # 只有本线程的 figure


def test_concurrent_locked_charts_never_share_figure_stack(tmp_path):
    """双线程并发受锁出图：任一线程锁内都只见自己的 figure。"""
    results: list[tuple[str, int]] = []
    lock = threading.Lock()

    def worker(name: str):
        r = _slow_chart(name, tmp_path / f"{name}.png", hold=0.2)
        with lock:
            results.append(r)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, f"chart-{i}") for i in range(2)]
        for f in futures:
            f.result(timeout=10)

    # 两个图都成功且各自锁内只见 1 个 figure——若无线程互斥，
    # 后启动的线程会看到 2 个在途 figure（前者尚未 close）
    assert len(results) == 2
    for _name, in_flight in results:
        assert in_flight == 1
    # 全部结束：全局栈清空
    assert plt.get_fignums() == []


def test_plot_lock_is_really_serializing(tmp_path):
    """锁串行化的行为证据：慢图持锁期间新线程必须等待。"""
    entered: list[str] = []
    order: list[str] = []

    @locked_plot
    def _chart(name: str, hold: float):
        entered.append(name)
        time.sleep(hold)
        order.append(name)
        fig = plt.figure()
        plt.close(fig)
        return name

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_chart, "first", 0.25)
        time.sleep(0.05)  # 确保 first 先拿锁
        f2 = pool.submit(_chart, "second", 0.01)
        assert f1.result(timeout=10) == "first"
        assert f2.result(timeout=10) == "second"

    # first 完整持锁区间内 second 未进入（串行证据）
    assert entered == ["first", "second"]
    assert order == ["first", "second"]
