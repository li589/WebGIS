# 系统细节优化 - 续作计划

> **背景**：原计划 `system_detail_optimization_plan.md` 已批准并部分执行。
> **已完成**：第一阶段 1.1-1.3（后端节点模板：端口类型细化 + 默认值补全 + `_param` 扩展 + 15 个新模块节点模板）
> **本计划范围**：剩余 7 个子任务 + 验证

---

## 当前状态确认（基于代码核查）

### ✅ 已完成（第一阶段 1.1-1.3）
- `Code/backend/app/services/node_template_registry.py` 已重写（919 行）
  - `_param` 函数支持 `unit`/`min_val`/`max_val`/`step`（L16-51）
  - 分层端口类型系统：`data:source`/`data:mat`/`data:raster`/`data:geojson`/`data:timeseries`/`value:number`/`value:string`/`value:time_range`/`geometry:bbox`
  - 全部 44 个节点模板已更新端口类型（30 现有 + 14 新增基础模块）
  - `module/smap_daily` 已新增 `time_range` 输入端口（L665，optional）
  - 所有缺失默认值已补全（freq_ghz=1.4, pixel_chunk_size=512, bbox=0.0 等）
  - 15 个新模块已添加：preprocess/* (5), stats/* (5), fusion/* (3), viz/* (3) — 注意原计划 2.3 是 5 个，实际 fusion 2 个 + viz 3 个 = 5 个

### ⏳ 待完成
1. **1.4 前端类型校验 + array 支持 + 端口颜色** — `litegraph-setup.ts`
2. **1.5 修复 smap_soil_moisture.json** — JSON 中端口类型仍为旧 "data"，且 node 2 未连接到 node 3
3. **2.4 后端 stub 实现** — 15 个新模块的 bridge service 注册
4. **3.1 节点库按功能分类** — `WorkflowNodePalette.vue` 的 `CATEGORY_LABELS`/`ENGINE_ICONS` 仍按引擎分类
5. **3.2-3.3 WorkflowInspector 参数渲染优化** — enum 仍用 text input，number 无 min/max/step，无验证
6. **3.4-3.5 端口类型可视化 + 参数单位显示** — 无端口颜色，无单位显示
7. **4.1-4.5 算法合规性** — `inversion.py` 仍有 magic constant、死代码、重复逻辑

---

## 任务 1.4：前端类型校验 + array 支持 + 端口颜色

**文件**: `Code/frontend/src/components/workflow/litegraph-setup.ts`

### 1.4.1 `mapParamTypeToWidget` 新增 array 支持
- L184-198：在 switch 中新增 `case 'array': return 'text'`
- 在 `registerWorkflowNodeTypes` 中，array 类型参数的默认值用 `Array.isArray(default) ? default.join(',') : String(default ?? '')`

### 1.4.2 新增 `checkConnectionValid` 函数
实现连接规则（在节点构造时注入到 `LGraphCanvas.onConnectNode` 或通过 `LGraphNode.prototype.onConnectInput`）：

```typescript
export function checkConnectionValid(
  inputType: string,
  outputType: string,
): boolean {
  // 相同类型：允许
  if (inputType === outputType) return true
  // data 通用类型 <-> data:* 子类型：允许（向后兼容）
  if (inputType === 'data' || outputType === 'data') return true
  // data:* 之间：禁止（不同子类型）
  if (inputType.startsWith('data:') && outputType.startsWith('data:')) return false
  // value:* 之间：禁止
  if (inputType.startsWith('value:') && outputType.startsWith('value:')) return false
  // geometry:* 之间：禁止
  if (inputType.startsWith('geometry:') && outputType.startsWith('geometry:')) return false
  // 其他不同类型：禁止
  return false
}
```

注入方式：在 `registerWorkflowNodeTypes` 的 WorkflowNode 类中重写 `onConnectInput(inputIndex, outputType, outputSlot, outputNode, outputSlotIndex)`：
```typescript
onConnectInput(inputIndex: number, outputType: string, ...): boolean {
  const inputSlot = this.inputs[inputIndex]
  if (!inputSlot) return false
  return checkConnectionValid(inputSlot.type as string, outputType)
}
```

### 1.4.3 新增 `getPortColor` 函数
```typescript
export function getPortColor(type: string): string {
  if (type === 'data' || type === 'data:source') return '#5ad5ff'   // 青色
  if (type === 'data:mat') return '#ffb84d'                          // 橙色
  if (type === 'data:raster') return '#5ad5ff'                       // 蓝色
  if (type === 'data:geojson') return '#78ffa0'                      // 绿色
  if (type === 'data:timeseries') return '#c084fc'                   // 紫色
  if (type === 'value:number' || type === 'value:string') return '#ffd5a8' // 浅黄
  if (type === 'value:time_range') return '#ff8fb1'                  // 粉色
  if (type === 'geometry:bbox') return '#ff6b6b'                     // 红色
  return '#6e8ba0'                                                    // 默认灰
}
```

在 WorkflowNode 构造函数中，`addInput`/`addOutput` 后设置 slot 的 `_color` 属性（LiteGraph 通过 `slot.color` 渲染）：
```typescript
for (const input of tpl.inputs) {
  this.addInput(input.name, input.type)
  const slot = this.inputs[this.inputs.length - 1]
  if (slot) (slot as any).color = getPortColor(input.type)
}
```

---

## 任务 1.5：修复 smap_soil_moisture.json

**文件**: `Code/backend/.data/workflow_definitions/system/smap_soil_moisture.json`

当前问题：
- node 1 输出 type="data" → 应为 "data:source"
- node 2 输出 type="data" → 应为 "value:time_range"
- node 3 只有 1 个输入（input_dir），缺少 time_range 输入
- node 3 输入/输出 type="data" → 应为 "data:source"/"data:mat"
- links 数组只有 2 条，node 2 的 time_range 输出无消费者

修复：
1. node 1 outputs: `[{ "name": "data", "type": "data:source" }]`
2. node 2 outputs: `[{ "name": "time_range", "type": "value:time_range" }]`
3. node 3 inputs: 增加第二个输入
   ```json
   [
     { "name": "input_dir", "type": "data:source" },
     { "name": "time_range", "type": "value:time_range" }
   ]
   ```
4. node 3 outputs: `[{ "name": "smap_daily_mat", "type": "data:mat" }]`
5. links 增加：`[3, 2, 0, 3, 1, "value:time_range"]`
6. node 4 inputs 保持 `data`（通用输出接收方）

最终 links：
```json
[
  [1, 1, 0, 3, 0, "data:source"],
  [2, 2, 0, 3, 1, "value:time_range"],
  [3, 3, 0, 4, 0, "data"]
]
```

---

## 任务 2.4：后端 stub 实现

**文件**: `Code/backend/app/services/python_provider_bridge_service.py`

为 15 个新模块添加最小 stub。需先核查该文件的模块注册结构。

策略：
- 在 bridge service 的模块映射表中注册 15 个新 `node_class`
- 每个 stub 返回 `{"status": "pending_implementation", "node_class": "..."}`
- 确保 workflow 可提交但返回"模块开发中"状态
- 不实现实际算法逻辑

新增 node_class 列表：
- `preprocess_reproject`, `preprocess_resample`, `preprocess_format_convert`, `preprocess_clip`, `preprocess_mask`
- `stats_spatial_mean`, `stats_temporal_trend`, `stats_anomaly_detect`, `stats_correlation`, `stats_histogram`
- `fusion_spatial_interpolate`, `fusion_multi_source_merge`
- `viz_chart_generate`, `viz_report_export`, `viz_statistics_summary`

---

## 任务 3.1：节点库按功能分类

**文件 1**: `Code/frontend/src/stores/workflow-definitions.ts`
- `templatesByCategory` computed 当前用 `tpl.category || tpl.engine` — 已正确（新模板有 category 字段）
- 无需修改 store

**文件 2**: `Code/frontend/src/components/workflow/WorkflowNodePalette.vue`
- L24-29 `CATEGORY_LABELS`：当前键为 `general/weather/python_provider/gee`，但实际 category 已是中文功能名（"数据输入"/"数据预处理"/"遥感处理"等）
- L32-37 `ENGINE_ICONS`：同样需要更新

修复方案：
1. 删除 `CATEGORY_LABELS`（category 字段已是人类可读中文，无需映射）
2. `getCategoryLabel` 直接返回 `category`
3. `ENGINE_ICONS` 改为 `CATEGORY_ICONS`，为每个功能分类配置图标：
   ```typescript
   const CATEGORY_ICONS: Record<string, string> = {
     '数据输入': '📂',
     '数据预处理': '🔧',
     '遥感处理': '🛰',
     '合成': '🔀',
     '反演': '📐',
     '统计分析': '📊',
     '数据融合': '🔗',
     '可视化': '📈',
     '天气-数据抓取': '☀',
     '天气-渲染': '🎨',
     '天气-处理': '⚙',
     'GEE-数据': '🌍',
     'GEE-处理': '🛠',
     '输出': '📤',
   }
   ```
4. `getEngineIcon` 重命名为 `getCategoryIcon`，从 `CATEGORY_ICONS` 查找

---

## 任务 3.2-3.3：WorkflowInspector 参数渲染优化 + 验证

**文件**: `Code/frontend/src/components/workflow/WorkflowInspector.vue`

### 3.2 参数渲染优化
当前 L202-237 的"自定义属性"区块仅用 `typeof value` 判断类型，应改为从 `templateParams` 获取参数元信息：

新增 computed：
```typescript
const templateParamMap = computed(() => {
  const m: Record<string, NodeTemplateParam> = {}
  for (const p of templateParams.value) m[p.key] = p
  return m
})

function getParamMeta(key: string) {
  return templateParamMap.value[key]
}
```

渲染规则更新（替换 L206-235）：
- **enum（有 options）**: 用 `<select>` 渲染，options 来自 `param.options`
- **number**: 加 `:min`/`:max`/`:step` 属性，从 `param.min`/`param.max`/`param.step`
- **boolean**: 用 toggle 开关样式（CSS 实现，保持 checkbox 语义）
- **array**: 逗号分隔文本输入 + placeholder 提示
- **string**: 加 placeholder（来自 `param.description`）
- 参数标签后显示单位（如 `param.unit` 存在）

### 3.3 参数验证
新增验证函数：
```typescript
function validateParam(key: string, value: unknown): string | null {
  const meta = getParamMeta(key)
  if (!meta) return null
  // number 范围验证
  if (meta.type === 'number' && typeof value === 'number') {
    if (meta.min != null && value < meta.min) return `最小值 ${meta.min}`
    if (meta.max != null && value > meta.max) return `最大值 ${meta.max}`
  }
  // 特定参数验证
  if (key === 'freq_ghz' && (value < 0.1 || value > 40)) return '频率范围 0.1-40 GHz'
  if (key === 'west' || key === 'east') {
    if (value < -180 || value > 180) return '经度范围 -180~180'
  }
  if (key === 'south' || key === 'north') {
    if (value < -90 || value > 90) return '纬度范围 -90~90'
  }
  return null
}

const validationErrors = ref<Record<string, string>>({})

function handlePropertyChange(key: string, value: unknown) {
  const err = validateParam(key, value)
  if (err) validationErrors.value[key] = err
  else delete validationErrors.value[key]
  localProperties.value[key] = value
  emit('updateProperty', key, value)
}
```

验证失败时输入框加 `.error` class（红色边框）+ 错误提示文本。

---

## 任务 3.4-3.5：端口类型可视化 + 参数单位显示

**文件 1**: `Code/frontend/src/components/workflow/litegraph-setup.ts`
- 端口颜色已在任务 1.4.3 实现

**文件 2**: `Code/frontend/src/components/workflow/WorkflowInspector.vue`
- 端口列表（L177-200）：在 `.port-type` span 旁加颜色色块
  ```html
  <span class="port-color-dot" :style="{ background: getPortColor(input.type) }"></span>
  <span class="port-type">{{ input.type }}</span>
  ```
- 从 `litegraph-setup.ts` import `getPortColor`
- 参数标签：单位显示已在任务 3.2 处理（标签后追加 `(unit)`）

---

## 任务 4.1-4.5：算法合规性

**文件**: `Code/algorithms/providers/Python/algorithms/inversion.py`

### 4.1 替换 magic constants
- L115 `lambda_value = 20.0` → 提取为模块级常量 `_TAU_REGULARIZATION_LAMBDA = 20.0`
- 添加注释：`# tau 正则化系数（L2 惩罚强度），用于约束 tau_value 接近 tau_ini`

### 4.2 清理遗留代码
- L83 `_ = (tbv_obs, tbh_obs)` → 删除
- 同时从 `tb_model` 函数签名中移除未使用的 `tbv_obs`/`tbh_obs` 参数
- 检查所有调用点（`f_sm_cost` L102-114、`f_h_cost` L137-149）并移除对应实参

### 4.3 消除重复代码
- `rough_reflectance` (L32-39) 和 `rough_reflectance_from_context` (L42-47) 合并
- 提取公共逻辑：
  ```python
  def _rough_reflectance_impl(theta_cos_sq: float, h_value: float, rh: float, rv: float) -> tuple[float, float]:
      q_value = _POLARIZATION_MIXING_Q * h_value
      exp_term = math.exp(-h_value * theta_cos_sq)
      rh_r = ((1 - q_value) * rh + q_value * rv) * exp_term
      rv_r = ((1 - q_value) * rv + q_value * rh) * exp_term
      return rh_r, rv_r

  def rough_reflectance(theta_deg: float, h_value: float, rh: float, rv: float) -> tuple[float, float]:
      return _rough_reflectance_impl(math.cos(math.radians(theta_deg)) ** 2, h_value, rh, rv)

  def rough_reflectance_from_context(context: TbModelContext, h_value: float, rh: float, rv: float) -> tuple[float, float]:
      return _rough_reflectance_impl(context.fresnel.cos_theta_sq, h_value, rh, rv)
  ```

### 4.4 边界条件处理
在 `tb_model` 开头加边界检查：
```python
# 物理约束检查
if not (0.0 <= soil_moisture <= 0.6):
    return float('inf'), float('inf')
if tau_value < 0.0 or h_value < 0.0:
    return float('inf'), float('inf')
```

在 `f_sm_cost` 开头加：
```python
if not (0.1 <= freq_ghz <= 40.0):
    return [float('inf'), float('inf'), float('inf')]
```

### 4.5 量纲注释
为每个公开函数添加量纲注释（docstring 形式）：
- `tb_model`: 输入 TB 单位 K，输出 TB 单位 K；soil_moisture 无量纲 (m³/m³)
- `f_sm_cost`: 返回残差向量，单位 K（前两项）+ 无量纲（第三项正则化）
- `rough_reflectance`: 输入/输出无量纲（反射率 0-1）
- `build_tb_model_context`: freq_ghz 单位 GHz，theta_deg 单位度
- `retrieve_dynamic_h_pixel`: 返回 h_value 无量纲（粗糙度参数）

---

## 实施顺序

```
1. 任务 1.4（前端类型校验 + array + 端口颜色）→ litegraph-setup.ts
2. 任务 1.5（修复 smap_soil_moisture.json）→ JSON 文件
3. 任务 2.4（后端 stub）→ python_provider_bridge_service.py
4. 任务 3.1（节点库分类）→ WorkflowNodePalette.vue
5. 任务 3.2-3.3（参数渲染 + 验证）→ WorkflowInspector.vue
6. 任务 3.4-3.5（端口可视化 + 单位）→ WorkflowInspector.vue（接 3.2）
7. 任务 4.1-4.5（算法合规性）→ inversion.py
8. 验证：vue-tsc + py_compile
```

---

## 假设与决策

1. **连接校验注入方式**：通过重写 `LGraphNode.onConnectInput` 实现类型校验，而非修改 `LGraphCanvas.onConnectNode`，因为前者粒度更细且不影响其他节点类型
2. **array 参数渲染**：前端用逗号分隔文本输入，后端 stub 解析时按逗号 split；空字符串视为空数组
3. **后端 stub 策略**：仅注册 node_class 映射，返回 `pending_implementation` 状态，不实现实际算法；实际算法由后续迭代完成
4. **节点库分类图标**：用 emoji 图标（📂🔧🛰等）区分功能分类，直观且无需引入图标库
5. **参数验证**：仅做范围验证（min/max），不做格式验证（如 ISO 8601 时间格式），避免过度工程化
6. **算法边界检查**：超出物理约束范围返回 `float('inf')`，让优化器自然排除无效解；不抛异常避免中断批处理
7. **端口颜色**：在 slot 上设置 `color` 属性，LiteGraph 原生支持 slot 颜色渲染

## 验证步骤

1. **前端**：
   - `npx vue-tsc --noEmit` 确认无类型错误
   - 打开工作流编辑器，确认节点库按功能分类显示（数据输入/数据预处理/遥感处理等）
   - 拖入 `gee/select_bands` 节点，确认 `bands` 参数用 text 输入（array 支持）
   - 拖入 `module/inversion_daily`，确认 `freq_ghz` 参数有 min=0.1/max=40/step=0.1
   - 拖入 `data/bbox` 节点，确认端口有颜色标识（红色 geometry:bbox）
   - 尝试将 `data/source`（输出 data:source）连接到 `weather/wind_field_render` 的 latitude 输入（value:number），确认被类型校验拦截
   - 选中 `module/smap_daily` 节点，确认参数面板显示单位（如"频率 (GHz)"）

2. **后端**：
   - `python -m py_compile Code/backend/app/services/python_provider_bridge_service.py`
   - `python -m py_compile Code/algorithms/providers/Python/algorithms/inversion.py`
   - 启动 FastAPI，访问 `/workflow-definitions/node-templates` 确认 44 个模板
   - 打开 smap_soil_moisture 工作流，确认 node 2 (time_range) 已连接到 node 3

3. **算法**：
   - 确认 `tb_model` 函数签名变化（移除 tbv_obs/tbh_obs）不破坏调用链
   - 确认边界检查返回 `inf` 不影响 `least_squares` 优化器收敛

4. **集成**：
   - 运行 smap_soil_moisture 工作流，确认无类型错误
   - 提交包含新模块（如 stats/spatial_mean）的工作流，确认返回 `pending_implementation` 状态
