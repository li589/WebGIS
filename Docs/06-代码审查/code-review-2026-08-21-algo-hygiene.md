# 算法包与管理卫生审查（2026-08-21）

- 审查人：Explore-3（代码审查专项）
- 范围：`Code/algorithms/providers/Python`（重点 `ingest/`、`modules/`、`workflow/`、`runner/`、`data_access/`）、`Tools/`、`launch/`、`launch.py`、`README.md`、`AGENTS.md`
- 方式：只读静态审查（grep 模式扫描 + 关键文件全文精读 + 交叉引用验证），未运行任何修改性命令
- 结论摘要：**无 P0**。算法包整体卫生水平高（零 TODO 残留、路径消毒齐备、凭据不入日志）；发现 5 项 P1（1 项重复实现、2 项并发共享态、1 项 VCS 明文口令、1 项 TLS 策略不一致）与 10 项 P2。

## P0（如有）

无。专项排查未发现：

- 凭据泄漏到日志/异常消息：全链路 grep `password|token|api_key` 结合各 logger 调用点逐一核对，密码/token 均不进入 logger、print 或异常文本（`nsidc_download.py` 仅记录用户名，见 P2-2）。
- 算法包内 `verify=False` 的 requests 调用：不存在。`data_access/sources/http.py` 的 TLS 放宽为**按域 allowlist**（默认仅 `satellite.nsmc.org.cn`，env `CGDA_HTTP_INSECURE_HOSTS` 可控，且每次放宽打 warning）——这是正确模式；`ingest/nsmc_portal.py` 的做法见 P1-5。
- 路径穿越：`ingest/remote_sync.py` 有 `sanitize_rel_path`（拒绝 `.`/`..`、Windows 保留设备名、非法字符）；`data_access_nodes.py` 的 `_is_safe_archive_member` 有完整 zip-slip 防护（绝对路径/`../`/盘符/`resolve()+relative_to` 校验）；各下载器落盘文件名均取自远端 URL basename（`url.split("/")[-1]`，不含路径分隔符）。`cdse_download.py:368` 的 filename 可来自 `search_results` 条目的 `title`（用户可控），理论可含 `..\`，但 `target_dir` 本身就是同一用户可控的节点参数，无权限面升级——记为设计已知边界，不单列。

## P1

### P1-1 `nsidc_download.py` 保留私有续传/重试副本，绕过共享 `_http_resume.py`

`ingest/nsidc_download.py:451-546` 的 `_download_single` / `_download_with_retry` 是 `ingest/_http_resume.py` 的 `download_resumable` / `download_with_retry` 的近乎逐行复制（`_http_resume.py` 的 docstring 明言"从 nsidc_download.py 提取"——提取后原文件未删除私有副本）。该文件只从共享模块 import 了 `check_disk_space` / `format_size`（47-50 行），续传主逻辑仍走私有副本。

后果：

- **语义分叉**：`gldas_download.py:247-266` 在共享工具上叠加了 `.part` 临时文件 + 原子替换（避免部分下载文件污染"已存在即跳过"判断）；nsidc 私有副本**没有**此保护——SMAP 下载中断留下的半成品 `.h5` 会被下次任务的增量过滤（`nsidc_download.py:633` `fp.stat().st_size > 0` 即跳过）误判为已完成。
- **死参数**：`_download_with_retry`（525 行）声明 `expected_size_mb: float | None = None`，函数体从未使用，调用方 668 行仍传 `g.size_mb`——复制粘贴陈旧化的直接证据。
- 共享工具后续修复（如 416 语义调整）不会自动传播到 nsidc 路径。

建议：删除私有副本，改用 `_http_resume.download_with_retry` + gldas 同款 `.part` 原子替换（可直接复用 `gldas_download._download_with_retry` 的模式，或将其上提为 `_http_resume` 的通用封装）。

### P1-2 `push_runtime_call` 对共享 `runtime_context.call_chain` 的无锁 check-then-act（并发）

`runner/call_guard.py:22-36` 对 `runtime_context.call_chain`（普通 list）做 `entry in chain` 检查 → `append` → `finally: pop()`，全程无锁。`runtime_context` 在同层并行节点间**共享**（`workflow/executor.py:96-105` 各线程拿同一个 `runtime_context`）：

- `workflow/bridge.py:95`（bridge.pipeline 节点）与 `modules/compat.py:96`（兼容 shim 模块）都会在节点执行内再调 `push_runtime_call`。当 `CGDA_WORKFLOW_NODE_PARALLELISM > 1`（`runner/dispatch.py:738-748` env 注入）且同层存在两个 shim/bridge 节点时：
  - 两线程若 push 相同 entry → 第二个线程假阳性抛 `Recursive runtime call detected`；
  - 交错 push/pop → `pop()` 弹掉对方条目，链内容损坏，后续深度/重入判断失真；
  - `len(chain) >= MAX_CALL_DEPTH` 检查与 append 非原子。

建议：`call_chain` 改为 `threading.local` 栈或用锁保护；至少在 `RuntimeContext` 上为并行节点派生 per-thread 副本。

### P1-3 并行同层节点共享同一 `workspace`，下载节点子目录写死（并发）

`workflow/executor.py:169` 为所有节点构造 `NodeExecutionContext(workspace=Path(runtime_context.workspace))`——同一 run 内**所有节点共享同一 workspace 路径**。而 `modules/download_nodes.py` 的各节点落盘子目录是固定名：

- 301 行 `ctx.workspace / "data_access" / "ssh_sync"`
- 464 行 `ctx.workspace / "data_access" / "smap_download"`
- 604 行 `ctx.workspace / "data_access" / "gldas_download"`
- 733 行 `ctx.workspace / "data_access" / "gldas_mat"`
- 886 行 `ctx.workspace / "products" / "fy_preprocess"`

当 `CGDA_WORKFLOW_NODE_PARALLELISM > 1` 且同层存在两个同型下载节点（如两段日期范围的 SMAP 下载）时，两线程写同一目录：增量过滤会互相把对方**正在下载的半成品**判为已存在而跳过（与 P1-1 的无 `.part` 保护叠加放大），极端情况下两线程对同一文件并发 `open("ab")` 追加导致内容损坏。

另：`executor.py:150-153` docstring 声称"每个节点拥有独立的 NodeExecutionContext.workspace 与 artifact 路径"——**与实现不符**（artifact_id 含 node_id 确实隔离，workspace 不隔离），注释误导后续维护者。

建议：workspace 取 `runtime_context.workspace / node_id`（或至少下载类节点）；同步修正 docstring。

### P1-4 `Tools/SyncData.py`（git 跟踪文件）注释中含真实明文口令

- 26/33 行：`"password": "wnai168618"`（配 `172.18.206.109` / `user03`，HPC 账号）
- 88 行：`"password": "Qiujianxiu.123456"`（配 `222.200.176.12` / `Teacher`）

虽为注释掉的配置模板，但均为真实账号口令且已进入 git 历史（`git ls-files` 确认跟踪）。虽然任务口径"Tools 硬编码可容忍"针对的是盘符/verify=False 类联调配置，**真实口令入库**不在此容忍范围。建议：轮换上述两账号口令；从工作区删除明文（替换为占位符）；如需彻底清除须重写历史（`git filter-repo`）或确认仓库永不外发。

### P1-5 `nsmc_portal.py` 模块级 `CERT_NONE` 作用于客户端全部流量（含登录链路）

`ingest/nsmc_portal.py:51-53` 模块级 `_SSL_CONTEXT` 关闭主机名校验与证书校验，用于该 client 的**所有**请求——包括携带 RSA 加密口令的登录 POST（341 行）与跨域 tokensync。有注释说明原因（NSMC 自签证书链，实测 CERTIFICATE_VERIFY_FAILED）且流量仅限 nsmc.org.cn 三个子域，但：

- 会话 cookie（SHIRO）经不校验通道传输，MITM 可劫持登录态；
- 同仓库 `data_access/sources/http.py:20-66` 已沉淀了更优模式（按域 allowlist + `CGDA_HTTP_INSECURE_HOSTS` env + warning 审计日志），两处策略不一致。

建议：对齐 http.py 的模式（域名白名单化），或对 NSMC 证书做指纹固定（pinning）；至少复用同一个 env 开关与 warning 日志，避免"两套 TLS 放宽口径"。

## P2（记录不修：TODO 清单/文档过时/死代码）

1. **requests.Session 从不 close**（资源卫生）：`ingest/cds_download.py:151`、`cdse_download.py:261,420`、`gldas_download.py:174`、`nomads_download.py:163`、`nsidc_download.py:219,363,445` 共 8 处裸 `requests.Session()`，无 with/close。单次调用量小、GC 可回收，实际风险低；建议统一 `with requests.Session() as s:` 或模块级复用。
2. **用户名入 info 日志**：`nsidc_download.py:205` `logger.info("测试 Earthdata 认证（用户: %s）...", username)`。非口令，轻度 PII，可降为 debug。
3. **token 缓存以明文账密作 key**：`modules/data_access_nodes.py:341` / `413` `cache_key = f"{username}:{password}"`，`_urs_token_cache` / `_cdse_token_cache` 为模块级 dict，明文口令以 key 形式滞留进程整个生命周期（token 有 TTL 但 key 不过期）。建议 key 改用 `sha256(username:password)` 摘要。并发上 dict 读写为 GIL 原子、TTL 竞争良性，无正确性问题。
4. **死代码：`debug_station.py`**：包根目录的遗留调试脚本（print 调试、硬编码 `d:/Workspace/mat2py/test_debug.stm`、import 私有 `_split_tokens`），全仓库无引用（仅自身）。建议删除或移入 `Test/debug/`。
5. **文档过时：README.md 失效链接**：154 行 `详见 [Doc/本地联调环境说明.md](Doc/本地联调环境说明.md)`——`Doc/` 目录已不存在（46 行自述"原 Doc/ 已全部并入 .ai/"），链接 404，且与同段自述矛盾。应改指 `.ai/` 内对应文档。
6. **UI 占位符硬编码 D:/ 盘符**：`workflow/ui_metadata.py:78-105` `_FIELD_PLACEHOLDERS` / `_FIELD_EXAMPLE_OVERRIDES` 含 `D:/data/input/` 等 Windows 路径。仅作输入框 placeholder/示例展示，无功能影响，但与项目"禁止盘符回退/数据根真源在 .env"的口径不一致，Linux 用户观感差。建议改中性示例（如 `/data/input`）。
7. **Matlab 提供方遗留脚本裸 `except: pass`**：`providers/Matlab/fy拼接/FY3B.py`（7 处）、`FY3d.py:377`、`FY3F_MWRI_mosaic.py:391` 为不带 `Exception` 的裸 `except: pass`。属历史参考代码（Python 包 `algorithms/` 内的同类均为窄化 `except ValueError: pass`，合规）；若这些脚本仍会被拼接链路调用，需补日志。
8. **Tools 硬编码环境（容忍记录）**：`Tools/sync_server_data.py:190-214` `host="172.16.98.184"`、`username="likr6008"`、108 行跳板 `ssh -W 172.16.98.184:22 win11-lab`；`Tools/SyncData.py:38-48` 公网 IP `121.46.19.4:6666` + 本机私钥路径。按"Tools 联调可容忍"口径记录备查，不要求修改。
9. **死参数**：`nsidc_download.py:525` `expected_size_mb`（见 P1-1，单列备忘：若暂不动私有副本，至少清理该参数与 668 行的传参）。
10. **本地工作区卫生**：仓库根有 31 个 `.pytest_tmp_*` 目录、一个 `nul` 文件（Windows 重定向产物）与 `p1_test_import.geojson`。均**未被 git 跟踪**（已验证），仅本地脏污；建议本地清理并在 `.gitignore` 补 `.pytest_tmp_*/` 与 `nul`。

**TODO/FIXME 统计**：`Code/algorithms` + `Tools` + `launch` 全范围 `.py` 文件中真实 TODO/FIXME/HACK/XXX 标记 **0 处**（匹配到的均为 `EPSG:XXXX` 字面量等误报；唯一真实 TODO 在 `Code/backend/app/services/source_fetcher.py:33`，属后端范围）。无 stale TODO 问题——这是显著的正向发现。

## 审查覆盖说明

**已覆盖**：

- `ingest/` 全部 22 个文件：`_http_resume`、`nsidc_download`、`gldas_download`、`cdse_download`、`cds_download`、`nomads_download`、`nsmc_portal`、`remote_sync`（全文精读）；`fy`、`smap`、`fy_preprocess`（GDAL 全局段）、`station`/`ndvi` 等（结构扫描 + 关键段）
- `modules/`：`registry`（全文）、`download_nodes`（workspace/凭据流）、`data_access_nodes`（token 缓存/压缩包安全/HTTP 凭据头）、`compat`（push_runtime_call 调用点）
- `workflow/`：`executor`（全文，并行路径）、`module_executor`、`registry`、`schemas`、`artifact_store`、`ui_metadata`
- `runner/`：`call_guard`（全文）、`dispatch`（WorkflowRunner 构造与并行度注入段）
- `data_access/sources/http.py`（全文，TLS 策略对照）
- `Tools/`：`SyncData.py`、`sync_server_data.py`、`merge_file.py`（精读）；其余按模式扫描（TODO/口令/IP/verify=False/open()）
- `launch/`：结构 + 端口常量 + 盘符扫描（与 README/AGENTS 声明交叉验证）
- 文档核对：README.md 全文、AGENTS.md 全文；抽查 AGENTS.md 声称的 11 个验证目标（`Test/backend/test_weather_tile_service.py` 等 6 个测试文件、`Tools/README.md`、`Code/infra/gateway/README.md`、`Docs/README.md`、`.github/workflows/ci.yml`、`.pre-commit-config.yaml`）**全部真实存在**；launch.py 子命令（start/stop/status/restart/logs/flush/clean-cache/reset-db/sync）与 `launch/cli.py` 注册一致；端口 5175/8000 与 `launch/constants.py`、`gateway_manager.py` 一致。

**避免误报已核实的正向设计**（不列为问题）：

- GLDAS 路径漂移回退（overlay_registry）——已知设计
- 算法包循环导入经"顶部 import contracts 破环"规避——已知设计
- FY3F 3D 数组抽通道、ORBA 升轨——业务约定
- `remote_sync.py` 的 `sanitize_rel_path` 路径消毒、`ServerConfig` 工厂默认值移除（fail-fast）
- `http.py` TLS 按域 allowlist + env + warning
- `data_access_nodes._is_safe_archive_member` zip-slip 防护
- `executor.py` 并行路径的快照隔离 + `progress_lock` + 快速失败取消（除 P1-2/P1-3 两处共享态外设计正确）
- `modules/registry` 自动加载失败打 warning 不静默
- 无凭据进日志/异常（全链路验证）

**未覆盖/超出本审查范围**：后端 `Code/backend/`（由安全与并发专项覆盖）、前端 `Code/frontend/`（由 UI 专项覆盖）、`algorithms/omega_sf.py` 等数值正确性（已由 2026-08-18 数值专项覆盖）、Matlab `.m` 源码本体。
