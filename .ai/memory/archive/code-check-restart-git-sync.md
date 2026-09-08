# 全面代码检查 → 重启项目 → Git 提交到 dev → 同步 dev 到 main

## Summary

对当前工作区的未提交前端/文档变更进行全量质量门验证（pre-commit + pytest + vitest + lint + build + check:openapi），修复发现的问题，重启全部 CGDA 服务，提交到远端 `dev` 分支，然后将 `dev` 同步到 `main`（merge + push），最终本地留在 `dev` 分支。

## Current State Analysis

### Git 状态
- **当前分支**: `dev`，已与 `origin/dev` 同步
- **远端**: `git@github.com:li589/WebGIS.git`（SSH，已配置 id_ed25519）
- **未提交变更**: 19 个文件（664 insertions, 190 deletions）
  - 前端风场渲染: `wind-streamline-layer.ts`（+276/-? 行，视口撒种优化）、`wind-particle-canvas.ts`、`wind-particle-webgl-shaders.ts`
  - 前端 UI: `InfoPanel.vue`、`DashboardView.vue`、`MapCanvas.vue`、`LayerSidebar.vue`
  - 前端工具/Store: `canvas-utils.ts`、`map-interaction-module.ts`、`stores/layers/index.ts`、`stores/log.ts`
  - 前端测试: 4 个 `.test.ts` 文件新增测试用例
  - 文档: `README.md`、`天气渲染进度同步-2026-07-21.md`、`规范文档.md`
- **后端重构已提交**: Phase 2 god class 拆分（download_service / python_provider_bridge_service / provider_workflow_service / launch.py → launch/ 包）已在 `b2b0325` 提交
- **dev vs main**: 树内容当前完全相同（`git diff --stat main dev` 为空），但提交历史已分叉（dev 有 `c9f2a9e`，main 有 5 个独立提交含 PR merge）。提交新变更后 dev 将领先 main。

### 服务状态
- Docker 容器: Redis / MinIO / Open-Meteo 均 running
- 后端进程: FastAPI / 7 个 Celery Worker / Beat / Frontend **均已退出**（前一会话的 5 个后台 job 已失效）

### CI 质量门（`.github/workflows/ci.yml`）
1. `pre-commit run --all-files` — ruff(lint+format) / mypy / eslint / prettier / 通用钩子
2. `cd Code/backend && pytest tests/ -x --tb=short -q`（需 `REDIS_URL=redis://localhost:6379/0` + `ENVIRONMENT=test`）
3. `cd Code/frontend && npm run test`（vitest run）
4. `cd Code/frontend && npm run check:openapi`（需 Redis）
- 额外: `npm run lint`（eslint）+ `npm run build`（vue-tsc -b + vite build = "编译"检查）

### 已知约束
- pre-commit 的 ruff/mypy 钩子仅覆盖 `Code/backend/app/` 和 `Code/algorithms/providers/Python/algorithms/`，不覆盖 `launch/` 和根目录脚本
- `launch/` 包已通过手动 `ruff check` + `ruff format` 验证
- 后端测试存在已知的前置失败（`test_interaction_hub.py` 数据路径问题），不阻塞提交
- `.data/` 根目录不被 `.gitignore` 覆盖，需用定向 `git add` 避免 accidentally staging

## Proposed Changes

### Step 1: 全量代码检查

#### 1a. pre-commit（全量）
```powershell
pre-commit run --all-files
```
- 覆盖: ruff(Python lint+format) / mypy / eslint(TS/Vue) / prettier / 通用钩子（尾随空格、EOF、YAML/JSON、merge conflict、private key）
- 若有自动可修复项（ruff --fix、prettier --write），pre-commit 会自动修复并标记为 "Failed"（需 re-stage）
- 若有手动修复项（eslint warnings、mypy errors），逐个修复后重新运行

#### 1b. 前端编译检查（vue-tsc + vite build）
```powershell
cd Code/frontend; npm run build
```
- `vue-tsc -b` 做 TypeScript 类型检查（等价于"编译"）
- `vite build` 做实际产物构建
- 任何类型错误或构建失败必须修复

#### 1c. 前端 lint
```powershell
cd Code/frontend; npm run lint
```
- eslint 检查 `src/` 目录
- 修复所有 error；warnings 酌情修复

#### 1d. 前端测试
```powershell
cd Code/frontend; npm run test
```
- vitest run，执行所有 `.test.ts` 文件
- 新增的 4 个测试文件（wind-particle-canvas.test.ts 等）必须通过

#### 1e. 后端测试
```powershell
cd Code/backend; $env:REDIS_URL="redis://127.0.0.1:6379/0"; $env:ENVIRONMENT="test"; python -m pytest tests/ -x --tb=short -q
```
- Redis 容器已运行（cgda-redis:6379），可直接连接
- `-x` 首个失败即停止；如遇已知前置失败（test_interaction_hub.py 数据路径），记录后跳过该文件继续
- 备选（跳过已知失败）: `pytest tests/ --ignore=tests/test_interaction_hub.py -q`

#### 1f. OpenAPI 契约检查
```powershell
cd Code/frontend; $env:REDIS_URL="redis://127.0.0.1:6379/0"; $env:ENVIRONMENT="test"; npm run check:openapi
```
- 检查前后端 OpenAPI 契约漂移

### Step 2: 修复发现的问题
- 根据 Step 1 的失败输出逐个修复
- 修复后重新运行对应的检查命令确认通过
- 对 `launch/` 包: 已通过 `ruff check` + `ruff format`，无需额外操作

### Step 3: 重启整个项目
```powershell
# 停止全部（清理已退出的僵尸进程 + Docker 容器）
python launch.py stop

# 启动全部（Docker + FastAPI + 7 Workers + Beat + Frontend）
python launch.py start

# 验证
python launch.py status
```
- 预期: Docker 容器 running + FastAPI :8000 就绪 + Frontend :5175 就绪 + 全部 Worker/Beat 运行中
- `python launch.py start` 会进入监控循环，需用后台运行或等待启动完成后 Ctrl+C 退出监控（服务继续运行）

### Step 4: Git 提交到 dev 分支

#### 4a. 暂存变更（定向 add，避免 .data/ 误入）
```powershell
git add Code/frontend/README.md
git add Code/frontend/src/components/InfoPanel.vue
git add Code/frontend/src/components/LayerSidebar.vue
git add Code/frontend/src/components/MapCanvas.vue
git add Code/frontend/src/components/map/canvas-utils.ts
git add Code/frontend/src/components/map/map-canvas-expose-bridge.ts
git add Code/frontend/src/components/map/map-interaction-module.test.ts
git add Code/frontend/src/components/map/map-interaction-module.ts
git add Code/frontend/src/components/map/wind-particle-canvas.test.ts
git add Code/frontend/src/components/map/wind-particle-canvas.ts
git add Code/frontend/src/components/map/wind-particle-webgl-shaders.test.ts
git add Code/frontend/src/components/map/wind-particle-webgl-shaders.ts
git add Code/frontend/src/components/map/wind-streamline-layer.ts
git add Code/frontend/src/components/map/wind-streamline-modes.test.ts
git add Code/frontend/src/stores/layers/index.ts
git add Code/frontend/src/stores/log.ts
git add Code/frontend/src/views/DashboardView.vue
git add "Doc/天气渲染进度同步-2026-07-21.md"
git add "Doc/规范文档.md"
```

#### 4b. 确认暂存内容
```powershell
git status
git diff --cached --stat
```
- 确认只有上述 19 个文件被暂存，无 `.data/` 或其他意外文件

#### 4c. 提交
```powershell
git commit -m "$(cat <<'EOF'
feat(frontend): wind streamline viewport seeding and weather UI enhancements

- Add viewport-based seed bounds for wind streamlines (zoom-out optimization)
- Improve wind particle canvas and WebGL shader rendering
- Enhance DashboardView and InfoPanel with weather display updates
- Add test coverage for wind particle/streamline modes
- Update documentation for weather rendering progress
EOF
)"
```
- 遵循 Conventional Commits（`feat` scope=frontend）

#### 4d. 推送到远端 dev
```powershell
git push origin dev
```

### Step 5: 同步 dev 到 main

#### 5a. 切换到 main
```powershell
git checkout main
```

#### 5b. 合并 dev
```powershell
git merge dev -m "chore: sync dev to main"
```
- dev 和 main 历史已分叉但树内容此前相同，此次合并将带入 dev 的新提交
- 预期无冲突（main 落后于 dev，仅 fast-forward 或生成 merge commit）

#### 5c. 推送到远端 main
```powershell
git push origin main
```

#### 5d. 切回 dev
```powershell
git checkout dev
```

### Step 6: 最终验证
```powershell
# 确认本地在 dev 分支
git branch --show-current

# 确认 dev 与 origin/dev 同步
git status

# 确认 dev 与 main 内容一致
git diff --stat main dev

# 确认服务运行正常
python launch.py status
```

## Assumptions & Decisions

1. **Redis 可用**: Docker 容器 `cgda-redis` 已运行（:6379），后端测试和 check:openapi 可直接连接
2. **已知前置失败不阻塞**: `test_interaction_hub.py` 的数据路径失败是前置问题（memory 记录），遇到时跳过该文件继续其余测试
3. **合并策略**: 使用 `git merge dev`（非 `reset --hard`），保留 main 的提交历史，与之前的 PR merge 模式一致
4. **提交粒度**: 19 个文件统一为一个 commit（均为风场渲染优化 + UI 增强的同一主题）
5. **`.data/` 防护**: 使用定向 `git add`（非 `git add -A`），避免 `.data/workflow_definitions/user/.gitkeep` 等运行时文件误入
6. **`launch.py stop`**: 会停止 Docker 容器 + 所有子进程；`launch.py start` 会重新拉起全部
7. **后台 job 清理**: 前一会话的 5 个后台 job 已失效（进程已退出），`launch.py stop` 会清理 PID 文件

## Verification Steps

| 步骤 | 验证命令 | 预期结果 |
|------|---------|---------|
| pre-commit | `pre-commit run --all-files` | All hooks Passed |
| 前端编译 | `cd Code/frontend && npm run build` | Build successful, no TS errors |
| 前端 lint | `cd Code/frontend && npm run lint` | No errors |
| 前端测试 | `cd Code/frontend && npm run test` | All tests passed |
| 后端测试 | `cd Code/backend && pytest tests/ -q` | All passed（或仅已知前置失败） |
| OpenAPI | `cd Code/frontend && npm run check:openapi` | No drift |
| 服务重启 | `python launch.py status` | 全部 ✓ running |
| Git push | `git log --oneline -1 origin/dev` | 显示新 commit |
| main 同步 | `git diff --stat main dev` | 空（内容一致） |
| 本地分支 | `git branch --show-current` | dev |
