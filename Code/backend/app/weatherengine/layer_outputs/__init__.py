"""Layer output strategy infrastructure.

策略模式包：将 WeatherEngineService._build_map_layer_outputs 中的 6 个 if/elif 分支
抽取为可插拔策略。Sprint 3 已将全部 6 个分支迁移到具体策略类。

注册机制：导入本包时，6 个策略模块（wind_field/temperature/precipitation/humidity/
pressure/visibility）的 @register_strategy 装饰器自动执行，注册到全局 registry。
service.py 通过 get_strategy(layer_id) 查找并调用。

公共接口:
    - LayerOutputStrategy: 策略抽象基类
    - LayerOutputResult: 策略构建结果（dataclass）
    - register_strategy: 策略注册装饰器（精确匹配或前缀匹配）
    - get_strategy: 策略查找函数（精确优先，前缀按注册顺序）
    - DefaultLayerOutput: 默认占位策略（不处理，仅示例）
    - clear_registry: 清空注册表（测试用）
    - list_registered: 列出已注册策略（诊断用）
"""
from app.weatherengine.layer_outputs.base import LayerOutputResult, LayerOutputStrategy
from app.weatherengine.layer_outputs.default import DefaultLayerOutput
from app.weatherengine.layer_outputs.registry import (
    clear_registry,
    get_strategy,
    list_registered,
    register_strategy,
)

# 导入具体策略模块以触发 @register_strategy 装饰器执行（side-effect imports）
from app.weatherengine.layer_outputs import (  # noqa: F401
    humidity,
    precipitation,
    pressure,
    temperature,
    visibility,
    wind_field,
)

__all__ = [
    "LayerOutputStrategy",
    "LayerOutputResult",
    "DefaultLayerOutput",
    "register_strategy",
    "get_strategy",
    "clear_registry",
    "list_registered",
]