# FY/SMAP UI 人工闭环（2026-08-04）

## 结论

**UI 主链已闭环**：全栈重启 → 图层/时间轴 → `omega_sf_fenkuai` 提交成功 → materialize SM/VOD/OMEGA → 时间切换 → 图层面板独立显示。

证据 run：`run-d1f167fbaec4`（succeeded，`max_pixels=30` + bbox 南非样区）。

## 本轮修复（保证图层面板可跑）

1. `layer_descriptors.json` / `omega-sf-fenkuai`：
   - `default_data_access_sources` 改为**输入**（`smap_folder` / `anc_root` / `ndvi_clim_folder`），不再把产出 `OMEGA_SF_FENKUAI` 当必选输入（此前会 422 或假阻塞）。
   - 补 `workflow_name` / `workflow_id` = `omega_sf_fenkuai_smap_single`，以便注入种子 `time_range` / `algorithm_params`。
2. 创建 `I:\Geograph_DataSet\Model_Outputs\Omega_SF_Fenkuai`（历史就绪检查用；现已改为输入就绪）。
3. FastAPI 重启后 `_resolve_provider_dataset_path` 负缓存失效。

## UI 验证勾选

| 项 | 结果 |
|----|------|
| 服务启动 | 通过（`launch.py status` 全绿） |
| 图层管理 / 刷新 | 通过（workspace-persist 恢复已添加层属预期） |
| 时间轴无层时 0–23h | 通过 |
| 工作流运行 | 通过（`run-d1f167fbaec4`） |
| 块产物 | runtime `omega_sf_fenkuai` 下 `????????_????????.mat` ≈47（含既有 Q4 拷贝） |
| UI 显示 SM/VOD/OMEGA | 通过（4 个本地导入层，可独立显隐） |
| 时间切换 | 通过（2025-12-27 → 12-28） |
| 导出 | **部分**：分析面板有「导出 PNG / GeoTIFF」；自动化点击偶发被 map canvas 拦截（层级） |

## 残留

- 条带视觉：本轮 smoke 像元极少；更大 bbox/样本上图仍可做一次人工目视加强。
- 图层面板默认提交若不显式传 `algorithm_params.max_pixels` / `bbox`，种子全局域会跑全图（已在闭环中用显式参数约束）。
- 导出按钮 z-index / 点击命中待跟进。
