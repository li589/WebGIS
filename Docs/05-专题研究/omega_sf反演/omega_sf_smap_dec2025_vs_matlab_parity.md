# omega_sf（SMAP）Dec 2025 vs Matlab `Omega_Custom_Res` 对比报告

- 生成时间：2026-08-02（全球跑完成后更新）
- 全球 UI 跑批：**`run-abcfad6d48db`**（种子 `omega_sf_fenkuai_smap_single`，`run_domain=GLOBAL`，`max_pixels=0`，Dec 2025；`requested_outputs` 含 `map_layer`）
- 状态：`succeeded`（约 67 min；成功反演 **369967** / 网格 6262083，成功率 5.9%）
- 前次同配置成功跑：`run-89d4e21a8715`（数值与本次一致量级）

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
| 20251203–20251210 | — | — | 318 140 | 0.347 |
| 20251211–20251218 | — | — | 319 809 | 0.358 |
| 20251219–20251226 | — | — | 323 794 | 0.359 |
| 20251227–20251231 | — | — | 147 932 | 0.287 |

## 重叠像元数值一致性（sample=2000）— `run-abcfad6d48db`

| 块 | n_overlap | MAE | median\|Δ\| | p95\|Δ\| |
|----|-----------|-----|-------------|---------|
| 20251203–10 | 318 140 | 0.0299 | **0.0046** | 0.1238 |
| 20251211–18 | 319 809 | 0.0390 | **0.0048** | 0.1670 |
| 20251219–26 | 323 794 | 0.0402 | **0.0048** | 0.1671 |
| 20251227–31 | 147 932 | 0.0379 | **0.0074** | 0.1645 |

解读：

1. **形状一致**：EASE 9 km 全球格网对齐。
2. **中位误差很好**：重叠像元中位绝对差约 **0.005–0.007**，主体分布与 Matlab 接近。
3. **尾部仍偏大**：MAE ~0.03–0.04、p95 ~0.12–0.17。
4. **覆盖缺口**：Python 成功反演约 37 万像元；Matlab 有效掩膜更宽，mask IoU ~0.29–0.36。

## UI / 跑批备注

- 提交形态：编译后的画布 `workflow_definition`（与工作流编辑器多图层启动等价），含 `map_layer` 输出。
- Worker：`heavy` 队列；产物目录四块 Dec mat + `omega_pixel.mat` / `omega_pft.mat`。
- 监控 loop 已在成功后停止。
