# 提取可复用 ingest 模块：remote_sync.py 与 nsidc_download.py

## 摘要

从 `Tools/sync_server_data.py` 与 `Tools/download_smap_nsidc.py` 两个 CLI 脚本中提取核心逻辑，
形成两个可导入、无 CLI 依赖的库模块，放入
`Code/algorithms/providers/Python/ingest/`：

1. `ingest/remote_sync.py` —— 远程数据集同步（SSH/SFTP via paramiko + FileBrowser REST API）
2. `ingest/nsidc_download.py` —— NASA NSIDC SMAP 数据下载（CMR 搜索 + earthaccess/requests 双路径）

两个文件均使用 `from __future__ import annotations`，遵循 `ingest/` 目录既有风格
（参考 `ingest/fy_preprocess.py`、`ingest/smap.py`、`ingest/ndvi_hdf_preprocess.py`：
模块级 `logger = logging.getLogger(__name__)`、`@dataclass(frozen=True, slots=True)`、
可选依赖延迟导入），不含 `argparse`、不含 `if __name__ == "__main__"`。

---

## 现状分析

### 源脚本

- `Tools/sync_server_data.py`（944 行）：CLI 脚本，通过 paramiko SSH/SFTP 把校园网 HPC
  （`likr6008@172.16.98.184`）的多源数据集增量同步到 `I:\Geograph_DataSet`。
  核心类 `ServerDataSynchronizer` 含连接管理、`walk_remote` 递归遍历、`download_file`
  （断点续传）、增量跳过（`classify_local` 按大小判断）。硬编码了 `ACCESS_METHODS`
  （direct/tunnel/jump）、`DATA_SOURCES`（9 个数据源）、私钥路径、`LOCAL_BASE`。
  仅支持 SSH/SFTP，不含 FileBrowser。

- `Tools/download_smap_nsidc.py`（683 行）：CLI 脚本，从 NSIDC 下载 SPL3SMP_E V6 SMAP 数据。
  含 CMR UMM-JSON 搜索（`_search_via_cmr`）、earthaccess 搜索/登录、`requests`+HTTPBasicAuth
  回退、断点续传（HTTP Range）、指数退避重试、磁盘空间检查、增量跳过。
  硬编码了默认凭据 `Rejoyce/Diandian143`、输出目录、日志目录。

### FileBrowser API 权威实现（本项目已验证可用）

`Tools/remote_data_scanner.py::FileBrowserClient` 是本项目已跑通的 FileBrowser 客户端，
`remote_sync.py` 的 FileBrowser 部分必须严格对齐其行为（已通过阅读源码确认）：

- 登录：`POST /api/login`，body `{"username":...,"password":...}`，
  响应体即 token 字符串（需 `.strip().strip('"')`）。请求头须含
  `Content-Type: application/json` 与 `User-Agent`。
- 认证头：`X-Auth: <token>`（**非** `Authorization: Bearer`）。
- 列目录：`GET /api/resources/{encoded_path}`，头含 `User-Agent`、`X-Auth`、`Accept: application/json`。
  响应根目录为 `{"items":[...]}` 字典，子目录为 list —— 两种格式都要处理。
  每项字段：`name`、`size`、`extension`、`isDir`（bool，目录判定唯一依据）、`type`、`modified`。
- 下载：`GET /api/raw/{encoded_path}`，流式写入本地。
- 路径编码：`urllib.parse.quote(path.strip("/"), safe="/")`。
- 401/403 自动重新登录并重试一次；404 返回空列表。
- 强制 `User-Agent`（Cloudflare 隧道否则 403）：
  `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36`。
- 使用 stdlib `urllib.request` + `ssl.create_default_context()`，**不引入 requests 依赖**。

### Lint/类型检查范围

`.pre-commit-config.yaml` 中 ruff 与 mypy 的 `files` 正则为
`^(Code/backend/app|Code/algorithms/providers/Python/algorithms)/.+\.py$`，
**不覆盖 `ingest/` 目录**。但 `check-ast`、`trailing-whitespace`、`end-of-file-fixer`、
`detect-private-key`、`check-added-large-files` 对全仓库生效。因此新文件须：
语法正确、无尾随空白、文件末尾换行、不含私钥明文/大文件。
风格仍主动对齐 `ingest/` 既有模块以保证一致性。

---

## 拟定变更

### 文件 1：`Code/algorithms/providers/Python/ingest/remote_sync.py`（新建）

#### 模块文档字符串
说明用途：从远程服务器（HPC SSH/SFTP、win11 SSH 别名、NAS FileBrowser API）
增量同步数据集到本地；服务器端只读；支持增量跳过与断点续传（SFTP）。
给出 `from ingest.remote_sync import sync_dataset, ServerConfig` 用法示例。

#### 顶部导入与可选依赖
```
from __future__ import annotations
import logging, os, posixpath, stat, ssl, urllib.error, urllib.parse, urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Callable, Sequence

try:
    import paramiko
except ImportError:
    paramiko = None  # 实际调用时再报错

logger = logging.getLogger(__name__)
```
FileBrowser 走 stdlib `urllib`，不导入 requests。paramiko 顶部 try/except 置 None。

#### 常量
- `ALLOWED_EXTENSIONS: frozenset[str]` = `{".mat",".h5",".hdf5",".hdf",".nc",".tif",".txt"}`
  （沿用源脚本默认过滤集）。
- `CHUNK_SIZE = 262144`（256 KB，SFTP 与 FileBrowser 下载共用）。
- `BROWSER_UA`（同 scanner 的 Chrome UA 字符串）。
- **不**硬编码服务器地址/私钥/本地根目录 —— 这些由调用方通过 `ServerConfig` 传入
  （库模块职责分离；原脚本中的 `ACCESS_METHODS`/`DATA_SOURCES`/`SEAHPC_KEY`/`ORIGINAL_KEY`/`LOCAL_BASE` 不进库）。

#### 数据类
```
@dataclass(frozen=True, slots=True)
class RemoteFile:
    name: str            # 文件/目录名
    path: str            # 远程绝对路径
    size: int            # 字节；目录为 0
    is_dir: bool
    modified: float | None = None   # 时间戳（可选）

@dataclass(frozen=True, slots=True)
class ServerConfig:
    server_type: Literal["hpc", "win11", "nas"]
    # SSH 字段（hpc / win11）
    host: str = ""
    port: int = 22
    username: str = ""
    key_filename: str | Path | None = None
    password: str = ""               # 可选口令认证
    proxy_command: str = ""          # jump/tunnel 的 ProxyCommand
    ssh_alias: str = ""              # win11：~/.ssh/config 别名（优先于 host）
    connect_timeout: int = 20
    # FileBrowser 字段（nas）
    url: str = ""                    # FileBrowser base_url
    fb_username: str = ""
    fb_password: str = ""

@dataclass
class SyncResult:
    total_files: int = 0
    skipped: int = 0                 # 本地已存在且大小一致
    downloaded: int = 0
    failed: int = 0
    downloaded_bytes: int = 0
    resumed: int = 0                 # 其中断点续传数
    errors: list[str] = field(default_factory=list)
```

#### 公共函数

**`sync_dataset(server_config, remote_path, local_path, date_range=None, file_filter=None, progress_callback=None) -> SyncResult`**
- 主入口。按 `server_config.server_type` 分发：
  - `"hpc"` / `"win11"` → SFTP 路径：`_sftp_connect(server_config)` 建连，
    `_sftp_walk(sftp, remote_path)` 递归收集 `RemoteFile`（仅文件，按扩展名/过滤器），
    逐文件 `_sftp_download_file`（增量跳过：本地大小==远程大小则 skip；
    本地<远程则 seek 续传；本地>远程则重下）。
  - `"nas"` → FileBrowser 路径：`filebrowser_login(url, user, pwd)` 取 token，
    `_filebrowser_walk(url, token, remote_path)` 递归收集 `RemoteFile`，
    逐文件 `_filebrowser_download`（本地大小==远程大小则 skip；否则整文件下载）。
- `date_range`：`tuple[str,str] | None`，`("YYYY-MM-DD","YYYY-MM-DD")`。
  非 None 时按文件名中 8 位日期串（正则 `\d{8}`）过滤，落在区间内才下载；None 不过滤。
- `file_filter`：`Callable[[RemoteFile], bool] | Sequence[str] | None`。
  为序列时视作允许扩展名集合（覆盖 `ALLOWED_EXTENSIONS`）；为可调用时直接判定；None 用默认集。
- `progress_callback`：`Callable[[int, int, str], None] | None`，
  签名 `(current_index, total_count, current_rel_path)`，每文件调用一次。
- 返回 `SyncResult`。错误记入 `result.errors` 并 `logger.exception`，不抛出（单文件失败不中断整体）。
- 用 `_require_paramiko()` 守卫 paramiko 缺失。

**`_sftp_list_dir(sftp, path) -> list[RemoteFile]`**
- `sftp.listdir_attr(path)` → 逐项构造 `RemoteFile`（`is_dir = stat.S_ISDIR(st_mode)`，
  `size = st_size or 0`，`modified = st_mtime`）。IOError 记日志返回空列表。
- 仅列一层（不递归），递归由 `sync_dataset` 内的 walk helper 处理。

**`_sftp_download_file(sftp, remote_path, local_path) -> bool`**
- 计算远程大小（`sftp.stat`），本地存在则按大小决定续传偏移（`seek(offset)` + `"ab"`）或全新 `"wb"`。
- `sftp.open(remote_path,"rb")` → 分块 `CHUNK_SIZE` 写入。完成后校验本地大小==远程大小。
- 异常记日志返回 False。

**`_filebrowser_list_dir(url, token, path) -> list[RemoteFile]`**
- `GET {url}/api/resources/{quote(path.strip('/'), safe='/')}`，头含 `User-Agent`、`X-Auth`、`Accept: application/json`。
- 解析响应：dict 且有 `items` 取 `data["items"]`；list 直接用；否则空。
- 逐项 → `RemoteFile`（`is_dir = bool(item.get("isDir", False))`，`size = item.get("size",0)`，
  `name = item.get("name","")`，`modified = item.get("modified")`）。
- 401/403 不在此处理（由调用方重新登录）；404 返回空。`urllib.error.HTTPError` 捕获并记日志。

**`_filebrowser_download(url, token, path, local_path) -> bool`**
- `GET {url}/api/raw/{quote(path.strip('/'), safe='/')}`，头含 `User-Agent`、`X-Auth`。
- `local_path.parent.mkdir(parents=True, exist_ok=True)`，流式 `resp.read(CHUNK_SIZE)` 写 `"wb"`。
- 完成后校验本地大小>0；异常返回 False。不做 Range 续传（FileBrowser raw 端点语义简单，跳过即增量）。

**`filebrowser_login(url, user, password) -> str`**
- `POST {url}/api/login`，body `{"username":user,"password":password}`（json），
  头 `Content-Type: application/json` + `User-Agent`。
- `urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=30)`，
  `resp.read().decode().strip().strip('"')` 返回 token。
- HTTPError 抛出带状态码的 `RuntimeError`。

#### 内部 helper（私有，不导出但实现需要）
- `_require_paramiko()`：paramiko 为 None 时抛 `ImportError("未安装 paramiko，请 pip install paramiko")`。
- `_sftp_connect(cfg: ServerConfig)`：返回 `(ssh_client, sftp)`。
  `cfg.ssh_alias` 非空时用 `paramiko.SSHConfig().parse(~/.ssh/config)` 解析别名得 host/port/user/IdentityFile/ProxyCommand；
  否则用 cfg.host/port/username/key_filename/proxy_command。
  `set_missing_host_key_policy(AutoAddPolicy())`，`look_for_keys=False, allow_agent=False`。
- `_sftp_walk(sftp, remote_dir)`：递归生成器，yield 文件 `RemoteFile`（目录递归、文件按 `file_filter` 过滤）。
- `_filebrowser_walk(url, token, path)`：递归调 `_filebrowser_list_dir`，遇 401/403 重新 `filebrowser_login` 并重试一次。
- `_classify_local(local_path, remote_size) -> str`：返回 `"equal"/"missing"/"partial"/"larger"`（沿用源脚本逻辑）。
- `_filter_file(remote: RemoteFile, file_filter, date_range) -> bool`：扩展名 + 日期过滤合一。
- `_parse_date_from_name(name) -> str | None`：正则 `\d{8}` 抽取 `YYYYMMDD`。

#### 关键决策
- FileBrowser 用 stdlib `urllib`（对齐已验证的 scanner，不增依赖）；SFTP 用 paramiko。
- 不硬编码任何服务器/路径/凭据 —— 全由 `ServerConfig` 传入（库 vs CLI 职责分离）。
- win11 经 `~/.ssh/config` 别名解析（`paramiko.SSHConfig`），与 hpc 共用 SFTP 下载逻辑。
- FileBrowser 下载不做 Range 续传（raw 端点 + 跳过即增量足够）；SFTP 保留断点续传。

---

### 文件 2：`Code/algorithms/providers/Python/ingest/nsidc_download.py`（新建）

#### 模块文档字符串
说明用途：从 NASA NSIDC 下载 SMAP L3 SPL3SMP_E 土壤湿度数据；
CMR 搜索 + earthaccess/requests 双认证路径；增量跳过、断点续传、指数退避重试、磁盘空间检查。
给出 `from ingest.nsidc_download import download_smap_range, Granule` 用法示例。

#### 顶部导入与可选依赖
```
from __future__ import annotations
import logging, os, shutil, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    import earthaccess
    _HAS_EARTHACCESS = True
except ImportError:
    earthaccess = None
    _HAS_EARTHACCESS = False

logger = logging.getLogger(__name__)
```
`requests` 在函数内部延迟 `import requests`（对齐源脚本，保证模块无 requests 也能导入）。

#### 常量
- `SHORT_NAME = "SPL3SMP_E"`，`DEFAULT_VERSION = "6"`。
- `CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"`。
- `MAX_RETRIES = 3`，`INITIAL_BACKOFF = 2.0`（项目硬约束：可重试失败用指数退避+抖动，max=3，initial=2s）。
- `CHUNK_SIZE = 262144`，`REQUEST_TIMEOUT = 60`，`DOWNLOAD_TIMEOUT = 3600`。
- `MIN_DISK_FREE_GB = 5.0`。
- `PROGRESS_INTERVAL = 2.0`。
- **不**硬编码默认凭据 —— 库模块从 `auth` 参数或环境变量 `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` 读取；
  均无则抛 `ValueError`（移除源脚本的 `Rejoyce/Diandian143` 硬编码，避免凭据泄露）。

#### 数据类
```
@dataclass(frozen=True, slots=True)
class Granule:
    name: str
    url: str
    size_mb: float | None = None

@dataclass(frozen=True, slots=True)
class EarthdataAuth:
    username: str
    password: str

@dataclass
class EarthaccessSession:
    session: Any                 # requests.Session（earthaccess 或 HTTPBasicAuth）
    method: str                  # "earthaccess" | "basic"
    auth: EarthdataAuth

@dataclass
class DownloadResult:
    total: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    downloaded_bytes: int = 0
    errors: list[str] = field(default_factory=list)
    granules: list[Granule] = field(default_factory=list)
```
（用户列明的 dataclass：`Granule`、`DownloadResult`、`EarthdataAuth`；额外定义 `EarthaccessSession`
以满足 `_earthaccess_login` 的返回类型注解。）

#### 公共函数

**`download_smap_range(start_date, end_date, local_dir, version=6, auth=None, progress_callback=None) -> DownloadResult`**
- `start_date`/`end_date`：`str`，`YYYY-MM-DD`（校验格式，`start <= end`）。
- `auth`：`EarthdataAuth | None`；None 时读环境变量，仍无则 `raise ValueError`。
- 流程：
  1. `_check_disk_space(Path(local_dir))` —— 不足且非 dry-run 时记 error 入 `result.errors` 并返回（不 sys.exit）。
  2. `granules = _cmr_search(start_date, end_date, str(version))`。
  3. 增量过滤：`local_dir/name` 已存在且 `st_size > 0` → `skipped`。
  4. `session = _earthaccess_login(auth.username, auth.password)`。
  5. 逐 granule `_download_granule(url, local_path, session)`（内部已含重试），
     成功 `downloaded += 1`，`downloaded_bytes += size`，失败 `failed += 1` 且记 errors。
  6. `progress_callback(current, total, name)` 每文件调用一次（`Callable[[int,int,str],None] | None`）。
  7. 返回 `DownloadResult`（`granules` 字段填搜索结果）。不 `sys.exit`（库语义，错误入 result）。

**`_cmr_search(start_date, end_date, version) -> list[Granule]`**
- `requests` 延迟导入。`temporal = f"{start}T00:00:00Z,{end}T23:59:59Z"`，
  分页 `page_size=2000`，`page_num` 上限 50。
- 逐 item：`umm.RelatedUrls` 优先 `.h5` 且 Type 以 `GET DATA` 开头，否则首个 `GET DATA`。
  `name = url.split('/')[-1]`；`size_mb` 从 `umm.DataGranule.ArchiveAndDistributionSize` 解析（GB→×1024，KB→/1024）。
- 构造 `Granule(name, url, size_mb)`。返回列表。

**`_download_granule(url, local_path, auth) -> bool`**
- `auth` 形参名为 `auth`，类型 `EarthaccessSession`（即已登录会话）。
- 流式 GET（`stream=True, timeout=DOWNLOAD_TIMEOUT`）；支持 Range 续传：
  本地存在则 `headers["Range"]=bytes={size}-`；416 视为完成；206 追加 `"ab"`，200 全新 `"wb"`。
- `iter_content(CHUNK_SIZE)` 写入，按 `PROGRESS_INTERVAL` 周期 `logger.info` 进度。
- 完成后校验 `st_size > 0`。
- 重试：`MAX_RETRIES` 次，退避 `INITIAL_BACKOFF * 2**(attempt-1)` **加随机抖动**
  （`time.sleep(backoff + random.uniform(0, 0.5*backoff))`，满足项目"指数退避+抖动"硬约束）。
  达上限返回 False。

**`_earthaccess_login(user, password) -> EarthaccessSession`**
- `_HAS_EARTHACCESS` 为真：`earthaccess.login(username=user, password=password, persist=True)`，
  `session = auth.get_session()`，返回 `EarthaccessSession(session, "earthaccess", EarthdataAuth(user,password))`。
  失败 `logger.warning` 后走回退。
- 回退：`requests.Session()`，`session.auth = HTTPBasicAuth(user, password)`，
  `session.headers["User-Agent"] = "cgda-nsidc-download/1.0 (Python)"`，
  返回 `EarthaccessSession(session, "basic", EarthdataAuth(user,password))`。

#### 内部 helper（私有）
- `_check_disk_space(path, min_gb=MIN_DISK_FREE_GB) -> tuple[bool, float]`：`shutil.disk_usage`，`path.mkdir(parents=True, exist_ok=True)`。
- `_resolve_auth(auth) -> EarthdataAuth`：auth 非 None 直接用；否则读环境变量；均无 `raise ValueError`。
- `_validate_date(s) -> str`：`datetime.strptime(s,"%Y-%m-%d")` 校验并归一化。
- `_granule_url_from_umm(...)` / 日期校验等小工具。

#### 关键决策
- 搜索统一走 CMR（requests，无需 earthaccess）；下载认证走 earthaccess 优先、HTTPBasicAuth 回退。
  这与用户列出的 `_cmr_search` + `_earthaccess_login` 函数职责划分一致。
- 移除硬编码凭据（库模块从参数/环境变量取，缺失抛错）。
- 重试加随机抖动以满足项目硬约束（源脚本仅纯指数退避）。
- 不 `sys.exit`（库语义，错误写入 `DownloadResult.errors`）。

---

## 假设与决策

1. **不修改 `ingest/__init__.py`**：其仅为 `"""Raw data readers and converters."""`，既有子模块均通过 `from ingest.xxx import ...` 导入，新模块沿用此模式。
2. **不新增依赖**：`remote_sync.py` FileBrowser 部分用 stdlib `urllib`（对齐已验证 scanner）；SFTP 用 paramiko（顶部 try/except）。`nsidc_download.py` 用 requests（延迟导入）+ earthaccess（可选 try/except）。模块级导入不依赖任何可选库，保证 import 验证通过。
3. **库 vs CLI 职责分离**：服务器地址、私钥、凭据、本地根目录、日志目录一律由调用方传入（`ServerConfig`/参数/环境变量），不进库。源脚本的硬编码常量留在 CLI 脚本中。
4. **win11 = SSH 别名**：经 `paramiko.SSHConfig` 解析 `~/.ssh/config`（对齐源脚本 `win11-lab` 别名语义）；hpc = SSH/SFTP 直连/隧道/跳板；nas = FileBrowser API。三种 `server_type` 在 `sync_dataset` 内分发。
5. **FileBrowser 认证头用 `X-Auth`**（非 `Authorization: Bearer`），`isDir` 判目录，强制 `User-Agent` —— 全部对齐本项目已验证的 `remote_data_scanner.py`。
6. **移除 nsidc 硬编码凭据**：库从 `auth` 参数或 `EARTHDATA_USERNAME/PASSWORD` 环境变量取，缺失抛 `ValueError`。
7. **重试加抖动**：nsidc 下载重试采用指数退避 + 随机抖动，满足项目硬约束（max_attempts=3, initial_backoff=2s）。
8. **库不 `sys.exit`**：错误记入结果对象的 `errors` 列表并记日志，由调用方决定如何处理。
9. **进度回调统一签名**：两模块均 `(current_index, total_count, current_name) -> None`，可选。
10. **lint 范围**：ruff/mypy 不覆盖 `ingest/`，但仍主动对齐 `ingest/` 风格；`check-ast`/`trailing-whitespace`/`end-of-file-fixer`/`detect-private-key` 对新文件生效，须通过。

---

## 验证步骤

1. **导入验证（用户指定命令）**，在
   `D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python`
   下执行：
   ```
   python -c "from ingest.remote_sync import sync_dataset, ServerConfig; print('remote_sync OK')"
   python -c "from ingest.nsidc_download import download_smap_range, Granule; print('nsidc_download OK')"
   ```
   两条均应打印 `... OK` 且无异常。这同时验证：语法正确、模块级无硬依赖、公共符号签名正确。

2. **语法编译检查**（可选，快速失败兜底）：
   ```
   python -m py_compile ingest\remote_sync.py ingest\nsidc_download.py
   ```

3. **符号自省**（可选，确认全部要求的函数/数据类可导入）：
   ```
   python -c "from ingest.remote_sync import sync_dataset, ServerConfig, RemoteFile, SyncResult, filebrowser_login, _sftp_list_dir, _sftp_download_file, _filebrowser_list_dir, _filebrowser_download; print('all remote_sync symbols OK')"
   python -c "from ingest.nsidc_download import download_smap_range, Granule, DownloadResult, EarthdataAuth, _cmr_search, _download_granule, _earthaccess_login; print('all nsidc symbols OK')"
   ```

4. **通用 pre-commit 钩子**（提交前）：`pre-commit run --all-files` 应使新文件通过
   `check-ast`/`trailing-whitespace`/`end-of-file-fixer`/`detect-private-key`/`check-added-large-files`
   （ruff/mypy 不覆盖 `ingest/`，不会阻塞）。

注：导入验证不触发网络/认证，仅验证可导入性；实际同步/下载需调用方提供有效 `ServerConfig`/凭据。
