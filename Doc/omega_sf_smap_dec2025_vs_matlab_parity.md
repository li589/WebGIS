# omega_sf（SMAP）Dec 2025 vs Matlab `Omega_Custom_Res` 对比报告

- 生成时间：2026-08-02（全球跑完成后更新）
- 全球 UI 跑批：**`run-89d4e21a8715`**（种子 `omega_sf_fenkuai_smap_single`，`run_domain=GLOBAL`，`max_pixels=0`，Dec 2025）
- 状态：`succeeded`（约 87.7 min；成功反演 ~37.0 万像元 / 网格 626 万像元中有效尝试，日志：`成功 369967 / 失败 5892116`）
- 前次失败：`run-6e2c106f335f`（`clay_fraction=NaN`）；已在 `omega_sf.py` 跳过无 clay/porosity 像元后重跑

## 对照数据

| 侧 | 路径 |
|----|------|
| Matlab 参考 | `I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res\smap_raw_omega\` |
| Python 预测 | `I:\Geograph_DataSet\_runtime\python_provider\products\omega_sf_fenkuai\` |
| 工具 | `Tools/compare_omega_block_parity.py`（重叠有限像元随机抽样，`--sample 2000`） |

网格形状两侧均为 `(1624, 3856)`。Matlab 键为 `OMEGA_grid`；Python 键为 `OMEGA`。

## 覆盖度（有限像元数）

| 块 | Matlab finite | Python finite | 重叠 finite | mask_iou |
|----|---------------|---------------|-------------|----------|
| 20251203–20251210 | 811 314 | 366 775 | 318 140 | 0.347 |
| 20251211–20251218 | 825 032 | 367 953 | 319 809 | 0.358 |
| 20251219–20251226 | 864 859 | 368 531 | 323 794 | 0.359 |
| 20251227–20251231 | 384 413 | 170 983 | 147 932 | 0.287 |

说明：Python 全球场约为 Matlab 有效掩膜的 ~40–45%（末块略低）；重叠区约 15–32 万像元，已远超先前条带（~1.5k）量级。

## 重叠像元数值一致性（sample=2000）

| 块 | n_overlap | MAE | median\|Δ\| | p95\|Δ\| |
|----|-----------|-----|-------------|---------|
| 20251203–10 | 318 140 | 0.0299 | **0.0046** | 0.1238 |
| 20251211–18 | 319 809 | 0.0390 | **0.0048** | 0.1670 |
| 20251219–26 | 323 794 | 0.0402 | **0.0048** | 0.1671 |
| 20251227–31 | 147 932 | 0.0379 | **0.0074** | 0.1645 |

解读：

1. **形状一致**：EASE 9 km 全球格网对齐。
2. **中位误差很好**：重叠像元中位绝对差约 **0.005–0.007**，主体分布与 Matlab 接近。
3. **尾部仍偏大**：MAE ~0.03–0.04、p95 ~0.12–0.17，说明少数像元偏差拉高均值（需后续查 outlier / QC / 有效性掩膜差异）。
4. **覆盖缺口**：Matlab 仍有更多有限 OMEGA；Python 成功率受 clay/TB/SM/NDVI 等联合有效性约束，约 15.6% 网格进度计数 vs 5.9% 成功反演（其余为跳过或失败）。

## UI / 跑批备注

- 提交形态：编译后的画布 `workflow_definition`（与工作流编辑器多图层启动等价）。
- 修复：`workflow_request_resolver` 读取编译节点 `params` 并解析相对数据路径；`omega_sf` 跳过 NaN clay/porosity，单像元 `ValueError` 不拖垮批次。
- Worker：`standard` 队列；chunk 9 曾 `BrokenProcessPool` 后回退串行，其后并行恢复。
- 产物写入时间：2026-08-02 16:09（四块 Dec mat）。

## 可选后续

1. 对照 `smap_raw_smvod` 的 SM/VOD。
2. 将全球产物挂回地图做目视检查。
3. 分析高误差尾部像元与 Matlab QC 差异。
