# Shared Contracts

本目录用于承载前后端共享的数据协议定义。

当前第一版协议文件：

- `api_contracts.py`

## 当前覆盖范围

- 图层目录接口 `GET /layers`
- 任务提交接口 `POST /tasks`
- 任务状态接口 `GET /tasks/{task_id}`

## 设计原则

- 字段优先使用 `snake_case`
- 前后端围绕统一的图层、时间范围、空间范围、任务状态对象协作
- 当前先用 `Pydantic` 模型作为协议单一事实来源，后续可再导出 JSON Schema 或 TypeScript 类型
