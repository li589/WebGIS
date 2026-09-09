# CGDA 项目长期记忆

## 仓库与分支
- 远端：`https://github.com/li589/WebGIS`（owner `li589`，默认分支 `main`，工作分支 `dev`）
- 本地工作分支 `dev`，跟踪 `origin/dev`
- 历史基线：`aa7dbf1`（data_io 属主 C-1 修复）、`d5148e9`（deck.gl 评估结论文档）

## 环境硬约定
- 沙箱内执行 git 需前置：`env -u ACC_PRODUCT_CONFIG_V3 CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= git ...`（否则报 not a git repository）
- Python 唯一解释器：`Env/Python312/python.exe`
- 全局 `core.autocrlf=true` → 工作区 CRLF、仓库 LF；判断"是否真改动"用 `git diff --quiet`，不要只信 `git status` 的 ` M`
- 测试：`Env/Python312/python.exe -m pytest Test/backend`；前端 `cd Code/frontend && npm run test`

## 产物目录（均已被 .gitignore 覆盖，不会污染 status）
`Code/backend/imports_output/`、`Code/frontend/coverage/`、`Test/pytest-run-tmp{,2}/`、
`Test/reports/`、`temp/`、`tmp.txt`、`.codegraph/`、`.pytest_tmp*/`

## 已完成的重大改动
- **C-1 导入任务属主丢失**（`aa7dbf1`）：`require_data_transfer_access` 是同步依赖，其
  ContextVar 不回传 async 端点 → `owner_user_id` 恒 None → 非管理员查不到自己的任务(403)。
  改为端点显式传参（`_owner_user_id(cred)`，5 端点 7 处 `enqueue_job`）；回归锁
  `Test/backend/test_import_job_ownership.py`。
- **deck.gl 结论**（`d5148e9`）：依赖未装、源码零引用，技术栈.md 已标「已评估·暂不引入」；
  GPU 渲染由自研 WebGL 图层承担（风场/标量场/3D 昼夜）。触发条件：真实百万级点渲染场景。

## 坑
- `Test/backend/test_agent_chat.py` 与大批量测试同跑会 4 failed（既有顺序污染），单独跑 12 passed
- pytest 用 `-p no:logging` 会抹掉 `caplog` fixture，制造假 error
- 后台线程执行的 handler，`with patch()` 退出后桩已失效 → 模块级夹具打桩
- Celery `send_task` 连 Redis 失败会重试 20 次（~60s/用例）；测试里 patch `celery_available=False`
- Vue 3.5.38 + Pinia 3.0.4：`storeToRefs` 对 undefined 属性有 bug，统一用 `toRef(store, key)`

## 目录职责（用户约定，2026-09-10）
- `.ai/` 是 AI 文档的唯一归宿（rules / skills / plans / progress / memory / docs）；本文件即为长期记忆。
- `Docs/` 存放供人阅读的公开文档。
- 不再保留工具私有目录 `.workbuddy/`；`.cursor/`、`.trae/`、`.kiro/`、`.cursorignore`、
  `.github/copilot-instructions.md` 也已从版本库移除（原本就已在 .gitignore 中）。
- 例外保留：`.github/workflows/ci.yml`（CI 配置，非 AI 文档）、根级 `AGENTS.md` / `CLAUDE.md` / `README.md`。

## 事故记录
- 2026-09-10：本地 `.git` 被误删，经"浅克隆 → 移植 .git → add+reset 重建索引 → 恢复 10 个
  误删受控文件"恢复，工作区与远端 dev 内容零差异。详见 `memory/2026-09-10-git-restore-and-sync.md`。
