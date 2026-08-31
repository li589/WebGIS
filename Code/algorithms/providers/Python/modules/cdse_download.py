"""Copernicus CDSE 产品下载节点（``download/cdse_download``）。

主路径：copernicus 门户凭据 token 交换 → OData ``$value`` 下载（共享
续传工具）。回退 ``use="legacy"`` 直链（``http_open_data`` 语义）。
支持输入 port 接 ``search_portal`` / ``cmr_granule_search`` 风格检索结果。
"""

from __future__ import annotations

from modules.base import BaseModule
from modules.download_nodes import (
    _make_byte_stream_progress_cb,
    _make_multi_file_progress_cb,
    _make_skip_complete_emit,
    _resolve_portal_entry,
    _store_path_manifest,
)
from modules.registry import register_module_decorator
from workflow.schemas import NodeExecutionContext, PortSpec

_VALID_USE = frozenset({"auto", "cdse", "legacy"})


def _resolve_copernicus_credentials(
    params: dict[str, object], datasource_selection: dict[str, object]
) -> tuple[str, str, str]:
    """(username, password, bearer_token)：节点参数 > 门户 copernicus > 空。"""
    username = str(params.get("username") or "").strip()
    password = str(params.get("password") or "").strip()
    bearer = str(params.get("bearer_token") or "").strip()
    if username and password:
        return username, password, bearer
    entry = _resolve_portal_entry(datasource_selection, "copernicus")
    if entry:
        username = username or str(entry.get("username") or "").strip()
        password = (
            password or str(entry.get("password") or entry.get("secret") or "").strip()
        )
        bearer = bearer or str(entry.get("token") or "").strip()
    return username, password, bearer


@register_module_decorator(name="cdse_download", template_overrides={"phase": "download"})
class CdseDownloadModule(BaseModule):
    name = "cdse_download"
    description = (
        "Copernicus CDSE 产品下载（Sentinel 等）：门户凭据 token 交换后 OData "
        "$value 下载（Range 续传）；use='legacy' 走公共直链。可接 "
        "search_portal/cmr_granule_search 检索结果（granule_id 条目）。"
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
        PortSpec(
            name="search_results",
            kind="value",
            data_class="dict",
            required=False,
        ),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params: dict[str, object] = {
        "product_ids": "",
        "odata_filter": "",
        "target_dir": "",
        "use": "auto",
        "username": "",
        "password": "",
        "bearer_token": "",
        "legacy_urls": "",
        "force": False,
        "max_products": None,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from ingest.cdse_download import download_cdse_products

        ds = dict(inputs.get("datasource_selection", {}))
        ap = dict(inputs.get("algorithm_params", {}))
        resolved = {**self.default_params, **params, **ap}

        use = str(resolved.get("use") or "auto").strip().lower()
        if use not in _VALID_USE:
            raise ValueError(f"cdse_download: invalid use={use!r}")

        product_ids = resolved.get("product_ids", "")
        if isinstance(product_ids, (list, tuple)):
            product_ids = [str(p) for p in product_ids]
        else:
            product_ids = str(product_ids or "")

        target_dir = str(resolved.get("target_dir") or "").strip()
        if not target_dir:
            target_dir = str(ctx.workspace / "data_access" / "cdse")

        username, password, bearer = _resolve_copernicus_credentials(resolved, ds)

        max_products_raw = resolved.get("max_products")
        max_products = int(max_products_raw) if max_products_raw else None

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "cdse_download",
                f"CDSE download (use={use}) -> {target_dir}",
            )

        _multi_cb = _make_multi_file_progress_cb(ctx.logger_adapter, "cdse_download")
        _byte_cb = _make_byte_stream_progress_cb(
            ctx.logger_adapter, "cdse_download", item_name="product"
        )

        result = download_cdse_products(
            product_ids,
            str(resolved.get("odata_filter") or ""),
            target_dir,
            search_results=inputs.get("search_results"),
            username=username,
            password=password,
            bearer_token=bearer,
            use=use,
            legacy_urls=resolved.get("legacy_urls", ""),
            force=bool(resolved.get("force")),
            max_products=max_products,
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
                    "cdse_download",
                    total=max(total, result.skipped),
                    skipped=result.skipped,
                    downloaded=result.downloaded,
                )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                "cdse_download",
                f"CDSE download done: {result.downloaded} skipped="
                f"{result.skipped} failed={result.failed}",
            )

        if result.failed > 0:
            error_summary = "; ".join(result.errors[:5]) if result.errors else "unknown"
            raise RuntimeError(
                f"cdse_download completed with {result.failed} failures: "
                f"{error_summary}"
            )

        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=result.target_dir,
            product_type="cdse_product_dir",
            extra={
                "use": result.use,
                "downloaded": result.downloaded,
                "skipped": result.skipped,
                "failed": result.failed,
                "downloaded_bytes": result.downloaded_bytes,
                "products": [
                    {"id": p.product_id, "name": p.name, "size": p.size_bytes}
                    for p in result.products
                ],
            },
        )
