# 图层 ID / 显示名规范

> 稳定目录 `layer_id` **不批量改名**（已绑瓦片 URL、workflow `linked_layer_id`、workspace）。本规范约束新增 id、显示名语义、回退链与导出文件名。

## 标识（必须唯一）

| 字段 | 规则 |
|------|------|
| 目录 `layer_id` / FE `catalogId` | 小写 kebab-case；无空格。前缀：`ref-` / `prod-` / `method-` / `obs-` / `imported-`。气压层**新层**用小写后缀（如 `850hpa`）；既有 `850hPa` 保留。 |
| `dataset_key` | 数据集标识，可与 `layer_id` 不同；同一数据集可多次导入/产出（靠 `instanceId` / `imported-{hex}` / `wf-run-*` 区分） |
| 运行时 `catalogId` | `wf-run-{groupId}-{sm\|vod\|omega}`；`wf-out-{ts}-{rand}`；`imported-{hex}` |
| TOC 行键 | 永远用 `instanceId`（UUID）；同一 `catalogId` 可有多行 |

## 显示名（面向地理工作者，允许重复）

| 类型 | TOC 展示 | 说明 |
|------|----------|------|
| 专属数据 | 专业中文核心词 + 行业缩写，约 ≤16 字 | 例：`植被指数 NDVI`、`SMAP L3 土壤水分`。时间/分辨率/算法细节放 `description`，不进 TOC。 |
| 变量单层 | 短变量/缩写 | `SM` / `VOD` / `ω`；全称用 `PRODUCT_TAG_DESCRIPTIONS`（InfoPanel / tooltip）。 |
| 导入层 | 文件 stem；用户可改 | 仅改显示名，不改物理文件名 / 导出 id |

**禁止**：空泛单独词（「结果/产品/数据」）、程序员腔裸露（`D2`/`SF`）、超长括号时间堆叠。

### 可用性芯片（图层管理器 TOC 底行）

侧栏 `availabilityLabel` 使用短标签；天气瓦片层**不**显示「待运行」。

| 标签 | 含义 |
|------|------|
| 待运行 | 目录层已加入工作区，尚无运行结果 / 导入数据 |
| 可查看 / 等待瓦片 / 加载中 / 完整数据 | 天气引擎层（tile manager）或已有瓦片缓存 |
| 运行中 / 排队中 / 等待重试 | 工作流 job 进行中（job 徽标另显短状态；详情在 tooltip） |
| 完整数据 | 成功结果、导入栅格/矢量、或天气瓦片齐全 |
| 等待结果 | `dataState=real` 但尚无 map/import 载荷 |
| 数据未就绪 / 数据异常 / 已取消 | 就绪阻断或终态失败/取消 |

工作流进度短文案（后端 `transition_builder`）：`已创建` → `编排中` → `运行中`（勿再使用「服务层正在执行真实工作流」等长句）。

### UI 回退链

`ActiveLayer.name` → 持久化显示名 → 目录 `display_name` → **`dataset_key`** → **`layer_id`/`catalogId`** → `未命名图层`。

重命名**只改**显示名，**永不改** `catalogId` / `overlayLayerId` / `instanceId`。运行组 header title 不随成员重命名变化。

## 导出 / 下载文件名（与 UI 解耦）

| 优先级 | 字段 |
|--------|------|
| 1 | `layer_id`（含 `ref-` / `prod-` / `method-` / `obs-` / `imported-`） |
| 2 | `dataset_key` |
| 3 | `source_filename` / 物理 stem |
| 4 | `display_name`（最后手段） |

**不要**用中文显示名作为默认导出文件名。

## 持久化

| 键 | 用途 |
|----|------|
| `geo:layer-display-names:v1` | 用户重命名；**新写入**优先 `instanceId`，导入层另写 `backendLayerId` / `overlayLayerId` |
| `geo:active-layers-workspace:v1` | 工作区快照含 `name` |

详见 [图层持久化说明](../design/图层持久化说明.md)。

## 类别 id

FE `LAYER_CATEGORIES.id` 与 BE `category` 对齐英文：`weather` / `climate` / …；UI 文案用类别的中文 `name`。

## 校验

```powershell
cd Code/frontend
npm run check:catalog   # FE catalogId ⊆ BE seeds，且共有 id 的 display_name 一致
```
