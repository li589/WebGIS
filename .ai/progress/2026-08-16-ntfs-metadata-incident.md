# 「17 文件元数据不一致」事件全案复盘（2026-08-16，最终版）

## 状态：**已结案（2026-08-16 VMCache 清除后全链路验证通过，AI 会话硬约束作废）**

## 结案验证记录（2026-08-16，VMCache 删除 + TRAE 重启后新会话）

用户执行：托盘退出 TRAE（含 2 个 `agent-tool-host.exe`）→ 删除
`VMCache\main-TRAE_SOLO-Yinli\drive\D\temp_desktop` → 重启 TRAE 新会话。AI 侧验证：

- `consumers.py`：Length=**3442**、mtime=**2026-08-16 02:46:39**（冻结值 3462/07-31 已消失）。
- `git status --porcelain` 空、exit 0；`skip-worktree` 计数 **0**（用户终端已全部解除）。
- 17/17 文件：`git hash-object` 全流读取成功且 sha == `git rev-parse HEAD:<path>`。
- `git update-index --really-refresh -- <17 文件>` exit 0；`git add -- <17 文件>` **exit 0，无 short read**（原故障点复测通过）。
- 14 个 Python 文件 `py_compile` exit 0。
- `pytest test_omega_avg_algorithm / test_omega_avg_daily_module / test_layer_workflow_validation`：**18 passed，exit 0**。
- HEAD = `87e24ba`（与提交记录一致，无代码回退）。

结论：仓库与 AI 会话视图一致，代码与功能无破坏、无回退。VMCache 陈旧镜像根因闭环。

## 新会话沙箱残留注意（与 VMCache 无关，环境固有）

1. PATH 缺 System32 与 git：git 需前置
   `$env:PATH = 'C:\FreeRulesPrograms\BasicToolkits\Git\cmd;C:\Windows\System32;C:\Windows;' + $env:PATH`。
2. 沙箱删除白名单仅 `C:\Users\likr`：D 盘路径 `Remove-Item` / pytest basetemp 清理会被拒
   （`path not in allowlist`）。跑 pytest 用 `--basetemp="$env:TEMP\..."`（C 盘），
   勿用 `Test\.pytest-be`（AGENTS.md 该建议仅针对 WorkBuddy shim 场景）。
3. 沙箱内无法清理的残留目录（均 gitignored，可由用户终端随手删除）：
   `Test\.pytest-be\`、`Code\backend\.pytest_tmp\`。

## 完整因果链（证据充分）

1. **2026-08-14 20:45**：TRAE SOLO CN 更新 ai-agent 模块（`meta.json` 版本
   `1.0.0-alpha.0`，`D:\Program Files\TRAE\TRAE SOLO CN\resources\app\modules\ai-agent\`）。
2. 该模块维护**整盘镜像缓存**
   `C:\Users\likr\AppData\Roaming\TRAE SOLO CN\VMCache\main-TRAE_SOLO-Yinli\drive\{C,D,I}\`
   （项目子树镜像 247,227 文件 / 34.71 GB）。toolhost（`agent-tool-host.exe`）启动的
   子进程被注入 `aiep_vm.dll` + `aiep_ipc.dll`，**文件 stat 元数据从该缓存回放**，
   内容读写穿透到真实磁盘（混合视图）。
3. **2026-08-15**：真实 D 盘 17 个文件发生 NTFS 目录项/数据流不一致（stat 3462 vs
   流 3442 等）——这是**真实的磁盘损坏**，被 VMCache 原样捕获（副本自身也是
   stat=3462/stream=3442/mtime=07-31 05:15:22，与 AI 视图逐字节一致）。
4. git add 在注入视图中 lstat(3462) > read(3442) → `short read while indexing`
   崩溃。当日用 `git hash-object -w` + `update-index --cacheinfo` 完成提交并
   skip-worktree 保护。
5. **2026-08-16**：用户 chkdsk 修复真实磁盘（0 问题）+ 挂载 I 盘；用户终端
   （无注入）视图 17/17 健康；`checkout-index` 重写 + 解除全部标记 + git 干净。
6. 但 chkdsk 类修复**绕过常规文件变更通知**，VMCache 对这 17 个路径永不失效：
   AI 侧 stat 冻结在 8-15 损坏值，内容读取却已是新磁盘内容。缓存跨 app 重启
   （toolhost 02:29 全新进程仍回放旧值）→ 磁盘持久化。

## 决定性实验（复现与反证）

- **改名探针**：`consumers.py` → `consumers.py.probe` 立即变新鲜（3442/08-16），
  改回原名立刻回到冻结值（3462/07-31）→ 路径键控缓存，非磁盘行为。
- **写穿透/元数据触碰**：WriteAllBytes 回写、SetLastWriteTime 均不使缓存失效。
- **无 junction/subst**；`TOOLHOST_SANDBOX_DISABLED=true` 仅关写重定向，stat 层仍在。
- 进程模块表直接可见 `aiep_vm.dll`/`aiep_ipc.dll` 注入。

## 深度解决（用户执行，2026-08-16 待办）

1. 完全退出 TRAE SOLO CN（含托盘与 2 个 `agent-tool-host.exe`）。
2. 删除陈旧镜像（外科化，仅项目子树）：
   `Remove-Item -LiteralPath "C:\Users\likr\AppData\Roaming\TRAE SOLO CN\VMCache\main-TRAE_SOLO-Yinli\drive\D\temp_desktop" -Recurse -Force`
   （更彻底可删整个 `VMCache` 文件夹——纯缓存，按需重建，可释放数十 GB。）
3. 重启 TRAE → 新会话验证：
   `(Get-Item 'Code\algorithms/providers/Python/data_access/consumers.py').Length`
   应为 3442、mtime 08-16；`git status` 干净；`git add` 无 short read。
4. 验证通过后，本文件「对后续 AI 会话的硬约束」一节自动作废。

## 对后续 AI 会话的硬约束（**已作废**：2026-08-16 VMCache 清除后验证通过，见顶部结案记录；保留原文仅作历史参考）

1. 以下 17 路径在 AI 侧 stat 冻结：git status 显示假阳性 " M"，**不是真实修改**；
   `git add` 这 5 个 stat>流 的文件会触发 short read 使整条 add 失败——
   用 pathspec 排除法分批暂存，或请用户在自己终端执行 git 操作：
   - Code/algorithms/providers/Python/{algorithms/omega_sf.py,
     data_access/{spatial_aligner,consumers}.py, ingest/{daily_bundle,mat_bundle}.py,
     modules/{export,omega_sf_fenkuai}.py, publish/raster_writer.py,
     workflow/executor.py}
   - Code/backend/app/{api/routers/layer_router.py, core/celery_app.py,
     services/{layer_catalog,overlay_registry,python_provider_result_builder}.py}
   - Code/frontend/src/{data-manager/ui/DataImportMenu.vue,
     stores/layers/{result-adapter.ts,types.ts}}
2. 校验这些文件内容用「open+read 全流 sha vs `git rev-parse HEAD:<path>`」。
3. 建议向 TRAE 反馈：ai-agent 1.0.0-alpha.0 的 VMCache 对外部磁盘修复（chkdsk）
   不失效，且 stat 与内容来源不一致。

## 历史遗留

- stash@{0}：`WIP on dev: 2d71f3f`（2026-08-12，19 文件 WIP，与本次无关）。
- I: 盘已挂载，`deployment.config.json` data_root fail-closed 问题已解除。
- `%TEMP%\cgda-corruption-backup-20260816\` 沙箱视角备份，可删。
