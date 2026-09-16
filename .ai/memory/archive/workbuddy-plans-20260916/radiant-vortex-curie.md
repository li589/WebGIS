# 计划：反馈中心前端页面移动端 / 小屏适配

## 1. 目标与范围
让 `Code/infra/gateway/maintenance/html/` 下的全部静态页在 **超小屏(≤480)、手机(≤640)、平板(≤1024)** 三档良好显示：无横向滚动、可读、可点、不破版。

**纳入范围（目录全覆盖）：**
- `feedback/index.html` + `assets/feedback.css`（用户反馈页，主战场）
- `feedback/console.html` + `assets/console.css`（工程师处理台，次战场）
- `maintenance.html` / `50x.html` / `413.html`（网关维护/错误页，已基本可用，仅轻量打磨）

**原则：**
- 纯 CSS + 极少量 HTML 调整；JS 交互逻辑**基本不动**（点击/键盘/拖拽已有兜底，移动端走点击）。
- 不引入新依赖、不改视觉语言（深海军蓝玻璃拟态设计系统保持同源）。
- 这些页面由 nginx 直接 bind-mount 提供，**改完浏览器刷新即生效，无需 `restart --rebuild-frontend`**；不改 `nginx.conf`，故无需 `nginx -s reload`。

## 2. 统一断点体系（feedback.css / console.css 对齐）
- `≤1024px`：主布局（用户页双列→单列）在此折叠，匹配平板竖屏。
- `≤768px`：平板/大手机中间档，收紧内边距、顶栏、面板。
- `≤640px`：手机档（原已有，细化）。
- `≤480px`：超小屏新档（新增），保证 320/360 可用。

## 3. 各文件具体改动

### 3.1 feedback/assets/feedback.css（用户页）
- `body`：`min-height:100vh` → 追加 `min-height:100dvh`（移动端地址栏安全）；顶栏加 `padding-top: env(safe-area-inset-top)` 适配刘海屏。
- 防溢出：`min-width:0` 补到 `.brand`、`.brand-text`、`.col-side` 等弹性文本容器（原 `.col-main`/`.kv-v` 已有）。
- `@media (max-width:1080px)` → 改名为 `(max-width:1024px)`：`.layout` 单列、`.col-side` 静态（其余不变）。
- 新增 `@media (max-width:768px)`：顶栏/面板/布局内边距收紧；`.dropzone` 内边距减小。
- 细化 `@media (max-width:640px)`（在既有规则上追加）：
  - `.form-actions .btn { flex:1 1 auto; justify-content:center }`（提交/清空填满宽度，便于拇指点击）
  - `.segmented { width:100% } .seg-btn{flex:1} .seg-btn span{width:100%;text-align:center}`（严重程度 4 项等宽铺满）
  - `.reports-toolbar`、`.page-footer` 在窄屏下改为列布局
- 新增 `@media (max-width:480px)`：进一步减小顶栏/面板/标签/成功编号/附件卡(2.3rem)/banner/卡片体内边距；`.brand-text small` 字号与字距收敛，避免长中文串溢出。
- 触控目标：在 `≤768px` 档给 `.btn` 加 `min-height:2.5rem`；`.seg-btn span`、`.icon-btn` 适当增高。
- 安全护栏：追加 `img,video{ max-width:100%; height:auto }`；**不**对 `html,body` 设 `overflow-x:hidden`（会破坏 `position:sticky` 顶栏），靠 `min-width:0` 解决溢出。

### 3.2 feedback/assets/console.css（工程师处理台）
- 新增 `@media (max-width:900px)`：`.composer .form-row` 三栏→两栏。
- 细化 `@media (max-width:760px)`（既有）：`.composer .form-row`→单栏（覆盖 900 档）；`.console-toolbar .search { flex:1 1 100% }` 独占一行；`.console-toolbar` 间距收紧。
- 新增 `@media (max-width:640px)`：
  - `.console-layout`、`.panel` 内边距收紧
  - `.console-toolbar .filter { flex:1 1 100% }`；`.toolbar-btns { width:100% }` 内按钮 `flex:1`
  - `.env-grid { grid-template-columns:1fr }`（手机强制单列，便于阅读键值）
  - `.auth-bar .auth-actions { flex-direction:column; align-items:stretch }`，`.token-input{ width:100%; max-width:none }`，按钮/链接 `width:100%`
  - `.composer-actions .btn { flex:1 }`；`.pending-list li { flex-wrap:wrap }`
- 新增 `@media (max-width:480px)`：进一步收紧间距/字号；`.console-card-head` 在极窄屏下允许换行堆叠。
- 触控目标：移动档 `.btn { min-height:2.5rem }`；顶栏 `padding-top: env(safe-area-inset-top)`。

### 3.3 feedback/index.html & console.html（极少量）
- 仅当需要时：`<input type=file>` 的 `accept` 追加 `image/*`，让手机相册/拍照选择器更易出现（提升移动端附件体验）。非必须，按需。
- 其余结构不动（点击/键盘交互、aria 属性已完备）。

### 3.4 maintenance.html / 50x.html / 413.html（轻量打磨）
- `min-height:100vh` → `100dvh`；`main` 内边距加 `env(safe-area-inset-*)`。
- `≤480px` 将 `main` 的 `padding:2rem` 收到 `1rem`，避免超小屏内容贴边；`.card` 宽度已是 `min(34rem,100%)` 无需改。
- 错误页无交互，确认居中无溢出即可。

## 4. JS 层面
- **默认不改逻辑**。现有 `dropzone` 点击→`file input`、卡片展开点击/键盘、剪贴板粘贴按钮均有移动端兜底。
- 不在本次范围内做移动端剪贴板图片读取增强（属功能扩展，非显示适配）。

## 5. 验证（实现后执行）
1. **静态审计**：grep 三个 CSS 文件中残留的定宽 `width:` / 固定 `px` 容器，确认无 >100vw 风险元素；确认所有弹性文本容器有 `min-width:0`。
2. **响应式实机/DevTools 截图**：经网关 `http://localhost:5175/feedback/` 与 `/feedback/console.html`，在 **320 / 375 / 768 / 1024** 四档视口截图，逐项核对：
   - 无横向滚动条；顶栏不溢出；表单可填、选项卡可切、dropzone 可点选附件；
   - 成功面板按钮填满；严重程度分段铺满；工程师端工具条/编辑器/认证条在手机上正常堆叠；
   - 错误页/维护页居中无贴边。
3. 用浏览器或 `agent-browser` 走查关键按钮（提交、清空、复制、导出、刷新、导入、展开卡片、保存令牌）在手机视口下可点且功能正常。
4. 不改 `nginx.conf`，故无需 reload；刷新浏览器即可见效果。

## 6. 交付与提交
- 改动仅限上述 CSS/HTML（静态资源），属本地文件，浏览器刷新即生效。
- 实现完成后按既有 SOP 提交（提交信息如 `style(feedback): 反馈中心页面移动端/小屏响应式适配`）。
- 不带入测试数据；维护页/错误页无新增依赖。

## 7. 风险与注意
- 不破坏既有桌面视觉：所有新增样式均包在 `max-width` 媒体查询内，桌面（>1024）显示不变。
- 勿对 `body` 设 `overflow-x:hidden`（会废掉 sticky 顶栏）；溢出靠 `min-width:0` 解决。
- 平板档(≤1024)用户页侧栏会沉到表单下方——这是有意为之（移动优先），桌面双列布局不受影响。
