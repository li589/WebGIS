# 本地 Open-Meteo 完善计划（2026-07-21）

> 状态：**Phase A 已落地 · Phase B/C/D 待办**  
> 范围：本地数据拉取 / 自动同步 / 天气模型选择真源贯通  
> 不在本轮：重做瓦片几何、风粒子渲染、多 Provider（WeatherAPI 等）商业化

### Phase A 落地摘要（2026-07-21）

| 项 | 状态 |
|----|------|
| `GET /config/weather` 扩展 default_model / sync_domains / supported_models | 已完成 |
| `PUT /config/weather/model` + SQLite `weather_engine.sqlite3` | 已完成 |
| `GET /weather/sync/overview` | 已完成 |
| coverage 错误码 local_unreachable / model_empty / probe_error | 已完成 |
| sync 结果写入 last_sync；status 增强 | 已完成 |
| 瓦片/点预报默认 model 读 DB 真源 | 已完成 |
| 单测 `test_weather_engine_settings_phase_a.py` | 已完成 |

下一刀：**Phase B 前端 Store 贯通**。

---

## 0. 目标与非目标

### 目标（用户可感知）

1. 设置页改「天气模型」后，**时间轴覆盖、瓦片请求、点预报**立刻用同一模型。
2. 设置页能看到：**已配置 sync 域、上次同步结果、本地服务是否可达**；选未 sync 的模型时有明确提示。
3. 手动/定时同步可观测、失败可诊断（不再只有 Celery `task_id`）。

### 非目标

- 不引入多模型同时渲染（本轮仍是「全局默认模型」）。
- 不把 sync 从 Docker 换成原生下载器（继续 `docker compose run open-meteo-sync`）。
- 不预生成全图瓦片磁盘缓存（继续按视口按需拉取）。

### 成功标准

| # | 验收 |
|---|------|
| A | 前端三处默认一致：设置页 / `weather-tile-manager` / `DashboardView` coverage 均读同一后端 `default_model` |
| B | 改模型并保存后，下一帧瓦片 URL 带新 `model=`，coverage 探针同参刷新 |
| C | `GET /weather/sync/overview`（或等价）返回 domains、cron、last_run、local_reachable |
| D | 选未列入 `sync_domains` 的模型时，UI 显示「需先加入同步域并触发 sync」，不静默 503 |
| E | 补齐至少：coverage mock 单测、sync dispatch mock 单测、前端 store 模型贯通单测 |

---

## 1. 现状诊断（事实）

### 1.1 已有骨架

| 能力 | 位置 | 备注 |
|------|------|------|
| 双 Provider | `open_meteo_provider.py` / `provider_registry.py` | local priority=0 默认 |
| 本地 URL / 模型 remap | `provider_ids.py` | `best_match`→`ecmwf_ifs025` |
| Coverage 探针 | `GET /weather/coverage` | 10min 内存缓存；Dashboard **不传 model** |
| Sync 任务 | `open_meteo_sync_tasks.py` + Celery Beat | 读 `OPEN_METEO_SYNC_DOMAINS` |
| 手动 sync | `POST /weather/sync/trigger` + status | 需 Celery |
| 设置 UI | `OpenMeteoSyncSettings.vue` | 模型仅 `localStorage` |
| 瓦片模型 | `weather-tile-manager.ts` | 硬编码 `DEFAULT_WEATHER_MODEL='best_match'` |
| 后端默认模型 | `settings.weather_default_model` | 默认 `ecmwf_ifs025`；`GET /config/weather` 已暴露 |

### 1.2 核心断裂点

```
设置页 selectedModel (localStorage)
        │ 仅影响 OpenMeteoSyncSettings 的 coverage
        ▼
┌───────────────────┐     ┌────────────────────────────┐
│ Dashboard coverage│     │ tile-manager / tile API    │
│ model=undefined   │     │ model=best_match（硬编码） │
│ → 后端 default    │     │ → 本地 remap 成 ifs025     │
└───────────────────┘     └────────────────────────────┘
        │                              │
        └────────── 不同路径 ──────────┘
                   易出现：探针绿、瓦片空 / 改模型无效
```

Sync 真源是环境变量 `OPEN_METEO_SYNC_DOMAINS`，与设置页 7 模型列表**无交集校验**。

---

## 2. 目标架构

### 2.1 单一配置真源

```
Backend settings / DB（可选持久化）
  weather_default_model
  open_meteo_sync_domains
  open_meteo_sync_enabled + cron
        │
        ▼
GET /config/weather  （已有，扩展字段）
GET /weather/sync/overview  （新增）
        │
        ▼
Pinia: useWeatherEngineStore（新建）
  defaultModel / syncDomains / lastSync / localReachable
        │
        ├─► OpenMeteoSyncSettings（读写）
        ├─► DashboardView coverage(model)
        └─► weather-tile-manager model 参数
```

**本轮默认策略**：全局一个 `default_model`（不按图层钉模型）。图层仍可钉 **Provider**（local/online），与模型正交。

### 2.2 模型解析规则（写进代码注释 + 规范）

| 场景 | 行为 |
|------|------|
| Provider = local，model = `best_match`/`auto`/空 | remap → `weather_default_model`（或 `BACKEND_OPEN_METEO_LOCAL_MODEL`） |
| Provider = online | 允许 `best_match`（官方 ensemble） |
| UI 可选列表 | = 已知模型全集 ∩（建议）与 `sync_domains` 标注「已同步 / 未同步」 |
| 瓦片请求 | **禁止**前端再写死 `best_match`；未加载配置前可用 `ecmwf_ifs025` 作 bootstrap |

---

## 3. 分阶段实施

### Phase A — 配置真源与 API（后端优先）

**工期建议**：0.5–1 天

| 任务 | 细节 |
|------|------|
| A1 扩展 `GET /config/weather` | 增加：`default_model`, `sync_domains`（list）, `sync_enabled`, `sync_cron` 摘要, `supported_models`（静态白名单，与前端列表同源可后续共享） |
| A2 新增 `PUT /config/weather/model` 或扩现有 PUT | Body: `{ "default_model": "ecmwf_ifs025" }`；校验白名单；写入 DB（若已有 config 表）或进程内 + 文档说明「持久化依赖 DB」；同步更新运行时 `settings` 可读路径 |
| A3 新增 `GET /weather/sync/overview` | 返回：`domains`, `enabled`, `cron`, `compose_ready`（docker 是否可调用，best-effort）, `last_success_at`, `last_failure_at`, `last_message`, `local_reachable`（轻量 ping coverage 或 health） |
| A4 改进 `GET /weather/sync/status` | 成功时附带 `finished_at`、`domains`、stderr 截断；失败时 `error` 人类可读 |
| A5 Coverage 错误码 | 区分：`local_unreachable` / `model_empty`（hourly 全空）/ `probe_error`；HTTP 仍可用 503 + `code` 字段，供前端文案 |

**持久化建议（二选一，计划默认选 P1）：**

- **P1（推荐）**：写入现有 `config_service` / DB 配置行（与 Provider 配置同路径），进程启动加载覆盖 env 默认值。
- **P2（最小）**：仅 env + 重启生效；PUT 返回 501「请改环境变量」——不满足「设置页改即用」，仅作兜底。

**验收**：curl 改 `default_model` 后，`/weather/coverage` 无参与有参均一致；瓦片服务未传 model 时用新值。

---

### Phase B — 前端 Store 贯通

**工期建议**：0.5–1 天

| 任务 | 细节 |
|------|------|
| B1 新建 `stores/weather-engine.ts` | 启动时 `fetchWeatherConfig()`；暴露 `defaultModel`, `setDefaultModel()`, `syncOverview`, `refreshCoverage(model?)` |
| B2 改 `weather-tile-manager.ts` | 去掉硬编码 `best_match`；`resolvedModel = model ?? weatherEngineStore.defaultModel`；store 未就绪时 fallback `ecmwf_ifs025` |
| B3 改 `weather-tile-api.ts` 默认参数 | 与 B2 一致，避免静默 `best_match` |
| B4 改 `DashboardView` | `getWeatherCoverage(defaultModel)`；watch `defaultModel` 刷新 coverage |
| B5 改 `OpenMeteoSyncSettings.vue` | 去掉孤立 `localStorage` 真源（可作离线缓存）；读写 store；模型下拉展示 sync 状态徽章 |
| B6 Provider 设置页交叉提示 | 若当前 Provider=local 且模型未 sync，显示 Callout |

**验收**：设置页改模型 → 地图瓦片网络面板 `model=` 变化；时间轴色条同步刷新。

---

### Phase C — Sync 运维可观测

**工期建议**：0.5 天

| 任务 | 细节 |
|------|------|
| C1 Sync 结果落库/落 Redis | `execute_open_meteo_sync` 成功/失败写 `last_sync` 摘要（时间、domains、exit_code、stderr 尾 2KB） |
| C2 设置页「同步域」只读展示 | 来自 overview；本轮 **不**做 UI 改 env domains（避免 Docker 权限误导）；文档写明改 `OPEN_METEO_SYNC_DOMAINS` |
| C3 可选：`POST /weather/sync/trigger` body `{ domains?: string }` | 临时覆盖本次 domains（不改持久配置）；需校验白名单 |
| C4 部署文档 | ✅ `Code/backend/.env.open-meteo.example`；运行栈 `docker compose -p backend up -d`；同步 `python launch.py sync` / `Code/infra/data-sync`；Worker 需 Docker CLI |
| C5 更新 `Doc/规范文档.md` §15.4 | ✅ `open-meteo-local` / `open-meteo-online`（遗留 `open-meteo` → online） |

**验收**：触发 sync 后 overview 有 `last_*`；Celery 不可用时 UI 明确「同步服务不可用」。

---

### Phase D — 测试与回归

**工期建议**：0.5 天

| 测试 | 内容 |
|------|------|
| D1 后端 | `test_weather_coverage.py`：mock urlopen；空 hourly / 超时 / 成功 |
| D2 后端 | `test_open_meteo_sync_api.py`：trigger 无 celery→503；overview 字段；model PUT 校验 |
| D3 前端 | `weather-engine` store 单测；tile-manager 使用 store model |
| D4 手工 | local 起容器 → 改模型（已 sync）→ 风场/温度图层 → 时间轴绿段与瓦片一致；停容器 → coverage 红字可读 |

---

## 4. 接口草图（供实现时对照）

### 4.1 `GET /config/weather` 扩展字段

```json
{
  "default_model": "ecmwf_ifs025",
  "sync_domains": ["ecmwf_ifs025"],
  "sync_enabled": true,
  "sync_cron": { "minute": "30", "hour": "*/6", "timezone": "UTC" },
  "supported_models": [
    { "id": "ecmwf_ifs025", "label": "ECMWF IFS 0.25°", "region": "global" }
  ]
}
```

### 4.2 `GET /weather/sync/overview`

```json
{
  "local_reachable": true,
  "domains": ["ecmwf_ifs025"],
  "enabled": true,
  "last_success_at": "2026-07-21T02:30:00Z",
  "last_failure_at": null,
  "last_message": "ok",
  "compose_hint": "docker compose -p backend up -d open-meteo  # API; sync: python launch.py sync"
}
```

### 4.3 `PUT /config/weather/model`

```json
{ "default_model": "gfs_global" }
```

→ 若 `gfs_global ∉ sync_domains`：仍允许保存（online 或未来 sync），但响应带 `warning: "not_in_sync_domains"`。

---

## 5. 文件改动清单（预期）

### 后端

- `app/core/config.py` — 已有字段，确认文档
- `app/services/config_service.py` — 读/写 default_model
- `app/api/config_routes.py` — PUT model
- `app/api/routers/weather_router.py` — coverage code、sync overview、status 增强
- `app/tasks/open_meteo_sync_tasks.py` — 写 last_sync
- `tests/test_weather_coverage.py`、`tests/test_open_meteo_sync_api.py`（新建）
- `Code/backend/.env.open-meteo.example`（新建）

### 前端

- `stores/weather-engine.ts`（新建）
- `stores/weather-tile-manager.ts`
- `services/weather-tile-api.ts`、`services/runtime-api.ts`、`services/settings-api.ts`
- `components/settings/OpenMeteoSyncSettings.vue`
- `views/DashboardView.vue`
- 可选：`WeatherProviderSettings.vue` 交叉提示

### 文档

- 本文档（计划）
- `Doc/规范文档.md` §15.4
- `Doc/天气渲染进度同步-2026-07-21.md` 可加一行「Open-Meteo 配置真源见独立计划」

---

## 6. 风险与依赖

| 风险 | 缓解 |
|------|------|
| Celery Worker 无 Docker | overview 标 `compose_ready=false`；文档要求挂载 docker.sock 或同机部署 |
| 改模型后旧瓦片缓存串味 | tile key 已含 model 则自然隔离；确认 cache key 含 model（审计 `tile_service` / 前端 mergeCache） |
| DB 不可用时 PUT 失败 | fallback 读 env；UI 提示只读 |
| 多 Worker 内存 settings 不一致 | 持久化必须以 DB/Redis 为准，请求时读取，忌只改单进程全局 |

---

## 7. 建议排期

| 顺序 | Phase | 可交付 |
|------|-------|--------|
| 1 | A | API 可 curl 验收 |
| 2 | B | 设置改模型即影响地图 |
| 3 | C | 同步可观测 |
| 4 | D | 回归与文档 |

合计约 **2–3 人日**。若只做「最小可用」：A1 + A2(P1) + B1–B5 + D4 手工 ≈ **1.5 人日**，C 可第二周。

---

## 8. 确认清单（动手前）

- [ ] 采用 **P1 持久化**（DB）还是 **P2 env-only**？
- [ ] 本轮是否允许 `POST sync` 临时覆盖 domains？
- [ ] 全局单模型是否足够（不做 per-layer model）？
- [ ] 是否需要同步改 `Doc/项目任务清单.md` 勾选？

确认后从 **Phase A** 开工。
