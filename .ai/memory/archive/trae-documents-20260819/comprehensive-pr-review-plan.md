# 全面代码审查计划 — 3 Bug 修复变更集

> 审查框架：Staff Engineer Mode → `agent-pr-review` specialist
> 变更范围：3 个 bug 修复，约 16 个文件（前端 TypeScript/Vue/CSS + nginx 配置）
> 审查目标：不放过一个地方，覆盖意图匹配、失效模式、行为验证、质量维度、契约影响、缺失产物、专项检查 7 大维度

---

## 一、审查范围界定

### 1.1 变更分组与文件清单

本 PR 含 3 个独立 bug 修复，审查按 bug 分组隔离，避免交叉污染判断。

**变更组 A — Bug 1：配色方案切换回原配色无变化（4 文件，逻辑变更）**

| 文件 | 变更性质 | 审查权重 |
|------|---------|---------|
| `Code/frontend/src/components/map/overlay-image-module.ts` (~L833) | 移除 `forceStyle` 门控，改为有 style 入口就调用 `setOverlayStyle`（内部 styleKey 比较防重复） | 高（核心逻辑） |
| `Code/frontend/src/stores/layers/types.ts` (~L358) | `ActiveLayerDisplay` 新增 `defaultPalette?: string` 字段 | 中（契约） |
| `Code/frontend/src/stores/layers/display-projection.ts` (~L351) | 从 `baseRenderHint?.palette` 设 `defaultPalette`（不含 override 的原始默认配色） | 高（数据源） |
| `Code/frontend/src/components/info-panel/useLayerSymbology.ts` (~L236) | `handleSelectPalette` 改用 `defaultPalette` 替代含 override 的 `weatherRenderHint.value?.palette` | 高（消费方） |

**变更组 B — Bug 2：浅色模式刷新呈现褐色（12 文件，纯样式替换）**

将 12 个文件中的 `background: var(--text-*)` 替换为 `var(--surface-*)`：
- Toggle 旋钮/滑块凸起元素 → `var(--surface-3)`
- 装饰性指示点/idle 状态 → `var(--surface-sunken)`

涉及文件：`MapCanvas.styles.css`、`LoginView.vue`、`InfoPanel.styles.css`、`ApiKeySettings.vue`、`GeeAccountSettings.vue`、`WeatherProviderSettings.vue`、`PanelDock.vue`、`WorkflowInspector.vue`、`WorkflowTimerPanel.vue`、`SshSyncForm.vue`、`ParamField.vue`、`WorkflowStatusButton.vue`

**变更组 C — Bug 3：分析工具 404（1 文件，配置）**

| 文件 | 变更性质 |
|------|---------|
| `Code/infra/gateway/nginx.conf` (~L35) | 代理白名单正则追加 `\|analysis` |

### 1.2 审查边界与排除项

- 不审查未变更的周边逻辑，但需验证变更点的调用方/被调用方未被破坏
- 不对 bug 成因做最终裁定（属审查结果），仅界定需验证的假设
- `forceStyle` 字段本身仍保留在 `OverlayStyleParams` 接口与 `styleKeyOf` 中 — 审查需确认其是否成为死代码或仍有用

### 1.3 Scope Creep 检查基线

逐组核对：变更是否严格限定在 3 个 bug 范围内，有无借机重构、无关格式化、未声明的新依赖或配置漂移。

---

## 二、逐文件审查要点

### 变更组 A 逐文件要点

#### A1. `overlay-image-module.ts`（~L833，syncOverlays）

**Intent Match**
- 确认改动确实将原 `forceStyle` 门控替换为 `if (styleByLayerId?.[layerId])`，且仅此一处行为变更
- 确认未顺手修改 `_addOverlay`、`_normalizeStyle`、`styleKeyOf` 等关联逻辑（若有则属 scope creep）

**Failure-Mode Pass（重点）**
- **truthy 陷阱**：`styleByLayerId[layerId]` 是对象字面量，几乎恒为 truthy。审查需确认：这是否意味着每次 `syncOverlays`（任何图层变动触发）都会对每个已加载图层调用 `setOverlayStyle`。若如此，性能影响与冗余渲染需评估
- **styleKey 防重复有效性**：`setOverlayStyle`（L963-964）以 `styleKeyOf(style) === loaded.styleKey` 跳过。审查需验证以下场景的 styleKey 变化：
  - 场景1：用户选 override palette A → styleKey 含 `A|...|forceStyle=1`
  - 场景2：切回默认（paletteOverride=null）→ 调用方传入 `palette=undefined, forceStyle=false` → styleKey 含 `|...|forceStyle=0`
  - 确认场景1→2 的 styleKey **必然不同**（palette 段 + forceStyle 段均变），否则修复无效
- **加载态 vs 同步态 forceStyle 不一致**：`_addOverlay`（L727-729）对 supports_recolor 且无 palette 的层强制 `style.palette=meta.palette; forceStyle=true`。而 syncOverlays 传入 `palette=undefined; forceStyle=false`。这意味着**首次 syncOverlays 必然触发一次 setOverlayStyle**（即使该层从未被用户改过配色），导致瓦片 URL 从 `?palette=meta.palette` 重写为无 palette 参数。审查需确认：
  - 服务端在**无 palette 参数**时的默认配色是否严格等于 `meta.palette`，否则会产生一次"默认→默认"的视觉闪烁
  - 是否存在反复触发（每次 sync 都因 forceStyle 差异重渲染） — 需确认 setOverlayStyle 写入 `loaded.styleKey` 后会稳定
- **desiredStyle 副作用**：`setOverlayStyle`（L960）无条件执行 `desiredStyle.set(layerId, style)`，即便 styleKey 相同也会写入。审查需确认 desiredStyle 的下游消费者不会因此产生意外行为，且与 L825 的 `desiredStyle.set` 是否重复冗余
- **未覆盖边界**：
  - `styleByLayerId[layerId]` 为 `undefined`（该层无 style 入口）时是否仍需清除已应用的 override 样式？当前逻辑跳过 setOverlayStyle，可能遗留旧样式
  - 图层从有 override 的源切换到不支持 recolor 的源时，残留 palette 是否被清理

#### A2. `types.ts`（~L358，ActiveLayerDisplay.defaultPalette）

**Intent Match**
- 确认仅新增 `defaultPalette?: string` 字段及注释，无其他字段变动

**Failure-Mode Pass**
- 确认字段可选（`?`），不破坏现有 `ActiveLayerDisplay` 构造点
- 确认无其他类型/接口误删 `paletteOverride` 或 `renderHint`（相关字段，易在编辑中误改）

**Public-Surface / Contract Impact**
- `ActiveLayerDisplay` 是 store → 组件的投影契约。新增可选字段属非破坏性扩展，但审查需确认：
  - 是否有序列化/持久化路径（如 workspace-persist）会因新字段产生 schema 漂移或存储脏数据
  - 是否有 `check:openapi` 或 catalog 校验受影响

#### A3. `display-projection.ts`（~L351）

**Intent Match**
- 确认 `defaultPalette: baseRenderHint?.palette ?? undefined`，且数据源是 `baseRenderHint`（不含 override）而非 `weatherRenderHint`（含 override）

**Failure-Mode Pass（重点）**
- **baseRenderHint 纯净性验证**：`baseRenderHint`（L216-218）= 天气层用 `buildDefaultWeatherRenderHint(catalogId, descriptor)`，非天气层用 `layer.jobLayer?.mapLayerPayload?.renderHint`。审查需确认：
  - `buildDefaultWeatherRenderHint` 的返回 palette 确实是"引擎默认"，不会读取 `layer.paletteOverride`
  - 非天气层的 `jobLayer.mapLayerPayload.renderHint.palette` 是否被任何上游逻辑用 override 污染过
- **空值语义**：`baseRenderHint?.palette ?? undefined` — 当 baseRenderHint 为 null 时 defaultPalette=undefined。审查需追踪此空值在消费方（A4）的 fallback 行为
- **renderHint 字段未变**：确认 L279 `renderHint: weatherRenderHint`（含 override）仍保留，未被误改为 baseRenderHint — 否则当前生效配色显示会错

#### A4. `useLayerSymbology.ts`（~L236，handleSelectPalette）

**Intent Match**
- 确认 `defaultId` 计算从原 `weatherRenderHint.value?.palette` 改为 `displayLayer.value?.defaultPalette ?? overlayStyleMeta.value?.palette ?? ''`

**Failure-Mode Pass（最高优先级）**
- **fallback 链污染风险**：`defaultPalette ?? overlayStyleMeta.value?.palette ?? ''`。审查必须确认 `overlayStyleMeta`（L72-76，来自 `overlaySymbologyStore.getMeta(overlayId)`）的 `palette` 字段**不含用户 override**：
  - 若 overlayStyleMeta.palette 是侧栏元数据的"注册默认"，则 fallback 安全
  - 若 overlayStyleMeta.palette 在某路径下会被 override 覆盖，则当 `defaultPalette=undefined`（非天气层）时 fallback 重新引入 bug
  - 这是本次修复最隐蔽的潜在漏洞，需重点验证
- **canonical 化一致性**：`resolveCanonicalPaletteId`（L236）与 `paletteIdsEqual`（L241）处理 palette 别名/大小写。审查需确认 defaultPalette 的值与 `currentPaletteId`（L161-164）经过相同的 canonical 化路径
- **原 weatherRenderHint 是否仍被正确使用**：确认 `weatherRenderHint`（L63-69，含 override）仍用于 `styleSymbology`（L116）与 `currentPaletteId`（L163）等"当前生效"语义处，未被一并替换
- **恢复默认判定逻辑**：`target = paletteIdsEqual(paletteId, defaultId) ? null : paletteId`。审查需验证三种场景的正确性

### 变更组 B 逐文件要点（12 文件批量审查框架）

由于 12 文件均为同模式样式替换，采用统一检查清单 + 抽样深查。

**统一检查清单（每文件）**
- [ ] 替换的 `var(--text-*)` 确为 `background`/`background-color` 用途，非 `color` 用途（避免误伤文本色）
- [ ] 元素角色与替换值匹配：凸起/旋钮/滑块 → `var(--surface-3)`；凹陷/装饰点/idle 指示 → `var(--surface-sunken)`
- [ ] 未引入新的内联 hex 或硬编码值
- [ ] 浅色模式 `[data-theme='light']` 下该元素不再呈褐色
- [ ] **深色模式视觉不回归**：原 `var(--text-primary)=#d8e6f5`（浅色）作凸起背景，现 `var(--surface-3)=rgba(18,30,48,0.96)`（深色）。深色模式下凸起元素颜色发生显著变化 — 审查需确认深色模式视觉仍合理

**抽样深查文件**
- `MapCanvas.styles.css`：变更行最多，含 `box-shadow` 等混合用途，确认 shadow 用法未被误改
- `WorkflowStatusButton.vue` / `WorkflowTimerPanel.vue`：状态指示类组件，确认 idle/active 态语义正确
- `LoginView.vue`：登录页首屏，褐色回归最显眼，确认浅色模式首屏正常

**跨文件遗漏检查**
- 全仓库 grep `background:\s*var\(--text-` 与 `background-color:\s*var\(--text-`，确认 12 处之外无遗漏
- 检查 `border.*var(--text-` 等近似误用
- 确认是否所有 12 文件都在变更清单内，无多改或少改

### 变更组 C 逐文件要点

#### C1. `nginx.conf`（~L35）

**Intent Match**
- 确认仅在第一个 location 正则的捕获组末尾追加 `|analysis`，无其他配置改动

**Failure-Mode Pass**
- **正则语法正确性**：审查完整正则 `^/(...|auth|analysis)(/|$)` 的括号闭合、`|` 分隔、`(/|$)` 锚定是否仍正确
- **location 优先级**：nginx 正则 location（`~`）优先于前缀 location `/`。确认 `/analysis` 请求不会落入 `location /` 的 `try_files ... /index.html` 兜底
- **鉴权透传**：`/analysis` 路由是否依赖 `X-API-Key`/会话 Cookie 鉴权。确认鉴权 header 默认透传且不被 `proxy_set_header Connection ""` 等影响
- **vite vs nginx 对齐**：完整比对 vite 代理路径列表与 nginx 两个 location 的并集，确认无其他遗漏路径

**Public-Surface / Contract Impact**
- `/analysis` 经 nginx 暴露后成为生产可达端点。审查需确认该端点的鉴权策略与 AGENTS.md 高风险区 RBAC 一致

---

## 三、跨文件一致性检查

### 3.1 defaultPalette 传递链（Bug 1 核心）

完整追踪字段从定义到消费的闭环，确认无断链、无污染、无旁路：

```
types.ts: defaultPalette?: string  (定义，注释"不含 override")
   ↓
display-projection.ts:351  defaultPalette = baseRenderHint?.palette  (赋值，baseRenderHint 不含 override)
   ↓  (经 ActiveLayerDisplay 投影，进入 store)
useLayerSymbology.ts:236  defaultId = resolveCanonicalPaletteId(defaultPalette ?? overlayStyleMeta?.palette ?? '')  (消费)
```

**检查项：**
- 确认 `defaultPalette` 在全仓库**无其他写入点**（grep `defaultPalette` 全仓库）
- 确认 `baseRenderHint` 与 `weatherRenderHint` 的区分在 display-projection.ts 中正确（L216 vs L219），且 defaultPalette 取前者、renderHint 取后者
- 确认 `displayLayer.value.defaultPalette` 在 useLayerSymbology 中能正确取到投影后的值
- 确认 fallback `overlayStyleMeta?.palette` 不含 override

### 3.2 palette 语义三态一致性

| 语义 | 取值来源 | 含 override | 用途 |
|------|---------|------------|------|
| 默认配色 | `defaultPalette` = `baseRenderHint.palette` | 否 | 判断"恢复默认" |
| 当前生效 | `currentPaletteId` = `paletteOverride ?? styleRenderHint.palette` | 是 | UI 高亮当前选中 |
| overlay 同步 | `styleParams.palette` = `paletteOverride ?? undefined` | 是（override 时） | syncOverlays → 瓦片 URL |

确认 handleSelectPalette 只改了"默认配色"来源，未误改"当前生效"来源。

### 3.3 forceStyle 字段残留一致性

`forceStyle` 仍存在于：
- `OverlayStyleParams` 接口
- `styleKeyOf`（L243）
- `_normalizeStyle`（L255-257）
- `_addOverlay`（L729）
- 调用方 styleParams 构造（map-canvas-non-weather-layer-sync-module.ts:73-79）

审查需确认：移除 syncOverlays 的 forceStyle 门控后，forceStyle 字段是否仍有实际消费者，还是沦为半死代码。若 styleKeyOf 仍依赖 forceStyle 区分状态，则 forceStyle 的不一致（加载 true vs sync false）会影响防重复逻辑。

### 3.4 vite/nginx 代理路径对齐（Bug 3）

逐项比对 `vite.config.ts` proxy 键与 `nginx.conf` 两个 location 正则的并集，输出差异表，确认本次 `analysis` 补齐后两环境完全一致。

### 3.5 CSS token 语义对齐（Bug 2）

确认 12 文件替换所选 surface 层级与 tokens.css 定义语义一致：
- `--surface-3`："最高 / Tooltip" — 用于凸起/旋钮是否语义匹配
- `--surface-sunken`："低 / 凹陷容器" — 用于装饰点/idle 是否语义匹配
- 审查是否存在本应选 `--surface-1/2/hover` 却选了 3/sunken 的误判

---

## 四、测试覆盖度评估

### 4.1 现有测试覆盖现状

| 变更点 | 现有测试 | 覆盖情况 |
|--------|---------|---------|
| syncOverlays forceStyle 门控移除 | `overlay-image-module.test.ts` | **未覆盖**（仅测纯函数） |
| setOverlayStyle styleKey 防重复 | 同上 | **未覆盖** |
| handleSelectPalette 恢复默认判断 | 无 useLayerSymbology 测试 | **未覆盖** |
| display-projection defaultPalette 投影 | 无 display-projection 测试 | **未覆盖** |
| CSS 浅色模式褐色 | 无视觉回归测试 | **未覆盖** |
| nginx /analysis 代理 | 无 nginx 集成测试 | **未覆盖** |

### 4.2 审查需评估的测试缺口

**Bug 1 需评估是否应新增：**
- `syncOverlays` 在 `paletteOverride: null` 时确实调用 setOverlayStyle 并重写瓦片 URL 的行为测试
- `syncOverlays` 在 style 未变时不重复渲染的测试
- `handleSelectPalette` 点击默认/非默认 palette 的测试
- `display-projection` 投影后 `defaultPalette === baseRenderHint.palette` 的测试

**Bug 2 需评估：**
- 是否有低成本的 token 用法 lint 规则可防止复发
- 视觉回归是否依赖手动验证

**Bug 3 需评估：**
- 是否可在 CI 增加 nginx 配置语法检查与 vite/nginx 路径对齐的自动化校验

### 4.3 测试策略审查

- 确认变更未删除/修改任何现有测试
- 确认 `npm run test && npm run lint && npm run build` 在变更后仍通过
- 确认无新增测试被 skip/todo 标记

---

## 五、风险评估维度

### 5.1 风险矩阵

| 风险项 | 维度 | 严重度 | 审查动作 |
|--------|------|--------|---------|
| 服务端无 palette 参数默认色 ≠ meta.palette，导致切回默认闪烁 | Failure-Mode | 高 | 核对后端瓦片着色服务默认 palette 逻辑 |
| overlayStyleMeta.palette fallback 含 override | Failure-Mode | 高 | 追踪 overlaySymbologyStore.getMeta 返回值来源 |
| 深色模式凸起元素视觉回归（text-primary→surface-3 颜色巨变） | Failure-Mode | 中 | 深色模式手动/截图验证 |
| 首次 syncOverlays 必触发一次冗余重渲染 | 性能/复杂度 | 中 | 确认稳定后不反复触发 |
| forceStyle 残留半死代码致 styleKey 不稳定 | 可维护性 | 中 | 评估 forceStyle 是否应一并清理或保留 |
| /analysis 经网关暴露后鉴权绕过 | 安全 | 中 | 确认应用层鉴权不受网关影响 |
| vite/nginx 代理仍有其他遗漏路径 | Failure-Mode | 中 | 完整对齐比对 |
| defaultPalette 持久化导致 workspace-persist schema 漂移 | Contract | 低 | 检查持久化路径是否过滤未知字段 |
| CSS 替换遗漏 background-color 变体 | Behavior | 低 | 全仓库 grep 复查 |

### 5.2 回滚路径评估

- Bug 1：forceStyle 门控移除是单行逻辑回退；defaultPalette 字段移除需同步回退 types/display-projection/useLayerSymbology 三处
- Bug 2：12 文件样式替换可独立回退，无依赖
- Bug 3：nginx 单行回退，但需确认回退后 /analysis 重新 404 的影响范围

### 5.3 Missing Artifacts 检查

- [ ] 是否更新了相关文档
- [ ] 是否有 release notes / changelog 记录
- [ ] 是否有 runbook 记录 nginx 代理白名单维护流程
- [ ] 遥测：配色切换、分析工具调用是否有前端埋点/后端日志
- [ ] 迁移安全：defaultPalette 字段对已持久化的旧 workspace 数据的兼容性

---

## 六、审查输出格式（agent-pr-review 模板结构）

审查执行后，按以下模板结构产出审查报告：

```
# PR Review — 3 Bug 修复变更集

## 0. 审查元数据
- 审查范围：3 bug / ~16 文件
- 审查框架：agent-pr-review（7 维度）
- 验证命令基线：npm run test && npm run lint && npm run build

## 1. Review Anchors（审查锚点）
| Anchor | Changed Location | Why It Matters |
| --- | --- | --- |

## 2. Intent Match（意图匹配）
- Bug 1/2/3 各自的意图匹配状态
- Scope creep 检查

## 3. Verdict（裁定）
- Ready / Request Changes / Block
- Override posture

## 4. Code-Quality Dimensions（质量维度）
| Dimension | Status | Support Or Reason |
| --- | --- | --- |
| Design | | |
| Functionality | | |
| Complexity | | |
| Tests | | |
| Naming | | |
| Comments | | |
| Style | | |

## 5. Findings（发现项）
| Severity | Category | Support | Finding | Required Action |
| --- | --- | --- | --- | --- |

## 6. Blocker List（阻塞项）
| Blocker | Support | Required Action |
| --- | --- | --- |

## 7. Behavior Exercise（行为验证）
| Changed Behavior | Failing-Without-Change Test? | Evidence | Gap |
| --- | --- | --- | --- |

## 8. Failure-Mode Pass（失效模式检查）
| Failure Mode | Checked? | Finding |
| --- | --- | --- |
| Silent assumption | | |
| Plausible-but-wrong logic | | |
| Hallucinated API/import/type | | |
| Deleted-but-used code | | |
| Missing edge case | | |
| Scope creep | | |

## 9. Missing Artifacts（缺失产物）
| Artifact | Needed? | Gap | Owner |
| --- | --- | --- | --- |

## 10. Specialist Sanity Check（专项检查）
- 安全：/analysis 鉴权透传
- API 兼容性：defaultPalette 可选字段非破坏性
- 测试策略：测试缺口严重度
- Web release gates：build / lint / check:openapi 通过性
```

---

## 七、审查执行顺序

1. **先跑基线验证**：`cd Code/frontend && npm run test && npm run lint && npm run build`
2. **组 C（nginx）先行**：单文件、低耦合，快速判定
3. **组 B（CSS）批量审查**：套用统一清单 + 抽样深查 + 全仓库遗漏 grep
4. **组 A（配色逻辑）深审**：按传递链顺序 types → display-projection → overlay-image-module → useLayerSymbology，最后做跨文件一致性收口
5. **测试覆盖度评估**：对照缺口表，标记必须补测项
6. **填模板产出报告**：按第六节模板逐节填写

---

## 八、最高优先级风险

本次审查的最高优先级风险集中在 Bug 1 的两条隐蔽线索：

1. **`overlayStyleMeta.palette` fallback 是否含 override** — 可能使修复在非天气层失效
2. **加载态与同步态 `forceStyle` 不一致** — 导致 styleKey 防重复逻辑的边界行为异常

测试覆盖是全局性缺口（3 个 bug 的核心行为均无自动化测试覆盖），应在审查报告中作为阻塞项或强建议项提出。
