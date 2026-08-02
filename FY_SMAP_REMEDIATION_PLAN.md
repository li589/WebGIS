# FY/SMAP 反演问题 - 最终诊断与解决方案

## 执行摘要

根据对代码的深度分析，确认用户反馈的问题根源在于**数据日期提取的严格性不足**以及**8 天块与空间显示的不匹配**。以下是完整的诊断和修复方案。

---

## 一、核心问题分析

### 1.1 症状描述
- ✅ **数据显示混叠** - 多个时间点的数据在地图上重叠显示
- ✅ **输出破碎** - Matlab 预期是清晰的"一条带一条带"效果，Python 产出非常破碎
- ✅ **非洲南部连成一片** - 缺乏独立的块状结构

### 1.2 根本原因

#### 问题 A: 日期提取不够鲁棒 ❌

**位置：** `algorithms/omega_sf.py` Line 1546-1563

```python
def _scan_folder_dates(folder: str) -> set[datetime]:
    """扫描文件夹中的 YYYYMMDD.mat 文件，返回日期集合。"""
    for f in p.glob("*.mat"):
        name = f.stem  # ← 假设文件名纯 YYYYMMDD
        try:
            d = datetime.strptime(name, "%Y%m%d")  # ← 严格要求匹配
            dates.add(d)
        except ValueError:
            continue  # ← 跳过不匹配的文件
```

**实际场景：**
- SMAP 处理后可能生成：`20250101_bundle.mat`, `20250101_processed.mat`
- FY GBAL 处理后可能生成：`FY3D_GB_20250101.mat`, `20250101_fy3d.mat`

这些文件名都会被 `_scan_folder_dates` 忽略，导致该日期的数据被跳过！

#### 问题 B: 文件名模糊匹配过于宽泛 ⚠️

**位置：** `ingest/daily_bundle.py` Line 414-422

```python
def _resolve_daily_mat_file(folder: str | Path, date_key: str) -> Path:
    direct = folder / f"{date_key}.mat"
    if direct.exists():
        return direct
    
    matches = sorted(folder.glob(f"*{date_key}*.mat"))  # ← 模糊匹配
    if matches:
        return matches[0]
```

**危险示例：**
- 请求：`20250101.mat`
- 找到：`20250101_bundle.mat` ✓ (应该用)
- 但也会找到：`202501011.mat` ✗ (错误!)

#### 问题 C: 8 天块的空间显示逻辑缺失 🎯

**Matlab 的工作方式：**
1. 按 8 天划分时间块
2. **每个块独立处理** → 生成独立的网格/图层
3. 结果显示时按时间滑动查看 → 自然呈现"一条带"效果

**Python 当前实现：**
1. 将所有时间块的像素混合成一个超长序列 (Nt days)
2. 一次性对所有像素进行反演
3. 输出是连续的时间序列 → 视觉上混叠在一起

**核心差异：**
- Matlab: Block-by-block spatial processing
- Python: Global temporal sequence processing

---

## 二、验证与诊断工具

### 2.1 快速诊断脚本

**文件:** `diag_quick_check.py`

**用法:**
```bash
cd "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python"
..\..\..\diag_quick_check.py I:/Geograph_DataSet/SMAP I:/Geograph_DataSet/FY3 I:/Geograph_DataSet/Ancillary
```

**功能:**
1. 对比两种日期提取模式（严格 vs 增强）
2. 统计文件命名模式的分布
3. 分析 8 天块的覆盖完整性
4. 生成改进建议

### 2.2 全面诊断脚本

**文件:** `diag_fy_smap_full.py`

**功能:**
- 完整的数据流路径检查
- 时间范围对齐验证
- MAT 字段结构分析
- 8 天块结构详细报告

---

## 三、工程化修复方案

### Phase 1: 立即修复（今日完成）⭐⭐⭐

#### Fix 1: 增强日期提取鲁棒性

**修改文件：** `Code/algorithms/providers/Python/algorithms/omega_sf.py`

**修改内容：**

```python
import re

# Add at module level (near top of file)
_ENHANCED_DATE_PATTERN = re.compile(r"(\d{8})")


def _scan_folder_dates_enhanced(folder: str) -> set[datetime]:
    """增强版：支持 YYYYMMDD_*.*.*格式的 Mat 文件。
    
    对应 Matlab 的日期提取逻辑，从文件名中提取任意 YYYYMMDD 模式。
    """
    from pathlib import Path
    
    if not folder:
        return set()
    
    p = Path(folder)
    if not p.exists():
        logger.warning("Folder does not exist: %s", folder)
        return set()
    
    dates: set[datetime] = set()
    invalid_names = []
    
    for f in p.glob("*.mat"):
        # Method 1: Try exact YYYYMMDD match first
        if re.match(r"^\d{8}$", f.stem):
            try:
                d = datetime.strptime(f.stem, "%Y%m%d")
                dates.add(d)
                continue
            except ValueError:
                pass
        
        # Method 2: Extract YYYYMMDD from any position
        match = _ENHANCED_DATE_PATTERN.search(f.name)
        if match:
            date_str = match.group(1)
            try:
                d = datetime.strptime(date_str, "%Y%m%d")
                dates.add(d)
            except ValueError:
                invalid_names.append(f.name)
    
    if len(invalid_names) > 10:
        logger.warning("Found %d files with unparseable names in %s", 
                      len(invalid_names), folder)
    
    return dates


# Replace the old function with this enhanced version
def _scan_folder_dates(folder: str) -> set[datetime]:
    """Scan folder for YYYYMMDD.mat files and return date set."""
    return _scan_folder_dates_enhanced(folder)
```

**预期效果：**
- 可识别更多格式的文件名
- 不会漏掉有效数据
- 向后兼容原有纯日期命名

#### Fix 2: 改进文件名匹配安全性

**修改文件：** `Code/algorithms/providers/Python/ingest/daily_bundle.py`

**修改内容：**

```python
import re

# Add at module level
_DAY_FILENAME_PATTERN = re.compile(r"^(\d{8})(?:_\w+)?\.mat$")


def _resolve_daily_mat_file(folder: str | Path, date_key: str) -> Path:
    folder = Path(folder)
    
    # Priority 1: Exact match YYYYMMDD.mat
    exact = folder / f"{date_key}.mat"
    if exact.exists():
        return exact
    
    # Priority 2: Strict pattern matching YYYYMMDD_*.mat
    # Only allow single underscore followed by alphanumeric suffix
    strict_pattern = re.compile(rf"^{re.escape(date_key)}_(\w+)\.mat$")
    
    for f in folder.glob("*.mat"):
        if strict_pattern.match(f.name):
            return f
    
    # Priority 3: Loose fuzzy match (fallback only)
    matches = sorted(folder.glob(f"*{date_key}*.mat"))
    if matches:
        logger.warning(
            "Fuzzy match used for %s: %s (prefer exact or YYYYMMDD_suffix.mat)",
            date_key, matches[0].name
        )
        return matches[0]
    
    raise FileNotFoundError(f"Cannot find {date_key}.*.mat under {folder}")
```

**效果：**
- 优先精确匹配
- 其次匹配 `YYYYMMDD_suffix.mat` 模式
- 最后才使用模糊匹配（带警告）

#### Fix 3: 确保 8 天块独立性（关键！）

**这是解决"一条带一条带"效果的核心！**

**需要理解的关键逻辑：**

目前 omega_sf.py 的流水线是：
```
Build time series (Nt days) 
→ Make blocks (K blocks of 8 days each)  
→ Execute pixel inversion (all Nt days together)
→ Output: SM_maps[block_idx], VOD_maps[block_idx], OMEGA_maps[block_idx]
```

问题在于**像素反演阶段没有按块独立执行**！

**修正方案：**

需要在 `retrieve_omega_sf_daily()`函数中增加**逐块反演的逻辑分支**：

```python
# In retrieve_omega_sf_daily(), after block_struct is built:

# Option 1: Block-by-block mode (recommended for MATLAB compatibility)
if config.block_mode.upper() == "BLOCK_BY_BLOCK":
    logger.info("[MODE] Running in BLOCK_BY_BLOCK mode")
    
    sm_block_results = {}
    vod_block_results = {}
    omega_block_results = {}
    
    for block_idx in range(len(block_struct.starts)):
        logger.info(f"[BLOCK] Processing block {block_idx}/{len(block_struct.starts)}")
        
        # Extract dates for this specific block
        block_indices = block_struct.indices[block_idx]
        block_dates = [tvec[i] for i in block_indices]
        
        # Build per-block data slices
        tbv_block = tbv_all[:, block_indices]
        tbh_block = tbh_all[:, block_indices]
        # ... similar for other variables
        
        # Run per-block inversion (modified execute_pixel_inclusion to accept limited tvec)
        block_result = execute_pixel_inversion_per_block(
            tbv_block, tbh_block, ..., config, block_struct, block_idx
        )
        
        # Store results
        sm_block_results[block_idx] = block_result.sm_map
        vod_block_results[block_idx] = block_result.vod_map
        omega_block_results[block_idx] = block_result.omega_map


# Option 2: Full sequence mode (current behavior)
else:
    # Current implementation runs all-at-once
    # This may produce fragmented results due to global optimization
    full_result = execute_pixel_inversion_all(...)
```

---

### Phase 2: 中期优化（明日完成）⭐⭐

#### Optimization 1: 添加空间掩码一致性

确保每个块的 NaN 区域一致，避免视觉上的"破碎"感。

#### Optimization 2: EASE-Grid 投影精度提升

检查浮点精度在坐标转换中的累积误差。

#### Optimization 3: UI 时间切片控件

在前端增加"按块切换"而非"按日切换"的选项。

---

### Phase 3: UI 全流程验证（后天完成）⭐

1. 启动完整栈
2. 选择 `omega_sf_fenkuai` 流程
3. 配置数据源和时间范围
4. 观察运行日志
5. 检查结果图层的空间分布

---

## 四、执行清单

### 今日必须完成的任务

- [ ] **Fix 1**: 增强 `_scan_folder_dates` 函数
- [ ] **Fix 2**: 改进 `_resolve_daily_mat_file` 的匹配规则
- [ ] **运行诊断**: 使用 `diag_quick_check.py`验证修复效果
- [ ] **单元测试**: 编写日期提取的测试用例

### 技术验收标准

✅ **日期提取：**
- 能正确解析 `20250101.mat`
- 能正确解析 `20250101_bundle.mat`
- 能正确解析 `FY3D_20250101_processed.mat`
- 不会因为文件名后缀导致数据丢失

✅ **8 天块划分：**
- 块数量合理（约 45-46 块/年）
- 每块天数接近 8 天（首尾块可能少于 8 天）
- 跨年自动重置

✅ **输出质量：**
- SM/VOD/OMEGA 三个图层独立可见
- 每个块有清晰的空间边界
- 非洲南部的碎片化程度明显改善

---

## 五、紧急预案

如果修复后仍有问题：

1. **回滚到旧版本**
   ```bash
   git stash  # 暂存当前修改
   git checkout <previous-stable>
   ```

2. **缩小验证范围**
   - 将时间范围改为单个月份（如 20250101-20250131）
   - 仅处理一个小地理区域（裁剪 landcover）

3. **切换到 Matlab 模式**
   - 暂时禁用 Python 反演
   - 直接使用 Matlab GUI 生成结果导入

---

## 六、关键代码位置索引

| 文件 | 行号 | 功能 |
|------|------|------|
| `algorithms/omega_sf.py` | 1546-1563 | `_scan_folder_dates` (待修复) |
| `ingest/daily_bundle.py` | 414-422 | `_resolve_daily_mat_file` (待修复) |
| `algorithms/omega_sf.py` | 269-312 | `make_viirs8_blocks` (正确) |
| `algorithms/omega_sf.py` | 1208-1500 | `retrieve_omega_sf_daily` (需增块独立模式) |
| `algorithms/omega_sf.py` | 530-900 | `execute_pixel_inversion` (核心反演) |

---

## 七、联系方式与支持

- **诊断工具**: `diag_quick_check.py`, `diag_fy_smap_full.py`
- **修复计划**: `.trae/documents/fysmap_problem_fix_plan.md`
- **参考文档**: `Doc/CGDA 一键启动完整指南.md`

---

**生成时间**: 2025-07-30  
**版本**: v1.0  
**状态**: 待实施
