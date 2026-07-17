"""Layer output strategy infrastructure.

策略模式基础设施包：将 WeatherEngineService._build_map_layer_outputs 中的 if/elif 分支
抽取为可插拔策略。Sprint 2.3 仅引入基础设施，不迁移具体分支；具体分支迁移留到 Sprint 3。

无行为变更约束：当前 registry 为空（DefaultLayerOutput 不注册），service.py 始终
fallback 到原 if/elif 链。Sprint 3 起逐个迁移分支到策略类。

公共接口:
    - LayerOutputStrategy: 策略抽象基类
    - register_strategy: 策略注册装饰器（精确匹配或前缀匹配）
    - get_strategy: 策略查找函数（精确优先，前缀按注册顺序）
    - DefaultLayerOutput: 默认占位策略（不处理，仅示例）
    - clear_registry: 清空注册表（测试用）
    - list_registered: 列出已注册策略（诊断用）
"""
from app.weatherengine.layer_outputs.base import LayerOutputStrategy
from app.weatherengine.layer_outputs.default import DefaultLayerOutput
from app.weatherengine.layer_outputs.registry import (
    clear_registry,
    get_strategy,
    list_registered,
    register_strategy,
)

__all__ = [
    "LayerOutputStrategy",
    "DefaultLayerOutput",
    "register_strategy",
    "get_strategy",
    "clear_registry",
    "list_registered",
]