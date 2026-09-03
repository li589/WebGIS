# CGDA — 综合地理数据分析系统

Comprehensive Geographic Data Analysis System（CGDA）是一套面向**地理科研人员**与**工程开发者**的 Web 地理数据分析平台：在浏览器中完成地图可视化、多源数据接入、工作流编排与算法产物展示，支持本地数据、Google Earth Engine（GEE）、Open-Meteo 及商业天气源等。

---

## 你能用它做什么

### 地理科研人员

- **地图浏览与叠加**：MapLibre 2D 主舞台，底图切换、行政区边界、栅格/矢量图层叠加
- **天气分析**：点查预报、网格场、标准 z/x/y 天气瓦片；风场粒子/风羽/等值线等 Canvas 叠加
- **工作流分析**：LiteGraph 可视化编辑器编排下载、预处理、反演、统计等节点（如 ω 反演、NDVI、FY/SMAP 等课题组算法）
- **时空结果展示**：时间轴驱动图层、InfoPanel 分析工具、产物预览与导出
- **多源数据**：本地磁盘、GEE、Open-Meteo（在线/自托管）、WeatherAPI、OpenWeather 等

### 工程开发者

- **前后端分离 + 协议先行**：`Code/shared/contracts` 为单一契约来源，OpenAPI 自动生成前端类型
- **工作流主链**：`workflow-runs` API + Celery 多队列异步执行 + SQLite 运行态持久化
- **算法插件化**：`Code/algorithms` Python 包经 provider bridge 接入，模块可独立演进
- **默认同域入口**：Nginx Gateway `:5175` 静态前端 + 反代 FastAPI，便于联调与演示

> 3D：默认 **MapLibre globe**（星空/太阳系/风场主路径）；**Cesium** 为设置可选实验引擎（底图 + overlay XYZ；见 `Docs/02-架构设计/cesium-dual-engine.md`）。

---

## 系统架构

```text
浏览器 (Vue 3 + MapLibre)
    │  HTTP
    ▼
Nginx Gateway :5175 ──► FastAPI :8000
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
         Celery Workers   weatherengine   GEE bridge
         (7 队列)         (点查/瓦片)      (可选)
              │
              ▼
    Python 算法包 + 本地/MinIO 产物存储
              │
    Redis (队列/缓存) · SQLite (运行态) · MinIO (对象) · Open-Meteo API
```

**基础设施分两栈**：

| 栈 | 路径 | 内容 |
|----|------|------|
| 运行栈 | `Code/backend/docker-compose.yml` | Redis、MinIO、`cgda-open-meteo` API |
| 数据栈 | `Code/infra/data-sync/` | Open-Meteo 一次性同步（`launch.py sync`） |

一键启停与组件管理见根目录 [`launch.py`](launch.py)。

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | Vue 3、TypeScript、Vite、Pinia | Node **22**（见 `Code/frontend/package.json`） |
| 2D 地图 | MapLibre GL JS + Canvas 叠加 | 当前主路径 |
| 3D | MapLibre globe（默认）/ Cesium（实验可选） | 设置切换；Cesium 未接风场主链 |
| API | FastAPI | 统一 REST 入口，`/docs` 交互文档 |
| 任务队列 | Celery + Redis | realtime / standard / heavy / batch / download / gee / weather |
| 算法 | Python 3.12 + provider bridge | `Code/algorithms/providers/Python/` |
| 瓦片 | 自研 unified-tiles + weather tiles | 底图 `/unified-tiles`；天气 `/weather/tiles` |
| 元数据 | SQLite | 工作流运行态；PostGIS 为后续目标 |
| 对象存储 | MinIO + 本地磁盘 | compose 已提供 |
| 启动 | `launch.py` + Docker Compose | Windows 推荐 `start.bat` |

---

## 仓库结构

```text
Comprehensive Geographic Data Analysis system/
├─ Code/
│  ├─ frontend/      # Vue 3 WebGIS 前端
│  ├─ backend/       # FastAPI + Celery + weatherengine + GEE
│  ├─ algorithms/    # Python 算法包与数据接入
│  ├─ shared/        # 前后端共享契约
│  └─ infra/         # gateway（Nginx）+ data-sync（气象同步）
├─ Docs/             # 公开文档（架构、规范、部署、专题研究）
├─ Test/             # 测试集中地（backend / frontend / algorithms）
├─ Tools/            # 辅助脚本（非运行时主体模块）
├─ Env/Python312/    # 本地联调唯一 Python 运行时（勿用系统 python）
├─ launch.py         # 跨平台启动器
├─ start.bat / start.sh
├─ README.md         # 本文档
├─ AGENTS.md         # 开发者/AI 导航（命令、验证、「改 X 则跑 Y」）
└─ CLAUDE.md         # Claude Code 入口指针
```

各子目录详情见 [`Code/README.md`](Code/README.md)。

---

## 环境要求

| 组件 | 要求 |
|------|------|
| Python | **3.12**，使用 `Env/Python312`（Windows：`Env\Python312\python.exe`） |
| Node.js | **22.x**（`npm >= 10`） |
| Docker | Desktop（Windows **须管理员身份**运行 Docker 与终端） |
| 磁盘 | 配置 `BACKEND_DATA_ROOT` 指向机构地理数据根目录 |

> 勿用系统 PATH 中的 `python` 启动后端或 Worker，否则易出现依赖不一致的「环境幽灵问题」。`start.bat` 会强制使用 `Env/Python312`。

---

## 快速开始

### 1. 克隆与依赖

```powershell
# 前端依赖（在 Code/frontend 下）
cd Code/frontend
npm install
npm run build
```

Python 依赖已随 `Env/Python312` 预置；若需重建，见 [`Docs/04-执行部署/本地联调环境说明.md`](Docs/04-执行部署/本地联调环境说明.md)。

### 2. 后端配置

```powershell
copy Code\backend\.env.example Code\backend\.env
```

本地联调至少设置：

```env
BACKEND_ENV=development
BACKEND_DATA_ROOT=<你的地理数据根绝对路径>
BACKEND_OUTPUT_ROOT=<产物输出根绝对路径>
```

首次使用可复制 `Code/backend/deployment.config.json.example` 为 `deployment.config.json`，或在登录后访问 **部署配置中心** `/deployment`（仅 `admin`）维护数据根与 Docker 相关项。

### 3. 启动全栈

```powershell
# Windows：以管理员身份打开终端
start.bat
# 或
Env\Python312\python.exe launch.py start
```

浏览器打开 **http://localhost:5175**。默认账号见 `.env` 中 `BACKEND_ADMIN_USERNAME` / `BACKEND_ADMIN_PASSWORD`（development 可在 `.env.example` 查看说明）。

### 4. 同步 Open-Meteo 本地数据（可选）

```powershell
Env\Python312\python.exe launch.py sync
```

本地天气源依赖此步骤；在线源可在设置中配置 Provider。

---

## 日常命令

| 命令 | 作用 |
|------|------|
| `start.bat` / `launch.py start` | Docker + FastAPI + 7 Worker + Beat + Nginx Gateway |
| `launch.py start --vite` | 同上，Gateway 同域 + 背后 Vite HMR（`:5174`） |
| `launch.py restart` | 全量重启（改前端后可用 `--rebuild-frontend`） |
| `launch.py restart backend` | 仅重启 FastAPI + Worker + Beat（改数据根后必用） |
| `launch.py status` / `logs [组件]` | 状态与日志 |
| `launch.py sync` | Open-Meteo 数据面同步 |
| `launch.py clean-cache` | 清理 `__pycache__` 与 Vite 缓存 |
| `launch.py flush` | 清空 Redis + 天气文件缓存（**高风险**，仅排障） |
| `stop.bat` / `launch.py stop` | 停止全部服务 |

前端仅改动时：`launch.py start frontend`（直连 Vite，会停 Gateway）。

完整命令表见 [`AGENTS.md`](AGENTS.md)。

---

## 服务地址

| 服务 | 地址 |
|------|------|
| 前端入口（Gateway） | http://localhost:5175 |
| FastAPI | http://127.0.0.1:8000（文档 `/docs`） |
| Open-Meteo API | http://127.0.0.1:8080 |
| Redis | `127.0.0.1:16379` |
| MinIO | API `:9100`，Console `:9101` |

---

## 配置要点

### 地理数据根

- **真源**：`Code/backend/deployment.config.json`（推荐）与 `Code/backend/.env` 中的 `BACKEND_DATA_ROOT` / `BACKEND_OUTPUT_ROOT`
- **修改入口**：前端 `/deployment`（admin）或编辑上述文件；变更后须 `launch.py restart backend`
- **就绪检查**：`GET /layers` 返回各图层的 `run_readiness`

production 未配置 `BACKEND_DATA_ROOT` 将拒绝启动；代码不会静默回退到其他盘符。

### 用户与鉴权

| 机制 | 说明 |
|------|------|
| 会话 Cookie | 浏览器默认登录方式（`cgda_session`） |
| 个人 API Token | 设置 → 账户，继承账户角色 |
| 服务密钥 | `X-API-Key: backend_auth`，角色由 `BACKEND_API_KEY_ROLE` 决定（默认 `standard`） |

**RBAC 三角色**：`admin`（全权限）、`standard`（读写工作流，不可改高危配置）、`demo`（只读 + 受控数据传输）。

production 写接口默认 fail-closed；development 且未启用 API Key 时，仅 **loopback** 可旁路鉴权。

### 加密与敏感配置

- `BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY`：64 位 hex（32 字节），加密 GEE 凭据、API Key、天气 Provider、远程存储等
- 非 development 环境缺此 key 将拒启
- 凭据轮换后建议 `launch.py restart` 使各进程生效

配置治理详见 [`Docs/03-规范协议/配置文件治理说明.md`](Docs/03-规范协议/配置文件治理说明.md)。

---

## 文档导航

| 读者 | 推荐阅读 |
|------|----------|
| 新人 | 本文 → [`AGENTS.md`](AGENTS.md) → [`Code/README.md`](Code/README.md) |
| 本地联调 | [`Docs/04-执行部署/本地联调环境说明.md`](Docs/04-执行部署/本地联调环境说明.md) |
| 架构与设计 | [`Docs/02-架构设计/`](Docs/02-架构设计/) |
| 接口与命名 | [`Docs/03-规范协议/`](Docs/03-规范协议/) · [`Code/shared/contracts/README.md`](Code/shared/contracts/README.md) |
| 算法接入 | [`Code/algorithms/providers/Python/README.md`](Code/algorithms/providers/Python/README.md) |
| ω 反演等工作流 | [`Docs/08-HTML报告/omega-algorithm-guide/`](Docs/08-HTML报告/omega-algorithm-guide/) |
| 交付与生产 | [`Docs/04-执行部署/delivery-checklist.md`](Docs/04-执行部署/delivery-checklist.md) |
| 文档总索引 | [`Docs/README.md`](Docs/README.md) |

带日期的快照文档（如 `99-历史归档/`）仅作历史参考，以模块 README 与无日期活文档为准。

---

## 开发与测试

### 后端 / 算法测试

在仓库根目录执行（需 `REDIS_URL` 与 `ENVIRONMENT=test`）：

```powershell
Env\Python312\python.exe -m pytest Test/backend -q
Env\Python312\python.exe -m pytest Test/algorithms -q
```

### 前端测试

```powershell
cd Code/frontend
npm run test
npm run lint
npm run build
npm run check:openapi
npm run check:catalog
```

### 提交前

```powershell
pre-commit run --all-files
```

「改某模块应跑哪些测试」见 [`AGENTS.md`](AGENTS.md) 中的「改 X 则跑 Y」表。

---

## 部署与安全摘要

- **单机构部署**：SQLite 元数据 + 多用户 RBAC；Gateway 默认同域入口
- **演示开关**：production 勿开启 `BACKEND_DEMO_SOURCES_ENABLED` / `BACKEND_NODE_STUBS_VISIBLE`
- **Open-Meteo 数据卷**：使用 Docker named volume，Windows 上勿改为 bind mount
- **flush**：仅排障时使用；`start`/`restart` 永不自动 flush
- **联调缓存**：见 [`Docs/07-工程保障/联调缓存与生效边界.md`](Docs/07-工程保障/联调缓存与生效边界.md)

完整交付核对清单见 [`Docs/04-执行部署/delivery-checklist.md`](Docs/04-执行部署/delivery-checklist.md)。

---

## 相关入口

- **Gateway 说明**：[`Code/infra/gateway/README.md`](Code/infra/gateway/README.md)
- **后端模块**：[`Code/backend/README.md`](Code/backend/README.md)
- **前端模块**：[`Code/frontend/README.md`](Code/frontend/README.md)
- **AI 辅助开发**：根目录 [`AGENTS.md`](AGENTS.md)（面向 coding agent 的完整导航）
