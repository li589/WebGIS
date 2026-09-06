# FY/SMAP 反演问题诊断与修复计划

## 问题描述

根据用户反馈：
1. **显示混叠** - 多个时间点的数据显示有混叠感觉
2. **数据破碎** - 理论上 Matlab 结果应该是一条带一条带的（每 8 天一个），但反演的很破碎
3. **非洲南部连成一片** - 根本没有一条带一条带的感觉

可能的问题根源:
- **日期解析错误** - FY/SMAP 文件名中的日期提取可能不准确
- **8 天块划分逻辑错误** - VIIRS 轨道编号方式可能与简单按 8 天分段不同
- **数据对齐问题** - SMAP/FY 数据的实际可用性与期望不匹配
- **坐标系转换精度丢失** - EASE-Grid 转换中的浮点精度问题

## 检查清单

### 一、数据拉取阶段 ✅

#### 1.1 SMAP 数据

**检查项：**
- [ ] SMAP L3 原始文件命名格式正确
- [ ] 日期提取正则表达式准确
- [ ] 时间范围过滤正确

**当前实现：**
```python
# Code/algorithms/providers/Python/ingest/smap.py
SMAP_DATE_PATTERN = re.compile(r"(\d{8})")

def extract_date_from_smap_filename(file_path: str | Path) -> str:
    match = SMAP_DATE_PATTERN.search(Path(file_path).name)
    return match.group(1)
```

**潜在问题：**
- 文件名中可能有多个 8 位数字串
- SMAP 文件名：`SMAP_L3_SM_P_20230110_R18290_001.h5` - OK
- 但可能存在混淆

**验证命令：**
```bash
cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system"
.\Env\Python312\python.exe diag_fy_smap_full.py
```

#### 1.2 FY 数据

**检查项：**
- [ ] FY 文件名格式识别正确 (MWRID/MWRIA)
- [ ] 下降轨/上升轨区分正确
- [ ] FY3B/FY3D识别正确

**当前实现：**
```python
# Code/algorithms/providers/Python/ingest/fy.py
FY_DATE_PATTERN = re.compile(r"(\d{8})")

def detect_fy_orbit_type(file_name: str) -> str:
    if "MWRID" in file_name:
        return "MWRID"  # descending
    if "MWRIA" in file_name:
        return "MWRIA"  # ascending
```

**预期文件名格式：**
`FY3B_MWR_GBAL_L1_10V10H_20250101_20250101_MWRID.hdf`

### 二、8 天块划分 ⚠️

这是最可能出问题的地方！

#### 2.1 当前实现

```python
# Code/algorithms/providers/Python/algorithms/omega_sf.py
def make_viirs8_blocks(tvec: list[datetime]) -> BlockStructure:
    """按 8 天划分时间块（VIIRS 风格）。"""
    
    doy = [t.timetuple().tm_yday for t in tvec]
    yy = [t.year for t in tvec]
    blk_starts_raw = [
        datetime(y, 1, 1) + timedelta(days=8 * ((d - 1) // 8))
        for y, d in zip(yy, doy)
    ]
    
    # ...去重...
```

**算法解释：**
- 以每年 1 月 1 日为起点（第 1 天）
- day 1-8 → Block 0 (Jan 1-8)
- day 9-16 → Block 1 (Jan 9-16)  
- day 17-24 → Block 2 (Jan 17-24)
- ...以此类推

**潜在问题：**
这与 Matlab 的 VIIRS 轨道编号是否一致？需要确认 Matlab 代码。

#### 2.2 Matlab 对照

在 `Code/algorithms/providers/Matlab/omega_sf_fenkuai.m` 中查找 `make_viirs8_blocks` 函数。

### 三、数据流传输 ⚠️

#### 3.1 daily_bundle.py 的数据提取

**关键函数：** `_resolve_daily_mat_file`

```python
# Line 414-422
def _resolve_daily_mat_file(folder: str | Path, date_key: str) -> Path:
    folder = Path(folder)
    direct = folder / f"{date_key}.mat"
    if direct.exists():
        return direct
    
    matches = sorted(folder.glob(f"*{date_key}*.mat"))
    if matches:
        return matches[0]
    
    raise FileNotFoundError(...)
```

**问题：**
这个模糊匹配可能匹配到错误的文件！例如：
- 请求 `20250101.mat`
- 找到了 `20250101_bundle.mat` ✓
- 但也可能找到 `202501011_bundle.mat` ✗

**建议修复：**
使用更严格的正则表达式匹配。

#### 3.2 字段名称映射

**关键位置：** `DailyBundleConfig` (Line 16-58)

```python
tbv_aliases: tuple[str, ...] = ("TBv", "tbv", "tb_v_corrected")
tbh_aliases: tuple[str, ...] = ("TBh", "tbh", "tb_h_corrected")
ts_aliases: tuple[str, ...] = ("Ts", "ts", "surface_temperature")
```

**检查项：**
- [ ] SMAP MAT 文件中的实际字段名
- [ ] FY GBAL 处理后的实际字段名
- [ ] 别名是否覆盖所有情况

### 四、坐标系转换 ⚠️

#### 4.1 EASE-Grid 投影

**可能问题点：**
- Lat/Lon to Grid坐标转换中的舍入误差
- 浮点精度导致的像元索引偏移
- 边界处理不一致

**需要检查的文件：**
- `algorithms/geospatial_utils.py`
- `algorithms/omega_sf.py` 中的网格构建

### 五、反演输出 🎯

#### 5.1 输出目录结构

预期：
```
Inversion_Results/
├── omega_sf_fenkuai/
│   ├── blocks/
│   │   ├── block_001_SM.mat      (20250101-20250108)
│   │   ├── block_001_VOD.mat
│   │   ├── block_001_OMEGA.mat
│   │   ├── block_002_SM.mat
│   │   └── ...
│   ├── omega_pixel.tif
│   └── omega_pft.mat
```

**检查项：**
- [ ] 每个块的日期范围正确
- [ ] SM/VOD/OMEGA三图层对应
- [ ] 像素级别 OMEGA 图的空间连续性

## 执行计划

### Phase 1: 立即验证（今天完成）

1. **运行诊断脚本** 
   ```bash
   cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system"
   .\Env\Python312\python.exe diag_fy_smap_full.py > diag_report.txt
   ```

2. **检查输出报告**
   - 数据日期范围是否正确
   - 是否有明显的日期断档
   - 8 天块划分的合理性

3. **对比 Matlab 结果**
   - 找出一条带样本（Matlab 产出 vs Python 产出）
   - 逐像素对比数值
   - 空间分布差异

### Phase 2: 数据修复（明天）

根据 Phase 1 的诊断结果，针对性修复：

#### Scenario A: 日期提取错误

**修复目标：**
确保 `extract_date_from_fy_filename()` 和 `extract_date_from_smap_filename()` 能准确提取正确的日期。

**示例修复：**
```python
# 更严格的名字模式
FY_FILENAME_PATTERN = re.compile(
    r"FY\d_[A-Z]{2}_GBAL_\d+([VH])_(\d{8})_"
)

def extract_date_from_fy_filename(file_name: str) -> str:
    match = FY_FILENAME_PATTERN.match(file_name)
    if not match:
        raise ValueError(...)
    return match.group(2)
```

#### Scenario B: 8 天块逻辑错误

如果 Matlab 使用不同的块划分方式，需要同步：

```python
# 假设 Matlab 使用轨道编号而非固定日历
def make_viirs8_blocks_with_orbit(tvec: list[datetime], orbits: list[int]) -> BlockStructure:
    """使用 VIIRS 轨道编号进行 8 天块划分。"""
    # TODO: 需要根据 Matlab 逻辑调整
    pass
```

#### Scenario C: 数据匹配错误

改进 `_resolve_daily_mat_file()`:

```python
def _resolve_daily_mat_file(folder: str | Path, date_key: str) -> Path:
    folder = Path(folder)
    
    # 优先精确匹配 YYYYMMDD.mat
    exact = folder / f"{date_key}.mat"
    if exact.exists():
        return exact
    
    # 次优：YYYYMMDD*.mat（限制后缀）
    pattern_match = list(folder.glob(f"{date_key}?.mat"))
    if pattern_match:
        return sorted(pattern_match)[0]
    
    raise FileNotFoundError(f"Cannot find {date_key}.*.mat under {folder}")
```

### Phase 3: UI 全流程验证（后天）

1. 启动完整栈
   ```bash
   start.bat
   ```

2. 在工作流界面选择 omega_sf_fenkuai 流程
   - 配置正确的数据源路径
   - 设置时间范围（建议先测试一小段）

3. 观察运行日志
   - daily_bundle 节点构建的日期序列
   - omega_sf_fenkuai 节点的进度和块数量

4. 检查结果图层
   - SM/VOD/OMEGA 三个图层
   - 空间分布是否符合"一条带一条带"的预期
   - 与 Matlab 结果的视觉对比

## 成功标准

✅ **UI 全流程通过的条件：**
1. 工作流正常完成，无异常退出
2. 生成的 SM 图层显示清晰的分块结构（非连成一片）
3. 每块的时间跨度约为 8 天
4. 数据值合理（SM: 0-1, VOD: 0-5, OMEGA: 0-1）
5. 时间切片显示时，各块独立变化而非混叠

✅ **与 Matlab 对比：**
- 相同区域的 SM/VOD 曲线趋势一致
- 异常值（NaN/无效区域）位置一致
- 整体统计特征（均值、方差、最大值最小值）接近

## 紧急修复预案

如果发现重大错误，准备以下回滚方案：

### 回滚 1: 使用旧版 stable分支
```bash
git checkout <previous-stable-commit>
```

### 回滚 2: 切换到纯 Matlab 运行
暂时禁用 Python 反演模块，直接使用 Matlab GUI 生成结果导入。

### 回滚 3: 缩小验证范围
将时间范围限制为单个月份，甚至单个 8 天块，简化调试复杂度。
