# 增量 PRD：收窄 router.py / config_service.py 过宽异常捕获

## 1. 项目信息

- **Language**: 中文
- **涉及文件（仅这两个 + 必要辅助）**:
  - `Code/backend/app/data_io/api/router.py`（33 处 `except Exception`）
  - `Code/backend/app/services/config_service.py`（19 处 `except Exception`）
- **复用基础设施（不新造）**:
  - `app/api/error_codes.py`：`ApiError(spec, status_code=...)`、`C403001`/`C429001`
  - `app/main.py` 全局异常处理器：
    - `http_exception_handler`（StarletteHTTPException）→ 保留 `status_code` + `detail` + `error_code` + `request_id`
    - `unhandled_exception_handler`（Exception）→ 500 `{"detail":"Internal server error","request_id":...}` + `logger.exception` ERROR 日志
    - `validation_exception_handler`（RequestValidationError）→ 422
- **原始需求复述**：前序代码审查发现上述两文件存在大量过宽的 `except Exception`，需逐处收窄，区分"预期缺失/可恢复"与"真错误"，复用已有统一错误码与全局处理器，且不破坏对外错误行为。

---

## 2. 产品目标

**一句话价值**：把"被宽捕获吞掉、既无 ERROR 日志又语义模糊"的真错误还原成"可观测的 500 + 日志"，同时让"预期缺失"返回精确的业务语义（404/空），使开发者排查、运维监控、终端用户报错反馈三条链路都从"黑盒 200/404"变成"可定位的明确响应"。

---

## 3. 用户故事

1. **作为后端开发者**，当某导入端点因 IO 故障或序列化 bug 抛出非预期异常时，我希望它被全局处理器捕获并产出 ERROR 日志（含 request_id 与堆栈），而不是被端点内的 `except Exception` 静默翻译成一个没有日志的 400/404，以便我能从日志快速定位根因。
2. **作为运维/SRE**，我希望"任务文件损坏"、"磁盘满"这类真故障在监控里体现为 5xx 错误率上升，而不是被伪装成 404（"任务不存在"）从而漏报，以便告警准确。
3. **作为终端用户/前端**，当请求一个不存在的图层/任务时，我希望得到明确的 404；当后端真出故障时，我希望得到稳定的"Internal server error"+ request_id（而非泄露服务端路径的原始异常串），以便我截图反馈、运维凭 request_id 追溯。

---

## 4. 需求池（P0 / P1 / P2）

### 4.1 router.py（33 处）

> 通用收窄模式（适用于下表"标准翻译"类，即 Group A）：
> 把 `try: svc() except Exception as exc: raise _http_err(exc) from exc` 拆为——
> ```python
> try:
>     return svc()
> except FileNotFoundError as exc:        # 预期缺失 → 404，不记 ERROR
>     raise _http_err(exc) from exc
> except QuotaExceededError as exc:        # 配额 → 507（必须在 RuntimeError 之前！）
>     raise _http_err(exc) from exc
> except (ValueError, RuntimeError) as exc:  # 客户端输入/业务校验 → 400
>     raise _http_err(exc) from exc
> # 其余 Exception 不捕获 → 上抛全局处理器：500 + "Internal server error" + ERROR 日志
> ```
> **关键排序约束**：`QuotaExceededError(RuntimeError)` 是 RuntimeError 子类，`_http_err` 内 507 分支必须在 400 分支之前命中。收窄时若手写 except 顺序，必须保持 507 在 400 之前，否则配额超限会被误降为 400。

#### P0 — 真错误被伪装成 4xx（`not_found=True` 把一切异常强转 404）

| 行号 | 端点 | 保护操作 | 当前行为 | 期望行为（收窄后） | 行为变更? |
|---|---|---|---|---|---|
| 368 | `import_job_status` | `get_job(job_id)` | 任何异常→404 | `FileNotFoundError`(任务不存在)→404；`JSONDecodeError`/`OSError`(任务文件损坏/IO)→上抛全局 500+日志 | 是(损坏文件 404→500，判定为 bug 修复) |
| 378 | `import_job_cancel` | `cancel_job`→`get_job` | 同上 | 同上 | 是(同上) |
| 388 | `import_job_download` | `get_job(job_id)` | 同上 | 同上；后续 404 分支(无下载文件/路径失效/非法路径)保持不变 | 是(损坏文件 404→500) |

> 说明：`get_job` 对缺失任务抛 `FileNotFoundError("任务不存在: ...")`（jobs.py:61），这才是"预期缺失"。当前 `not_found=True` 把 `json.JSONDecodeError`（任务 json 损坏）也变成 404，掩盖了真故障。收窄后仅 `FileNotFoundError`→404，其余上抛。

#### P1 — 语义不清 / 日志缺失（其余 `not_found=True` + 标准翻译类）

**P1-a：其余 `not_found=True` 强转 404（图层/文档读取类）**

| 行号 | 端点 | 保护操作 | 当前行为 | 期望行为 | 行为变更? |
|---|---|---|---|---|---|
| 535 | `vector_meta` | `load_vector_meta` | 任何异常→404 | `FileNotFoundError`→404；其余→上抛 500+日志 | 是(非缺失异常 404→500) |
| 545 | `vector_geojson` | `load_vector_geojson` | 同上 | 同上 | 是 |
| 571 | `vector_features` | `list_vector_features` | 同上 | `FileNotFoundError`→404；`ValueError`(非法 where/sort)→400；其余→500 | 是 |
| 815 | `document_preview` | `preview_document_session` | 任何异常→404 | `FileNotFoundError`(会话不存在)→404；其余→500 | 是 |

**P1-b：标准翻译类（Group A，24 处）——补"漏记日志"+ 限定捕获类型**

下表 24 处当前均为 `except Exception as exc: raise _http_err(exc) from exc`，问题在于：未知异常（IO 故障/序列化 bug/编程错误）被 `_http_err` 翻译成 500+`str(exc)` 且**无任何日志**，真错误被静默吞掉。期望：仅捕获已知类型翻译为 4xx，未知类型上抛全局处理器（500+"Internal server error"+ERROR 日志）。

| 行号 | 端点 | 已知预期异常（保留翻译） | 备注 |
|---|---|---|---|
| 267 | `upload_init` | `ValueError`(非法扩展名/文件名)→400；`QuotaExceededError`→507 | `init_upload` 对 `evil.exe` 抛 ValueError（有测试 `test_reject_executable_extension` 锁定） |
| 284 | `upload_resumable_init` | `ValueError`→400 | 同上 |
| 294 | `upload_status` | `FileNotFoundError`(上传不存在)→404；`KeyError`/`ValueError`(meta 损坏)→400 | — |
| 309 | `upload_chunk` | `ValueError`(offset/size)→400；`FileNotFoundError`→404 | **保留 `finally: await file.close()`** |
| 327 | `upload_chunk_indexed` | 同 309 | 保留 finally |
| 337 | `upload_complete` | `FileNotFoundError`→404；`ValueError`→400 | — |
| 347 | `upload_resumable_complete` | 同 337 | — |
| 458 | `import_batch` | `ValueError`(不支持类型/空组)→400；`FileNotFoundError`(resolve_upload_path)→404 | 内部已对空 groups 显式 400 |
| 497 | `import_vector` | `FileNotFoundError`→404；`ValueError`→400；`QuotaExceededError`→507 | — |
| 523 | `import_vector_multipart` | `ValueError`→400；`FileNotFoundError`→404；`QuotaExceededError`→507 | **保留 `finally: shutil.rmtree(tmp)`**；文件落盘 `OSError` 应上抛 500 |
| 584 | `vector_feature_patch` | `ValueError`(非法 index/field)→400；`FileNotFoundError`→404 | — |
| 597 | `vector_feature_batch` | 同 584 | — |
| 607 | `vector_field_add` | 同 584 | — |
| 618 | `vector_field_delete` | 同 584 | — |
| 629 | `vector_rename_field` | 同 584 | — |
| 708 | `raster_inspect` | `FileNotFoundError`→404；`ValueError`→400 | — |
| 758 | `raster_commit` | `FileNotFoundError`→404；`ValueError`→400；`QuotaExceededError`→507 | — |
| 772 | `raster_detect_invalid` | `FileNotFoundError`→404；`ValueError`→400 | — |
| 785 | `import_document` | `FileNotFoundError`→404；`ValueError`→400 | `resolve_upload_path` 未完成抛 ValueError |
| 802 | `import_document_multipart` | `ValueError`→400；`FileNotFoundError`→404 | **保留 `finally: file.close()+rmtree`** |
| 825 | `document_ops` | `ValueError`(非法 op)→400；`FileNotFoundError`(会话缺失)→404 | — |
| 858 | `document_commit` | `ValueError`→400；`FileNotFoundError`→404 | — |
| 880 | `export_layer_endpoint` | `FileNotFoundError`(图层缺失)→404；`ValueError`(非法 format)→400 | — |
| 923 | `export_batch_endpoint` | `FileNotFoundError`→404；`ValueError`→400 | 已对空 layer_ids 显式 400 |

> **P1-b 的行为变更点（需主理人/架构师确认）**：未知异常当前 → 500 + `str(exc)`（可能含服务端路径，信息泄露）；收窄后 → 500 + "Internal server error"（全局处理器）+ ERROR 日志。HTTP 状态码不变（仍 500），响应体 `detail` 由 `str(exc)` 变为 "Internal server error"。建议判定为"信息泄露 bug 修复"。现有测试（`test_import_data_io.py` 为服务层测试、`test_error_handlers.py` 只测全局处理器 boom）未断言 router 层 500 的 `detail` 文案，回归风险低。

#### P2 — 有意宽捕获（保留 + 补注释/日志）

| 行号 | 端点 | 当前 | 期望 |
|---|---|---|---|
| 671 | `delete_imported_layer` | `except Exception: pass`（unregister_overlay 失败静默吞掉，无日志） | 保留宽捕获（删除主操作已成功，overlay 注销为尽力而为的清理），但补 `logger.debug`/`warning` 记录被吞异常 + 注释说明"故意最后防线" |
| 647 | `patch_imported_layer_display_name` | 已有 `except FileNotFoundError`+`except Exception` | 把 `except Exception` 作为"未知→上抛"处理（与 Group A 一致），或保留并补注释；建议前者 |

### 4.2 config_service.py（19 处）

> 此文件为**服务层**，函数返回值（如 `(bool, str)` 元组、dict）由 `config_routes.py` 翻译为 HTTP 响应。因此"不破坏对外行为"主要指：**返回值形状与成功/失败语义不变**；收窄的收益是"为真错误补 ERROR 日志"+"SSRF 校验异常类型精确化"。

#### P1 — 探测/测试函数：返回失败元组但未记录真错误日志 / 语义不一致

| 行号 | 函数 | 当前行为 | 期望行为 | 行为变更? |
|---|---|---|---|---|
| 361 | `test_api_key`(tianditu) SSRF 校验 | `except Exception as exc: return False,"出站 URL 校验失败"` | 收窄为 `except SSRFBlockedError as exc: ...`（+ `ValueError` 非法 URL）；非 SSRF 的意外异常落到外层 435 | 是(非 SSRF 异常文案由"出站 URL 校验失败"变为"测试失败"，更准确) |
| 390 | `test_api_key`(baidu) SSRF 校验 | 同 361 | 同 361 | 是 |
| 435 | `test_api_key` 外层兜底 | `except Exception as e: update_test_status("failed"); return False,"测试失败: {e}"`（无日志） | 保留作为测试端点最后防线，但**补 `logger.exception`** 记录意外错误（HTTP 响应不变） | 否（仅加日志） |
| 507 | `test_gee_account` | `except Exception as e: ...; return False,"测试失败"`（已有 `except ImportError` 在前，无日志） | 同上，补 `logger.exception` | 否（仅加日志） |
| 530 | `reload_gee_account_pool` | `except Exception as e: return False,0,"重载失败: {e}"`（无日志） | 补 `logger.exception`；返回值不变 | 否（仅加日志） |
| 1300 | `update_weather_provider`(apply_config) | `except Exception as e: logger.warning(...)`；但函数仍 `return get_weather_provider(...)` 即返回"成功" | 语义问题：运行时配置应用失败但对外返回成功。建议在返回 dict 中标注 `runtime_apply_error`（**待确认**，见 Q3），或至少提升 warning→error 日志 | 待确认 |
| 1598 | `test_remote_storage_profile` 外层 | `except Exception as exc: update_test_status("failed"); return failure`（已有 `SSRFBlockedError` 专捕在 1574） | 区分"探测失败(预期,返回 message)"与"意外异常(记 `logger.exception` 再返回 failure)"；返回形状不变 | 否（仅加日志） |

#### P2 — 尽力而为副作用（hydrate/sync/reload/purge/migrate）：已记日志，保留宽捕获 + 补注释

下表 12 处均为"主操作已成功后的副作用/启动期迁移/惰性注册"最佳努力清理，**已 `logger.exception`/`warning` 记录**，宽捕获合理。收窄动作 = 补注释说明"故意宽捕获 + 已记日志 + 不影响主流程"，可选地把 `except Exception` 收窄到更具体的 `(ImportError, OSError, ...)` 但非必须。

| 行号 | 函数 | 副作用 | 备注 |
|---|---|---|---|
| 186 | `upsert_api_key` | `hydrate_effective_config()` | 主操作(upsert)已完成 |
| 236 | `delete_api_key` | `hydrate_effective_config()` | 同上 |
| 279 | `toggle_api_key` | `hydrate_effective_config()` | 同上 |
| 307 | `_sync_api_config_manager_key` | 投影 key 到 ApiConfigManager | 见 Q2：同步失败可能留底图用旧 key |
| 519 | `_reload_gee_facade` | 重载 GEE facade | — |
| 1137 | `_ensure_weather_providers_registered` | 惰性注册默认天气源 | — |
| 1199 | `list_weather_providers` | 清理遗留 open-meteo DB 行 | — |
| 1384 | `delete_weather_provider` | 删除后重置 provider config | — |
| 1620 | `apply_persisted_provider_overrides` | 从 DB 加载覆盖 | 已 `return` 跳过 |
| 1648 | `apply_persisted_provider_overrides` | 遗留行清理迁移 | — |
| 1678 | `apply_persisted_provider_overrides` | 优先级迁移 | — |
| 1697 | `apply_persisted_provider_overrides` | 逐 provider 应用 config | — |

---

## 5. 不破坏约束清单（收窄前后必须等价的对外行为）

> 铁律：除下表"行为变更（判定为 bug 修复）"列外，其余端点的 HTTP 状态码、错误消息、错误码在收窄前后必须等价。

### 5.1 必须严格等价（不可变）

1. **客户端输入校验类 4xx**：所有 `ValueError`/`RuntimeError`（非法扩展名、空 upload_ids、非法 layer_id、不支持类型、非法 where/sort/format、上传未完成等）→ 收窄后仍必须返回 **400 + 原 `detail` 文案**。已有测试锁定：`test_reject_executable_extension`、`test_reject_zip_path_traversal`、`test_shp_sidecar_error_lists_received`、`test_import_batch` 空 groups 等。
2. **预期缺失 404**：`FileNotFoundError`（任务不存在、上传不存在/文件缺失、图层不存在、文档会话不存在）→ 收窄后仍 **404 + 原 `detail`**。
3. **配额超限 507**：`QuotaExceededError` → 仍 **507**。**排序约束**：507 分支必须在 400(RuntimeError) 分支之前命中（因 `QuotaExceededError(RuntimeError)`）。
4. **成功路径 200 + 响应体形状**：所有成功返回的 dict/Response/FileResponse 结构不变。
5. **Pydantic 422**：请求体校验失败仍由全局 `validation_exception_handler` 返回 422（这些不在本次收窄范围）。
6. **限流 429 + C429001 + Retry-After**：由中间件处理，不在本次收窄范围，不可受影响。
7. **鉴权 401/403 + C403001**：由 `require_write_access` 依赖处理，本次不触碰；收窄不得把鉴权异常吞成 200/4xx。
8. **config_service 返回值形状**：`(bool, str)` 元组、dict 结构、`success/message/tested_at` 字段不变（仅允许新增可选字段，见 Q3）。
9. **`finally` 清理块**：`upload_chunk`(309)、`upload_chunk_indexed`(327)、`import_vector_multipart`(523)、`import_document_multipart`(802) 的 `finally: file.close()/rmtree` 必须保留，收窄不得破坏资源释放。
10. **`request_id` 透传**：所有错误响应仍包含 `request_id`（全局处理器与 `http_exception_handler` 已保证）。

### 5.2 明确的行为变更（建议判定为 bug 修复，需主理人/架构师签字确认）

| 变更 | 触发条件 | 前 | 后 | 判定理由 |
|---|---|---|---|---|
| 5xx 响应体 `detail` | router 未知异常（IO/序列化/编程错误） | 500 + `str(exc)`（可能含服务端路径） | 500 + "Internal server error" + ERROR 日志 | 信息泄露修复；状态码不变；与全局处理器契约一致（`test_internal_error_includes_request_id` 已锁定全局 500 文案） |
| 损坏任务文件 404→500 | `get_job` 读到损坏 json（`JSONDecodeError`） | 404（被 `not_found=True` 误判） | 500 + 日志 | 真故障不应伪装为"不存在" |
| 图层/文档非缺失异常 404→500 | `load_vector_*`/`preview_document_session` 抛非 FileNotFoundError | 404 | 500 + 日志 | 同上 |
| SSRF 校验意外异常文案 | `validate_outbound_url` 抛非 `SSRFBlockedError` | "出站 URL 校验失败" | 落到外层"测试失败: {e}" | 文案更准确，区分"被拦截"与"校验自身出错" |

---

## 6. 测试陪护要求（每类收窄模式须有覆盖）

1. **预期缺失路径**：缺失任务/上传/图层/文档会话 → 断言 404 + 原 detail。
2. **客户端校验路径**：非法扩展名/空 upload_ids/非法 where/不支持类型 → 断言 400 + 原 detail（回归现有 `test_import_data_io.py` 用例不破）。
3. **配额路径**：触发 `QuotaExceededError` → 断言 507（验证 507-before-400 排序未被破坏）。
4. **真错误路径（新增）**：注入损坏任务 json / mock 服务抛 `OSError` → 断言 500 + `detail=="Internal server error"` + `request_id` 存在 + 日志产出。
5. **config_service 探测失败**：mock `validate_outbound_url` 抛 `SSRFBlockedError` → 断言 `(False, "出站 URL 校验失败...")`；mock 抛意外 `RuntimeError` → 断言 `(False, "测试失败...")` 且有 ERROR 日志。
6. **现有回归**：`test_import_data_io.py`、`test_error_handlers.py`、`test_error_codes.py`、`test_config_*` 全绿。

---

## 7. 待确认问题（需主理人/架构师决策）

- **Q1（核心）**：router 未知异常由"500 + `str(exc)`"改为"500 + Internal server error（全局处理器）"，是否确认为可接受的 bug 修复（信息泄露修复）？还是要求保留 `str(exc)` 仅补日志（即收窄时保留末尾 `except Exception as exc: logger.exception(...); raise _http_err(exc)`）？此决定影响全部 P1-b 24 处的收窄形态。
- **Q2**：`_sync_api_config_manager_key`(307) 同步失败时底图 provider 可能持有旧 key，当前仅 warning。是否需要在 P2 基础上提升为 P1（对外提示"key 已保存但运行时同步失败，可能需重启"）？
- **Q3**：`update_weather_provider`(1300) apply_config 失败但返回成功，是否在返回 dict 增加 `runtime_apply_error` 可选字段暴露给前端？这属新增字段（不破坏契约），但需产品确认 UI 是否消费。
- **Q4**：Group B（`not_found=True` 强转 404）的 7 处中，`import_job_*` 3 处是否一并纳入 P0？还是仅 `import_job_status` 为 P0、其余因使用频率低降为 P1？（当前方案：3 处 import_job_* 列 P0，4 处图层/文档列 P1）
- **Q5**：是否允许在 `router.py` 顶部新增一个共享的具体异常类型别名（如 `from app.data_io.services.paths import QuotaExceededError` 已有），或新增一个 `DataIoError` 基类统一业务异常？建议**不新增**（增量原则），复用现有 `FileNotFoundError`/`ValueError`/`RuntimeError`/`QuotaExceededError`。请确认。
- **Q6**：`delete_imported_layer`(671) 的 `except Exception: pass` 是否可接受改为 `except Exception: logger.debug(...)`（debug 级避免日志噪声）？还是要求 warning 级？
