# Git 沙箱安全规范（2026-08-22 事故沉淀，单一真源）

> 背景：AI 工具沙箱（safe-delete shim）会拦截/杀死涉及批量删除的 git 操作，
> 已两次（2026-08-21 / 08-22）造成 `.git/refs` 或 pack 文件丢失。
> 本规范目标是：**修改不丢失、代码不意外回退、事故可快速恢复**。

---

## 1. 禁用清单（沙箱内绝对不做）

| 禁用操作 | 原因 | 替代方案 |
|---|---|---|
| `git stash` / `git stash pop` | stash 内部做 refs 移动+工作区删除，被沙箱杀死后 refs/objects 双丢 | 用 `git diff > patch` + `git checkout -- file` 分步做；或直接 commit 到临时分支 |
| `git checkout <branch>`（切换分支） | 需批量删除/覆写工作区文件，沙箱静默杀死，留 index.lock | 需要旧版本文件用 `git show <sha>:<path> > <path>`（纯写入，沙箱安全） |
| `git merge`（工作区合并） | 同上 | 纯 plumbing 合并：`git commit-tree $(git rev-parse dev^{tree}) -p main -p dev` → `git update-ref` |
| `git worktree remove` | 批量删除 | 手动 `python -c "import shutil; shutil.rmtree(...)"` |
| `git reset --hard` | 覆写工作区，未提交修改直接丢失 | `git reset --mixed`（只重建 index，工作区不动） |
| `git rebase -i` / 交互式命令 | 打开编辑器挂死 | 不用 |
| `rm -rf .git` / `git init --bare` 修复 | **严禁**——会造成不可逆损坏 | 见 §3 恢复套路 |

## 2. 提交纪律（防修改丢失）

1. **小步提交**：完成一个逻辑单元立即 commit，不让大量改动滞留工作区（滞留的修改在沙箱事故中最易丢）。
2. **即时推送**：每次 commit 后立即 `git push origin dev`——GitHub 是最可靠的备份（SSH 443 通道：`ssh://git@ssh.github.com:443/li589/WebGIS.git`）。
3. **大文件预检**：`git add` 前查 blob（>100MB GitHub 拒收；>1MB pre-commit 拦截需 `--no-verify` 用户批准）。
4. **提交前置**：`env -u ACC_PRODUCT_CONFIG_V3 git commit ...`（大注入 env 超 Windows 32767 上限会崩 pre-commit）。
5. **钩子绕过前置**（pytest/node 触发的 git 操作）：`CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= ...`

## 3. .git 损伤恢复套路（已两次验证，2026-08-21 / 08-22）

症状：`git status` 报 `not a git repository`，或 `git cat-file` 报 `bad object`（pack 文件只剩 .idx 没有 .pack）。

```
1. 评估损伤：ls .git/refs/ 、.git/objects/pack/、cat .git/logs/HEAD（reflog 通常还在）
2. 从远程拉对象：git fetch origin dev          # SSH 443 通道
3. 重建指针：
   git update-ref refs/heads/dev <FETCH_HEAD 的 sha>
   git update-ref refs/remotes/origin/dev <同 sha>
   （refs/heads / refs/remotes/origin 目录不存在先 mkdir -p）
4. 重建 index（不动工作区）：git reset --mixed
5. 验证：git log --oneline -3 && git status --short
```

**红线**：恢复过程严禁 `rm -rf .git` / `git init --bare` / 任何 refs 目录删除。
拿不准时**停下问用户**，远程（origin/dev）永远有完整副本。

## 4. "回退"的安全姿势（AI 助手专用）

- 用户说"回退/还原某文件"→ **只允许** `git show <sha>:<path> > <path>`（文件级、纯写入）。
- 用户说"不要危险回退"→ 不得 stash / checkout / reset --hard / clean，只做前向修复。
- 二分定位问题时，改动过的文件用完**立即** `git checkout HEAD -- <file>` 还原或按 sha 重写，不留半成品状态。
- **诊断代码（console.log / window.__diag / try-catch 探针）在问题解决后必须全部清除**再提交。

## 5. remote-tracking ref 写入被拦的处置

`refs/remotes/origin/*` 写入可能被沙箱拦（packed-refs 不更新）。手动写 loose ref：
```
mkdir -p .git/refs/remotes/origin && printf "<sha>" > .git/refs/remotes/origin/dev
```
