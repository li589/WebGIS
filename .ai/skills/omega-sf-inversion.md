# 技能：FY/SMAP `omega_sf` 土壤水分反演 + Matlab 一致性校验

> 场景：需要新增/修改/调试 FY-3D/FY-3B 与 SMAP 的 τ-ω 模型微波辐射反演（土壤水分 SM、植被光学厚度 VOD），并与 Matlab 参考实现 `omega_sf_fenkuai.m` 对照验证。
> 适用工具：后端 / 算法包开发（Python 3.12 + `Env/Python312`）。

## 1. 关键文件

| 角色 | 路径 |
|------|------|
| Python 主算法 | `Code/algorithms/providers/Python/algorithms/omega_sf.py` |
| 块反演流水线模块 | `Code/algorithms/providers/Python/modules/omega_sf_fenkuai.py` |
| Matlab 参考实现 | `Code/algorithms/providers/Matlab/omega_sf_fenkuai.m` |
| 已验证对照报告 | `.ai/docs/reference/omega_sf_smap_dec2025_vs_matlab_parity.md`、`omega_sf_export_tif_vs_matlab_detail.md` |
| 进度/修复记录 | `.ai/progress/fy-smap-*.md` |

算法流水线（`omega_sf.py` 模块 docstring 已确认）：
1. 构建时间序列（TB / SMAP / NDVI / 辅助数据交集）
2. 按 **8 天**划分时间块（`make_viirs8_blocks`）
3. 逐日 SF 倒推（`build_sf_row_daily`）或加载静态 SF
4. 逐块反演：低 τ 样本 → h/alpha 反演 → OMEGA 识别 → 逐日 SM/VOD
5. 汇总输出：OMEGA_pft / OMEGA_pixel + 逐日 SM / VOD

核心差异（与 `inversion.py` 的 DDCA/Retrieve_DH 区别，已核对代码）：
- `Q = max(alpha * h, 0)`（alpha 可优化），而非固定 `Q = 0.1771 * h`
- h/alpha **联合优化**（所有低 τ 样本同时拟合），而非逐样本反演 h
- OMEGA 块识别使用逐样本 h/alpha + 时间平滑正则化
- DDCA 初始猜测 `[0.20, Tau_ini]`，而非 `[0.2, 0.5]`

常量（与 Matlab `VWC.m`/`Tau.m` 对齐，已核对）：
- IGBP 代码：`10=Grasslands, 12=Croplands, 0=Water`（数据集 `IGBP_9km_12.mat` 用 `0` 表示水体）
- VWC 经验系数：`vwc_leaf = 1.9134*ndvi² - 0.3215*ndvi`（B 为负，Jackson 1999）
- NDVI 有效范围 `[0,1]`，超出置 nan
- 默认频率：FY `10.65 GHz`、SMAP `1.41 GHz`

`OmegaSfConfig`（`frozen` dataclass）镜像 Matlab CFG：
- `tb_source`: `"FY"` | `"SMAP"`
- `sm_source`: `"SMAP"` | `"ISMN"` | `"DDCA"`
- `fy_platform`: `"3D"` | `"3B"`
- `temp_scheme`: `"ORIG_TS"` | `"DUAL"`
- `run_domain`: `"ISMN"` | `"GLOBAL"`

## 2. 运行方式

- 全栈 worker：`Env\Python312\python.exe launch.py start worker:omega_sf`
- 算法包单测：`cd Code/algorithms/providers/Python && pytest tests/ -q`（注意 `run_job()` 统一入口，`modules + workflow` 主导，pipeline 仅兼容层）

## 3. 一致性校验流程（Matlab ↔ Python）

对照目标：Python 反演结果与 Matlab `omega_sf_fenkuai.m` 输出逐像元/逐块比对，算 **MAE**（均绝对误差）。

已达成基线（来自 `.ai/docs/reference/omega_sf_smap_dec2025_vs_matlab_parity.md`）：
- FY 反演 vs Matlab Dec 对照：**MAE ≈ 0.046–0.058**
- SMAP 反演 vs Matlab Dec 对照：**MAE ≈ 0.006–0.053**

对照步骤：
1. 取同一组输入（FY-3D/FY-3B 亮温 `.mat`、SMAP 亮温 `.mat`、两路 NDVI、SMAP ancillary 静态参数：容重/黏粒/IGBP 等）。
2. 跑 Python 反演，定位 `run-*` 产物（按日期/块组织，见进度文档）。
3. 与 `.ai/docs/reference/` 下已存对照报告同口径算 MAE；新结果写入 `omega_sf_*_vs_matlab_*.md`（归档到 `.ai/docs/reference/`）。
4. 若 MAE 显著偏离基线，按下方「已知坑」逐项排查。

## 4. 已知坑（来自 `.ai/progress/fy-smap-remediation-plan.md` 与修复记录）

- **preload 全 NaN**：数据预加载某通道整列 NaN 时后续反演会污染整块 → 需加 all-NaN 守卫（参考提交 `fix(backend): guard preload against all-NaN chunk` 风格）。
- **`event_factory` 即时落库 + `INSERT OR IGNORE`**：事件需即时落库，且重复主键用 `INSERT OR IGNORE` 避免回放冲突。
- **bbox 列表参数展开**：bbox 以列表传入时若未展开会破坏 SQL/查询参数 → 显式展开。
- **8 天块 / 空间显示不匹配**：反演按 8 天块，但前端时间轴/空间显示需与块边界对齐，常见「日期鲁棒性」「文件名三级匹配」问题。
- **日期鲁棒性**：文件名/数据中的日期解析需覆盖多种格式，避免 None。
- **文件名三级匹配**：输入文件按「平台-日期-通道」三级匹配，缺失一级会错配源。

## 5. 注意

- 大规模数据接入注意**双路 NDVI** 与**静态辅助数据（ancillary）**路径，避免错用源（对齐 `Doc/`→`.ai/docs/` 规范文档）。
- 凭据/数据通道属私有，仅走 `.ai/docs/specs/远程存储接入说明.md` 描述的 remote-storage 接口，不在此写入明文。
