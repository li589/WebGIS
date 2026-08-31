"""NCEP NOMADS GRIB2 下载节点（``download/nomads_grib_download``）。

主路径 herbie（模型/产品/起报时/成员/时效/字段子集参数化），回退 NOMADS
直连 HTTP（完整 GRIB2 或 filter 直链，复用共享续传工具）。
产物默认落 ``ctx.workspace/data_access/nomads/``。
"""

from __future__ import annotations

from modules.base import BaseModule
from modules.download_nodes import (
    _make_byte_stream_progress_cb,
    _make_multi_file_progress_cb,
    _make_skip_complete_emit,
    _store_path_manifest,
)
from modules.registry import register_module_decorator
from workflow.schemas import NodeExecutionContext, PortSpec

_VALID_USE = frozenset({"auto", "herbie", "legacy"})


@register_module_decorator(
    name="nomads_grib_download", template_overrides={"phase": "download"}
)
class NomadsGribDownloadModule(BaseModule):
    name = "nomads_grib_download"
    description = (
        "NCEP NOMADS GRIB2 下载（GFS/GEFS/GDAS/NAM 等）：主路径 herbie 参数化"
        "检索与字段子集物化，回退 NOMADS 直连直链（Range 续传）。"
    )
    input_ports = [
        PortSpec(
            name="datasource_selection",
            kind="config",
            data_class="dict",
            required=False,
        ),
        PortSpec(
            name="algorithm_params", kind="config", data_class="dict", required=False
        ),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params: dict[str, object] = {
        "date": "",
        "model": "gfs",
        "product": "",
        "fxx": 0,
        "search_string": "",
        "members": None,
        "target_dir": "",
        "use": "auto",
        "legacy_url": "",
        "overwrite": False,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from ingest.nomads_download import download_nomads_grib

        ds = dict(inputs.get("datasource_selection", {}))
        ap = dict(inputs.get("algorithm_params", {}))
        resolved = {**self.default_params, **params, **ap, **ds}

        date = str(resolved.get("date") or "").strip()
        if not date:
            raise ValueError("nomads_grib_download requires date (or 'latest')")

        use = str(resolved.get("use") or "auto").strip().lower()
        if use not in _VALID_USE:
            raise ValueError(f"nomads_grib_download: invalid use={use!r}")

        members_raw = resolved.get("members")
        members: list[str] | None = None
        if isinstance(members_raw, (list, tuple)):
            members = [str(m) for m in members_raw]
        elif isinstance(members_raw, str) and members_raw.strip():
            members = [p.strip() for p in members_raw.split(",") if p.strip()]

        target_dir = str(resolved.get("target_dir") or "").strip()
        if not target_dir:
            target_dir = str(ctx.workspace / "data_access" / "nomads")

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "nomads_grib_download",
                f"NOMADS GRIB2 download: model={resolved.get('model')} "
                f"date={date} use={use} -> {target_dir}",
            )

        _multi_cb = _make_multi_file_progress_cb(
            ctx.logger_adapter, "nomads_grib_download"
        )
        _byte_cb = (
            _make_byte_stream_progress_cb(
                ctx.logger_adapter,
                "nomads_grib_download",
                item_name="grib2",
            )
            if use in {"legacy", "auto"}
            else None
        )

        result = download_nomads_grib(
            date,
            str(resolved.get("model") or "gfs"),
            product=str(resolved.get("product") or ""),
            fxx=resolved.get("fxx", 0),  # type: ignore[arg-type]
            search_string=str(resolved.get("search_string") or ""),
            members=members,
            target_dir=target_dir,
            use=use,
            legacy_url=str(resolved.get("legacy_url") or ""),
            overwrite=bool(resolved.get("overwrite")),
            progress_callback=_multi_cb,
            byte_stream_callback=_byte_cb,
        )

        if ctx.logger_adapter is not None:
            total = result.downloaded + result.skipped + result.failed
            if total == 0 or (
                result.skipped >= total and result.downloaded == 0 and total > 0
            ):
                _make_skip_complete_emit(
                    ctx.logger_adapter,
                    "nomads_grib_download",
                    total=max(total, result.skipped),
                    skipped=result.skipped,
                    downloaded=result.downloaded,
                )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "nomads_grib_download",
                f"Downloaded: {result.downloaded} failed={result.failed} "
                f"bytes={result.downloaded_bytes}",
            )

        if result.failed > 0:
            error_summary = "; ".join(result.errors[:5]) if result.errors else "unknown"
            raise RuntimeError(
                f"nomads_grib_download completed with {result.failed} failures: "
                f"{error_summary}"
            )

        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=result.target_dir,
            product_type="nomads_grib_dir",
            extra={
                "model": result.model,
                "date": result.date,
                "use": result.use,
                "downloaded": result.downloaded,
                "failed": result.failed,
                "downloaded_bytes": result.downloaded_bytes,
                "files": [f.path for f in result.files],
            },
        )
