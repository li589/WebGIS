# 硬编码清理计划（可配置性 + 跨平台部署）

> 审计基准：fullstack-dev 配置集中化原则 + Twelve-Factor；三路扫描（后端/算法包、前端、基础设施/Tools）
> 范围：🔴 全部 + 高价值 🟡（用户圈定）；deployment.config.json **不动**（配置中心真源，有意架构）
> 仓库：D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system · 分支 dev

## 已验证的关键事实
- SSH 工厂（for_hpc_tunnel/direct/win11）全仓**零调用点**（生产走 profile 注入）→ 可安全改必填
- {DATA_ROOT_WIN} 5 种子 16 处；种子日期 7 文件 14 处；Tools 25 脚本写死 I 盘 + 3 脚本写死仓库路径
- 前端粤边界 = `@datapool/guangdong.geojson`（421K）静态 re-export，3 消费点已异步化；后端无 adcode 能力但 catalog_seeds 有静态数据先例
- `/config/general` 为按需拉取（非启动全局）；`system-settings-fill.ts` 的 30s TTL 缓存单例是既有模式（D0 复用）
- GATEWAY_PORT 在 gateway_manager.py:22 与 constants.py:47 双声明

---

## 阶段 A：后端/算法包 🔴（提交 1-4）

### A1 GDAL 发现链跨平台化 — `ingest/fy_preprocess.py:53-117`
- `_GDAL_SUFFIX = ".exe" if os.name == "nt" else ""`；`_try_prefix` 用之拼 gdal_translate/gdalbuildvrt/gdalwarp/gdalinfo
- QGIS/OSGeo4W 探测限 win32；conda 候选加 `$CONDA_PREFIX/bin`（Linux 布局）
- env `CGDA_GDAL_BIN` 优先（两平台生效）；报错文案按平台（Linux："Tried CGDA_GDAL_BIN, conda($CONDA_PREFIX/bin) and PATH"）
- 测试：新增 `Test/algorithms/test_fy_preprocess_gdal_resolve.py`（win/linux 布局、env 优先、报错文案）

### A2 SSH 工厂去默认值 — `ingest/remote_sync.py:109-157`
- 参照同文件 for_nas L171-174「缺参抛 ValueError」范式；移除 likr6008/qiujianqiu/172.16.98.184/win11-lab 默认值；`~/.ssh/seahpc_key` key 兜底保留（无敏感信息）
- 补 3 个缺参抛错单测；`test_remote_sync.py` 回归

### A3 {DATA_ROOT_WIN} 跨平台 — 双层修复（提交 4）
1. **种子根治**：5 文件 16 处 `{DATA_ROOT_WIN}\\Sub\\Path` → `{DATA_ROOT}/Sub/Path`（Windows 全链路 Python/GDAL 接受正斜杠）
2. **展开防御**：`workflow_request_resolver.py:75` + `workflow_definition_service.py:68` 模块级 `_IS_WINDOWS = sys.platform == "win32"`（可 monkeypatch），非 Windows 时 `{DATA_ROOT_WIN}` 按 posix root 展开（保护用户旧自定义种子）
- 测试：`test_seed_placeholder_expansion.py` 新增 posix 平台用例（monkeypatch `_IS_WINDOWS=False`）；跑 5 种子 compile 测试

### A4 NSIDC 兜底盘符 — `ingest/nsidc_download.py:24,65-72`
- 删模块级 `DEFAULT_OUTPUT_DIR` 常量，改 `_default_output_dir()` 函数：未设 `BACKEND_DATA_ROOT` 抛 RuntimeError（对齐 dataset_config.py 既有决策）；docstring 示例同步

### A5 端点收敛 + E1 网络参数 env（提交 3 合并）
- **新建 `ingest/endpoints.py`**：NSMC_PORTAL_BASE/CENTER_BASE/TOKENSYNC（CGDA_NSMC_*）、CMR umm_json/json（CGDA_CMR_*）、URS token/tokens/profile（CGDA_URS_*），env 可覆盖默认现值
- 引用改造：`nsmc_portal.py:55-59`、`nsidc_download.py:210,347`、`gldas_download.py:168`、`data_access_nodes.py:281-282,749`
- **E1 env 通道**（默认值全保留现值）：`CGDA_DOWNLOAD_RETRIES`(3)/`CGDA_HTTP_TIMEOUT`(60)/`CGDA_DOWNLOAD_TIMEOUT`(3600)/`CGDA_MIN_DISK_FREE_GB`(5.0) → nsidc_download.py:57-62、nsmc_portal.py:448(600)、remote_sync.py:450,479(30)/555(300)
- 测试：`test_endpoints_env.py` + `test_http_env_overrides.py`（monkeypatch env + importlib.reload）；nsmc/nsidc/gldas 回归

---

## 阶段 B：基础设施/Tools（提交 5-8）

### B1 三脚本去仓库绝对路径
- `Tools/start_services.py:8-9` → `Path(__file__).resolve().parents[1]` + python 优先 sys.executable
- `Tools/start_fastapi_only.py:6` → 同模式推导 backend 路径
- `Tools/run_download.bat:2` → `cd /d "%~dp0"`

### B2 25 脚本 I 盘 env 化（codemod）
- 统一两行模式：`DATA_ROOT = os.getenv("BACKEND_DATA_ROOT", r"I:\Geograph_DataSet")`（默认值保留，零行为变化）
- 一次性 codemod 脚本 `Tools/_codemod_i_drive.py`（跑完删）：独立 token 整体替换 + 根+子路径前缀切分；**f-string/变量拼接形态输出人工清单不改**；缺 `import os` 自动补
- 收尾三件套：`py_compile Tools/*.py` 全量 + `grep` 残留 == env 默认值出现次数 + 抽查 3 脚本 dry-run + `ruff check Tools/`

### B3 sync_server_data 内网信息出库（提交 7）
- 新建不入库 `Tools/sync_server_data.local.json`（本机真实值实施时创建）+ 入库 `.example`（REPLACE_ME 占位）；`.gitignore` 追加
- 脚本 `_load_local_config()`：CLI 参数 > env（CGDA_SYNC_*，沿用 CGDA_SSH_TUNNEL_PORT 惯例）> local.json > 报错提示复制 example
- 出库项：LOCAL_BASE、私钥路径（含 2026-08-23 过期文件名）、内网 IP/账号/jump 别名、DATA_SOURCES 远程路径

### B4 docker 镜像 pin（提交 8）
- backend compose：minio/minio + mc + open-meteo `:latest` → 实施时 `docker inspect` 取本机版本/digest；open-meteo **对齐 data-sync 已 pin digest**
- MinIO minioadmin：注释强化 + .env.example 示例（不加 compose 检查——过度工程）

### B5 launch 端口收敛（保守）
- `gateway_manager.py:22` 改 `GATEWAY_PORT = int(os.getenv("CGDA_GATEWAY_PORT", str(DEFAULT_FRONTEND_PORT)))`（从 constants import 消双声明）；cli.py/commands.py 文案改 f-string 引用
- nginx.conf 顶部加注释块（listen/proxy_pass 与 CGDA_GATEWAY_PORT 联动需手动同步；模板化列技术债）
- 验证：`launch.py start gateway` 冒烟 + env 覆盖 5176 测试

---

## 阶段 C：种子日期占位符（提交 9）
- 7 文件 14 处 `2025xxxx` start/end_date → `{YYYYMMDD}`（展开逻辑已存在 resolver._DATE_PLACEHOLDER_RE）
- **语义变化**：原 start≠end 演示窗口 → 提交日当天；偏移语法（{YYYYMMDD-30d}）列技术债
- 文件：omega_avg_daily_gldas_online(30-31)/omega_sf_fenkuai_fy_dual(123-124)/fy_online(188-189)/fy_single(122-123)/smap_dual(81-82)/smap_online(106-107)/smap_single(80-81)
- 验证：各 `test_*_seed_compile.py` 断言更新 + `Tools/audit_workflow_seeds.py` 只读审计

---

## 阶段 D：前端（提交 10-13）

### D0 运行时配置单例（提交 10 基础，与 D1 同提交）
- 新建 `src/services/frontend-runtime-config.ts`：仿 system-settings-fill.ts 的 30s TTL 缓存模式；FALLBACK = 现硬编码值；`fetchGeneralConfig` 失败静默回退；hydrate 挂 settings.ts 的 hydrateMapDefaults 旁 + 使用点惰性 ensureRuntimeConfigLoaded()

### D1 Overpass 可配（提交 10）
- 后端：Settings 加 overpass_endpoint/timeout_sec/max_bbox_area_sq_deg/max_road_features（默认现值）；`config_contracts.py GeneralConfig` 加可选字段（已有 extra=ignore）；config_service 填充
- 前端：`basemap-extract.ts:33-38` 四常量改 getRuntimeConfig() 读取 + 发请求前 ensureRuntimeConfigLoaded()
- 注意：加 security 依赖须 re-export openapi + `npm run gen:types`（F14 闸门）——仅加字段无新路由则不需要

### D2 粤边界后端下发（提交 11，工程量最大）
1. 数据迁移：`@datapool/guangdong.geojson` 拷贝到 `Code/backend/app/static/boundaries/guangdong_440000_city.geojson`（实施前确认 license）
2. 后端：新建 `app/api/boundaries_routes.py`——`GET /boundaries/adcode/{adcode}`（仅支持 440000，未知 404）；lru_cache 读一次；ETag=sha256 前 16 位；Cache-Control max-age=86400；无鉴权 GET（非敏感公开数据）；main.py 挂载
3. 前端：`src/app/guangdong-boundaries.ts` 重写为 API 加载器（fetch `${base}/boundaries/adcode/440000` + 模块级缓存 + **失败降级动态 import @datapool 保留**）；3 消费点改调 `loadGuangdongCityBoundaries()`（basemap-extract.ts / admin-boundary-module.ts / display-projection.ts，均已异步化改动小）
4. 测试：`test_boundaries_routes.py`（200 特征 21 features/adcode 44 前缀/404/ETag 稳定）；前端 mock fetch + fallback 分支；手动冒烟（行政区图层+点选提取）

### D3 定位 fallback（提交 12）
- `map-chrome-controls.ts:395,405` 两处 `[113.26, 23.13]` → `getMapDefaults()` 的 longitude/latitude（未 hydrate 时返回值即广州，零回归）

### D4 TIMER_TZ 全链路（提交 13，依赖 #10 的 D0）
- 后端：Settings `timer_timezone`（BACKEND_TIMER_TZ，默认 Asia/Shanghai）+ workflow_timer_service.py:41 try/except ZoneInfo 回退告警 + GeneralConfig 下发
- 前端：WorkflowTimerPanel.vue:474,494 两处 'Asia/Shanghai' → getRuntimeConfig().timerTimezone；静态文案改「按系统时区（默认 Asia/Shanghai）」
- 测试：新增 env 指定 tz 的 cron 求值单测；timer 系列回归

---

## 提交序列（13 个，可独立回滚）
1. `fix(algo): GDAL 发现链跨平台化`（A1）
2. `fix(algo): SSH 工厂与 NSIDC 兜底去硬编码默认值`（A2+A4）
3. `refactor(algo): 外部端点收敛 endpoints.py + 网络参数 env 通道`（A5+E1）
4. `fix(backend): DATA_ROOT_WIN 跨平台展开 + 种子 posix 分隔符`（A3）
5. `chore(tools): 启动脚本去仓库绝对路径`（B1）
6. `chore(tools): 25 脚本数据根 env 化`（B2）
7. `chore(tools): sync_server_data 内网配置出库`（B3）
8. `chore(infra): docker 镜像 pin + launch 端口收敛`（B4+B5）
9. `feat(seeds): omega 种子日期改占位符`（C1）
10. `feat(backend+frontend): Overpass 参数经 /config/general 下发`（D0+D1）
11. `feat(backend+frontend): 粤边界按 adcode 后端下发`（D2）
12. `fix(frontend): 定位 fallback 用地图默认中心`（D3）
13. `feat(backend+frontend): 定时器时区 env 化`（D4，依赖 10）

## 验证策略
- 每提交：对应 pytest/vitest 子集 + ruff/eslint/prettier
- 收尾全量：算法包 639+ / 后端关键子集 / 前端 161 文件全量 + `npm run build` + F14 `check:openapi`
- 手动冒烟一次：全栈启动 → 行政区图层+定位+点选提取 → omega online compile → 设置面板新字段可见
- 提交前置 `env -u ACC_PRODUCT_CONFIG_V3`；推送后手动修正 origin/dev loose ref（已知坑）

## 明确不做（技术债登记）
deployment.config.json（用户决策）；overlay_registry 固定文件名（有降级）；前端 15 条运行常量全面配置化；512MB/128MB 上传阈值三处；{YYYYMMDD-30d} 偏移语法；nginx.conf 模板化；边界数据版本化
