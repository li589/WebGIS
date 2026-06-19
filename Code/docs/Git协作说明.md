# WebGIS 项目 Git 协作说明

## 当前仓库约定

- GitHub 仓库：`https://github.com/li589/WebGIS`
- 稳定分支：`main`
- 日常开发分支：`dev`

项目约定如下：

- `main` 只放相对稳定、可展示、可交付的代码
- `dev` 用于日常开发和合并
- 前端主要目录：`Code/frontend`
- 后端主要目录：`Code/backend`、`Code/algorithms`、`Code/infra`
- 共同维护目录：`Code/docs`、`Code/shared`、根目录 `README.md`

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
- `Code/infra`

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
git restore --source origin/dev -- Code/backend Code/algorithms Code/infra
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
git restore --source origin/dev -- Code/backend Code/algorithms Code/infra
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
- `Code/infra`

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

然后我在 `Code/backend`、`Code/algorithms`、`Code/infra` 中开发。

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
如果我是后端开发者，我重点维护 `Code/backend`、`Code/algorithms`、`Code/infra`，同步时优先拿前端和共享目录。
不管我是哪种角色，我都尽量避免在本地有重要未提交改动时直接执行 `git restore --source ...`。
