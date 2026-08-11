# 导出 TIF（Downloads/1、2）vs Matlab `Omega_Custom_Res` 细致对比

- 分析时间：2026-08-02
- 导出路径：`C:\Users\likr\Downloads\1` 与 `...\2`（**字节级完全相同**，下文只分析文件夹 1）
- Matlab 参考：`I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res\`
- Python 运行产物：`I:\Geograph_DataSet\_runtime\python_provider\products\omega_sf_fenkuai\`（`run-abcfad6d48db`）
- 原始统计 JSON：`Doc/omega_sf_export_tif_vs_matlab_detail.json`

## 1. 导出物是什么

| 文件 | 格网 | CRS | 有效像元 | 对应产物语义 |
|------|------|-----|----------|--------------|
| `omega_sf_fenkuai_OMEGA.tif` | 1624×3856 EASE 9 km | EPSG:6933 | **369 967** | 像素级 OMEGA（`omega_pixel.mat` / `omega_pix_map`） |
| `OMEGA_BLOCK.tif` | 同上 | 同上 | **170 983** | **仅末块** `20251227–20251231` 的块级 OMEGA |
| `omega_sf_fenkuai_SM.tif` | 同上 | 同上 | **170 983** | **仅末块** SM |
| `omega_sf_fenkuai_VOD.tif` | 同上 | 同上 | **170 983** | **仅末块** VOD |

说明：UI 导出的 SM/VOD/OMEGA_BLOCK 来自「最新一块」物化结果，不是 12 月四块平均；像素级 OMEGA 才是全月全球成功像元全集。

## 2. 导出完整性（TIF ↔ Python 产物）

| 对比 | 重叠 | median\|Δ\| | corr |
|------|------|-------------|------|
| OMEGA TIF ↔ `omega_pixel.mat` | 369 967 | ~2.7e-9 | **1.000** |
| OMEGA_BLOCK TIF ↔ `20251227_20251231.mat:OMEGA` | 170 983 | ~2.4e-9 | **1.000** |
| SM TIF ↔ 末块 `SM` | 170 983 | ~1.5e-9 | **1.000** |
| VOD TIF ↔ 末块 `VOD` | 170 983 | ~5e-10 | **1.000** |

结论：导出 TIF 与当次 Python 科学产物 **数值一致**（浮点往返误差量级），可作为 UI 导出链路的正确性证明。

## 3. 与 Matlab 对比（核心）

### 3.1 像素级 OMEGA TIF vs Matlab `smap_raw_omega` 各 8-day 块

| Matlab 块 | 重叠有限像元 | mask IoU | median\|Δ\| | MAE | p95\|Δ\| | corr(抽样) |
|-----------|--------------|----------|-------------|-----|----------|------------|
| 20251203–10 | 319 206 | 0.370 | **0.0047** | 0.0335 | 0.139 | 0.16 |
| 20251211–18 | 320 232 | 0.366 | **0.0046** | 0.0353 | — | 0.28 |
| 20251219–26 | 323 906 | 0.356 | **0.0053** | 0.0406 | — | 0.16 |
| 四块 nanmean | 325 720 | 0.350 | **0.0056** | 0.0358 | 0.155 | 0.28 |

解读：

- **中位误差很好**（~0.005），与此前 mat↔mat 全球对照一致。
- Matlab 有效掩膜更宽（单块 ~38–86 万 vs Python ~37 万），IoU ~0.35–0.37。
- **相关系数偏低**：重叠区主体接近，但尾部/局部差异拉低线性相关（MAE≫median）。

### 3.2 末块导出 vs Matlab（应对齐的一对）

| 导出 | Matlab 对照 | 重叠 | median\|Δ\| | MAE | corr |
|------|-------------|------|-------------|-----|------|
| OMEGA_BLOCK | `smap_raw_omega` 20251227–31 | 147 932 | **0.0066** | 0.0396 | 0.26 |
| SM | `smap_raw_smvod` 日均 12/27–31 | 147 932 | **0.0019** | 0.0064 | **0.993** |
| VOD | 同上日均 VOD | 147 932 | 0.0287 | 0.0561 | **0.963** |

解读：

- **SM 与 Matlab 末候日均高度一致**（corr≈0.99，median≈0.002）。
- **VOD 相关仍高（0.96）但偏差更大**（median≈0.029，偏置约 −0.05），需后续查尺度/QC。
- **OMEGA 块级**中位仍好，相关偏弱——与像素级 OMEGA 对 Matlab 的模式相同。

## 4. 文件夹 1 vs 2

四文件 **MD5/字节完全相同**，无需区分；重复导出。

## 5. 结论与使用建议

1. 导出 TIF 忠实于 Python 全球跑 `run-abcfad6d48db`，格网与 Matlab 同为 1624×3856。
2. 和 Matlab 比时请注意语义：
   - 比 **全月像素 OMEGA** → 用 `omega_sf_fenkuai_OMEGA.tif` vs `smap_raw_omega` 各块（或四块平均）。
   - 比 **末块 SM/VOD/OMEGA** → 用对应 TIF vs `20251227–31` / 日均 27–31。
3. 最可信对齐：**SM 末块**（corr≈0.99）；OMEGA 看 **median\|Δ\|≈0.005** 而非单一相关系数。
4. 若要做「四块完整 SM/VOD 对 Matlab」，需分别导出/物化四个 block mat，而不是当前单一末块 TIF。
