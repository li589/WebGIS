# Comprehensive Geographic Data Analysis System

## 项目概述

本项目面向课题组的地理信息数据展示与分析需求，目标是建设一个基于 Web 的综合地理信息平台，支持以下核心能力：

- 双显示模式：`3D 地球模式` 与 `2D 平面地图模式`
- 多源数据接入：服务器本地数据、Google Earth Engine（GEE）、外部公共数据接口
- 动态结果展示：根据图层选择、时间轴、时空范围实时计算并回传展示结果
- 多课题组算法融合：支持将不同数据集和算法模块化接入统一平台
- 兼顾视觉效果与性能：在用户规模暂不大的前提下，优先保证展示质量、交互流畅度和后续扩展能力

## 当前仓库现状

当前仓库以方案文档为主，代码目录尚处于初始化阶段：

- `Doc/技术介绍.md`：关键技术选型说明
- `Doc/技术栈.md`：整体技术栈表格
- `Doc/架构设计.png`：架构图
- `Doc/Draw/TechStack.py`：技术栈图绘制脚本
- `Env/Python312`：本地 Python 运行环境，便于后续算法和后端服务开发
- `Code/`：已按本 README 初始化为首版工程骨架，后续在此基础上逐步落地

## 目标能力

### 1. 前端展示

- `3D 地球模式`：使用 CesiumJS 展示地球、地形、实体对象、时间动画
- `2D 平面地图模式`：使用 MapLibre GL JS 展示底图、矢量瓦片、专题图层
- `大数据叠加`：在 2D 模式中使用 deck.gl 进行百万级点、热力图、网格等 GPU 渲染
- `统一交互`：共享图层控制、时间轴、时空范围选择、任务提交与结果回显

### 2. 后端与计算

- `FastAPI` 作为主 API 服务，负责请求入口、任务提交、结果查询
- `Celery + Redis` 负责异步任务执行，避免长时间算法阻塞 Web 请求
- `算法引擎` 以插件化方式接入不同课题组的数据处理流程
- `GEE 代理服务` 负责获取地图瓦片 URL，尽量避免无必要的原始数据下载

### 3. 数据与存储

- `PostgreSQL + PostGIS`：管理业务数据、元数据、矢量边界、空间查询
- `MinIO + COG`：管理栅格历史数据和大体量时序影像
- `Redis`：缓存任务状态、热点请求、轻量结果
- `本地磁盘 / NAS`：保存中间结果、导出成果、调试输出

## 建议技术架构

- 前端：`Vue 3 + TypeScript + Vite + Naive UI + Pinia`
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

## 推荐开发顺序

### 阶段 1：最小可运行骨架

- 初始化前端项目，完成 2D/3D 模式切换界面
- 初始化 FastAPI 服务与健康检查接口
- 建立任务提交、任务查询的基础 API
- 配置 Redis 和 Celery 的最小异步任务链路

### 阶段 2：地图与图层能力

- 接入 Cesium 地球视图
- 接入 MapLibre 平面地图
- 建立统一图层配置协议
- 打通静态边界、基础矢量图层、简单专题图层展示

### 阶段 3：数据接入与计算

- 接入 GEE 代理服务
- 接入静态 COG 栅格数据与动态切片服务
- 设计课题组算法注册机制
- 支持按时间、空间范围触发计算

### 阶段 4：性能与工程化

- 增加缓存策略与任务结果复用
- 优化前端图层加载和大数据渲染
- 完善日志、监控、异常处理
- 增加部署脚本与容器编排

## `Code` 目录规划

`Code` 目录已按照“前端、后端、算法、共享协议、部署、脚本”进行拆分：

```text
Code/
├─ frontend/       # Web 前端：2D/3D 双模式展示
├─ backend/        # FastAPI、Celery、GEE 代理、瓦片与任务服务
├─ algorithms/     # 各课题组算法注册、适配器、输出规范
├─ shared/         # 前后端共享协议、常量、示例配置
├─ infra/          # Docker、Nginx、Compose 等部署配置
├─ scripts/        # 初始化、导入、清洗、运维脚本
└─ docs/           # 面向代码实现的补充文档
```

更详细的落地结构见 `Code/README.md`。

## 目录说明

```text
Comprehensive Geographic Data Analysis system/
├─ Doc/
├─ Env/
├─ Code/
└─ README.md
```

## 下一步建议

- 在 `Code/frontend` 初始化 `Vue 3 + Vite + TypeScript`
- 在 `Code/backend` 初始化 `FastAPI` 与基础依赖
- 明确课题组算法接入规范，例如输入参数、输出格式、任务元数据
- 确定第一批演示数据源，优先做一个可演示闭环

## 备注

- 当前 `Env/Python312` 更像本地开发环境，不建议作为长期交付环境依赖
- 后续若进入多人协作阶段，建议统一迁移到 `Docker Compose` 管理运行环境
- `Code` 目录结构已按扩展性优先设计，前期即使用户不多，也能兼顾展示效果、性能和后期接入成本
