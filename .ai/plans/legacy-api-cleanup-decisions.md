---
name: Legacy API cleanup decisions
overview: 针对旧 /tiles、配置≠运行时、SSE 名实不符三块遗留账，先锁定几条产品/技术原则；下面给出需要判断的问题、建议默认值与原因，作为后续彻底清理的决策骨架。
todos: []
isProject: false
---

# 遗留账清理：决策问题与建议

彻底收拾这三块时，真正卡进度的不是改代码量，而是下面几条原则拍错会反复返工。下列每题给出**建议默认**与原因；你确认（或改选）后，再按锁定原则出实施清单。

```mermaid
flowchart TB
  subgraph tiles [Tiles surface]
    T1[唯一瓦片面]
    T2[兼容窗口策略]
    T3[缓存管理归宿]
  end
  subgraph cfg [Config truth]
    C1[单一密钥真源]
    C2[capability 只写真有]
    C3[登记层角色]
  end
  subgraph events [Events transport]
    E1[本轮是否上推送]
    E2[轮询限流语义]
  end
  T1 --> T2 --> T3
  C1 --> C2 --> C3
  E1 --> E2
```

---

## A. 旧 `/tiles`（含 `/weather/tiles`）

### A1. 对外契约目标是什么？

| 选项 | 含义 |
|------|------|
| **唯一入口** | 只保留 `/unified-tiles/{layer_id}/...`；旧口删除或立刻 410 |
| 双轨过渡 | 旧口保留 N 个版本，打 `Deprecated` + Sunset 头 |
| 长期兼容 | 旧口永久转发到统一实现 |

**建议：唯一入口（本仓库前端已不打旧像素口）+ 短过渡可选。**  
原因：当前前端热路径已走 `/unified-tiles`；再养三条口会继续造成状态码/响应头/ zoom 校验分裂。若确认没有外部脚本依赖 `/tiles`，直接下线比重写一遍“永远转发”更省。

### A2. `/tiles/providers`、`/tiles/cache/*` 放哪？

旧模块里**真正没有统一对等物**的是 cache 管理与 provider 列表。

| 选项 | 含义 |
|------|------|
| **并入统一管理面** | 例如 `/runtime/tiles/cache` 或 `/unified-tiles/admin/...`，再删旧前缀 |
| 随旧口一起删 | 缓存只靠 TTL/进程内自然失效，不做人工 clear |
| 单独留下旧管理口 | 像素口删了，管理口挂在 `/tiles` 上——最容易再长成黑洞 |

**建议：并入 runtime/统一管理面，或明确删掉人工 clear。**  
原因：“像素走 unified、管理仍走 /tiles”会让“已经统一了”变成假话。

### A3. 错误语义以谁为准？

天气路径上已出现 **400 vs 404**、zoom 规则不一致。

**建议：以统一口为准写一份错误表（未知 layer → 404；非法 z/x/y → 400；上游失败 → 502/503），旧口若短期保留则必须转发到同一实现，禁止各写各的。**  
原因：兼容期最怕的是“看起来还通，错误码却两套”。

### A4. OpenAPI / 前端 `routePrefix: '/tiles'` / Vite 代理何时砍？

**建议：与删口同一 PR 或紧随其后的契约再生 PR：再生 OpenAPI、删死 `routePrefix` 误导字段、Vite 去掉 `/tiles`（保留 `/unified-tiles`）。**  
原因：代码删了、类型和代理还在，债务会从 runtime 搬到契约层。

---

## B. 「配置里有」≠「运行时真走」

### B1. 对外集成故事要多宽？

| 选项 | 含义 |
|------|------|
| **诚实窄面** | 只声明：天气=Open-Meteo；底图=代理后的若干 CDN；GEE=独立桥 |
| 雄心宽面 | 继续展示百度/高德地理编码、GEE 天气等“未来能力” |

**建议：诚实窄面。**  
原因：宽面是当前混沌的根源——UI/registry 看起来可切换，HTTP 从未切换。彻底清理的第一原则应是 **capability = 有可调用实现**。

### B2. 密钥 / 数据源的“单一真源”选谁？

现状是三套：`Settings`(env)、`ApiKeysRepository`(DB/UI)、`ApiConfigManager`(registry)。

| 选项 | 含义 |
|------|------|
| **Settings/DB 为运行真源**，registry 最多做只读投影 | 瓦片/天气读 `get_effective_*`；改 UI 必须生效 |
| registry 为编排中枢，Settings 只做引导 | 所有 fetch 读 `ApiConfigManager` |
| 砍掉一层 | 删除 registry 或删除 DB，只留 env |

**建议：运行真源 = env 冷启动 + DB 覆盖（`get_effective_api_key`），所有出网读取只走这一条；`ApiConfigManager` 降级为“集成状态投影”或直接内联进 `config_service`，禁止第二套 key 字段。**  
原因：瓦片已经在读 `settings.*`，UI 却写 DB——这是最高优先级的名实不符；先统一消费点，再决定是否保留独立 registry 类。

### B3. 未接线的能力怎么处理？

包括：高德 Key、`BACKEND_OPEN_METEO_URL`、百度/高德 REST、GEE-as-weather、`tile_proxy_enabled` TTL、坏掉的 `POST /runtime/api-config`、`secretRef` 虚构名、Bing api-key 标记等。

| 策略 | 含义 |
|------|------|
| **接线或删除（二选一，禁止半挂）** | 每个配置项必须：有实现 / 或从 UI·env·OpenAPI 消失 |
| 标 `planned` 灰色展示 | 允许展示但不可配置密钥 |

**建议：本轮对“无调用方”一律删除或标 planned 且不可配密钥；Open-Meteo URL、tile proxy enable/TTL、Tianditu/Baidu key 必须接线或从设置页拿掉。修掉不存在的 `update_config`（删除该写接口或真正实现）。**  
原因：半挂配置比没有配置更害人（绿勾骗人）。

### B4. `/runtime/api-config` 是否允许返回明文 key？

**建议：永不返回明文；只返回 `configured: bool` / `source: env|db|none`。**  
原因：它既不是运行真源，又有泄露面。

---

## C. SSE 名 vs 轮询实

### C1. 本轮传输目标是什么？

| 选项 | 含义 |
|------|------|
| **诚实轮询** | 保持 JSON poll；改名、改限额、改文案；文档去掉“已有 WebSocket/SSE” |
| 本轮上真 SSE | `text/event-stream` + 前端 `EventSource`，轮询降为 fallback |
| 本轮上 WebSocket | 改动面更大 |

**建议：本轮诚实轮询，不上推送。**  
原因：债务在**名实与限流杀轮询**；上 SSE 是新产品能力，会把清理 scope 炸开。规范文档已写“第一版轮询，以后可升”——对齐现状即可。

### C2. 限流应按什么模型定？

当前约 **10 次 / 5 分钟**，与前端 **1.2s/2.6s** 轮询严重冲突。

**建议：按“每 IP 每分钟请求数”重定（例如 60–120/min 量级，或按活跃 run 数加权），命名改为 `EventPollRateLimiter`；429 文案写 poll/requests，禁止 SSE connections。**  
若产品上要防刷，也应在测过前端稳态 QPS 后再定数字，而不是沿用“连接数”遗产。

### C3. 架构文档怎么写现状 vs 路线图？

**建议：现状图只画 REST + 轮询；SSE/WebSocket 单独放「路线图」小节。**  
原因：图上画着 WebSocket，比代码注释更误导新人。

---

## 建议的默认决策包（可整包采纳）

1. **瓦片：** 只保留 `/unified-tiles`；旧像素口删除或短过渡 410；cache 管理并入 runtime 或删除；契约/代理同步砍。  
2. **配置：** 诚实窄面；出网只认 effective key/URL；registry 降为投影或合并；无实现的 capability/ env/ 写接口删除或标 planned。  
3. **事件：** 本轮不上 SSE；限流与命名改为 poll；修 429 文案与额度；文档去 WebSocket 现状表述。

---

## 需要你回复的判断（简写）

请按题号回复选项（可写“全采纳建议默认”）：

- **A1** 唯一入口 / 双轨过渡 / 长期兼容  
- **A2** 管理面并入 / 删 clear / 旧管理口留下  
- **B1** 诚实窄面 / 雄心宽面  
- **B2** Settings+DB 真源 / registry 中枢 / 砍一层  
- **B3** 接线或删除 / 允许 planned 灰显  
- **C1** 诚实轮询 / 本轮真 SSE / 本轮 WebSocket  

你确认后，再输出按文件拆分的实施计划（含顺序：先修会打脸生产的限流与 key 真源，再删旧口与瘦配置面）。
