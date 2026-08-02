# FY/SMAP 全流程验证进度追踪

## 目标状态

| 检查项 | 当前状态 | 完成标准 | 证据 |
|--------|---------|---------|------|
| 服务启动 | 通过 | FastAPI + Worker 正常 | `launch.py status` 2026-08-02 |
| 路径别名 / seed | 通过 | FY3D/SMAP_Auxiliary 可解析 | `PATH_ALIASES` + seeds |
| VI_v_qa / Nov 拉取 | 通过 | 辅助库 + 202511*.mat | manifest 60 ok |
| preload 赋值修复 | 通过 | `_fill_chunk_row` | unit + DIAG |
| FY Q4 扩样 | 通过 | 139/210 像元，8 块 | `run-35770cbbed20` |
| FY vs Matlab Dec | 通过 | MAE ≈ 0.046–0.058 | `omega_sf_fenkuai_fy_q4_run35770` |
| SMAP Q4 扩样 | 通过 | 53/210 像元，7 refs | `run-5d31768eb95e` **succeeded** |
| SMAP vs Matlab Dec | 通过 | 重叠像元 MAE ≈ 0.006–0.05 | 同 run 产物 |
| 精细进度事件 | 通过 | detail 落库 | chunk/pixel/phase |
| event UNIQUE 收尾 | 通过 | 不再把成功算法标 failed | finalize 不再重写 mid-run events |
| bbox 列表参数 | 通过 | `bbox:[w,s,e,n]` → west/south/east/north | `OmegaSfConfig.from_params` |
| UI | 部分 | 工作流范例可见；条带上图待更大样本 | 前端 :5175 |

## 关键修复（本轮）

1. preload `_fill_chunk_row`（此前致命全 NaN）。
2. mid-run `event_factory` 即时落库 + `INSERT OR IGNORE`；finalize **不再**重插 `execution.events`。
3. `bbox` 列表展开；bbox 时忽略 `OMEGA_SF_MAX_CHUNKS` / `CHUNK_OFFSET`。
4. 清理用户级残留 `OMEGA_SF_*` 环境变量；全量 stop/start 清掉旧 Celery 进程。

## 对照摘要

| 源 | run | 成功像元 | Dec MAE（重叠） |
|----|-----|----------|----------------|
| FY | run-35770cbbed20 | 139/210 | 0.046–0.058（n=90–125） |
| SMAP | run-5d31768eb95e | 53/210 | 0.006–0.053（n≈3/块，样本区重叠少） |

产物备份：`…/omega_sf_fenkuai_fy_q4_run35770`、`…/omega_sf_fenkuai_smap_q4_30pix`。
