# 代码审查报告：正确性与并发专项（2026-08-10）

> 范围：`Code/{backend,algorithms,shared,frontend/src}`（同 08-10 全量基线）
> 重点：算法数值正确性、并发竞态、契约一致性、跨平台路径
> 基线：后端 688 passed（08-09）/ 算法 337 passed（08-10）/ 本次复跑 upload×import 18 passed
> 工作区：HEAD `37dc091`（omega 重构），0 未提交变更

---

## 发现汇总

| ID | 严重度 | 模块 | 问题 | 状态 |
|----|--------|------|------|------|
| CC-1 | **P1** | data_io/upload.py | append 模式缺锁 + 非原子写，与 manifest 模式不对称 | 新发现 |
| CC-2 | P2 | data_io/resumable_upload.py | complete_resumable 未持 _meta_lock | 新发现 |
| CC-3 | P2 | algorithms/omega_sf.py | 日志统计 avail/total_req 缺零保护 | 新发现 |
| CC-4 | P2/观察 | algorithms/publish/* | 12 处裸 resolve().as_uri() 跨平台隐患 | 新发现 |
| CC-5 | nit | api/config_routes.py:703 | 403 表示功能门禁，与鉴权 403 语义混淆 | 观察项 |

**整体结论**：无 P0 正确性缺陷。数值守卫完善、契约无漂移、跨平台历史 bug 已修。主要风险集中在 append 上传模式并发（P1）。

---

## 详细发现

### CC-1 [P1] append 上传模式缺锁 + 非原子写

**定位**：`Code/backend/app/data_io/services/upload.py`
- `append_upload_chunk` L150-191：无 `_meta_lock`，meta.json 用裸 `write_text`（L188）
- `complete_upload` L194-236：无 `_meta_lock`，meta.json 用裸 `write_text`（L228）

**对比**：同子系统 `resumable_upload.py` 的 manifest 模式已在 08-09 修复并发——
`upload_chunk_by_index`（L193）持 `_meta_lock`（跨进程 msvcrt/fcntl 文件锁）+ `_save_meta`（`os.replace` 原子写，L137-142）。

**风险**：
1. 并发重试同 offset：两个请求都读 meta(received=current) → 都 append 写 blob.part → 第二个 `write_text` 覆盖第一个的 received 记录 → **meta 与实际 blob 大小不一致**。
2. 并发 complete：两个请求都 `part.replace(final_path)`（L219）→ 第二个 FileNotFoundError 或 final_path 损坏。
3. `write_text` 非原子：并发读写可能读到半写 JSON → JSONDecodeError（与 08-09 修过的 manifest 模式同类根因）。

**触发条件**：append 模式设计为顺序追加（offset 递增），客户端严格顺序不触发。但 API 层允许并发请求（网络重试、双击完成）时存在损坏风险。

**修复建议**：复用 `resumable_upload._meta_lock` + `_save_meta`，与 manifest 模式统一：
```python
from app.data_io.services.resumable_upload import _meta_lock, _save_meta
# append_upload_chunk / complete_upload 包入 with _meta_lock(dest):
# meta 写入改 _save_meta(dest, meta)
```
注意：`_meta_lock`/`_save_meta` 当前是模块私有（下划线前缀），需提为模块公开或移至共享 utils。

**验证**：补 append 模式并发测试（两线程同 offset / 双 complete），参考 `test_resumable_upload.py` 的并发用例。

---

### CC-2 [P2] complete_resumable 未持锁

**定位**：`Code/backend/app/data_io/services/resumable_upload.py:277` `complete_resumable`

**现状**：`upload_chunk_by_index`（L193）持 `_meta_lock`，但 `complete_resumable`（L277）直接 `_load_meta`（L282）+ 拼接（L312）+ `_save_meta`（L354），全程无锁。

**风险**：API 层并发 complete + upload_chunk 时，两者的 `_save_meta` 竞争可能丢块记录。正常顺序使用（先上传完所有块再 complete）不触发。

**修复建议**：`complete_resumable` 主体包入 `with _meta_lock(dest):`，与 `upload_chunk_by_index` 对称。

---

### CC-3 [P2] omega_sf 日志统计缺零保护

**定位**：`Code/algorithms/providers/Python/algorithms/omega_sf.py`
- L2389/2403/2417/2431：`100.0 * avail / total_req`

**现状**：核心数值计算（SF 反演 L245-256）有完善守卫（`np.errstate` + `abs(den)>=1e-6` + `np.nan` 回退）；L1836/2280 的统计已用 `max(...,1)`。仅这 4 处日志统计缺零保护。

**风险**：`total_req` 由日期范围生成，正常不为 0。仅边缘情况（空日期范围）触发 ZeroDivisionError 中断日志输出。

**修复建议**：统一改 `100.0 * avail / max(total_req, 1)`。

---

### CC-4 [P2/观察] publish 路径裸 as_uri()

**定位**：`Code/algorithms/providers/Python/publish/{output_manager,raster_writer,table_writer}.py`、`data_access/sources/{remote,minio,http}.py`、`storage/local_fs.py`、`interfaces/datasource.py`、`modules/data_access_nodes.py` —— 共 12 处 `Path.resolve().as_uri()`。

**现状**：`service/result_dto.py::_as_file_uri`（L604）已在 08-09 修复跨平台问题（手动构造 `file:///D:/...` 处理 Windows 盘符在 Linux 的语义）。

**风险**：这 12 处用裸 `resolve().as_uri()`。若 `output_file` 是运行时本地路径（join 生成），当前平台 `resolve().as_uri()` 正常。**但若接收跨平台序列化的路径字符串**（如从配置/DB 读的 Windows 路径在 Linux 运行），`resolve()` 会把 `D:\foo` 当相对路径 → 产出错误 URI。

**修复建议**：涉及跨平台序列化路径的场景统一改用 `_as_file_uri`；纯运行时本地路径可保留 `resolve().as_uri()` 但加注释说明。当前未确认有实际触发场景，故列为观察项。

---

### CC-5 [nit] 403 表示功能门禁

**定位**：`Code/backend/app/api/config_routes.py:703`

**现状**：`restart_backend_service` 捕获 `PermissionError` 返回 403。该 403 是"UI 重启门禁 `BACKEND_UI_RESTART_ENABLED` 关闭"，非鉴权失败（鉴权已由 L695 `Depends(require_write_access)` 处理）。按项目约定"功能开关不挂 C403001"，此处用裸 `HTTPException(403)` 不挂错误码是**正确的**。

**观察**：403 既用于鉴权失败（挂 C403001）又用于功能门禁（不挂），前端需靠 `error_code` 字段区分。建议功能门禁改用 503（Service Unavailable）或 409（Conflict）语义更清晰。低优先级。

---

## 已确认良好的维度

| 维度 | 结论 |
|------|------|
| 算法数值守卫 | omega.py（eps 零保护 L1377）/ omega_sf.py（errstate+1e-6+nan 回退 L245-256）/ inversion.py / ndvi.py 的 NaN/inf/除零守卫完善；golden 基线覆盖 omega.py 8 cases |
| 契约一致性 | openapi.json（464K）+ api-contracts.ts（375K）均 clean，与 HEAD 一致，无漂移；错误码 C403001/C429001 落地完整（deps 6处 + auth_router 4处 + rate_limit） |
| 跨平台路径 | detect_source_kind（scheme=="" 分支）+ _as_file_uri（手动 file:///D:/）历史 bug 已正确修复，注释清晰 |
| 原子写 | env_file_upsert / workflow_definition_service / gee/tasks 均用 os.replace 原子写；SQLite 池 WAL+busy_timeout+Queue 设计良好 |
| 限流/会话多 worker | rate_limit 已 Redis 集中化（08-09 S2），降级有告警；session_service Redis 集中 |

**已知限制（非 bug）**：spatial_repository / cache_service / circuit_breaker 等用 threading.Lock，多 worker（多进程）下不共享——README 已声明 SQLite 初代、PostGIS 后续。

---

## 建议优先级

1. **P1 CC-1**：append 模式加锁 + 原子写（与 manifest 模式统一），补并发测试
2. **P2 CC-2**：complete_resumable 加锁
3. **P2 CC-3/CC-4**：零保护 + as_uri 统一（低风险，可批量处理）
4. **nit CC-5**：功能门禁状态码语义（可选）

> 复跑命令：`CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= REDIS_URL=redis://localhost:6379/0 ENVIRONMENT=test Env/Python312/python.exe -m pytest Test/backend/test_resumable_upload.py Test/backend/test_import_data_io.py -p no:cacheprovider --basetemp="Test/.pytest-review" -q` → 18 passed
