# 前台维护模式 + 问题反馈中心（Gateway）

本目录同时存放：

| 路径 | 作用 |
|------|------|
| `on` | 维护开关（空文件；**不入库**） |
| `html/maintenance.html` | 升级/修 bug 时展示的纯 HTML 页（不依赖 Vue） |
| `html/50x.html` | 上游 FastAPI 502/503/504 及前台 5xx 错误页 |
| `html/413.html` | 上传体超限错误页（浏览器表单直发场景）；API XHR 上传超限返回 JSON 413（nginx `@json413`，保持前端 `{detail}` 错误契约） |
| `html/feedback/` | **问题反馈中心**（非 Vue 纯静态页，详见下文） |

存在 `on` 时，Nginx 对 **SPA / 静态资源** 返回 `503` 并展示 `html/maintenance.html`。

**API 反代不中断**（`/workflow-runs`、`/auth`、`/weather` 等），便于升级或修 bug 时让后台任务跑完。

## 启用

```powershell
New-Item -ItemType File -Force Code\infra\gateway\maintenance\on | Out-Null
docker exec cgda-gateway-nginx nginx -s reload
```

## 关闭

```powershell
Remove-Item -Force Code\infra\gateway\maintenance\on
docker exec cgda-gateway-nginx nginx -s reload
```

## 预览

不创建 `on` 也可直接打开：`http://localhost:5175/maintenance.html`（gateway 剖面）。

---

# 问题反馈中心（/feedback/）

访问入口：**`http://localhost:5175/feedback/`**（gateway 剖面）。

## 定位

面向用户的 bug / 问题反馈页，**纯静态、非 Vue**。数据面**双轨**：

- **在线轨**（后端在线时）：反馈一键上传服务端（`/feedback/api/*` → `BACKEND_DATA_ROOT/_runtime/feedback/`），工程师处理台在线查看与回复
- **离线轨**（后端宕机或维护期——恰恰是最需要报 bug 的时候）：反馈存本机浏览器，导出/复制交给开发者，功能完全不受影响

页面本身不依赖后端即可访问与提交；在线轨按健康状态自动启用。

## 目录结构

```text
html/feedback/
  index.html               # 用户端入口（nginx location ^~ /feedback/ 直出）
  console.html             # 工程师端入口（反馈处理台，/feedback/console.html）
  assets/
    feedback.css           # 共享样式（深海军蓝玻璃拟态，与 maintenance.html 同源）
    console.css            # 工程师端补充样式
    feedback.js            # 用户端逻辑（IndexedDB / 附件校验 / 限流 / 复制粘贴）
    console.js             # 工程师端逻辑（导入解析 / 附件预览 / 回复编排）
  data/
    announcements.json     # 运维维护：公告 + 维护信息 + 各反馈的处理进展
```

## 工程师端：反馈处理台（/feedback/console.html）

处理台支持**两种数据源**（双轨）：

**在线轨（后端在线时，推荐）**——打开页面自动检测认证并拉取服务端反馈：
1. 用户在 `/feedback/` 提交后点「上传到服务器」，反馈直接落盘后端（无需转发文件）
2. 工程师打开处理台，admin 会话（同域 cookie 自动携带）或 Admin API Token 认证
3. 服务端反馈自动列出；点击展开在线查看（**不落盘本机**）：描述/步骤/环境/提交人、附件（图片预览/文本预览/下载）
4. 「发布处理进展」直接写入服务器（状态/受理人/时间线/回复），用户端 60 秒内可见

**离线轨（后端宕机/维护期兜底）**——本地导入：
1. 用户在 `/feedback/` 点「导出完整 JSON」，把 `CGDA-BUG-*.json` 经 IM / 邮件发给工程师
2. 工程师拖入 / 选择 / 粘贴 JSON 导入（本机 IndexedDB 留存，可搜索过滤）
3. 详情查看同上；处理与回复编排后「复制 responses JSON」粘贴到 `data/announcements.json` 发布

处理台同时拉取 `announcements.json`，本地导入的反馈可显示已发布状态与历史回复。

## 服务端 API（在线轨，/feedback/api/*）

后端新增 `app/api/routers/feedback_router.py`（FastAPI）+ `app/services/feedback_store.py`（文件系统存储）；
nginx 在 `location ^~ /feedback/` 内嵌套 `location ^~ /feedback/api/` 反代到后端
（维护开关不影响该入口；vite 剖面经 `vite.config.ts` 的 `/feedback/api` proxy）。

| 端点 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/feedback/api/reports` | POST | 匿名 + 限流（默认 5 次/分钟/IP，`BACKEND_FEEDBACK_UPLOAD_RATE_LIMIT_PER_MINUTE`） | multipart 上传导出 JSON；返回 `{reportId, token}` |
| `/feedback/api/reports/{id}/response?token=` | GET | 上传时下发的 token（防编号枚举） | 用户端查询自己反馈的进展 |
| `/feedback/api/session` | GET | admin | 工程师端认证探测 |
| `/feedback/api/reports` | GET | admin | 服务端反馈摘要列表 |
| `/feedback/api/reports/{id}` | GET | admin | 完整报告 + 附件清单 + 进展 |
| `/feedback/api/reports/{id}/attachments/{name}` | GET | admin | 附件下载 |
| `/feedback/api/reports/{id}/response` | PUT | admin | 发布/更新处理进展 |
| `/feedback/api/reports/{id}` | DELETE | admin | 删除一条反馈（含附件与进展，不可恢复） |

**鉴权**：admin 会话 cookie（工程师登录主应用后同域自动携带）/ admin 用户 API Token / `backend_auth` 服务密钥（`X-API-Key`），复用 `credential_resolver`；开发旁路（dev_bypass）仅 standard 角色，天然被拒。

**存储位置**：`settings.feedback_dir`（默认 `<BACKEND_DATA_ROOT>/_runtime/feedback/`，`BACKEND_FEEDBACK_DIR` 可覆盖）。每条反馈一个目录：`report.json`（净化后的导出原文）+ `meta.json`（token/上传时间/IP）+ `attachments/`（base64 解包落盘）+ `response.json`（处理进展）。目录名 = 白名单正则校验过的 reportId（防路径穿越）；JSON 原子写；同编号重复上传 409。

**认证模式说明**：浏览器内（cookie 会话）图片/附件可直接经 API 预览下载；使用 Token 模式时处理台内部 fetch 转 blob，功能一致。

## 数据流

| 环节 | 机制 |
|------|------|
| 用户提交 | 表单数据（含附件）存**浏览器本地 IndexedDB**（localStorage 降级），生成编号 `CGDA-BUG-YYYYMMDD-XXXX` |
| 交给开发者 | **在线轨**：后端在线时一键「上传到服务器」（工程师自动可见）／**离线轨**：「复制 Markdown」或「导出 JSON」经 IM/邮件转发 |
| 开发者追问 / 修复进展 / 受理人 | **在线轨**：处理台直接发布（`PUT response`，服务端权威存储）／**离线轨**：`data/announcements.json` 的 `responses`（按 `reportId` 匹配）；两轨页面每 60 秒拉取合并（服务端优先） |
| **AI 消费与规范化修复** | 服务端反馈落盘 `_runtime/feedback/` 后，AI 编码助手经 `Tools/feedback_triage.py` 扫描/读取 → 分析 → 修复 → 提交 → 处理台或 `PUT response` 发布进展闭环（见下节） |
| 系统维护信息 | `announcements.json` 的 `maintenance.active=true` 时页面顶部显示维护横幅 |
| 联系方式 | `announcements.json` 的 `maintainer` 字段，展示在侧栏「支持渠道」 |
| 后端健康 | 页面轮询 `/health`（30 秒），仅作状态提示；后端不可用时自动降级离线轨，反馈功能不受影响 |

## AI 消费环（反馈 → 规范化修复）

服务端反馈是**权威存储**，AI 编码助手可直接读取并进入问题分析与规范化修复：

1. **扫描**：`Env\Python312\python.exe Tools/feedback_triage.py --open`（未受理/未修复待办）、`--count`（统计）、`--show <id>`（单条完整内容：描述/复现/期望/实际/环境/提交人/进展）。脚本只读、纯标准库，路径自动解析（`BACKEND_FEEDBACK_DIR` → `BACKEND_DATA_ROOT/_runtime/feedback` → 项目现行 DATA_ROOT）。
2. **修复**：遵守 `.ai/rules/feedback-triage.md`（SOP）与 `.ai/rules/project-conventions.md`（硬约定）；被指派处理反馈时加载 `.ai/prompts/feedback-fix.md`。
3. **闭环**：修复提交（`fix(<scope>): 修复反馈 CGDA-BUG-xxxx：…`）后，在处理台 `/feedback/console.html` 或经 `PUT /feedback/api/reports/{id}/response` 发布进展（状态/受理人/时间线/回复），用户端 60 秒内可见，`--open` 待办随之消失。

## 运维操作：发布公告 / 回复反馈

直接编辑 `html/feedback/data/announcements.json`（bind mount 只读进容器，宿主机可改，页面下次轮询生效，无需 reload nginx）；也可以在工程师端处理台（`/feedback/console.html`）里编排好后复制 JSON 粘贴进来：

- 新公告 → `announcements` 数组追加条目（`type`: info/fix/notice/security）
- 回复某条反馈 → `responses` 数组按 `reportId`（用户复制/导出中可见）追加：
  - `status`: `received` 已受理 / `in_progress` 处理中 / `needs_info` 待补充 / `fixed` 已修复 / `closed` 已关闭 / `rejected` 不予处理
  - `timeline`: 处理节点（时间线展示）；`replies`: 追问内容（会展示在用户该条反馈下）
  - `assignee`: 受理人姓名与角色（接收人员信息登记）
- 维护窗口 → `maintenance.active` 置 `true` 并填写标题/说明/时间窗

改完保存即可，格式错误时页面会安全忽略（字段级防御校验）。

## 安全设计

| 威胁 | 防护 |
|------|------|
| XSS / 输入注入 | 所有用户数据经 `textContent` 渲染（绝不经 innerHTML）；输入清洗去控制字符并截断；文本附件预览走 `<pre>` |
| CSP | `/feedback/` 单独下发严格 CSP：`script-src 'self'`（无 unsafe-inline，JS/CSS 外置）、`object-src 'none'`、`frame-ancestors 'none'` |
| 恶意文件 | 扩展名白名单（图片/文本/数据三类）+ 图片魔数校验 + 可执行文件黑名单 + 单文件 10/2/25MB 分级上限 + 最多 10 个 / 总 40MB + 文件名净化（去路径与控制字符） |
| 高频提交 | 提交间隔 ≥15s，10 分钟 ≤5 条、1 小时 ≤20 条、24 小时 ≤60 条（localStorage 计数）；蜜罐字段 + 加载时序检查 |
| 身份 | 本机自动生成匿名设备标识（无需注册）；身份与联系方式可选项式附带 |
| 隐私 | 数据仅存本机；导出/复制动作由用户主动触发 |
| 工程师端导入 | 导入 JSON 字段级净化 + 长度上限（80MB 文本 / 单附件 45MB base64）+ 编号格式校验；附件同样仅 textContent 渲染（HTML/SVG 一律按文本显示，不解析执行） |
| 服务端上传（在线轨） | 上传走独立限流（默认 5 次/分钟/IP，Redis 集中计数）；60MB JSON / 45MB 单附件 / 20 个附件上限；reportId 白名单正则（防目录穿越）；附件文件名净化；同编号重复上传 409；token 查询 `secrets.compare_digest` 防时序侧信道与编号枚举；工程师端 admin 鉴权（dev_bypass 天然被拒） |

> 注意：纯静态页面的本地限流与身份认证在**客户端**，防的是误操作与低强度滥用；在线轨的服务端限流/鉴权/大小校验由后端 API 体系承担（`/feedback/api/*`）。

## 与 Vite 开发剖面

日常 `launch.py start` / `restart` **默认走 Gateway**。本地 HMR：`launch.py start --vite`（会停 Gateway）。若在 Vite 下不想看到红屏源码叠加层，可设 `VITE_HIDE_ERROR_OVERLAY=1`。
