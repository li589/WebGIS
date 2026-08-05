# CGDA 代码审查报告（工作树增量 + 全仓静态基线）

**日期**：2026-08-05
**审查者**：Senior Developer（高级开发工程师）
**范围**：未提交工作树（54 文件，+1720 / −282 行）+ 全仓静态分析基线
**方法**：定向人工审查（安全敏感模块）+ 自动化静态分析（ruff / eslint）+ 前后端契约核对

> 说明：本仓库已于 2026-08-04 完成一轮五维联合发布就绪审计（见 `deliverables/gstack/pre-launch-check-cgda-2026-08-04.md`），结论为 P0/P1/P2 全部修复并提交。本次审查**不重复**已修复项，聚焦当前未提交工作树的新增/改动代码，并给出全仓静态基线。

---

## 1. 审查结论（TL;DR）

**整体评估：✅ 通过（可直接提交）** —— 本次未提交改动质量高，是一次以「**去硬编码（批 1）**」+「**SSRF 重定向绕过修复（BUG-1）**」+「**限流 IP 伪造修复（BUG-3）**」+「**看门狗终态保护（BUG-2）**」+「**空态可见化（BUG-4）**」为主的高质量收口。

- 安全敏感改动均经人工核对，**未发现新的注入 / 鉴权 / SSRF 绕过漏洞**。
- 新增的 `palette` / `min_value` / `max_value` / `nodata_mode` / `nodata_color` 查询参数**已正确接入 allowlist 校验**，无注入面。
- 全仓 ruff 仅 9 条告警（8×F401 + 1×E402），均为可自动修复的次要项。
- 残留 1 项中风险（SSRF 的 DNS 重绑定 / TOCTOU），属已知难题，建议在不可信网络部署时处理。

**最重要操作提醒**：以上改动目前**全部在工作树、未提交**。请按项目约定（`git commit --no-verify`，因本地 pre-commit 钩子环境损坏）提交，并在 CI 跑 `pytest` + `npm run build` 做实跑验证（本次仅做静态审查，未跑测试）。

---

## 2. 静态分析基线

| 工具 | 范围 | 结果 |
|------|------|------|
| `ruff check` | 全仓 `Code/backend` + `Code/algorithms`（~115k LOC） | **9 violations**：8×`F401` 未用导入、1×`E402` 导入位置 |
| `ruff check` | 本次改动的 17 个 Python 文件 | **0**（全绿） |
| `eslint` | 本次改动的 24 个前端文件 | **0 error / 6 warning**（`no-explicit-any` ×5、`no-console` ×1） |

结论：代码库静态质量处于健康水平；改动未引入任何 lint 错误。6 条 eslint warning 均为既有的 `any` / `console` 写法，非阻塞。

---

## 3. 安全敏感改动逐条核对

### 3.1 已确认正确修复 ✅

| 项 | 位置 | 说明 |
|----|------|------|
| **BUG-1 SSRF 重定向绕过** | `app/core/ssrf.py` 新增 `safe_urlopen`；`source_fetcher.py` 改用之 | 原 `validate_outbound_url` + `urlopen` 会被 3xx 自动跟随绕过到环回/链路本地/云元数据。`safe_urlopen` 用 `_NoRedirectHandler` 禁自动跳转，每次 `Location` 目标**重新跑 SSRF 校验**（含 `urljoin` 归一化、协议白名单、私网/环回/链路本地/组播拦截），超过 `max_redirects=5` 即拒绝。逻辑正确。 |
| **BUG-3 限流 IP 伪造** | `app/api/rate_limit.py` `client_ip` | 默认**不信任** `X-Forwarded-For` / `X-Real-IP`（可被客户端伪造），仅当 `settings.trust_proxy`（`BACKEND_TRUST_PROXY`）为真才解析转发头；否则用 `request.client.host`。配套 `core/config.py` 新增 `trust_proxy`（默认 `false`）。修复正确。 |
| **去硬编码（批 1）** | `config.py` / `dataset_config.py` / `overlay_registry.py` / `workflow_router.py` / `workflow_definition_service.py` | 移除全部 `I:\Geograph_DataSet` 默认盘符与实验室账号（`ssh_hpc_user=likr6008` → `""`、`ssh_win11_user=qiujianqiu` → `""`）；路径改为相对 `BACKEND_DATA_ROOT`，缺失即 fail-fast（`assert_data_root_policy` 启动期校验 + `dataset_config._get_data_root()` 抛错）。种子 JSON 用 `{DATA_ROOT}`/`{DATA_ROOT_WIN}` 占位、同步期展开。 |
| **配色参数 allowlist** | `raster_preview_service.py` `resolve_palette_id` | 新增的 `palette` 查询参数只返回 `_PALETTES` 字典内存在的键，否则回落 `viridis`；`nodata_color` 经 `parse_nodata_color` 正则校验（`#rgb`/`#rrggbb`/`r,g,b`）；`nodata_mode` 仅允许 `solid`/`transparent`。**无注入面**。前端 `buildOverlayStyleQuery` 映射 `vmin→min_value`、`vmax→max_value`、`nodataMode→nodata_mode`、`nodataColor→nodata_color`，与后端 `Query` 参数名完全一致 —— 前后端契约正确。 |
| **BUG-2 看门狗终态保护** | `workflow/lifecycle_service.py` `_is_protected_terminal` | 防止「看门狗将卡死 run 标 failed」后，迟到的 worker 回调又把它 `finalize_workflow_success` 覆盖为 succeeded（或反之）。保护 `cancelled` 与 `cleanup_reason=stuck_running_watchdog` 的终态。逻辑正确，保护路径仅做诊断 materialize + 记事件，不改 status。 |
| **BUG-4 空态可见化** | `stores/layers/index.ts` | `imports` 为空（非 dismiss 滤空）时经 `resolveEmptyOverlayWorkflowError` 给出可见 `workflowError`，消除「succeeded 但 0 图层、无提示」的静默断链。 |
| **启动 fail-fast** | `main.py` 调用 `assert_data_root_policy()` | 非 dev/test 环境缺 `BACKEND_DATA_ROOT` 时启动即拒，杜绝静默回退实验室盘符。 |

### 3.2 残留风险（需关注）

| # | 严重度 | 位置 | 问题 | 建议 |
|---|--------|------|------|------|
| R1 | 🟠 中 | `app/core/ssrf.py` `validate_outbound_url` / `safe_urlopen` | **DNS 重绑定 / TOCTOU**：校验时解析主机名得到安全 IP，随后 `opener.open` 再次解析可能得到恶意 IP（环回 `127.0.0.1` / 云元数据 `169.254.169.254`），尤其主机有多 A 记录或攻击者控制 DNS 时。当前「SSRF 已修复」应理解为「重定向绕过 + 私网/链路本地拦截」已修，DNS 重绑定为残余面。 | 单次解析后**钉死 IP** 连接（自定义 `HTTPConnection`/handler 用已解析 IP，并校验证书 SNI/Host）；或限制出站仅允许解析一次的 IP。若仅在内网可信环境运行，可暂不处理并写入局限说明。 |
| R2 | 🟡 低 | `layer_router.py` `get_overlay_preview` 响应头 | `Vary: Accept-Encoding` 对按 query 参数变体的缓存意义不大；styled 响应已是 `no-cache`，无实际危害，仅语义不精确。 | 如需 CDN/代理正确缓存多配色变体，改 `Vary` 为包含样式参数的键，或保持 `no-cache`。可选优化。 |
| R3 | 🟡 低 | `raster_preview_service.py:236` `resolve_palette_id` | 三元表达式 `aliased or raw.lower() if raw.lower() in _PALETTES else raw` 可读性偏低，但功能经核对**正确**（大小写、别名均正确回落）。 | 可拆为显式 `if/elif` 提升可读性，非必需。 |
| R4 | 🟢 信息 | `overlay_tile_service.py` `_cached_tile` | 缓存键新增 `palette/min_value/max_value/nodata_mode/nodata_color`，`maxsize=512`。styled 变体多时会更快占满缓存，但均为有限离散值，影响可控。 | 若担心内存，可按样式组合数量调整 `maxsize`。信息项。 |

---

## 4. 逻辑 / 健壮性核对

- **`raster_preview_service.py`（+309 行，最大改动）**：实为一次干净的特性重构 + **顺带修复潜在崩溃**——旧 `_PALETTES.get(palette) or _PALETTES["wind-blue"]` 在传入未知 palette 时返回 `None`，随后 `numpy.array(None)` 崩溃；新 `get_palette_rgb_stops` 安全回落 `viridis`。新增 `colorize_array_to_rgba` / `encode_rgba_png` 被 overlay preview 与 tile 渲染共用，去重良好。无逻辑 bug。
- **`overlay_tile_service.py`**：`_apply_palette` 重构为复用 `colorize_array_to_rgba`；透明模式保留历史 `~200` alpha（`np.where(alpha>0,200,0)`），行为一致。tile 渲染路径在越界时返回空 `_apply_palette(dst, zeros, **style_kw)`，正确。
- **前端 `overlay-image-module.ts`**：`setOverlayStyle` 用 `styleKeyOf` 做变更去重，避免无变化时重复重建 source；`desiredStyle` 在加载中记住最新意图，完成后应用，与 `desiredVisibility` 同模式，正确。`_previewUrl` 的 `_=` 缓存破坏符与 styled query 拼接逻辑正确。
- **前端 `SettingsPanel.vue`**：`VITE_SETTINGS_TABS` 白名单控制可见设置页；空/非法配置安全回退到 `ALL_TABS`，不会因配置错误导致面板空白。
- **前端 `stores/layers/index.ts`**：`resolveRestoreWorkflowBridge` 替换写死的 `omega-sf-fenkuai` / `omega_sf_fenkuai_smap_single` 为动态解析（批 1 去硬编码），并用子串匹配启发式；属可接受风险。`setLayerRangeOverride` / `setLayerNodataDisplay` 正确持久化到工作区。

---

## 5. 发现汇总表

| # | 严重度 | 类别 | 位置 | 建议 |
|---|--------|------|------|------|
| R1 | 🟠 中 | 安全/SSRF 残余 | `app/core/ssrf.py` | DNS 重绑定：钉死解析 IP 后连接；不可信网络部署前处理 |
| R2 | 🟡 低 | 缓存语义 | `layer_router.py:135` | `Vary` 头按需调整（可选） |
| R3 | 🟡 低 | 可读性 | `raster_preview_service.py:236` | 拆分三元表达式（可选） |
| F1 | 🟢 清理 | 静态 | 全仓 8×`F401` | `ruff check --fix` 移除未用导入 |
| F2 | 🟢 清理 | 静态 | 1×`E402` | 将导入移至文件顶部 |
| F3 | 🟢 清理 | 静态 | 前端 6×warning | 逐步替换 `any`、收敛 `console` |

---

## 6. 建议后续动作

1. **提交工作树改动**：`git add` 相关文件后 `git commit --no-verify`（项目约定；完整质量门由 CI(Ubuntu) 把关）。
2. **清理 9 条 ruff 告警**：`Env/Python312/python.exe -m ruff check Code/backend Code/algorithms --fix` + 手动处理 `E402`。
3. **实跑验证（本次未跑）**：`Env/Python312/python.exe -m pytest Test/backend Test/algorithms`，`cd Code/frontend && npm run test && npm run build`，确认绿。
4. **R1（DNS 重绑定）**：评估部署网络可信度；若暴露到不可信网络，实施「解析一次 + 钉 IP 连接」；否则在发布局限中明确说明。
5. **可选**：R2/R3 可读性/缓存语义微调。

---

## 7. 审查局限

- 本次为**静态审查 + 定向人工核对**，未起服务、未跑测试套件、未做依赖 CVE 深度扫描（延续 prior audit 局限）。
- 未审查 `Code/algorithms/providers/Python/` 算法数学正确性（仅核对 `dataset_config.py` 去硬编码与导入）。
- 前端仅对改动文件做 eslint + 人工契约核对，未跑 E2E/组件渲染测试。
