# Comprehensive Geographic Data Analysis System

## 项目定位

本项目面向地理信息数据展示与分析需求，目标是建设一个基于 Web 的综合地理信息平台，统一承载：

- `3D 地球模式` 与 `2D 平面地图模式`
- 多源数据接入，包括本地数据、Google Earth Engine（GEE）、公共数据接口
- 动态时空结果展示与回传
- 多课题组算法模块化接入
- 面向展示效果、交互流畅度与后续扩展性的工程化实现

本仓库已从“方案与原型阶段”进入“工程化落地阶段”：`workflow-runs` 主链、天气瓦片渲染、Celery/Redis/MinIO 基础设施与架构拆分均已具备可运行实现。

## 当前仓库结构

```text
Comprehensive Geographic Data Analysis system/
├─ Doc/         # 项目方案、技术栈、规范与协作文档
├─ Env/         # 本地开发环境与启停辅助脚本
├─ Code/        # 实际工程代码
├─ Tools/       # 数据下载、校验与辅助工具
├─ Example/     # 外部参考材料（如 Windy）
├─ launch.py    # 跨平台一键启动（Docker + FastAPI + Celery + 前端）
├─ start.bat / start.sh
├─ stop.bat / stop.sh
└─ README.md
```

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

1. 巩固天气瓦片与风场渲染体验（当前工作区主要推进项）
2. 保持 `workflow-runs` / unified-tiles / artifact 契约稳定
3. 继续完善课题组 Python 算法真实数据接入
4. 按需推进 PostGIS、TiTiler/Martin、Cesium 3D 与 Nginx 部署

## 文档导航

建议优先阅读：

- `Code/README.md`：`Code` 目录工程总览
- `Code/frontend/README.md`：前端工程说明
- `Code/backend/README.md`：后端工作流与运行说明
- `Code/shared/contracts/README.md`：共享协议说明
- `Code/algorithms/providers/Python/README.md`：Python 算法包说明
- `Code/docs/双通道接口设计总结.md`：控制流 / 数据流双通道设计
- `Doc/技术栈.md`：目标架构与落地状态对照
- `Doc/规范文档.md`：字段与接口命名约定

带明确日期的阶段快照与实施计划（如 `代码事实同步文档-2026-07-06.md`、`.trae/documents/*-2026-07-*.md`）作历史参考，不以它们覆盖上述活文档。

## 说明

- `Env/Python312` 更接近本地开发环境，不建议直接作为长期交付依赖
- 日常联调优先使用根目录 `launch.py` / `start.bat`（Windows）或 `./start.sh`（Linux）：
  - `python launch.py start` — 运行栈 + FastAPI + Workers + 前端
  - `python launch.py sync` — 数据面 Open-Meteo 同步（`Code/infra/data-sync`）
  - `python launch.py stop` / `status` / `flush`
- 活文档应随代码结构变化同步更新；带日期的记录文档可归档保留
