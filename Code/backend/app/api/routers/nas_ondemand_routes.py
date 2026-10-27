"""NAS 按需出图 API。

- ``POST /nas-ondemand/frame``       确保「产品 × 变量 × 某天」在本地有图
- ``POST /nas-ondemand/layer-frame`` 确保「某个既有图层 × 某天」有图（补帧进原图层）
- ``GET  /nas-ondemand/layers``      哪些图层支持按需补帧 + 数据覆盖范围
- ``GET  /nas-ondemand/cache-state`` 查看缓存现状（帧数/占用/最久未用）
- ``GET  /nas-ondemand/products``    列出可选产品与变量（前端下拉用）

权限（2026-10-27 修正，见下方原因）：
* 全部接口统一走 ``require_workflow_run_access``（admin / standard / demo 均可）。

为什么要放宽到 demo：补帧产出的是**图层数据**，与「跑工作流」同一性质，不是系统
配置、也不是数据导入导出。上一版把 ``layers`` 挂在 ``require_config_read_access``、
把 ``frame`` 挂在 ``require_write_access`` 上，结果 demo 账号（guest）读登记表就是
403 ⇒ 前端静默关闭整个能力，用户看到的现象是「拖日期毫无反应」。
安全边界没有变松：NAS 依旧只读（8 目录白名单 + 写请求拦截），仍受 2000 帧缓存上限约束。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import require_workflow_run_access
from app.services.nas_ondemand import config
from app.services.nas_ondemand.fetcher import (
    NasFileMissing,
    NasPathDenied,
    NasUnavailable,
    NasWriteForbidden,
)
from app.services.nas_ondemand.service import (
    FrameError,
    cache_state,
    ensure_frame,
    ensure_layer_frame,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nas-ondemand", tags=["nas-ondemand"])


class FrameRequest(BaseModel):
    """单帧请求。"""

    product: str = Field(description="fy_avg | fy_raw | smap_avg | smap_raw")
    variable: str = Field(description="SM | VOD | OMEGA")
    date: str = Field(description="YYYYMMDD")
    force: bool = Field(default=False, description="忽略本地缓存强制重取")


class LayerFrameRequest(BaseModel):
    """按需补帧请求（写进既有工作流图层目录，不改该层 meta.json）。"""

    layer_id: str = Field(description="imported-… 图层 ID")
    date: str = Field(description="YYYYMMDD")
    force: bool = Field(default=False, description="忽略本地已有强制重取")


class FrameResponse(BaseModel):
    """单帧结果。"""

    layer_id: str
    time_key: str
    cached: bool
    source: str
    elapsed_ms: int
    png: str
    bounds: str
    nas_dir: str | None = None
    nas_filename: str | None = None
    time_list_size: int | None = None
    mat_bytes: int | None = None
    eviction: dict | None = None
    render: dict | None = None


def _run_frame(fn, *args, **kwargs) -> FrameResponse:
    """把 service 层异常统一映射成 HTTP 状态码（两个入口共用）。"""
    try:
        result = fn(*args, **kwargs)
    except NasPathDenied as exc:
        # 白名单拦截属于程序性错误，不该被当成用户输入问题
        logger.error("NAS 路径被白名单拦截：%s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    except NasWriteForbidden as exc:
        logger.error("NAS 写请求被红线拦截：%s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    except NasFileMissing as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except NasUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except (FrameError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return FrameResponse(**result)


@router.post(
    "/frame",
    response_model=FrameResponse,
    status_code=status.HTTP_200_OK,
    summary="确保某天有图（本地没有才去 NAS 取）",
)
def post_frame(
    payload: FrameRequest,
    _user=Depends(require_workflow_run_access),
) -> FrameResponse:
    return _run_frame(
        ensure_frame,
        payload.product,
        payload.variable,
        payload.date,
        force=payload.force,
    )


@router.post(
    "/layer-frame",
    response_model=FrameResponse,
    status_code=status.HTTP_200_OK,
    summary="按需补帧：把某天的图补进既有图层目录（不改该层 meta）",
)
def post_layer_frame(
    payload: LayerFrameRequest,
    _user=Depends(require_workflow_run_access),
) -> FrameResponse:
    return _run_frame(
        ensure_layer_frame, payload.layer_id, payload.date, force=payload.force
    )


@router.get(
    "/layers",
    summary="哪些图层支持按需补帧 + 数据覆盖范围",
)
def get_layers(_user=Depends(require_workflow_run_access)) -> dict:
    return {
        "layers": [
            {
                "layer_id": layer_id,
                "product": spec["product"],
                "variable": spec["variable"],
            }
            for layer_id, spec in config.ONDEMAND_TARGETS.items()
        ],
        "coverage": {
            "start": config.DATA_COVERAGE_START,
            "end": config.DATA_COVERAGE_END,
        },
    }


@router.get(
    "/cache-state",
    summary="缓存现状（帧数 / 占用 / 最久未使用的帧）",
)
def get_cache_state(_user=Depends(require_workflow_run_access)) -> dict:
    return cache_state()


@router.get(
    "/products",
    summary="可选产品与变量清单",
)
def get_products(_user=Depends(require_workflow_run_access)) -> dict:
    return {
        "products": [
            {
                "key": key,
                "source": cfg["source"],
                "source_label": cfg["source_label"],
                "constraint": cfg["constraint"],
            }
            for key, cfg in config.PRODUCTS.items()
        ],
        "variables": [
            {
                "key": key,
                "label": cfg["label"],
                "title": cfg["title"],
                "palette": cfg["palette"],
                "vmin": cfg["vmin"],
                "vmax": cfg["vmax"],
                "unit": cfg["unit"],
            }
            for key, cfg in config.VARIABLES.items()
        ],
        "cache": {
            "max_frames": config.CACHE_MAX_FRAMES,
            "target_frames": config.CACHE_TARGET_FRAMES,
            "per_layer_floor": config.PER_LAYER_FLOOR,
            "protect_recent_days": config.PROTECT_RECENT_DAYS,
        },
    }
