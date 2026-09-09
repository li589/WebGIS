# 2026-09-10

## 事故：本地 .git 目录被误删（用户清理导致），版本控制已恢复

**现象**：项目根 `.git` 与 `.workbuddy` 目录同时消失，`git` 命令报 `not a git repository`。
回收站无 `.git` 记录（且 `overview.md`、`refs/` 等文件也已不在）。

**查证结论（重要，决定了同步策略）**：
- 远端 `github.com/li589/WebGIS`，默认分支 `main`，工作分支 `dev`。
- 远端 dev HEAD = `0ef37db`（2026-09-08），相对本机最后推送 `d5148e9` **领先 49 个提交、落后 0**
  → 我此前的工作（C-1 修复 `aa7dbf1`、deck.gl 文档 `d5148e9`）**全部在远端，无丢失**。
- 用 GitHub Tree API 拉取 dev 文件树（2557 blob）与本地比对：
  - 1672 处"内容不同"→ 按 CRLF 归一化后**真实差异 0**（全局 `core.autocrlf=true`，工作区 CRLF/仓库 LF）
  - 本地独有文件基本是运行期产物，且全部被 `.gitignore` 覆盖
  - 结论：**本地工作区内容与远端 dev HEAD 完全一致，无需合代码**，只需补回 `.git`

**恢复步骤（可复用）**：
1. `git clone --depth 1 --branch dev <url>` 到临时目录（全量 123MB 太慢，约 2MB/min）
2. 把临时仓库的 `.git` 复制进项目根（不动任何工作区文件）
3. `git add -A` + `git reset --mixed HEAD` 重建索引 stat 缓存
   —— 关键：借来的索引会让 ~309 个文件显示为 ` M`，但 `git diff --quiet` 判定**零内容差异**，
   纯 stat 脏；`git update-index --refresh` 无法消除，必须用 add+reset
4. 恢复误删的 10 个受控文件：`.cursor/`(4) `.github/`(2) `.kiro/`(2) `.trae/`(1) `Test/.vitest-reg-result.txt`(1)
5. 最终 `git status` 完全干净，HEAD `0ef37db`，`dev...origin/dev`

**教训**：
- 大仓库排查优先用 GitHub API（commits / trees）而非等全量克隆，几分钟就能定性
- 判断"是否真有改动"必须用 `git diff --quiet`，`git status` 的 ` M` 在索引外借场景下是假阳性
- 沙箱下 git 需前置 `env -u ACC_PRODUCT_CONFIG_V3 CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID=`
