# 代码问题报告（2026-08-11）

> 范围：本轮未提交改动（基于 `4587c70` 之上的工作树改动，共 36 文件改动 + 9 新增）。
> 重点区域：导出服务（`export_layer.py`）、运行时资源接口、工作流执行器 optional 端口、前端导出/资源面板。
> 结论：**静态检查与测试全绿，但发现 1 个可达的并发缺陷（P1）与若干稳健性/运维隐患。**

---

## 0. 验证矩阵（已通过的客观信号）

| 检查项 | 命令/对象 | 结果 |
|---|---|---|
| ruff（后端改动文件） | `ruff check export_layer / runtime_status_service / executor / router / import_jobs / runtime_router` | ✅ 全通过 |
| 后端导出测试 | `test_export_*.py`（14 项）+ 新增 `test_export_mat`/`test_export_arcgis_opts`（6 项） | ✅ 20 passed |
| 前端测试 | 改动/新增测试文件（28 项） | ✅ 28 passed |
| 前端类型检查 | `vue-tsc --noEmit` | ✅ 无错误 |
| 前端 ESLint | 8 个改动文件 | ✅ 无告警 |
| 契约一致性 | `api_contracts.py` ⇄ `api-contracts.ts` ⇄ `openapi.json` | ✅ 新增 `ResourceUsageResponse`/`SystemResourceSnapshot`/`ProcessResourceSnapshot` 与 `/runtime/resources` 三处对齐 |
| 执行器 optional 端口 | `test_workflow_engine_optional_edge` | ✅ passed |
| 依赖可达性 | `psutil` 7.2.2 已装、`PortSpec.required` 存在、`settings.data_root` 存在 | ✅ |

---

## 1. 问题清单

### 🔴 P1 — NetCDF 导出临时文件名不唯一（并发竞态，可达）

**位置**：`Code/backend/app/data_io/services/export_layer.py` → `_geotiff_bytes_to_netcdf()`（约 L899–912）

```python
buf_path = exports_dir / f"_export_tmp_{time_key or 'static'}.nc"
```

**问题**：临时文件名只由 `time_key` 决定，未加进程/请求级唯一标识。在以下**可达**场景下会碰撞：

- **同一次批导出内**：多个无 `time` 的栅格图层都会落到 `_export_tmp_static.nc`，后一个写入会覆盖前一个正在被读取的临时文件，`finally` 中的 `unlink` 还可能删掉另一个请求仍在使用中的文件 → `FileNotFoundError` 或读到的字节损坏。
- **并发单图层导出**：两个无 `time` 的 NetCDF 导出请求同时到达，同样碰撞。

**建议修复**：使用 `tempfile.NamedTemporaryFile(dir=exports_dir, suffix=".nc", delete=False)` 或 `uuid` 保证每次调用唯一；读取后按现有 `finally` 逻辑清理即可。

---

### 🟠 P2 — `IMPORTS_DIR/_exports` 产物无清理（磁盘泄漏）

**位置**：`export_layers_batch_zip()`（L1045）/ `_try_export_layers_batch_mat()`（L1013）

**问题**：批导出 zip、合并 mat 以 `uuid` 命名持久化到 `IMPORTS_DIR/_exports`，**从不删除**。单图层 NetCDF 导出的临时文件虽每次清理，但批产物会持续累积。长期运行的服务会悄悄吃满磁盘（尤其大栅格/多图层批量导出）。

**建议修复**：导出时顺带做一次惰性清理（删除超过 N 小时的文件），或由定时任务/Celery beat 周期回收。

---

### 🟠 P2 — 执行器 optional 端口语义靠输出端口 `required` 复用（易误配）

**位置**：`executor.py` → `_is_port_required()`（L162–177）

**问题**：判断"源端口缺失是否允许跳过"，读取的是**源节点输出端口**的 `required` 字段。但 `required` 语义上描述"输入端口是否必填"，用它表达"该输出可能不存在"是语义错位，作者极易忘记给输出端口标 `required=False`（默认 `True`），导致功能"看起来开了实际仍报错"。

**现状安全性**：默认 `required=True`，缺失输出仍会抛 `KeyError`（安全兜底），所以**不会静默产出垃圾结果**；但功能意图与字段语义不一致。

**建议**：在 `PortSpec` 增加独立字段（如 `optional_output: bool`）表达"该输出可能不产生"，并同步更新节点 `build_spec()` 约定与 `_is_port_required` 读取逻辑；或至少在 AGENTS/docs 中明确该契约。

---

### 🟡 P3 — 资源接口进程过滤在 Windows 开发态可能漏掉主进程

**位置**：`runtime_status_service.py` → `get_resource_usage()`（约 L320–345）

**问题**：仅收集进程名含 `"celery"` 或 `"uvicorn"` 的进程。Windows 开发态下 FastAPI 常以 `python.exe`（经 `launch.py`/`start.bat` 拉起）运行，`"uvicorn" in name` 命中失败 → `processes` 列表不含后端主进程，资源面板数据不完整（不崩溃）。

**建议**：同时纳入当前 PID 及其父进程，或按监听端口/模块名匹配。

---

### 🟡 P3 — 栅格 MAT 导出传 `fields` 在波段无命名时直接报错

**位置**：`export_layer.py` → `_geotiff_bytes_to_mat_payload()`（L810–819）

**问题**：对栅格图层传 `fields` 但该栅格波段无命名（`variable_ids`/`band_names` 缺失）时，会抛 `ValueError("fields 与栅格波段名无交集…")`。`fields` 本质是矢量概念，前端若把矢量导出选项复用到栅格 MAT 上会触发该错误。当前已被 router 的 `ValueError → 4xx` 兜底，影响有限。

**建议**：前端对栅格格式禁用 `fields`；或在后端对该情况给出更友好的提示文案。

---

### ⚪ P3 — 仓库根存在游离/未跟踪文件（提交卫生）

**现象**：`git status` 显示未跟踪：`~/`、`_pipeline_health_static.json`、`_stub_inventory.json`。其中 `~/` 是可疑的游离项，其余为运行期生成物。

**建议**：确认是否应加入 `.gitignore`，避免误提交；`~` 建议直接清理。

---

## 2. 提交前提醒（流程门，非当前故障）

- **`check:openapi` 漂移门**：已确认当前 `openapi.json` 与 `api-contracts.ts` 对齐（含新增资源接口）。但若后续再改后端契约，提交前务必跑 `cd Code/frontend && npm run check:openapi`，否则 CI 闸门会失败。
- **pre-commit**：前端 prettier 钩子校验全部前端文件；本次改动含大量 `.vue`/`.ts`，提交时会整体格式化（LF→CRLF 警告已出现，属正常）。

---

## 3. 建议处理顺序

1. **立即修 P1**（NetCDF 临时文件竞态）—— 一行改动即可消除，影响正确性。
2. **修 P2**（_exports 清理 + optional 端口语义）—— 影响运维与长期可维护性。
3. P3 可并入后续小提交或本期一并处理。

> 本报告仅分析问题，未做任何修改。是否按上述顺序进入修复，请确认。

---

## 4. 修复记录（2026-08-11 下午 · 已实施并验证）

> 用户确认"复查并准备修复"后按 P1→P2→P3 实施，**工作树已修改、未提交**。
> 改动：5 文件，+158/−7。

| 项 | 修复内容 | 验证 |
|---|---|---|
| 🔴 P1 | `_geotiff_bytes_to_netcdf` 临时文件改 `uuid4().hex` 唯一名，消除并发/同批碰撞 | ruff ✅；导出测试 14 passed ✅；**16 线程并发导出全成功、零残留** ✅ |
| 🟠 P2a | 新增 `_cleanup_exports_dir()`（TTL 24h 惰性清理），`export_layers_batch_zip` 写入前调用 | 导出测试全绿 ✅ |
| 🟠 P2b | `PortSpec` 新增 `optional_output: bool = False`；`_is_port_required` 优先读它、回退 `required`（向后兼容旧写法）；新增 `test_workflow_engine_optional_output_flag` | business regression 9 passed ✅（含新旧两用例） |
| 🟡 P3a | 进程过滤加 `cmdline` 匹配（celery/uvicorn）+ 父进程纳入，覆盖 Windows 下 `python.exe` 场景 | 冒烟调用正常：列出 5 个 python.exe、worker_count=7 ✅ |
| 🟡 P3b | **判定不修**：前端 `showFieldPicker` 仅 `hasVector` 时显示、栅格路径不传 fields；后端报错已可读 | — |
| ⚪ P3c | **自动关闭**：`~/`、`_pipeline_health_static.json`、`_stub_inventory.json` 已在 `.gitignore` | `git check-ignore` 确认 ✅ |

工作流相关回归：`test_business_regression.py`（9）+ `test_workflow_graph_compiler/request_resolver/bridge_resolution`（14）全部通过。
**待办**：未提交，等用户"提交一下"。
