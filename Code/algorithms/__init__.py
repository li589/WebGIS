"""算法顶层包：聚合 adapters / providers / registry 与 provider 内核算法模块。

当 ``Code`` 根目录先于 provider 根目录进入 ``sys.path`` 时（如后端 pytest 的
conftest），本包会遮蔽 provider 内部的同名内核包
（``providers/Python/algorithms/``，含 omega / smap / ndvi / physics 等科学核），
导致 ``from algorithms.omega import ...`` 报 ``No module named 'algorithms.omega'``。
这里把内核目录追加到本包 ``__path__``，两种 sys.path 布局下均可解析。
"""

from pathlib import Path as _Path

_provider_kernels = (
    _Path(__file__).resolve().parent / "providers" / "Python" / "algorithms"
)
if _provider_kernels.is_dir():
    __path__.append(str(_provider_kernels))  # type: ignore[name-defined]
