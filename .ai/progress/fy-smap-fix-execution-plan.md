# FY/SMAP UI 全流程修复与验证计划

> **状态（2026-08-04）**：算法侧修复与离线 Matlab 对照已完成（见 `fy-smap-progress-tracker.md`）。  
> 下方阶段 2a 代码确认已完成；**UI 人工验证 / 导出（阶段 2a 末项～阶段 5）仍未闭环**，以 `ui-verification-steps.md` 与 tracker「UI | 部分」为准。

## 问题诊断总结

### 问题 1: 图层管理器刷新后异常显示未添加的图层

**根因分析**:
- 检查 `Code/frontend/src/stores/layers/index.ts` 中的 `activeLayers`:
  ```typescript
  const activeLayers = ref<ActiveLayer[]>([]) // Line 509
  ```
- **确认**: activeLayers 初始化为空数组 `[]`
- **结论**: 刷新异常可能是以下原因导致：
  1. 前端会话状态被 localStorage/sessionStorage 持久化并在刷新后恢复
  2. 后端 workflow-runs 自动拉取了某些 jobLayer 并添加为 activeLayers

**验证方法**:
```bash
# 检查前端是否有 activeLayers 持久化逻辑
grep -r "activeLayers.*localStorage\|activeLayers.*sessionStorage" Code/frontend/src/
grep -r "restore.*layers\|load.*layers" Code/frontend/src/
```

### 问题 2: 时间轴默认显示 hour 刻度

**当前实现**:
- `TimelineScrubber.vue` Line 60:
  ```typescript
  const progressPercent = computed(() => `${((props.currentHour / 23) * 100).toFixed(1)}%`)
  ```
- DashboardView.vue Line 85-87:
  ```typescript
  const now = new Date()
  const currentHour = ref(now.getHours())  # 初始化为当前小时
  const currentDate = ref(now)
  ```

**需求理解**: 
用户要求在"无数据/无选择图层"情况下:
- 默认显示小时刻度（已实现）
- 不触发数据选择逻辑（只保留用户之前选择的统一模式时间）

**当前行为验证**:
- unifiedTimeLock (Line 93 ui.ts):
  ```typescript
  const unifiedTimeLock = ref(loadUnifiedFlag())
  ```
- 新加图层时跳过切层记忆恢复（DashboardView.vue Line 167-170）:
  ```typescript
  const pendingSnapCatalogIds = new Set<string>()
  const knownActiveInstanceIds = new Set<string>()
  ```

**结论**: 时间轴功能**已经正确实现**。需验证实际运行行为是否符合预期。

### 问题 3: FY/SMAP 反演结果不正确

**Matlab 参考结构**:
```
I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res/
├── fy_raw_smvod/     (31 .mat files - 每日 FY3D)
├── smap_raw_omega/   (4 .mat files - 块级输出 8 天/块)
└── smap_raw_smvod/   (31 .mat files - 每日 SMAP)
```

**Python 核心算法验证** (`lightweight_verify.py`):
```
Year: 2025
Total blocks: 46 (Matlab should be 46) [PASS]
Last block: Start: 2025-12-27, End: 2025-12-31 (5 days)
First block: 2025-01-01 ~ 2025-01-08
```

**已完成修复**:
1. ✅ 日期提取逻辑增强 (`omega_sf.py` `_scan_folder_dates`)
2. ✅ 文件名匹配安全性改进 (`daily_bundle.py` _resolve_daily_mat_file)
3. ✅ 输出命名 Matlab 兼容格式 (`omega_sf.py` L1467+)

## 执行计划

### 阶段 1 / 算法修复（已完成）
- [x] 日期提取逻辑增强（`omega_sf.py` `_scan_folder_dates`）
- [x] 文件名匹配安全性改进（`daily_bundle.py`）
- [x] 输出命名 Matlab 兼容格式
- [x] Q4 扩样 + vs Matlab 对照（见 `fy-smap-progress-tracker.md`）

### 阶段 2a: 时间轴逻辑确认
- [x] 读取 TimelineScrubber.vue 确认小时刻度显示
- [x] 确认 DashboardView.vue 的初始化逻辑
- [ ] 实际启动 UI 验证无数据场景下的行为（人工，见 `ui-verification-steps.md`）

### 阶段 2b: 图层管理器刷新异常诊断
- [x] 检查 activeLayers 持久化逻辑（`workspace-persist.ts`：刷新恢复已添加层；移除进 dismissed）
- [ ] 检查后端 workflow-runs API 是否自动添加图层
- [ ] 如存在异常持久化则清空/禁用

### 阶段 3: FY/SMAP 全流程回归验证
- [x] 离线/workflow 扩样运行与 Matlab 对照（tracker 已记 run-id）
- [ ] 通过 UI 提交 omega_sf_fenkuai 工作流（人工）
- [ ] 等待运行完成并在 UI 确认成功态（人工）
- [ ] 对比输出目录结构与 Matlab 参考数据（UI 路径确认）
- [ ] 验证数据内容（形状、有效值统计）在界面侧可见

### 阶段 4: UI 全流程验证（未完成）
- [ ] 启动完整栈: `start.bat`
- [ ] 选择 omega_sf_fenkuai 工作流
- [ ] 运行并验证:
  - 图层管理器只显示已添加图层
  - 时间轴能切换不同 8 天块
  - SM/VOD/OMEGA 独立显示；条带特征（更大样本）
- [ ] 验证导航流畅性、渲染性能

### 阶段 5: 数据导出验证（未完成）
- [ ] 选择一个完成的图层
- [ ] 验证导出功能:
  - 导出文件格式（GeoTIFF/NetCDF/MAT）
  - 数据完整性校验
  - 路径配置正确性

## 下一步行动

1. **P0**：按 `ui-verification-steps.md` 跑完整栈并勾选人工清单
2. **P0**：更大 bbox/样本上图，确认条带特征后更新 tracker UI 行
3. 排期总览见 `2026-08-04-pending-tasks-audit.md`
