# UI优化与底图模块审计 实施计划

## 概要

本计划覆盖5项任务：登录页视觉升级、底图模块逻辑审计、加载动画兼容性检查、日志面板优化、截图/数据/日志组件样式适配，最后通过构建验证并更新文档。

---

## 当前状态分析

### 登录页 (LoginView.vue)
- 纯CSS深色科技风背景（网格线+光晕），无背景图片
- 品牌Logo使用Unicode字符`◎`，渲染一致性差
- 表单字号偏小（label 0.62rem≈10px，input 0.72rem≈11.5px），未达12px下限
- 卡片玻璃态样式已有基础，但视觉层次较单一

### 日志面板 (LogPanel.vue)
- 右上角显示**总日志条数**（蓝色药丸），而非错误数
- 工具栏badge已显示errorCount，但面板标题语义不一致
- 日志字体大小未统一到设计令牌
- 数值过大时无截断/格式化处理（如99+显示）

### 底图模块
- 后端：内存LRU缓存（512条/TTL 3600s），无磁盘缓存；坐标转换中心点近似；OSM/CARTO硬编码单子域名；错误信息可能泄露内部URL
- 前端：瓦片错误熔断（5秒15个错误触发），天气瓦片管理器有完善的重试/退避/并发控制/预取机制
- 天地图vec层已添加，但cva注记层未作为叠加层使用

### 加载动画
- 6套加载组件：Skeleton.vue（通用）、InlineLoader、LoadingOverlay（hero/compact）、MapCanvas内置Skeleton、map-loading药丸、DataImportMenu spinner
- LoadingOverlay hero动画复杂（8+同时动画），可能低端GPU卡顿
- MapCanvas内置Skeleton与通用Skeleton.vue视觉语言不统一
- 最近修改的CSS变量/令牌需确认所有加载组件兼容

### 截图/数据/日志组件
- ScreenshotExport：面板定位硬编码padding，字号偏小
- DataImportMenu：下拉菜单全局非scoped样式可能冲突
- LogPanel：字号、间距未完全适配新设计令牌

---

## 拟议更改

### 任务1：登录页面优化（LoginView.vue）

**文件：** `Code/frontend/src/views/LoginView.vue`

**更改内容：**
1. 添加SVG背景图层（地球网格/科技感线条图案，使用CSS SVG data URI避免外部依赖）
2. 升级品牌区域：用SVG地球图标替换Unicode`◎`字符
3. 统一字号到设计令牌：label→`var(--font-size-caption)`(12px)，input→`var(--font-size-body)`(13px)，btn→`var(--font-size-body)`
4. 增强卡片玻璃态效果：提升backdrop-blur强度，优化边框渐变
5. 添加微妙的入场动画（卡片上浮+淡入）
6. 优化光晕效果，增加层次感
7. 确保prefers-reduced-motion下禁用动画

**原因：** 提升品牌辨识度和视觉品质，统一到设计系统规范。

---

### 任务2：底图模块调研与修复

**文件：**
- `Code/backend/app/services/tile_proxy_service.py`
- `Code/frontend/src/components/map/basemap-module.ts`
- `Code/frontend/src/services/api-config.ts`

**调研与修复项：**

2a. **缓存泄漏检查**
- 确认LRU缓存OrderedDict的`popitem(last=False)`正确淘汰最旧条目
- 检查TTL过期是否在访问时检查（当前实现验证）
- 无磁盘缓存是设计决策（保持无状态），不做修改

2b. **重试机制验证**
- 后端：httpx客户端使用connect=5s/read=30s超时，无自动重试（依赖前端重试）
- 前端basemap-module.ts：确认瓦片错误熔断逻辑（5秒15错误）正常工作
- 天气瓦片管理器的退避重试机制已完善，无需修改

2c. **加载策略检查**
- OSM使用德国镜像`tile.openstreetmap.de`，官方在国内可能不稳定→保留但添加注释说明
- CARTO硬编码`b.basemaps.cartocdn.com`→这是有意为之（a子域名国内不可达）
- 天地图/百度Key缺失时返回503→前端需确保正确显示错误状态

2d. **修复项**
- 错误处理：`HTTPException(detail=...)`中避免暴露完整上游URL，改为通用错误信息
- 检查basemap-module.ts中的瓦片错误状态重置逻辑是否正确

2e. **注记层叠加**（可选，如时间允许）
- 天地图cva注记层可作为矢量/影像底图的叠加层，但需要MapLibre多层raster支持，复杂度较高，本次仅记录为待办

---

### 任务3：加载动画兼容性检查

**检查范围：**
- `Skeleton.vue`：确认sweep动画使用设计令牌颜色，12px下限已满足
- `InlineLoader.vue`：检查字号是否≥12px，颜色是否使用令牌
- `LoadingOverlay.vue`：检查hero模式动画在修改后的CSS变量下是否正常，检查prefers-reduced-motion
- `MapCanvas.vue`内置skeleton/loading：检查硬编码颜色是否替换为令牌，字号统一
- `DataImportMenu` spinner：同上

**更改内容：**
1. 逐一检查上述文件的CSS，确保：
   - 所有颜色使用`var(--*)`令牌（无硬编码hex/rgba）
   - 所有字号≥12px（使用`var(--font-size-caption)`或更大）
   - 动画尊重`prefers-reduced-motion: reduce`
2. 修复发现的不一致项

---

### 任务4：日志面板优化（LogPanel.vue + log store）

**文件：**
- `Code/frontend/src/components/toolbar/LogPanel.vue`
- `Code/frontend/src/stores/log.ts`

**更改内容：**
1. **右上角数字改为仅显示错误数**：将`.entry-count`从显示`entries.length`改为显示`errorCount`
2. **错误数为0时**：不显示badge或显示中性色调
3. **字号缩小**：badge字号设为`var(--font-size-caption)`(12px)，适当缩小pill尺寸
4. **大数显示**：errorCount≥100时显示"99+"
5. **过滤"一般日志"**：默认视图不显示info级别？不，用户说"不用显示一般日志的数据"→理解为右上角badge不统计info/debug，仅统计error（warn可选）。保持现有4个filter tab不变。
6. 统一面板内所有文字字号到设计令牌
7. 检查日志条目间距、颜色是否适配新设计系统

**工具栏badge确认**：AGENTS.md说工具栏badge显示errorCount，需确认ModeToolbar/工具栏中的日志按钮badge是否正确（可能在LogPanel触发按钮的父组件中）。

---

### 任务5：截图框/数据下拉/日志侧栏样式适配

**文件：**
- `Code/frontend/src/components/ScreenshotExport.vue`
- `Code/frontend/src/data-manager/ui/DataImportMenu.vue`
- `Code/frontend/src/components/toolbar/LogPanel.vue`

**更改内容：**

5a. **ScreenshotExport.vue**
- 统一所有字号到设计令牌（标题/选项/按钮文字）
- 修复硬编码padding定位（如可能，改用相对定位或CSS变量）
- 确保capture-btn文字不重复
- 检查颜色使用令牌

5b. **DataImportMenu.vue**
- 下拉菜单项字号统一到12px+
- 将全局非scoped样式`.import-dropdown`改为scoped（或使用唯一前缀）
- 检查菜单项hover/active状态颜色使用令牌
- 统一spacing到`var(--space-*)`

5c. **LogPanel.vue**（与任务4合并）
- 统一面板标题、tab按钮、日志条目、时间戳等所有字号
- 统一间距和颜色
- 确保滚动条样式与主题一致

---

### 任务6：构建验证与文档更新

6a. **构建验证**
```
cd Code/frontend
npx vite build
```
- 确保无编译错误
- 检查CSS中是否有未定义的var()引用

6b. **运行lint**
```
cd Code/frontend
npm run lint
```
（若Node环境可用）

6c. **文档更新**
- 检查`.ai/docs/`下是否有需要更新的设计系统文档
- 更新修改记录（如`.ai/progress/`中有相关文件）
- 如无专门文档需要更新，在总结中说明

---

## 假设与决策

1. **登录页背景图**：使用内联SVG CSS背景（地球经纬线+点阵图案），不引入外部图片文件，保持构建产物自包含
2. **底图模块**：主要进行审计和小修复（错误信息脱敏、确认现有机制正常），不重构坐标转换或添加磁盘缓存（超出本次范围）
3. **日志badge**：右上角仅显示错误数量，warn不计入（如需要可后续扩展）
4. **大数截断**：≥100显示"99+"，符合常见UI模式
5. **LoadingOverlay hero动画**：不简化或移除，仅确保颜色/字号使用令牌；低端设备性能问题通过prefers-reduced-motion已经部分覆盖
6. **天地图注记层叠加**：本次不实现（需MapLibre多raster图层支持，复杂度较高），记录为后续功能

---

## 验证步骤

1. **构建验证**：`npx vite build` 成功，无错误
2. **视觉验证**（需人工）：
   - 登录页：背景效果、字号、品牌图标、动画
   - 顶栏：日志按钮badge显示错误数（非总条数），99+截断
   - 底图切换：天地图街道模式正常显示（vec底图）
   - 截图面板/数据下拉/日志侧栏：字号统一、间距协调
3. **功能验证**（需人工）：
   - 底图切换各源正常加载
   - 瓦片错误时熔断/重试正常
   - 日志面板过滤、导出、清空功能正常
   - 截图导出功能正常
   - 数据导入菜单正常展开/关闭
4. **代码质量**：无硬编码颜色/字号（除特殊效果如渐变），所有动画支持reduced-motion
