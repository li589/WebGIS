# WebGIS 项目 Git 协作说明

## 当前仓库约定

- GitHub 仓库：`https://github.com/li589/WebGIS`
- 稳定分支：`main`
- 日常开发分支：`dev`

项目约定如下：

- `main` 只放相对稳定、可展示、可交付的代码
- `dev` 用于日常开发和合并
- 前端主要目录：`Code/frontend`
- 后端主要目录：`Code/backend`、`Code/algorithms`
- 说明：早期约定中的 `Code/infra` 当前不存在；基础设施见 `Code/backend/docker-compose.yml` 与根目录 `launch.py`
- 共同维护目录：`Code/docs`、`Code/shared`、根目录 `README.md`

## Windows 和 Linux 下的 Git 安装与基础配置

### Windows 安装 Git

如果我是 Windows 用户，我优先这样安装：

1. 打开 Git 官网：`https://git-scm.com/download/win`
2. 下载 Windows 安装包并安装
3. 安装时大多数选项保持默认即可
4. 安装完成后，打开 `PowerShell`、`Git Bash` 或终端测试：

```bash
git --version
```

如果能看到版本号，例如 `git version 2.x.x`，说明安装成功。

### Linux 安装 Git

如果我是 Linux 用户，我根据发行版执行对应命令。

Ubuntu / Debian:

```bash
sudo apt update
sudo apt install -y git
```

CentOS / Rocky / RHEL:

```bash
sudo dnf install -y git
```

较老系统如果没有 `dnf`，可尝试：

```bash
sudo yum install -y git
```

安装完成后测试：

```bash
git --version
```

### 第一次基础配置

不管我是 Windows 还是 Linux，第一次安装 Git 后，建议先配置用户名和邮箱：

```bash
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"
```

查看当前全局配置：

```bash
git config --global --list
```

如果我是 Windows 用户，建议再配置一次换行策略：

```bash
git config --global core.autocrlf true
```

如果我是 Linux 用户，建议保持 `LF`：

```bash
git config --global core.autocrlf input
```

如果我希望默认分支名是 `main`，可以执行：

```bash
git config --global init.defaultBranch main
```

### 可选：生成 SSH Key

如果我后续希望更方便地推送 GitHub，也可以配置 SSH Key。

先生成：

```bash
ssh-keygen -t ed25519 -C "你的邮箱"
```

然后查看公钥内容：

```bash
cat ~/.ssh/id_ed25519.pub
```

把公钥添加到 GitHub 账号后，后续就可以使用 SSH 地址克隆和推送仓库。

## 基本 Git 使用方法

### 日常命令

查看当前目录是不是 Git 仓库：

```bash
git status
```

查看当前分支：

```bash
git branch --show-current
```

查看远端仓库：

```bash
git remote -v
```

查看提交历史：

```bash
git log --oneline --graph --decorate -10
```

### 我第一次拿到一个已有项目

如果仓库已经在 GitHub 上，我一般这样获取：

```bash
git clone https://github.com/li589/WebGIS.git
cd WebGIS
```

然后切到开发分支：

```bash
git checkout dev
git pull origin dev
```

### 我本地改完代码后怎么提交

最基本的提交流程是：

```bash
git status
git add .
git commit -m "feat: 简要说明本次改动"
git push origin dev
```

如果我只想提交某一个文件或某一个目录，可以写具体路径：

```bash
git add Code/frontend
git add Code/backend/app
```

### 我想先同步远端最新代码

最直接的方式是：

```bash
git pull origin dev
```

如果我只想先拿远端信息，不立刻合并：

```bash
git fetch origin
```

### 我想新建一个功能分支

如果我要开发独立功能，我可以从 `dev` 拉一个分支：

```bash
git checkout dev
git pull origin dev
git checkout -b feature/功能名
```

完成后推送：

```bash
git push -u origin feature/功能名
```

### 我改乱了但还没提交怎么办

如果我只是改了工作区，还没提交，可以先看状态：

```bash
git status
```

如果我想临时把当前改动收起来：

```bash
git stash
```

恢复暂存内容：

```bash
git stash pop
```

### 我需要特别注意什么

- `git add .` 会把当前目录下所有改动一起加入暂存区，执行前先看 `git status`
- `git commit` 是提交到本地仓库，不等于已经上传 GitHub
- `git push` 才是把本地提交上传到远端仓库
- `git pull` 是“拉取并合并”，执行前最好确认自己当前分支和工作区状态
- 如果本地有重要未提交改动，不要直接执行覆盖性的 `git restore --source ...`

## 如果我是前端开发者

### 第一次获取项目

第一次在本地拿这个项目时，执行：

```bash
git clone https://github.com/li589/WebGIS.git
cd WebGIS
git checkout dev
git pull origin dev
```

完成后，我就在本地切到了 `dev` 分支。

### 我主要改哪里

我主要修改：

- `Code/frontend`

我尽量不主动改这些目录，除非已经和后端开发者确认：

- `Code/backend`
- `Code/algorithms`

我如果要改这些公共目录，会先沟通：

- `Code/docs`
- `Code/shared`
- `README.md`

### 我开始开发前怎么同步

因为我主要做前端，我不希望覆盖自己正在开发的前端代码，所以我优先按目录同步后端和公共文件，而不是直接整分支 `pull`。

我执行：

```bash
git checkout dev
git fetch origin
git restore --source origin/dev -- Code/backend Code/algorithms
git restore --source origin/dev -- Code/shared Code/docs README.md Code/README.md
```

这样做的效果是：

- 我拿到后端最新代码
- 我拿到共享协议和文档最新内容
- 我尽量不动自己的 `Code/frontend`

### 如果我当前前端还没提交

同步前我先看状态：

```bash
git status
```

如果我本地有重要前端改动，我先做其中一种：

#### 方案 1：直接提交

```bash
git add .
git commit -m "wip(frontend): current progress"
```

#### 方案 2：临时暂存

```bash
git stash
```

恢复时：

```bash
git stash pop
```

### 我日常开发和提交的流程

我平时这样做：

```bash
git checkout dev
git fetch origin
git restore --source origin/dev -- Code/backend Code/algorithms
git restore --source origin/dev -- Code/shared Code/docs README.md Code/README.md
```

然后我在 `Code/frontend` 中开发。

开发完成后，我执行：

```bash
git add .
git commit -m "feat(frontend): 简要说明本次改动"
git push origin dev
```

我常见的提交信息会写成：

```bash
git commit -m "feat(frontend): add OSM base map"
git commit -m "fix(frontend): adjust floating panels"
git commit -m "refactor(frontend): split dashboard layout"
```

### 如果我有独立功能

如果我在做一块比较独立的前端功能，我更推荐从 `dev` 拉自己的功能分支：

```bash
git checkout dev
git pull origin dev
git checkout -b feature/frontend-map-panel
```

开发完成后：

```bash
git add .
git commit -m "feat(frontend): complete map panel"
git push -u origin feature/frontend-map-panel
```

然后再由项目负责人把这个功能分支合并到 `dev`。

### 我什么时候改回正常 `git pull`

如果我后续开始频繁修改这些公共目录：

- `Code/shared`
- `Code/docs`
- 根目录说明文档

那我就不再只按目录同步，而是改成：

```bash
git checkout dev
git pull origin dev
```

### 我作为前端开发者特别注意什么

- 我提交前先看 `git status`
- 我尽量只提交和当前前端功能相关的文件
- 我不把 `node_modules`、构建产物、缓存提交到仓库
- 如果我要改共享协议，我先和后端开发者确认字段结构

## 如果我是后端开发者

### 第一次获取项目

第一次在本地拿这个项目时，执行：

```bash
git clone https://github.com/li589/WebGIS.git
cd WebGIS
git checkout dev
git pull origin dev
```

### 我主要改哪里

我主要修改：

- `Code/backend`
- `Code/algorithms`

我尽量不主动改这些目录，除非已经和前端开发者确认：

- `Code/frontend`

我如果要改这些公共目录，会先沟通：

- `Code/docs`
- `Code/shared`
- `README.md`

### 我开始开发前怎么同步

因为我主要做后端，我不希望覆盖自己正在开发的后端代码，所以我优先按目录同步前端和公共文件，而不是直接整分支 `pull`。

我执行：

```bash
git checkout dev
git fetch origin
git restore --source origin/dev -- Code/frontend
git restore --source origin/dev -- Code/shared Code/docs README.md Code/README.md
```

这样做的效果是：

- 我拿到前端最新代码
- 我拿到共享协议和文档最新内容
- 我尽量不动自己的后端目录

### 如果我当前后端还没提交

同步前我先看状态：

```bash
git status
```

如果我本地有重要后端改动，我先做其中一种：

#### 方案 1：直接提交

```bash
git add .
git commit -m "wip(backend): current progress"
```

#### 方案 2：临时暂存

```bash
git stash
```

恢复时：

```bash
git stash pop
```

### 我日常开发和提交的流程

我平时这样做：

```bash
git checkout dev
git fetch origin
git restore --source origin/dev -- Code/frontend
git restore --source origin/dev -- Code/shared Code/docs README.md Code/README.md
```

然后我在 `Code/backend`、`Code/algorithms` 中开发。

开发完成后，我执行：

```bash
git add .
git commit -m "feat(backend): 简要说明本次改动"
git push origin dev
```

我常见的提交信息会写成：

```bash
git commit -m "feat(backend): add task submit api"
git commit -m "fix(backend): normalize response schema"
git commit -m "feat(algorithms): add demo model loader"
```

### 如果我有独立功能

如果我在做一块比较独立的后端功能，我更推荐从 `dev` 拉自己的功能分支：

```bash
git checkout dev
git pull origin dev
git checkout -b feature/backend-task-api
```

开发完成后：

```bash
git add .
git commit -m "feat(backend): complete task api"
git push -u origin feature/backend-task-api
```

然后再由项目负责人把这个功能分支合并到 `dev`。

### 我什么时候改回正常 `git pull`

如果我后续开始频繁修改这些公共目录：

- `Code/shared`
- `Code/docs`
- 根目录说明文档
- 前后端共同依赖的接口定义

那我就不再只按目录同步，而是改成：

```bash
git checkout dev
git pull origin dev
```

### 我作为后端开发者特别注意什么

- 我提交前先看 `git status`
- 我尽量只提交和当前后端功能相关的文件
- 我不把本地环境、缓存、临时文件提交到仓库
- 如果接口返回结构变化，我先同步给前端开发者
- 如果新增公共协议，我优先更新 `Code/shared` 或 `Code/docs`

## 如果我只是想快速查命令

查看当前分支：

```bash
git branch --show-current
```

查看当前状态：

```bash
git status
```

查看所有分支：

```bash
git branch -a
```

切到 `dev`：

```bash
git checkout dev
```

拉取 `dev` 最新代码：

```bash
git pull origin dev
```

提交并推送到 `dev`：

```bash
git add .
git commit -m "feat: 本次改动说明"
git push origin dev
```

只同步前端目录：

```bash
git fetch origin
git restore --source origin/dev -- Code/frontend
```

只同步后端目录：

```bash
git fetch origin
git restore --source origin/dev -- Code/backend
```

同步公共文档和共享协议：

```bash
git fetch origin
git restore --source origin/dev -- Code/shared Code/docs README.md Code/README.md
```

## 最后一句话

如果我是前端开发者，我重点维护 `Code/frontend`，同步时优先拿后端和共享目录。
如果我是后端开发者，我重点维护 `Code/backend`、`Code/algorithms`，同步时优先拿前端和共享目录。
不管我是哪种角色，我都尽量避免在本地有重要未提交改动时直接执行 `git restore --source ...`。
