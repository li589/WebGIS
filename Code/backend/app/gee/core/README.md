# WebGIS GEE Core

`core` 目录用于承载 WebGIS 后端 `gee` 模块的所有 Python 代码。

当前阶段目标：

1. 建立可扩展的 GEE 工作流引擎骨架。
2. 定义统一的工作流、节点、账号池和存储抽象。
3. 提供可被 FastAPI 和 Celery 复用的服务层接口。

## 当前能力

1. 工作流定义模型
2. 节点注册机制
3. 基础工作流校验器
4. 最小执行服务
5. 示例节点

## 开发说明

安装依赖：

```bash
pip install -e .[dev]
```

运行测试：

```bash
pytest
```
