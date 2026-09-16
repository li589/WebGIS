# 修复后端 32 个 pytest 失败项 → 全绿

> 仓库：`D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system`  
> 测试位置：`Test/backend/`（已迁出 `Code/backend/tests/`）  
> 解释器：`Env/Python312/python.exe`  
> 目标：32 → 0（用户选择「分析+修复全部到全绿」）

## 32 项失败分类总表

| 组 | 数 | 失败项 | 根因 | 性质 | 修复 |
|----|----|--------|------|------|------|
| A | 5 | `test_archive_safe.py`（unrar/7z 相关） | `Code/backend/vendor/unrar/{win-x64,linux-x64}/` 无二进制（gitignore 排除）；PATH 无 unrar/7z | 环境/部署 | 补齐 vendor unrar 二进制 |
| B | 2 | `test_import_data_io::test_delete_imported_layer_dir`、`test_import_quota_reimport::test_reclaim_tmp_and_quota_message` | WorkBuddy safe-delete 拦截 `shutil.rmtree`/`os.remove`，basetemp 路径回收站不可用 → fail-closed | 沙箱副作用 | 关沙箱跑 pytest |
| C | 12 | `test_import_raster_crs.py`（全部） | `deps.py:27` 免鉴权逃逸口只认 `environment=="development"`；conftest 设 `BACKEND_ENV=test` → 逃逸不触发 → 无 key → 503 | 预先存在（配置） | 改 `client` fixture：设 `settings.api_key` + 注入 `X-API-Key` header |
| D | 6 | `test_interaction_hub`(smap)、`test_layer_remote_uris::injects_smap`、`test_workflow_bridge_resolution`(2)、`test_workflow_request_resolver`(2) | `layer_descriptors.json` 已演化（smap-soil 移除、dem-etopo 加 engine、ndvi 转 available、lab-output notes 变），测试断言停留在旧事实 | 真实测试漂移 | 更新 6 处断言对齐现行 catalog |
| E | 2 | `test_raster_timeseries_upsert::{test_upsert_refreshes_when_mat_newer,test_omega_reuses_legacy_omega_block_layer_id}` | upsert 刷新/替换 TIF 时内部文件删除被 safe-delete 拦截（rasterio/scipy 实已安装，非缺包） | 沙箱副作用（待确认） | 关沙箱重跑确认；若仍失败再查 upsert 刷新逻辑 |
| F | 1 | `test_provider_frontend_compat::test_lab_output_map_layer_ref_matches_frontend_shape` | 全局 `submission_service` 同步真跑 lab-output，测试环境 `data_root=""` → LAB_OUTPUT_RASTER 无法解析 → run failed | 集成/配置 | 设 `BACKEND_DATA_ROOT` 指向样本数据，或在测试 patch provider 数据源 |
| G | 4 | `test_resumable_upload`（4 个） | 纯文件系统、无 redis/rasterio 依赖；疑 `resumable_upload.py`/`upload.py` 分块/SHA/幂等回归，或 safe-delete 干扰 | 待定 | 关沙箱取干净 traceback；真 bug 则修代码 |

> 关键裁决：conftest 设 `BACKEND_WORKFLOW_EXECUTOR=sync`，**不派发 Celery**；redis 有优雅降级。故 D/F/G **不需要**启动 Redis/worker。第三 agent 的「缺 rasterio/scipy」诊断已被推翻（文件可收集、algo 套件用过 rasterio）。

## 执行步骤

### Step 0 — 诊断性重跑（关沙箱，分离 safe-delete 假阳性）
用 Bash 工具 `dangerouslyDisableSandbox: true` 跑：
```
Env/Python312/python.exe -m pytest Test/backend -q --tb=short -p no:cacheprovider --basetemp="D:/.../Test/.pytest-be"
```
- 预期 B(2)、E(2) 立即转绿；G(4) 给出干净 traceback。
- 记录剩余真实失败（应为 C(12)+D(6)+F(1)+A(5，若 unrar 仍缺)+G 中真 bug 部分）。
- **确立运行约定**：后端测试在 WorkBuddy 内须关沙箱跑（写 `.ai/rules/project-conventions.md` + `AGENTS.md` 的「后端测试」节）。

### Step 1 — 补齐 unrar 二进制（A，5 项）
- 下载：https://www.rarlab.com/rar_add.htm → `unrarw64.exe`（SFX 包，**勿直接当工具**）。
- 静默解出 CLI：`unrarw64.exe -s -d<out>` → 复制为 `Code/backend/vendor/unrar/win-x64/UnRAR.exe`。
- 验证：`UnRAR.exe`（打印 Usage、无窗口）。
- Linux（CI 用）：`Code/backend/vendor/unrar/linux-x64/unrar`（或 CI 装 `apt install unrar`）。
- 这两个子目录已被 `.gitignore`（L120-121）排除，属本地/CI 环境准备，不入库。
- `test_find_console_unrar_not_sfx` 是契约测试，**补二进制而非 skip**。

### Step 2 — 修 API-key 503（C，12 项）
**只改 1 个文件**：`Test/backend/test_import_raster_crs.py` 的 `client` fixture（L84-87）。
```python
@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient（测试环境注入 API key 绕过写鉴权）。"""
    from app.core.config import settings
    monkeypatch.setattr(settings, "api_key", "test-key")
    monkeypatch.setattr(settings, "api_keys_enabled", True)
    return TestClient(create_app(), headers={"X-API-Key": "test-key"})
```
- 机制：`get_backend_auth_key()` = `get_effective_secret("backend_auth") or settings.api_key`（effective_config.py:207）；`settings.api_key`←`BACKEND_API_KEY`（config.py:194）。
- **验证点**：测试 env 无 DB 时 `get_effective_secret("backend_auth")` 应返回 None（否则需先清 EffectiveSecrets）；实现时先 `print(get_backend_auth_key())` 确认拿到 `"test-key"`。
- 不改 `deps.py`（安全敏感，用户已否决）；不改 conftest 全局 env（避免波及其它测试）。
- 扫描确认：仅此文件有「dev mode 跳过 auth」的 `client` fixture，其它测试用别的 fixture 或不触写端点，不受影响。

### Step 3 — 更新 6 处目录漂移断言（D，6 项）
逐文件读测试 + 现行 `Code/backend/app/catalog_seeds/layer_descriptors.json`，把断言对齐到事实：
- `test_interaction_hub::test_submit_workflow_auto_populates_python_provider_defaults_for_smap_and_fy_layers`：smap-soil 已从目录移除（仅剩 smap-sm-ts）→ 删/改 smap-soil 相关期望。
- `test_layer_remote_uris::test_apply_remote_layer_data_uris_injects_smap`：同上，smap-soil 不再注入。
- `test_workflow_bridge_resolution`（2）：dem-etopo 现有 `engine=python_provider`（曾为静态层）→ 改消息断言。
- `test_workflow_request_resolver`（2）：ndvi 现 `status=available`（非 placeholder）、lab-output notes 不含「实验/样板」→ 改状态/消息断言。
- 原则：**测试反映现行 catalog 事实**，不改 catalog 去迁就旧测试（除非 catalog 本身有错，需另行确认）。

### Step 4 — 修 provider_frontend_compat（F，1 项）
`Test/backend/test_provider_frontend_compat.py`：lab-output provider 同步真跑需 LAB_OUTPUT_RASTER。
- 优先：在测试 setup（或 conftest）设 `BACKEND_DATA_ROOT` 指向含 lab-output 样本栅格的目录（查 `Code/backend/.data/` 或算法样本）。
- 备选：用 `monkeypatch` patch lab-output provider 的栅格读取，返回合成数据。
- 先读 lab-output provider 源码确认其数据路径解析逻辑再定方案。

### Step 5 — 排查 resumable_upload（G，4 项）
Step 0 关沙箱重跑后：
- 若转绿 → safe-delete 干扰（归入运行约定，无需改代码）。
- 若仍失败 → 按 traceback 修 `Code/backend/app/data_io/services/resumable_upload.py` / `upload.py` 的分块/SHA256/幂等/并发逻辑。

### Step 6 — 全量验证（关沙箱）
```
Env/Python312/python.exe -m pytest Test/backend -q --tb=short -p no:cacheprovider --basetemp="D:/.../Test/.pytest-be"
```
目标：**0 failed**。同时回归：
```
Env/Python312/python.exe -m pytest Test/algorithms -q     # 306 passed 不退化
cd Code/frontend && npm run test                           # 432 passed 不退化
```

### Step 7 — 文档同步 + 记忆
- `.ai/rules/project-conventions.md` + `AGENTS.md`「后端测试」节：注明「WorkBuddy 内跑后端测试须关沙箱（`dangerouslyDisableSandbox`）以避 safe-delete 拦截文件删除」；补 unrar 二进制准备说明。
- `.workbuddy/memory/2026-08-04.md`：追加 32 项修复记录。

## 关键文件清单

| 文件 | 改动 |
|------|------|
| `Test/backend/test_import_raster_crs.py` | 改 `client` fixture（L84-87）注入 API key + header |
| `Test/backend/test_interaction_hub.py` | 更新 smap-soil 断言 |
| `Test/backend/test_layer_remote_uris.py` | 更新 smap 注入断言 |
| `Test/backend/test_workflow_bridge_resolution.py` | 更新 dem-etopo engine 断言（2） |
| `Test/backend/test_workflow_request_resolver.py` | 更新 ndvi/lab-output 断言（2） |
| `Test/backend/test_provider_frontend_compat.py` | 设 data_root 或 patch provider |
| `Code/backend/app/data_io/services/resumable_upload.py`（可能） | 按 Step 5 traceback 修 |
| `Code/backend/app/data_io/services/upload.py`（可能） | 同上 |
| `Code/backend/vendor/unrar/win-x64/UnRAR.exe` | 新增二进制（gitignore，不入库） |
| `Code/backend/vendor/unrar/linux-x64/unrar` | 新增二进制（CI 用，gitignore） |
| `.ai/rules/project-conventions.md`、`AGENTS.md` | 加「关沙箱跑后端测试」+ unrar 准备说明 |
| `.workbuddy/memory/2026-08-04.md` | 追加修复记录 |

## 风险与注意
- **deps.py 不改**（安全敏感，用户已明确）。API-key 方案仅作用于 `test_import_raster_crs.py` 单文件 fixture，不影响生产鉴权语义。
- **safe-delete 是 WorkBuddy 沙箱特性**：B/E（及可能的 G）本质是运行环境问题，"修复"= 关沙箱运行；非代码缺陷。需在文档固化该约定，避免后续误判。
- **catalog 漂移（D）**：若发现 catalog 本身（如 smap-soil 移除）是误删而非有意，应反过来恢复 catalog 而非改测试——实现时与用户确认每个变更方向。
- **unrar 二进制不入库**（gitignore）：CI 须靠 `apt install unrar` 或独立缓存；本地须手动放置。test 1（契约测试）会提醒部署遗漏。
