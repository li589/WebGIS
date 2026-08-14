# CGDA 代码库修复执行计划

> 已归档 2026-08-13，续接计划见 .trae/documents/复审与修复计划.md

> 审查日期：2026-08-13
> 审查框架：Brooks-Lint Health Dashboard + SEM architecture-decisions
> 综合健康度：67/100（架构 65 · 安全 82 · 测试 55 · 卫生 68）
> 总发现项：38 项（P0: 4 · P1: 14 · P2: 13 · P3: 7）
> 本轮：只读审查，不修改代码。以下为可执行修复方案。

---

## P0 — 阻塞级（立即修复）

### P0-1：overlay_registry.py 硬编码开发机器绝对路径

| 属性 | 值 |
|------|-----|
| 编号 | A-01 |
| 文件 | `Code/backend/app/services/overlay_registry.py` |
| 行号 | 29-30 |
| 严重度 | P0 — 其他环境完全不可用 |

**当前代码**：
```python
_PROVIDER_ROOT = Path(
    r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python"
)
```

**修复方案**：
```python
from app.core.config import settings

_PROVIDER_ROOT = Path(settings.python_provider_root)
```

若 `settings` 中无 `python_provider_root` 字段，在 `core/config.py` 的 `Settings` 类中添加：
```python
python_provider_root: str = field(
    default_factory=lambda: str(Path(__file__).resolve().parents[3] / "algorithms" / "providers" / "Python")
)
```

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_overlay_registry.py Test/backend/test_overlay_tile_service.py -q
```

---

### P0-2：weather_sync_service.py 服务层反向导入路由层

| 属性 | 值 |
|------|-----|
| 编号 | A-02 |
| 文件 | `Code/backend/app/services/weather_sync_service.py` |
| 行号 | 172 |
| 严重度 | P0 — 分层架构破坏 |

**当前代码**：
```python
from app.api.routers.weather_router import invalidate_weather_coverage_cache
```

**修复方案**：
1. 将 `invalidate_weather_coverage_cache` 函数从 `weather_router.py` 移至 `weather_sync_service.py`（或独立的 `weather_cache_service.py`）
2. `weather_router.py` 改为从 service 层导入：
```python
from app.services.weather_sync_service import invalidate_weather_coverage_cache
```

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_weather_bridge_service.py -q
```

---

### P0-3：CI 后端覆盖率阈值 50% 过低

| 属性 | 值 |
|------|-----|
| 编号 | C-01 |
| 文件 | `.github/workflows/ci.yml` |
| 行号 | 101 |
| 严重度 | P0 — 测试质量门禁形同虚设 |

**当前代码**：
```yaml
--cov-fail-under=50
```

**修复方案**（分阶段提升）：
```yaml
# 第一阶段：提升至 55%（立即执行）
--cov-fail-under=55
# 第二阶段：补测后提升至 60%（1-2 周内）
--cov-fail-under=60
# 第三阶段：提升至 70%（1 个月内）
--cov-fail-under=70
```

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend --cov=app --cov-report=term-missing -q
```

---

### P0-4：CI 无前端覆盖率阈值

| 属性 | 值 |
|------|-----|
| 编号 | C-02 |
| 文件 | `.github/workflows/ci.yml` |
| 行号 | 121-123 |
| 严重度 | P0 — 前端覆盖率无量化追踪 |

**当前代码**：
```yaml
- name: Run vitest
  run: cd Code/frontend && npm run test
```

**修复方案**：
1. 在 `Code/frontend/package.json` 中添加 coverage 脚本：
```json
"test:coverage": "vitest run --coverage"
```
2. 在 `vite.config.ts` 中配置 coverage：
```typescript
test: {
  coverage: {
    provider: 'v8',
    reporter: ['text', 'lcov'],
    thresholds: {
      lines: 40,  // 起步阈值，后续逐步提升
      statements: 40,
      branches: 35,
      functions: 40,
    },
  },
}
```
3. CI 中替换为 `npm run test:coverage`

**验证命令**：
```powershell
cd Code/frontend && npm run test:coverage
```

---

## P1 — 高优先级（本轮或下轮迭代修复）

### P1-1：weather-tile-manager.ts 14 职责 God Store 拆分

| 属性 | 值 |
|------|-----|
| 编号 | A-03 |
| 文件 | `Code/frontend/src/stores/weather-tile-manager.ts` |
| 行号 | 1-1948（全文） |
| 严重度 | P1 — 测试隔离问题 + 脆弱响应式模式 |

**修复方案**：按职责拆分为 4 个子模块：

| 新文件 | 职责 | 来源行号 |
|--------|------|---------|
| `tile-cache.ts` | SWR 缓存 + LRU trim + merge cache | 74-79, 407-408, 637-657 |
| `tile-concurrency.ts` | 全局并发槽位 + round-robin + generation 取消 | 7-8, 259-267 |
| `tile-scheduler.ts` | 四级优先级队列 + 视口排序 + gap sweep | 101-106, 469-545 |
| `tile-error-handler.ts` | 错误分类 + 退避重试 + soft requeue + 断路器 | 86-100, 301-331 |

`weather-tile-manager.ts` 保留为编排层，组合 4 个子模块。

**验证命令**：
```powershell
cd Code/frontend && npm run test -- weather-tile
```

---

### P1-2：overlay_registry.py 非线程安全注册表加锁

| 属性 | 值 |
|------|-----|
| 编号 | A-04 |
| 文件 | `Code/backend/app/services/overlay_registry.py` |
| 行号 | 625-997（17 处 register_overlay 调用） |
| 严重度 | P1 — 并发竞态 |

**修复方案**：
```python
import threading

_REGISTRY_LOCK = threading.Lock()
_REGISTRY: dict[str, OverlaySpec] = {}

def register_overlay(spec: OverlaySpec) -> None:
    with _REGISTRY_LOCK:
        _REGISTRY[spec.overlay_id] = spec

def get_overlay_spec(overlay_id: str) -> OverlaySpec | None:
    with _REGISTRY_LOCK:
        return _REGISTRY.get(overlay_id)

def list_overlay_ids() -> list[str]:
    with _REGISTRY_LOCK:
        return list(_REGISTRY.keys())
```

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_overlay_registry.py -q
```

---

### P1-3：workflow_request_resolver.py lru_cache 添加失效机制

| 属性 | 值 |
|------|-----|
| 编号 | A-05 |
| 文件 | `Code/backend/app/services/workflow_request_resolver.py` |
| 行号 | 188, 1031, 1115 |
| 严重度 | P1 — 缓存陈旧导致数据不一致 |

**修复方案**：
```python
# 方案 A：暴露 cache_clear 为 admin API
def invalidate_template_cache() -> None:
    """Call after modifying provider templates."""
    _load_module_template_map.cache_clear()
    _resolve_provider_dataset_path.cache_clear()
    _load_provider_dataset_helpers.cache_clear()

# 方案 B：使用带 TTL 的缓存（推荐）
from functools import lru_cache
import time

_CACHE_TTL = 300  # 5 分钟

_cached_template_map = None
_cached_template_map_time = 0

def _load_module_template_map():
    global _cached_template_map, _cached_template_map_time
    now = time.monotonic()
    if _cached_template_map is None or (now - _cached_template_map_time) > _CACHE_TTL:
        _cached_template_map = _do_load_module_template_map()
        _cached_template_map_time = now
    return _cached_template_map
```

在 `config_routes.py` 中添加 admin 端点：
```python
@router.post("/config/cache/invalidate-templates")
async def invalidate_templates(_: str = Depends(require_config_management_access)):
    from app.services.workflow_request_resolver import invalidate_template_cache
    invalidate_template_cache()
    return {"status": "ok"}
```

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_workflow_graph_compiler.py -q
```

---

### P1-4：weather_render_service.py 6 个重复方法统一

| 属性 | 值 |
|------|-----|
| 编号 | A-06 |
| 文件 | `Code/backend/app/weatherengine/weather_render_service.py` |
| 行号 | 1054-1455 |
| 严重度 | P1 — 维护时需同步修改 7 处 |

**修复方案**：删除 6 个特化方法，统一调用已有的通用方法：

```python
# 删除以下方法：
# - build_dewpoint_geojson_from_grid (行 1383)
# - build_humidity_geojson_from_grid (行 1121)
# - build_pressure_geojson_from_grid (行 1188)
# - build_visibility_geojson_from_grid (行 1253)
# - build_precipitation_geojson_from_grid (行 1054)
# - build_temperature_geojson (行 441) — 部分逻辑不同，需检查

# 保留并使用通用方法：
def build_scalar_geojson_from_grid(self, grid_data, field_name, ...):
    """通用标量场 GeoJSON 构建（行 1455 已存在）"""
    ...

# 调用方修改：
# 原: build_humidity_geojson_from_grid(grid, ...)
# 改: build_scalar_geojson_from_grid(grid, "humidity", ...)
```

注意：`build_wind_geojson_from_grid`（162 行）因含 Hellmann 幂律外推逻辑，保留但提取外推为独立函数。

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_weatherengine_service.py Test/backend/test_weather_tile_service.py -q
```

---

### P1-5：WorkflowCanvas.vue 抽取 composables

| 属性 | 值 |
|------|-----|
| 编号 | A-07 |
| 文件 | `Code/frontend/src/components/workflow/WorkflowCanvas.vue` |
| 行号 | 1-1890（script setup） |
| 严重度 | P1 — God Component 无法测试 |

**修复方案**：抽取以下 composables：

| 新文件 | 职责 | 来源行号 |
|--------|------|---------|
| `composables/useLiteGraphLifecycle.ts` | LiteGraph 实例创建/销毁/ResizeObserver | 1-200（估计） |
| `composables/useAlignmentGuides.ts` | 对齐辅助线 + 吸附网格 | 82-93 |
| `composables/useNodeSerialization.ts` | 序列化/反序列化 + 保存/加载 | 分布在 script 中 |
| `composables/usePortTooltip.ts` | 端口悬停提示 | 95-100 |
| `composables/useCanvasTheme.ts` | 主题同步 | 分布在 script 中 |

`WorkflowCanvas.vue` 缩减至 ≤300 行，仅组合 composables + 模板。

**验证命令**：
```powershell
cd Code/frontend && npm run build && npm run test
```

---

### P1-6：workflow-runner.ts 缩窄 DI 接口 + 补测

| 属性 | 值 |
|------|-----|
| 编号 | A-08 |
| 文件 | `Code/frontend/src/stores/layers/workflow-runner.ts` |
| 行号 | 89-161（WorkflowRunnerDeps 接口） |
| 严重度 | P1 — 30+ 方法 DI 接口 + 零测试 |

**修复方案**：
1. 将 `WorkflowRunnerDeps` 接口从 30+ 方法缩窄为 5-8 个高层方法：
```typescript
interface WorkflowRunnerDeps {
  // 状态读取
  getActiveRuns(): Map<string, WorkflowRun>
  getPoller(): WorkflowPoller
  // 状态写入
  upsertRun(run: WorkflowRun): void
  removeRun(runId: string): void
  // 业务判定
  buildPayload(submission: WorkflowSubmission): Promise<WorkflowPayload>
  shouldTrack(run: WorkflowRun): boolean
  // 恢复
  restoreSnapshot(): void
}
```
2. 将 30+ 个细粒度方法封装在 store 内部，不暴露给 runner
3. 创建 `Test/frontend/stores/layers/workflow-runner.test.ts`，覆盖核心编排路径

**验证命令**：
```powershell
cd Code/frontend && npm run test -- workflow-runner
```

---

### P1-7：WebGL shader 工具函数抽取共享模块

| 属性 | 值 |
|------|-----|
| 编号 | A-09 |
| 文件 | `components/map/wind-particle-webgl-renderer.ts:78-100` + `scalar-field-webgl-renderer.ts:18-52` |
| 严重度 | P1 — 代码重复 |

**修复方案**：
```typescript
// 新文件: components/map/webgl-utils.ts
export function compileShader(
  gl: WebGL2RenderingContext,
  type: number,
  source: string,
  label: string = 'WebGL'
): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error(`[${label}] Failed to create shader`);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const info = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    console.error(`[${label}] Shader compile error:`, info);
    throw new Error(`[${label}] Shader compile failed: ${info}`);
  }
  return shader;
}

export function linkProgram(
  gl: WebGL2RenderingContext,
  vertexShader: WebGLShader,
  fragmentShader: WebGLShader,
  label: string = 'WebGL'
): WebGLProgram {
  const program = gl.createProgram();
  if (!program) throw new Error(`[${label}] Failed to create program`);
  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const info = gl.getProgramInfoLog(program);
    console.error(`[${label}] Program link error:`, info);
    throw new Error(`[${label}] Program link failed: ${info}`);
  }
  return program;
}

export function createProgram(
  gl: WebGL2RenderingContext,
  vsSource: string,
  fsSource: string,
  label: string = 'WebGL'
): WebGLProgram {
  const vs = compileShader(gl, gl.VERTEX_SHADER, vsSource, label);
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, fsSource, label);
  return linkProgram(gl, vs, fs, label);
}
```

两个渲染器文件改为 `import { compileShader, linkProgram } from './webgl-utils'`。

**验证命令**：
```powershell
cd Code/frontend && npm run test -- wind-particle scalar-field
```

---

### P1-8：后端 workflow/ 目录 9 个无测试模块补测

| 属性 | 值 |
|------|-----|
| 编号 | C-03 |
| 文件 | `Code/backend/app/services/workflow/` |
| 严重度 | P1 — 核心业务路径无覆盖 |

**修复方案**：创建以下测试文件，每个至少 3 个测试（正常/边界/异常）：

| 测试文件 | 被测模块 | 测试要点 |
|---------|---------|---------|
| `test_workflow_execution.py` | `workflow_execution.py` | 执行入口、异常传播 |
| `test_lifecycle_service.py` | `lifecycle_service.py` (555行) | 状态转换、终态处理 |
| `test_persistence_service.py` | `persistence_service.py` | 持久化、恢复 |
| `test_follow_up_dispatch.py` | `follow_up_dispatch_service.py` | 后续调度逻辑 |
| `test_retry_dispatcher.py` | `retry_dispatcher.py` | 重试策略、退避 |
| `test_queue_dispatch.py` | `queue_dispatch_service.py` | 队列路由、容量管理 |
| `test_session_service.py` | `session_service.py` | 会话创建/过期/吊销 |
| `test_download_service.py` | `download_service.py` | 下载编排 |
| `test_passwords.py` | `passwords.py` | 哈希验证、常量时间比较 |

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_lifecycle_service.py Test/backend/test_session_service.py Test/backend/test_passwords.py -q
```

---

### P1-9：conftest.py 提取共享 fixture

| 属性 | 值 |
|------|-----|
| 编号 | C-04 |
| 文件 | `Test/backend/conftest.py` |
| 严重度 | P1 — 测试 setup 重复 |

**修复方案**：在 `conftest.py` 中添加共享 fixture：

```python
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.user_repository import UserRepository

@pytest.fixture
def app():
    return create_app()

@pytest.fixture
def client(app):
    return TestClient(app)

@pytest.fixture
def auth_client(app, tmp_path):
    """带鉴权的测试客户端，自动登录为 admin"""
    repo = UserRepository(str(tmp_path / "test.db"))
    # ... 创建 admin 用户
    with TestClient(app) as c:
        c.post("/auth/login", json={"username": "admin", "password": "..."})
        yield c

@pytest.fixture
def service():
    """通用服务实例 fixture"""
    # ...
```

从 `test_auth.py` 等文件中删除重复的 setup 代码。

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_auth.py -q
```

---

### P1-10：test_circuit_breaker.py 替换 time.sleep

| 属性 | 值 |
|------|-----|
| 编号 | C-05 |
| 文件 | `Test/backend/test_circuit_breaker.py` |
| 行号 | 58, 66 |
| 严重度 | P1 — flaky 测试 |

**修复方案**：
```python
# 方案 A：使用 freezegun
from freezegun import freeze_time

@freeze_time("2026-01-01 00:00:00")
def test_open_state_blocks_requests():
    breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
    # ... 触发 5 次失败
    assert breaker.state == "open"

@freeze_time("2026-01-01 00:01:01")  # 61 秒后
def test_half_open_after_timeout():
    breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
    # ... 验证 half_open 状态

# 方案 B：mock time.monotonic（无需安装 freezegun）
def test_open_state_blocks_requests(mocker):
    mock_time = mocker.patch('time.monotonic')
    mock_time.side_effect = [0, 0, 0, 0, 0, 0, 61]  # 最后一次调用模拟超时
    # ...
```

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_circuit_breaker.py -q
```

---

### P1-11：统一测试风格为 pytest

| 属性 | 值 |
|------|-----|
| 编号 | C-06 |
| 文件 | `test_workflow_routes.py`, `test_circuit_breaker.py`, `test_weather_tile_service.py` |
| 严重度 | P1 — 风格不一致 |

**修复方案**：将所有 `unittest.TestCase` 子类改为 pytest function-based 风格：

```python
# 之前:
class TestWorkflowRoutes(unittest.TestCase):
    def test_submit_workflow(self):
        self.assertEqual(response.status_code, 200)

# 之后:
def test_submit_workflow():
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
```

规则：
- 所有断言添加 message：`assert x == y, "description"`
- 使用 `pytest.raises` 替代 `self.assertRaises`
- 使用 `tmp_path` 替代 `self.tmpdir`
- 移除 `class` 包装（除非有共享 fixture 需求）

**验证命令**：
```powershell
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend -q
```

---

## P2 — 中优先级（计划迭代修复）

### P2-1：node_template_registry.py 数据外置

| 编号 | A-10 |
|------|------|
| 文件 | `Code/backend/app/services/node_template_registry.py`（3398 行） |

**修复方案**：按引擎拆分：
- `app/services/templates/weather_templates.py` — 天气节点模板
- `app/services/templates/gee_templates.py` — GEE 节点模板
- `app/services/templates/python_provider_templates.py` — Python Provider 节点模板
- `app/services/templates/common_templates.py` — 通用节点模板
- `node_template_registry.py` 保留逻辑代码（~95 行）+ 导入聚合

或外置为 JSON：`app/services/templates/*.json`，启动时加载。

---

### P2-2：data_io/api/router.py 拆分为 5 个子路由

| 编号 | A-11 |
|------|------|
| 文件 | `Code/backend/app/data_io/api/router.py`（823 行，42 端点） |

**修复方案**：
- `upload_router.py` — 文件上传端点
- `vector_router.py` — 矢量导入端点
- `raster_router.py` — 栅格提交端点
- `document_router.py` — 文档操作端点
- `export_router.py` — 导出端点

每个子路由 ≤200 行，业务逻辑下沉至 service 层。

---

### P2-3：services/import_service/ 添加 deprecation warning

| 编号 | A-12 |
|------|------|
| 文件 | `Code/backend/app/services/import_service/`（11 个文件） |

**修复方案**：在每个文件中添加：
```python
import warnings
warnings.warn(
    "app.services.import_service is deprecated; use app.data_io.services instead",
    DeprecationWarning,
    stacklevel=2,
)
```

---

### P2-4：service 层去除 HTTPException 依赖

| 编号 | A-13 |
|------|------|
| 文件 | `overlay_registry.py:25`, `tile_proxy_service.py:20`, `credential_resolver.py:11` |

**修复方案**：
1. 定义领域异常：
```python
# app/services/errors.py
class OverlayNotFoundError(Exception): pass
class TileProxyError(Exception): pass
class CredentialResolutionError(Exception): pass
```
2. Service 层抛领域异常
3. Router 层添加异常处理器：
```python
@app.exception_handler(OverlayNotFoundError)
async def overlay_not_found_handler(request, exc):
    raise HTTPException(status_code=404, detail=str(exc))
```

---

### P2-5：安全 — 源码硬编码开发凭据移至 .env

| 编号 | B-01 |
|------|------|
| 文件 | `Code/backend/app/services/auth_bootstrap.py:12,14` |

**修复方案**：
```python
# 之前:
DEV_DEFAULT_API_KEY = "cgda-dev-write-key"
DEV_DEFAULT_ADMIN_PASSWORD = "cgda-dev-admin"

# 之后:
DEV_DEFAULT_API_KEY = os.getenv("BACKEND_DEV_DEFAULT_API_KEY", "")
DEV_DEFAULT_ADMIN_PASSWORD = os.getenv("BACKEND_DEV_DEFAULT_API_KEY", "")
```

在 `.env.example` 中添加（注释 + 占位符）：
```
# Development-only defaults (DO NOT use in production)
# BACKEND_DEV_DEFAULT_API_KEY=<generate-a-secure-key>
# BACKEND_ADMIN_PASSWORD=<generate-a-secure-password>
```

---

### P2-6：.env.example 弱默认值替换为占位符

| 编号 | B-02 |
|------|------|
| 文件 | `Code/backend/.env.example:14,24,27,47` |

**修复方案**：
```
# 之前:
# BACKEND_API_KEY=cgda-dev-write-key
# BACKEND_ADMIN_PASSWORD=cgda-dev-admin

# 之后:
# BACKEND_API_KEY=<generate-with: python -c "import secrets; print(secrets.token_hex(32))">
# BACKEND_ADMIN_PASSWORD=<generate-a-strong-password>
```

---

### P2-7：Nginx 加固

| 编号 | B-03 |
|------|------|
| 文件 | `Code/infra/gateway/nginx.conf` |

**修复方案**：在 `http` 块中添加：
```nginx
server_tokens off;
```

在生产部署配置中添加 TLS：
```nginx
listen 5175 ssl;
ssl_certificate /path/to/cert.pem;
ssl_certificate_key /path/to/key.pem;
ssl_protocols TLSv1.2 TLSv1.3;
```

---

### P2-8：CI security-scan 高危级别设为阻塞

| 编号 | C-07 |
|------|------|
| 文件 | `.github/workflows/ci.yml:194` |

**修复方案**：
```yaml
# 之前:
- name: Security scan
  continue-on-error: true
  run: |
    pip-audit || true
    npm audit || true

# 之后:
- name: Security scan (blocking for high/critical)
  run: |
    pip-audit --desc --ignore-vuln GHSA-xxxx  # 忽略已知低危
    cd Code/frontend && npm audit --audit-level=high
```

---

### P2-9：265 处 except Exception 批量替换

| 编号 | D-01 |
|------|------|
| 范围 | `Code/backend/app/` 全目录 |

**修复方案**（分批执行）：
1. **第一批**（高优先级文件）：
   - `raster_science.py`（15 处）→ 替换为 `rasterio.errors.RasterioIOError` / `ValueError` / `OSError`
   - `export_layer.py`（10 处）→ 替换为具体异常
   - `main.py`（9 处）→ lifespan 中保留 `except Exception` 但添加 `logger.exception` + 明确的 raise/continue 策略

2. **第二批**（中优先级文件）：
   - `workflow_request_resolver.py`（11 处）
   - `config_weather_providers.py`（8 处）

3. **规则**：按 project_memory 约定 —
   - 网络/API 失败 → `httpx.HTTPError` / `ConnectionError` / `TimeoutError`
   - 数据格式错误 → `ValueError` / `KeyError` / `json.JSONDecodeError`
   - 编程 bug（`AttributeError` / `NameError`）→ 不捕获，传播

---

### P2-10：core/config.py 分组为嵌套 dataclass

| 编号 | D-02 |
|------|------|
| 文件 | `Code/backend/app/core/config.py`（547 行，80+ 字段） |

**修复方案**：
```python
@dataclass(frozen=True)
class RedisConfig:
    url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    max_connections: int = field(default_factory=lambda: int(os.getenv("REDIS_MAX_CONNECTIONS", "20")))

@dataclass(frozen=True)
class GeeConfig:
    enabled: bool = field(default_factory=lambda: os.getenv("BACKEND_GEE_ENABLED", "false").lower() == "true")
    encryption_key: str = field(default_factory=lambda: os.getenv("BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY", ""))

@dataclass(frozen=True)
class Settings:
    environment: str = ...
    redis: RedisConfig = field(default_factory=RedisConfig)
    gee: GeeConfig = field(default_factory=GeeConfig)
    # ...
```

同时提取魔法数字为命名常量：
```python
_DOWNLOAD_MAX_BYTES = 512 * 1024 * 1024  # 512 MB
_BROKER_VISIBILITY_TIMEOUT = 8100  # seconds
_OPEN_METEO_DAILY_BUDGET = 8000
_OPEN_METEO_SOFT_WARNING = 6400
```

---

### P2-11：main.py import 时副作用移入 create_app()

| 编号 | D-03 |
|------|------|
| 文件 | `Code/backend/app/main.py:46` |

**修复方案**：
```python
# 之前:
register_default_providers()  # 模块级，import 时执行

# 之后:
def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    register_default_providers()  # 移入此处
    # ...
    return app
```

---

### P2-12：test_auth.py 模块单例替换改为 mock.patch

| 编号 | C-08 |
|------|------|
| 文件 | `Test/backend/test_auth.py:49` |

**修复方案**：
```python
# 之前:
ur_mod._repo = UserRepository(...)

# 之后:
@pytest.fixture
def mock_repo(mocker, tmp_path):
    repo = UserRepository(str(tmp_path / "test.db"))
    with mocker.patch('app.services.user_repository_module._repo', repo):
        yield repo
```

---

### P2-13：stores/layers/ 29 个文件补充 barrel export 文档

| 编号 | A-14（补充） |
|------|------|
| 文件 | `Code/frontend/src/stores/layers/index.ts` |

**修复方案**：在 `index.ts` 中为每个子模块添加 docstring 注释声明公共接口，确保 Agent 搜索可达性。

---

## P3 — 低优先级（技术债清理）

### P3-1：超长函数拆分（Top 5）

| 编号 | D-04 |
|------|------|
| 函数 | `_build_product_map_layer_ref`（204行）, `_populate_python_provider_request`（174行）, `build_wind_geojson_from_grid`（162行）等 |

**修复方案**：按 Extract Function 重构手法，每个函数拆分为 ≤40 行子函数。每个子函数命名以"动词+对象"模式。

---

### P3-2：Tools/ 临时脚本清理

| 编号 | D-05 |
|------|------|
| 文件 | `Tools/_tmp_*.py`, `Tools/start_backend.py`, `Tools/restart_backend.py` |

**修复方案**：
1. 删除 `_tmp_check_data_root.py`, `_tmp_list_runs.py`, `_tmp_watch_run.py`
2. 为 `start_backend.py`, `restart_backend.py` 添加文件头注释：`# DEPRECATED: Use launch.py instead`
3. 或直接删除已被 `launch.py` 取代的遗留脚本

---

### P3-3：overlay_registry.py 时间列表生成函数去重

| 编号 | A-15（补充） |
|------|------|
| 文件 | `Code/backend/app/services/overlay_registry.py` |

**修复方案**：将 `_smap_time_list`, `_gpcp_time_list`, `_doy_time_list`, `_soil_ddca_time_list`, `_date8_time_list` 提取为通用时间列表生成器 + 配置参数。

---

### P3-4：core/config.py dotenv 加载失败不应静默吞掉

| 编号 | D-06（补充） |
|------|------|
| 文件 | `Code/backend/app/core/config.py:14` |

**修复方案**：
```python
# 之前:
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# 之后:
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv 未安装，环境变量已通过其他方式设置
except Exception as exc:
    import logging
    logging.warning(f"Failed to load .env file: {exc}")
```

---

### P3-5：api/deps.py 重复权限检查模式提取为通用 helper

| 编号 | A-16（补充） |
|------|------|
| 文件 | `Code/backend/app/api/deps.py` |

**修复方案**：
```python
def _require_permission(request: Request, x_api_key: str | None, permission: str) -> CredentialContext:
    cred = resolve_credential(request, x_api_key)
    if not cred.has_permission(permission):
        if dev_bypass_allowed(request):
            return _dev_bypass_context()
        raise _permission_denied_error(permission, cred.role)
    return cred

def require_write_access(request: Request, x_api_key: str | None = Header(None)):
    return _require_permission(request, x_api_key, "write")

def require_workflow_run_access(request: Request, x_api_key: str | None = Header(None)):
    return _require_permission(request, x_api_key, "workflow_run")
```

---

## 执行顺序建议

```
第 1 轮（立即）：P0-1 ~ P0-4
  ├─ P0-1: overlay_registry 硬编码路径 → 替换为 settings
  ├─ P0-2: weather_sync_service 反向导入 → 提取 cache 函数
  ├─ P0-3: CI 覆盖率阈值 → 提升至 55%
  └─ P0-4: CI 前端覆盖率 → 添加 vitest --coverage

第 2 轮（1 周内）：P1-1 ~ P1-4
  ├─ P1-1: weather-tile-manager 拆分
  ├─ P1-2: overlay_registry 加锁
  ├─ P1-3: lru_cache 失效机制
  └─ P1-4: weather_render_service 去重

第 3 轮（2 周内）：P1-5 ~ P1-7
  ├─ P1-5: WorkflowCanvas 抽取 composables
  ├─ P1-6: workflow-runner 缩窄接口
  └─ P1-7: WebGL utils 抽取

第 4 轮（同步进行）：P1-8 ~ P1-11
  ├─ P1-8: workflow/ 目录补测
  ├─ P1-9: conftest 共享 fixture
  ├─ P1-10: circuit_breaker 去 sleep
  └─ P1-11: 统一 pytest 风格

第 5 轮（1 个月内）：P2-1 ~ P2-13
  ├─ P2-1: node_template_registry 拆分
  ├─ P2-2: data_io router 拆分
  ├─ P2-3: import_service deprecation
  ├─ P2-4: service 层去 HTTPException
  ├─ P2-5~P2-7: 安全加固
  ├─ P2-8: CI security-scan 阻塞
  ├─ P2-9: except Exception 批量替换
  ├─ P2-10: config.py 分组
  └─ P2-11~P2-13: 其他清理

第 6 轮（持续）：P3-1 ~ P3-5
  └─ 技术债清理
```

---

## 每轮验证检查清单

每完成一批修复后，执行以下验证：

```powershell
# 1. 后端测试
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend -p no:cacheprovider --basetemp="Test/.pytest-be" -q

# 2. 算法测试
Env/Python312/python.exe -m pytest Test/algorithms -q

# 3. 前端测试
cd Code/frontend && npm run test

# 4. 前端构建
cd Code/frontend && npm run build

# 5. Lint
cd Code/frontend && npm run lint
pre-commit run --all-files

# 6. 契约检查
cd Code/frontend && npm run check:openapi && npm run check:catalog
```

所有检查通过后方可进入下一轮。

---

## 健康度目标

| 维度 | 当前 | 目标（3 个月） |
|------|------|--------------|
| 综合健康度 | 67 | 80+ |
| 架构边界 | 65 | 75+ |
| 安全防护 | 82 | 88+ |
| 测试质量 | 55 | 75+ |
| 代码卫生 | 68 | 80+ |

关键里程碑：
- P0 修复后 → 综合健康度提升至 72+
- P1 修复后 → 综合健康度提升至 78+
- P2 修复后 → 综合健康度提升至 82+
