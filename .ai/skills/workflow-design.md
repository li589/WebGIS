# 技能：工作流设计与定时器规范

> 场景：新增/修改工作流种子、画布模板、`_meta` 分类标签、工作流定时器（cron/interval/event），或审查 AI 生成的工作流方案时。
> 适用：后端 seeds、定义服务、定时器服务、前端定时器面板。

## 1. 必读真源（按序）

1. **种子命名 / 分类 / 标记**：`Docs/03-规范协议/workflow_seed_conventions.md`（含 tag 词表、`workflow_seeds/archive/` 归档与孤儿清理约定）
2. **调度与取消主链审计**：`Docs/05-专题研究/其它专题/workflow_scheduling_audit_report.md`（含定时器域）
3. **后端架构（含 `/workflow-timers`）**：`Docs/02-架构设计/后端架构设计.md`
4. **硬约定**：`.ai/rules/project-conventions.md`（`workflow-runs` 主链、Celery 英文 title、改 X 则跑 Y）

算法包侧图执行扩展另见 `Code/algorithms/providers/docs/workflow_extension_design.md`（provider DAG，不是平台定时器）。

## 2. 设计硬规则（检查清单）

### 2.1 标识与 `_meta`

- [ ] `workflow_id` / 文件名：`snake_case`，`^[a-zA-Z0-9][a-zA-Z0-9_\-]*$`
- [ ] `_meta.kind`：`system` | `user`
- [ ] `_meta.engine`：`python_provider` | `weather` | `gee` | `common`
- [ ] `_meta.category`（单选主分类）：`inversion` | `weather` | `data_access` | `analysis` | `demo`
- [ ] `_meta.tags`（多选标记）：只用规范词汇表；新 tag 先改 `workflow_seed_conventions.md`
- [ ] system 种子：`readonly: true`，`is_template: true`
- [ ] 推荐 `linked_layer_id` 指向图层 catalog

**「标记」= `tags` + 标志位（`is_template` / `readonly` / `linked_layer_id`），不要发明 `markers` 字段。**

### 2.2 三套分类勿混用

| 体系 | 用途 |
|------|------|
| 工作流 `_meta.category/tags` | 模板库 |
| 节点调色板中文 category | 画布节点分组 |
| 图层 catalog category/tags | 地图图层 |

### 2.3 Celery 元数据

- [ ] 任何 `WorkflowResultReference.title` / artifact title 为 **纯英文 US-ASCII**
- [ ] 中文名只放 `_meta.name` / UI

### 2.4 定时器

- [ ] 触发类型：`cron` | `interval`（≥60s）| `event`
- [ ] Cron **墙钟 = Asia/Shanghai（北京时间）**；存储 `next_fire_at` 为 UTC ISO
- [ ] DOM 与 DOW 同时受限时为 **AND**（非 Vixie OR）
- [ ] 改 `trigger_type` 必须同时提交匹配的 `trigger_config`
- [ ] `payload_overrides` 放可运行参数；图定义由后端按 engine 自动注入，勿提交空壳 analysis
- [ ] Beat 每分钟 `tick_workflow_timers` → `workflow_queue_standard`；需 `launch.py start beat` + worker
- [ ] 僵死 `CLAIMED:` 由 tick 开头按 TTL（默认 300s）回收，勿手写永久 CLAIMED 哨兵
- [ ] **定时器 UI** 为编辑器主区**主从面板**（列表 | 详情），不是 LiteGraph 节点；侧栏边缘可拖拽调宽
- [ ] 自动触发的 run **不会**即时推入状态面板；依赖 Dashboard `restoreActiveWorkflows` / 手动刷新；手动「立即运行」会 `registerExternalWorkflowRun`
- [ ] 提交失败仍推进 schedule，错误写入 `last_error`

实现：`Code/backend/app/services/workflow_timer_service.py`、`workflow_timer_router.py`、`app/tasks/workflow_timer_tasks.py`；前端 `WorkflowTimerPanel.vue`、`stores/workflow-timers.ts`。

## 3. 新增算法节点接入清单

> 场景：给画布接入一个新的算法模块节点（python_provider 引擎）。
> 全程**只需 3 处**（①②③）；**不需**动 bridge / dispatch / runner / provider_registry —— 模块经 pkgutil 自动扫描注册，执行链按 `node_type` 自动路由。

### ① 模块实现（算法包）

`Code/algorithms/providers/Python/modules/<模块名>.py`：

- 继承 `BaseModule`，声明 `input_ports` / `output_ports`（`PortSpec`）、`default_params`；
- 用 `@register_module_decorator(name="<模块名>", ...)` 注册 —— `modules/registry.py` 的 pkgutil 扫描自动发现，**零手工登记**；
- **声明阶段分类**（推荐）：`template_overrides={"phase": "<download|preprocess|inversion|output|processing>"}`，前端阶段分组读此声明优先于名称匹配；不声明则回退 substring 匹配；
- 上游产物入口统一收 `data` 输入端口（`kind="data"`，可选），实现内做 str/dict/ArtifactRef 的目录归一，避免单一化输入。

```python
@register_module_decorator(
    name="my_module",
    template_overrides={"phase": "inversion"},
)
class MyModule(BaseModule):
    name = "my_module"
    input_ports = [PortSpec(name="data", kind="data", required=False), ...]
    output_ports = [...]
    default_params: dict[str, object] = {...}
    def execute(self, inputs, params, ctx): ...
```

### ② 画布模板（后端注册表，手写）

`Code/backend/app/services/node_template_registry.py` 追加条目：

- `type`（画布契约，`download/xxx` 等前缀分组）、`engine: "common"`、中文 `category`（画布调色板分组）、`title`/`description`；
- `inputs`/`outputs` 用 `_port(...)`，`params` 用 `_param(...)`；
- **模板端口必须与模块 PortSpec 一致**（双向对齐，防 `unknown input port` 编译错）；
- 新模板自动进入 `test_node_template_compile_coverage.py` 编译覆盖，未声明必测引擎会被暴露。

### ③ 可选：种子与图层目录

- 演示工作流种子：`Code/backend/workflow_seeds/system/<workflow_id>.json`（遵循本技能 §2.1 的 `_meta`/命名规则；`_meta.engine: "python_provider"`）；
- 产物若要成为地图图层：`catalog_seeds/layer_descriptors.json` 加图层条目（命名规范见 `Docs/03-规范协议/layer-naming.md`）。

### 验证

```text
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_node_template_compile_coverage.py Test/backend/test_workflow_seed_sync.py -q -p no:cacheprovider --basetemp="Test/.pytest-be"
```

含 `phase` 声明 / 阶段分类改动时加跑：`Test/backend/test_module_phase_classification.py`。

### 已知缺口（backlog，勿在本清单内解决）

- **N7 portal preset 归一**：provider 侧 `_DEFAULT_OPEN_DATA_PRESETS` 与后端 `data_cache_service.DEFAULT_OPEN_DATA_PRESETS` 仍是双登记（provider 侧仅为离线安全网），待归一。
- **N9 模板自动派生**：② 的手写模板长期应从模块 spec 自动派生（`workflow/template_inference.py` / `template_deriver.py` 起点），消除双登记漂移面。

## 4. 验证命令

```text
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env\Python312\python.exe -m pytest Test/backend/test_workflow_timer_service.py Test/backend/test_celery_tasks.py -q
```

前端定时器相关：

```text
cd Code/frontend && npm run test -- workflow-timer && npm run lint && npm run build
```

工作流主链（改运行/取消等时）：见 `project-conventions.md`「工作流运行」行。

## 5. 反模式

- 用图层或节点 palette 的 category 去填 `_meta.category`
- Cron 按 UTC 写「每天 8 点」却期望北京时间 08:00
- 定时器只设 `workflow_id`、空 overrides，且指望已删除的 `extra.default_command` alone（现已按 engine 注入定义，但仍应在 overrides 里给齐业务参数）
- 中文写入 Celery result title
- 把定时器做成 LiteGraph 节点（当前是外部调度记录，挂在编辑器「定时器」页）
- 节点模板（`node_template_registry.py`）声明的端口与模块 `PortSpec` 不一致（双登记漂移 → `unknown input port` 编译错；fy_tb_online_read 教训）
- 只为单一种子/单一数据源硬编码模块输入（应走 `data` 端口 + datasource 回退链，见接入清单 ①）
