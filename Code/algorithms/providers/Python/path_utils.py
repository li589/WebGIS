"""跨平台安全的本地路径 → file:// URI 工具（算法包顶层模块）。

算法包内多处用 ``Path.resolve().as_uri()`` 生成产物/资源 URI。在非 Windows 平台
遇到 Windows 盘符路径字符串（如从配置/工作流参数序列化来的 ``D:\\foo``）时，
``Path.resolve()`` 会误判为相对路径，产出错误 URI。本模块提供统一的安全转换，
供 publish / data_access / storage / modules / interfaces 共用，闭合审查 CC-4。

为何放在顶层而非 ``service/`` 下：``service/__init__.py`` 在包导入时拉起
``job_api`` → ``contracts.api_errors`` → ``contracts.serialization`` 重链，
而 ``interfaces/datasource`` 等模块在导入序列极早期被 ``runner.dispatch`` 引用，
从 ``service`` 子包导入会命中 ``contracts.serialization`` 半初始化窗口触发循环
导入。顶层模块无 ``__init__``，不触发任何包初始化，可被任意层安全导入。

设计要点：
- Windows 盘符路径（``D:\\foo`` / ``D:/foo``）仅在**非 Windows 平台**手动构造
  ``file:///D:/foo``（Windows 原生 ``as_uri()`` 已正确处理盘符，手动分支反而绕过
  resolve 与原行为不一致；非 Windows 上 ``resolve()`` 会把盘符路径当相对路径破坏）。
- 其余路径 → ``Path.as_uri()``；``resolve=True`` 时先 ``resolve()``，与原
  ``path.resolve().as_uri()`` 行为一致。调用点按原写法选择 ``resolve`` 取值，
  避免引入新的行为差异（如 Windows 8.3 短名规范化）。
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["local_path_to_uri"]


def _looks_like_windows_drive_path(value: str) -> bool:
    """检测 ``D:\\`` / ``D:/`` 形式的 Windows 盘符绝对路径。"""
    return len(value) >= 3 and value[1] == ":" and value[2] in ("\\", "/")


def local_path_to_uri(path: Path | str, *, resolve: bool = False) -> str:
    """将本地路径转为跨平台安全的 ``file://`` URI。

    Args:
        path: 本地路径（``Path`` 或字符串）。跨平台序列化路径字符串（如
            从配置/工作流参数读到的 ``D:\\data\\foo.tif``）应直接传入，**不要**
            先 ``resolve()``——非 Windows 平台的 ``resolve()`` 会把盘符路径当相对
            路径破坏掉，本函数靠原始字符串识别盘符并手动构造 URI。
        resolve: 是否在非盘符分支先 ``resolve()``。原调用点用
            ``path.resolve().as_uri()`` 的传 ``True``（解析符号链接、相对路径转绝对）；
            用裸 ``as_uri()`` 的传 ``False``（默认），以保持各自行为不变。

    Returns:
        形如 ``file:///D:/foo/bar.tif`` 或 ``file:///abs/path`` 的 URI。
    """
    s = str(path)
    if not sys.platform.startswith("win") and _looks_like_windows_drive_path(s):
        normalized = s.replace("\\", "/")
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        return "file://" + normalized
    p = Path(path).resolve() if resolve else Path(path)
    return p.as_uri()
