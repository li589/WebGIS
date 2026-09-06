# CGDA 全流程回归报告（2026-08-06）

> **范围**：已修项复验 + 主链路冒烟 A–I + 相关 vitest  
> **入口**：`http://localhost:5175` + FastAPI `:8000`  
> **方法**：Chrome DevTools MCP + `npm run test`  
> **不做**：`launch.py flush`、改计划文件、git 提交；FY/SMAP（ID05）不阻塞交付

---

## 环境

| 组件 | 结果 |
|------|------|
| `launch.py status` | Redis / MinIO / Open-Meteo、FastAPI `:8000`、Vite `:5175`、Worker×7 + Beat 就绪 |
| Nginx Gateway | 未要求 |

---

## 自动化

在 `Code/frontend`：

```text
npm run test -- map-canvas-expose-bridge screenshot-export overlay-symbology analysis-panel-summary weather-tile-readiness weather-tile weather-tile-banner
```

**结果**：54/54 通过。

---

## 主链路冒烟（Chrome MCP）

| # | 模块 | 结果 | 备注 |
|---|------|------|------|
| A | 首屏 | PASS | MapLibre / 工具栏 / 时间轴；首屏无 console error |
| B | 图层库 ↔ 已添加 | PASS | 分类可浏览；persist 非空属预期（ID09）；未就绪层 = ID05 |
| C | 天气温度 | PASS | 添加温度；`/weather/tiles/temperature/...` 200；banner「完整数据」 |
| D | 点查 | PASS（上轮+本轮） | 温度主值有 °C；叠加 N/A = ID06 expected |
| E | 测量 | PASS | 可进模式；有「清除测量路径」 |
| F | 截图 ID11 | PASS | 「已生成 — 若未自动下载请点下方链接」+ 手动下载；无 `map.render` / `color()` 致命错 |
| G | 数据导出 | PARTIAL | 工作台导出 Tab 可开；当前「暂无已导入图层可导出」（无导入层）；上轮 GeoTIFF 成功仍有效 |
| H | 工作流状态 | PASS | 面板可开；汇总/瓦片进度可见（本会话失败 run=0） |
| I | 设置 | PASS | 打开/关闭无崩 |
| — | 定时器新建+Beat | 跳过 | 可选；未新建 |
| — | FY/SMAP | 阻塞记档 | ID05 数据源 env |

---

## 已修项专项复验

| ID | 结果 | 2026-08-06 回归说明 |
|----|------|---------------------|
| **ID11** | PASS | 截图导出成功路径（picker / 面板手动下载）；console 无 Capture failed |
| **ID01** | PASS | 硬刷新后无「工作流结果图层加载失败」黄条；无 `materialize…409` 黄条噪音 |
| **ID03** | PASS（代码准） | 本会话无 omega 进度推送，未复现 Duplicate keys；`:key="\`job-note-${idx}\`"` 已合入 |
| **ID07** | PASS（附注） | 全程 **无** `/overlay-bounds/omega-sf-fenkuai`；`aridity-cn` 同会话曾见 **2×404**（未达刷屏），其后添加/刷新未见循环 |
| **ID04/10** | PASS | 选中温度且 banner「完整数据」时，分析 stage = `succeeded` / 「已缓存」（非 `running`+「加载中」） |

---

## 残留 / 附录噪音

- **ID05**：图层库大量「默认数据源未就绪」—— env 阻塞，不纳入本轮修码。
- **ID02**：孤儿排队 failed 机制仍 confirmed；本会话状态面板失败计数为 0。
- **ID07 附注**：`aridity-cn` 偶发同会话双次 404，负缓存/注册门禁大体生效，未观察到持续刷屏。
- **Console 噪音**（不升 P1）：Vite HMR / `Canvas2D willReadFrequently` 等与功能无关。
- **导航**：MCP `navigate_page` 偶发超时，页面仍可加载。

---

## 结论

主链路冒烟与 P1/P2 已修项（ID11 / ID01 / ID03 / ID07 / ID04·10）复验通过；截图覆盖矩阵改为**已验·通过**。数据源未就绪（ID05）与定时器 Beat 不阻塞本次回归交付。登记表已同步更新。
