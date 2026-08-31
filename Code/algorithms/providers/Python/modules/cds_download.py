"""ECMWF CDS 数据集下载节点（``download/cds_download``）。

主路径 cdsapi（排队轮询），回退 legacy 静态直链（HttpSource 门户头语义，
复用共享续传工具）。凭据链：节点参数 > 门户 ``ecmwf_cds``（token 存个人
访问密钥）> 环境变量 ``BACKEND_CDS_API_KEY``。
"""

from __future__ import annotations

import os
from pathlib import Path

from modules.base import BaseModule
from modules.download_nodes import (
    _emit_download_progress,
    _make_byte_stream_progress_cb,
    _make_skip_complete_emit,
    _resolve_portal_entry,
    _store_path_manifest,
)
from modules.registry import register_module_decorator
from workflow.schemas import NodeExecutionContext, PortSpec

_VALID_USE = frozenset({"auto", "cdsapi", "legacy"})


def _resolve_cds_api_key(
    params_value: str, datasource_selection: dict[str, object]
) -> str:
    """节点参数 > 门户 ecmwf_cds entry > 环境变量。"""
    explicit = str(params_value or "").strip()
    if explicit:
        return explicit
    entry = _resolve_portal_entry(datasource_selection, "ecmwf_cds")
    token = str(entry.get("token") or "").strip() if entry else ""
    if token:
        return token
    return os.environ.get("BACKEND_CDS_API_KEY", "").strip()


@register_module_decorator(name="cds_download", template_overrides={"phase": "download"})
class CdsDownloadModule(BaseModule):
    name = "cds_download"
    description = (
        "ECMWF CDS 数据集下载（ERA5/ORAS5 等再分析）：主路径 cdsapi 排队轮询，"
        "回退 legacy 静态直链（Range 续传）。凭据经门户 ecmwf_cds 或 "
        "BACKEND_CDS_API_KEY 下发。"
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
        "dataset": "",
        "request": "",
        "target_dir": "",
        "use": "auto",
        "api_key": "",
        "filename": "",
        "direct_url": "",
        "force": False,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from ingest.cds_download import download_cds_dataset

        ds = dict(inputs.get("datasource_selection", {}))
        ap = dict(inputs.get("algorithm_params", {}))
        resolved = {**self.default_params, **params, **ap}

        dataset = str(resolved.get("dataset") or "").strip()
        if not dataset:
            raise ValueError("cds_download requires dataset")

        use = str(resolved.get("use") or "auto").strip().lower()
        if use not in _VALID_USE:
            raise ValueError(f"cds_download: invalid use={use!r}")

        raw_request = resolved.get("request", "")
        if isinstance(raw_request, dict):
            request: dict[str, object] | str = raw_request
        else:
            request = str(raw_request or "")

        target_dir = str(resolved.get("target_dir") or "").strip()
        if not target_dir:
            target_dir = str(ctx.workspace / "data_access" / "cds")

        api_key = _resolve_cds_api_key(str(resolved.get("api_key") or ""), ds)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "cds_download",
                f"CDS download: {dataset} (use={use}) -> {target_dir}",
            )

        target_name = str(resolved.get("filename") or "").strip() or dataset
        _byte_cb = (
            _make_byte_stream_progress_cb(
                ctx.logger_adapter, "cds_download", item_name=target_name
            )
            if use in {"legacy", "auto"}
            else None
        )

        result = download_cds_dataset(
            dataset,
            request,
            target_dir,
            api_key=api_key,
            use=use,
            filename=str(resolved.get("filename") or ""),
            direct_url=str(resolved.get("direct_url") or ""),
            force=bool(resolved.get("force")),
            progress_callback=_byte_cb,
        )

        if ctx.logger_adapter is not None:
            if result.skipped:
                _make_skip_complete_emit(
                    ctx.logger_adapter,
                    "cds_download",
                    total=1,
                    skipped=1,
                )
            elif result.downloaded_bytes > 0 and use not in {"legacy"}:
                from ingest._http_resume import format_size

                _emit_download_progress(
                    ctx.logger_adapter,
                    "cds_download",
                    1.0,
                    f"CDS 下载完成 · {format_size(result.downloaded_bytes)}",
                    {
                        "download_mode": "byte_stream",
                        "downloaded_bytes": result.downloaded_bytes,
                        "total_bytes": result.downloaded_bytes,
                        "current_item_name": Path(result.target).name,
                        "phase": "complete",
                    },
                )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "cds_download",
                f"CDS download done: {Path(result.target).name} "
                f"skipped={result.skipped}",
            )

        if not result.success:
            raise RuntimeError(
                f"cds_download failed: {'; '.join(result.errors[:5]) or 'unknown'}"
            )

        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=result.target,
            product_type="cds_file",
            extra={
                "dataset": dataset,
                "use": result.use,
                "skipped": result.skipped,
                "downloaded_bytes": result.downloaded_bytes,
                "request": result.request,
            },
        )
