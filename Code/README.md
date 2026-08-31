# Code 目录总览

`Code/` 是本项目的工程代码根目录，负责承载前端应用、后端服务、算法计算包、共享协议与协作文档。当前项目已进入工程落地阶段，这里是整个仓库的开发导航中心。

## 设计目标

- `前后端分离`：展示层、服务层与计算层可独立演进
- `协议先行`：用统一数据契约连接前端、后端和算法包
- `算法插件化`：支持不同课题组在统一框架下接入算法
- `工作流驱动`：后端以 `workflow-runs` / 结果引用 / 事件流为主线组织业务
- `数据面按需加载`：artifact、预览图、统一瓦片与控制流分离
- `先主链后扩展`：先稳定 workflow / 天气瓦片 / provider 桥接，再补 PostGIS、3D、专用瓦片服务

## 当前工程结构

```text
Code/
├─ frontend/   # Web 前端：MapLibre 2D 主舞台、天气叠加、图层与工作流交互
├─ backend/    # FastAPI + Celery：workflow 编排、weatherengine、统一瓦片、GEE
├─ algorithms/ # Python 算法包、数据接入、工作流与产品输出
├─ shared/     # 前后端共享协议与公共契约
├─ weixin/     # 微信小程序开发项目
├─ agentKits/  # 实现AI Agent助手功能
└─ infra/      # data-sync（气象同步）+ gateway（可选 Nginx 同域入口）

```

说明：公开文档在仓库根 **`Docs/`**（编号目录）；AI 本地工作区在 **`.ai/`**。测试在仓库根 **`Test/`**。运行栈见 `backend/docker-compose.yml`；一键启停在仓库根 `launch.py`（`Env/Python312`）。

## 目录职责

### `frontend`

前端负责统一 WebGIS 壳层与用户交互，重点管理：

- MapLibre 地图主舞台与底图切换
- 天气图层瓦片加载、风场 Canvas 叠加（粒子 / 风羽 / 等值线）
- 图层树、时间轴、工具栏导入、截图导出
- 工作流提交、状态面板与结果信息面板
- LiteGraph 工作流编辑器：画布 Run 会编译为 `workflow_definition` 提交（课题组数据下载/解析节点可执行）

建议优先把前端理解为“展示层 + 交互层”，而不是单纯地图页面。Cesium 依赖已引入，但默认主链仍是 `2D-first`。

### `backend`

后端负责请求入口、工作流调度、运行状态、事件流、结果与瓦片服务。主执行模型是：

`API routers → workflow services → Celery tasks / bridges → providers`

后端职责通常包括：

- 接收并校验 `workflow-runs` 请求
- 创建运行记录与事件流（SQLite 持久化）
- 调度同步或异步执行
- 管理 artifact、预览图与结果引用
- 天气点查 / 网格 / 标准 z/x/y 瓦片（`/unified-tiles`）；天气引擎支持多 Provider（`open-meteo-online` / `open-meteo-local` / WeatherAPI / OpenWeather），图层侧栏与 InfoPanel 可钉源
- 对接 Python 算法包与 GEE

原单体 `interaction_hub.py` 已拆分为 `services/workflow/` 下多个聚焦服务；原单一 `routes.py` 已拆为 `api/routers/*` 域路由。

### `algorithms`

算法目录是项目最关键的计算层。当前 Python 计算包已演化为一套稳定工程包，包含：

- `contracts`：任务、数据、产品与事件契约
- `interfaces`：调度器、数据源、日志、产品输出等适配接口
- `runner`：统一入口与运行时上下文
- `workflow`：工作流定义、执行与序列化
- `service`：HTTP / 队列 / 平台适配服务
- `data_access`：数据源发现、解析、物化与格式适配
- `modules`：原生算法模块
- `ingest`：原始数据读取与装配
- `algorithms`：科学计算核心
- `publish`：产品写出与 manifest 构建
- `storage`：缓存、中间文件与路径组织

### `shared`

共享协议负责统一前后端与算法之间的字段、对象和约定。前端可通过 `openapi-typescript` 从后端 OpenAPI 生成 `src/types/api-contracts.ts`。

### 文档与测试（不在 `Code/` 内）

- **`Docs/`**：人类可读正式文档（协作 / 架构 / 规范 / 专题 / 审查 / 结题）
- **`.ai/`**：AI 技能、规则、计划、进度（本地，不上传）
- **`Test/`**：后端 / 前端 / 算法测试集中地（见 `AGENTS.md`）
- **`AGENTS.md`**：命令指针、「改 X 则跑 Y」、高风险区

## 需要避免的做法

- 不要把所有 Python 代码堆进单一目录
- 不要让前端直接依赖算法实现细节
- 不要让每个课题组自定义一套请求和结果格式
- 不要把 GEE、数据库、瓦片服务和算法逻辑混写在一起
- 不要重新把工作流逻辑收回已删除的单体 hub / 巨型 routes

## 推荐阅读顺序

1. 仓库根 `README.md` → `AGENTS.md`
2. `Code/README.md`
3. `Code/backend/README.md`
4. `Code/frontend/README.md`
5. `Code/shared/contracts/README.md`
6. `Docs/README.md` → `Docs/02-架构设计/工程决策纪要-配置瓦片与契约.md`
7. `Docs/03-规范协议/双通道接口设计总结.md`
8. `Code/algorithms/providers/Python/README.md`
9. `Code/algorithms/providers/docs/detailed_design.md`
10. `Docs/05-专题研究/其它专题/课题组数据全链路-2026-07-21.md`（画布编译 + 数据获取节点）
