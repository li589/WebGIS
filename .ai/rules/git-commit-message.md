# Git 提交信息规范（CGDA）

> 单一真源：提交信息规范与提交操作硬约定。各工具规则文件指向本文件。

## 提交操作硬约定（本机 Windows 环境，2026-08-16 事故教训）

**查找git：先查找虚拟沙箱（如果存在）下的git，如果找不到请在系统默认目录安装目录和环境变量中查找，即在系统盘和软件盘的"Program Files"中查找，对于我个人的开发环境相关组件（gh、git、c编译器等）放置于"C:\FreeRulesPrograms\BasicToolkits"目录下。**

**提交前必须先 `git add -A` 全量暂存，使工作区无任何未暂存改动，再执行 `git commit -m <msg>`。**

- **禁止**部分暂存后提交、**禁止** pathspec 形式提交（`git commit -- <paths>`）。
- 原因：pre-commit 的 `staged_files_only` 机制在存在未暂存改动时会先 stash（写入 `~/.cache/pre-commit/patch<时间戳>`）再 `git checkout -- .`；本机 Windows 文件锁（`unable to unlink ... Invalid argument`）会导致 checkout / 恢复 patch 失败，未暂存改动被**回滚甚至文件被删**（2026-08-16 两次触发，均从 patch 缓存找回）。
- 分批提交的正确姿势：一次 `git add -A` 后做**单个综合提交**；确需拆分时，用文件系统层面把无关文件移出仓库再逐批提交，勿依赖 git 暂存区分批。
- 若 hook 自动修复文件导致提交中止（`files were modified by this hook`），重新 `git add -A` 后再次提交即可。

### 事故恢复方法（改动被 stash 吞掉时）

1. 丢失的改动保存于 `C:\Users\likr\.cache\pre-commit\patch<时间戳>-<pid>`（git diff 格式，取最新者）。
2. `git apply --exclude=<仍存在的冲突文件> <patch>` 恢复（如 `.gitignore` 未丢失时会冲突，需排除）。
3. `MD` 状态（暂存区有、工作区文件被删）用 `git checkout -- <files>` 从暂存区恢复。
4. 恢复后必须抽查关键符号并跑相关 pytest，确认无静默丢失。

提交信息遵循 **Conventional Commits**，格式：

```
<type>(<scope>): <subject>

<body（可选，说明为什么而非做了什么）>
```

## 允许的 type

`feat` / `fix` / `refactor` / `perf` / `chore` / `docs` / `test` / `style` / `build` / `ci`

## scope 建议（按改动域）

- `backend`：FastAPI / Celery / 服务层
- `frontend`：Vue 组件 / store / 服务
- `algo`：算法包（omega / ndvi / smap / fy 等）
- `weather`：天气引擎 / 瓦片
- `gee`：GEE 模块
- `config`：配置 / 契约 / 启动器
- `docs`：文档

## 约束

- subject 用祈使句、小写开头、不加句号，如 `fix(backend): guard preload against all-NaN chunk`。
- 中文提交信息允许，但 **Celery 任务元数据（artifact/workflow title）必须纯英文**，不要用中文。
- 关联问题可加 `Refs #123` 或 `Closes #123`。
- 提交前务必通过 `pre-commit run --all-files`（ruff + mypy + eslint + prettier + OpenAPI 契约检查）。

## 示例

```
feat(weather): add WebGL scalar LUT with bilinear cross-fade

- 连续色场优先 WebGL 双线性；失败回退 MapLibre grid_fill
- 时次 400ms 交叉淡入

Refs #456
```
