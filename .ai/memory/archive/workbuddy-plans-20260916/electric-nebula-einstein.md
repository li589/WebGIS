# CGDA 两阶段实施计划

## 阶段 1：六源在线下载验证（#58）

**新建** `Tools/dataset_download_verify.py`（不要下划线开头，`Tools/_*.py` 被 gitignore）。

### 导入方式（已核实，参考 Tools/nsmc_online_probe.py:67-82）
```python
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"))  # import ingest.*
sys.path.insert(0, str(REPO_ROOT / "Code" / "backend"))
os.chdir(REPO_ROOT / "Code" / "backend")  # settings 依赖 cwd
from app.services.config_service import get_portal_credentials_runtime
```

### 脚本结构
- argparse：`--sources nomads,cmr,gldas,smap,cds,cdse` / `--all` / `--report <json路径>`
- 每源独立 try/except 互不阻断；退出码：全过 0，有失败 1
- 凭据：`get_portal_credentials_runtime()`（config_service.py:698）返回解密 dict，键取 `earthdata`/`esa_copernicus`（多键容错，accounts[0]）；CDS 优先 `os.getenv("BACKEND_CDS_API_KEY")`；凭据只记 ok/missing，**不落日志**
- 落盘：`Tools/reports/dataset_verify_tmp/<source>/`（gitignore 区，不污染 DATA_ROOT），保留供人工检查

### 各源最小验证（签名已核实）
| 源 | 调用 | 最小参数 |
|---|---|---|
| NOMADS | `ingest.nomads_download.download_nomads_grib(date, model, *, product, fxx, search_string, target_dir, use)` (nomads_download.py:176) | date="latest", model="gfs", product="pgrb2.0p25", fxx=0, search_string=":TMP:2 m above ground:" |
| CMR | urllib GET `https://cmr.earthdata.nasa.gov/search/granules.json?short_name=SPL3SMP_E&page_size=1&temporal=<昨日,...>`（复刻 data_access_nodes.py:846-855） | 单日单 granule 检索 |
| GLDAS | `ingest.gldas_download.download_gldas_range(*, start_date, end_date, local_dir, username, password, max_files)` (gldas_download.py:269) | 单日（昨日），max_files=1，Earthdata 账密 |
| SMAP | `ingest.nsidc_download.download_smap_range(start_date, end_date, local_dir, *, username, password, max_files)` (nsidc_download.py:552) | 单日，max_files=1 |
| CDS | `ingest.cds_download.download_via_cdsapi(dataset, request, target, *, api_key)` (cds_download.py:120) | dataset="reanalysis-era5-single-levels"，单日+极小 area+`download_format:"unarchived"` |
| CDSE | `exchange_cdse_token` (cdse_download.py:142) → `search_by_odata_filter(page_size=1)` → `download_product_value` | 近期小产品（如 S2GRD 单景），下载 1 个 |

### 校验与报告
- 每源：凭据获取 → 检索 → 下载 → `st_size > 0` 校验 → duration_ms/bytes/error 分类（credential/search/download/network/unknown）
- 报告 JSON：`Tools/reports/dataset_download_verify_<date>.json`
- 运行：`Env\Python312\python.exe Tools\dataset_download_verify.py --all`
- **NSMC 后补**：用户手动预热会话后追加（脚本预留 `nsmc` 源占位，检测会话缓存缺失时报告 "skipped: session not warm"）

### 阶段 1 提交
- `feat(tools): 六源数据集在线下载最小验证脚本（#58）`
- 验证结论摘要写入 commit message + `Docs/06-代码审查/dataset-verify-2026-08-21.md`（简短记录各源结果，可入库）；NSMC 标注"待会话预热后补验"

## 阶段 2：全量代码审查（报告 + 修 P0/P1）

**报告位置**：`Docs/06-代码审查/`（既有惯例入库）；命名 `code-review-2026-08-21-{security-concurrency,ui-sync,algo-hygiene}.md` + 汇总 `code-review-2026-08-21-summary.md`。

### 审查执行：3 个并行 agent
**Agent A（后端安全与并发）** Code/backend/app：
- 安全 grep：`logger.*(password|secret|token|api_key)`、`except.*pass`、`eval\(|exec\(`、`shell=True`、`os.system`、`urlopen|requests.(get|post)\(` 无 timeout、用户可控 URL（SSRF）、`os.path.join` 拼接用户输入（路径穿越）
- 并发 grep：`threading\.(Lock|RLock|Event)` 成对使用、模块级可变全局、`asyncio.` 与线程混用、`run_in_executor` 共享 session、缺锁的 check-then-act

**Agent B（前端 UI 同步）** Code/frontend/src：
- grep：`watch\(` 依赖缺失/deep、`v-if` 挂异步数据、`onMounted` 未捕获 rejection、store 与本地 state 双份不同步、`v-for` 无 `:key`、竞态（连续请求旧响应覆盖）、loading/error 态缺失、`setTimeout` 未清理

**Agent C（算法包与管理卫生）** Code/algorithms/providers/Python + Tools + launch：
- grep：`TODO|FIXME|HACK|XXX` 残留、硬编码盘符（`I:|D:\`）、死代码、文档过时（README/AGENTS.md 与实际不符）、重复实现

### 报告结构
P0（安全泄漏/数据竞争）/ P1（功能 bug/资源泄漏）/ P2（细节风格）；每条：`文件:行号` + 证据片段 + 修复建议 + 影响面。**报告中不得出现凭据明文**。

### 修复流程
1. 主 agent 复核 agent 报告（去误报）→ 按汇总逐项修 P0→P1（P2 仅记录）
2. Commit 拆分：`fix(security)` / `fix(concurrency)` / `fix(ui)` / `chore(cleanup)`（每类一个）
3. 回归（修正路径——测试在 Test/ 下）：
   - `Env/Python312/python.exe -m pytest Test/backend -q`
   - `Env/Python312/python.exe -m pytest Test/algorithms -q`
   - `cd Code/frontend && npm run test`
   - 涉及安全依赖变更时 `npm run check:openapi`（F14 闸门）
4. 全量推送 `git push origin dev`

## 关键文件清单
- 新建：`Tools/dataset_download_verify.py`、`Docs/06-代码审查/code-review-2026-08-21-*.md`（4 份）、`Docs/06-代码审查/dataset-verify-2026-08-21.md`
- 参考：`Tools/nsmc_online_probe.py`（import 模式）
- 依赖（只读）：`Code/algorithms/providers/Python/ingest/{nomads,gldas,nsidc,cds,cdse}_download.py`、`Code/backend/app/services/config_service.py:698`

## 执行顺序
1. 写验证脚本 → 跑 6 源 → 修复脚本问题（如有）→ 记录结果 → commit + push
2. 3 个审查 agent 并行 → 主 agent 复核汇总 → 修 P0/P1 → 回归 → 分批 commit + push
