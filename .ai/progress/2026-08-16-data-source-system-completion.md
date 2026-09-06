# 数据源管理系统完善：M1–M6 全量完成（2026-08-16）

计划：`.trae/documents/数据源管理系统完善计划.md`（brooks-lint 架构审计 78/100 → 全量推进方案）。
本文记录六个里程碑的交付物与本轮全量验证矩阵。**改动尚未 commit**（待用户指示；提交须遵守 `git add -A` 全量暂存硬约定）。

## 里程碑交付物

| 里程碑 | 交付物 |
|--------|--------|
| M1/P0 依赖固化 | `Code/backend/requirements.txt` + 算法包 requirements：`cdsapi` / `herbie`（可降级可选）/ `cfgrib`+`xarray` 版本固化，`earthaccess` 已在 |
| M2/P1 检索分发 | `portal_catalog`：CDS 数据集检索分发 + CDSE OData 分发，`/config/portals` 检索链衔接 `search_portal` |
| M3/P2a–c 下载模块 | `ingest/cds_download.py` / `nomads_download.py` / `cdse_download.py`（主路径 cdsapi/herbie/OData，回退 legacy 直链共享 Range 续传）+ 节点 `modules/` 同名包装 + 测试 |
| M3/P2d 共享工具 | `ingest/_http_resume.py`：Range 断点续传/指数退避下沉共享，三新模块 + NSIDC 复用，单测覆盖 |
| M3/P2e earthaccess 默认化 | `http_open_data`：主路径 `earthaccess`，回退 CMR+requests（静默回退记 warning），对齐 `nsidc_download.py` 先例 |
| M3/P2f 注册三件套 | 后端节点注册表 3 模板（cmr_search 后）、前端 `node-forms/` 3 表单 + dispatch/path map、seeds；portal 凭据键（`ecmwf_cds` 等）对齐 `PortalCredHint` |
| M4/P3 后端续传 | `source_fetcher`：Range 断点续传（大文件中断续传不再整文件重来），门户下载链与算法链语义对齐 |
| M5/P4 GRIB 一等公民 | `raster_science`：`_open_grib_dataset` / `_grib_geo_bounds` / `_list_grib` / `_load_grib_2d`（inspect 枚举变量 → commit 抽取 GeoTIFF，bounds 取 cfgrib 经纬坐标外扩半格）；`upload_validation` 放行 `.grib2`（魔数 GRIB）；`data_access/format_adapters/grib_file.py` + registry/contracts 注册；`variable_extract` / `format_convert` 节点支持 GRIB；离线 fixture `Test/algorithms/fixtures/grib2_t2m_2x2.grib2`（生成器入库：centre=kwbc + heightAboveGround level=2 才解析出 `t2m`，末格 bitmap 缺测 → NaN） |
| M6/P5 文档同步 | `Docs/03-规范协议/远程存储接入说明.md`（新节点 + 主/回退矩阵 + GRIB 消费链 + 依赖）；`.ai/skills/multi-source-data-ingestion.md`（CDS/NOMADS/CDSE 通道表 + 验证路径修正 `Test/` + GRIB 已知坑）；`当前数据源与产出一览.md`（专用源下载节点条目）；`数据源与工作流对照说明-2026-07-21.md`（ECMWF 风场再分析待下载项 → 标注 CDS/NOMADS 获取路径） |

## 全量验证矩阵（2026-08-16，Env/Python312）

| 检查 | 命令（等价） | 结果 |
|------|--------------|------|
| ruff lint | `python -m ruff check Code/backend/app Code/algorithms/providers/Python` | 通过 |
| ruff format | `python -m ruff format --check …` | 4 文件重排后全 470 clean |
| mypy | `python -m mypy --config-file=Code/backend/mypy.ini …` | 470 文件 0 issue |
| pytest 后端 | `-m pytest Test/backend`（fresh basetemp） | **exit 0 全量通过** |
| pytest 算法 | `-m pytest Test/algorithms` | 514 passed + 28 subtests；格式化后补验相关 5 文件 104 passed |
| vitest | `vitest run`（分批） | 全部 144 文件通过（133 主跑 944 tests + 11 文件 `--maxWorkers=1` 补跑 127 tests，0 失败） |
| eslint | `npm run lint` | 0 errors（2 既有 warning 在未改动的 MultiOverlayBarChart.vue） |
| prettier | `npm run format:check` | clean |
| build | `npm run build` | ✓ 5.6s |
| 契约 | `check:catalog` / `check:openapi` | 52 items + 7 categories 同步；OpenAPI 指纹同步 |

## 环境注意事项（本轮实证）

1. **沙箱无 git**：`pre-commit run --all-files` 本体不可跑，以上为逐钩子等价直检（ruff/ruff-format/mypy/eslint/prettier/check-yaml 等语义等价；conventional commit-msg 钩子在提交时生效）。
2. **`Test\.pytest-be` basetemp 已损坏**：任何复用它的 pytest 运行会产出大量 `PermissionError [WinError 5]` 伪故障（299 errors + 7 failed 假象）。必须每次用全新 `--basetemp`（本轮用 `Test\.pytest-be-vfy1`）。损坏目录待人工删除。
3. **vitest worker 启动超时为沙箱环境噪声**：慢机器上最重的一批测试文件（settings/views/services 系）偶发 `Failed to start forks worker ... Timeout`，换批运行均通过；可信判定标准是"每个文件至少一次全绿"，而非单次 run 的 exit code。
4. PowerShell job host 中 `*>` 文件重定向对长时间 native 输出不可靠（截断为空），完整输出应依赖 job 自身 output.log + `Select-String` 解析。

## 用户待办

1. 改动 **未提交**；如需提交，按 `.ai/rules/git-commit-message.md`（Conventional Commits）+ 全量 `git add -A` 硬约定执行（建议拆分：feat(algorithms) 下载模块三件套 / feat(backend) 注册+续传+GRIB / test+docs）。
2. 人工删除损坏的 `Test\.pytest-be` 目录（以及可顺手清理其他 `.pytest-*` 残留）。
3. ECMWF 风场再分析实际拉取：配置门户凭据 `ecmwf_cds` 后经 `download/cds_download` 节点（ERA5 wind NetCDF）；NOMADS 预报风场走 `download/nomads_grib_download`（GRIB2 → inspect/commit 转 GeoTIFF）。
