#!/usr/bin/env python3
"""FileBrowser 远程数据扫描工具。

扫描两个 Cloudflare 隧道映射的远程文件服务器，查找植被和土壤相关的数据文件
（.nc / .hdf / .h5 / .tif / .tiff / .mat / .csv / .txt / .dat 等），
生成结构化清单报告，并支持按需下载到本地 I:\\Geograph_DataSet\\。

用法：
    # 快速扫描两个服务器（深度 3，仅顶层目录结构）
    python remote_data_scanner.py scan --quick

    # 标准扫描（深度 4，平衡速度和覆盖）
    python remote_data_scanner.py scan

    # 深度扫描（深度 6，完整覆盖，耗时较长）
    python remote_data_scanner.py scan --max-depth 6

    # 只扫描 win11 服务器（E 盘）
    python remote_data_scanner.py scan --server win11

    # 根据清单下载文件到 I:\\Geograph_DataSet\\
    python remote_data_scanner.py download --inventory scan_report_20260714.json

    # 交互式选择要下载的文件
    python remote_data_scanner.py download --inventory scan_report_20260714.json --interactive
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ─── 配置 ────────────────────────────────────────────────────────────────────

SERVERS = {
    "win11": {
        "base_url": "https://win11file.personaltunnel.dpdns.org",
        "username": "user",
        "password": "remotefangwen123",
        "label": "Win11 E盘",
        "description": "映射了远端电脑 E 盘，包含数据和软件",
    },
    "nas": {
        "base_url": "https://nasfile.personaltunnel.dpdns.org",
        "username": "user",
        "password": "remotefangwen123",
        "label": "NAS Z盘",
        "description": "映射了 NAS 网络驱动器 Z 盘，包含课题组成员数据",
    },
}

# 目标数据文件扩展名
TARGET_EXTENSIONS = {
    # 栅格/网格数据
    ".nc",
    ".hdf",
    ".h5",
    ".he5",
    ".tif",
    ".tiff",
    ".mat",
    # 矢量数据
    ".shp",
    ".geojson",
    ".json",
    # 表格数据
    ".csv",
    ".xlsx",
    ".xls",
    # 文本数据
    ".txt",
    ".dat",
    # 其他
    ".grib",
    ".grib2",
    ".grb",
}

# 关键词分类（不区分大小写，匹配文件名或路径）
KEYWORD_CATEGORIES = {
    "土壤水分": [
        "smap",
        "soil_moisture",
        "soil moisture",
        "sm_",
        "_sm",
        "soilmoisture",
        "ismn",
        "casmos",
        "cern",
        "土壤水分",
        "土壤湿度",
    ],
    "植被指数": [
        "ndvi",
        "evi",
        "lai",
        "fpar",
        "viirs",
        "modis",
        "vegetation",
        "植被",
        "归一化植被",
    ],
    "亮温": [
        "mwri",
        "tb_",
        "tbh",
        "tbv",
        "brightness",
        "亮温",
        "亮度温度",
        "fy3",
        "fy-3",
        "fy3d",
        "fy3b",
    ],
    "气象数据": [
        "ecmwf",
        "era5",
        "wind",
        "temperature",
        "humidity",
        "precipitation",
        "pressure",
        "weather",
        "gldas",
        "气象",
        "风场",
        "温度",
        "降水",
        "气压",
    ],
    "碳通量": [
        "gosat",
        "xco2",
        "co2",
        "carbon",
        "碳",
    ],
    "地形": [
        "dem",
        "srtm",
        "elevation",
        "terrain",
        "地形",
        "高程",
    ],
    "土地覆盖": [
        "landcover",
        "land cover",
        "lc_",
        "igbp",
        "mcd12",
        "土地覆盖",
        "土地利用",
    ],
    "降水": [
        "rain",
        "precipitation",
        "gpm",
        "trmm",
        "降水",
        "降雨",
        "融合降水",
    ],
    "站点观测": [
        "station",
        "site",
        "obs",
        "observation",
        "站点",
        "观测",
    ],
    "行政区划": [
        "admin",
        "boundary",
        "province",
        "city",
        "行政",
        "边界",
        "省",
        "市",
    ],
    "土壤质地": [
        "clay",
        "sand",
        "silt",
        "bulk_density",
        "soil_texture",
        "质地",
        "黏土",
        "沙土",
        "容重",
    ],
    "反照率": [
        "albedo",
        "反照率",
    ],
}

# 扫描时跳过的目录名（节省时间）—— 扩展列表以加速扫描
SKIP_DIRS = {
    # 系统目录
    "system volume information",
    "$recycle.bin",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "users",
    "appdata",
    # 开发工具/IDE
    "node_modules",
    ".git",
    "__pycache__",
    ".cache",
    ".venv",
    "venv",
    "env",
    ".env",
    ".idea",
    ".vscode",
    ".vs",
    # 临时目录
    "temp",
    "tmp",
    "cache",
    ".cache",
    "__pycache__",
    # 软件安装目录
    "software",
    "installer",
    "installers",
    "drivers",
    "lib",
    "libs",
    "bin",
    "conda",
    "anaconda",
    "miniconda",
    "python",
    "java",
    "jre",
    "jdk",
    "matlab",
    "matlabroot",
    "polyspace",
    "simscape",
    "rtw",
    # 构建产物
    "build",
    "dist",
    "target",
    "out",
    "output",
    "outputs",
    ".gradle",
    ".m2",
    ".npm",
    ".nuget",
    "packages",
    # 版本控制/备份
    ".svn",
    ".hg",
    "backup",
    "backups",
    "bak",
    # 其他常见非数据目录
    "logs",
    "log",
    "doc",
    "docs",
    "documentation",
    "help",
    "examples",
    "sample",
    "samples",
    "test",
    "tests",
    "testing",
    "config",
    "configs",
    "configuration",
    "settings",
    "scripts",
    "tools",
    "util",
    "utils",
    "utility",
    "utilities",
}

# 本地数据根目录
LOCAL_DATA_ROOT = Path(r"I:\Geograph_DataSet")

# 扫描报告输出目录
REPORT_DIR = Path(
    r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Tools\reports"
)

# 请求间隔（秒），避免请求过快
REQUEST_DELAY = 0.12

# 定期保存部分结果的间隔（每扫描多少个目录保存一次）
CHECKPOINT_INTERVAL = 200


# ─── FileBrowser API 客户端 ──────────────────────────────────────────────────

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


class FileBrowserClient:
    """FileBrowser REST API 客户端。"""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: str | None = None
        self._ssl_ctx = ssl.create_default_context()

    def _headers(self, extra: dict | None = None) -> dict:
        """构建请求头，包含 User-Agent（Cloudflare 要求）。"""
        h = {"User-Agent": BROWSER_UA}
        if self._token:
            h["X-Auth"] = self._token
        if extra:
            h.update(extra)
        return h

    def login(self) -> str:
        """登录并获取 JWT token。"""
        url = f"{self.base_url}/api/login"
        body = json.dumps(
            {"username": self.username, "password": self.password}
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": BROWSER_UA},
            method="POST",
        )
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=30) as resp:
            token = resp.read().decode("utf-8").strip().strip('"')
        self._token = token
        return token

    def list_dir(self, path: str = "/") -> list[dict]:
        """列出目录内容，返回子项列表。

        每项包含: name, size, extension, isDir, type, modified 等字段。
        """
        if self._token is None:
            self.login()
        encoded_path = urllib.parse.quote(path.strip("/"), safe="/")
        url = f"{self.base_url}/api/resources/{encoded_path}"
        req = urllib.request.Request(
            url,
            headers=self._headers({"Accept": "application/json"}),
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 401):
                self.login()
                return self.list_dir(path)
            if exc.code == 404:
                return []
            raise
        if isinstance(data, dict) and "items" in data:
            return data["items"]
        if isinstance(data, list):
            return data
        return []

    def download_file(
        self, remote_path: str, local_path: Path, chunk_size: int = 65536
    ) -> None:
        """下载远程文件到本地。"""
        if self._token is None:
            self.login()
        encoded_path = urllib.parse.quote(remote_path.strip("/"), safe="/")
        url = f"{self.base_url}/api/raw/{encoded_path}"
        req = urllib.request.Request(
            url,
            headers=self._headers(),
            method="GET",
        )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=300) as resp:
            with open(local_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)


# ─── 数据扫描器 ──────────────────────────────────────────────────────────────


class DataScanner:
    """递归扫描远程目录，分类标记数据文件。"""

    # 每个目录最多采样多少个匹配文件（防止海量同类文件刷屏）
    MAX_FILES_PER_DIR = 30

    def __init__(
        self,
        client: FileBrowserClient,
        server_key: str,
        max_depth: int = 4,
        checkpoint_path: Path | None = None,
    ) -> None:
        self.client = client
        self.server_key = server_key
        self.max_depth = max_depth
        self.results: list[dict] = []
        self.dirs_scanned = 0
        self.files_found = 0
        self.files_truncated = 0
        self.errors: list[dict] = []
        self._checkpoint_path = checkpoint_path
        self._start_time = time.time()
        # 记录每个深度的目录数，便于了解结构
        self.dirs_by_depth: dict[int, int] = {}

    def _should_skip_dir(self, name: str) -> bool:
        lower = name.lower().strip()
        if lower in SKIP_DIRS:
            return True
        # 跳过隐藏目录
        if lower.startswith(".") and lower not in (".", ".."):
            return True
        return False

    def _classify_file(self, name: str, path: str) -> list[str]:
        """根据文件名和路径关键词分类。"""
        text = f"{name} {path}".lower()
        categories = []
        for category, keywords in KEYWORD_CATEGORIES.items():
            for kw in keywords:
                if kw.lower() in text:
                    categories.append(category)
                    break
        if not categories:
            categories.append("其他")
        return categories

    def scan(self) -> list[dict]:
        """从根目录开始递归扫描。"""
        print(f"  [{self.server_key}] 登录中...")
        self.client.login()
        print(
            f"  [{self.server_key}] 登录成功，开始扫描（最大深度 {self.max_depth}）..."
        )
        self._scan_dir("/", 0)
        elapsed = time.time() - self._start_time
        print(
            f"  [{self.server_key}] 扫描完成：目录 {self.dirs_scanned}，"
            f"匹配文件 {self.files_found}（截断 {self.files_truncated}），"
            f"错误 {len(self.errors)}，耗时 {elapsed:.0f}s"
        )
        return self.results

    def _scan_dir(self, path: str, depth: int) -> None:
        if depth > self.max_depth:
            return
        self.dirs_scanned += 1
        self.dirs_by_depth[depth] = self.dirs_by_depth.get(depth, 0) + 1

        # 每 50 个目录打印一次进度
        if self.dirs_scanned % 50 == 0:
            elapsed = time.time() - self._start_time
            rate = self.dirs_scanned / elapsed if elapsed > 0 else 0
            print(
                f"  [{self.server_key}] 已扫描 {self.dirs_scanned} 个目录，"
                f"找到 {self.files_found} 个匹配文件 "
                f"({rate:.1f} dirs/s, 深度 {depth})..."
            )

        # 定期保存检查点
        if self._checkpoint_path and self.dirs_scanned % CHECKPOINT_INTERVAL == 0:
            self._save_checkpoint()

        try:
            items = self.client.list_dir(path)
        except Exception as exc:
            self.errors.append({"path": path, "error": str(exc)})
            time.sleep(0.3)
            return

        time.sleep(REQUEST_DELAY)

        dir_count = 0
        file_count_in_dir = 0

        for item in items:
            name = item.get("name", "")
            is_dir = item.get("isDir", False)
            size = item.get("size", 0)
            full_path = f"{path.rstrip('/')}/{name}" if path != "/" else f"/{name}"

            if is_dir:
                if self._should_skip_dir(name):
                    continue
                dir_count += 1
                self._scan_dir(full_path, depth + 1)
            else:
                ext = item.get("extension", "")
                if ext and not ext.startswith("."):
                    ext = f".{ext}"
                ext_lower = ext.lower() if ext else ""

                if ext_lower in TARGET_EXTENSIONS:
                    if file_count_in_dir >= self.MAX_FILES_PER_DIR:
                        self.files_truncated += 1
                        continue
                    categories = self._classify_file(name, full_path)
                    record = {
                        "server": self.server_key,
                        "remote_path": full_path,
                        "name": name,
                        "extension": ext_lower,
                        "size_bytes": size,
                        "size_human": _format_size(size),
                        "categories": categories,
                        "depth": depth,
                        "modified": item.get("modified", ""),
                    }
                    self.results.append(record)
                    self.files_found += 1
                    file_count_in_dir += 1

    def _save_checkpoint(self) -> None:
        """保存当前扫描进度到检查点文件。"""
        if not self._checkpoint_path:
            return
        try:
            checkpoint = {
                "server": self.server_key,
                "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "dirs_scanned": self.dirs_scanned,
                "files_found": self.files_found,
                "files_truncated": self.files_truncated,
                "dirs_by_depth": self.dirs_by_depth,
                "results": self.results,
                "errors": self.errors,
            }
            self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"  [{self.server_key}] 检查点保存失败: {exc}")


def _format_size(size_bytes: int) -> str:
    """将字节数转为人类可读格式。"""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"


# ─── 报告生成 ────────────────────────────────────────────────────────────────


def generate_report(all_results: list[dict], errors: list[dict]) -> dict:
    """生成结构化的扫描报告。"""
    # 按分类统计
    by_category: dict[str, list[dict]] = {}
    by_server: dict[str, list[dict]] = {}
    by_extension: dict[str, int] = {}
    by_extension_size: dict[str, int] = {}
    total_size = 0

    for item in all_results:
        total_size += item["size_bytes"]
        for cat in item["categories"]:
            by_category.setdefault(cat, []).append(item)
        by_server.setdefault(item["server"], []).append(item)
        ext = item["extension"]
        by_extension[ext] = by_extension.get(ext, 0) + 1
        by_extension_size[ext] = by_extension_size.get(ext, 0) + item["size_bytes"]

    # 排序：按文件大小降序
    for cat_items in by_category.values():
        cat_items.sort(key=lambda x: x["size_bytes"], reverse=True)
    for srv_items in by_server.values():
        srv_items.sort(key=lambda x: x["size_bytes"], reverse=True)

    report = {
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total_files": len(all_results),
            "total_size_bytes": total_size,
            "total_size_human": _format_size(total_size),
            "total_errors": len(errors),
            "by_extension": dict(sorted(by_extension.items(), key=lambda x: -x[1])),
            "by_extension_size": {
                ext: _format_size(sz)
                for ext, sz in sorted(by_extension_size.items(), key=lambda x: -x[1])
            },
        },
        "by_category": {
            cat: {
                "count": len(items),
                "total_size": _format_size(sum(i["size_bytes"] for i in items)),
                "total_size_bytes": sum(i["size_bytes"] for i in items),
                "files": items,
            }
            for cat, items in sorted(by_category.items())
        },
        "by_server": {
            srv: {
                "count": len(items),
                "total_size": _format_size(sum(i["size_bytes"] for i in items)),
                "total_size_bytes": sum(i["size_bytes"] for i in items),
                "files": items,
            }
            for srv, items in sorted(by_server.items())
        },
        "errors": errors,
    }
    return report


def save_report(report: dict, output_path: Path) -> None:
    """保存报告为 JSON 文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {output_path}")


def print_summary(report: dict) -> None:
    """在终端打印摘要。"""
    s = report["summary"]
    print("\n" + "=" * 70)
    print("  远程数据扫描报告摘要")
    print("=" * 70)
    print(f"  扫描时间:   {report['scan_time']}")
    print(f"  匹配文件:   {s['total_files']} 个")
    print(f"  总大小:     {s['total_size_human']}")
    print(f"  错误数:     {s['total_errors']}")

    print("\n  按扩展名统计:")
    print(f"    {'扩展名':<12s} {'数量':>8s} {'大小':>12s}")
    print(f"    {'─'*12} {'─'*8} {'─'*12}")
    for ext, count in s["by_extension"].items():
        size_str = s["by_extension_size"].get(ext, "0 B")
        print(f"    {ext or '(无)':<12s} {count:>8d} {size_str:>12s}")

    print("\n  按分类统计:")
    print(f"    {'分类':<12s} {'数量':>8s} {'大小':>12s}")
    print(f"    {'─'*12} {'─'*8} {'─'*12}")
    for cat, data in report["by_category"].items():
        print(f"    {cat:<12s} {data['count']:>8d} {data['total_size']:>12s}")

    print("\n  按服务器统计:")
    for srv, data in report["by_server"].items():
        label = SERVERS.get(srv, {}).get("label", srv)
        print(f"    {label:<16s} {data['count']:>6d} 个  ({data['total_size']})")

    # 打印 Top 20 大文件
    all_files = []
    for srv_data in report["by_server"].values():
        all_files.extend(srv_data["files"])
    all_files.sort(key=lambda x: x["size_bytes"], reverse=True)

    print("\n  Top 20 大文件:")
    print(f"    {'大小':<12s} {'分类':<16s} {'服务器':<8s} 路径")
    print(f"    {'─'*12} {'─'*16} {'─'*8} {'─'*40}")
    for item in all_files[:20]:
        cats = ",".join(item["categories"][:2])
        # 截断过长的路径
        path_display = item["remote_path"]
        if len(path_display) > 60:
            path_display = "..." + path_display[-57:]
        print(
            f"    {item['size_human']:<12s} {cats:<16s} {item['server']:<8s} {path_display}"
        )

    print("=" * 70)


# ─── 下载管理 ────────────────────────────────────────────────────────────────


def download_files(
    inventory_path: Path,
    categories: list[str] | None = None,
    max_size_mb: float | None = None,
    dry_run: bool = False,
) -> None:
    """根据清单下载文件到本地 I:\\Geograph_DataSet\\。"""
    with open(inventory_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # 收集所有文件
    all_files: list[dict] = []
    for srv_data in report["by_server"].values():
        all_files.extend(srv_data["files"])

    # 按分类过滤
    if categories:
        cat_set = set(categories)
        all_files = [f for f in all_files if cat_set & set(f["categories"])]

    # 按大小过滤
    if max_size_mb is not None:
        max_bytes = int(max_size_mb * 1024 * 1024)
        all_files = [f for f in all_files if f["size_bytes"] <= max_bytes]

    print(f"待下载文件: {len(all_files)} 个")

    if dry_run:
        for item in all_files:
            local_path = _resolve_local_path(item)
            print(f"  [DRY-RUN] {item['server']}:{item['remote_path']} -> {local_path}")
        return

    # 按服务器分组下载
    by_server: dict[str, list[dict]] = {}
    for item in all_files:
        by_server.setdefault(item["server"], []).append(item)

    total_downloaded = 0
    total_skipped = 0
    total_failed = 0

    for srv_key, items in by_server.items():
        cfg = SERVERS[srv_key]
        client = FileBrowserClient(cfg["base_url"], cfg["username"], cfg["password"])
        client.login()
        print(f"\n[{cfg['label']}] 开始下载 {len(items)} 个文件...")

        for i, item in enumerate(items, 1):
            local_path = _resolve_local_path(item)
            if local_path.exists() and local_path.stat().st_size == item["size_bytes"]:
                total_skipped += 1
                continue
            try:
                print(f"  [{i}/{len(items)}] {item['name']} ({item['size_human']})...")
                client.download_file(item["remote_path"], local_path)
                total_downloaded += 1
                time.sleep(REQUEST_DELAY)
            except Exception as exc:
                print(f"  [FAILED] {item['remote_path']}: {exc}")
                total_failed += 1

    print(
        f"\n下载完成: {total_downloaded} 成功, {total_skipped} 跳过, {total_failed} 失败"
    )


def _resolve_local_path(item: dict) -> Path:
    """根据文件分类和远程路径确定本地存储路径。"""
    # 取第一个分类作为子目录
    category = item["categories"][0] if item["categories"] else "其他"
    # 分类名转英文目录名
    category_dir_map = {
        "土壤水分": "SMAP",
        "植被指数": "NDVI",
        "亮温": "FY_MWRI",
        "气象数据": "Weather",
        "碳通量": "GOSAT",
        "地形": "DEM",
        "土地覆盖": "LandCover",
        "降水": "Precipitation",
        "站点观测": "Station",
        "行政区划": "AdminBoundary",
        "土壤质地": "SoilTexture",
        "反照率": "Albedo",
        "其他": "Others",
    }
    subdir = category_dir_map.get(category, "Others")
    # 使用文件名作为本地文件名
    return LOCAL_DATA_ROOT / subdir / item["name"]


# ─── 主入口 ──────────────────────────────────────────────────────────────────


def cmd_scan(args: argparse.Namespace) -> None:
    """执行扫描。"""
    servers_to_scan = [args.server] if args.server else list(SERVERS.keys())
    all_results: list[dict] = []
    all_errors: list[dict] = []

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for srv_key in servers_to_scan:
        cfg = SERVERS[srv_key]
        print(f"\n{'─' * 70}")
        print(f"扫描服务器: {cfg['label']} ({cfg['base_url']})")
        print(f"说明: {cfg['description']}")
        print(f"{'─' * 70}")

        client = FileBrowserClient(cfg["base_url"], cfg["username"], cfg["password"])
        # 每个服务器单独的检查点
        checkpoint_path = REPORT_DIR / f"checkpoint_{srv_key}_{timestamp}.json"
        scanner = DataScanner(
            client,
            srv_key,
            max_depth=args.max_depth,
            checkpoint_path=checkpoint_path,
        )
        results = scanner.scan()
        all_results.extend(results)
        all_errors.extend(scanner.errors)

        # 打印该服务器的目录结构统计
        print(f"  [{srv_key}] 目录深度分布:")
        for depth in sorted(scanner.dirs_by_depth.keys()):
            count = scanner.dirs_by_depth[depth]
            print(f"    深度 {depth}: {count} 个目录")

    report = generate_report(all_results, all_errors)
    report_path = REPORT_DIR / f"scan_report_{timestamp}.json"
    save_report(report, report_path)
    print_summary(report)
    print(f"\n完整报告: {report_path}")
    print(
        f"使用下载命令: python remote_data_scanner.py download --inventory {report_path}"
    )


def cmd_download(args: argparse.Namespace) -> None:
    """执行下载。"""
    inventory = Path(args.inventory)
    if not inventory.exists():
        print(f"清单文件不存在: {inventory}")
        sys.exit(1)
    categories = args.categories.split(",") if args.categories else None
    download_files(
        inventory,
        categories=categories,
        max_size_mb=args.max_size_mb,
        dry_run=args.dry_run,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FileBrowser 远程数据扫描工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # scan 子命令
    scan_parser = subparsers.add_parser("scan", help="扫描远程服务器数据")
    scan_parser.add_argument(
        "--server", choices=["win11", "nas"], help="只扫描指定服务器"
    )
    scan_parser.add_argument(
        "--max-depth", type=int, default=4, help="最大扫描深度（默认 4）"
    )
    scan_parser.add_argument(
        "--quick", action="store_true", help="快速扫描（深度 3，仅顶层结构）"
    )

    # download 子命令
    dl_parser = subparsers.add_parser("download", help="根据清单下载文件")
    dl_parser.add_argument("--inventory", required=True, help="扫描清单 JSON 文件路径")
    dl_parser.add_argument(
        "--categories", type=str, help="按分类过滤（逗号分隔，如: 土壤水分,植被指数）"
    )
    dl_parser.add_argument("--max-size-mb", type=float, help="最大文件大小（MB）")
    dl_parser.add_argument("--dry-run", action="store_true", help="只打印不实际下载")

    args = parser.parse_args()
    if args.command == "scan":
        if args.quick:
            args.max_depth = 3
        cmd_scan(args)
    elif args.command == "download":
        cmd_download(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
