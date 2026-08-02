# 完整的 UI 运行生产、显示、导出数据全流程验证清单

## ✅ 前置修复已完成

### 1. python-dotenv 依赖问题 - FIXED
- 修改位置：`Code/backend/app/core/config.py` Line 5-9
- 方案：用 try/except 绕过缺失的 dotenv 模块
- 验证结果：Config 能正常加载 ✅

### 2. FY/SMAP 核心算法修复（之前完成）
- ✅ `omega_sf.py`: 日期提取增强 + Matlab 兼容输出命名
- ✅ `daily_bundle.py`: 文件名匹配安全性改进  
- ✅ 8 天块划分逻辑验证通过 (46 blocks)

---

## 📋 请按照以下顺序执行验证

### **第一步：启动完整栈** (请在 PowerShell 中执行)

```powershell
cd D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system
.\start.bat
```

**预期看到**:
```
[OK] Docker containers started: redis, minio, open-meteo
[INFO] FastAPI started on http://127.0.0.1:8000
[INFO] Gateway started on http://localhost:5175
[OK] Workers started: standard, heavy, batch, weather, etc.
```

**⚠️ 关键点**: 
- 不再出现 `ModuleNotFoundError: No module named 'dotenv'` 错误
- 等待约 30-60 秒让所有服务完全就绪

**完成后回复**: "服务已启动"

---

### **第二步：访问 UI 验证** (浏览器操作)

打开浏览器：**http://localhost:5175**

#### 验证 A: 图层管理器刷新异常
1. **刷新页面** (按 F5 或 Ctrl+R)
2. 检查右侧 **"图层"** 面板
3. 查看 **"已添加图层"** 标签页

**✅ 预期结果**:
- "已添加图层" 为空列表
- 只显示图层库（未添加状态）

**❌ 如果异常**:
- 截图发给我，我会检查 `activeLayers` 持久化逻辑

#### 验证 B: 时间轴默认小时刻度
1. 确保没有选择任何 FY/SMAP 相关图层
2. 观察底部时间轴组件

**✅ 预期结果**:
- 显示 0-23 小时滑块
- 滑块可自由拖动
- 不触发数据加载

**❌ 如果异常**:
- 截图发给我，我会检查 TimelineScrubber.vue

**完成后回复**: "UI 验证完成"

---

### **第三步：运行 FY/SMAP 反演工作流** (请在 UI 中操作)

1. 在左侧图层库中找到 **`omega_sf_fenkuai`**
2. 点击 **"运行工作流"** 按钮
3. 配置参数（使用默认值即可）
4. 提交后等待 Celery Worker 完成

**预期流程**:
- 状态变为 "运行中..." 
- 进度条更新
- 完成后状态为 "成功"

**完成后回复**: "工作流运行完成"

---

### **第四步：对比 Python vs Matlab 输出** (请在 PowerShell 中执行)

```powershell
# Python 反演结果（新）
Write-Host "=== Python Output (omega_sf_fenkuai) ==="
dir I:\Geograph_DataSet\Inversion_Results\omega_sf_fenkuai\block_output\*.mat | 
    Select-Object -First 10 Name, Length, LastWriteTime

# Matlab 参考数据（旧）
Write-Host "`n=== Matlab Reference (Omega_Custom_Res) ==="
dir I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res\smap_raw_omega\*.mat | 
    Select-Object -First 10 Name, Length, LastWriteTime

# 统计数量
$python_count = dir I:\Geograph_DataSet\Inversion_Results\omega_sf_fenkuai\block_output\*.mat | Measure-Object
$matlab_count = dir I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res\smap_raw_omega\*.mat | Measure-Object

Write-Host "`n[STATS]"
Write-Host "Python output blocks: $($python_count.Count)"
Write-Host "Matlab reference blocks: $($matlab_count.Count)"
```

**✅ 预期结果**:
- Python 生成 **46 个** 块级文件
- 每个块文件名为 `YYYYMMDD_YYYYMMDD.mat` 格式
- 文件格式与 Matlab 一致

**❌ 如果异常**:
- 告知我具体的块数和文件名

**完成后回复**: "输出对比完成"

---

### **第五步：UI 显示验证** (请在浏览器中操作)

1. 在工作流完成后的结果页面
2. 点击 **"添加到地图"** 或自动添加到图层管理器
3. 在图层管理器中选择该图层
4. 观察地图上的显示效果

**✅ 预期结果**:
- SM (土壤湿度) 独立显示
- VOD (植被光学厚度) 独立显示
- OMEGA 独立显示
- 每个都按 8 天块独立渲染，不是叠加混合

**验证时间序列切换**:
5. 找到时间轴/时间选择器
6. 尝试切换到不同的 8 天块

**✅ 预期结果**:
- 能正确显示对应时间块的 SM/VOD/OMEGA
- 每个块内的像素呈现"一条带一条带"的轨道特征

**❌ 如果异常**:
- 截图发给我（整个界面 + 图层管理器 + 时间轴）
- 描述具体问题（混叠？破碎？非洲南部连成一片？）

**完成后回复**: "UI 显示验证完成"

---

### **第六步：数据导出功能验证** (请在 UI 中操作)

1. 选择一个完成的图层（如 SM 图层）
2. 查找 **"导出"** 或 **"下载结果"** 按钮
3. 选择导出格式（GeoTIFF / NetCDF / MAT）
4. 导出到本地

**✅ 预期结果**:
- 导出成功
- 文件大小合理（例如 GeoTIFF ~50MB 对于全球 EASE-Grid）
- 能在 GIS 软件（QGIS/ArcGIS）中打开

**❌ 如果异常**:
- 截图发给我（包括错误信息）
- 描述具体问题

**完成后回复**: "导出验证完成"

---

## 🎯 最终目标检查清单

- [ ] **服务启动**: start.bat 正常启动所有服务（无 dotenv 错误）
- [ ] **图层管理**: 刷新后无异常自动显示图层
- [ ] **时间轴**: 无数据时默认显示 0-23 小时刻度
- [ ] **工作流运行**: omega_sf_fenkuai 成功运行
- [ ] **输出对比**: Python 生成 46 个块，Matlab 兼容格式
- [ ] **UI 显示**: SM/VOD/OMEGA 独立显示，有"一条带"特征
- [ ] **时间切换**: 能按 8 天块切换时间
- [ ] **数据导出**: 导出功能正常工作

---

## 🔧 可能遇到的问题与解决方案

| 问题 | 解决 |
|------|------|
| start.bat 报错 dotenv | ✅ 已修复，config.py 改用 try/except |
| 浏览器无法打开 localhost:5175 | 检查前端是否启动，或尝试 `Code/frontend/npm run dev` |
| Worker 持续退出 | 查看终端日志，告诉我具体错误 |
| UI 空白或报错 | 按 F12 查看浏览器控制台错误，截图发给我 |

---

## 📞 立即开始

请执行 **第一步**，完成后告诉我："服务已启动"

我会继续指导您完成后续验证步骤。
