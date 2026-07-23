from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from workflow.panel_schema import (
    WorkflowInputPanelSchema,
    WorkflowPanelField,
    build_workflow_input_panel_schema,
)


_SECTION_METADATA = (
    (
        "datasource_selection",
        "数据源输入",
        "用于填写文件、目录、MAT 或其他外部数据输入。",
    ),
    ("algorithm_params", "算法参数", "用于填写算法模式、数值参数和实验开关。"),
    ("request", "请求对象", "用于说明 workflow 直接读取的请求级对象。"),
)

_FIELD_LABEL_OVERRIDES = {
    "input_dir": "输入目录",
    "input_mat": "输入 MAT 文件",
    "lin_pix_mat": "线性像元 MAT",
    "omega_fixed_mat": "OMEGA 固定场 MAT",
    "exp0_calib_mat": "Exp0 标定 MAT",
    "dh_mat": "DH 辅助 MAT",
    "site_info_csv": "站点信息 CSV",
    "smap_grid_mat": "SMAP 网格 MAT",
    "landcover_mat": "地表覆盖 MAT",
    "climate_mat": "气候分区 MAT",
    "network_map_csv": "网络映射 CSV",
    "ndvi_clim_dir": "NDVI 气候态目录",
    "ndvi_clim_folder": "NDVI 气候态子目录",
    "algorithm_params": "算法参数对象",
    "datasource_selection": "数据源选择对象",
    "time_range": "时间范围",
    "region": "区域对象",
    "tags": "请求标签",
    "output_spec_extra": "输出扩展参数",
    "mode": "反演模式",
    "freq_ghz": "频率 GHz",
    "pixel_chunk_size": "像元分块大小",
    "write_daily_files": "输出日文件",
    "exp_mode": "实验模式",
    "temp_scheme": "温度方案",
    "orbit_mode": "轨道模式",
    "band_ids": "波段列表",
    "overlap_option": "重叠处理策略",
    "spatial_mode": "空间模式",
    "gdal_bin": "GDAL 可执行目录",
    "execute_commands": "直接执行命令",
    "source_type": "站点数据源类型",
    "emit_validation_products": "输出验证产品",
    "validation_start": "验证开始时间",
    "validation_end": "验证结束时间",
    "validation_min_valid_days": "最少有效天数",
    "validation_hour": "验证时刻",
    "validation_network_groups": "网络分组",
    "validation_min_sm": "最小土壤湿度",
    "validation_max_sm": "最大土壤湿度",
    "emit_quality_products": "输出质量产品",
    "sg_step_days": "SG 步长天数",
    "daily_step_days": "日步长天数",
    "gap_threshold_days": "插值断档阈值天数",
    "sg_polyorder": "SG 多项式阶数",
    "sg_window_length": "SG 窗口长度",
    "lin_pix": "线性像元索引",
    "lin_pix_varname": "线性像元变量名",
    "tb_source": "亮温来源",
    "sm_source": "土壤湿度来源",
    "ndvi_mode": "NDVI 模式",
    "sf_mode": "地表冻结模式",
}

_FIELD_PLACEHOLDERS = {
    "input_dir": "D:\\data\\input\\",
    "input_mat": "D:\\data\\bundle\\timeseries_bundle.mat",
    "omega_fixed_mat": "D:\\data\\omega\\omega_fixed.mat",
    "exp0_calib_mat": "D:\\data\\omega\\exp0_calib.mat",
    "site_info_csv": "D:\\data\\station\\site_info.csv",
    "algorithm_params": '{"mode": "dh"}',
    "datasource_selection": '{"input_dir": "D:/data/input"}',
    "time_range": '{"start": "2020-01-01T00:00:00Z", "end": "2020-01-31T23:59:59Z"}',
    "region": '{"kind": "bbox", "value": {"xmin": 70, "ymin": 15, "xmax": 140, "ymax": 55}}',
    "mode": "dh / ddca / omega",
    "exp_mode": "Exp0 / Exp1A / Exp1B / Exp2",
    "orbit_mode": "MWRID / MWRIA / Both",
}

_FIELD_EXAMPLE_OVERRIDES = {
    "input_dir": "D:\\Workspace\\data\\ndvi_daily",
    "input_mat": "D:\\Workspace\\data\\retrieval\\timeseries_bundle.mat",
    "lin_pix_mat": "D:\\Workspace\\data\\lin_pix\\lin_pix.mat",
    "omega_fixed_mat": "D:\\Workspace\\data\\omega\\omega_fixed.mat",
    "exp_mode": "Exp2",
    "orbit_mode": "Both",
    "execute_commands": "false",
    "write_daily_files": "true",
    "freq_ghz": "6.925",
    "pixel_chunk_size": "5000",
    "validation_hour": "6",
}


@dataclass(frozen=True, slots=True)
class WorkflowPanelUiField:
    key: str
    section: str
    label: str
    required: bool
    control_type: str
    description: str
    placeholder: str | None = None
    example_value: str | None = None
    value_kind: str = "scalar"
    consumers: tuple[str, ...] = ()
    entry_names: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    format_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowPanelUiSection:
    key: str
    title: str
    description: str
    fields: tuple[WorkflowPanelUiField, ...]


@dataclass(frozen=True, slots=True)
class WorkflowInputPanelUiSchema:
    workflow_id: str
    workflow_name: str | None
    sections: tuple[WorkflowPanelUiSection, ...]
    notes: tuple[str, ...] = ()


def build_workflow_input_panel_ui_schema(value: object) -> WorkflowInputPanelUiSchema:
    schema = build_workflow_input_panel_schema(value)
    return enhance_panel_schema_with_ui_metadata(schema)


def enhance_panel_schema_with_ui_metadata(
    schema: WorkflowInputPanelSchema,
) -> WorkflowInputPanelUiSchema:
    section_fields = {
        "datasource_selection": schema.datasource_fields,
        "algorithm_params": schema.algorithm_param_fields,
        "request": schema.request_fields,
    }
    sections: list[WorkflowPanelUiSection] = []
    for key, title, description in _SECTION_METADATA:
        fields = section_fields[key]
        ui_fields = tuple(_build_ui_field(field) for field in fields)
        sections.append(
            WorkflowPanelUiSection(
                key=key,
                title=title,
                description=description,
                fields=ui_fields,
            )
        )

    return WorkflowInputPanelUiSchema(
        workflow_id=schema.workflow_id,
        workflow_name=schema.workflow_name,
        sections=tuple(sections),
        notes=schema.notes,
    )


def _build_ui_field(field: WorkflowPanelField) -> WorkflowPanelUiField:
    label = _field_label(field.key)
    description = _field_description(field)
    control_type = _control_type(
        field.section,
        field.key,
        field.allowed_values,
        field.source_types,
        field.format_hints,
    )
    placeholder = _placeholder(field.key)
    example_value = _example_value(field.key, field.entry_names, field.allowed_values)
    return WorkflowPanelUiField(
        key=field.key,
        section=field.section,
        label=label,
        required=field.required,
        control_type=control_type,
        description=description,
        placeholder=placeholder,
        example_value=example_value,
        value_kind=field.value_kind,
        consumers=field.consumers,
        entry_names=field.entry_names,
        allowed_values=field.allowed_values,
        source_types=field.source_types,
        format_hints=field.format_hints,
    )


@lru_cache(maxsize=None)
def _field_label(key: str) -> str:
    label = _FIELD_LABEL_OVERRIDES.get(key)
    if label is not None:
        return label
    return key.replace("_", " ").title()


def _field_description(field: WorkflowPanelField) -> str:
    if field.description:
        return field.description
    if field.section == "datasource_selection":
        return "Workflow 外部数据输入。"
    if field.section == "algorithm_params":
        return "Workflow 算法参数。"
    return "Workflow 请求级输入。"


@lru_cache(maxsize=None)
def _control_type(
    section: str,
    key: str,
    allowed_values: tuple[str, ...],
    source_types: tuple[str, ...],
    format_hints: tuple[str, ...],
) -> str:
    if section == "request":
        if key == "time_range":
            return "datetime_range"
        if key == "region":
            return "region_editor"
        return "json_editor"
    if allowed_values:
        return "select"
    if section == "datasource_selection":
        if key.endswith("_dir") or "directory" in source_types:
            return "directory_picker"
        if key.endswith("_csv") or "csv" in format_hints:
            return "file_picker"
        if key.endswith("_mat") or "mat" in format_hints:
            return "file_picker"
        return "path_input"
    if key.startswith("emit_") or key in {"execute_commands", "write_daily_files"}:
        return "switch"
    if key.endswith("_groups") or key == "band_ids":
        return "json_editor"
    if key.endswith("_start") or key.endswith("_end"):
        return "datetime_input"
    if any(
        token in key for token in ("days", "hour", "size", "ghz", "length", "order")
    ):
        return "number_input"
    return "text_input"


@lru_cache(maxsize=None)
def _placeholder(key: str) -> str | None:
    return _FIELD_PLACEHOLDERS.get(key)


@lru_cache(maxsize=None)
def _example_value(
    key: str, entry_names: tuple[str, ...], allowed_values: tuple[str, ...]
) -> str | None:
    if key == "mode":
        return "omega" if "omega_block" in entry_names else "dh"
    example = _FIELD_EXAMPLE_OVERRIDES.get(key)
    if example is not None:
        return example
    if allowed_values:
        return allowed_values[0]
    return None
