# FY/SMAP 反演问题修复总结

## 修复完成时间
2025-07-30

## 修复内容

### 1. 日期提取增强 ✅

**文件**: `Code/algorithms/providers/Python/algorithms/omega_sf.py`

**问题**: 原 `_scan_folder_dates` 只支持纯 `YYYYMMDD.mat` 文件名，导致以下格式的文件被忽略：
- `20250101_bundle.mat`
- `FY3D_20250101_processed.mat`
- `SMAP_L3_SM_P_20230110_R18290_001.mat`

**修复**: 增强日期提取逻辑，支持三种格式：
1. 纯日期: `YYYYMMDD.mat`
2. 日期+后缀: `YYYYMMDD_*.mat`
3. 前缀+日期: `*_YYYYMMDD_*.mat`

```python
# 新增代码
_ENHANCED_DATE_PATTERN = re.compile(r"(\d{8})")

def _scan_folder_dates(folder: str) -> set[datetime]:
    # 方法 1: 纯 YYYYMMDD 匹配
    if re.fullmatch(r"\d{8}", name):
        ...
    # 方法 2: 从文件名任意位置提取 YYYYMMDD
    match = _ENHANCED_DATE_PATTERN.search(f.name)
    ...
```

### 2. 文件名匹配安全性改进 ✅

**文件**: `Code/algorithms/providers/Python/ingest/daily_bundle.py`

**问题**: 原 `_resolve_daily_mat_file` 使用模糊匹配 `*{date_key}*.mat`，可能误匹配：
- 请求 `20250101.mat` 可能匹配到 `202501011_bundle.mat`

**修复**: 实现三级匹配优先级：
1. 精确匹配: `YYYYMMDD.mat`
2. 严格模式: `YYYYMMDD_suffix.mat`（单下划线+字母数字后缀）
3. 宽松匹配: `*YYYYMMDD*.mat`（带警告日志）

```python
def _resolve_daily_mat_file(folder: str | Path, date_key: str) -> Path:
    # 优先级 1: 精确匹配
    exact = folder / f"{date_key}.mat"
    if exact.exists():
        return exact

    # 优先级 2: 严格模式
    strict_pattern = re.compile(rf"^{re.escape(date_key)}_[a-zA-Z0-9_]+\.mat$")
    ...

    # 优先级 3: 宽松匹配（带警告）
    ...
```

### 3. 输出文件命名 Matlab 兼容 ✅

**文件**: `Code/algorithms/providers/Python/algorithms/omega_sf.py`

**问题**: Python 输出命名为 `block_001.mat`，丢失了日期信息，与 Matlab 的 `20250101_20250108.mat` 格式不兼容。

**修复**: 同时生成两种命名格式：
1. **Matlab 兼容格式**: `YYYYMMDD_YYYYMMDD.mat`（如 `20250101_20250108.mat`）
2. **向后兼容格式**: `block_{idx:03d}.mat`（如 `block_001.mat`）

```python
# 新命名逻辑
blk_start = block_struct.starts[blk_idx]
blk_end = block_struct.ends[blk_idx]
date_start_str = blk_start.strftime("%Y%m%d")
date_end_str = blk_end.strftime("%Y%m%d")

# Matlab 兼容命名
blk_file = out_path / f"{date_start_str}_{date_end_str}.mat"

# 向后兼容命名
blk_compat_file = out_path / f"block_{blk_idx:03d}.mat"
```

### 4. 8 天块划分验证 ✅

**验证结果**: Matlab 和 Python 的实现逻辑一致：
- 以每年 1 月 1 日为起点
- 每 8 天一块
- 年末不足 8 天按实际天数（如 2025 年最后一块为 12/27-12/31，共 5 天）
- 2025 年共 46 个块

### 5. EASE-Grid 坐标常量验证 ✅

**验证结果**: 使用 NSIDC 官方精确值：
- 形状: 1624 x 3856 (rows x cols)
- 分辨率: 9008.05521014913 m
- 边界: 使用官方角点坐标，避免投影有效域问题

## 问题根因分析

### 用户反馈问题
1. **"多个时间点的数据显示有混叠的感觉"** → 前端显示问题，需要时间序列分层显示
2. **"数据很破碎，非洲南部连成一片"** → 数据加载问题，部分日期文件被忽略
3. **"没有一条带一条带的感觉"** → SMAP 轨道覆盖特性未正确保留

### 根因
1. **日期提取过于严格** → 导致部分数据文件被跳过，时间序列不连续
2. **文件名匹配过于宽泛** → 可能加载错误日期的数据
3. **输出命名不规范** → 前端无法正确识别时间序列

## 验证结果

运行 `test_fix.py` 验证：
```
=== Test 1: Date Extraction ===
Found 1 dates
  - 2025-01-01

=== Test 2: 8-day Block Structure ===
Total blocks: 46
First 3 blocks:
  Block 0: 2025-01-01 ~ 2025-01-08 (8 days)
  Block 1: 2025-01-09 ~ 2025-01-16 (8 days)
  Block 2: 2025-01-17 ~ 2025-01-24 (8 days)
Last block:
  2025-12-27 ~ 2025-12-31 (5 days)
```

## 后续建议

### UI 全流程验证步骤
1. 启动完整栈: `start.bat`
2. 选择 `omega_sf_fenkuai` 工作流
3. 配置数据源路径
4. 运行并观察日志
5. 检查输出图层的空间分布

### 预期效果
- SM/VOD/OMEGA 三个图层按 8 天块独立显示
- 每个块有清晰的日期范围标识
- 非洲南部等区域显示合理的覆盖模式
- 时间切片切换时各块独立变化

### 如果仍有问题
1. 检查 SMAP L3 数据的有效值掩码
2. 验证前端是否正确按块分层显示
3. 检查 EASE-Grid 到经纬度的转换精度

## 相关文件

| 文件 | 修改内容 |
|------|----------|
| `algorithms/omega_sf.py` | 日期提取增强、输出命名改进 |
| `ingest/daily_bundle.py` | 文件名匹配安全性改进 |
| `test_fix.py` | 修复验证测试脚本 |
| `diag_fy_smap_comprehensive.py` | 综合诊断脚本 |

## 联系方式

如有问题，请查看：
- 诊断脚本: `diag_fy_smap_comprehensive.py`
- 修复计划: `FY_SMAP_REMEDIATION_PLAN.md`
- 本文档: `FY_SMAP_FIX_SUMMARY.md`
