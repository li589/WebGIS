# Code 目录规划

本目录用于承载项目的实际工程代码，按照“展示层、服务层、算法层、共享协议、部署层”进行拆分，避免未来 2D/3D 前端、空间服务、异步计算和多课题组算法混在一起。

## 设计原则

- `前后端分离`：便于独立开发、测试与部署
- `算法插件化`：便于不同课题组独立维护算法实现
- `共享协议先行`：前后端围绕统一数据结构协作
- `部署配置独立`：避免把运行环境细节耦合进业务代码
- `先骨架后实现`：先明确责任边界，再逐步填充模块

## 推荐目录树

```text
Code/
├─ frontend/
│  ├─ public/
│  └─ src/
│     ├─ app/          # 应用初始化、路由、地图模式切换入口
│     ├─ components/   # 通用组件，如图层面板、时间轴、图例
│     ├─ modules/      # 业务模块，如 3D 地球、2D 地图、任务中心
│     ├─ services/     # API 请求、地图服务封装、任务轮询
│     ├─ stores/       # Pinia 状态管理
│     ├─ styles/       # 全局样式与主题
│     ├─ types/        # 前端类型定义
│     ├─ utils/        # 工具函数
│     └─ views/        # 页面级视图
├─ backend/
│  ├─ app/
│  │  ├─ api/          # REST API 路由
│  │  ├─ core/         # 配置、日志、鉴权、异常处理
│  │  ├─ db/           # 数据库连接、会话、仓储
│  │  ├─ gee/          # GEE 代理与服务端封装
│  │  ├─ models/       # ORM 模型
│  │  ├─ schemas/      # Pydantic 输入输出模型
│  │  ├─ services/     # 业务服务层
│  │  ├─ tasks/        # Celery 任务定义
│  │  ├─ tiles/        # 瓦片、图层、渲染相关服务
│  │  └─ workers/      # Worker 启动与任务编排
│  └─ tests/           # 后端测试
├─ algorithms/
│  ├─ registry/        # 算法注册表与发现机制
│  ├─ providers/       # 各课题组算法实现
│  ├─ adapters/        # 输入输出适配层
│  └─ outputs/         # 标准结果样例与导出模板
├─ shared/
│  ├─ contracts/       # 前后端共享协议，如图层配置、任务参数
│  ├─ constants/       # 共享常量、枚举
│  └─ samples/         # 示例请求、示例响应、测试样本
├─ infra/
│  ├─ compose/         # Docker Compose 编排
│  ├─ docker/          # 各服务 Dockerfile
│  └─ nginx/           # 反向代理配置
├─ scripts/            # 初始化、数据导入、批处理、运维脚本
└─ docs/               # 面向实现的接口说明、规范与补充文档
```

## 各模块职责

### `frontend`

建议先围绕“双模式统一壳层”设计：

- `app/` 负责应用入口、全局布局、模式切换
- `modules/earth/` 后续放 3D 地球相关能力
- `modules/map/` 后续放 2D 地图相关能力
- `modules/layers/` 后续放图层树、图例、样式切换
- `modules/tasks/` 后续放任务提交、进度轮询、结果展示

前端重点不是单纯画地图，而是统一管理：

- 地图状态
- 时间轴状态
- 图层可见性
- 查询条件
- 任务生命周期

## `backend`

建议按“接口层 -> 服务层 -> 任务层 -> 数据层”组织：

- `api/` 只负责参数接收与响应返回
- `services/` 处理业务流程，如任务创建、图层查询、结果聚合
- `tasks/` 负责长耗时异步计算
- `gee/` 单独封装，避免 GEE 调用逻辑散落到业务代码中
- `tiles/` 用于组织瓦片服务、图层拼装、切片代理

推荐后续优先补齐的接口：

- `GET /health`
- `GET /layers`
- `POST /tasks`
- `GET /tasks/{task_id}`
- `GET /results/{task_id}`

## `algorithms`

这是本项目后续最关键的扩展点，建议从一开始就约束统一接口。

每个算法模块至少应明确：

- 输入数据来源
- 输入参数定义
- 时间范围与空间范围要求
- 输出结果格式
- 是否支持缓存
- 是否支持异步执行

建议每个课题组算法后续以独立子目录方式接入，例如：

```text
algorithms/providers/
├─ topic_group_a/
├─ topic_group_b/
└─ demo_model/
```

## `shared`

该目录解决“前端传什么、后端收什么、算法吃什么、结果回什么”这类接口混乱问题。

建议优先定义：

- 图层描述协议
- 任务提交协议
- 时间范围协议
- 空间查询协议
- 标准结果元数据协议

## `infra`

本目录不放业务代码，只放运行环境配置：

- 前端镜像
- 后端镜像
- Redis/PostGIS/MinIO 依赖编排
- Nginx 代理与静态资源转发

后续如果引入 TiTiler、Martin、Flower，也建议放在这里统一管理。

## 首批落地建议

建议按以下顺序在 `Code` 内继续实现：

1. `frontend` 初始化 Vue 3 工程
2. `backend` 初始化 FastAPI 工程
3. `shared/contracts` 先定义任务与图层协议
4. `algorithms/providers/demo_model` 放一个演示算法闭环
5. `infra/compose` 补一个最小开发环境编排

## 不建议的做法

- 不要把所有 Python 代码都堆到一个目录
- 不要让前端直接依赖算法细节
- 不要让每个课题组自定义一套输入输出格式
- 不要把 GEE、数据库、瓦片服务逻辑混写在同一个模块里

这样规划后，`Code` 目录既适合先做演示版，也能平滑扩展到后续正式版本。
