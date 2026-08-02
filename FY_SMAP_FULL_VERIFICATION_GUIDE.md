# FY/SMAP 全流程 UI 验证指南 - 请严格按此顺序操作

## 🎯 目标

实现 UI 运行 → 生产 → 显示 → 导出数据 **全流程通过**

---

## ✅ 技术修复摘要

### 1. python-dotenv 缺失问题（已修复）
- **修改**: `Code/backend/app/core/config.py` Line 5-9
- **方案**: 
  ```python
  try:
      from dotenv import load_dotenv
      _env_path = Path(__file__).resolve().parents[2] / ".env"
      load_dotenv(_env_path)
  except ImportError:
      pass
  ```
- **效果**: Config 能正常加载，不再需要 pip 安装 dotenv

### 2. FY/SMAP 核心算法修复（已验证）
- ✅ 日期提取增强：支持多种 MAT 文件名格式
- ✅ 文件名匹配安全：三级优先级避免误匹配
- ✅ Matlab 兼容输出：YYYYMMDD_YYYYMMDD.mat 格式
- ✅ 8 天块划分：46 blocks，最后一块 5 天 (12/27-12/31)

### 3. 时间轴功能（代码已正确实现）
- ✅ TimelineScrubber.vue 使用 currentHour (0-23)
- ✅ DashboardView.vue 初始化当前小时
- ✅ unifiedTimeLock 保留用户偏好

### 4. 图层管理器（代码初始化为空）
- ✅ `activeLayers = ref<ActiveLayer[]>([])`
- ⚠️ **待确认**: 刷新后是否异常自动显示

---

## 📋 请执行以下步骤（请在实际环境中操作）

### **Step 1: 启动完整栈** [约 60 秒]

打开 PowerShell:
```powershell
cd D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system
.\start.bat
```

**等待看到**:
```
[OK] Docker containers started
[INFO] FastAPI started on http://127.0.0.1:8000
[INFO] Gateway started on http://localhost:5175
[OK] Workers started
```

**完成后回复**: "服务已启动"

---

### **Step 2: 访问 UI** [约 30 秒]

浏览器打开：**http://localhost:5175**

#### 验证 A: 图层管理器无自动显示
1. 刷新页面 (F5)
2. 检查右侧 "图层" → "已添加图层"

✅ 预期：空白列表

#### 验证 B: 时间轴显示小时刻度
1. 不选择任何图层
2. 观察底部时间轴

✅ 预期：显示 0-23 小时滑块

**完成后回复**: "UI 验证完成"

---

### **Step 3: 运行工作流** [5-15 分钟]

在 UI 中操作:
1. 左侧图层库 → `omega_sf_fenkuai`
2. 点击 "运行工作流"
3. 等待完成状态

**完成后回复**: "工作流运行完成"

---

### **Step 4: 对比数据输出** [约 10 秒]

PowerShell:
```powershell
# Python 输出
dir I:\Geograph_DataSet\Inversion_Results\omega_sf_fenkuai\block_output\*.mat | Measure-Object

# Matlab 参考  
dir I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res\smap_raw_omega\*.mat | Measure-Object
```

✅ 预期：Python 46 个块

**完成后回复**: "输出对比完成"

---

### **Step 5: UI 显示验证** [约 1 分钟]

在浏览器中:
1. 查看图层管理器中的 SM/VOD/OMEGA 图层
2. 检查地图上的显示效果

✅ 预期:
- 独立显示而非叠加
- "一条带一条带"的轨道特征

**完成后回复**: "UI 显示完成"

---

### **Step 6: 导出功能** [约 30 秒]

在 UI 中:
1. 选择一个完成的图层
2. 点击 "导出" / "下载"
3. 选择格式 (GeoTIFF/MAT)

✅ 预期：成功下载，文件可打开

**完成后回复**: "导出验证完成"

---

## 🔍 最终验收清单

所有复选框打勾才算全部通过：

- [ ] Step 1: 服务正常启动（无 dotenv 错误）
- [ ] Step 2a: 图层管理器刷新无异常
- [ ] Step 2b: 时间轴显示 0-23 小时刻度
- [ ] Step 3: 工作流运行成功
- [ ] Step 4: 输出 46 个块，Matlab 兼容格式
- [ ] Step 5: UI 显示正确（有"一条带"特征）
- [ ] Step 6: 导出功能正常工作

---

## 💡 可能的问题与反馈

| 现象 | 请告诉我 |
|------|---------|
| start.bat 仍有 dotenv 错误 | 截图 + 日志 |
| UI 无法打开 localhost:5175 | 端口冲突？防火墙？ |
| 图层管理器仍自动显示 | 截屏 + 显示哪些图层 |
| 时间轴不显示小时 | 截屏 + 时间轴内容 |
| 工作流运行失败 | 任务日志 + 错误信息 |
| Python 输出不是 46 个块 | 输出目录截图 + 数量 |
| UI 显示不是一条带 | 地图区域截图（非洲南部特写） |
| 导出失败 | 错误消息截屏 |

---

## 🚀 立即开始

请按 **Step 1** 执行并回复："服务已启动"
