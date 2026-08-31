# CGDA 微信小程序（Code/WeiXin）

> 仅前端工程，适配 CGDA FastAPI 后端；数据图层 + 腾讯底图 + 时间轴**纯显示**。
> 设计方案：`.ai/plans/2026-08-22-weixin-miniprogram-design.md`

## 当前状态：M0 ✅ M1 ✅ M2 ✅ M3-UI ✅（2026-08-30：禁首屏自动选层）

- **进入页不自动加载任何叠加图层**（含 dem-etopo）；目录只拉 `/layers`+`/overlays`，bounds/瓦片仅在用户点选后请求。
- **canvas 按需挂载**（`showOverlayCanvas`）；UI 经 `root-portal` 置于原生 map/canvas 之上。

### M0 spike 验收结果（模拟器实测）

| 验收项 | 标准 | 实测 | 结论 |
|---|---|---|---|
| canvas 同层渲染覆盖 map | 叠加层可见且手势透传 | ✅ `pointer-events:none` 生效，拖动/缩放流畅 | 通过 |
| UI 控件不被瓦片盖住 | colorbar/工具栏/时间轴始终在 canvas 之上 | ✅ `.ui-layer`（普通 view + z-index:20）承载控件；勿把定位 class 直接挂在自定义组件 host 上 | 通过（2026-08-30 修复） |
| mercator 对齐精度（z12） | 错位 < 5px | **0.3px**（getRegion 四角自检） | 通过 |
| mercator 对齐精度（z16 卫星） | 错位 < 5px | **0.3px** | 通过 |
| marker ↔ canvas 圆点重合 | 目视重合 | ✅ 重合（z16 截图） | 通过 |
| enable-satellite 影像切换 | 正常 | ✅ | 通过 |

自检测试：组件内 `_selfTest()`（M2 移除），经 `MapContext.getRegion` 取视口角点反投影验证。

### M1 地图壳

- 全屏腾讯底图（街道 ⇄ 影像切换，右下按钮）
- 禁旋转/倾斜/3D（`enable-rotate/overlooking/skew/3D = false`，对齐前提）
- 左上 logo（纯 CSS 占位，无文字）；左下比例尺（随缩放自适应 1/2/5 序列）
- 顶部 colorbar 占位（M2 接入）；**底部时间轴已完整接入**（见 M3-UI）

### M3-UI 时间轴（提前于图层链路）

四种时间域统一一个 `timeline` 组件：

| 模式 | 数据源 | 视觉 |
|---|---|---|
| `hour` | 天气预报 hour 0–47 | 48 ticks，主刻度为日分隔（"现在"、"8/23"、"8/24"），主标签 "周X HH:00"，副 "M月D日 · +Nh" |
| `day` | 产品时序 time_list（如 SMAP） | 31 ticks（近 31 天），主刻度月分隔，主标签 "M月D日"，副 "YYYY年 · 第N/31天" |
| `month` | 月度粒度产品 | 25 ticks（近 25 个月），主刻度年分隔，主标签 "YYYY年M月"，副 "月度数据 · N/25" |
| `static` | 无时间维度的图层 | 轨道收起，播放按钮禁用，提示 "静态图层 · 无时间维度" |

交互（Windy 式）：
- 拖动轨道任意位置 → 吸附最近 tick（`bindtouchstart/move` → `_rect` 缓存 + `Math.round`）
- 播放按钮 → 700ms 间隔自增，到末回卷（`setInterval` + `triggerEvent('change')`）
- 点模式 chip → 循环切换 `hour → day → month → static`（M2 接图层选择前的演示入口）

**模拟器验收**：四模式 + 播放推进（实测 current 0→45）+ 中段（current=24）拖动视觉均通过。

### M2 图层链路

完整接入后端 CGDA FastAPI（127.0.0.1:8000）：
- `services/api.js`：POST /auth/login（开发预填账号）→ 会话 cookie；GET /layers + /categories + /overlays + /overlay-bounds + /overlay-tiles 自动 401 重登
- `services/catalog.js`：目录归一为「分组 rail + 抽屉」，**加载时并行拉所有 overlay-bounds 标注 xyz 能力并按 `supports_xyz_tiles` 二次过滤**（后端 GDAL XYZ 切片能力薄，非 COG 缺金字塔的图层会被隐藏）
- `services/palettes.js`：24 套色带逐色对齐后端 `raster_preview_service._PALETTES`（色块从后端 dump，色带与瓦片渲染严格一致）
- `services/tiles.js`：视口 WGS-84 瓦片集合 → 并发≤6 队列 → 文件缓存（userData/tiles/，LRU 400 上限）→ Image onload
- 瓦片绘制：每片四角 WGS-84 → GCJ-02 → P() 投影到屏幕，与底图严格同链路（含火星偏移，0.3px 实测已涵盖）
- `components/layer-rail`：右侧分组符号竖条 + 计数徽标
- `components/layer-drawer`：右滑抽屉（遮罩 + 72vw 白卡 + 名称/描述/时间能力徽章）
- `components/colorbar`：palette/vmin/vmax/unit 自动；离散色（tab10）用色块，连续色用渐变条 + 5 刻度

**模拟器验收（实测）**：
- 默认图层 dem-etopo（全局 ETOPO 高程，terrain 渐变）→ 30/30 瓦片全加载
+ ~~默认自动加载 dem-etopo~~（已关闭：`AUTO_SELECT_DEFAULT_LAYER=false`；进页仅底图+控件，右侧工具栏手动选层）
+- 手动选 dem-etopo → 按需挂载 canvas → 30/30 瓦片（对齐后再绘）
- 切 CLCD 土地利用（土地覆盖，discrete tab10）→ 离散色块可视，30/30 加载
- 切 CMFD 区域降水（climate，YlGnBu 渐变）→ 30/30 加载
- 切 CO₂ 柱浓度（climate，RdYlGn_r 渐变）→ 30/30 加载

**后端 XYZ 能力现状（限制说明）**：本机后端仅 4 个图层带 `supports_xyz_tiles=true`：dem-etopo / co2-cn / cmfd-precip-cn / clcd-cn，**且全部 static 无 time_list**。所以当前 rail 仅显示 3 个分类（C/L/T），所有图层 time 轴均收为静态模式。后续图层接 COG 概述金字塔（`supplemental_overviews` 或 fsspec range request）即可让更多 time-series 图层进入 rail，时间轴动态切换能力已就绪（`_buildTimelineFromTimeList` 支持 YYYYMM/YYYYMMDD 解析）。

## 技术决策备忘

1. **ES6 JS 起步，非 TS**：M0/M1 优先零工具链风险跑通同层渲染验证；模块结构已按 TS 规划组织（`services/geo`、`store`），M2 评审是否迁移（迁移 = 重命名 + 补类型注解）。
2. **坐标系**：map 组件 = GCJ-02；后端 = WGS-84。所有换算收口在 `services/geo/gcj02.js`，禁止散写。
3. **对齐模型**：`regionchange(end)` → `getCenterLocation` + `getScale` → mercator 投影锚定画布中心。手势期间冻结上一帧（M3 做连续同步）。
4. **z 语义**：map `scale`（3–20 浮点）直接等价 Web Mercator z（实测 0.3px 验证）。

## 运行

1. 微信开发者工具导入本目录（AppID：接口测试号 wxda07edd368e0f67c，或自己的）。
2. 编译即可；模拟器内点「影像/街道」切底图，点击地图打蓝色十字（GCJ→WGS 换算见 console）。

## wechatide CLI 操作备忘（本机）

- 路径：`"C:\Program Files (x86)\Tencent\微信web开发者工具\wechatide.cmd"`（不在 PATH；Git Bash 调含空格/中文路径的参数会断，**一律用 PowerShell `&` 调用**）。
- clientName：`CodeBuddy`（已授权信任）。
- 常用：`open_project_window --project <path>` → `simulator_open_page --page pages/index/index` → `simulator_screenshot`；运行时取值用 `automation_evaluate --fn-source <单行JS，字符串字面量只用单引号> --args-file <json 数组>`。
- 调试 HUD 为 M0 专用，M2 前移除（`_selfTest` 一并移除）。

## 目录

```
miniprogram/
├─ pages/index/            # 唯一主页面（全屏地图应用）
├─ components/
│  ├─ map-shell/           # 核心：map + canvas 叠加 + 对齐引擎 + 瓦片调度 + M0 自检 + 时间轴宿主
│  ├─ logo-badge/          # 左上 logo（纯 CSS）
│  ├─ scale-bar/           # 左下比例尺
│  ├─ timeline/            # 底部全宽时间轴（hour/day/month/static，由图层时间能力驱动）
│  ├─ layer-rail/          # 右侧分组符号竖条
│  ├─ layer-drawer/        # 右滑图层抽屉
│  └─ colorbar/            # 顶部自动色带
├─ services/
│  ├─ api.js               # 后端客户端（鉴权 / 目录 / 边界 / 瓦片）
│  ├─ catalog.js           # 目录归一 + xyz 能力标注 + 二次过滤
│  ├─ tiles.js             # 瓦片调度器（并发队列 + 文件缓存 LRU）
│  ├─ palettes.js          # 色带表（与后端 _PALETTES 同源）
│  ├─ geo/
│  │  ├─ gcj02.js          # GCJ-02 ↔ WGS-84
│  │  └─ mercator.js       # 投影 + 米/像素 + 视口瓦片集合
│  └─ (deprecated) store/index.js  # 轻量 pub/sub（已并入组件 props，后续移除）
└─ store/index.js          # 轻量 pub/sub（M2 未启用，M3 用作事件总线预留）
```

## 下一步（M3+）

- 接 COG 概述金字塔（`supplemental_overviews` / range request），释放更多 time-series 图层进 rail
- 天气层（GeoJSON wind/precip particles）渲染：M3 weather tiles 接入
- 点取值（M4）：点击地图 → 瓦片在 WGS-84 坐标系反查最近像素 → 调 `/overlay-value` 拉精确值
- 手势期间 canvas 连续同步（M3 优化）
- JS → TS 迁移（M2 评审）
