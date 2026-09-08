# W3.4/W3.5/W3.6 收尾 + 图层库清理与在线拉取测试（2026-08-16）

> 触发：用户指令「继续完成 W3.4（前端覆盖率门）以及后续的 W3.5（sync/retry 并发加固，需先出小设计）、W3.6（时间轴自动 seek）。完成后提交并推送。然后进行新计划：确保当前已有的图层可以正常显示，预设的工作流也有对应图层，奇怪命名的和失效的图层从图层库中移除，相关组件也需要同步，在线拉取的功能比如 smap、ndvi、风云数据需要进行测试」。用户休息期间自主执行。
> 方法：staff-engineer-mode（交付就绪视角）+ praxis（plan → TDD 执行 → ship）。
> 依据（实读验证）：`temp.txt`（W3.4 中断现场）、`vite.config.ts`、`run-layers.ts`、`useTimelineSync.ts`、`retry_dispatcher.py`、`reuse_cache.py`、`open_meteo_sync_tasks.py`、`redis_client.py`、`omega_sf_fenkuai.py` L181-200、`catalog_seeds/layer_descriptors.json`、roadmap（`next-steps-roadmap-2026-08-16.md`）、问题清单 B-N2/B-N3。

## 总体结构

- **第一阶段**：W3.4 → W3.5 → W3.6 → 分批提交 → push（用户明确授权）
- **第二阶段**：图层库清理（S1）→ 在线拉取测试（S2）→ 账户记录（S3）→ 提交 push

---

## 第一阶段

### W3.4 前端覆盖率门 22%→30%

**现状**（temp.txt 中断现场 + git 确认）：
- 未提交改动：`Test/frontend/services/auth-api.test.ts`（新增，16 例）、`Test/frontend/services/_http.test.ts`（扩展至 21 例）、`Test/frontend/session-expired.test.ts`（扩展，+53 行）——三文件已全绿
- 基线：全量 LF=27668 / LH=6117（lines 22.11%）；目标 30% 需新增 ~2184 覆盖行
- 阈值现状（`vite.config.ts` L99-103）：lines 22 / statements 21 / branches 16 / functions 19

**执行步骤**：
1. 跑 `npm run test:coverage` 确认已改三文件的实际增益（基线 6117 → X）
2. 按杠杆顺序补测试（每完成 2-3 个文件跑一次该文件测试，最后统一跑覆盖率）：
   | 序 | 新测试文件 | 目标源 | 未覆盖行 |
   |----|-----------|--------|---------|
   | 1 | `Test/frontend/stores/layers/run-layers.test.ts` | `stores/layers/run-layers.ts`（2%） | 451 |
   | 2 | `Test/frontend/views/dashboard/useTimelineSync.test.ts` | `useTimelineSync.ts`（含 W3.6 seek 路径） | 258 |
   | 3 | `Test/frontend/stores/settings.test.ts` | `stores/settings.ts` | 199 |
   | 4 | `Test/frontend/stores/layers/workflow-poller.test.ts` | `workflow-poller.ts` | 181 |
   | 5 | `Test/frontend/stores/layers/online-temporal-orchestrator.test.ts` | `online-temporal-orchestrator.ts` | 168 |
   | 6 | `Test/frontend/composables/workflow-validator.test.ts` | `composables/workflow-validator.ts` | 162 |
   | 7 | `Test/frontend/components/ui/usePanelDragResize.test.ts` | `usePanelDragResize.ts` | 186 |
   | 8 | 视差距追加：draw-store(110)、weather-tile-merge(99)、workflow-timers(67)、log(61)、workflow-definitions(56)、theme(37)、wind-particle-canvas(498，已有测试可扩展) | | |
3. **run-layers 测试设计**（temp.txt 已详研，沿用）：mock deps 注入模式（参考 `workflow-runner.test.ts` 模板），mock `@/services/runtime-api`、`../workflow-output-layers`、`../log`、`./result-adapter`、`./imported-raster`、`./workspace-persist`、`@/utils/workflow-progress-format`、`./catalog-builders`、`@/ui-copy/workflow`、`./materialize-empty`、`@/utils/workflow-expected-outputs`、`./layer-naming`、`@/utils/workflow-timekey-seek`、`@/utils/job-layer-coverage`；覆盖 workflowSummary / emitWorkflowProgressTimeSeek / removeJobLayerById / upsertJobLayer / buildWorkflowPayloadForCatalog / formatProgressiveSyncMessage / applyProgressiveSyncToJob / attachAlgorithmProductOverlays / reconcileOmegaBlockLayers / reorderLayers / createRunLayerGroup / cleanupUnproducedRunLayers / refreshRunGroupDissolvable / updateRunGroupFromJob / dissolveRunGroup / reorderWithinRunGroup / moveRunGroupBlock 等纯逻辑函数
4. 达标后改阈值：`vite.config.ts` L100-103 → lines 30；statements/branches/functions 按实测可达整数值同步提升（保守取实测值减 1 的整数，防贴线）
5. 全量回归：`npm run test`（串行）+ `npm run lint` + `npm run build`

**决策**：若一轮补测后实测不足 30%（如停在 27-28%），继续从第 8 行候选池追加；确有困难则阈值设在 ≥26 的实际整数值，roadmap 标注「分阶段，30% 目标顺延」——不虚设达不到的阈值。

### W3.5 sync/retry 并发加固（先小设计，后 TDD）

**B-N3 — sync 按单域加锁（all-or-nothing）**

小设计（定稿，直接实现）：
- `open_meteo_sync_tasks.py` 新增 `_sync_domains(domains: str) -> list[str]`：归一化（排序+去重+去空白；空 → `["default"]`）
- 锁键从集合键 `sync:{a,b}` 改为**每域** `sync:domain:{d}`
- `acquire_open_meteo_sync_lock(domains, ttl_seconds)`：逐域 `acquire_dedup_lock(f"sync:domain:{d}", ttl)`；**任一失败 → 逆序释放已获取 → 返回 None**；全成功返回聚合 token（JSON 串 `{"domain": token}`）
- `release_open_meteo_sync_lock(domains, token)`：解析 token JSON 逐域 `release_dedup_lock`；Redis 不可用路径：本地 `_sync_local_holders` 由 `set[str]`（集合键）改为存每域键，token 退化为本地持有标记
- `is_open_meteo_sync_locked(domains)`：任一域被持 → True（API 409 快速路径语义不变）
- 调用方签名不变（token 仍为 str）；三入口（API trigger / Beat / launch.py sync）无需改动
- TDD：`Test/backend/test_celery_tasks.py`（或 `test_open_meteo_dual_providers.py`）新增用例（先红后绿）：
  1. `sync:a` 持有时 `sync:a,b` acquire → None（子集重叠互斥）
  2. 无交集 `sync:c` 可获取
  3. 部分获取失败时已获取域全部回滚（可再获取）
  4. 释放后同域可重获；token 配对删除不误删他人
  5. Redis 不可用（本地兜底）路径同验证 1-3

**B-N2 — retry reuse_output_dir 并发独占（claim + 安全降级）**

小设计（定稿，零算法侧改动）：
- 语义依据（`omega_sf_fenkuai.py` L181-194）：每 run 默认独立目录 `{output_root}/{run_id}`；显式 `reuse_output_dir` 仅供失败重试复用块缓存。并发双 retry 同一旧 run → 两个新 run 交错读写同一目录
- `reuse_cache.py` 新增 `claim_retry_reuse_dir(repository, reuse_output_dir: str, ttl_seconds: int = 7200) -> bool`：
  - 键 `retryselock:{sha1(abs dir)}`；Redis `acquire_dedup_lock`；Redis 不可用 → 进程内 `threading.Lock` + dict 兜底
  - **抢占自愈**：锁被持时，解析 value 中记录的 run_id，`repository.get_run(run_id)` 已终态（succeeded/failed/cancelled）→ 释放重建返回 True（防 TTL 卡死后续 retry）；非终态 → False
- `retry_dispatcher.py`（L70-76 改造）：`resolve_reuse_output_dir` 成功后先 `claim_retry_reuse_dir`；claim 失败 → **跳过 `inject_retry_reuse_params`**（新 run 走默认 run_id 隔离目录，等价普通提交，安全降级）+ log warning；claim 成功 → 注入 + `retry_meta["reuse_claimed"]=True`
- TDD：`Test/backend/test_workflow_reuse_cache.py`（新增）：
  1. 并发双 retry 同目录 → 恰一个注入 reuse，另一个降级（不注入、不报错）
  2. 持锁 run 终态后 → 可重新 claim（自愈）
  3. 持锁 run 运行中 → claim False
  4. Redis 不可用路径兜底互斥
- 回归：`test_workflow_routes.py` 既有 retry 用例不退化

### W3.6 时间轴自动 seek

**现状**：实现已落地——emit 侧 `run-layers.ts` L74-103（`emitWorkflowProgressTimeSeek` + 守卫 + token 去重）、工具 `utils/workflow-timekey-seek.ts`（`timelineTargetFromWorkflowTimeKey` + `matchSliceLabelInTimeList`）、消费侧 `useTimelineSync.ts` L298-359（watch hint → `seekTimelineToWorkflowProgressTimeKey`：unifiedTimeLock/isPlaying/layer time lock 守卫、同 runGroup 判定、组内成员 overlay seek）。**缺测试与文档勾选**。

**执行步骤**：
1. W3.4 第 2 项的 `useTimelineSync.test.ts` 中专门覆盖 seek 路径：hint 触发 seek（applyDateHour + granularity + rememberLayerTime）、三守卫各一例（locked/playing/layerTimeLocked）、跨 runGroup 且非选中层不 seek、`matchSliceLabelInTimeList` 精确/前缀/无匹配三态、`setOverlayTime` 对组内成员逐一调用
2. 文档勾选：`Docs/05-专题研究/其它专题/workflow_scheduling_audit_report.md` P-02 行 → **已实施**（注明实现位置）；roadmap（`.trae/documents/next-steps-roadmap-2026-08-16.md`）进度行更新 W3.4/W3.5/W3.6 状态
3. `Test/frontend/utils/workflow-timekey-seek.test.ts` 若不存在则补（62 行小文件，含 range 格式 `YYYYMMDD_YYYYMMDD` 分支）

### 提交与推送（第一阶段收口）

分批 Conventional Commits（dev 分支）：
1. `test(frontend): expand auth, http and session coverage`（含已有三文件改动）
2. `test(frontend): add run-layers, timeline-sync and store coverage`（W3.4 补测 + 阈值提升，若量大可再拆）
3. `fix(backend): per-domain sync locks and retry reuse dir claim`（W3.5 两项 + 新测试）
4. `docs: mark scheduling P-02 implemented and update roadmap`（W3.6 文档）
- 每批提交前 `pre-commit run --all-files`；后端改动跑 `pytest Test/backend/test_celery_tasks.py Test/backend/test_workflow_routes.py`（basetemp C 盘）+ 新增测试文件
- 全部完成后 `git push origin dev`（用户明确授权「完成后提交并推送」）

---

## 第二阶段

### S1 图层库盘点与清理

**盘点**（先出审计清单，落 `.ai/progress/2026-08-16-layer-catalog-cleanup.md`）：
1. BE 全量：`app/catalog_seeds/layer_descriptors.json` 逐条 layer_id / display_name / dataset_key / data 依赖
2. 运行时 readiness：起后端（`Env\Python312\python.exe launch.py start fastapi`）→ `GET /layers` 记录每层 `run_readiness`；**前置：I: 盘须挂载**（当前 `deployment.config.json` data_root=`I:\test`；若 I:\test 数据缺 → 可临时经设置页切 `I:\Geograph_DataSet`，或按现状记录 blocked 清单）
3. FE 对照：`stores/layers/catalog.ts` LAYER_LIBRARY ↔ BE seeds（`npm run check:catalog`）+ `layer-display-names.ts`
4. 工作流种子：`workflow_seeds/system/*.json` 各 seed 的产物图层绑定（presentation/layer 字段）是否指向存在的 catalogId；孤儿绑定（指向不存在层）列清单

**清理规则**（决策标准）：
- **失效层**：data_root 下数据目录不存在 → run_readiness=blocked 且无在线能力替代 → `LAYER_LIBRARY` 中标 `hidden`（不物理删除 descriptor，可逆）；确属废弃（历史调试产物）→ 删除 + 清单留档
- **奇怪命名**：`display_name` 不符 `Docs/03-规范协议/layer-naming.md`（临时名/英文占位/调试后缀）→ 按规范重命名，同步 `layer-display-names.ts`
- **组件同步**：改 seeds 后跑 `Tools/generate_catalog_seeds.py`（或 `npm run gen:catalog`）重生成 `catalog-seeds.generated.json` → `npm run check:catalog` 必须零漂移
- 保守原则：每处移除/改名前记入审计清单（layer_id、原因、动作）；不确定项倾向 hidden 而非删除

**验证**：`npm run check:catalog` + `npm run test -- layer-naming layer-display-names catalog`（相关域）+ `GET /layers` 复核 + `pytest Test/backend/test_layer_catalog.py`（若存在，按实际文件名）

### S2 在线拉取测试（smap / ndvi / 风云）

**前置**：后端起栈 + 网络可达 + 凭据入库。

**执行**：
1. **凭据配置**：经设置页（admin）或 API 写入 portal_credentials（加密存储）：
   - earthdata：`Rejoyce` / `********`（用户标注「好像是」——配置后实测验证，失败则报告并留待用户确认）
   - 风云三账户（单账号限额，轮换）：`2643632060@qq.com`/`********`、`415114178@qq.com`/`********`、`fengrui`/`********`
2. **NDVI**：`GET /layers/ndvi/online-temporal`（capability 已配 2000-01~2025-06 月步）→ 前端 timeline fetchable 段 + 实际切片拉取（在线时序编排 3 并发/500ms 错峰）
3. **SMAP**：核对 descriptor 在线能力 / NSIDC portal credential 路径，小范围时间窗实测下载-读取链
4. **风云**：`fy_download.py` 模块 + `workflow_seeds/system/fy_tb_online_read.json` 种子 → 提交小日期范围在线读取 run → 验证产物落盘与图层物化
5. 每项记录：成功证据（run_id / 产物路径 / 瓦片或图层 ID）或阻断原因（网络/凭据/限额）
6. 产出报告：`.ai/progress/2026-08-16-online-fetch-verification.md`

**决策**：网络不可达或凭据失败 → 记录阻断原因并跳过实测，不阻塞其余项；不因测试目的长时间占用下载带宽（小样本窗口）。

### S3 账户信息记录

写入 `c:\Users\likr\.trae-cn\memory\projects\-d-temp-desktop-Proj-Comprehensive-Geographic-Data-Analysis-system--p2-f02d651790412ef19de2\project_memory.md`（本地文件，不上传 GitHub）：
- earthdata portal：Rejoyce / ********（待实测验证）
- 风云三账户（单账号限额轮换）：2643632060@qq.com / ********；415114178@qq.com / ********；fengrui / ********
- 注明用途与来源（用户 2026-08-16 提供）

### 第二阶段提交与推送

- S1 清理：`chore(catalog): hide stale layers and normalize display names`（或 refactor）
- S2 若有配置/文档改动：`docs(progress)` 或相应类型
- 完成后 `git push origin dev`（与用户「提交并推送」整体意图一致）；最终输出总报告（两阶段结果 + 阻断项清单）

---

## 验证命令速查

```powershell
# 环境前置（沙箱）
$env:PATH = 'C:\FreeRulesPrograms\BasicToolkits\Git\cmd;C:\Windows\System32;C:\Windows;' + $env:PATH
$env:ENVIRONMENT='test'; $env:REDIS_URL='redis://127.0.0.1:6379/0'

# 后端/算法（basetemp 必须 C 盘）
Env\Python312\python.exe -m pytest Test/backend/test_celery_tasks.py Test/backend/test_workflow_routes.py -p no:cacheprovider --basetemp="$env:TEMP\cgda-w35" -q

# 前端与契约门
cd Code/frontend
npm run test            # 串行全量
npm run test:coverage   # 覆盖率门
npm run lint; npm run build
npm run check:catalog; npm run check:openapi

# 提交前
pre-commit run --all-files
```

## 假设与决策

1. **I: 盘挂载**是 S1 readiness 核对与 S2 数据链实测的前置；未挂载则 S1 降级为静态种子审计、S2 记录阻断，其余照常。
2. W3.4 阈值不虚设：达不到 30 则设实测可达整数（≥26）并标注分阶段。
3. B-N2 采用 claim+降级方案（零算法侧改动），不做代次子目录（会破坏块缓存复用语义，算法侧需改接口，影响面大）。
4. B-N3 锁 API 签名不变，三入口零改动；聚合 token 对调用方不透明。
5. 图层清理以 hidden 优先、删除需审计清单留档（可逆性优先）。
6. 凭据仅写入系统加密凭据库与本地 project_memory，不入 .env / 不入 git。
7. 两阶段各自收口时 push；用户休息期间不追问，最终一次性汇报（结果 + 阻断 + 遗留）。
