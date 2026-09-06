# CGDA 微信小程序（Code/WeiXin）设计方案

> 日期：2026-08-22 ｜ 状态：方案评审稿（不动代码）
> 定位：**仅前端工程**，适配现有 FastAPI 后端；数据图层 + 底图 + 时间轴**纯显示**，无分析操作；预留 Agent 自然语言入口。
> UI 样板：Windy.com / Windy.app 移动版。

---

## 1. 现状盘点（后端已有能力 → 小程序可直接复用）

| 能力 | 后端接口 | 小程序用途 |
|---|---|---|
| 图层目录（含分组定义） | `GET /layers`（items + categories，X1 后端下发分类） | 右侧符号分组 + 图层抽屉数据源 |
| 栅格产品瓦片（GeoTIFF→PNG XYZ） | `GET /overlay-tiles/{layer_id}/{z}/{x}/{y}.png?time=&palette=&min_value=&max_value=` | SMAP/FY 等数据图层主渲染通道 |
| 图层边界+元数据 | `GET /overlay-bounds/{layer_id}?time=` | 时间序列图层的 time_list + palette/vmin/vmax/unit（colorbar 数据源） |
| 图层点取值 | `GET /overlay-value/{layer_id}?lng=&lat=&time=` | 点击地图小标签显示数据值（overlay 层） |
| 天气 GeoJSON 瓦片 | `GET /weather/tiles/{layer_id}/{z}/{x}/{y}?hour=0..47` | 在线天气图层渲染（canvas 绘制） |
| 天气点查询（含逐小时序列） | `GET /weather/point?layer_id=&latitude=&longitude=` | 点击小标签显示天气值（天气层） |
| 底图瓦片代理 | `GET /unified-tiles/{layer_id}/{z}/{x}/{y}`（天地图/高德/百度） | 本方案不用（底图用腾讯原生 map），留作备选 |
| 鉴权 | `POST /login`、API token（`/tokens`）、`GET /config` | 首版固定 token；后期 wx.login（后端配合项） |

关键结论：**MVP 无需任何后端改动**。API 无 `/api` 前缀；未带凭据返回 401 + `C403001` 为预期行为（登录时序参照）。

前端可移植资产（Web 版）：`WEATHER_PALETTES` 色带表（weather-render.ts，含 wind-blue/viridis 等）、GCJ02 偏移换算（geo-math.ts）、Windy 式时间轴交互逻辑（TimelineScrubber.vue）。

---

## 2. 核心架构决策

### 2.1 地图引擎：原生 map 组件 + 同层 Canvas 叠加（关键决策）

微信 `map` 组件的限制与机会：
- ✅ 底图即腾讯地图：默认街道矢量；`enable-satellite` 影像 —— 正好满足"一个影像一个街道"，且无需任何瓦片代理与域名白名单。
- ❌ **不支持自定义 XYZ 瓦片叠加**（无 raster source 概念），数据图层必须自绘。

三个候选方案对比：

| 方案 | 做法 | 结论 |
|---|---|---|
| **A. native map + canvas 叠加（推荐）** | 腾讯底图走 map 组件；数据图层用 canvas 2d（同层渲染）覆盖其上，按 Web Mercator 数学对齐，自绘 overlay PNG 瓦片与天气 GeoJSON | ✅ 采用。满足腾讯底图要求，数据通道全走自家后端 |
| B. 全 canvas 自绘地图 | 底图也自绘，走 `/unified-tiles` 代理（天地图/高德） | ❌ 违背"底图用腾讯"；后端未代理腾讯瓦片 |
| C. map 组件 polygons 承载数据 | GeoJSON 转 polygons 属性 | ❌ 数量上限低（格点数据必超），性能不可行 |

**方案 A 对齐原理**（canvas 与腾讯地图叠合的核心）：
1. `bindregionchange`（end）读取 `center + scale`；小程序 scale 与 Web Mercator z 级近似对应（z ≈ round(scale)）。
2. 以屏幕中心经纬度（GCJ-02→WGS-04 纠偏）+ scale 计算 mercator 像素矩阵 → 推算视口四角对应 z/x/y 瓦片集合。
3. `wx.request` 拉取 PNG（overlay-tiles）/ GeoJSON（weather-tiles），`drawImage` / path 绘制到 canvas，逐瓦片按地理坐标换算屏幕像素定位。
4. 拖动/缩放期间重绘（regionchange begin 先清屏或冻结上一帧，end 精确重绘），体验对齐 Windy。

**必踩坑（写入实现规范）**：
- **坐标系偏移**：map 组件坐标为 GCJ-02（火星坐标），后端全部 WGS-84。所有"屏幕→地理→API"和"API→地理→屏幕"往返必须过 `gcj02↔wgs84` 换算（纯 JS 实现，从 web 版 geo-math 移植）。漏掉会出现"瓦片整体偏移几百米"的经典 bug。
- **禁用旋转/倾斜**：`enable-rotate=false`、`enable-overlooking=false`、`enable-skew=false`（旋转态下 mercator 对齐失效）。
- **同层渲染兼容**：canvas 覆盖 map 依赖同层渲染；**M1 第一周做技术验证 spike**（WebView 模式基础库 ≥ 2.9.0 与 Skyline 模式各验一遍），不达标即切 Skyline（小程序项目配置 `"renderer": "skyline"` + `"componentFramework": "glass-easel"`）。
- **并发限制**：`wx.request` 并发上限 10 → 瓦片调度器需队列 + LRU。
- 天气 GeoJSON 低 zoom feature 密度高 → 视口裁剪 + 简化（后端 tile 已做 clip，前端再按 zoom 控制绘制粒度）。

### 2.2 技术栈：原生小程序 + TypeScript

- **原生框架**（非 uni-app / Taro）：只投微信一个端；map 组件 + 同层渲染兼容性最好；包体最小；避免跨端框架的同层渲染适配坑。
- TS + gulp/或直接 JS（微信开发者工具支持 TS 编译），npm 依赖 MVP 尽量为零（色带表、坐标换算全部内联移植，控制主包 < 2MB）。
- 状态管理：轻量发布订阅 store（自写 ~100 行），不引 mobx-miniprogram 亦可。
- 开发工具链：微信开发者工具 + wechatide CLI（本机已具备，支持编译/预览/自动化截图验证）。

### 2.3 网络与鉴权

- 后端直连 FastAPI（如内网 `https://<host>/`，无 /api 前缀）。
- **域名白名单**：正式环境需后端具备 **HTTPS** 域名并加入小程序后台 request/downloadFile 合法域名；开发期勾选"不校验合法域名"。→ 部署依赖项，需运维确认。
- 鉴权策略分期：
  - M1–M4：内置服务账号/API token（`POST /login` 换 session 或长效 token 存 storage，401+C403001 时静默重登）。
  - 后期：`wx.login` → code2Session 打通（**需后端新增接口**，列为后端配合项，不阻塞 MVP）。

---

## 3. 页面与信息架构（单页地图应用）

Windy 移动版布局映射（全屏地图为底，控件浮于其上）：

```
┌──────────────────────────────────────────┐
│ [自动 colorbar：palette 渐变 + 刻度 + 单位] │  ← 顶部通栏，随主图层自动切换
│ ┌──┐                            ┌──────┐ │
│ │logo│                          │图层分组│ │  ← 左上角 logo（无文字）
│ └──┘                            │符号竖条│ │  ← 右侧分组 rail（W/V/T/L/R/C…）
│                                 │      │ │
│        全屏腾讯底图              ├──────┤ │
│      （街道 ⇄ 影像切换）         │图层  │ │  ← 点分组符号右拉出该组图层列表
│                                 │抽屉  │ │     （Windy 式，选中即收回）
│  [比例尺]                        │      │ │
│                    [📍点位标按钮] │      │ │  ← 左下比例尺 / 右下点位标
│ ┌────────────────────────────────────────┤
│ │       时间轴（占满全屏宽）              │  ← 底部通栏：拖动 + 时间标签
│ └────────────────────────────────────────┘
└──────────────────────────────────────────┘
点击地图任意点 → 小标签（图层名 + 数值 + 单位 + 时间），不弹大面板
```

组件清单（`components/`）：

| 组件 | 职责 | 数据源 |
|---|---|---|
| `map-shell` | map 组件 + 数据 canvas 叠加 + 手势/对齐引擎 | tiles 调度器 |
| `logo-badge` | 左上角 logo（纯图，无文字） | 静态资源 |
| `colorbar` | 顶部自动色带条：渐变 + legend_ticks + 单位 | 主图层 palette/vmin/vmax/unit |
| `layer-rail` | 右侧 category 符号竖条（激活组高亮） | `GET /layers` categories |
| `layer-drawer` | 右拉抽屉：组内图层单选/可见性 | `GET /layers` items |
| `timeline` | 底部全宽时间轴：拖动滑块 + 当前时间标签 + 播放（预留） | 主图层时间域 |
| `scale-bar` | 左下比例尺（scale→米/像素自绘线段） | regionchange scale |
| `point-marker` | 右下点位标按钮：钉一个 marker（无缩放/旋转控制） | 本地状态 |
| `point-popup` | 点选小标签：浮层显示取值结果 | overlay-value / weather/point |
| `agent-entry` | Agent 对话入口（**M5 预留**，默认隐藏） | — |

---

## 4. 数据流与状态设计

### 4.1 单主图层模型（Windy 式，简化一切）

- 同一时刻只有**一个主数据图层**（drives colorbar + timeline + 点取值）；底图（街道/影像）独立切换。
- 图层抽屉内选择即切换主图层；支持"隐藏/显示"当前主图层。
- 理由：多层叠加时 colorbar 与时间轴归属会歧义，纯显示场景单主图层足够；后续要叠加再扩展为"主图层 + 辅图层"。

### 4.2 时间轴的两种时间域（自动适配）

| 主图层类型 | 时间域来源 | 时间轴形态 |
|---|---|---|
| 天气层（is_realtime / weather tiles） | hour 0–47 预报小时 | 48 tick 连续刻度（Windy 风格），拖动 → 重拉 `?hour=` |
| overlay 时序层（SMAP/FY 等） | `overlay-bounds` 的 time_list（如 YYYYMMDD、8 天步长） | 离散日期刻度，拖动吸附到最近有效时间 |
| 静态层 | 无 | 时间轴折叠/禁用 |

- 时间切换 → 仅失效受 time 参数影响的瓦片（`t=` cache-bust），其余瓦片命中缓存。
- 相邻时间帧预取（前后各 1 帧），保证拖动流畅（后端 prefetch 思路的客户端版）。

### 4.3 瓦片调度器（tiles service，核心模块）

```
regionchange end → 计算视口 z/x/y 集合（含屏幕外 1 圈缓冲）
  → 与已加载集合 diff → 请求队列（并发≤10，优先视口中心）
  → LRU 缓存：内存 Map + FileSystemManager 文件缓存（上限 ~50MB，LRU 淘汰）
  → 绘制管线：clear → 按 z 对齐矩阵 drawImage(PNG) / path(GeoJSON) → 委托 canvas commit
  → 失败重试（指数退避 ×2）→ 连续失败展示占位/静默降级
```

### 4.4 Colorbar 自动化

- 数据源优先级：`overlay-bounds` 元数据（palette/vmin/vmax/unit）＞天气层 renderHint（`GET /layers` descriptor.style + WeatherLayerRenderHint）。
- 前端内置色带表：从 web 版 `WEATHER_PALETTES` 移植为纯 TS 常量（palette id → 16 档色标数组），渲染色带渐变 + legend_ticks 刻度 + 单位。
- 未知 palette id → 回退 viridis（web 版有后端→前端色带 ID 映射表，一并移植）。

### 4.5 点取值（点击小标签）

```
map bindtap（e.detail 经纬度，GCJ-02）
  → gcj02→wgs84 → 判定主图层类型
  → overlay 层：GET /overlay-value/{layer_id}?lng&lat&time（time=当前时间轴标签）
  → 天气层：GET /weather/point?layer_id&latitude&longitude（forecast_hours=6）
  → point-popup：图层名 + 数值 + 单位 + 时间点（单值，不画序列图）
```

---

## 5. 工程目录规划（Code/WeiXin）

```
Code/WeiXin/
├─ project.config.json          # appid、skyline/webview 渲染模式、基础库版本
├─ miniprogram/
│  ├─ app.ts / app.json / app.wxss
│  ├─ pages/index/              # 唯一主页面（全屏地图应用）
│  ├─ components/
│  │  ├─ map-shell/             # map + canvas 叠加 + 对齐引擎（核心）
│  │  ├─ colorbar/  layer-rail/  layer-drawer/
│  │  ├─ timeline/  scale-bar/
│  │  └─ point-marker/  point-popup/  logo-badge/  agent-entry/
│  ├─ services/
│  │  ├─ api.ts                 # 后端 API 封装（token 注入 + 401 重登）
│  │  ├─ tiles.ts               # 瓦片调度器（LRU + 队列 + 重试）
│  │  ├─ catalog.ts             # 图层目录缓存（storage 持久化）
│  │  └─ geo/
│  │     ├─ gcj02.ts            # GCJ-02 ↔ WGS-84（移植 geo-math）
│  │     ├─ mercator.ts         # z/x/y ↔ 像素 ↔ 经纬度矩阵
│  │     └─ palettes.ts         # 色带表（移植 WEATHER_PALETTES）
│  ├─ store/                    # 轻量发布订阅：layers/time/basemap/point
│  └─ assets/                   # logo、分组图标（SVG→PNG 内联）
├─ typings/
└─ README.md                    # 与 Code/README.md 风格一致
```

---

## 6. 实施阶段（SOP）

> **进度（2026-08-22）**：M0 ✅ M1 ✅（见 Code/WeiXin/README.md 验收表：同层渲染 OK、对齐 0.3px、卫星切换 OK；技术栈微调为 ES6 JS 起步，M2 评审 TS 迁移）

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **M0 骨架验证 spike（0.5 周）** ✅ | 建项目（wechatide CLI）；**验证同层渲染 canvas 覆盖 map**；验证 regionchange→mercator 对齐精度与 enable-satellite | 实测对齐误差 **0.3px**（z12/z16，getRegion 四角自检）≪ 5px 标准；marker 与 canvas 地标重合 |
| **M1 地图壳（0.5 周）** ✅ | 全屏 map、街道/影像切换、禁旋转、logo、比例尺 | 双底图切换正常；比例尺随缩放更新（z12→2km，z16→100m） |
| **M2 图层链路（1 周）** | login/token、GET /layers、右侧分组 rail + 抽屉、overlay-tiles canvas 叠加、colorbar 自动 | 任选 SMAP/FY 层可见且与 Web 端视觉一致；colorbar 正确 |
| **M3 时间轴（1 周）** | 双时间域适配、帧预取缓存、拖动刷新、时间标签 | 天气层拖 hour、overlay 层拖日期均流畅（≥ 24fps 体验）；静态层时间轴折叠 |
| **M4 交互收尾（0.5 周）** | 点选取值小标签、点位标、GCJ02 纠偏回归、异常态（离线/401/瓦片失败） | 点取值与 Web 端 InfoPanel 数值一致；断网有占位提示 |
| **M5 打磨 + Agent 预留（0.5–1 周）** | 包体优化、真机预览（wechatide auto_preview）、agent-entry 隐藏入口 + WebSocket 会话占位 | 真机通过；主包 < 2MB |

总计约 4 周单人量。每阶段结束跑一次 wechatide 自动化截图比对。

---

## 7. 风险与依赖清单

| # | 风险/依赖 | 等级 | 对策 |
|---|---|---|---|
| R1 | 同层渲染兼容性（canvas 盖 map） | 高 | M0 spike 前置；Skyline 兜底；最坏退化方案：数据图层用 cover-image 网格拼贴（性能差，仅保底） |
| R2 | GCJ-02/WGS-84 偏移 | 高 | 统一 geo 模块收口；M4 专项回归（用 Web 端同点位数值对拍） |
| R3 | HTTPS 域名 + 小程序合法域名 | 高（部署依赖） | 需运维给出公网 HTTPS 网关地址；开发期关校验 |
| R4 | overlay-tiles 后端动态渲染首帧慢（GDAL 切 PNG） | 中 | 客户端时间帧预取 + 后端已有 tile cache（X-Tile-Cache）；必要时提后端预热（后端配合项，非阻塞） |
| R5 | wx.login 鉴权打通 | 中 | MVP 用固定 token；后端新增 code2session 接口列入"后端配合项" |
| R6 | 天气 GeoJSON 高密度绘制 | 中 | zoom 分级绘制 + 视口裁剪；canvas 路径合并 |
| R7 | 并发 10 上限 + 瓦片风暴 | 低 | 队列 + 视口 diff + 缓冲 1 圈；regionchange 高频节流 |
| R8 | Agent 接入 | 低（远期） | SSE 小程序不支持 → WebSocket 流式；仅留 UI 入口与协议占位 |

**需后端/运维配合项汇总（均不阻塞 MVP）**：① 公网 HTTPS 网关；② wx.login code2session 接口；③ Agent 对话 WebSocket 协议；④（可选）overlay 瓦片预热。

---

## 8. 与 Web 前端的边界

- 小程序**不移植**：工作流编辑器、分析工具、导入导出、绘制/测量、InfoPanel 大面板 —— 全部超出"纯显示"范围。
- 共享心智：色带表、坐标换算、时间轴交互语义与 Web 端对齐（视觉语言一致，用户在两端看到同名图层同色）。
- 代码不共享（跨端框架已否决），以"契约共享"替代：类型定义参照 `openapi.json` 手工精简为 TS 接口（仅取用到的 8 个端点）。

---

## 附：术语对照

| 本文 | 后端/代码对应 |
|---|---|
| 主图层 | layer_descriptor（render_type/数据通道决定 tiles 端点） |
| overlay 层 | overlay_registry OverlaySpec（GeoTIFF 时序产品） |
| 天气层 | weatherengine WEATHER_LAYER_SPECS（GeoJSON tiles + point） |
| 分组 | LayerCategoryDef（catalog_seeds/layer_categories.json：climate/landcover/terrain/vegetation/research-group/imported/weather） |
| 时间域 | weather: hour 0–47；overlay: spec.time_list |
