# Comprehensive Geographic Data Analysis System

## 项目定位

CGDA 是**面向课题组与大气研究院研究员**的科研数据分析平台（初代发布定位），以 2D 平面地图（MapLibre）为主链路，统一承载：

- `2D 平面地图模式`（主链路）；`3D 地球模式`（Cesium，实验性，非默认主链）
- 多源数据接入：本地数据、Google Earth Engine（GEE）、Open-Meteo 等公共数据接口
- 动态时空结果展示与回传
- 多课题组算法模块化接入（workflow 编排）

本仓库已从"方案与原型阶段"进入"工程化落地阶段"：`workflow-runs` 主链、天气瓦片渲染、Celery/Redis/MinIO 基础设施与架构拆分均已具备可运行实现。

## 发布边界（初代）

- **目标用户**：本课题组 + 大气研究院研究员，访问量小；可能有临时展出演示需求
- **部署形态**：单机构部署、SQLite 元数据；支持多用户 RBAC（admin / operator / viewer）与会话 Cookie + 个人 API Token
- **鉴权层次**：浏览器默认 **HttpOnly 会话 Cookie**（`cgda_session`）；脚本/CI 用服务密钥 `backend_auth`（角色由 `BACKEND_API_KEY_ROLE` 决定，默认 operator）；用户可在「设置 → 账户」创建个人 API Token（继承账户角色）
- **写鉴权**：production 默认 fail-closed；development 且 `BACKEND_API_KEYS_ENABLED=false` 时仅 **loopback** 可旁路，局域网调试需显式 `BACKEND_DEV_AUTH_BYPASS=true`
- **敏感配置读**：`GET /config/api-keys|gee/*|weather*|remote-storage|data-source*|data-cache/overview` 与写接口同级鉴权；`/config/general` 与 `/config/about` 仍公开。已登录 operator/admin 通过会话鉴权；可选在浏览器粘贴服务密钥（`sessionStorage` / `localStorage`）
- **加密主密钥**：`BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY` 须为 **64 位 hex（32 字节）**；同一把 key 加密 GEE SA / API keys / 天气 provider / 远程存储 / 门户凭据（泄露 blast radius 大）。非 development 缺 key 拒启
- **GEE 账号 API 管理**：production 默认关闭；development 默认开启（`BACKEND_GEE_API_ACCOUNT_MANAGEMENT_ENABLED` 可覆盖）
- **UI 重启后端**：始终重启 FastAPI+Worker+Beat（请求体 `components` 仅校验、不选子集）；门禁 `BACKEND_UI_RESTART_ENABLED`（默认仅 development）
- **演示模式**：`demo://` 占位数据源仅 development 默认可用；展出演示需以 production 运行时设 `BACKEND_DEMO_SOURCES_ENABLED=true`
- **占位节点**：未实现执行器的节点模板在 production 节点面板默认隐藏（`BACKEND_NODE_STUBS_VISIBLE=true` 可显示）
- **写接口限流**：`/config`、`/import`、`/workflow-runs` 写方法默认 120 次/分钟/IP；天气瓦片 GET 另有宽松限流（`BACKEND_WEATHER_TILE_RATE_LIMIT_PER_MINUTE`，默认 240）；development/test 旁路
- **会话过期**：使用中 API 返回 401 时前端自动跳转登录页；工具栏「日志」可导出错误记录（含 `request_id`）
- **Gateway 模式**：`launch.py start gateway` 时 Nginx 反代须包含 `/auth`、`/overlay-tiles`、`/health`（与 Vite proxy 一致）；见 `Code/infra/gateway/README.md`

## 当前仓库结构

```text
Comprehensive Geographic Data Analysis system/
├─ .ai/         # 【本地专用，不上传 GitHub】AI 工作区：规则/技能/计划/进度/记忆/文档
├─ Env/Python312/  # 【本地联调唯一 Python 运行时】勿用系统 PATH 的 python
├─ Code/           # 实际工程代码（含 backend/vendor 等运行时第三方二进制）
├─ Tools/          # 主线外辅助：外部/临时工具、下载校验脚本（禁止放主体运行模块）
├─ Example/        # 外部参考材料（如 Windy）
├─ launch.py       # 跨平台一键启动（会优先切换到 Env/Python312）
├─ start.bat / start.sh   # 推荐入口（强制 Env/Python312）
├─ stop.bat / stop.sh
├─ README.md       # 项目说明（表面三文档之一）
├─ AGENTS.md       # AI 编程导航（表面三文档之一）
└─ CLAUDE.md       # Claude Code 入口（表面三文档之一）
```

> 原 `Doc/` 与根目录进度/验证文档已全部并入 `.ai/`（`.ai/docs/`、` .ai/progress/`）；各 AI 工具的规则文件（`.cursor/`、`.trae/`、`.github/`）保留原位但仅作指针，完整约定见 `.ai/rules/`。

## 当前工程分层

`Code/` 目录按职责划分为：

```text
Code/
├─ frontend/   # Vue 3 WebGIS：MapLibre 2D 主舞台、天气叠加、工作流交互
├─ backend/    # FastAPI + Celery：workflow 编排、天气引擎、瓦片、GEE
├─ algorithms/ # Python 算法包、数据接入、工作流与产品输出
├─ shared/     # 前后端共享协议与公共契约
├─ infra/      # 数据面 compose（data-sync；与运行栈隔离）
└─ docs/       # 面向实现与协作的补充文档
```

说明：基础设施分两栈——**运行** `Code/backend/docker-compose.yml`（Redis / MinIO / `cgda-open-meteo`）；**数据** `Code/infra/data-sync/`（一次性 sync，如 `open-meteo-sync`）。一键启停与同步见仓库根目录 `launch.py`。

## 系统总体能力

### 前端展示

- `2D`（当前主路径）：MapLibre 底图、行政区边界、天气图层瓦片、风场 Canvas（粒子/风羽/等值线）
- `3D`：Cesium / vue-cesium 已打包依赖，真实地球模式尚未作为默认主链启用
- 统一交互：图层侧栏、时间轴、工具栏导入、截图导出、工作流状态面板、信息面板
- 工作流编辑器：LiteGraph 画布可编译执行；支持课题组数据下载 / 解压 / 配置读取 / 变量提取节点（见 `Code/docs/课题组数据全链路-2026-07-21.md`）

### 后端与计算

- `FastAPI` 作为统一 API 与工作流入口
- `Celery + Redis` 作为异步任务执行通道（多队列：realtime / weather / gee 等）
- `Python` 算法包作为科学计算与产品生成核心
- `weatherengine`：点查 + 网格预报 + 标准 z/x/y 天气瓦片
- `GEE` 模块已嵌入后端，可按配置挂载

### 数据与存储

- 工作流状态：当前以 `SQLite` 持久化（`PostGIS` 仍为后续目标）
- `MinIO`：对象/artifact 存储（compose 已提供，本地与 MinIO 双后端抽象）
- `Redis`：队列、缓存、天气请求限流/断路器支撑
- 本地磁盘 / `.data`：中间结果、调试输出与开发态数据

## 推荐技术栈

| 层级 | 技术 | 当前状态 |
| ---- | ---- | ---- |
| 前端 | Vue 3 + TypeScript + Vite + Pinia | 已落地 |
| 2D | MapLibre GL JS + Canvas 叠加 | 已落地（主路径） |
| 3D | CesiumJS + vue-cesium | 依赖已引入，模式未成为主链 |
| 大数据叠加 | deck.gl | 规划中 |
| API | FastAPI | 已落地 |
| 异步任务 | Celery + Redis | 已落地（经 compose / launch 启动） |
| 算法 | Python + importlib / provider bridge | 已落地第一层 |
| GEE | Earth Engine Python API（服务端） | 模块已落地，产线仍在完善 |
| 空间库 | PostgreSQL + PostGIS | 规划中（现状 SQLite） |
| 瓦片服务 | unified-tiles（自研） / Martin + TiTiler（规划） | 统一瓦片入口已落地 |
| 对象存储 | MinIO + 本地 | MinIO compose 已落地 |
| 启动 | launch.py + Docker Compose | 运行栈 Redis/MinIO/Open-Meteo API；数据同步 `infra/data-sync` |

## 当前阶段建议

近期排期以 `.ai/progress/2026-08-04-pending-tasks-audit.md` 与 `.ai/docs/reference/工程收口仪表盘.md` 为准：

1. **P0**：FY/SMAP UI 人工闭环（更大样本条带上图 + `ui-verification-steps.md`）
2. **P0**：Open-Meteo Phase B（tile-manager / coverage 与 settings `default_model` 贯通）
3. **P1**：真实课题组数据 e2e / NAS 绿测；工作流调度 P1（dry-validate / progress 选取等）
4. **P2–P3**：Layers god store 继续拆分；按需推进 PostGIS、TiTiler/Martin、Cesium 主链（Nginx 可选 gateway 已可用：`launch.py start gateway`）

契约层面保持 `workflow-runs` / `unified-tiles` / artifact 稳定。
## 文档导航

建议优先阅读：

- `Code/README.md`：`Code` 目录工程总览
- `Code/frontend/README.md`：前端工程说明
- `Code/backend/README.md`：后端工作流与运行说明
- `Code/shared/contracts/README.md`：共享协议说明
- `Code/algorithms/providers/Python/README.md`：Python 算法包说明
- `Code/docs/双通道接口设计总结.md`：控制流 / 数据流双通道设计
- `.ai/docs/specs/技术栈.md`：目标架构与落地状态对照
- `.ai/docs/specs/规范文档.md`：字段与接口命名约定
- `.ai/README.md`：AI 工作区导航（规则/技能/计划/进度/记忆/文档）

带明确日期的阶段快照与实施计划（如 `.ai/docs/reference/`、`.ai/memory/archive/*`）作历史参考，不以它们覆盖上述活文档。

## 本地 Python 环境（必读）

**本仓库本地联调唯一解释器：`Env/Python312`。**

| 平台 | 解释器路径 | 推荐启动 |
|------|------------|----------|
| Windows | `Env\Python312\python.exe` | `start.bat` / `stop.bat` |
| Linux/macOS | `Env/Python312/bin/python`（或同目录 `python3`） | `./start.sh` / `./stop.sh` |

- **不要**用系统 PATH 里的 `python` / `C:\Program Files\Python\...` 起后端与 Worker：依赖（如 `rarfile`、科学库）与 `Env/Python312` 不一致会导致导入/解压等「环境幽灵问题」。
- `start.bat` / `stop.bat` **强制**使用上述路径；找不到则直接报错退出。
- 若手动调用：`Env\Python312\python.exe launch.py start`。即便误用系统 `python launch.py`，启动器也会在检测到 `Env/Python312` 时自动 `exec` 切换过去。
- `Env/Python312` 是**本地开发/联调运行时**，不是 Docker 生产镜像；交付部署另走容器/服务器环境。旧文档中「不建议作为长期交付依赖」仅指生产交付，**不表示本地应回避它**。

## Windows：Docker 必须以管理员身份运行（必读）

本仓库联调依赖 Docker Desktop 拉起 Redis / MinIO / Open-Meteo 等容器。在 **Windows** 上：

- **Docker Desktop 与启动终端（`start.bat` / PowerShell / Cursor 终端）须以「管理员身份」运行。**
- **否则启动可能会失败**（例如报 Docker 未就绪、compose 起不全、镜像/volume 访问失败等）。
- 非管理员时的常见症状：**镜像无法拉取/访问**、named volume / 引擎配置读失败、部分 compose 服务起不全或权限报错。
- 排障顺序：先确认 Docker Desktop **以管理员身份**启动且引擎就绪 → 终端也提权 → 再 `launch.py start` / `restart`。

详见 [`Doc/本地联调环境说明.md`](Doc/本地联调环境说明.md)。

> 默认联调不启 Nginx。演示/同域入口：`Env\Python312\python.exe launch.py start gateway`（需先有 FastAPI `:8000` 与 `Code/frontend/dist`；与 Vite 互斥，详见 `Code/infra/gateway/README.md`）。

## 日常联调命令

- `start.bat`（或 `Env\Python312\python.exe launch.py start`）— 运行栈 + FastAPI + Workers + Vite 前端
- `Env\Python312\python.exe launch.py start gateway` — Nginx 同域入口 `:5175`（可选）
- `Env\Python312\python.exe launch.py restart backend` — 仅重启 FastAPI + Worker + Beat（改数据根后必用；不动 Docker/Vite）
- `Env\Python312\python.exe launch.py sync` — 数据面 Open-Meteo 同步（`Code/infra/data-sync`）
- `stop.bat` / `Env\Python312\python.exe launch.py status` / `flush`
- 活文档应随代码结构变化同步更新；带日期的记录文档可归档保留

## 地理数据根（可变）

- **真源**：`Code/backend/.env` 中的 `BACKEND_DATA_ROOT` / `BACKEND_OUTPUT_ROOT`（进程启动时读入；**禁止**代码静默回退盘符）。
- **本机联调示例**：`I:\Geograph_DataSet`（见 `.env.example`）；他机构须改为本机绝对路径。production 未设 `BACKEND_DATA_ROOT` 将拒启。
- **前端**：设置 → **数据源** → 编辑路径 →「保存路径」或「保存并重启后端」（调度 `launch.py restart backend`；需写鉴权 / development 旁路；`BACKEND_UI_RESTART_ENABLED` 控制门禁）。
- **API**：`PUT /config/data-source/paths`、`POST /config/service/restart`；`GET /config/data-source` 返回生效值与 `pending_restart`。
- 图层库「默认数据源未就绪」多因根未配或相对路径与盘上布局不一致；就绪检查见 `GET /layers` 的 `run_readiness`。

## 运维手册（初代）

### 凭据轮换（P2-1）

- **写鉴权密钥**（`backend_auth`）与 MinIO / GEE / 天气源凭据均缓存在进程内（`effective_config` 三层缓存 + 各 repository），**轮换后须全栈重启**才彻底生效。
  - 写密钥轮换经配置页 upsert/toggle/delete → 进程内即时失效（`cache_clear` + `rehydrate`）；但**跨进程**（多 worker / 多 FastAPI 副本）不会即时传播，须重启所有后端进程。
  - 安全做法：先在配置页设新密钥 → `launch.py restart` → 再撤旧密钥。
- **凭据不入前端 bundle**（P1-1）：写密钥仅由操作员运行时经设置页写入（localStorage），不随 JS 分发。

### 数据库 schema 与迁移（P2-3）

- 本项目无 Alembic；`workflow_state.sqlite3` 采用 **additive-only** 迁移策略：仅向前加列 / 加表 / 加索引，不改类型、不删列、不迁数据。
- `workflow_repository.py` 维护 `SCHEMA_VERSION` 常量与 `schema_meta` 版本表；`get_schema_version()` 可读当前 DB 版本。每次 schema 变更须递增 `SCHEMA_VERSION` 并在 `SCHEMA_CHANGES` 记录说明。
- 发版前检查：若 `get_schema_version() < SCHEMA_VERSION`，说明 DB 落后于代码（additive 迁移会在启动时自动补齐）；若 `>`，说明运行了更新代码的 DB（不支持回滚，需从快照恢复）。
- **备份 / 恢复**：
  - `launch.py reset-db` 会自动在 `.data/workflow_state_snapshots/` 创建带时间戳的快照（保留最近 N 份，`--keep-snapshots` 可配）。
  - 手动备份：`cp -r Code/backend/.data/workflow_state/ <backup>/`（须先 `launch.py stop`，Windows 下 SQLite 文件被占用无法复制）。
  - 恢复：停服务 → 用快照覆盖 `workflow_state/` → `launch.py start`。
- 凭据 DB（`api_keys` / `gee_credentials` / `remote_storage_credentials` / `weather_engine` 等）与 `workflow_state` 同目录，备份时一并覆盖。
