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

面向用户的 bug / 问题反馈页，**纯静态、非 Vue、不依赖后端** —— 后端宕机或维护期（恰恰是最需要报 bug 的时候）仍可访问与提交。

## 目录结构

```text
html/feedback/
  index.html               # 页面入口（nginx location ^~ /feedback/ 直出）
  assets/
    feedback.css           # 样式（深海军蓝玻璃拟态，与 maintenance.html 同源）
    feedback.js            # 逻辑（IndexedDB / 附件校验 / 限流 / 复制粘贴）
  data/
    announcements.json     # 运维维护：公告 + 维护信息 + 各反馈的处理进展
```

## 数据流

| 环节 | 机制 |
|------|------|
| 用户提交 | 表单数据（含附件）存**浏览器本地 IndexedDB**（localStorage 降级），生成编号 `CGDA-BUG-YYYYMMDD-XXXX` |
| 交给开发者 | 「复制 Markdown」（纯文本摘要）或「导出 JSON」（完整报告 + base64 附件），由用户经 IM/邮件转发 |
| 开发者追问 / 修复进展 / 受理人 | 运维编辑 `data/announcements.json` 的 `responses`（按 `reportId` 匹配），页面每 60 秒拉取并合并到「我的反馈」时间线 |
| 系统维护信息 | `announcements.json` 的 `maintenance.active=true` 时页面顶部显示维护横幅 |
| 联系方式 | `announcements.json` 的 `maintainer` 字段，展示在侧栏「支持渠道」 |
| 后端健康 | 页面轮询 `/health`（30 秒），仅作状态提示，不影响反馈功能 |

## 运维操作：发布公告 / 回复反馈

直接编辑 `html/feedback/data/announcements.json`（bind mount 只读进容器，宿主机可改，页面下次轮询生效，无需 reload nginx）：

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

> 注意：纯静态页面的限流与身份认证均在**客户端**，防的是误操作与低强度滥用；服务端统一限流仍由后端 API 体系承担（本页不产生任何服务端写入）。

## 与 Vite 开发剖面

日常 `launch.py start` / `restart` **默认走 Gateway**。本地 HMR：`launch.py start --vite`（会停 Gateway）。若在 Vite 下不想看到红屏源码叠加层，可设 `VITE_HIDE_ERROR_OVERLAY=1`。
