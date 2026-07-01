from __future__ import annotations

from algorithms.providers.base import ProviderExecutionPayload


def run_lab_output_algorithm(payload: ProviderExecutionPayload) -> dict:
    hour = payload.requested_hour
    metric_value = round(72 + (hour % 24) * 0.8, 1)

    return {
        "provider_key": "lab_output_external_example",
        "title": "课题组模型输出",
        "summary": "示例外部算法实现，展示如何把真实核心计算挂接到 workflow provider。",
        "metric_label": "综合风险评分",
        "metric_unit": "/ 100",
        "metric_value": metric_value,
        "status_label": "外部算法已执行",
        "confidence_label": "示例实现",
        "hotspots": [
            {"name": "广州北部", "lng": 113.42, "lat": 23.06, "risk_score": round(metric_value + 3.2, 1)},
            {"name": "东莞中部", "lng": 113.74, "lat": 22.98, "risk_score": round(metric_value + 1.1, 1)},
            {"name": "深圳西部", "lng": 113.9, "lat": 22.56, "risk_score": round(metric_value - 1.7, 1)},
        ],
        "series": [
            {"label": "00:00", "value": round(metric_value - 5.0, 1)},
            {"label": "06:00", "value": round(metric_value - 2.1, 1)},
            {"label": "12:00", "value": round(metric_value + 1.8, 1)},
            {"label": "18:00", "value": round(metric_value - 0.6, 1)},
        ],
        "diagnostics": [
            "命中示例外部算法实现。",
            f"requested_hour={hour}",
        ],
        "metadata": {
            "source": "lab_output_example_impl",
            "parameter_keys": sorted(payload.parameters.keys()),
        },
    }
