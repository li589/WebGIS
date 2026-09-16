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

## 部署决策（2026-09-16）
- **目标形态 = 全量容器化**：后端（FastAPI/Worker/Beat）+ 网关进容器；Redis/MinIO/Open-Meteo 沿用官方镜像。
- 目标 OS：**Linux（CentOS/RHEL 系、Debian/Ubuntu 系）+ Windows 10+**；数据盘为**本地盘**；目标机**可联网**。
-   方案稿（含 Dockerfile 草案、compose 生产编排、bind mount/UID、容器化 SOP、TBD 8 项）：
  `Docs/04-执行部署/部署手册与硬约束清单.md`（v0.3：§12 容器化实施方案 + **§12.9 改码工作流**，
  原 TBD 顺延 §12.10）。裸机 `launch.py` 路径降级为开发/回退。

## 容器化相关代码事实（已核实，写 Dockerfile 前必读）
- **镜像内必须保持 `Code/` 兄弟目录结构**：`start_fastapi.py:18-24` / `start_celery_worker.py:6-13` 把
  `backend_root.parent`（即 `Code/`）插入 `sys.path`；`config.py:42-44` 的 provider 根 =
  `BACKEND_ROOT.parent/"algorithms"/"providers"/"Python"`。
- `BACKEND_HOST` 代码默认 **`127.0.0.1`**（`config.py:249`）→ 容器内必须显式设 `0.0.0.0`。
- Redis/MinIO 键名：`BACKEND_REDIS_URL`（默认 `redis://127.0.0.1:16379/0`）、`BACKEND_MINIO_ENDPOINT`
  （容器内用 `minio:9000`，非宿主 9100）。
- **本地 Open-Meteo 源**：取数 URL 由 `BACKEND_OPEN_METEO_LOCAL_URL` 驱动
  （`provider_registry.py:277-283`，可被天气 Provider 的 DB `base_url` 覆盖）；但
  `provider_ids.py:17` 仍硬编码 `http://127.0.0.1:8080/v1/forecast`，被
  `weather_engine_settings.py:145`、`weather_router.py:82` 的**探活**使用 → 容器内会**误报"本地源不可用"**
  而取数正常。彻底修法：把该常量改为 env 驱动。
- `BACKEND_RELOAD` 代码默认 `true`（`config.py:251`），但 `start_fastapi.py:32-40` **已有 production 守卫**
  （标记 A-4）：非 development 强制关热重载。⇒ 交付演练记录 2026-08-16 §二 #12 的结论已过时。
- **改码工作流（手册 §12.9）**：交付态源码 `COPY` 进镜像 → 改码必须 `docker build` + 滚动升级（可回滚/可审计）；
  开发态用 bind mount（宿主 `Code/` → 容器 `/srv/Code`）+ `--reload` / Vite HMR，改完即生效。
  ⬛ **因上述守卫，容器内开 `--reload` 需 `BACKEND_ENV=development`，与硬约束 B1（生产非 development）冲突
  ⇒ 开发态与交付态必须两套 compose，不能一套通吃**。另两点：Celery worker 不热载（改 worker 代码须重启 worker）；
  Open-Meteo named volume 禁 bind mount（A5），勿与数据盘 bind mount 混淆。

## 坑
- **GBK 文件不能用 Edit/Write 工具改**（会用 UTF-8 覆盖，中文全乱）：`start.bat` 是 GBK+CRLF。
  正解：沙箱 python 读 bytes → `decode('gbk')` → 替换 → `encode('gbk')` 写回（本机 shell 子进程写此文件未被拦）。
  其余 `.md` 均为 UTF-8/LF，可正常用 Edit。判断编码：`b.decode('utf-8')` 失败且 `gbk` 成功即 GBK。

- `Test/backend/test_agent_chat.py` 与大批量测试同跑会 4 failed（既有顺序污染），单独跑 12 passed
- pytest 用 `-p no:logging` 会抹掉 `caplog` fixture，制造假 error
- 后台线程执行的 handler，`with patch()` 退出后桩已失效 → 模块级夹具打桩
- Celery `send_task` 连 Redis 失败会重试 20 次（~60s/用例）；测试里 patch `celery_available=False`
- Vue 3.5.38 + Pinia 3.0.4：`storeToRefs` 对 undefined 属性有 bug，统一用 `toRef(store, key)`

## 目录职责（用户约定，2026-09-10）
- `.ai/` 是 AI 文档的唯一归宿（rules / skills / plans / progress / memory / docs）；本文件即为长期记忆。
  **历史计划归档区**：`memory/archive/trae-documents-20260819/`（Trae）、
  `memory/archive/workbuddy-plans-20260916/`（WorkBuddy，13 份，见其 `INDEX.md` 的代号→主题映射与排除清单）。
  归档约定：另一 AI 工具的计划按「工具名-日期」建子目录整体迁入，附 `INDEX.md`，保留原始文件名不改名。
- `Docs/` 存放供人阅读的公开文档。
- 不再保留工具私有目录 `.workbuddy/`；`.cursor/`、`.trae/`、`.kiro/`、`.cursorignore`、
  `.github/copilot-instructions.md` 也已从版本库移除（原本就已在 .gitignore 中）。
- 例外保留：`.github/workflows/ci.yml`（CI 配置，非 AI 文档）、根级 `AGENTS.md` / `CLAUDE.md` / `README.md`。

## 事故记录
- 2026-09-10：本地 `.git` 被误删，经"浅克隆 → 移植 .git → add+reset 重建索引 → 恢复 10 个
  误删受控文件"恢复，工作区与远端 dev 内容零差异。详见 `memory/2026-09-10-git-restore-and-sync.md`。
