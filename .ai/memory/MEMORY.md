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

## 启动器与三态（2026-09-16 逐文件核实 + 当日落地）

- **`launch/` 分层**：`start.bat` → `launch.py`(87行) → `launch/cli.py`(argparse+分发表) →
  `launch/commands.py`(57KB) → `process_manager.py` / `docker_manager.py` / `gateway_manager.py` /
  `subprocess_utils.py` / `constants.py`。
- **CLI 11 子命令**：start / stop / status / reload / restart / logs / flush / clean-cache / reset-db /
  sync / **deploy**。**组件 9 种**：all、docker、fastapi、beat、worker、worker:\<name\>、frontend、
  gateway、backend。
- **四个 compose project**：`backend`（Redis/MinIO/Open-Meteo，硬编码于 `docker_manager.py`）、
  `gateway`（Nginx 裸机态，硬编码于 `gateway_manager.py`）、`data-sync`（可经 env 覆盖）、
  **`cgda`（交付态应用层，`compose.prod.yml` + `docker-compose.yml` 合并）**。
- ✅ **三态已全部可用**（2026-09-16 落地）：
  - 裸机态（默认 `--mode bare`）`start`：宿主 FastAPI/9 Worker/Beat + 容器基础设施 + 容器 Gateway 静态 dist
  - 开发态 `start --mode dev`（= `--vite`）：Gateway :5175 + 宿主 Vite HMR :5174
  - **交付态 `start --mode prod` / `deploy up`**：全量容器化，`cgda-backend`(一镜像三角色 fastapi/worker/beat)
    + `cgda-web`(静态 dist + 反代)。`--mode` **只在全量分支生效**；单组件命令语义不变。
- **`deploy` 子命令 7 动作**：`config`（干跑校验）/ `build` / `up`（`--no-build`）/ `restart` /
  `ps` / `logs [svc] -n N` / `down`（`--volumes` 危险）。只读动作（ps/logs/down/config）用
  `readonly_prod_env()` 补占位值绕过 compose 的 fail-closed 插值。
- **交付态必配**（写 `Code/backend/.env`）：`CGDA_TAG`（git sha）、`CGDA_DATA_ROOT`（Windows 用 `D:/geo`）；
  另 `CGDA_IMAGE_PREFIX` / `CGDA_BACKEND_HOST_PORT` / `CGDA_GATEWAY_PORT` / `CGDA_DEPLOYMENT_CONFIG` /
  `CGDA_{REDIS,MINIO,STATE}_VOLUME`。**卷名默认值刻意对齐裸机态**（`backend_redis-data` /
  `backend_minio-data`），防换 project 名后数据"看起来丢了"。
- **Docker 自定义现状**：卷名/Open-Meteo 镜像与端口/MinIO 凭据/数据面 project 已 env 化；
  **Redis/MinIO 端口(16379/9100/9101)、裸机两个 compose project 名、容器名、网关 5175 仍硬编码在代码里**。
  **镜像存储位置不归 launcher 管**——Docker 引擎 data-root（Windows 用 Docker Desktop 设置，
  本机为 `I:\Docker\DockerDesktop`；Linux 用 `daemon.json` 的 `data-root`）。
- **`Env/Python312` = 官方安装包全量布局**（非 venv，无 `pyvenv.cfg`；`sys.prefix` 指向该目录；
  `Lib/site-packages` 595 项；`Scripts/pip.exe` 可用）→ 重建须装 **Python 3.12.9**；
  依赖 pin 在 `Code/backend/requirements.txt`（+ `-dev.txt`、`Code/algorithms/providers/Python/requirements.txt`）。
  ⚠️ `.gitignore:2 Env/` 生效，但 `Env/backend/` 下 **8 个 .ps1 是入库的**（历史联调辅助脚本）——
  不代表 `Env/` 可从 git 复现。

## 交付态容器的三个必踩坑（2026-09-16 实读代码确认，非理论风险）

1. **Beat 的 Open-Meteo 自动同步在容器内必失败**：`open_meteo_sync_executor.py` 用 subprocess 调
   `docker compose`，容器内无 CLI/socket，而 `BACKEND_OPEN_METEO_SYNC_ENABLED` **代码默认 true**
   ⇒ 每 6h 报错。已在 `compose.prod.yml` 设 `false`；同步改在**宿主** `launch.py sync`。
2. **9 个容器抢同一个日志文件**：`app/core/logging.py` 用 `CGDA_LOG_FILE_ROLE` 分文件名，且
   `BACKEND_LOG_DIR` 派生自数据根 ⇒ 交付态 9 容器共用同一 bind mount。已逐服务显式赋值
   （`fastapi` / `worker-<name>` / `beat`）。**新增 compose 服务时勿漏**。
3. **只读 compose 命令被 fail-closed 插值挡住**：`${CGDA_TAG:?}` 在**解析期**生效，
   连 `ps`/`logs`/`down` 都会报错。launcher 侧用 `readonly_prod_env()` 只给只读动作补占位值；
   `compose.prod.yml` 本身**不放宽**。

另两条结构性陷阱：
- **YAML `<<` 不深合并**：`compose.prod.yml` 服务级一旦出现 `environment:` 就**整体替换**锚点 ⇒
  9 个服务都重复写 `<<: *backend-env`。新增服务漏写 ⇒ 只剩一个环境变量，表现为连不上 Redis/MinIO。
- **`deployment.config.json` 挂载陷阱**：宿主文件不存在时 Docker 会建**同名目录**挂进去；
  `deployment_config.py` 的 `is_file()` 为假 → 回退 `.env`（**不拒启**），但配置中心 PUT 写不进。

## 交接缺口状态（2026-09-16）

- **G-F ✅ 已修**：`.gitignore` 已加 `Code/backend/source_uri_map.json`（`.example.json` 仍入库）。
- **G-A…G-E ✅ 已修**：4 个容器化文件 + launcher 三态分派（详见上节）。
- **G-G ⚠️ 未变**：`deployment.config.json` 真源仍不存在（仅 `.bak.1` 内容 `data_root: I:\test` +
  `.example`），本机跑 `.env` 单轨。目标机须明确单轨或补建（补建须格式合法，否则 fail-closed 拒启）。
- **G-H ✅ 非阻塞**：`Code/frontend/public/data/boundaries` 源 SHP/解包目录未入库，但**构建只需
  GeoJSON**（26MB，已入库）；`.dockerignore` 已把 `ne_*.zip` / `admin_0` / `admin_1` 排除出上下文。
- **G-I / G-J ✅ 已修**：见上节坑 1 / 坑 2。
- **G-K ⚠️ 未修，已文档化**：两处 Open-Meteo 探活仍写死 `provider_ids.OPEN_METEO_LOCAL_URL`
  （`weather_engine_settings.py`、`weather_router.py`）；**取数路径可经 `BACKEND_OPEN_METEO_LOCAL_URL` 覆盖**，
  但探活在容器内会**误报"本地源不可用"**。处置：接受误报并注明，或把常量改 env 驱动（小改动）。
- 其余交接必确认项：`Code/frontend/dist` 在 `Code/frontend/.gitignore:11` 内（目标机须 `npm run build`）；
  `Code/backend/.env` 在 `.gitignore:3`（含 API Key/管理员密码/CDS Key，只能走安全通道交接）。

## 交接机平台卫生（LF / 可执行位，2026-09-16）

`core.autocrlf=true` 是本机默认，会对**交付资产**造成两类真实故障，已修：

1. **LF/CRLF**：`.gitattributes` 原先只覆盖 `Code/frontend/**`、`Test/frontend/**`。现补充
   `**/Dockerfile`、`**/Dockerfile.*`、`**/.dockerignore`、`**/compose*.yml`、
   `**/docker-compose*.yml`、`Code/**/*.conf`、`**/*.sh` → `text eol=lf`。
   - 危害：Dockerfile 的 `\` 续行尾随 `\r` 污染下一条指令；shell 脚本在 Linux 下
     `./start.sh` 报 `\r: command not found`。
   - **判定要点**：`git ls-files --eol` 显示这些文件 `i/lf w/crlf` ⇒ 索引本就是 LF，CRLF 只在工作树。
     故加 `eol=lf` **无内容 diff**，只改未来 checkout 的落地形态（零 churn）。若 `i/crlf` 才需
     `git add --renormalize`。
2. **可执行位**：`start.sh` / `stop.sh` / `Code/infra/data-sync/*.sh` 原为 `100644`，Linux 下
   `./start.sh` = Permission denied。已 `git update-index --chmod=+x` → `100755`。
   - **注意**：mode 只活在索引，`git reset` 会静默回退，须在同一提交流程内完成。

新增/移动任何 `Dockerfile`、compose、`*.conf`、`*.sh` 时无需再动 `.gitattributes`（通配已覆盖）。

## 容器化残留（诚实登记，勿当已完成）

- `unrar` **未进镜像**：`Code/backend/vendor/unrar/linux-x64/` 在 `.gitignore` 内，克隆后不存在
  ⇒ 容器内 RAR5 导入不可用（zip / 7z 不受影响，已装 `p7zip-full`）。
- `libeccodes0`(Debian 2.28) 与 PyPI `eccodes` 2.47 的 API 兼容性**未实测**（GRIB2 导入链）。
- 两个 Dockerfile 均通过 `docker build --check`，但**完整构建与容器内运行未实测**
  （科学库层体积大，未在本轮拉取）。首次真机构建是待验项。

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
