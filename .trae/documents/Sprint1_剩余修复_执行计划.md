# Sprint 1 剩余修复执行计划（1.4 → 1.1 → 1.3 + 验证）

> 本计划聚焦 Sprint 1 剩余 3 项阻断性修复。Sprint 1 共 7 项，前 4 项（1.7/1.2/1.6/1.5）已在上一会话完成并核验。
>
> **本计划修正 v2 方案 Sprint 1.4 的 2 处假阳性**（与之前 physics.py `import math` 同类错误）：
> 1. v2 称 omega.py 可用 `logger.debug(...)` — 实际 omega.py **无** `logging` 导入，需新增模块级 logger
> 2. v2 称 L1106 可用 `np.isfinite(porosity)` — 实际 `ddca_single_temp` 函数作用域 **无** `np`（np 仅在嵌套 `cost_func` L1090 内导入），需新增函数级 `import numpy as np`
>
> **执行顺序**：1.4 → 1.1 → 1.3（从复杂到简单，先解决有 v2 修正的项），每项独立 commit。
>
> **分支**：`dev`（最新 commit `f92e200`），不直接动 `main`。

---

## 当前状态（2026-07-18 直接读文件核验）

| 编号 | 文件 | 状态 | 核验方式 |
|------|------|------|----------|
| 1.7 | `weatherengine/service.py` L4 | ✅ 已完成（`from typing import Any` 已在 L4） | 直接读文件 |
| 1.2 | `layer_router.py` L4 | ✅ 已完成（`status` 已在 L4 import 末尾） | 直接读文件 |
| 1.6 | `physics.py` L3 + `_safe_sqrt` | ✅ 已完成（`import math` 在 L3，`_safe_sqrt` 已新增） | 直接读文件 |
| 1.5 | `ndvi.py` L81-89 | ✅ 已完成（`sg_days.size < sg_window_length` 降级已加） | 直接读文件 |
| 1.4 | `omega.py` | ⏳ 待实施（3 处修复，含 v2 方案修正） | 直接读文件 |
| 1.1 | `inversion.py` | ⏳ 待实施（2 处签名修复，沿用 v2） | 直接读文件 |
| 1.3 | `weather_providers_repository.py` | ⏳ 待实施（`_encrypt` fail-fast，沿用 v2） | 直接读文件 |

---

## 1.4 omega.py porosity 未验证致 least_squares 崩溃

**文件**：[Code/algorithms/providers/Python/algorithms/omega.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/algorithms/omega.py)

**核验结论**：
- L5：`from typing import Any` ✅
- L24：`_MINERAL_PARTICLE_DENSITY = 2.65` ✅
- L1063-1114：`ddca_single_temp` 函数，L1084 `from scipy.optimize import least_squares`，L1089-1090 嵌套 `cost_func` 内 `import numpy as np`
- L1106-1114：`lower_bounds = (0.02, 0.0)` / `upper_bounds = (porosity, 5.0)` / `least_squares(...)` / `return float(result.x[0]), float(result.x[1])` ✅
- L2039：`porosity = 1.0 - float(bulk_density_value) / _MINERAL_PARTICLE_DENSITY`（无前置校验）✅
- L2040：`retrieved_indices = np.flatnonzero(valid_tau & np.isfinite(omega))`（np 在此函数作用域可用）✅
- **omega.py 全文无 `import logging`，无 `logger =`**（`findstr /n "logging" omega.py` 返回 Exit 1 无匹配）
- **omega.py 全文无模块级 `import numpy`**（所有 `import numpy as np` 均在函数内部，共 20+ 处）

**v2 方案错误修正**：
| v2 原文 | 实际情况 | 修正措施 |
|---------|----------|----------|
| `logger.debug("Skip porosity computation...")` | omega.py 无 logger | 新增模块级 `import logging` + `logger = logging.getLogger(__name__)` |
| `if not np.isfinite(porosity)...`（L1106 处） | `ddca_single_temp` 作用域无 np | 在 L1084 后新增 `import numpy as np` |
| "np 已在文件顶部导入" | np 全部在函数级导入 | 删除 v2 此说明，改为函数级导入 |

### 修复 1：模块级新增 logging + logger

**目的**：为 L2039 的 `logger.debug` 提供符号；同时与 `weather_providers_repository.py`、`ndvi.py` 等文件风格一致。

`old_string`（L3-5）：
```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
```

`new_string`：
```python
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)
```

### 修复 2：L24 后新增命名常量

`old_string`（L23-24）：
```python
# 矿物土壤颗粒密度 (g/cm³)，用于孔隙度计算 porosity = 1 - bulk_density / particle_density
_MINERAL_PARTICLE_DENSITY = 2.65
```

`new_string`：
```python
# 矿物土壤颗粒密度 (g/cm³)，用于孔隙度计算 porosity = 1 - bulk_density / particle_density
_MINERAL_PARTICLE_DENSITY = 2.65

# ─── 反演边界与有效性阈值（无量纲） ─────────────────────────────────────────
# 残余/最小土壤含水率下限（m³/m³），least_squares lower_bound
_SOIL_MOISTURE_LOWER_BOUND = 0.02
# 茂密森林 tau 上限（无量纲），least_squares upper_bound
_TAU_UPPER_BOUND = 5.0
# 孔隙度物理下限（无量纲），低于此值视为 bulk_density 异常，跳过像素
_POROSITY_MIN_REASONABLE = 0.02
```

### 修复 3：`ddca_single_temp` 新增函数级 np 导入

**目的**：L1106 的 porosity 校验需用 `np.isfinite`，但 np 仅在嵌套 `cost_func` L1090 内导入。在 `ddca_single_temp` 作用域新增导入，与文件约定一致。

`old_string`（L1084-1090，含足够上下文保证唯一）：
```python
    from scipy.optimize import least_squares

    if model_context is None:
        model_context = _build_tb_forward_context(freq_ghz, clay_fraction, theta_deg)

    def cost_func(x: Any) -> Any:
        import numpy as np
```

`new_string`：
```python
    from scipy.optimize import least_squares
    import numpy as np

    if model_context is None:
        model_context = _build_tb_forward_context(freq_ghz, clay_fraction, theta_deg)

    def cost_func(x: Any) -> Any:
        import numpy as np
```

**说明**：保留 `cost_func` 内的 `import numpy as np`（冗余但无害，最小化改动）。`_build_tb_forward_context` + `model_context is None` 组合保证 old_string 唯一。

### 修复 4：L1106-1114 替换魔法数字 + 前置 porosity 校验

`old_string`（L1106-1114）：
```python
    lower_bounds = (0.02, 0.0)
    upper_bounds = (porosity, 5.0)
    result = least_squares(
        cost_func,
        x0=[0.20, tau_ini],
        bounds=(lower_bounds, upper_bounds),
        jac=lambda x: _finite_difference_jacobian(x, cost_func, lower_bounds, upper_bounds),
    )
    return float(result.x[0]), float(result.x[1])
```

`new_string`：
```python
    if not np.isfinite(porosity) or porosity <= _SOIL_MOISTURE_LOWER_BOUND:
        # 孔隙度无效时 least_squares 会因 bounds 不合理抛 ValueError，直接返回 NaN
        return float("nan"), float("nan")
    lower_bounds = (_SOIL_MOISTURE_LOWER_BOUND, 0.0)
    upper_bounds = (porosity, _TAU_UPPER_BOUND)
    result = least_squares(
        cost_func,
        x0=[0.20, tau_ini],
        bounds=(lower_bounds, upper_bounds),
        jac=lambda x: _finite_difference_jacobian(x, cost_func, lower_bounds, upper_bounds),
    )
    return float(result.x[0]), float(result.x[1])
```

### 修复 5：L2039 porosity 计算前增加 bulk_density 校验

`old_string`（L2039-2040）：
```python
        porosity = 1.0 - float(bulk_density_value) / _MINERAL_PARTICLE_DENSITY
        retrieved_indices = np.flatnonzero(valid_tau & np.isfinite(omega))
```

`new_string`：
```python
        if not np.isfinite(bulk_density_value) or bulk_density_value <= 0:
            logger.debug("Skip porosity computation: invalid bulk_density=%r", bulk_density_value)
            porosity = float("nan")
        else:
            porosity = 1.0 - float(bulk_density_value) / _MINERAL_PARTICLE_DENSITY
            if porosity <= _POROSITY_MIN_REASONABLE:
                logger.debug("Unrealistic porosity=%r (bulk_density=%r)", porosity, bulk_density_value)
                porosity = float("nan")
        retrieved_indices = np.flatnonzero(valid_tau & np.isfinite(omega))
```

**说明**：L2040 的 `np.flatnonzero` + `np.isfinite(omega)` 已能正常工作（np 在此函数作用域可用），只需保证 `porosity` 流入下游 `ddca_dual_temp(...)` 时若为 NaN 不会触发 least_squares 崩溃。下游 `ddca_dual_temp` 内部调用 `ddca_single_temp`（L1063），修复 4 已在 `ddca_single_temp` 入口拦截 NaN porosity。

### 验证

```bash
cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python"
python -c "
import numpy as np
from algorithms.omega import (
    _SOIL_MOISTURE_LOWER_BOUND,
    _TAU_UPPER_BOUND,
    _POROSITY_MIN_REASONABLE,
    _MINERAL_PARTICLE_DENSITY,
    ddca_single_temp,
)
import logging
assert logging.getLogger('algorithms.omega') is not None
print(f'Constants OK: lower={_SOIL_MOISTURE_LOWER_BOUND}, tau_upper={_TAU_UPPER_BOUND}, porosity_min={_POROSITY_MIN_REASONABLE}')

# NaN porosity 应返回 (nan, nan) 而非抛 ValueError
sm, vod = ddca_single_temp(
    tbv=280.0, tbh=270.0, ts=290.0, tau_ini=0.3,
    h_value=0.1, clay_fraction=0.2, omega_value=0.1,
    porosity=float('nan'), freq_ghz=1.4, theta_deg=40.0,
    alpha_value=0.1, lambda_tau=20.0,
)
assert np.isnan(sm) and np.isnan(vod), f'Expected NaN for invalid porosity, got ({sm}, {vod})'
print('ddca_single_temp NaN-porosity guard OK')

# 过小 porosity 同样拦截
sm, vod = ddca_single_temp(
    tbv=280.0, tbh=270.0, ts=290.0, tau_ini=0.3,
    h_value=0.1, clay_fraction=0.2, omega_value=0.1,
    porosity=0.01, freq_ghz=1.4, theta_deg=40.0,
    alpha_value=0.1, lambda_tau=20.0,
)
assert np.isnan(sm) and np.isnan(vod), f'Expected NaN for too-small porosity, got ({sm}, {vod})'
print('ddca_single_temp small-porosity guard OK')
"
```

**Commit**：`fix(algorithms): validate porosity before least_squares to prevent ValueError on bad bulk_density`

---

## 1.1 inversion.py grid→pixel 签名不匹配

**文件**：[Code/algorithms/providers/Python/algorithms/inversion.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/algorithms/inversion.py)

**核验结论**：✅ v2 描述完全正确，沿用 v2
- L4：`import math` ✅；L5：`from typing import Any` ✅
- L29-32：`TbModelContext` dataclass 定义 ✅
- L244-254：`retrieve_dynamic_h_pixel` 签名末尾 `theta_deg: float,` → `) -> float:`，不接受 `model_context`
- L268：`model_context = build_tb_model_context(freq_ghz, clay_fraction, theta_deg)`（局部变量）
- L283-294：`ddca_retrieve_pixel` 签名末尾 `theta_deg: float,` → `) -> tuple[float, float]:`，不接受 `model_context`
- L303：`model_context = build_tb_model_context(freq_ghz, clay_fraction, theta_deg)`（局部变量）
- L378-389 / L458-472：grid 版本调用传 `model_context=context_cache[key]` → TypeError

### 修复 1：`retrieve_dynamic_h_pixel` 签名 + 内部复用

`old_string`（L244-268 关键部分）：
```python
def retrieve_dynamic_h_pixel(
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    clay_fraction: float,
    albedo: float,
    porosity: float,
    freq_ghz: float,
    theta_deg: float,
) -> float:
    """单像素动态 h 粗糙度反演。

    量纲: 输入 tbv/tbh/ts 单位 K，freq_ghz 单位 GHz，theta_deg 单位度 (°)，
    其余无量纲。返回 h_value 无量纲（粗糙度参数）。
    """
    from scipy.optimize import least_squares

    if any(
        _is_nan(value)
        for value in [tbv, tbh, ts, tau_ini, clay_fraction, albedo, porosity, theta_deg]
    ):
        return float("nan")

    model_context = build_tb_model_context(freq_ghz, clay_fraction, theta_deg)
```

`new_string`：
```python
def retrieve_dynamic_h_pixel(
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    clay_fraction: float,
    albedo: float,
    porosity: float,
    freq_ghz: float,
    theta_deg: float,
    model_context: TbModelContext | None = None,
) -> float:
    """单像素动态 h 粗糙度反演。

    量纲: 输入 tbv/tbh/ts 单位 K，freq_ghz 单位 GHz，theta_deg 单位度 (°)，
    其余无量纲。返回 h_value 无量纲（粗糙度参数）。
    可选 model_context 由调用方预计算以避免重复开销（grid 版本使用）。
    """
    from scipy.optimize import least_squares

    if any(
        _is_nan(value)
        for value in [tbv, tbh, ts, tau_ini, clay_fraction, albedo, porosity, theta_deg]
    ):
        return float("nan")

    if model_context is None:
        model_context = build_tb_model_context(freq_ghz, clay_fraction, theta_deg)
```

### 修复 2：`ddca_retrieve_pixel` 签名 + 内部复用

`old_string`（L283-303 关键部分）：
```python
def ddca_retrieve_pixel(
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    h_value: float,
    clay_fraction: float,
    albedo: float,
    porosity: float,
    freq_ghz: float,
    theta_deg: float,
) -> tuple[float, float]:
    from scipy.optimize import least_squares

    if any(
        _is_nan(value)
        for value in [tbv, tbh, ts, tau_ini, h_value, clay_fraction, albedo, porosity, theta_deg]
    ):
        return float("nan"), float("nan")

    model_context = build_tb_model_context(freq_ghz, clay_fraction, theta_deg)
```

`new_string`：
```python
def ddca_retrieve_pixel(
    tbv: float,
    tbh: float,
    ts: float,
    tau_ini: float,
    h_value: float,
    clay_fraction: float,
    albedo: float,
    porosity: float,
    freq_ghz: float,
    theta_deg: float,
    model_context: TbModelContext | None = None,
) -> tuple[float, float]:
    from scipy.optimize import least_squares

    if any(
        _is_nan(value)
        for value in [tbv, tbh, ts, tau_ini, h_value, clay_fraction, albedo, porosity, theta_deg]
    ):
        return float("nan"), float("nan")

    if model_context is None:
        model_context = build_tb_model_context(freq_ghz, clay_fraction, theta_deg)
```

**说明**：grid 函数（L376-389、L458-472）无需改动，已正确传递 `model_context=context_cache[key]`。`TbModelContext` 已在 L29-32 定义，`from typing import Any` 已在 L5，无需新增 import。

### 验证

```bash
cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python"
python -c "
from algorithms.inversion import retrieve_dynamic_h_pixel, ddca_retrieve_pixel
import inspect
sig1 = inspect.signature(retrieve_dynamic_h_pixel)
sig2 = inspect.signature(ddca_retrieve_pixel)
assert 'model_context' in sig1.parameters, 'retrieve_dynamic_h_pixel missing model_context'
assert 'model_context' in sig2.parameters, 'ddca_retrieve_pixel missing model_context'
assert sig1.parameters['model_context'].default is None
assert sig2.parameters['model_context'].default is None
print('OK: both pixel functions accept model_context=None')
"
```

**Commit**：`fix(algorithms): accept model_context param in pixel-level inversion functions to fix TypeError in grid path`

---

## 1.3 weather_providers_repository.py 加密静默降级

**文件**：[Code/backend/app/services/weather_providers_repository.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/weather_providers_repository.py)

**核验结论**：✅ v2 描述正确，沿用 v2
- L30：`import logging` ✅；L36：`logger = logging.getLogger(__name__)` ✅
- L45：`def __init__(self, db_path: str | Path, encryption_key: str = "") -> None:` ✅
- L79-97：`_encrypt` 三处静默返回明文（L80-81 无 key / L92-94 ImportError / L95-97 Exception）
- L27-34 imports：无 `from app.services.effective_config import`（采用方法内 lazy import，与 `gee_credentials_repository` 一致，避免循环依赖）
- `api_keys_repository` 和 `gee_credentials_repository` 不动（已正确实现）

### 修复：`_encrypt` 改为 fail-fast 模式

`old_string`（L79-97 完整 `_encrypt` 方法）：
```python
    def _encrypt(self, plaintext: str) -> tuple[str, str]:
        if not self._encryption_key:
            return plaintext, ""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
            import base64
            import os

            key_bytes = bytes.fromhex(self._encryption_key)
            iv = os.urandom(12)
            aesgcm = AESGCM(key_bytes)
            ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
            return base64.b64encode(ct).decode("ascii"), base64.b64encode(iv).decode("ascii")
        except ImportError:
            logger.warning("cryptography not installed, storing weather provider config as plaintext")
            return plaintext, ""
        except Exception as e:
            logger.error("Encryption failed for weather provider config: %s", e)
            return plaintext, ""
```

`new_string`：
```python
    def _encrypt(self, plaintext: str) -> tuple[str, str]:
        """AES-GCM 加密，返回 (ciphertext_b64, iv_b64)。无 key 时仅 development 允许明文。"""
        if not self._encryption_key:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError(
                    "Cannot store weather provider config without BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY "
                    "outside development."
                )
            logger.error("Weather provider encryption key not set, storing plaintext (development only)")
            return plaintext, ""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
            import base64
            import os

            key_bytes = bytes.fromhex(self._encryption_key)
            iv = os.urandom(12)
            aesgcm = AESGCM(key_bytes)
            ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
            return base64.b64encode(ct).decode("ascii"), base64.b64encode(iv).decode("ascii")
        except ImportError:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError("cryptography package required to encrypt weather provider config") from None
            logger.warning("cryptography not installed, storing plaintext")
            return plaintext, ""
        except RuntimeError:
            raise
        except Exception as e:
            from app.services.effective_config import secrets_encryption_required

            if secrets_encryption_required():
                raise RuntimeError(f"Encryption failed for weather provider config: {e}") from e
            logger.error("Encryption failed for weather provider config, storing plaintext: %s", e)
            return plaintext, ""
```

**说明**：
- 完全复用 `gee_credentials_repository._encrypt` 的代码结构（仅修改日志措辞和异常消息）
- `except RuntimeError: raise` 防止被后面的 `except Exception` 吞掉
- 采用方法内 lazy import `secrets_encryption_required`（与 `gee_credentials_repository` 一致，避免循环依赖）
- **不改 `_decrypt`**（L99-113）：`_decrypt` 在无 key 时返回密文比 `_encrypt` 返回明文风险低，留到 Sprint 3 统一 review

### 验证

```bash
cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend"
# 1. 确认 import 无误
python -c "from app.services.weather_providers_repository import WeatherProvidersRepository; print('OK: import clean')"

# 2. 确认 development 环境无 key 时降级为明文（不抛异常）
python -c "
import os
os.environ['BACKEND_ENVIRONMENT'] = 'development'
from app.services.weather_providers_repository import WeatherProvidersRepository
import tempfile, pathlib
repo = WeatherProvidersRepository(pathlib.Path(tempfile.mkdtemp()) / 'test.db', encryption_key='')
ct, iv = repo._encrypt('secret-value')
assert ct == 'secret-value' and iv == '', f'Expected plaintext fallback, got ({ct!r}, {iv!r})'
print('OK: development plaintext fallback works')
"

# 3. 确认生产环境无 key 时抛 RuntimeError
python -c "
import os
os.environ['BACKEND_ENVIRONMENT'] = 'production'
from app.services.weather_providers_repository import WeatherProvidersRepository
import tempfile, pathlib
repo = WeatherProvidersRepository(pathlib.Path(tempfile.mkdtemp()) / 'test.db', encryption_key='')
try:
    repo._encrypt('secret-value')
    print('FAIL: should have raised RuntimeError')
except RuntimeError as e:
    print(f'OK: production raises RuntimeError: {e}')
"
```

**Commit**：`fix(security): fail-fast on weather provider config encryption in production, matching gee/api_keys repos`

---

## Sprint 1 完成后整体验证清单

### 1. 语法编译检查

```bash
# 后端
cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend"
python -m py_compile app/api/routers/layer_router.py app/services/weather_providers_repository.py app/weatherengine/service.py

# 算法
cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python"
python -m py_compile algorithms/inversion.py algorithms/omega.py algorithms/ndvi.py algorithms/physics.py
```

### 2. 导入与签名检查（单条命令）

```bash
cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend"
python -c "
# 后端
from app.api.routers.layer_router import router
print('1. layer_router OK')
from app.services.weather_providers_repository import WeatherProvidersRepository
print('2. WeatherProvidersRepository OK')
from app.weatherengine.service import WeatherEngineService
print('3. WeatherEngineService OK')
from app.services.effective_config import secrets_encryption_required, assert_encryption_policy
print('4. effective_config OK')
"

cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python"
python -c "
# 算法
from algorithms.inversion import retrieve_dynamic_h_pixel, ddca_retrieve_pixel
import inspect
assert 'model_context' in inspect.signature(retrieve_dynamic_h_pixel).parameters
assert 'model_context' in inspect.signature(ddca_retrieve_pixel).parameters
print('5. inversion signatures OK')

from algorithms.physics import _safe_sqrt
assert _safe_sqrt(-1e-20) == 0.0
print('6. _safe_sqrt OK')

from algorithms.omega import _SOIL_MOISTURE_LOWER_BOUND, _TAU_UPPER_BOUND, _POROSITY_MIN_REASONABLE
print('7. omega constants OK')

import numpy as np
from datetime import datetime, timedelta
from algorithms.ndvi import vi_sg_interpolate, build_datetime_sequence, to_day_numbers
obs = [datetime(2024,1,1)+timedelta(days=i*8) for i in range(5)]
data = np.array([0.3,0.4,0.5,0.45,0.55])
sg = build_datetime_sequence(datetime(2024,1,1), datetime(2024,1,5), 8)
out = build_datetime_sequence(datetime(2024,1,1), datetime(2024,1,5), 1)
r = vi_sg_interpolate(data, to_day_numbers(obs), to_day_numbers(sg), to_day_numbers(out))
assert r.shape == out.shape
print('8. ndvi short-window fallback OK')
"
```

### 3. 端到端验证（可选，启动后端后）

1. 启动后端：`python launch.py start fastapi`
2. 验证 layer_router：`curl "http://localhost:8000/api/layers/geo/transform?lng=113&lat=23&source=EPSG:9999&target=EPSG:4326"` → 应返回 400（而非 500 NameError）
3. 在 Settings → Weather Providers 添加 Provider，检查 DB 中 `config_encrypted` 非明文（生产）或正确降级（开发）
4. 跑一次天气图层生成，确认无 TypeError from inversion
5. 跑一次 NDVI 反演（短时间窗），确认无 savgol_filter ValueError

### 4. Git 提交策略

- 每项修复独立 commit（共 3 个 commit）
- commit message 使用英文（与项目历史一致，避免 Celery 非 ASCII 元数据问题）
- commit 后不自动 push，等用户确认
- **commit 前必须** `git status` 检查，避免 `git add -A` 误暂存 `.data/` 运行时文件

---

## 假设与决策

1. **决策**：Sprint 1.4 新增模块级 `import logging` + `logger`，而非移除 `logger.debug` 调用。理由：与项目其他算法/服务文件风格一致，且生产环境调试需要日志。
2. **决策**：Sprint 1.4 在 `ddca_single_temp` 新增函数级 `import numpy as np`，而非改为 `math.isfinite`。理由：与 omega.py 现有 20+ 处函数级 np 导入约定一致；`np.isfinite` 对 NaN/inf 的语义更明确。
3. **决策**：Sprint 1.4 保留 `cost_func` 内的冗余 `import numpy as np`（L1090）。理由：最小化改动，避免因删除引发意外作用域问题。
4. **决策**：Sprint 1.3 不改 `_decrypt`。理由：`_decrypt` 无 key 时返回密文比 `_encrypt` 无 key 返回明文风险低（解密失败不影响存储安全），留到 Sprint 3 统一 review。
5. **假设**：grid 版本的 `retrieve_dynamic_h_grid` / `ddca_retrieve_grid` 已正确传递 `model_context=context_cache[key]`（v2 已核验 L378-389 / L458-472，本计划不重复核验）。
6. **假设**：`launch.py start fastapi` 命令可用（上一会话已确认服务正常运行于端口 8000）。
7. **分支策略**：所有 commit 到 `dev` 分支，不直接动 `main`，不自动 push。

---

## 不在本计划范围内（后续 Sprint）

以下内容明确不在本计划内，避免范围蔓延：

- Sprint 2：ndvi 向量化、block_inversion 优化、WeatherEngineService 拆分、SQLite 连接池、remote_storage 原子性、config_service async 化、前端死调试代码清理
- Sprint 3：`_decrypt` 静默降级统一 review、omega.py `pixel_chunk_size` 清理、mypy/pre-commit 配置
- Sprint 4：前端 lint 脚本、测试覆盖、CI/CD
- **v3 方案中的 "Sprint 1 补充项 — 启动时强制加密策略"** 已确认为假阳性（`main.py` L79 + `effective_config.py` L72 已实现），不实施
