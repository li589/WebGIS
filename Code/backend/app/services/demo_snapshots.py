from __future__ import annotations

import math
from typing import Any

from shared.contracts.api_contracts import (
    DemoAvailabilityState,
    DemoDataStateMode,
    DemoFieldAliasMap,
    DemoLayerSnapshot,
    DemoLayerSnapshotsResponse,
)

DEFAULT_OBSERVATION_FIELD_ALIASES = ["time", "timestamp", "forecast_time"]

DEMO_LAYER_CATALOG: list[dict[str, Any]] = [
    {
        "id": "wind-field",
        "name": "风场",
        "category": "气象场",
        "metric_label": "核心指标",
        "metric_unit": "m/s",
        "metric_precision": 1,
        "update_label": "每 10 分钟刷新",
        "source_label": "ECMWF + 本地处理",
        "accent_color": "#67d4ff",
        "accent_glow": "rgba(103, 212, 255, 0.34)",
        "chip_tone": "rgba(103, 212, 255, 0.18)",
        "data_state": {
            "mode": DemoDataStateMode.mixed,
            "label": "Demo 驱动",
            "empty_label": "待接入真实风场格点后替换",
        },
        "field_aliases": DemoFieldAliasMap(
            metric_value=["speed", "wind_speed", "value"],
            hotspot_value=["station_value", "grid_value", "speed"],
            observation_time=DEFAULT_OBSERVATION_FIELD_ALIASES,
            status_label=["status", "quality_flag"],
        ),
        "hotspot_templates": [
            {"id": "gzs", "name": "广州南沙", "lng": 113.6, "lat": 22.77, "base_value": 15.6, "amplitude": 1.4},
            {"id": "szb", "name": "深圳东部", "lng": 114.35, "lat": 22.62, "base_value": 14.9, "amplitude": 1.1},
            {"id": "zjz", "name": "珠江口", "lng": 113.82, "lat": 22.34, "base_value": 17.2, "amplitude": 1.6},
        ],
        "time_bands": [
            {
                "start_hour": 0,
                "end_hour": 6,
                "metric_base": 13.9,
                "hotspot_drift": -0.5,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "夜间海陆风维持，沿海风速偏强",
                "summary": "展示近地表风速、风向与局部梯度，适合演示沿海风场框架。",
                "status_label": "Demo 更新",
                "confidence_label": "置信度 92%",
            },
            {
                "start_hour": 6,
                "end_hour": 12,
                "metric_base": 14.8,
                "hotspot_drift": 0.2,
                "availability_state": DemoAvailabilityState.ready,
                "trend_label": "西南风增强 12%",
                "summary": "展示近地表风速、风向与局部梯度，上午时段可观察局地增强。",
                "status_label": "Demo 更新",
                "confidence_label": "置信度 93%",
            },
            {
                "start_hour": 12,
                "end_hour": 18,
                "metric_base": 16.1,
                "hotspot_drift": 0.9,
                "availability_state": DemoAvailabilityState.ready,
                "trend_label": "午后海风推进，沿岸梯度扩大",
                "summary": "展示近地表风速、风向与局部梯度，午后更适合演示高值带迁移。",
                "status_label": "Demo 峰值",
                "confidence_label": "置信度 94%",
            },
            {
                "start_hour": 18,
                "end_hour": 24,
                "metric_base": 14.4,
                "hotspot_drift": -0.2,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "傍晚风速回落，通道逐步收敛",
                "summary": "展示近地表风速、风向与局部梯度，傍晚阶段适合演示回落过程。",
                "status_label": "Demo 回落",
                "confidence_label": "置信度 92%",
            },
        ],
    },
    {
        "id": "precipitation",
        "name": "降水",
        "category": "灾害监测",
        "metric_label": "峰值降水",
        "metric_unit": "mm/h",
        "metric_precision": 0,
        "update_label": "每小时滚动",
        "source_label": "卫星融合降水",
        "accent_color": "#72ffcf",
        "accent_glow": "rgba(114, 255, 207, 0.3)",
        "chip_tone": "rgba(114, 255, 207, 0.16)",
        "data_state": {
            "mode": DemoDataStateMode.demo,
            "label": "Demo 时段样例",
            "empty_label": "待接入实况降水产品后替换",
        },
        "field_aliases": DemoFieldAliasMap(
            metric_value=["precip_rate", "rain_rate", "value"],
            hotspot_value=["site_rain", "pixel_rain", "rain_rate"],
            observation_time=DEFAULT_OBSERVATION_FIELD_ALIASES,
            status_label=["warning_level", "status"],
        ),
        "hotspot_templates": [
            {"id": "qys", "name": "清远山地", "lng": 113.15, "lat": 24.05, "base_value": 42, "amplitude": 8},
            {"id": "dgx", "name": "东莞西部", "lng": 113.71, "lat": 23.02, "base_value": 55, "amplitude": 10},
            {"id": "hzz", "name": "惠州中部", "lng": 114.53, "lat": 23.14, "base_value": 38, "amplitude": 6},
        ],
        "time_bands": [
            {
                "start_hour": 0,
                "end_hour": 6,
                "metric_base": 28,
                "hotspot_drift": -6,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "夜间对流减弱，强降水范围收缩",
                "summary": "展示小时降水强度与强对流核心区，夜间以残余回波为主。",
                "status_label": "监测中",
                "confidence_label": "置信度 86%",
            },
            {
                "start_hour": 6,
                "end_hour": 12,
                "metric_base": 41,
                "hotspot_drift": -1,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "晨间回波重组，山区率先触发",
                "summary": "展示小时降水强度与强对流核心区，上午利于演示对流初生。",
                "status_label": "短临预报",
                "confidence_label": "置信度 88%",
            },
            {
                "start_hour": 12,
                "end_hour": 18,
                "metric_base": 62,
                "hotspot_drift": 7,
                "availability_state": DemoAvailabilityState.ready,
                "trend_label": "对流带向东移动",
                "summary": "展示小时降水强度与强对流核心区，午后为 Demo 峰值时段。",
                "status_label": "强对流活跃",
                "confidence_label": "置信度 90%",
            },
            {
                "start_hour": 18,
                "end_hour": 24,
                "metric_base": 36,
                "hotspot_drift": -3,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "傍晚主雨带减弱，沿海残留回波",
                "summary": "展示小时降水强度与强对流核心区，傍晚阶段适合演示衰减过程。",
                "status_label": "回波衰减",
                "confidence_label": "置信度 87%",
            },
        ],
    },
    {
        "id": "temperature",
        "name": "温度",
        "category": "热环境",
        "metric_label": "区域均温",
        "metric_unit": "°C",
        "metric_precision": 1,
        "update_label": "每 30 分钟聚合",
        "source_label": "遥感反演 + 站点订正",
        "accent_color": "#ffb65c",
        "accent_glow": "rgba(255, 182, 92, 0.3)",
        "chip_tone": "rgba(255, 182, 92, 0.16)",
        "data_state": {
            "mode": DemoDataStateMode.mixed,
            "label": "Demo + 占位",
            "empty_label": "待接入真实热环境栅格后替换",
        },
        "field_aliases": DemoFieldAliasMap(
            metric_value=["temperature", "lst", "value"],
            hotspot_value=["site_temp", "urban_heat", "temperature"],
            observation_time=DEFAULT_OBSERVATION_FIELD_ALIASES,
            status_label=["status", "product_state"],
        ),
        "hotspot_templates": [
            {"id": "fos", "name": "佛山禅城", "lng": 113.12, "lat": 23.02, "base_value": 31.4, "amplitude": 2.2},
            {"id": "gzt", "name": "广州天河", "lng": 113.36, "lat": 23.13, "base_value": 32.3, "amplitude": 2.5},
            {"id": "szh", "name": "深圳河套", "lng": 114.05, "lat": 22.53, "base_value": 30.9, "amplitude": 1.9},
        ],
        "time_bands": [
            {
                "start_hour": 0,
                "end_hour": 6,
                "metric_base": 26.8,
                "hotspot_drift": -2.1,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "夜间热岛减弱，城区与郊区差异缩小",
                "summary": "展示地表温度与城市热岛强度，夜间可演示热岛回落阶段。",
                "status_label": "夜间回放",
                "confidence_label": "置信度 89%",
            },
            {
                "start_hour": 6,
                "end_hour": 12,
                "metric_base": 30.2,
                "hotspot_drift": -0.4,
                "availability_state": DemoAvailabilityState.ready,
                "trend_label": "日照增强，热岛逐步建立",
                "summary": "展示地表温度与城市热岛强度，上午阶段适合演示升温过程。",
                "status_label": "升温中",
                "confidence_label": "置信度 90%",
            },
            {
                "start_hour": 12,
                "end_hour": 18,
                "metric_base": 31.6,
                "hotspot_drift": 1.3,
                "availability_state": DemoAvailabilityState.ready,
                "trend_label": "城区热岛上升 1.8 °C",
                "summary": "展示地表温度与城市热岛强度，午后阶段为 Demo 主展示时段。",
                "status_label": "高温峰值",
                "confidence_label": "置信度 91%",
            },
            {
                "start_hour": 18,
                "end_hour": 24,
                "metric_base": 29.1,
                "hotspot_drift": -0.8,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "晚间降温开始，核心城区仍偏暖",
                "summary": "展示地表温度与城市热岛强度，晚间阶段适合演示滞后降温。",
                "status_label": "回落中",
                "confidence_label": "置信度 90%",
            },
        ],
    },
    {
        "id": "remote-sensing",
        "name": "遥感反演",
        "category": "遥感产品",
        "metric_label": "反演指数",
        "metric_unit": "",
        "metric_precision": 2,
        "update_label": "按日更新",
        "source_label": "Landsat / Sentinel",
        "accent_color": "#bb89ff",
        "accent_glow": "rgba(187, 137, 255, 0.3)",
        "chip_tone": "rgba(187, 137, 255, 0.16)",
        "data_state": {
            "mode": DemoDataStateMode.placeholder,
            "label": "占位协议",
            "empty_label": "待接入真实遥感反演结果",
        },
        "field_aliases": DemoFieldAliasMap(
            metric_value=["retrieval_index", "index_value", "value"],
            hotspot_value=["pixel_index", "region_index", "index_value"],
            observation_time=DEFAULT_OBSERVATION_FIELD_ALIASES,
            status_label=["inversion_state", "status"],
        ),
        "hotspot_templates": [
            {"id": "jm", "name": "江门沿海", "lng": 113.02, "lat": 21.94, "base_value": 0.79, "amplitude": 0.04},
            {"id": "zh", "name": "珠海西岸", "lng": 113.24, "lat": 22.08, "base_value": 0.77, "amplitude": 0.03},
            {"id": "zs", "name": "中山南部", "lng": 113.36, "lat": 22.35, "base_value": 0.74, "amplitude": 0.03},
        ],
        "time_bands": [
            {
                "start_hour": 0,
                "end_hour": 8,
                "metric_base": 0.74,
                "hotspot_drift": -0.02,
                "availability_state": DemoAvailabilityState.empty,
                "trend_label": "夜间阶段保留上一期反演结果",
                "summary": "展示遥感反演结果与空间差异，当前以占位协议演示字段映射。",
                "status_label": "待真实数据",
                "confidence_label": "置信度 待接入",
            },
            {
                "start_hour": 8,
                "end_hour": 16,
                "metric_base": 0.78,
                "hotspot_drift": 0.01,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "边缘区梯度明显",
                "summary": "展示遥感反演结果与空间差异，白天阶段用于演示反演产品接入框架。",
                "status_label": "协议演示",
                "confidence_label": "置信度 占位",
            },
            {
                "start_hour": 16,
                "end_hour": 24,
                "metric_base": 0.76,
                "hotspot_drift": -0.01,
                "availability_state": DemoAvailabilityState.empty,
                "trend_label": "晚间保留最近一次有效反演结果",
                "summary": "展示遥感反演结果与空间差异，当前未接入实时产品，保持 Demo 占位。",
                "status_label": "待真实数据",
                "confidence_label": "置信度 待接入",
            },
        ],
    },
    {
        "id": "lab-output",
        "name": "课题组模型输出",
        "category": "模拟结果",
        "metric_label": "综合评分",
        "metric_unit": "/ 100",
        "metric_precision": 0,
        "update_label": "按任务刷新",
        "source_label": "模型任务结果",
        "accent_color": "#ff6f91",
        "accent_glow": "rgba(255, 111, 145, 0.3)",
        "chip_tone": "rgba(255, 111, 145, 0.16)",
        "data_state": {
            "mode": DemoDataStateMode.mixed,
            "label": "Demo 任务结果",
            "empty_label": "待接入真实任务输出文件",
        },
        "field_aliases": DemoFieldAliasMap(
            metric_value=["score", "risk_score", "value"],
            hotspot_value=["cell_score", "grid_score", "risk_score"],
            observation_time=["task_time", "run_time", "forecast_time"],
            status_label=["task_status", "status"],
        ),
        "hotspot_templates": [
            {"id": "gza", "name": "广州北部", "lng": 113.31, "lat": 23.39, "base_value": 81, "amplitude": 3},
            {"id": "dga", "name": "东莞中部", "lng": 113.85, "lat": 23.0, "base_value": 79, "amplitude": 3},
            {"id": "sza", "name": "深圳西部", "lng": 113.86, "lat": 22.56, "base_value": 77, "amplitude": 2},
        ],
        "time_bands": [
            {
                "start_hour": 0,
                "end_hour": 6,
                "metric_base": 76,
                "hotspot_drift": -2,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "夜间风险带维持，模型结果趋稳",
                "summary": "展示课题组模型结果与风险分区，夜间阶段用于演示任务留存结果。",
                "status_label": "任务留存",
                "confidence_label": "置信度 89%",
            },
            {
                "start_hour": 6,
                "end_hour": 12,
                "metric_base": 80,
                "hotspot_drift": 0,
                "availability_state": DemoAvailabilityState.ready,
                "trend_label": "晨间风险带沿通道扩展",
                "summary": "展示课题组模型结果与风险分区，上午阶段用于演示新任务接力。",
                "status_label": "任务生成",
                "confidence_label": "置信度 90%",
            },
            {
                "start_hour": 12,
                "end_hour": 18,
                "metric_base": 82,
                "hotspot_drift": 2,
                "availability_state": DemoAvailabilityState.ready,
                "trend_label": "风险带持续扩展",
                "summary": "展示课题组模型结果与风险分区，午后阶段适合作为 Demo 峰值。",
                "status_label": "任务峰值",
                "confidence_label": "置信度 91%",
            },
            {
                "start_hour": 18,
                "end_hour": 24,
                "metric_base": 78,
                "hotspot_drift": -1,
                "availability_state": DemoAvailabilityState.partial,
                "trend_label": "傍晚风险区回缩，边缘区逐步减弱",
                "summary": "展示课题组模型结果与风险分区，晚间阶段适合演示结果回缩。",
                "status_label": "任务回落",
                "confidence_label": "置信度 90%",
            },
        ],
    },
]


def _normalize_hour(hour: float) -> float:
    return round(((hour % 24) + 24) % 24, 2)


def _band_matches(hour: float, band: dict[str, Any]) -> bool:
    if band["start_hour"] <= band["end_hour"]:
        return band["start_hour"] <= hour < band["end_hour"]
    return hour >= band["start_hour"] or hour < band["end_hour"]


def _format_observation_time(hour: float) -> str:
    whole_hours = math.floor(hour)
    minutes = round((hour - whole_hours) * 60)
    normalized_minutes = 0 if minutes == 60 else minutes
    normalized_hours = (whole_hours + 1) % 24 if minutes == 60 else whole_hours
    return f"{normalized_hours:02d}:{normalized_minutes:02d}"


def _resolve_band(layer: dict[str, Any], hour: float) -> dict[str, Any]:
    normalized_hour = _normalize_hour(hour)
    return next((band for band in layer["time_bands"] if _band_matches(normalized_hour, band)), layer["time_bands"][0])


def _create_raw_payload(layer: dict[str, Any], band: dict[str, Any], hour: float) -> dict[str, Any]:
    aliases = layer["field_aliases"]
    metric_alias = aliases.metric_value[int(hour) % len(aliases.metric_value)]
    status_alias = aliases.status_label[int(hour + 1) % len(aliases.status_label)]
    observation_alias = aliases.observation_time[int(hour + 2) % len(aliases.observation_time)]
    hotspot_alias = aliases.hotspot_value[int(hour + 3) % len(aliases.hotspot_value)]
    normalized_phase = math.sin((_normalize_hour(hour) / 24) * math.pi * 2 - math.pi / 2)

    if band["availability_state"] == DemoAvailabilityState.empty:
        return {
            observation_alias: _format_observation_time(hour),
            status_alias: "missing",
            "hotspots": [],
        }

    raw_payload: dict[str, Any] = {
        metric_alias: round(
            band["metric_base"] + normalized_phase * (1 if layer["metric_precision"] == 0 else 0.35),
            layer["metric_precision"],
        ),
        status_alias: band["status_label"],
        observation_alias: _format_observation_time(hour),
    }

    hotspots: list[dict[str, Any]] = []
    for index, hotspot in enumerate(layer["hotspot_templates"]):
        next_value = hotspot["base_value"] + band["hotspot_drift"] + normalized_phase * hotspot["amplitude"] * (
            0.55 + index * 0.12
        )
        next_record: dict[str, Any] = {
            "id": hotspot["id"],
            "name": hotspot["name"],
            "lng": hotspot["lng"],
            "lat": hotspot["lat"],
        }
        if not (
            band["availability_state"] == DemoAvailabilityState.partial
            and index == len(layer["hotspot_templates"]) - 1
        ):
            next_record[hotspot_alias] = round(next_value, layer["metric_precision"])
        hotspots.append(next_record)

    raw_payload["hotspots"] = hotspots
    return raw_payload


def get_demo_layer_snapshot(layer_id: str, requested_hour: float) -> DemoLayerSnapshot | None:
    layer = next((item for item in DEMO_LAYER_CATALOG if item["id"] == layer_id), None)
    if layer is None:
        return None

    normalized_hour = _normalize_hour(requested_hour)
    band = _resolve_band(layer, normalized_hour)

    return DemoLayerSnapshot(
        layer_id=layer["id"],
        display_name=layer["name"],
        category=layer["category"],
        metric_label=layer["metric_label"],
        metric_unit=layer["metric_unit"],
        metric_precision=layer["metric_precision"],
        update_label=layer["update_label"],
        source_label=layer["source_label"],
        accent_color=layer["accent_color"],
        accent_glow=layer["accent_glow"],
        chip_tone=layer["chip_tone"],
        data_state_mode=layer["data_state"]["mode"],
        data_state_label=layer["data_state"]["label"],
        empty_state_label=layer["data_state"]["empty_label"],
        availability_state=band["availability_state"],
        trend_label=band["trend_label"],
        summary=band["summary"],
        status_label=band["status_label"],
        confidence_label=band["confidence_label"],
        requested_hour=normalized_hour,
        field_aliases=layer["field_aliases"],
        raw_payload=_create_raw_payload(layer, band, normalized_hour),
    )


def list_demo_layer_snapshots(requested_hour: float) -> DemoLayerSnapshotsResponse:
    normalized_hour = _normalize_hour(requested_hour)
    return DemoLayerSnapshotsResponse(
        requested_hour=normalized_hour,
        items=[
            snapshot
            for snapshot in (get_demo_layer_snapshot(layer["id"], normalized_hour) for layer in DEMO_LAYER_CATALOG)
            if snapshot is not None
        ],
    )
