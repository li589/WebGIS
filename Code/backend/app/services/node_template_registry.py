"""统一节点模板注册表

汇聚天气引擎、Python Provider、GEE 三个引擎的节点模板，
为前端 ComfyUI 风格编辑器提供可拖拽的节点目录。
"""

from __future__ import annotations

from typing import Any


# ─── 端口规格工具 ────────────────────────────────────────────────────────────
def _port(
    name: str, kind: str, required: bool = True, description: str = ""
) -> dict[str, Any]:
    return {
        "name": name,
        "type": kind,
        "required": required,
        "description": description,
    }


def _param(
    key: str,
    kind: str = "string",
    default: Any = None,
    description: str = "",
    options: list[str] | None = None,
    unit: str | None = None,
    min_val: float | None = None,
    max_val: float | None = None,
    step: float | None = None,
    allow_custom: bool | None = None,
    widget: str | None = None,
    bbox_keys: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构造参数描述字典。

    Args:
        key: 参数键名
        kind: 参数类型 (string/number/boolean/enum/array)
        default: 默认值
        description: 人类可读描述
        options: enum 类型的可选值列表
        unit: 物理单位 (如 "GHz"、"度"、"米"、"天")
        min_val: 数值下限
        max_val: 数值上限
        step: 数值步长
        allow_custom: 有 options 时是否允许自定义输入；None 时由前端推断
        widget: 前端渲染控件类型提示，优先级高于根据 type/value 自动推断。
            可选值: date | datetime | bbox | coordinate | path | textarea | color
            - date: 原生日期选择器，存储格式 YYYYMMDD
            - datetime: 日期+时间选择器，存储格式 YYYYMMDDHHmm
            - bbox: 四分量经纬度输入器（需配合 bbox_keys 指定字段映射）
            - coordinate: 单点经纬度选择器
            - path: 路径输入框（带目录浏览按钮）
            - textarea: 多行文本输入
            - color: 颜色选择器
        bbox_keys: widget=bbox 时，指定四个分量 key 映射
            (如 {"west": "min_lon", "east": "max_lon", ...})；默认 west/south/east/north
    """
    p: dict[str, Any] = {
        "key": key,
        "type": kind,
        "default": default,
        "description": description,
    }
    if options:
        p["options"] = options
    if unit:
        p["unit"] = unit
    if min_val is not None:
        p["min"] = min_val
    if max_val is not None:
        p["max"] = max_val
    if step is not None:
        p["step"] = step
    if allow_custom is not None:
        p["allow_custom"] = allow_custom
    if widget:
        p["widget"] = widget
    if bbox_keys:
        p["bbox_keys"] = bbox_keys
    return p


# ─── 节点模板定义 ────────────────────────────────────────────────────────────
# 每个模板包含: type, engine, category, title, description, inputs, outputs, params, node_class
# 端口类型系统:
#   data            通用数据流（向后兼容）
#   data:mat        .mat 文件（Python Provider 输出）
#   data:raster     栅格数据（GEE 影像、天气网格）
#   data:geojson    GeoJSON 矢量数据
#   data:timeseries 时间序列 .mat
#   data:source     数据源引用（路径/URI + 可选时空过滤上下文）
#   value:number    数值
#   value:string    字符串
#   value:boolean   布尔
#   value:time_range 时间窗口（含分辨率/字段映射/是否绑定主时间轴）
#   geometry:bbox   空间范围（含 CRS/字段映射）
# 连接规则: 相同类型允许; data <-> data:* 允许; data:* 之间禁止
#
# 时空维度约定（摘要）:
#   time_range = {start_at,end_at,resolution_unit,resolution_step,time_fields,field_format,timezone,bind_timeline}
#   bbox       = {west,south,east,north,crs,spatial_fields,source}
#   数据源声明「原生」时间/空间字段；time_range/bbox 输入表示「本次运行的过滤窗口」。

_NODE_TEMPLATES: list[dict[str, Any]] = [
    # ═══ 参数与范围（用连线驱动下游算法）═══════════════════════════════════════
    {
        "type": "data/source",
        "engine": "common",
        "category": "参数与范围",
        "title": "数据源",
        "description": "外部数据路径/URI，并声明原生时间与空间字段；可接入过滤用的时间范围与空间范围。",
        "inputs": [
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="读取时的时间过滤窗口。",
            ),
            _port(
                "bbox",
                "geometry:bbox",
                required=False,
                description="读取时的空间过滤窗口。",
            ),
        ],
        "outputs": [
            _port("data", "data:source", description="带上下文的数据源引用。"),
            _port("path", "value:string", description="解析后的路径字符串。"),
            _port(
                "manifest",
                "data",
                description="含路径引用的 product_manifest（供下游分析节点）。",
            ),
        ],
        "params": [
            _param(
                "dataset_key",
                "string",
                description="数据集标识符（如 SMAP_SPL3SMP_E）。",
            ),
            _param("path", "string", description="数据路径或 URI。", widget="path"),
            _param("pattern", "string", default="*", description="文件匹配模式。"),
            _param(
                "format",
                "string",
                default="auto",
                options=[
                    "auto",
                    "hdf5",
                    "netcdf",
                    "geotiff",
                    "geojson",
                    "csv",
                    "mat",
                    "grib",
                ],
                description="数据格式（auto 自动检测）。",
            ),
            _param(
                "native_resolution_unit",
                "string",
                default="day",
                options=["minute", "hour", "day", "month", "year", "custom"],
                description="数据原生时间分辨率单位。",
            ),
            _param(
                "native_resolution_step",
                "number",
                default=1,
                description="原生分辨率步长（如 3 + day 表示每 3 天一景）。",
                min_val=1,
                max_val=3650,
                step=1,
            ),
            _param(
                "time_fields",
                "string",
                default="datetime",
                description="时间字段名，多字段用逗号分隔（如 year,doy 或 datetime）。",
            ),
            _param(
                "time_field_format",
                "string",
                default="",
                description="时间字段解析格式提示（如 %Y%j、ISO8601；空=自动）。",
            ),
            _param(
                "spatial_fields",
                "string",
                default="",
                description="空间字段（如 lon,lat 或 geometry；栅格可留空）。",
            ),
            _param("crs", "string", default="EPSG:4326", description="数据坐标系。"),
        ],
        "node_class": "data_source",
    },
    # ═══ 数据获取与解析 ════════════════════════════════════════════════════════
    {
        "type": "download/remote_fetch",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "远程拉取",
        "description": "将任意 URI（smb/sftp/ftp/http/https/gs/local）物化到长期缓存；开放门户下载请优先用「门户数据下载」。凭证可用 ?cred=profile。",
        "inputs": [
            _port(
                "uri", "value:string", required=False, description="远程或本地 URI。"
            ),
            _port(
                "data", "data:source", required=False, description="上游数据源引用。"
            ),
        ],
        "outputs": [
            _port("path", "value:string", description="本地落盘路径。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "uri",
                "string",
                description="URI（也可由上游端口提供）。",
                widget="path",
            ),
            _param(
                "cred_profile",
                "string",
                description="远程存储凭证 profile（可选，等价 ?cred=）。",
            ),
        ],
        "node_class": "remote_fetch",
    },
    {
        "type": "download/http_open_data",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "门户数据下载",
        "description": "按 NOAA/NASA/NSIDC/ESA 预设 base URL + 相对路径下载并缓存；不负责产品检索。支持 cred_profile（earthdata/nsidc/copernicus）与 force_refresh。",
        "inputs": [
            _port("path", "value:string", required=False, description="相对路径覆盖。"),
        ],
        "outputs": [
            _port("path", "value:string", description="下载后的本地路径。"),
            _port("url", "value:string", description="解析后的完整 URL。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "preset",
                "string",
                default="noaa_nomads",
                options=[
                    "noaa_nomads",
                    "noaa_goes",
                    "nasa_earthdata",
                    "nasa_cmr",
                    "nsidc_data",
                    "nasa_ges_disc",
                    "nasa_gldas",
                    "esa_copernicus",
                    "esa_download",
                    "cma_nsmc",
                    "cma_data",
                ],
                description="开放门户预设键（与设置页 open_data_presets 对齐）。",
                allow_custom=False,
            ),
            _param("base_url", "string", description="自定义 base URL（优先于预设）。"),
            _param(
                "relative_path",
                "string",
                description="相对路径或对象键（必填）。",
                widget="path",
            ),
            _param("query", "string", description="可选 query string。"),
            _param(
                "cred_profile",
                "string",
                description="门户凭证 profile：earthdata / nsidc / copernicus（设置页配置）。",
                options=["", "earthdata", "nsidc", "copernicus"],
            ),
            _param(
                "token_header", "string", description="可选鉴权头名称（覆盖 profile）。"
            ),
            _param(
                "token_value", "string", description="可选鉴权头值 / Bearer token。"
            ),
            _param(
                "force_refresh",
                "boolean",
                default=False,
                description="忽略缓存强制重下。",
            ),
            _param("accept", "string", description="可选 Accept 请求头。"),
        ],
        "node_class": "http_open_data",
    },
    {
        "type": "download/cmr_search",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "CMR Granule 检索",
        "description": (
            "NASA CMR granule 检索（公共只读，免凭据）：按产品短名/版本/时间/范围"
            "返回 granule 数据 URL。输出 path（首个 URL，可直接接「门户数据下载」）。"
            "Earthdata 云 CDN 对象名含 tile/时间戳无法直接拼路径时，用本节点解析真实地址。"
        ),
        "inputs": [
            _port(
                "path",
                "value:string",
                required=False,
                description="预留（当前以参数为准）。",
            ),
        ],
        "outputs": [
            _port("path", "value:string", description="首个数据 URL（绝对地址）。"),
            _port("urls", "value:string", description="数据 URL 列表。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "short_name",
                "string",
                description="产品短名（如 VNP13A1 / SPL3SMP_E / GLDAS_NOAH025_3H）。",
            ),
            _param("version", "string", description="产品版本（可选）。"),
            _param(
                "start_date",
                "string",
                description="起始日期 YYYY-MM-DD 或 YYYYMMDD。",
                widget="date",
            ),
            _param(
                "end_date",
                "string",
                description="结束日期 YYYY-MM-DD 或 YYYYMMDD（默认同起始）。",
                widget="date",
            ),
            _param(
                "bounding_box",
                "string",
                description="范围过滤（西,南,东,北，可选）。",
            ),
            _param(
                "link_filter",
                "string",
                description="URL 子串过滤（如 .h5，可选）。",
            ),
            _param(
                "max_results",
                "number",
                default=5,
                description="最多返回条数（1~50）。",
            ),
            _param(
                "cmr_base",
                "string",
                description="CMR 检索端点覆盖（一般不改）。",
            ),
        ],
        "node_class": "cmr_granule_search",
    },
    {
        "type": "download/cds_download",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "CDS 再分析下载",
        "description": (
            "ECMWF CDS 数据集下载（ERA5/ORAS5 等再分析）：主路径 cdsapi 排队轮询，"
            "回退 legacy 静态直链（Range 续传）。凭据经门户 ecmwf_cds 或"
            " BACKEND_CDS_API_KEY 下发。"
        ),
        "inputs": [
            _port(
                "datasource_selection",
                "config",
                required=False,
                description="数据源选择（门户 ecmwf_cds 凭据注入）。",
            ),
            _port(
                "algorithm_params",
                "config",
                required=False,
                description="算法参数覆盖（可选）。",
            ),
        ],
        "outputs": [
            _port("path", "value:string", description="下载后的本地路径。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "dataset",
                "string",
                description="CDS 数据集 ID（如 reanalysis-era5-single-levels）。",
            ),
            _param(
                "request",
                "string",
                description="CDS request JSON（变量/日期/范围等）。",
                widget="textarea",
            ),
            _param(
                "target_dir",
                "string",
                description="本地目标目录（默认 workspace/data_access/cds）。",
                widget="path",
            ),
            _param(
                "use",
                "string",
                default="auto",
                options=["auto", "cdsapi", "legacy"],
                description="下载路径：auto=自动（cdsapi→legacy 回退）。",
                allow_custom=False,
            ),
            _param(
                "api_key",
                "string",
                description="CDS Personal Access Key（留空走门户/环境变量）。",
            ),
            _param(
                "filename",
                "string",
                description="落盘文件名（可选，默认由数据集/请求推导）。",
            ),
            _param(
                "direct_url",
                "string",
                description="legacy 直链 URL（use=legacy 或回退时使用）。",
            ),
            _param(
                "force",
                "boolean",
                default=False,
                description="忽略已有文件强制重下。",
            ),
        ],
        "node_class": "cds_download",
    },
    {
        "type": "download/nomads_grib_download",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "NOMADS GRIB2 下载",
        "description": (
            "NCEP NOMADS GRIB2 下载（GFS/GEFS/GDAS/NAM 等）：主路径 herbie 参数化"
            "检索与字段子集物化，回退 NOMADS 直连直链（Range 续传）。"
        ),
        "inputs": [
            _port(
                "datasource_selection",
                "config",
                required=False,
                description="数据源选择（可选）。",
            ),
            _port(
                "algorithm_params",
                "config",
                required=False,
                description="算法参数覆盖（可选）。",
            ),
        ],
        "outputs": [
            _port("path", "value:string", description="下载后的本地目录。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "date",
                "string",
                description="起报日期 YYYYMMDD 或 latest。",
                widget="date",
            ),
            _param(
                "model",
                "string",
                default="gfs",
                options=["gfs", "gefs", "gdas", "nam", "hrrr", "rap"],
                description="NOMADS 模型（herbie 命名）。",
                allow_custom=True,
            ),
            _param(
                "product",
                "string",
                description="产品子路径（如 pgrb2.0p25；空=模型默认）。",
            ),
            _param(
                "fxx",
                "number",
                default=0,
                min_val=0,
                max_val=8640,
                step=1,
                description="预报时效（小时）。",
                unit="h",
            ),
            _param(
                "search_string",
                "string",
                description="GRIB 字段子集（herbie 语法，如 :TMP:2 m ；空=整场）。",
            ),
            _param(
                "members",
                "string",
                description="集合成员列表（逗号分隔，GEFS 适用，可选）。",
            ),
            _param(
                "target_dir",
                "string",
                description="本地目标目录（默认 workspace/data_access/nomads）。",
                widget="path",
            ),
            _param(
                "use",
                "string",
                default="auto",
                options=["auto", "herbie", "legacy"],
                description="下载路径：auto=自动（herbie→legacy 回退）。",
                allow_custom=False,
            ),
            _param(
                "legacy_url",
                "string",
                description="legacy 直链 URL（可选覆盖）。",
            ),
            _param(
                "overwrite",
                "boolean",
                default=False,
                description="覆盖已存在文件。",
            ),
        ],
        "node_class": "nomads_grib_download",
    },
    {
        "type": "download/cdse_download",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "CDSE 产品下载",
        "description": (
            "Copernicus CDSE 产品下载（Sentinel 等）：门户 copernicus 凭据 token"
            " 交换后 OData $value 下载（Range 续传）；use='legacy' 走公共直链。"
            "可接 search_portal / cmr_granule_search 检索结果。"
        ),
        "inputs": [
            _port(
                "datasource_selection",
                "config",
                required=False,
                description="数据源选择（门户 copernicus 凭据注入）。",
            ),
            _port(
                "algorithm_params",
                "config",
                required=False,
                description="算法参数覆盖（可选）。",
            ),
            _port(
                "search_results",
                "data",
                required=False,
                description="上游检索结果（含 granule_id/product_id 条目）。",
            ),
        ],
        "outputs": [
            _port("path", "value:string", description="下载后的本地目录。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "product_ids",
                "string",
                description="产品 UUID 列表（逗号/换行分隔）。",
                widget="textarea",
            ),
            _param(
                "odata_filter",
                "string",
                description="OData $filter（在线检索产品，可选）。",
            ),
            _param(
                "target_dir",
                "string",
                description="本地目标目录（默认 workspace/data_access/cdse）。",
                widget="path",
            ),
            _param(
                "use",
                "string",
                default="auto",
                options=["auto", "cdse", "legacy"],
                description="下载路径：auto=自动（cdse→legacy 回退）。",
                allow_custom=False,
            ),
            _param(
                "username",
                "string",
                description="CDSE 用户名（留空走门户凭据）。",
            ),
            _param(
                "password",
                "string",
                description="CDSE 密码（留空走门户凭据）。",
            ),
            _param(
                "bearer_token",
                "string",
                description="CDSE Bearer token（可选，优先于账密）。",
            ),
            _param(
                "legacy_urls",
                "string",
                description="公共直链列表（use=legacy，逗号/换行分隔）。",
                widget="textarea",
            ),
            _param(
                "force",
                "boolean",
                default=False,
                description="忽略已有文件强制重下。",
            ),
            _param(
                "max_products",
                "number",
                min_val=1,
                step=1,
                description="最多下载数（联调节流，可选）。",
            ),
        ],
        "node_class": "cdse_download",
    },
    # ── 远程数据下载/同步/预处理节点 ──
    {
        "type": "download/ssh_sync",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "SSH/SFTP 同步",
        "description": "从远程服务器增量同步数据到本地。server_type 可选「远程与存储」中的 profile（ssh/sftp/filebrowser）或 hpc/win11/nas 遗留内置。支持日期过滤、断点续传、FileBrowser REST API。",
        "inputs": [
            _port(
                "data",
                "data:source",
                required=False,
                description="上游数据源引用（可选）。",
            ),
        ],
        "outputs": [
            _port("path", "value:string", description="本地落盘路径。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "server_type",
                "string",
                default="hpc",
                options=["hpc", "win11", "nas"],
                allow_custom=True,
                description="服务器：远程存储 profile id（设置→远程与存储）或 hpc/win11/nas 遗留内置。",
            ),
            _param(
                "remote_path", "string", description="远程目录路径。", widget="path"
            ),
            _param("local_path", "string", description="本地目标目录。", widget="path"),
            _param(
                "start_date",
                "string",
                description="起始日期 YYYYMMDD（可选过滤）。",
                widget="date",
            ),
            _param(
                "end_date",
                "string",
                description="结束日期 YYYYMMDD（可选过滤）。",
                widget="date",
            ),
            _param(
                "file_filter",
                "string",
                description="文件扩展名过滤（如 .mat,.h5）。",
            ),
        ],
        "node_class": "ssh_sync",
    },
    {
        "type": "download/nsidc_smap_download",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "NSIDC SMAP 下载",
        "description": "从 NASA NSIDC 下载 SMAP L3 SPL3SMP_E V6 土壤湿度数据。支持日期范围、增量下载、earthaccess 认证。",
        "inputs": [],
        "outputs": [
            _port("path", "value:string", description="本地落盘目录。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "start_date", "string", description="起始日期 YYYYMMDD。", widget="date"
            ),
            _param(
                "end_date", "string", description="结束日期 YYYYMMDD。", widget="date"
            ),
            _param("local_path", "string", description="本地目标目录。", widget="path"),
            _param(
                "version",
                "string",
                default="6",
                options=["5", "6"],
                description="产品版本。",
            ),
        ],
        "node_class": "nsidc_smap_download",
    },
    {
        "type": "download/gldas_download",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "GLDAS 在线下载",
        "description": "从 NASA GES DISC 下载 GLDAS NOAH025_3H V2.1（.nc4）。支持日期范围、增量下载、earthdata 认证；落地后可转 .mat 接入 DUAL 温度链。",
        "inputs": [],
        "outputs": [
            _port("path", "value:string", description="本地落盘目录。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "start_date", "string", description="起始日期 YYYYMMDD。", widget="date"
            ),
            _param(
                "end_date", "string", description="结束日期 YYYYMMDD。", widget="date"
            ),
            _param(
                "local_dir",
                "string",
                description="本地目标目录（默认 Meteorological/Weather/GLDAS_Download）。",
                widget="path",
            ),
            _param(
                "version",
                "string",
                default="2.1",
                options=["2.1"],
                description="产品版本。",
            ),
            _param(
                "short_name",
                "string",
                default="GLDAS_NOAH025_3H",
                description="CMR/GES DISC 产品短名。",
            ),
            _param(
                "dry_run",
                "boolean",
                default=False,
                description="仅搜索/统计，不实际下载。",
            ),
            _param(
                "max_files",
                "number",
                description="最多下载文件数（联调节流，可选）。",
            ),
        ],
        "node_class": "gldas_download",
    },
    {
        "type": "download/gldas_nc4_to_mat",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "GLDAS nc4→mat",
        "description": "将 GLDAS NOAH025_3H .nc4 重采样到 9 km 研究网格，输出 Ts_gldas/Tsoil1_gldas/Tsoil2_gldas（YYYYMMDD_HHMM.mat），供 DUAL 温度链使用。",
        "inputs": [
            _port(
                "data",
                "data:source",
                required=False,
                description="上游 nc4 目录（可选）。",
            ),
        ],
        "outputs": [
            _port("path", "value:string", description="输出 .mat 目录。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "input_dir",
                "string",
                description="输入 .nc4 目录（通常 GLDAS_Download）。",
                widget="path",
            ),
            _param(
                "output_dir",
                "string",
                description="输出 .mat 目录（默认 Meteorological/Weather/GLDAS）。",
                widget="path",
            ),
            _param(
                "ancillary_mat",
                "string",
                description="含 lat_9km/lon_9km 的辅助 MAT（默认 anc_root/IGBP_9km_12.mat）。",
                widget="path",
            ),
            _param(
                "skip_existing",
                "boolean",
                default=True,
                description="跳过已存在的目标 .mat。",
            ),
            _param(
                "dry_run",
                "boolean",
                default=False,
                description="仅统计，不写文件。",
            ),
            _param(
                "max_files",
                "number",
                description="最多转换文件数（联调节流，可选）。",
            ),
        ],
        "node_class": "gldas_nc4_to_mat",
    },
    {
        "type": "download/fy_preprocess",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "FY 亮温预处理",
        "description": "FY-3B/3D MWRI HDF 亮温预处理：geolocation 校正、日内轨道拼接、多通道合并、重投影。",
        "inputs": [
            _port(
                "data",
                "data:source",
                required=False,
                description="上游数据源（可选）。",
            ),
        ],
        "outputs": [
            _port("path", "value:string", description="输出目录。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "satellite",
                "string",
                default="FY3D",
                options=["FY3D", "FY3B"],
                description="卫星。",
            ),
            _param("input_dir", "string", description="HDF 输入目录。", widget="path"),
            _param("output_dir", "string", description="输出目录。", widget="path"),
            _param(
                "start_date", "string", description="起始日期 YYYYMMDD。", widget="date"
            ),
            _param(
                "end_date", "string", description="结束日期 YYYYMMDD。", widget="date"
            ),
            _param(
                "orbit_mode",
                "string",
                default="MWRID",
                options=["MWRID", "MWRIA", "Both"],
                description="轨道模式。",
            ),
            _param(
                "outfile_type",
                "string",
                default="HDF5",
                options=["GTiff", "NetCDF", "HDF5"],
                description="输出格式。",
            ),
        ],
        "node_class": "fy_preprocess",
    },
    {
        "type": "download/fy_download",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "风云卫星数据下载",
        "description": (
            "风云卫星数据专用下载模块：支持 NSMC 门户 HTTP 下载、NAS SMB 远程拉取、"
            "auto 自动回退（NSMC→NAS）。下载 FY-3 MWRI HDF 亮温数据供 fy_preprocess 处理。"
        ),
        "inputs": [
            _port(
                "datasource_selection",
                "config",
                required=False,
                description="数据源选择（含 portal_credentials 等）。",
            ),
        ],
        "outputs": [
            _port("path", "value:string", description="下载后的本地路径。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "satellite",
                "string",
                default="FY3D",
                options=["FY3D", "FY3B"],
                description="卫星。",
            ),
            _param(
                "data_source",
                "string",
                default="auto",
                options=["auto", "nsmc", "nas"],
                description="数据源：auto=自动回退（NSMC→NAS），nsmc=NSMC门户，nas=NAS远程拉取。",
            ),
            _param(
                "start_date", "string", description="起始日期 YYYYMMDD。", widget="date"
            ),
            _param(
                "end_date", "string", description="结束日期 YYYYMMDD。", widget="date"
            ),
            _param("local_dir", "string", description="本地保存目录。", widget="path"),
            _param(
                "band_ids",
                "string",
                default="1,2",
                description="通道 ID 列表（逗号分隔），如 1,2。",
            ),
            _param(
                "orbit_mode",
                "string",
                default="MWRID",
                options=["MWRID", "MWRIA", "Both"],
                description="轨道模式。",
            ),
        ],
        "node_class": "fy_download",
    },
    {
        "type": "archive/extract",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "解压归档",
        "description": (
            "解压 zip/tar/gz/tgz；非归档数据文件（如 CMR 直下的裸 .h5/.nc）透传复制进目录，"
            "url 输入可恢复原始文件名。支持 member_glob、recurse_once、Sentinel SAFE 识别。"
            "不支持 7z/rar。"
        ),
        "inputs": [
            _port("path", "value:string", required=False, description="归档文件路径。"),
            _port("data", "data:source", required=False, description="上游数据源。"),
            _port(
                "url",
                "value:string",
                required=False,
                description="来源 URL；透传时恢复原始文件名（HTTP 缓存以 sha256 命名）。",
            ),
        ],
        "outputs": [
            _port(
                "path",
                "value:string",
                description="解压结果路径（SAFE 时指向 SAFE 根）。",
            ),
            _port("extract_dir", "value:string", description="解压根目录。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "archive_path",
                "string",
                description="归档路径（也可由上游提供）。",
                widget="path",
            ),
            _param(
                "output_dirname",
                "string",
                default="extracted",
                description="输出子目录名。",
            ),
            _param(
                "member_glob", "string", description="可选成员过滤，如 *.nc / *.h5。"
            ),
            _param(
                "recurse_once",
                "boolean",
                default=False,
                description="对解压出的内层 zip/gz 再解一层。",
            ),
        ],
        "node_class": "archive_extract",
    },
    {
        "type": "config/read",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "读取配置",
        "description": "读取 JSON/YAML/INI/XML 配置为字典，供下游参数或清单使用。",
        "inputs": [
            _port("path", "value:string", required=False, description="配置文件路径。"),
            _port("data", "data:source", required=False, description="上游数据源。"),
        ],
        "outputs": [
            _port("config", "data", description="配置字典。"),
            _port("path", "value:string", description="源文件路径。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param("path", "string", description="配置文件路径。", widget="path"),
            _param(
                "format",
                "string",
                default="auto",
                options=["auto", "json", "yaml", "ini", "xml"],
                description="配置格式。",
            ),
        ],
        "node_class": "config_read",
    },
    {
        "type": "extract/variable",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "提取变量",
        "description": "用 UniversalDataReader 从 HDF5/NetCDF/GeoTIFF/MAT/GRIB 提取变量，支持 bbox/time_index。",
        "inputs": [
            _port(
                "path", "value:string", required=False, description="数据文件或目录。"
            ),
            _port("data", "data:source", required=False, description="上游数据源。"),
            _port("bbox", "geometry:bbox", required=False, description="空间裁剪。"),
        ],
        "outputs": [
            _port("path", "value:string", description="提取结果落盘路径。"),
            _port("array", "data:raster", description="变量摘要。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "path",
                "string",
                description="文件路径（也可由上游提供）。",
                widget="path",
            ),
            _param(
                "variable", "string", description="变量名（HDF5/NetCDF/MAT/GRIB）。"
            ),
            _param(
                "west",
                "number",
                description="bbox west。",
                min_val=-180,
                max_val=180,
                step=0.01,
            ),
            _param(
                "south",
                "number",
                description="bbox south。",
                min_val=-90,
                max_val=90,
                step=0.01,
            ),
            _param(
                "east",
                "number",
                description="bbox east。",
                min_val=-180,
                max_val=180,
                step=0.01,
            ),
            _param(
                "north",
                "number",
                description="bbox north。",
                min_val=-90,
                max_val=90,
                step=0.01,
            ),
            _param(
                "time_index",
                "number",
                description="时间层索引（可选）。",
                min_val=0,
                max_val=100000,
                step=1,
            ),
        ],
        "node_class": "variable_extract",
    },
    {
        "type": "format/convert",
        "engine": "common",
        "category": "数据获取与解析",
        "title": "格式转换",
        "description": "转为课题组常用 mat/npy/geotiff/csv/json（经 UniversalDataReader / FormatRegistry）。",
        "inputs": [
            _port("path", "value:string", required=False, description="源文件路径。"),
            _port("data", "data:source", required=False, description="上游数据源。"),
            _port("raster", "data:raster", required=False, description="上游栅格。"),
        ],
        "outputs": [
            _port("path", "value:string", description="转换后路径。"),
            _port("raster", "data:raster", description="转换结果引用。"),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param("path", "string", description="源路径。", widget="path"),
            _param(
                "target_format",
                "string",
                default="mat",
                options=["mat", "npy", "npz", "csv", "json"],
                description="目标格式。",
            ),
            _param("variable", "string", description="源变量名（科学格式需要）。"),
        ],
        "node_class": "format_convert",
    },
    {
        "type": "data/time_range",
        "engine": "common",
        "category": "参数与范围",
        "title": "时间范围",
        "description": "运行时间窗口：起止、分辨率（可到分钟/多天）、字段映射，以及是否绑定主界面时间轴。",
        "inputs": [],
        "outputs": [
            _port("time_range", "value:time_range", description="时间窗口输出"),
        ],
        "params": [
            _param(
                "start_at",
                "string",
                default="",
                description="起始时间 ISO 8601（如 2023-01-01T00:00:00）。",
                widget="datetime",
            ),
            _param(
                "end_at",
                "string",
                default="",
                description="结束时间 ISO 8601。",
                widget="datetime",
            ),
            _param(
                "resolution_unit",
                "string",
                default="day",
                options=["minute", "hour", "day", "month", "year", "custom"],
                description="窗口内期望的时间分辨率单位。",
            ),
            _param(
                "resolution_step",
                "number",
                default=1,
                description="分辨率步长（与单位组合，如 3 天）。",
                min_val=1,
                max_val=3650,
                step=1,
            ),
            _param(
                "granularity",
                "string",
                default="day",
                options=["minute", "hour", "day", "month", "year"],
                description="兼容旧字段：等同 resolution_unit（若两者不一致以 resolution_unit 为准）。",
            ),
            _param(
                "time_fields",
                "string",
                default="",
                description="可选：覆盖下游解析所用的时间字段列表（逗号分隔）。",
            ),
            _param(
                "field_format",
                "string",
                default="",
                description="可选：时间字段格式提示。",
            ),
            _param(
                "timezone",
                "string",
                default="UTC",
                description="时区（如 UTC、Asia/Shanghai）。",
            ),
            _param(
                "bind_timeline",
                "boolean",
                default=True,
                description="绑定主界面时间轴：运行时用 Timeline 当前时刻/窗口覆盖起止。",
            ),
        ],
        "node_class": "time_range",
    },
    {
        "type": "data/bbox",
        "engine": "common",
        "category": "参数与范围",
        "title": "空间范围",
        "description": "分析用 AOI 矩形范围，可指定 CRS 与空间字段映射。",
        "inputs": [],
        "outputs": [
            _port("bbox", "geometry:bbox", description="空间范围输出"),
        ],
        "params": [
            _param(
                "west",
                "number",
                default=73.0,
                description="西边界经度。",
                unit="度",
                min_val=-180,
                max_val=180,
                step=0.01,
                widget="bbox",
                bbox_keys={
                    "west": "west",
                    "south": "south",
                    "east": "east",
                    "north": "north",
                },
            ),
            _param(
                "south",
                "number",
                default=18.0,
                description="南边界纬度。",
                unit="度",
                min_val=-90,
                max_val=90,
                step=0.01,
            ),
            _param(
                "east",
                "number",
                default=135.0,
                description="东边界经度。",
                unit="度",
                min_val=-180,
                max_val=180,
                step=0.01,
            ),
            _param(
                "north",
                "number",
                default=54.0,
                description="北边界纬度。",
                unit="度",
                min_val=-90,
                max_val=90,
                step=0.01,
            ),
            _param("crs", "string", default="EPSG:4326", description="坐标系。"),
            _param(
                "spatial_fields",
                "string",
                default="",
                description="可选：矢量经纬度/几何字段（如 lon,lat）。",
            ),
        ],
        "node_class": "bbox",
    },
    {
        "type": "data/map_viewport",
        "engine": "common",
        "category": "参数与范围",
        "title": "地图视口",
        "description": "使用前端当前地图视口作为 bbox（运行时从 map_context 注入）。",
        "inputs": [],
        "outputs": [
            _port("bbox", "geometry:bbox", description="当前视口 bbox。"),
            _port(
                "viewport_bbox",
                "geometry:bbox",
                description="同 bbox，便于接到 viewport_bbox 端口。",
            ),
        ],
        "params": [
            _param(
                "padding_deg",
                "number",
                default=0.0,
                description="视口外扩。",
                unit="度",
                min_val=0,
                max_val=10,
                step=0.01,
            ),
            _param("crs", "string", default="EPSG:4326", description="坐标系。"),
        ],
        "node_class": "map_viewport",
    },
    {
        "type": "data/number",
        "engine": "common",
        "category": "参数与范围",
        "title": "数值",
        "description": "可调数值常量。",
        "inputs": [],
        "outputs": [
            _port("value", "value:number", description="数值输出。"),
        ],
        "params": [
            _param("value", "number", default=0.0, description="数值。"),
            _param("label", "string", default="", description="备注标签（仅显示）。"),
        ],
        "node_class": "number_const",
    },
    {
        "type": "data/string",
        "engine": "common",
        "category": "参数与范围",
        "title": "文本",
        "description": "可调文本常量。",
        "inputs": [],
        "outputs": [
            _port("value", "value:string", description="文本输出。"),
        ],
        "params": [
            _param("value", "string", default="", description="文本值。"),
            _param("label", "string", default="", description="备注标签（仅显示）。"),
        ],
        "node_class": "string_const",
    },
    {
        "type": "data/boolean",
        "engine": "common",
        "category": "参数与范围",
        "title": "开关",
        "description": "布尔开关常量。",
        "inputs": [],
        "outputs": [
            _port("value", "value:boolean", description="布尔输出。"),
        ],
        "params": [
            _param("value", "boolean", default=False, description="开关值。"),
            _param("label", "string", default="", description="备注标签（仅显示）。"),
        ],
        "node_class": "boolean_const",
    },
    {
        "type": "data/latlng",
        "engine": "common",
        "category": "参数与范围",
        "title": "经纬度",
        "description": "一组经纬度坐标。",
        "inputs": [],
        "outputs": [
            _port("latitude", "value:number", description=""),
            _port("longitude", "value:number", description=""),
        ],
        "params": [
            _param(
                "latitude",
                "number",
                default=23.1,
                description="纬度。",
                unit="度",
                min_val=-90,
                max_val=90,
                step=0.0001,
            ),
            _param(
                "longitude",
                "number",
                default=113.3,
                description="经度。",
                unit="度",
                min_val=-180,
                max_val=180,
                step=0.0001,
            ),
        ],
        "node_class": "latlng",
    },
    {
        "type": "output/map_layer",
        "engine": "common",
        "category": "输出",
        "title": "地图图层输出",
        "description": "将上游数据输出为地图图层。",
        "inputs": [
            _port("data", "data", description="要输出的图层数据或上游 manifest。"),
            _port(
                "manifest",
                "data",
                required=False,
                description="上游产物清单（可与 data 二选一）。",
            ),
            _port(
                "path",
                "value:string",
                required=False,
                description="可选本地路径。",
            ),
        ],
        "outputs": [
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param("layer_id", "string", description="目标图层标识符。"),
            _param("display_name", "string", description="图层显示名称。"),
        ],
        "node_class": "output_map_layer",
    },
    {
        "type": "output/file",
        "engine": "common",
        "category": "输出",
        "title": "文件输出",
        "description": "将上游数据输出为文件。",
        "inputs": [
            _port("data", "data", description="要输出的数据。"),
        ],
        "outputs": [
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "format",
                "string",
                default="mat",
                options=["mat", "geojson", "geotiff", "json", "csv"],
                description="输出文件格式。",
            ),
            _param("filename", "string", description="输出文件名。"),
        ],
        "node_class": "output_file",
    },
    # ═══ 数据预处理模块 ════════════════════════════════════════════════════════
    {
        "type": "preprocess/reproject",
        "engine": "python_provider",
        "category": "数据预处理",
        "title": "重投影",
        "description": "将栅格数据重投影到目标坐标系。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格。"),
            _port(
                "bbox", "geometry:bbox", required=False, description="可选空间范围。"
            ),
        ],
        "outputs": [
            _port("raster", "data:raster", description="重投影后栅格。"),
        ],
        "params": [
            _param(
                "target_crs", "string", default="EPSG:4326", description="目标坐标系。"
            ),
            _param(
                "resampling",
                "string",
                default="nearest",
                options=["nearest", "bilinear", "cubic"],
                description="重采样方法。",
            ),
        ],
        "executable": True,
        "node_class": "preprocess_reproject",
    },
    {
        "type": "preprocess/resample",
        "engine": "python_provider",
        "category": "数据预处理",
        "title": "重采样",
        "description": "改变栅格数据的空间分辨率。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格。"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="重采样后栅格。"),
        ],
        "params": [
            _param(
                "target_resolution",
                "number",
                default=1000,
                description="目标分辨率。",
                unit="米",
                min_val=1,
                max_val=100000,
                step=1,
            ),
            _param(
                "resampling",
                "string",
                default="nearest",
                options=["nearest", "bilinear", "cubic"],
                description="重采样方法。",
            ),
            _param(
                "unit",
                "string",
                default="meters",
                options=["meters", "degrees"],
                description="分辨率单位。",
            ),
        ],
        "executable": True,
        "node_class": "preprocess_resample",
    },
    {
        "type": "preprocess/format_convert",
        "engine": "common",
        "category": "数据预处理",
        "title": "格式转换",
        "description": "在不同数据格式之间转换。",
        "inputs": [
            _port("data", "data", description="输入数据。"),
        ],
        "outputs": [
            _port("data", "data", description="转换后数据。"),
        ],
        "params": [
            _param(
                "input_format",
                "string",
                default="auto",
                options=["auto", "netcdf", "hdf5", "geotiff", "mat"],
                description="输入格式（auto 自动检测）。",
            ),
            _param(
                "output_format",
                "string",
                default="geotiff",
                options=["geotiff", "cog", "mat", "json"],
                description="输出格式。",
            ),
        ],
        "node_class": "format_convert",
    },
    {
        "type": "preprocess/clip",
        "engine": "python_provider",
        "category": "数据预处理",
        "title": "裁剪",
        "description": "按空间范围裁剪栅格数据。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格。"),
            # required=False: LiteGraph bbox fan-in is scraped to job_request /
            # algorithm_params (see workflow_graph_compiler._normalize_python_edges).
            _port(
                "bbox",
                "geometry:bbox",
                required=False,
                description="裁剪范围（可由 data/bbox 或请求 spatial_filter 注入）。",
            ),
        ],
        "outputs": [
            _port("raster", "data:raster", description="裁剪后栅格。"),
        ],
        "params": [
            _param(
                "buffer_meters",
                "number",
                default=0,
                description="缓冲区大小。",
                unit="米",
                min_val=0,
                max_val=10000,
                step=10,
            ),
        ],
        "executable": True,
        "node_class": "preprocess_clip",
    },
    {
        "type": "preprocess/mask",
        "engine": "python_provider",
        "category": "数据预处理",
        "title": "掩膜",
        "description": "用掩膜栅格遮蔽输入栅格的像元。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格。"),
            _port("mask", "data:raster", description="掩膜栅格。"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="掩膜后栅格。"),
        ],
        "params": [
            _param(
                "mask_value",
                "number",
                default=0,
                description="掩膜值（等于此值的像元被遮蔽）。",
            ),
            _param("invert", "boolean", default=False, description="是否反转掩膜。"),
        ],
        "executable": True,
        "node_class": "preprocess_mask",
    },
    # ═══ 统计分析模块 ══════════════════════════════════════════════════════════
    {
        "type": "stats/spatial_mean",
        "engine": "python_provider",
        "category": "统计分析",
        "title": "空间均值",
        "description": "计算栅格数据的空间统计量。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格。"),
        ],
        "outputs": [
            _port("value", "value:number", description="统计值。"),
        ],
        "params": [
            _param(
                "statistic",
                "string",
                default="mean",
                options=["mean", "median", "min", "max", "std"],
                description="统计量类型。",
            ),
            _param(
                "band",
                "number",
                default=0,
                description="波段索引。",
                min_val=0,
                max_val=100,
                step=1,
            ),
        ],
        "executable": True,
        "node_class": "stats_spatial_mean",
    },
    {
        "type": "stats/temporal_trend",
        "engine": "python_provider",
        "category": "统计分析",
        "title": "时间趋势分析",
        "description": "分析时间序列数据的趋势（线性/Theil-Sen/Mann-Kendall）。",
        "inputs": [
            _port("timeseries", "data:timeseries", description="时间序列数据。"),
        ],
        "outputs": [
            _port("result", "data:geojson", description="趋势分析结果 GeoJSON。"),
        ],
        "params": [
            _param(
                "trend_method",
                "string",
                default="linear",
                options=["linear", "theil_sen", "mann_kendall"],
                description="趋势分析方法。",
            ),
            _param(
                "confidence_level",
                "number",
                default=0.95,
                description="置信水平。",
                min_val=0.5,
                max_val=0.999,
                step=0.01,
            ),
        ],
        "executable": True,
        "node_class": "stats_temporal_trend",
    },
    {
        "type": "stats/anomaly_detect",
        "engine": "python_provider",
        "category": "统计分析",
        "title": "异常检测",
        "description": "检测时间序列中的异常值（Z-score/IQR/DBSCAN）。",
        "inputs": [
            _port("timeseries", "data:timeseries", description="时间序列数据。"),
        ],
        "outputs": [
            _port("anomalies", "data:geojson", description="异常点 GeoJSON。"),
        ],
        "params": [
            _param(
                "method",
                "string",
                default="zscore",
                options=["zscore", "iqr", "dbscan"],
                description="异常检测方法。",
            ),
            _param(
                "threshold",
                "number",
                default=2.0,
                description="阈值（Z-score 标准差倍数）。",
                min_val=1.0,
                max_val=5.0,
                step=0.1,
            ),
        ],
        "executable": True,
        "node_class": "stats_anomaly_detect",
    },
    {
        "type": "stats/correlation",
        "engine": "python_provider",
        "category": "统计分析",
        "title": "相关性分析",
        "description": "计算两个时间序列的相关系数（Pearson/Spearman/Kendall）。",
        "inputs": [
            _port("x", "data:timeseries", description="X 序列。"),
            _port("y", "data:timeseries", description="Y 序列。"),
        ],
        "outputs": [
            _port("coefficient", "value:number", description="相关系数 [-1, 1]。"),
        ],
        "params": [
            _param(
                "method",
                "string",
                default="pearson",
                options=["pearson", "spearman", "kendall"],
                description="相关系数方法。",
            ),
            _param(
                "lag_days",
                "number",
                default=0,
                description="滞后天数。",
                unit="天",
                min_val=0,
                max_val=365,
                step=1,
            ),
        ],
        "executable": True,
        "node_class": "stats_correlation",
    },
    {
        "type": "stats/histogram",
        "engine": "python_provider",
        "category": "统计分析",
        "title": "直方图统计",
        "description": "计算任意数值栅格的直方图分布（float64，nodata 感知），产出 ChartSpec/TableSpec。",
        "inputs": [
            _port(
                "manifest",
                "data",
                required=False,
                description="上游 product_manifest。",
            ),
            _port(
                "raster",
                "data:raster",
                required=False,
                description="输入栅格（或 datasource）。",
            ),
        ],
        "outputs": [
            _port(
                "manifest", "data", description="含 chart_spec/table_spec 的 manifest。"
            ),
        ],
        "params": [
            _param(
                "bins",
                "number",
                default=50,
                description="分箱数量。",
                min_val=5,
                max_val=500,
                step=1,
            ),
            _param(
                "band",
                "number",
                default=0,
                description="波段索引。",
                min_val=0,
                max_val=100,
                step=1,
            ),
            _param(
                "density",
                "boolean",
                default=False,
                description="是否归一化为概率密度。",
            ),
            _param(
                "variable",
                "string",
                default="",
                description="变量名（空=自动选取）。",
            ),
            _param(
                "nodata",
                "string",
                default="",
                description="Nodata 值（空=仅排除非有限值）。",
            ),
        ],
        "executable": True,
        "node_class": "stats_histogram",
    },
    # ═══ 数据融合与可视化模块 ═══════════════════════════════════════════════════
    {
        "type": "fusion/spatial_interpolate",
        "engine": "python_provider",
        "category": "数据融合",
        "title": "空间插值",
        "description": "将离散点数据插值为栅格（IDW/克里金/最近邻）。",
        "inputs": [
            _port("points", "data:geojson", description="离散点 GeoJSON。"),
            _port("bbox", "geometry:bbox", description="插值范围。"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="插值结果栅格。"),
        ],
        "params": [
            _param(
                "method",
                "string",
                default="idw",
                options=["idw", "kriging", "nearest"],
                description="插值方法。",
            ),
            _param(
                "power",
                "number",
                default=2.0,
                description="IDW 幂参数。",
                min_val=1.0,
                max_val=6.0,
                step=0.5,
            ),
            _param(
                "resolution",
                "number",
                default=1000,
                description="输出分辨率。",
                unit="米",
                min_val=10,
                max_val=50000,
                step=10,
            ),
        ],
        "executable": True,
        "node_class": "fusion_spatial_interpolate",
    },
    {
        "type": "fusion/multi_source_merge",
        "engine": "python_provider",
        "category": "数据融合",
        "title": "多源融合",
        "description": "融合两个栅格数据源（加权/PCA/贝叶斯）。",
        "inputs": [
            _port("primary", "data:raster", description="主数据源。"),
            _port("secondary", "data:raster", description="辅助数据源。"),
        ],
        "outputs": [
            _port("merged", "data:raster", description="融合结果。"),
        ],
        "params": [
            _param(
                "method",
                "string",
                default="weighted",
                options=["weighted", "pca", "bayesian"],
                description="融合方法。",
            ),
            _param(
                "weight_primary",
                "number",
                default=0.6,
                description="主数据源权重。",
                min_val=0.0,
                max_val=1.0,
                step=0.05,
            ),
        ],
        "executable": True,
        "node_class": "fusion_multi_source_merge",
    },
    {
        "type": "viz/chart_generate",
        "engine": "python_provider",
        "category": "可视化",
        "title": "图表生成",
        "description": "将上游 chart/table/statistics JSON 规范化为 ChartSpec（可选附带 PNG）。",
        "inputs": [
            _port(
                "manifest",
                "data",
                required=False,
                description="上游 product_manifest。",
            ),
            _port("data", "data", required=False, description="输入数据。"),
        ],
        "outputs": [
            _port("manifest", "data", description="含 chart_spec 的 manifest。"),
        ],
        "params": [
            _param(
                "chart_type",
                "string",
                default="line",
                options=["line", "bar", "scatter", "histogram", "boxplot"],
                description="图表类型。",
            ),
            _param(
                "title",
                "string",
                default="Chart",
                description="图表标题（建议 ASCII）。",
            ),
            _param("x_label", "string", default="", description="X 轴标签。"),
            _param("y_label", "string", default="", description="Y 轴标签。"),
            _param(
                "width",
                "number",
                default=800,
                description="可选 PNG 宽度。",
                unit="像素",
                min_val=200,
                max_val=4000,
                step=50,
            ),
            _param(
                "height",
                "number",
                default=600,
                description="可选 PNG 高度。",
                unit="像素",
                min_val=200,
                max_val=4000,
                step=50,
            ),
            _param(
                "write_png",
                "boolean",
                default=True,
                description="是否额外写出 matplotlib PNG。",
            ),
        ],
        "executable": True,
        "node_class": "viz_chart_generate",
    },
    {
        "type": "viz/report_export",
        "engine": "python_provider",
        "category": "可视化",
        "title": "报表导出",
        "description": "将分析结果导出为报表（PDF/HTML/DOCX/Markdown）。",
        "inputs": [
            _port("data", "data", description="分析结果数据。"),
        ],
        "outputs": [
            _port("filepath", "value:string", description="输出文件路径。"),
        ],
        "params": [
            _param(
                "format",
                "string",
                default="html",
                options=["pdf", "html", "docx", "markdown"],
                description="报表格式。",
            ),
            _param(
                "template", "string", default="default", description="报表模板名称。"
            ),
            _param(
                "include_charts", "boolean", default=True, description="是否包含图表。"
            ),
        ],
        "executable": True,
        "node_class": "viz_report_export",
    },
    {
        "type": "viz/statistics_summary",
        "engine": "python_provider",
        "category": "可视化",
        "title": "统计摘要",
        "description": "生成数据统计摘要（均值/标准差/分位数）。",
        "inputs": [
            _port("data", "data", description="输入数据。"),
        ],
        "outputs": [
            _port("summary", "data:geojson", description="统计摘要 GeoJSON。"),
            _port(
                "manifest", "data", description="含 table_spec 的 product_manifest。"
            ),
        ],
        "params": [
            _param("include_mean", "boolean", default=True, description="包含均值。"),
            _param("include_std", "boolean", default=True, description="包含标准差。"),
            _param(
                "include_percentiles",
                "boolean",
                default=True,
                description="包含分位数。",
            ),
            _param(
                "percentile_list",
                "string",
                default="25,50,75",
                description="分位数列表（逗号分隔）。",
            ),
        ],
        "executable": True,
        "node_class": "viz_statistics_summary",
    },
    # ═══ 天气引擎节点 ══════════════════════════════════════════════════════════
    {
        "type": "weather/forecast_fetch",
        "engine": "weather",
        "category": "天气-数据抓取",
        "title": "预报数据抓取",
        "description": "经天气引擎 Provider（Open-Meteo / WeatherAPI / OpenWeather 等）抓取预报数据。",
        "inputs": [
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port("layer_id", "value:string", description="天气图层标识。"),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="可选时间范围。",
            ),
            _port("model", "value:string", required=False, description="气象模型。"),
            _port(
                "forecast_hours",
                "value:number",
                required=False,
                description="预报小时数。",
            ),
            _port(
                "provider_id",
                "value:string",
                required=False,
                description="钉选天气源：open-meteo-online | open-meteo-local | weatherapi | openweather；空=自动。",
            ),
        ],
        "outputs": [
            _port("forecast", "data", description="原始预报数据。"),
            _port("cache_status", "value:string", description="缓存状态 (hit/miss)。"),
            _port("layer_spec", "data", description="图层规格字典。"),
            _port("provider_id", "value:string", description="实际使用的天气源。"),
        ],
        "params": [
            _param(
                "default_model",
                "string",
                default="icon_seamless",
                description="默认气象模型。",
            ),
            _param(
                "provider_id",
                "string",
                default="",
                description="钉选天气源 Provider ID（空=自动）：open-meteo-online | open-meteo-local | weatherapi | openweather。",
            ),
        ],
        "node_class": "weather_forecast_fetch",
    },
    {
        "type": "weather/grid_fetch",
        "engine": "weather",
        "category": "天气-数据抓取",
        "title": "网格数据抓取",
        "description": "经天气引擎 Provider 抓取网格化天气数据用于渲染。",
        "inputs": [
            _port("layer_id", "value:string", description="天气图层标识。"),
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="可选时间范围。",
            ),
            _port(
                "forecast_hours",
                "value:number",
                required=False,
                description="预报小时数。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间范围。"),
            _port(
                "provider_id",
                "value:string",
                required=False,
                description="钉选天气源：open-meteo-online | open-meteo-local | weatherapi | openweather；空=自动。",
            ),
            _port(
                "model",
                "value:string",
                required=False,
                description="预报模型（如 best_match）。",
            ),
        ],
        "outputs": [
            _port("grid_data", "data:raster", description="网格化天气数据。"),
            _port("hour", "value:number", description="当前小时。"),
            _port("provider_id", "value:string", description="实际使用的天气源。"),
        ],
        "params": [
            _param(
                "provider_id",
                "string",
                default="",
                description="钉选天气源 Provider ID（空=自动）：open-meteo-online | open-meteo-local | weatherapi | openweather。",
            ),
            _param("model", "string", default="best_match", description="预报模型。"),
        ],
        "node_class": "weather_grid_fetch",
    },
    {
        "type": "weather/wind_field_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "风场渲染",
        "description": "基于预报数据生成风场矢量 GeoJSON，支持粒子流动画。",
        "inputs": [
            _port(
                "weather_point",
                "data",
                required=False,
                description="上游点位数据，未提供时自行获取。",
            ),
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port(
                "grid_data",
                "data:raster",
                required=False,
                description="上游网格数据（优先）。",
            ),
            _port(
                "layer_id",
                "value:string",
                required=False,
                description="目标图层标识，默认 wind-field。",
            ),
            _port(
                "viewport_bbox",
                "geometry:bbox",
                required=False,
                description="前端视口。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间过滤。"),
        ],
        "outputs": [
            _port(
                "geojson",
                "data:geojson",
                description="风场矢量 GeoJSON FeatureCollection。",
            ),
        ],
        "params": [
            _param(
                "layer_id",
                "string",
                default="wind-field",
                description="目标图层标识。",
            ),
        ],
        "node_class": "weather_wind_field",
    },
    {
        "type": "weather/temperature_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "温度渲染",
        "description": "生成温度栅格图层。",
        "inputs": [
            _port(
                "grid_data", "data:raster", required=False, description="上游网格数据。"
            ),
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port(
                "layer_id", "value:string", required=False, description="目标图层标识。"
            ),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="温度栅格 GeoJSON。"),
        ],
        "params": [
            _param(
                "layer_id",
                "string",
                default="temperature",
                description="目标图层标识。",
            ),
        ],
        "node_class": "weather_temperature_grid",
    },
    {
        "type": "weather/precipitation_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "降水渲染",
        "description": "生成降水栅格图层。",
        "inputs": [
            _port(
                "grid_data", "data:raster", required=False, description="上游网格数据。"
            ),
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port(
                "layer_id", "value:string", required=False, description="目标图层标识。"
            ),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="降水栅格 GeoJSON。"),
        ],
        "params": [
            _param(
                "layer_id",
                "string",
                default="precipitation",
                description="目标图层标识。",
            ),
        ],
        "node_class": "weather_precipitation_grid",
    },
    {
        "type": "weather/humidity_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "湿度渲染",
        "description": "生成湿度栅格图层。",
        "inputs": [
            _port(
                "grid_data", "data:raster", required=False, description="上游网格数据。"
            ),
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port(
                "layer_id", "value:string", required=False, description="目标图层标识。"
            ),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="湿度栅格 GeoJSON。"),
        ],
        "params": [
            _param(
                "layer_id",
                "string",
                default="humidity",
                description="目标图层标识。",
            ),
        ],
        "node_class": "weather_humidity_grid",
    },
    {
        "type": "weather/pressure_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "气压渲染",
        "description": "生成气压栅格图层。",
        "inputs": [
            _port(
                "grid_data", "data:raster", required=False, description="上游网格数据。"
            ),
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port(
                "layer_id", "value:string", required=False, description="目标图层标识。"
            ),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="气压栅格 GeoJSON。"),
        ],
        "params": [
            _param(
                "layer_id",
                "string",
                default="pressure",
                description="目标图层标识。",
            ),
        ],
        "node_class": "weather_pressure_grid",
    },
    {
        "type": "weather/visibility_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "能见度渲染",
        "description": "生成能见度栅格图层。",
        "inputs": [
            _port(
                "grid_data", "data:raster", required=False, description="上游网格数据。"
            ),
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port(
                "layer_id", "value:string", required=False, description="目标图层标识。"
            ),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="能见度栅格 GeoJSON。"),
        ],
        "params": [
            _param(
                "layer_id",
                "string",
                default="visibility",
                description="目标图层标识。",
            ),
        ],
        "node_class": "weather_visibility_grid",
    },
    {
        "type": "weather/cloud_cover_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "云量渲染",
        "description": "生成云量栅格图层。",
        "inputs": [
            _port(
                "grid_data", "data:raster", required=False, description="上游网格数据。"
            ),
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port(
                "layer_id", "value:string", required=False, description="目标图层标识。"
            ),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="云量栅格 GeoJSON。"),
        ],
        "params": [
            _param(
                "layer_id",
                "string",
                default="cloud-cover",
                description="目标图层标识。",
            ),
        ],
        "node_class": "weather_cloud_cover_grid",
    },
    {
        "type": "weather/dewpoint_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "露点渲染",
        "description": "生成露点栅格图层。",
        "inputs": [
            _port(
                "grid_data", "data:raster", required=False, description="上游网格数据。"
            ),
            _port("latitude", "value:number", description="中心纬度。"),
            _port("longitude", "value:number", description="中心经度。"),
            _port(
                "layer_id", "value:string", required=False, description="目标图层标识。"
            ),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="露点栅格 GeoJSON。"),
        ],
        "params": [
            _param(
                "layer_id",
                "string",
                default="dewpoint",
                description="目标图层标识。",
            ),
        ],
        "node_class": "weather_dewpoint_grid",
    },
    {
        "type": "weather/tile_render",
        "engine": "weather",
        "category": "天气-瓦片",
        "title": "天气瓦片渲染",
        "description": "生成天气瓦片用于前端地图显示。",
        "inputs": [
            _port("grid_data", "data:raster", description="上游网格数据。"),
            _port("layer_id", "value:string", description="目标图层标识。"),
            _port("z", "value:number", description="缩放级别。"),
            _port("x", "value:number", description="瓦片 X 坐标。"),
            _port("y", "value:number", description="瓦片 Y 坐标。"),
        ],
        "outputs": [
            _port("tile", "data", description="渲染后的瓦片数据。"),
        ],
        "params": [
            _param(
                "hour",
                "number",
                default=0,
                min_val=0,
                max_val=240,
                step=1,
                unit="小时",
                description="渲染目标小时偏移（0=当前）。",
            ),
            _param(
                "model",
                "string",
                default="best_match",
                description="预报模型。",
            ),
            _param(
                "provider_id",
                "string",
                default="",
                description="天气源 Provider ID（空=自动）。",
            ),
        ],
        "node_class": "weather_tile_render",
    },
    {
        "type": "weather/point_parse",
        "engine": "weather",
        "category": "天气-处理",
        "title": "点位解析",
        "description": "解析天气点位查询结果。",
        "inputs": [
            _port("latitude", "value:number", description="纬度。"),
            _port("longitude", "value:number", description="经度。"),
            _port("layer_id", "value:string", description="天气图层标识。"),
        ],
        "outputs": [
            _port("weather_point", "data", description="解析后的天气点位数据。"),
        ],
        "params": [
            _param(
                "forecast_hours",
                "number",
                default=6,
                min_val=1,
                max_val=240,
                step=1,
                unit="小时",
                description="预报小时数。",
            ),
        ],
        "node_class": "weather_point_parse",
    },
    {
        "type": "weather/summary_generate",
        "engine": "weather",
        "category": "天气-处理",
        "title": "摘要生成",
        "description": "生成天气摘要文本。",
        "inputs": [
            _port("weather_point", "data", description="天气点位数据。"),
            _port("layer_id", "value:string", required=False, description="图层标识。"),
        ],
        "outputs": [
            _port("summary", "value:string", description="天气摘要文本。"),
        ],
        "params": [],
        "node_class": "weather_summary_generate",
    },
    # ═══ Python Provider 模块节点 ══════════════════════════════════════════════
    {
        "type": "module/smap_daily",
        "engine": "python_provider",
        "category": "遥感处理",
        "title": "SMAP 日常处理",
        "description": "读取 SMAP L3 HDF5，转换为日常 .mat 产品。",
        "inputs": [
            _port("input_dir", "data:source", description="SMAP HDF5 目录。"),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="过滤时间。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间裁剪。"),
        ],
        "outputs": [
            _port("smap_daily_mat", "data:mat", description="SMAP 日常 .mat 输出。"),
        ],
        "params": [
            _param(
                "output_dir",
                "string",
                default="",
                description="输出目录（空=默认工作区 products/smap_daily）。",
                widget="path",
            ),
        ],
        "node_class": "smap_daily",
    },
    {
        "type": "module/ndvi_daily",
        "engine": "python_provider",
        "category": "遥感处理",
        "title": "NDVI 日常处理",
        "description": "读取 NDVI 栅格，生成日常 NDVI .mat 产品。",
        "inputs": [
            _port(
                "data",
                "data:source",
                required=False,
                description="上游节点（archive/extract、remote_fetch）输出的数据目录；缺省时回退 datasource_selection。",
            ),
            _port(
                "datasource_selection",
                "data:source",
                required=False,
                description="数据源选择（含 input_dir；通常 request 绑定）。",
            ),
            _port(
                "algorithm_params",
                "value:any",
                required=False,
                description="算法参数（通常 request 绑定）。",
            ),
            _port(
                "output_spec_extra",
                "value:any",
                required=False,
                description="输出扩展配置。",
            ),
        ],
        "outputs": [
            _port("manifest", "data", description="NDVI 日常产品清单。"),
        ],
        "params": [
            _param(
                "emit_quality_products",
                "boolean",
                default=False,
                description="是否输出质量产品。",
            ),
            _param(
                "sg_step_days",
                "number",
                default=1,
                description="SG 滤波步长。",
                unit="天",
                min_val=1,
                max_val=30,
                step=1,
            ),
            _param(
                "gap_threshold_days",
                "number",
                default=16,
                description="间隔阈值。",
                unit="天",
                min_val=1,
                max_val=60,
                step=1,
            ),
        ],
        "node_class": "ndvi_daily",
    },
    {
        "type": "module/ndvi_hdf_preprocess",
        "engine": "python_provider",
        "category": "遥感处理",
        "title": "NDVI HDF 预处理 (A1/A2)",
        "description": "VNP13C1/MOYD13C1 → QA 掩膜 + 9 km GeoTIFF，供 ndvi_daily 使用。",
        "inputs": [
            _port(
                "input_dir", "data:source", description="VIIRS/MODIS NDVI HDF 目录。"
            ),
        ],
        "outputs": [
            _port("manifest", "data:manifest", description="产物清单。"),
            _port("output_dir", "value:string", description="9 km TIF 输出目录。"),
        ],
        "params": [
            _param(
                "output_dir",
                "string",
                default="",
                description="9 km GeoTIFF 输出目录（空=默认工作区）。",
                widget="path",
            ),
            _param(
                "work_dir",
                "string",
                default="",
                description="临时工作目录（空=output_dir/_tmp_ndvi_hdf）。",
                widget="path",
            ),
        ],
        "node_class": "ndvi_hdf_preprocess",
    },
    {
        "type": "module/fy_daily",
        "engine": "python_provider",
        "category": "遥感处理",
        "title": "风云数据处理",
        "description": "读取风云三号 MWRI 数据，提取多波段亮温为 .mat。",
        "inputs": [
            _port("input_dir", "data:source", description="FY MWRI 目录。"),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="过滤时间。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间裁剪。"),
        ],
        "outputs": [
            _port("fy_daily_mat", "data:mat", description="FY 日常 .mat 输出。"),
        ],
        "params": [
            _param(
                "orbit_mode",
                "string",
                default="MWRID",
                options=["MWRID", "MWRIA", "Both"],
                description="轨道模式。",
            ),
            _param(
                "band_ids", "string", description="波段 ID 列表（逗号分隔，如 1,2,3）。"
            ),
        ],
        "node_class": "fy_daily",
    },
    {
        "type": "module/station_daily",
        "engine": "python_provider",
        "category": "遥感处理",
        "title": "站点数据处理",
        "description": "读取 ISMN/CASMOS 站点数据，生成验证产品。",
        "inputs": [
            _port("input_dir", "data:source", description="站点数据目录。"),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="过滤时间。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间过滤。"),
        ],
        "outputs": [
            _port("station_mat", "data:mat", description="站点 .mat 输出。"),
        ],
        "params": [
            _param(
                "source_type",
                "string",
                default="ISMN",
                options=["ISMN", "CASMOS"],
                description="数据源类型。",
            ),
        ],
        "node_class": "station_daily",
    },
    {
        "type": "module/inversion_daily",
        "engine": "python_provider",
        "category": "反演",
        "title": "单日反演",
        "description": "基于日常合成数据反演土壤湿度(SM)与植被光学厚度(VOD)。",
        "inputs": [
            _port("input_mat", "data:mat", description="daily_bundle 输出。"),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="目标日期。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间子集。"),
        ],
        "outputs": [
            _port("inversion_mat", "data:mat", description="反演结果 .mat。"),
        ],
        "params": [
            _param(
                "mode",
                "string",
                default="dh",
                options=["dh", "ddca"],
                description="反演模式。",
            ),
            _param(
                "freq_ghz",
                "number",
                default=1.4,
                description="频率。",
                unit="GHz",
                min_val=0.1,
                max_val=40,
                step=0.1,
            ),
        ],
        "node_class": "inversion_daily",
    },
    {
        "type": "module/block_inversion",
        "engine": "python_provider",
        "category": "反演",
        "title": "批量反演",
        "description": "基于时间序列合成数据进行批量反演。",
        "inputs": [
            _port(
                "input_mat", "data:timeseries", description="timeseries_bundle 输出。"
            ),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="时间窗口。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间子集。"),
        ],
        "outputs": [
            _port("block_mat", "data:mat", description="批量反演结果 .mat。"),
        ],
        "params": [
            _param(
                "mode",
                "string",
                default="dh",
                options=["dh", "ddca"],
                description="反演模式。",
            ),
            _param(
                "freq_ghz",
                "number",
                default=1.4,
                description="频率。",
                unit="GHz",
                min_val=0.1,
                max_val=40,
                step=0.1,
            ),
            _param(
                "pixel_chunk_size",
                "number",
                default=512,
                description="像素分块大小。",
                unit="像素",
                min_val=64,
                max_val=4096,
                step=64,
            ),
            _param(
                "write_daily_files",
                "boolean",
                default=False,
                description="是否输出每日文件。",
            ),
        ],
        "node_class": "block_inversion",
    },
    {
        "type": "module/omega_block",
        "engine": "python_provider",
        "category": "反演",
        "title": "Omega 反演",
        "description": "基于时间序列数据进行 Omega 反演，支持多种实验模式。",
        "inputs": [
            _port(
                "input_mat", "data:timeseries", description="timeseries_bundle 输出。"
            ),
            _port(
                "datasource_selection",
                "data:mat",
                required=False,
                description="可选数据源选择（与 request 绑定合并）。",
            ),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="时间窗口。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间子集。"),
            _port(
                "algorithm_params",
                "value:any",
                required=False,
                description="算法参数（通常 request 绑定）。",
            ),
            _port(
                "output_spec_extra",
                "value:any",
                required=False,
                description="输出扩展配置。",
            ),
        ],
        "outputs": [
            _port("manifest", "data", description="Omega 反演产物清单。"),
        ],
        "params": [
            _param(
                "exp_mode",
                "string",
                default="Exp0",
                options=["Exp0", "EXP1A", "EXP1B", "EXP2"],
                description="实验模式。",
            ),
            _param(
                "freq_ghz",
                "number",
                default=1.4,
                description="频率。",
                unit="GHz",
                min_val=0.1,
                max_val=40,
                step=0.1,
            ),
            _param(
                "temp_scheme", "string", default="default", description="温度方案。"
            ),
            _param(
                "write_daily_files",
                "boolean",
                default=False,
                description="是否输出每日文件。",
            ),
        ],
        "node_class": "omega_block",
    },
    {
        "type": "module/daily_bundle",
        "engine": "python_provider",
        "category": "合成",
        "title": "日常合成",
        "description": "将 SMAP、NDVI、FY 等日常产品合成为统一 .mat。",
        "inputs": [
            _port(
                "smap_daily_mat",
                "data:mat",
                required=False,
                description="SMAP 日常 .mat。",
            ),
            _port(
                "ndvi_daily_mat",
                "data:mat",
                required=False,
                description="NDVI 日常 .mat。",
            ),
            _port(
                "fy3b_folder", "data:source", required=False, description="FY3B 目录。"
            ),
            _port(
                "fy3d_folder", "data:source", required=False, description="FY3D 目录。"
            ),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="合成日期。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间对齐。"),
        ],
        "outputs": [
            _port("daily_bundle_mat", "data:mat", description="日常合成 .mat 输出。"),
        ],
        "params": [
            _param(
                "tb_source", "string", default="default", description="亮温数据源。"
            ),
            _param(
                "sm_source", "string", default="default", description="土壤湿度数据源。"
            ),
            _param("ndvi_mode", "string", default="default", description="NDVI 模式。"),
        ],
        "node_class": "daily_bundle",
    },
    {
        "type": "module/timeseries_bundle",
        "engine": "python_provider",
        "category": "合成",
        "title": "时间序列合成",
        "description": "将日常合成产品汇总为时间序列 .mat。",
        "inputs": [
            _port(
                "datasource_selection",
                "data:mat",
                description="日常 .mat 数据源选择（dataset_key→path）。",
            ),
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="序列窗口。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="空间子集。"),
            _port(
                "algorithm_params",
                "value:any",
                required=False,
                description="算法参数（通常 request 绑定）。",
            ),
            _port(
                "output_spec_extra",
                "value:any",
                required=False,
                description="输出扩展配置。",
            ),
        ],
        "outputs": [
            _port(
                "output_path",
                "data:timeseries",
                description="时间序列 .mat 路径（接 omega_block.input_mat）。",
            ),
            _port("manifest", "data", description="产物清单。"),
        ],
        "params": [
            _param(
                "tb_source", "string", default="default", description="亮温数据源。"
            ),
            _param(
                "sm_source", "string", default="default", description="土壤湿度数据源。"
            ),
        ],
        "node_class": "timeseries_bundle",
    },
    {
        "type": "module/omega_avg_daily",
        "engine": "python_provider",
        "category": "算法模块",
        "title": "OMEGA 日均 (D2)",
        "description": "从 omega_block 输出构建 DOY 气候态并回代 SM/VOD（Matlab D2）。",
        "inputs": [
            _port(
                "datasource_selection",
                "data:mat",
                required=False,
                description="D2 数据源选择（omega_block/smap/anc/ndvi 等）。",
            ),
            _port(
                "algorithm_params",
                "value:any",
                required=False,
                description="算法参数（通常 request 绑定）。",
            ),
            _port(
                "output_spec_extra",
                "value:any",
                required=False,
                description="输出扩展配置。",
            ),
        ],
        "outputs": [
            _port("manifest", "data", description="日均/回代产物清单。"),
        ],
        "params": [
            _param("target_year", "number", description="目标反演年份。"),
            _param(
                "tb_source",
                "string",
                default="SMAP",
                options=["SMAP", "FY"],
                description="亮温数据源。",
            ),
            _param(
                "temp_scheme",
                "string",
                default="ORIG_TS",
                options=["ORIG_TS", "DUAL"],
                description="温度方案。",
            ),
            _param(
                "ndvi_mode",
                "string",
                default="DOY_CLIM",
                options=["DAILY_FILE", "DOY_CLIM"],
                description="NDVI 模式。",
            ),
            _param(
                "sf_mode",
                "string",
                default="INVERTED_DAILY",
                options=["STATIC", "INVERTED_DAILY"],
                description="SF 模式。",
            ),
            _param(
                "sm_source",
                "string",
                default="SMAP",
                options=["SMAP", "ISMN", "DDCA"],
                description="土壤水分参考源。",
            ),
            _param(
                "enable_parallel",
                "boolean",
                default=True,
                description="启用并行处理。",
            ),
            _param(
                "pixel_chunk_size",
                "number",
                default=200000,
                min_val=10000,
                max_val=500000,
                step=10000,
                description="像元分块大小。",
            ),
            _param(
                "avg_build_start_year",
                "number",
                description="气候态构建起始年。",
            ),
            _param(
                "avg_build_end_year",
                "number",
                description="气候态构建结束年。",
            ),
        ],
        "node_class": "omega_avg_daily",
    },
    {
        "type": "module/omega_sf_fenkuai",
        "engine": "python_provider",
        "category": "反演",
        "title": "SF 块反演 (omega_sf)",
        "description": "SF 块反演 + OMEGA 识别：8-day 分块、逐日 SF 倒推、块级 h/alpha/OMEGA 优化、DDCA SM/VOD 反演。输出 SM/VOD/OMEGA 三图层。",
        "inputs": [
            _port(
                "datasource_selection",
                "data:source",
                required=False,
                description="数据源选择（smap_folder/anc_root/fy3d_folder 等）。",
            ),
            _port(
                "algorithm_params",
                "value:any",
                required=False,
                description="算法参数覆盖。",
            ),
        ],
        "outputs": [
            _port(
                "manifest",
                "data",
                description="产物清单（含 SM/VOD/OMEGA 三个 ProductRef）。",
            ),
        ],
        "params": [
            _param(
                "tb_source",
                "string",
                default="FY",
                options=["FY", "SMAP"],
                description="亮温数据源。",
            ),
            _param(
                "fy_platform",
                "string",
                default="3D",
                options=["3D", "3B"],
                description="FY 平台（tb_source=FY 时）。",
            ),
            _param(
                "sm_source",
                "string",
                default="SMAP",
                options=["SMAP", "ISMN", "DDCA"],
                description="土壤水分参考源。",
            ),
            _param(
                "temp_scheme",
                "string",
                default="ORIG_TS",
                options=["ORIG_TS", "DUAL"],
                description="温度方案。",
            ),
            _param(
                "sf_mode",
                "string",
                default="INVERTED_DAILY",
                options=["STATIC", "INVERTED_DAILY"],
                description="SF 模式。",
            ),
            _param(
                "sf_invert_mode",
                "string",
                default="POINT1",
                options=["POINT1", "NDVIMIN"],
                description="SF 倒推模式。",
            ),
            _param(
                "ndvi_mode",
                "string",
                default="DOY_CLIM",
                options=["DAILY_FILE", "DOY_CLIM"],
                description="NDVI 模式。",
            ),
            _param(
                "omega_fixed_mode",
                "string",
                default="PFT",
                options=["PFT", "PIXEL"],
                description="OMEGA 固定模式。",
            ),
            _param(
                "match_enable",
                "boolean",
                default=True,
                description="启用 FY3B→FY3D 匹配。",
            ),
            _param(
                "match_method",
                "string",
                default="bias",
                options=["none", "bias", "cdf"],
                description="匹配方法。",
            ),
            _param(
                "block_days",
                "number",
                default=8,
                min_val=1,
                max_val=16,
                step=1,
                unit="天",
                description="块大小。",
            ),
            _param(
                "start_date",
                "string",
                default="20250101",
                description="起始日期 YYYYMMDD。",
            ),
            _param(
                "end_date",
                "string",
                default="20251231",
                description="结束日期 YYYYMMDD。",
            ),
            _param(
                "enable_parallel",
                "boolean",
                default=True,
                description="启用并行。",
            ),
            _param(
                "pixel_chunk_size",
                "number",
                default=200000,
                min_val=10000,
                max_val=500000,
                step=10000,
                description="像元分块大小。",
            ),
        ],
        "node_class": "omega_sf_fenkuai",
    },
    {
        "type": "module/validation_metrics",
        "engine": "python_provider",
        "category": "算法模块",
        "title": "验证指标",
        "description": "r / RMSE / bias 等验证指标（Matlab metrics）。",
        "inputs": [
            _port("data", "data:mat", required=False, description="观测/模拟配对。"),
        ],
        "outputs": [
            _port("data", "data:mat", description="指标表。"),
        ],
        "params": [
            _param(
                "predicted_variable",
                "string",
                default="",
                description="predicted 文件中的变量名（空=自动选取）。",
            ),
            _param(
                "observed_variable",
                "string",
                default="",
                description="observed 文件中的变量名（空=自动选取）。",
            ),
            _param(
                "output_dir",
                "string",
                default="",
                description="输出目录（空=默认工作区 products/validation）。",
                widget="path",
            ),
        ],
        "node_class": "validation_metrics",
    },
    {
        "type": "module/statistics",
        "engine": "python_provider",
        "category": "算法模块",
        "title": "分区/时序统计",
        "description": "平台统计模块（global/zonal/landcover/timeseries），产出 ChartSpec/TableSpec。",
        "inputs": [
            _port(
                "manifest",
                "data",
                required=False,
                description="上游 product_manifest。",
            ),
            _port("data", "data", required=False, description="输入数据（可选）。"),
        ],
        "outputs": [
            _port(
                "manifest", "data", description="含 chart_spec/table_spec 的统计结果。"
            ),
        ],
        "params": [
            _param(
                "mode",
                "string",
                default="global",
                options=["global", "zonal", "landcover", "timeseries"],
                description="统计模式。",
            ),
            _param(
                "variable",
                "string",
                default="",
                description="待统计变量名（空=自动选取）。",
            ),
            _param(
                "zones_source",
                "string",
                default="",
                description="分区数据文件路径（zonal/landcover 模式必需）。",
                widget="path",
            ),
            _param(
                "output_dir",
                "string",
                default="",
                description="输出目录（空=默认工作区）。",
                widget="path",
            ),
        ],
        "executable": True,
        "node_class": "statistics",
    },
    {
        "type": "module/curve_fitting",
        "engine": "python_provider",
        "category": "算法模块",
        "title": "曲线拟合",
        "description": "平台曲线拟合模块。",
        "inputs": [
            _port("data", "data", required=False, description="输入数据。"),
        ],
        "outputs": [
            _port("data", "data", description="拟合结果。"),
        ],
        "params": [
            _param(
                "method",
                "string",
                default="linear",
                options=["linear", "polynomial", "exponential"],
                description="拟合方法。",
            ),
            _param(
                "degree",
                "number",
                default=2,
                min_val=1,
                max_val=10,
                step=1,
                description="多项式阶数（method=polynomial 时）。",
            ),
            _param(
                "variable",
                "string",
                default="",
                description="待拟合变量名（空=自动选取）。",
            ),
            _param(
                "output_dir",
                "string",
                default="",
                description="输出目录（空=默认工作区）。",
                widget="path",
            ),
        ],
        "node_class": "curve_fitting",
    },
    {
        "type": "module/data_export",
        "engine": "python_provider",
        "category": "算法模块",
        "title": "数据导出",
        "description": "导出中间/最终产物。",
        "inputs": [
            _port("data", "data", required=False, description="待导出数据。"),
        ],
        "outputs": [
            _port("path", "value:string", description="导出路径。"),
        ],
        "params": [
            _param(
                "format",
                "string",
                default="mat",
                options=["mat", "netcdf", "geotiff", "csv"],
                description="导出格式。",
            ),
            _param(
                "variables",
                "string",
                default="",
                description="逗号分隔的变量名列表（空=导出全部）。",
            ),
            _param(
                "output_dir",
                "string",
                default="",
                description="输出目录（空=默认工作区）。",
                widget="path",
            ),
        ],
        "node_class": "data_export",
    },
    # ═══ GIS 基础工具模块 ═══════════════════════════════════════════════════════
    {
        "type": "gis/buffer_analysis",
        "engine": "python_provider",
        "category": "GIS工具",
        "title": "缓冲区分析",
        "description": "对矢量点/线/面创建缓冲区。",
        "inputs": [
            _port("points", "data:geojson", description="输入矢量要素 GeoJSON。"),
            _port("distance", "value:number", description="缓冲距离。"),
        ],
        "outputs": [
            _port("buffer", "data:geojson", description="缓冲区 GeoJSON。"),
        ],
        "params": [
            _param(
                "distance_unit",
                "string",
                default="meters",
                options=["meters", "kilometers", "degrees"],
                description="缓冲距离单位。",
            ),
            _param(
                "segments",
                "number",
                default=16,
                description="圆弧段数（曲线光滑度）。",
                min_val=3,
                max_val=128,
                step=1,
            ),
        ],
        "executable": True,
        "node_class": "gis_buffer_analysis",
    },
    {
        "type": "gis/zonal_statistics",
        "engine": "python_provider",
        "category": "GIS工具",
        "title": "分区统计",
        "description": "按矢量分区计算栅格统计量。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格。"),
            _port("zones", "data:geojson", description="分区矢量 GeoJSON。"),
        ],
        "outputs": [
            _port("stats", "data:geojson", description="分区统计结果 GeoJSON。"),
        ],
        "params": [
            _param(
                "statistic",
                "string",
                default="mean",
                options=["mean", "median", "sum", "min", "max", "count"],
                description="统计量类型。",
            ),
            _param(
                "band",
                "number",
                default=0,
                description="波段索引。",
                min_val=0,
                max_val=100,
                step=1,
            ),
            _param(
                "all_touched",
                "boolean",
                default=False,
                description="是否统计所有接触像元（否则仅统计中心点在内的像元）。",
            ),
        ],
        "executable": True,
        "node_class": "gis_zonal_statistics",
    },
    {
        "type": "gis/raster_calculator",
        "engine": "python_provider",
        "category": "GIS工具",
        "title": "栅格计算器",
        "description": "对栅格执行数学表达式运算（如 A*2 + B）。",
        "inputs": [
            _port("a", "data:raster", description="输入栅格 A。"),
            _port(
                "b", "data:raster", required=False, description="输入栅格 B（可选）。"
            ),
        ],
        "outputs": [
            _port("result", "data:raster", description="计算结果栅格。"),
        ],
        "params": [
            _param(
                "expression",
                "string",
                default="A",
                description="表达式，变量名 A/B/C，支持 + - * / ** 等。",
            ),
            _param(
                "nodata_handling",
                "string",
                default="propagate",
                options=["propagate", "zero", "ignore"],
                description="NoData 处理方式。",
            ),
        ],
        "executable": True,
        "node_class": "gis_raster_calculator",
    },
    {
        "type": "gis/vector_to_raster",
        "engine": "python_provider",
        "category": "GIS工具",
        "title": "矢量转栅格",
        "description": "将矢量数据栅格化为栅格图层。",
        "inputs": [
            _port("vector", "data:geojson", description="输入矢量 GeoJSON。"),
            _port("bbox", "geometry:bbox", description="输出栅格范围。"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="栅格化结果。"),
        ],
        "params": [
            _param(
                "attribute_field", "string", description="用于赋值的矢量属性字段名。"
            ),
            _param(
                "resolution",
                "number",
                default=1000,
                description="输出分辨率。",
                unit="米",
                min_val=1,
                max_val=100000,
                step=1,
            ),
            _param(
                "dtype",
                "string",
                default="float32",
                options=["float32", "int32", "uint8"],
                description="输出数据类型。",
            ),
            _param("fill_value", "number", default=0, description="背景填充值。"),
        ],
        "executable": True,
        "node_class": "gis_vector_to_raster",
    },
    {
        "type": "gis/raster_to_vector",
        "engine": "python_provider",
        "category": "GIS工具",
        "title": "栅格转矢量",
        "description": "将栅格数据转换为矢量多边形或等值线。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格。"),
        ],
        "outputs": [
            _port("vector", "data:geojson", description="矢量化结果 GeoJSON。"),
        ],
        "params": [
            _param(
                "band",
                "number",
                default=0,
                description="波段索引。",
                min_val=0,
                max_val=100,
                step=1,
            ),
            _param(
                "threshold",
                "number",
                default=0,
                description="阈值化（大于此值的像元转矢量）。",
            ),
            _param(
                "simplify_tolerance",
                "number",
                default=0,
                description="简化容差。",
                unit="米",
                min_val=0,
                max_val=10000,
                step=1,
            ),
        ],
        "executable": True,
        "node_class": "gis_raster_to_vector",
    },
    {
        "type": "gis/reclassify",
        "engine": "python_provider",
        "category": "GIS工具",
        "title": "重分类",
        "description": "按重映射表对栅格值重新分类。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格。"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="重分类后栅格。"),
        ],
        "params": [
            _param(
                "remap_table",
                "string",
                default="",
                description='重映射表，逗号分隔如 "0-30:1,30-60:2,60-100:3"',
            ),
            _param(
                "nodata_value", "number", default=-9999, description="输出 NoData 值。"
            ),
        ],
        "executable": True,
        "node_class": "gis_reclassify",
    },
    {
        "type": "gis/contour",
        "engine": "python_provider",
        "category": "GIS工具",
        "title": "等值线提取",
        "description": "从栅格表面提取等值线。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格表面（如 DEM）。"),
        ],
        "outputs": [
            _port("contours", "data:geojson", description="等值线 GeoJSON。"),
        ],
        "params": [
            _param(
                "interval",
                "number",
                default=100,
                description="等值线间距。",
                min_val=0.01,
                max_val=10000,
                step=0.01,
            ),
            _param(
                "band",
                "number",
                default=0,
                description="波段索引。",
                min_val=0,
                max_val=100,
                step=1,
            ),
            _param(
                "smoothing", "boolean", default=True, description="是否平滑等值线。"
            ),
        ],
        "executable": True,
        "node_class": "gis_contour",
    },
    {
        "type": "gis/slope_aspect",
        "engine": "python_provider",
        "category": "GIS工具",
        "title": "坡度坡向",
        "description": "从 DEM 计算坡度（度）和坡向（度）。",
        "inputs": [
            _port("dem", "data:raster", description="输入 DEM 栅格。"),
        ],
        "outputs": [
            _port("slope", "data:raster", description="坡度栅格（度）。"),
            _port("aspect", "data:raster", description="坡向栅格（度，0=北 90=东）。"),
        ],
        "params": [
            _param(
                "z_unit",
                "string",
                default="meters",
                options=["meters", "feet"],
                description="高程单位。",
            ),
            _param(
                "algorithm",
                "string",
                default="horn",
                options=["horn", "zevenbergen"],
                description="坡度算法。",
            ),
        ],
        "executable": True,
        "node_class": "gis_slope_aspect",
    },
    {
        "type": "gis/watershed",
        "engine": "python_provider",
        "category": "GIS工具",
        "title": "流域分析",
        "description": "基于 DEM 和出水点提取流域边界。",
        "inputs": [
            _port("dem", "data:raster", description="输入 DEM 栅格。"),
            _port("pour_points", "data:geojson", description="出水点 GeoJSON。"),
        ],
        "outputs": [
            _port("watershed", "data:geojson", description="流域边界 GeoJSON。"),
        ],
        "params": [
            _param(
                "fill_threshold",
                "number",
                default=0.01,
                description="填洼阈值。",
                min_val=0,
                max_val=1,
                step=0.01,
            ),
            _param(
                "flow_direction",
                "string",
                default="d8",
                options=["d8", "dinf"],
                description="流向算法。",
            ),
        ],
        "executable": True,
        "node_class": "gis_watershed",
    },
    # ═══ GEE 节点 ═════════════════════════════════════════════════════════════
    {
        "type": "gee/image",
        "engine": "gee",
        "category": "GEE-数据",
        "title": "GEE 影像加载",
        "description": "从 Google Earth Engine 加载影像 Asset。",
        "inputs": [
            _port(
                "time_range",
                "value:time_range",
                required=False,
                description="影像日期过滤。",
            ),
            _port("bbox", "geometry:bbox", required=False, description="感兴趣区。"),
        ],
        "outputs": [
            _port("image", "data:raster", description="GEE 影像对象。"),
        ],
        "params": [
            _param("asset_id", "string", description="GEE Asset ID。"),
        ],
        "node_class": "gee_image",
    },
    {
        "type": "gee/cloud_mask",
        "engine": "gee",
        "category": "GEE-处理",
        "title": "云掩膜",
        "description": "对 Sentinel-2 影像执行云掩膜。",
        "inputs": [
            _port("image", "data:raster", description="输入影像。"),
        ],
        "outputs": [
            _port("masked", "data:raster", description="掩膜后影像。"),
        ],
        "params": [],
        "node_class": "gee_cloud_mask",
    },
    {
        "type": "gee/clip",
        "engine": "gee",
        "category": "GEE-处理",
        "title": "裁剪",
        "description": "按空间范围裁剪影像。",
        "inputs": [
            _port("image", "data:raster", description="输入影像。"),
            _port("geometry", "geometry:bbox", description="裁剪范围。"),
        ],
        "outputs": [
            _port("clipped", "data:raster", description="裁剪后影像。"),
        ],
        "params": [],
        "node_class": "gee_clip",
    },
    {
        "type": "gee/select_bands",
        "engine": "gee",
        "category": "GEE-处理",
        "title": "波段选择",
        "description": "选择或重命名影像波段。",
        "inputs": [
            _port("image", "data:raster", description="输入影像。"),
        ],
        "outputs": [
            _port("image", "data:raster", description="波段选择后影像。"),
        ],
        "params": [
            _param(
                "bands",
                "array",
                default=[],
                description="要选择的波段列表（逗号分隔）。",
            ),
            _param(
                "rename",
                "array",
                default=[],
                description="重命名后的波段列表（逗号分隔）。",
            ),
        ],
        "node_class": "gee_select_bands",
    },
]


# ─── 时空维度端口注入 ─────────────────────────────────────────────────────────
# 设计约定见前端 dimension-model.ts：
# - time_range / bbox 表示「本次运行过滤窗口」
# - 数据源 params 声明「原生」时间/空间字段与分辨率
# - 未连接时可由主界面时间轴 / 地图视口注入
_PARAM_ONLY_TYPES = frozenset(
    {
        "data/time_range",
        "data/bbox",
        "data/map_viewport",
        "data/number",
        "data/string",
        "data/boolean",
        "data/latlng",
    }
)

_TIME_PREFIXES = (
    "module/",
    "weather/",
    "gee/",
    "stats/",
    "fusion/",
    "viz/",
)

_SPACE_PREFIXES = (
    "module/",
    "weather/",
    "gee/",
    "stats/",
    "fusion/",
    "viz/",
    "preprocess/",
    "gis/",
)


def _input_names(tpl: dict[str, Any]) -> set[str]:
    return {str(p.get("name")) for p in tpl.get("inputs", [])}


def _wants_time_range(node_type: str) -> bool:
    if node_type in _PARAM_ONLY_TYPES or node_type.startswith("output/"):
        return False
    if node_type == "data/source":
        return True
    return node_type.startswith(_TIME_PREFIXES)


def _wants_bbox(node_type: str) -> bool:
    if node_type in _PARAM_ONLY_TYPES or node_type.startswith("output/"):
        return False
    if node_type == "data/source":
        return True
    # gee/clip 已有 geometry:bbox，不再强制加同名 bbox
    if node_type == "gee/clip":
        return False
    return node_type.startswith(_SPACE_PREFIXES)


def _ensure_dimension_ports(templates: list[dict[str, Any]]) -> None:
    """为消费时空窗口的节点补齐可选 time_range / bbox 输入（幂等）。"""
    for tpl in templates:
        node_type = str(tpl.get("type", ""))
        inputs: list[dict[str, Any]] = list(tpl.get("inputs") or [])
        names = {str(p.get("name")) for p in inputs}
        changed = False

        if _wants_time_range(node_type) and "time_range" not in names:
            inputs.insert(
                0,
                _port(
                    "time_range",
                    "value:time_range",
                    required=False,
                    description="可选时间过滤窗口（分辨率/字段映射见「时间范围」节点）。",
                ),
            )
            names.add("time_range")
            changed = True

        if _wants_bbox(node_type) and "bbox" not in names and "geometry" not in names:
            # 插在 time_range 之后，数据端口之前
            insert_at = 1 if "time_range" in names else 0
            # 若刚插入 time_range，它在 index 0
            if "time_range" in names:
                for i, p in enumerate(inputs):
                    if p.get("name") == "time_range":
                        insert_at = i + 1
                        break
            inputs.insert(
                insert_at,
                _port(
                    "bbox",
                    "geometry:bbox",
                    required=False,
                    description="可选空间过滤窗口（AOI）。视口请接「地图视口」。",
                ),
            )
            changed = True

        if changed:
            tpl["inputs"] = inputs


_ensure_dimension_ports(_NODE_TEMPLATES)


# ─── 门户/存储动态 options ───────────────────────────────────────────────────
# http_open_data 的 preset/cred_profile 与 remote_fetch 的 cred_profile 选项
# 在查询时动态注入（目录/存储 profile 运行时可编辑；硬编码列表仅作兜底）。

_PORTAL_OPTIONS_TTL_SECONDS = 30.0
_portal_options_cache: dict[str, list[str]] | None = None
_portal_options_cached_at: float = 0.0

_FALLBACK_PRESET_OPTIONS = [
    "noaa_nomads",
    "noaa_goes",
    "nasa_earthdata",
    "nasa_cmr",
    "nsidc_data",
    "nasa_ges_disc",
    "nasa_gldas",
    "esa_copernicus",
    "esa_download",
    "cma_nsmc",
    "cma_data",
]
_FALLBACK_PORTAL_CRED_OPTIONS = ["", "earthdata", "nsidc", "copernicus"]

_DYNAMIC_OPTION_NODES = frozenset(
    {"download/http_open_data", "download/remote_fetch", "download/ssh_sync"}
)

# ssh_sync 可直接选用的远程存储协议（SFTP 直连 / FileBrowser REST）
_SSH_SYNC_PROFILE_PROTOCOLS = frozenset({"ssh", "sftp", "filebrowser"})
_SSH_SYNC_LEGACY_SERVERS = ["hpc", "win11", "nas"]


def invalidate_portal_options_cache() -> None:
    """门户/存储目录变更后失效动态 options 缓存。"""
    global _portal_options_cache, _portal_options_cached_at
    _portal_options_cache = None
    _portal_options_cached_at = 0.0


def _dynamic_portal_options() -> dict[str, list[str]]:
    global _portal_options_cache, _portal_options_cached_at
    import time

    now = time.monotonic()
    if (
        _portal_options_cache is not None
        and now - _portal_options_cached_at < _PORTAL_OPTIONS_TTL_SECONDS
    ):
        return _portal_options_cache

    presets = list(_FALLBACK_PRESET_OPTIONS)
    portal_creds = list(_FALLBACK_PORTAL_CRED_OPTIONS)
    remote_creds: list[str] = []
    ssh_servers = list(_SSH_SYNC_LEGACY_SERVERS)
    try:
        from app.services.portal_catalog import known_portal_ids, list_portal_defs

        presets = list(list_portal_defs().keys())
        portal_creds = [""] + sorted(known_portal_ids())
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.config_remote_storage import list_remote_storage_profiles

        profiles = list_remote_storage_profiles()
        remote_creds = [
            str(p.get("profile_id"))
            for p in profiles
            if str(p.get("profile_id") or "").strip()
        ]
        ssh_servers += [
            str(p["profile_id"])
            for p in profiles
            if str(p.get("protocol") or "").lower() in _SSH_SYNC_PROFILE_PROTOCOLS
            and p.get("enabled") is not False
            and str(p.get("profile_id") or "").strip()
        ]
    except Exception:  # noqa: BLE001
        pass

    _portal_options_cache = {
        "presets": presets,
        "portal_creds": portal_creds,
        "remote_creds": remote_creds,
        "ssh_servers": ssh_servers,
    }
    _portal_options_cached_at = now
    return _portal_options_cache


def _apply_dynamic_options(tpl: dict[str, Any]) -> dict[str, Any]:
    if tpl.get("type") not in _DYNAMIC_OPTION_NODES:
        return tpl
    options = _dynamic_portal_options()
    params: list[dict[str, Any]] = []
    for p in tpl.get("params") or []:
        p = dict(p)
        key = p.get("key")
        if tpl["type"] == "download/http_open_data":
            if key == "preset":
                p["options"] = list(options["presets"])
                if p.get("default") not in p["options"] and p["options"]:
                    p["default"] = p["options"][0]
            elif key == "cred_profile":
                p["options"] = list(options["portal_creds"])
                p["allow_custom"] = True
        elif tpl["type"] == "download/remote_fetch":
            if key == "cred_profile" and options["remote_creds"]:
                p["options"] = list(options["remote_creds"])
                p["allow_custom"] = True
        elif tpl["type"] == "download/ssh_sync":
            if key == "server_type" and options["ssh_servers"]:
                p["options"] = list(options["ssh_servers"])
                p["allow_custom"] = True
        params.append(p)
    out = dict(tpl)
    out["params"] = params
    return out


# ─── 查询接口 ────────────────────────────────────────────────────────────────
def get_all_node_templates() -> list[dict[str, Any]]:
    """返回所有节点模板的列表。"""
    return [_apply_dynamic_options(dict(t)) for t in _NODE_TEMPLATES]


def get_node_templates_by_engine(engine: str) -> list[dict[str, Any]]:
    """按引擎过滤节点模板。"""
    return [
        _apply_dynamic_options(dict(t))
        for t in _NODE_TEMPLATES
        if t["engine"] == engine
    ]


# 历史种子/画布类型别名 → 现行注册 type（避免画布出现「未定义」节点）
_NODE_TYPE_ALIASES: dict[str, str] = {
    "algorithm/omega_avg_daily": "module/omega_avg_daily",
    "remote_fetch": "download/remote_fetch",
    "module/fy_preprocess": "download/fy_preprocess",
    "module/fy_download": "download/fy_download",
}


def resolve_node_type(node_type: str) -> str:
    """将历史/别名节点 type 归一为注册表中的规范 type。"""
    return _NODE_TYPE_ALIASES.get(node_type, node_type)


def get_node_template(node_type: str) -> dict[str, Any] | None:
    """按类型获取单个节点模板（支持历史别名）。"""
    canonical = resolve_node_type(node_type)
    for t in _NODE_TEMPLATES:
        if t["type"] == canonical:
            return _apply_dynamic_options(dict(t))
    return None


def get_node_template_summary() -> list[dict[str, str]]:
    """返回节点模板摘要列表（仅 type, engine, category, title）。"""
    return [
        {
            "type": t["type"],
            "engine": t["engine"],
            "category": t["category"],
            "title": t["title"],
        }
        for t in _NODE_TEMPLATES
    ]
