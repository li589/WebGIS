# Comprehensive Geographic Data Analysis System

## 项目定位

本项目面向地理信息数据展示与分析需求，目标是建设一个基于 Web 的综合地理信息平台，统一承载：

- `3D 地球模式` 与 `2D 平面地图模式`
- 多源数据接入，包括本地数据、Google Earth Engine（GEE）、公共数据接口
- 动态时空结果展示与回传
- 多课题组算法模块化接入
- 面向展示效果、交互流畅度与后续扩展性的工程化实现

本仓库当前已经从“方案与原型阶段”进入“工程化落地阶段”，核心代码、协议、算法包和后端工作流都在持续完善中。

## 当前仓库结构

```text
Comprehensive Geographic Data Analysis system/
├─ Doc/        # 项目方案、技术介绍、架构图与协作文档
├─ Env/        # 本地开发环境、启动脚本与依赖脚本
├─ Code/       # 实际工程代码
└─ README.md   # 仓库总入口
```

## 当前工程分层

`Code/` 目录按职责划分为：

```text
Code/
├─ frontend/   # Web 前端：2D/3D 双模式展示与交互
├─ backend/    # FastAPI 工作流服务、任务编排、结果与事件管理
├─ algorithms/ # Python 算法包、数据接入、工作流与产品输出
├─ shared/     # 前后端共享协议与公共契约
├─ infra/      # 部署配置、容器与网关相关内容
├─ scripts/    # 初始化、导入、清洗、运维脚本
└─ docs/       # 面向实现与协作的补充文档
```

## 系统总体能力

### 前端展示

- `3D 地球模式`：用于地球、地形、实体和时间动画展示
- `2D 平面地图模式`：用于底图、矢量瓦片、专题图层展示
- `统一交互`：图层控制、时间轴、时空范围选择、任务入口与结果面板

### 后端与计算

- `FastAPI` 作为统一 API 与工作流入口
- `Celery + Redis` 作为异步任务执行通道
- `Python` 算法包作为科学计算与产品生成核心
- `GEE`、本地文件、对象存储等作为多源数据与结果承载方式

### 数据与存储

- `PostgreSQL + PostGIS`：业务数据、空间元数据与空间查询
- `MinIO + COG`：栅格历史数据与大体量时序影像
- `Redis`：任务状态、热点结果与队列支撑
- `本地磁盘 / NAS`：中间结果、调试输出与导出文件

## 推荐技术栈

- 前端：`Vue 3 + TypeScript + Vite + Pinia`
- 3D：`CesiumJS + vue-cesium`
- 2D：`MapLibre GL JS`
- 高性能可视化：`deck.gl`
- 后端 API：`FastAPI`
- 异步任务：`Celery + Redis`
- 算法集成：`Python + importlib`
- GEE 集成：`Earth Engine Python API`
- 空间数据库：`PostgreSQL + PostGIS`
- 栅格切片：`TiTiler`
- 矢量切片：`Martin`
- 对象存储：`MinIO`
- 网关与部署：`Nginx + Docker Compose`

## 当前阶段建议

项目当前更适合按“先打通主链路，再逐步补齐能力”的顺序推进：

1. 完成前端基础壳层与 2D/3D 模式切换
2. 完成后端工作流入口、状态查询与结果回传
3. 统一前后端共享协议
4. 持续完善 Python 算法包与数据接入链路
5. 补齐部署、监控、日志和协作规范

## 文档导航

建议优先阅读以下文档，了解当前架构与开发边界：

- `Code/README.md`：`Code` 目录工程总览
- `Code/frontend/README.md`：前端工程说明
- `Code/backend/README.md`：后端工作流与运行说明
- `Code/shared/contracts/README.md`：共享协议说明
- `Code/algorithms/providers/Python/README.md`：Python 算法包说明
- `Code/algorithms/providers/docs/detailed_design.md`：Python 计算包详细设计
- `Code/docs/双通道接口设计总结.md`：前后端控制流 / 数据流双通道设计总结

## 说明

- `Env/Python312` 更接近本地开发环境，不建议直接作为长期交付依赖
- 后续若进入多人协作阶段，建议统一以脚本与容器化方式管理运行环境
- 当前仓库中的文档已经从“规划说明”逐步演进为“工程事实说明”，后续应持续与代码同步更新