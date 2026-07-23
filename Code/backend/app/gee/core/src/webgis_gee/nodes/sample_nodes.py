from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from webgis_gee.domain.enums import PortKind
from webgis_gee.domain.enums import RunStatus
from webgis_gee.domain.models import NodeExecutionResult, NodeSpec, PortSpec
from webgis_gee.nodes.base import BaseNode


class SampleInputNode(BaseNode):
    node_type = "sample_input"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="sample_input",
            node_type=SampleInputNode.node_type,
            output_ports=[PortSpec(name="value", kind=PortKind.VALUE)],
            params={"default": 0},
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        value = inputs.get("value", self.spec.params.get("default"))
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={"value": value},
        )


class SampleComputeNode(BaseNode):
    node_type = "sample_compute"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="sample_compute",
            node_type=SampleComputeNode.node_type,
            input_ports=[PortSpec(name="a", kind=PortKind.VALUE)],
            output_ports=[PortSpec(name="result", kind=PortKind.VALUE)],
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        a = inputs.get("a", 0)
        result = a * 2
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={"result": result},
        )


class SampleOutputNode(BaseNode):
    node_type = "sample_output"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="sample_output",
            node_type=SampleOutputNode.node_type,
            input_ports=[PortSpec(name="value", kind=PortKind.VALUE)],
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        value = inputs.get("value")
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={"final": value},
        )


class LiteralNode(BaseNode):
    node_type = "literal"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="literal",
            node_type=LiteralNode.node_type,
            output_ports=[PortSpec(name="value", kind=PortKind.VALUE)],
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={"value": self.spec.params.get("value")},
        )


class IdentityNode(BaseNode):
    node_type = "identity"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="identity",
            node_type=IdentityNode.node_type,
            input_ports=[PortSpec(name="value", kind=PortKind.VALUE)],
            output_ports=[PortSpec(name="value", kind=PortKind.VALUE)],
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={"value": inputs.get("value")},
        )


class BatchMapNode(BaseNode):
    node_type = "batch_map"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="batch_map",
            node_type=BatchMapNode.node_type,
            input_ports=[PortSpec(name="items", kind=PortKind.VALUE)],
            output_ports=[PortSpec(name="batch_items", kind=PortKind.VALUE)],
            batch_enabled=True,
            parameter_aliases={"map_key": "item_key"},
            params={
                "item_key": "item",
                "extra_params": {},
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        items = inputs.get("items")
        if items is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing items input for batch_map"],
            )
        if not isinstance(items, list):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_map items input must be a list"],
            )

        item_key = str(inputs.get("item_key", self.spec.params.get("item_key", "item")))
        extra_params = inputs.get(
            "extra_params", self.spec.params.get("extra_params", {})
        )
        if not isinstance(extra_params, dict):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_map extra_params must be an object"],
            )

        batch_items = [
            {
                "index": index,
                "item": item,
                "payload": self._build_payload(
                    item=item, item_key=item_key, extra_params=extra_params
                ),
            }
            for index, item in enumerate(items)
        ]
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={"batch_items": batch_items},
        )

    @staticmethod
    def _build_payload(
        *,
        item: Any,
        item_key: str,
        extra_params: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(item, dict):
            return {**item, **extra_params}
        return {item_key: item, **extra_params}


class BatchSplitByTimeNode(BaseNode):
    node_type = "batch_split_by_time"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="batch_split_by_time",
            node_type=BatchSplitByTimeNode.node_type,
            output_ports=[PortSpec(name="batch_items", kind=PortKind.VALUE)],
            batch_enabled=True,
            parameter_aliases={"window_key": "item_key"},
            params={
                "start_date": None,
                "end_date": None,
                "step_unit": "day",
                "step_size": 1,
                "item_key": "time_window",
                "extra_params": {},
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        start_raw = inputs.get("start_date", self.spec.params.get("start_date"))
        end_raw = inputs.get("end_date", self.spec.params.get("end_date"))
        if not start_raw or not end_raw:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_split_by_time requires start_date and end_date"],
            )

        try:
            start_date = _parse_iso_date(str(start_raw))
            end_date = _parse_iso_date(str(end_raw))
        except ValueError as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[f"batch_split_by_time invalid date: {exc}"],
            )

        if end_date < start_date:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[
                    "batch_split_by_time end_date must be on or after start_date"
                ],
            )

        step_unit = str(
            inputs.get("step_unit", self.spec.params.get("step_unit", "day"))
        ).lower()
        step_size = inputs.get("step_size", self.spec.params.get("step_size", 1))
        if not isinstance(step_size, int) or step_size <= 0:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_split_by_time step_size must be a positive integer"],
            )
        if step_unit not in {"day", "month"}:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_split_by_time step_unit must be 'day' or 'month'"],
            )

        item_key = str(
            inputs.get("item_key", self.spec.params.get("item_key", "time_window"))
        )
        extra_params = inputs.get(
            "extra_params", self.spec.params.get("extra_params", {})
        )
        if not isinstance(extra_params, dict):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_split_by_time extra_params must be an object"],
            )

        windows = _build_time_windows(
            start_date=start_date,
            end_date=end_date,
            step_unit=step_unit,
            step_size=step_size,
        )
        batch_items = [
            {
                "index": index,
                "item": window,
                "payload": {
                    item_key: window,
                    "start_date": window["start_date"],
                    "end_date": window["end_date"],
                    **extra_params,
                },
            }
            for index, window in enumerate(windows)
        ]
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={"batch_items": batch_items},
        )


class BatchSplitByRegionsNode(BaseNode):
    node_type = "batch_split_by_regions"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="batch_split_by_regions",
            node_type=BatchSplitByRegionsNode.node_type,
            input_ports=[PortSpec(name="regions", kind=PortKind.VALUE)],
            output_ports=[PortSpec(name="batch_items", kind=PortKind.VALUE)],
            batch_enabled=True,
            params={
                "region_key": "region",
                "region_id_key": "region_id",
                "extra_params": {},
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        regions = inputs.get("regions")
        if regions is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing regions input for batch_split_by_regions"],
            )
        if not isinstance(regions, list):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_split_by_regions regions input must be a list"],
            )

        region_key = str(
            inputs.get("region_key", self.spec.params.get("region_key", "region"))
        )
        region_id_key = str(
            inputs.get(
                "region_id_key", self.spec.params.get("region_id_key", "region_id")
            )
        )
        extra_params = inputs.get(
            "extra_params", self.spec.params.get("extra_params", {})
        )
        if not isinstance(extra_params, dict):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_split_by_regions extra_params must be an object"],
            )

        batch_items = [
            {
                "index": index,
                "item": region,
                "payload": self._build_region_payload(
                    region=region,
                    index=index,
                    region_key=region_key,
                    region_id_key=region_id_key,
                    extra_params=extra_params,
                ),
            }
            for index, region in enumerate(regions)
        ]
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={"batch_items": batch_items},
        )

    @staticmethod
    def _build_region_payload(
        *,
        region: Any,
        index: int,
        region_key: str,
        region_id_key: str,
        extra_params: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(region, dict):
            region_id = region.get(region_id_key, index)
            return {
                region_key: region,
                region_id_key: region_id,
                **region,
                **extra_params,
            }
        return {
            region_key: region,
            region_id_key: index,
            **extra_params,
        }


class BatchCollectNode(BaseNode):
    node_type = "batch_collect"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="batch_collect",
            node_type=BatchCollectNode.node_type,
            input_ports=[PortSpec(name="batch_items", kind=PortKind.VALUE)],
            output_ports=[
                PortSpec(name="collected_items", kind=PortKind.VALUE),
                PortSpec(name="item_count", kind=PortKind.VALUE),
            ],
            params={
                "collect_field": None,
                "flatten": False,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        batch_items = inputs.get("batch_items")
        if batch_items is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing batch_items input for batch_collect"],
            )
        if not isinstance(batch_items, list):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_collect batch_items input must be a list"],
            )

        collect_field = inputs.get(
            "collect_field", self.spec.params.get("collect_field")
        )
        flatten = bool(inputs.get("flatten", self.spec.params.get("flatten", False)))

        try:
            collected_items = self._collect_items(
                batch_items=batch_items,
                collect_field=collect_field,
                flatten=flatten,
            )
        except ValueError as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[str(exc)],
            )

        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={
                "collected_items": collected_items,
                "item_count": len(collected_items),
            },
        )

    @staticmethod
    def _collect_items(
        *,
        batch_items: list[Any],
        collect_field: Any,
        flatten: bool,
    ) -> list[Any]:
        if collect_field is None:
            values = list(batch_items)
        else:
            values = []
            for index, item in enumerate(batch_items):
                if not isinstance(item, dict):
                    raise ValueError(
                        "batch_collect collect_field requires dict items in batch_items"
                    )
                if collect_field not in item:
                    raise ValueError(
                        f"batch_collect missing field {collect_field!r} in item at index {index}"
                    )
                values.append(item[collect_field])

        if not flatten:
            return values

        flattened: list[Any] = []
        for value in values:
            if isinstance(value, list):
                flattened.extend(value)
            else:
                flattened.append(value)
        return flattened


class BatchFlattenNode(BaseNode):
    node_type = "batch_flatten"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="batch_flatten",
            node_type=BatchFlattenNode.node_type,
            input_ports=[PortSpec(name="items", kind=PortKind.VALUE)],
            output_ports=[
                PortSpec(name="flattened_items", kind=PortKind.VALUE),
                PortSpec(name="item_count", kind=PortKind.VALUE),
            ],
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        items = inputs.get("items")
        if items is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing items input for batch_flatten"],
            )
        if not isinstance(items, list):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_flatten items input must be a list"],
            )

        flattened: list[Any] = []
        for item in items:
            if isinstance(item, list):
                flattened.extend(item)
            else:
                flattened.append(item)

        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={
                "flattened_items": flattened,
                "item_count": len(flattened),
            },
        )


class BatchFilterNode(BaseNode):
    node_type = "batch_filter"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="batch_filter",
            node_type=BatchFilterNode.node_type,
            input_ports=[PortSpec(name="items", kind=PortKind.VALUE)],
            output_ports=[
                PortSpec(name="filtered_items", kind=PortKind.VALUE),
                PortSpec(name="item_count", kind=PortKind.VALUE),
            ],
            params={
                "field": None,
                "operator": "eq",
                "value": None,
                "indices": None,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        items = inputs.get("items")
        if items is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing items input for batch_filter"],
            )
        if not isinstance(items, list):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["batch_filter items input must be a list"],
            )

        field = inputs.get("field", self.spec.params.get("field"))
        operator = str(
            inputs.get("operator", self.spec.params.get("operator", "eq"))
        ).lower()
        value = inputs.get("value", self.spec.params.get("value"))
        indices = inputs.get("indices", self.spec.params.get("indices"))

        try:
            filtered_items = self._filter_items(
                items=items,
                field=field,
                operator=operator,
                value=value,
                indices=indices,
            )
        except ValueError as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[str(exc)],
            )

        return NodeExecutionResult(
            node_id=self.spec.node_id,
            outputs={
                "filtered_items": filtered_items,
                "item_count": len(filtered_items),
            },
        )

    @classmethod
    def _filter_items(
        cls,
        *,
        items: list[Any],
        field: Any,
        operator: str,
        value: Any,
        indices: Any,
    ) -> list[Any]:
        allowed_operators = {
            "eq",
            "ne",
            "gt",
            "gte",
            "lt",
            "lte",
            "in",
            "not_in",
            "contains",
            "truthy",
            "falsy",
        }
        if operator not in allowed_operators:
            raise ValueError(
                "batch_filter operator must be one of "
                "'eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'not_in', 'contains', 'truthy', 'falsy'"
            )

        index_set: set[int] | None = None
        if indices is not None:
            if not isinstance(indices, list) or any(
                not isinstance(index, int) for index in indices
            ):
                raise ValueError("batch_filter indices must be a list of integers")
            index_set = set(indices)

        has_value_filter = (
            field is not None or value is not None or operator in {"truthy", "falsy"}
        )
        if index_set is None and not has_value_filter:
            raise ValueError(
                "batch_filter requires indices or a field/value filter condition"
            )

        filtered_items: list[Any] = []
        for index, item in enumerate(items):
            if index_set is not None and index not in index_set:
                continue
            if has_value_filter:
                candidate = cls._resolve_candidate(item=item, field=field, index=index)
                if not cls._matches(
                    candidate=candidate, operator=operator, value=value
                ):
                    continue
            filtered_items.append(item)
        return filtered_items

    @staticmethod
    def _resolve_candidate(*, item: Any, field: Any, index: int) -> Any:
        if field is None:
            return item
        if not isinstance(field, str) or not field:
            raise ValueError("batch_filter field must be a non-empty string")
        if not isinstance(item, dict):
            raise ValueError("batch_filter field filtering requires dict items")
        if field not in item:
            raise ValueError(
                f"batch_filter missing field {field!r} in item at index {index}"
            )
        return item[field]

    @staticmethod
    def _matches(*, candidate: Any, operator: str, value: Any) -> bool:
        if operator == "eq":
            return candidate == value
        if operator == "ne":
            return candidate != value
        if operator == "truthy":
            return bool(candidate)
        if operator == "falsy":
            return not bool(candidate)

        try:
            if operator == "gt":
                return candidate > value
            if operator == "gte":
                return candidate >= value
            if operator == "lt":
                return candidate < value
            if operator == "lte":
                return candidate <= value
            if operator == "in":
                return candidate in value
            if operator == "not_in":
                return candidate not in value
            if operator == "contains":
                return value in candidate
        except TypeError as exc:
            raise ValueError(
                f"batch_filter operator {operator!r} cannot compare provided values"
            ) from exc

        raise ValueError(f"batch_filter unsupported operator {operator!r}")


def _parse_iso_date(value: str) -> date:
    return datetime.fromisoformat(value).date()


def _build_time_windows(
    *,
    start_date: date,
    end_date: date,
    step_unit: str,
    step_size: int,
) -> list[dict[str, str]]:
    windows: list[dict[str, str]] = []
    cursor = start_date
    while cursor <= end_date:
        next_cursor = _advance_date(cursor, step_unit=step_unit, step_size=step_size)
        window_end = min(end_date, next_cursor - timedelta(days=1))
        windows.append(
            {
                "start_date": cursor.isoformat(),
                "end_date": window_end.isoformat(),
            }
        )
        cursor = window_end + timedelta(days=1)
    return windows


def _advance_date(source: date, *, step_unit: str, step_size: int) -> date:
    if step_unit == "day":
        return source + timedelta(days=step_size)
    return _add_months(source, months=step_size)


def _add_months(source: date, *, months: int) -> date:
    month_index = source.month - 1 + months
    year = source.year + month_index // 12
    month = month_index % 12 + 1
    day = min(source.day, monthrange(year, month)[1])
    return date(year, month, day)
