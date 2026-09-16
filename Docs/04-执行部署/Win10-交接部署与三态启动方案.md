# Win10 交接部署与三态启动方案

> **定位**：本文回答四件事——交接怎么交、目标机怎么起、三态怎么统一进 launcher、Docker 怎么自定义。
> 它是 `部署手册与硬约束清单.md` 的**执行侧补充**：硬约束（§5）、容器化设计（§12）、改码工作流（§12.9）
> 仍以手册为真源，本文不复制、只引用与落地。
>
> 决策基线（2026-09-16 用户确认）：临时部署到**另一台 Win10 台式机** → **裸机态先行**；三态**统一进 launcher**。

---

## 0. 怎么用本文

| 你的角色 | 读哪节 |
|---|---|
| 今天就要把服务在那台 Win10 上跑起来 | §6 交接作业指引（阶段 A–F） |
| 想知道启动脚本现在支持什么、缺什么 | §1（含三态支持矩阵） |
| 要补齐「交付态」 | §3 + §4 |
| 要改镜像存放位置 / 换镜像源 / 自定义端口卷名 | §5 |
| 接手人（要长期维护） | §6-F 交接材料清单 + 手册 §5 硬约束 |

---

## 1. 现状盘点：启动脚本全貌

### 1.1 分层结构（实测）

```
start.bat / start.sh          ← 入口包装（切到 Env/Python312 后调 launch.py）
        └─ launch.py          87 行，只做 sys.argv 兜底 + 转交 cli.main()
                └─ launch/cli.py          argparse 子命令树 + 分发表
                        └─ launch/commands.py     cmd_* 实现（57 KB，最大件）
                                ├─ launch/process_manager.py   宿主进程启停（FastAPI/Worker/Beat/Vite）
                                ├─ launch/docker_manager.py    容器栈：Redis/MinIO/Open-Meteo
                                ├─ launch/gateway_manager.py   Nginx Gateway（静态 / HMR 两剖面）
                                ├─ launch/subprocess_utils.py  命名卷、隐藏窗口、按命令行杀进程
                                └─ launch/constants.py         路径、端口、7 队列定义
```

### 1.2 CLI 表面（10 个子命令）

| 子命令 | 作用 | 备注 |
|---|---|---|
| `start` | 启动服务（默认 `component=all`、`mode=bare`） | 无子命令时等价于 `start` |
| `stop` | 停止全部；`stop gateway` 仅停网关 | 不删缓存、不 flush |
| `status` | 服务状态（Docker / FastAPI / 前端 / Gateway / Worker PID / volume） | |
| `reload` | 配置热重载，当前仅 `gateway`（`nginx -t` + `-s reload`，不重建容器） | |
| `restart` | 重启；`--rebuild-frontend` 可强制 rebuild dist | 默认按组件矩阵 clean |
| `logs` | 日志，`-n N` 指定行数 | |
| `flush` | 清 Redis DB + 天气文件缓存 | **高风险**，start/restart 永不自动执行 |
| `clean-cache` | 清 `__pycache__` / `*.pyc` / Vite `.vite` | 不碰 Redis |
| `reset-db` | 清空 `workflow_state`，自动快照 + 重 seed | 有 `--yes` / `--dry-run` 语义 |
| `sync` | 数据面一次性同步（`data-sync` 栈，默认 `open-meteo-sync`） | |

### 1.3 组件矩阵（`start <component>`）

| component | 实际动作 | 形态 |
|---|---|---|
| `all`（默认） | `_start_all()`：Docker 基础设施 → 等 Redis 就绪 → 后端进程组 → Nginx Gateway | 全量 |
| `docker` | 仅 Redis + MinIO + MinIO-init + Open-Meteo | 容器（project `backend`） |
| `backend` | FastAPI + 7 队列 / 9 Worker 进程 + Beat | **宿主进程** |
| `fastapi` / `beat` / `worker` / `worker:<name>` | 单个宿主进程 | 宿主进程 |
| `frontend` | Vite 直连 `:5175`（会先停 Gateway，二者互斥） | 宿主进程 |
| `gateway` | Nginx 同域入口 `:5175`（静态 `dist`；`--vite` 时背后挂 Vite `:5174`） | 容器（project `gateway`） |

### 1.4 三个 compose 栈（project 名彼此隔离）

| 栈 | project 名 | 文件 | 内容 |
|---|---|---|---|
| 基础设施 | `backend`（**硬编码**于 `launch/docker_manager.py`） | `Code/backend/docker-compose.yml` | Redis / MinIO / minio-init / Open-Meteo |
| 网关 | `gateway`（**硬编码**于 `launch/gateway_manager.py`） | `Code/infra/gateway/docker-compose.yml`（+ `.hmr.yml`） | Nginx |
| 数据面 | `data-sync`（可由 `BACKEND_OPEN_METEO_SYNC_COMPOSE_PROJECT` 覆盖） | `Code/infra/data-sync/docker-compose.yml` | 一次性同步任务 |

### 1.5 三态支持矩阵 ← **这就是你的问题的答案**

| 态 | 现状 | 实际入口 | 后端跑在哪 | 前端跑在哪 |
|---|---|---|---|---|
| **裸机态** | ✅ **已可用** | `start.bat` / `launch.py start` | 宿主进程（`Env/Python312`） | Gateway 容器服务静态 `dist`，`:5175` |
| **开发态** | ✅ **已可用** | `launch.py start --vite` | 宿主进程（同上） | Gateway `:5175` + 宿主 Vite HMR `:5174` |
| **交付态（全容器化）** | ❌ **完全缺失** | 无 | 无 | 无 |

**结论：当前只支持两态。** 交付态不是"配置没开"，而是**代码不存在**：

- 全仓**没有任何 Dockerfile**（`find Code -iname "Dockerfile*"` 为空）；
- `launch/docker_manager.py` 只负责拉起 Redis/MinIO/Open-Meteo 三个基础设施容器，**没有**构建镜像、拉起后端容器的能力；
- `launch/commands.py` 的 `cmd_start` 分派表里没有 prod 分支，`_start_all()` 走到的是宿主进程组；
- 网关 `nginx.conf:20-23` 的 upstream 写死 `host.docker.internal:8000`（**假设后端正跑在宿主机上**），容器化后端时该地址失效；
- `launch/cli.py` 没有 `--mode` 之类的模式开关。

### 1.6 缺口清单（供指派）

| # | 缺口 | 影响 | 归属 |
|---|---|---|---|
| **G-A** | 无 backend Dockerfile | 交付态无法构建 | §3.1 |
| **G-B** | 无 web（前端）Dockerfile | 交付态前端仍是宿主机 `dist` 目录 | §3.1 |
| **G-C** | 无 `compose.prod.yml` 生产编排 | 后端/Worker/Beat 无法容器化编排 | §3.2 |
| **G-D** | 网关 upstream 写死 `host.docker.internal:8000` | 容器化后 API 反代断开 | §3.3 |
| **G-E** | launcher 无 `--mode prod` 入口与分派 | 三态无法用一个入口切换 | §4 |
| **G-F** | **`source_uri_map.json` 未被 `.gitignore` 覆盖** | 目标机创建真实机构 URI 后**会被误提交**（内含实验室盘符路径） | §6-D，**交接前必修** |
| **G-G** | `deployment.config.json` 真源**当前不存在**（仅有 `.bak.1`，内容为 `data_root: I:\test`） | 目标机沿用现状只能靠 `.env`；若配了该文件则须保证格式合法，否则 fail-closed 拒启 | §6-D |

---

## 2. 目标机选型：为什么先走裸机态

| 维度 | 裸机态（现实选择） | 交付态（目标形态） |
|---|---|---|
| 今天能否跑通 | ✅ 现有脚本直接可用 | ❌ 需先补 G-A…G-E |
| 目标机依赖 | Python 3.12.9 + Node 22 + Docker Desktop | 只需 Docker Desktop |
| 与开源代码一致性 | `Env/Python312` 需按配方重建（§6-B） | 镜像内固化，无重建 |
| 交付态可切换性 | — | 镜像 tag = git sha，可一键回滚 |
| 风险 | 环境漂移（本机 595 个包，新机装错版本） | 首次构建耗时 |

**推荐路径**：裸机态先上（完成交接与验收）→ 期间按 §3/§4 补交付态 → 在目标机上按 §6-G 切换。
两种形态**端口互斥**（都占 `5175`/`8000`/`16379`），不可同时运行（手册 §12.8）。

---

## 3. 交付态实施方案（补齐 G-A…G-D）

> 详细设计与草案条文见手册 **§12**（镜像规划 / 目录硬约束 / Dockerfile 草案 / bind mount 与 UID /
> 生产编排 / 构建分发 / 容器化 SOP / 迁移回退）。本节只列**交接视角必须记住的要点**。

### 3.1 镜像规划（引用手册 §12.1）

| 镜像 | 角色 |
|---|---|
| `cgda-backend:<sha>` | **一镜像三角色**：`fastapi` / `worker` / `beat`（仅启动命令不同） |
| `cgda-web:<sha>` | 静态 `dist` + 容器版 nginx 反代 |
| `redis` / `minio` / `minio-mc` / Open-Meteo | 沿用既有 pin（tag 或 digest） |

**镜像内目录布局是硬约束**（手册 §12.2）：必须保持 `/srv/Code/{backend,algorithms,shared}` 兄弟结构——
依据 `Code/backend/start_fastapi.py:18-24`、`start_celery_worker.py:6-13` 把 `Code/` 插入 `sys.path`，
以及 `app/core/config.py:42-44` 的 provider 根推导。**不要**把 backend 单独 COPY 到 `/app`。

### 3.2 交接需新增的文件（尚未创建）

| 文件 | 作用 | 草案出处 |
|---|---|---|
| `Code/backend/Dockerfile` | 后端镜像（含算法包、shared、spatialite/GDAL） | 手册 §12.3 |
| `Code/infra/gateway/Dockerfile.web` | 前端构建 + nginx 运行 | 手册 §12.1 |
| `Code/backend/compose.prod.yml` | fastapi / worker-* / beat 生产编排（project `cgda`） | 手册 §12.5 |
| `Code/infra/gateway/nginx.prod.conf` | upstream 改指容器后端 | §3.3 |

### 3.3 网关 upstream 切换（G-D 的具体做法）

现状（裸机态，`Code/infra/gateway/nginx.conf:20-23`）：

```nginx
upstream cgda_fastapi {
    server host.docker.internal:8000;   # ← 假设后端在宿主机
    keepalive 16;
}
```

交付态必须改为容器网络内的服务名（与 `compose.prod.yml` 的服务名一致）：

```nginx
upstream cgda_fastapi {
    server backend:8000;                # ← 同一 compose 网络
    keepalive 16;
}
```

同理，`extra_hosts: host.docker.internal:host-gateway` 这一条在交付态不再需要。
**两张 upstream 表分属两个文件，切换时不要手改同一份**（否则裸机态回退会失败）。

---

## 4. 三态统一进 launcher 的设计（补 G-E）

### 4.1 目标 CLI 表面（向后兼容）

```bash
# 裸机态（默认，等价于今天的 start）
Env\Python312\python.exe launch.py start
Env\Python312\python.exe launch.py start --mode bare

# 开发态（--vite 保留为同义词，不破坏既有习惯）
Env\Python312\python.exe launch.py start --mode dev
Env\Python312\python.exe launch.py start --vite

# 交付态
Env\Python312\python.exe launch.py start --mode prod
Env\Python312\python.exe launch.py deploy build     # 构建两个自建镜像
Env\Python312\python.exe launch.py deploy up|down   # 起停交付态栈
Env\Python312\python.exe launch.py deploy logs      # 容器日志
```

### 4.2 `--mode` 语义表

| mode | 基础设施（容器） | 后端 | 前端 | 对外入口 | 前提 |
|---|---|---|---|---|---|
| `bare`（默认） | `backend` 栈 | **宿主进程**（`Env/Python312`） | Gateway 容器 → 静态 `dist` | `:5175` | Python 运行时已建 |
| `dev` | `backend` 栈 | **宿主进程** | Gateway 容器 + 宿主 Vite HMR `:5174` | `:5175` | 同上 + Node |
| `prod` | `backend` 栈 + 应用容器 | **容器**（一镜像三角色） | `cgda-web` 容器 | `:5175` | 两镜像已构建 |

### 4.3 兼容与冲突规则（务必遵守，否则破坏现有习惯）

1. `--mode` **仅在 `component=all`（或不指定组件）时生效**；显式 `start fastapi` / `start worker:x`
   等**保持宿主进程语义不变**——那是排障入口，不应被模式改写。
2. `--mode prod` 与 `--vite` **互斥**，同时给应报错退出（prod 下没有宿主 Vite）。
3. `--mode prod` 与 `--no-docker` 互斥（prod 本身就是容器栈）。
4. `--mode prod` 时 `--mode` 隐含 `BACKEND_ENV=production`，因此**不得**开启热重载
   （`start_fastapi.py:32-40` 的生产守卫会强制关闭；详见手册 §12.9 坑 1）。
5. 交付态与裸机态**不可同时运行**（端口冲突）；`start --mode prod` 应先做互斥检测并给出明确提示。

### 4.4 落地清单（最小改动，文件级）

| 文件 | 改动 | 说明 |
|---|---|---|
| `launch/cli.py` | `_add_start_restart_args()` 增加 `--mode`（`choices=["bare","dev","prod"]`，默认 `bare`）；新增 `deploy` 子命令（`build`/`up`/`down`/`logs`） | 只加参数与子命令，不改既有参数 |
| `launch/commands.py` | `cmd_start` 在 `component=="all"` 分支前置 mode 判定；新增 `_start_all_prod()` 与 `cmd_deploy()` | 既有 `_start_all()` 分支**不动** |
| `launch/docker_manager.py` | 新增 prod 应用的 `up/down`（project `cgda`，文件 `Code/backend/compose.prod.yml`）；新增 `build_images()` | 复用既有 `hidden_kwargs()` 隐藏窗口 |
| `launch/gateway_manager.py` | 增加 prod 剖面：用 `nginx.prod.conf` 与 `Dockerfile.web` 镜像 | 现有 static/hmr 两剖面不动 |
| `launch/constants.py` | 新增 `MODE_*` 常量、prod compose 路径、`CGDA_TAG` 读取 | |

**设计原则**：三态是**入口层的分派**，不是重写。既有 `_start_all()`（裸机）与 HMR 剖面保持原样，
新增分支只在 `mode` 命中时接管——这样即使新代码有 bug，裸机态也不受影响（可安全回退）。

---

## 5. Docker 自定义清单

### 5.1 镜像存储位置（**你最需要自定义的一项**）

**概念澄清**：镜像与容器层存在 **Docker 引擎的 data-root**，**不在仓库里、也不归 launcher 管**。
`launch/` 全程只调 `docker` CLI，从不碰这个路径。所以"改镜像位置"是改 **Docker 引擎配置**，不是改本项目。

| 平台 | 容器/镜像与卷的实际落点 | 改法 |
|---|---|---|
| **Windows + Docker Desktop（WSL2 后端）** | `Settings → Resources → Advanced → Disk image location`，本机现为 `I:\Docker\DockerDesktop` | GUI 改后 Docker 会迁移动 vhdx（耗时） |
| Docker Desktop（含卷） | 同上，**named volume 也在此 vhdx 内** | 同上 |
| Linux（CentOS/Debian） | `/var/lib/docker` | `/etc/docker/daemon.json` 设 `"data-root": "/data/docker"`，然后 `systemctl restart docker` |

⚠️ **三个必须知道的后果**：

1. **迁移会停引擎并搬迁全部镜像/容器/卷**。本项目 named volume
   `backend_open-meteo-data`（Open-Meteo 数 GB 数据）就在里面——迁移前**必须**确认它要一起走，
   或先按手册 §6/数据面流程重新 `launch.py sync` 拉取。
2. **硬约束 A5 关联**：Open-Meteo 数据**只进 named volume，Windows 上禁 bind mount**。
   换盘时不能用"改成 bind mount 到 D 盘"来偷懒（会 errno 95 或数据错位）。
3. **迁移后必须复验**：`docker volume inspect backend_open-meteo-data` 能看到 volume；
   `launch.py status` 能识别；Open-Meteo 探活正常。

> 本机已有 Docker WSL 数据目录符号链接指向外接 `I:` 盘的历史事故记录，
> 见 `.ai/memory/2026-09-11-docker-wsl-symlink-i-drive.md` —— 换盘前先读。

### 5.2 镜像命名与 tag（现状：无自建镜像）

设计（配合 `CGDA_TAG` 注入，手册 §12.6 已采用）：

| 变量 | 默认 | 作用 |
|---|---|---|
| `CGDA_REGISTRY` | 空（= 本地镜像） | 镜像仓库前缀，如 `harbor.lab.local/cgda` |
| `CGDA_IMAGE_PREFIX` | `cgda` | 镜像名前缀 |
| `CGDA_TAG` | `git rev-parse --short HEAD` | 版本标记，**回滚靠它** |

拼装结果：`${CGDA_REGISTRY}/${CGDA_IMAGE_PREFIX}-backend:${CGDA_TAG}`。

### 5.3 registry 镜像加速（内网 / 国内网络）

现状：compose 直连 Docker Hub、`public.ecr.aws`（Open-Meteo）、`quay` 系。目标机若无外网直连或很慢：

| 手段 | 做法 | 适用 |
|---|---|---|
| 镜像加速器 | Docker Desktop → `Settings → Docker Engine` → `"registry-mirrors": ["https://<mirror>"]` | 目标机能出网但慢 |
| 私有 registry | 在 `CGDA_REGISTRY` 前先 `docker tag` + `docker push` | 多台目标机 / 内网 |
| 离线包 | `docker save cgda-backend:<sha> cgda-web:<sha> \| gzip > images.tar.gz` → 目标机 `docker load` | **完全隔离网**（手册 §12.6） |

需拉取的基础镜像清单：`nginx` / `redis` / `minio/minio` / `minio/mc` / `python:3.12-slim` /
`node:22-alpine` / Open-Meteo（ECR digest）。**交付前应在目标机预拉一遍并记录 digest**。

### 5.4 已可自定义 vs 需改代码

| 项 | 现状 | 可否自定义 | 机制 |
|---|---|---|---|
| Open-Meteo 数据卷名 | ✅ | ✅ | `OPEN_METEO_DATA_VOLUME`（默认 `backend_open-meteo-data`） |
| Open-Meteo 镜像 | ✅ digest pin | ✅ | `OPEN_METEO_IMAGE` |
| Open-Meteo 宿主端口 | 8080 | ✅ | `OPEN_METEO_HOST_PORT` |
| MinIO 凭据 | `minioadmin` 默认 | ✅ | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` |
| 数据面 compose project | `data-sync` | ✅ | `BACKEND_OPEN_METEO_SYNC_COMPOSE_PROJECT` |
| 数据根 / 产物根 | — | ✅ | `BACKEND_DATA_ROOT` / `BACKEND_OUTPUT_ROOT`（**目录须已存在**，生产空根拒启） |
| 前端端口 | 5175 | ⚠️ 部分 | `--frontend-port`（**仅** `start frontend` 时生效） |
| **Redis / MinIO 宿主端口** | 16379 / 9100 / 9101 | ❌ | 硬编码在 `Code/backend/docker-compose.yml`（注释说明为避开 WinNAT 保留段） |
| **基础设施 compose project 名** | `backend` | ❌ | 硬编码于 `launch/docker_manager.py:61,98` |
| **网关 compose project 名 / 容器名** | `gateway` / `cgda-gateway-nginx` | ❌ | 硬编码于 `launch/gateway_manager.py:31-33` |
| **网关宿主端口 5175** | 5175 | ❌ | 硬编码于 `launch/gateway_manager.py:33` + compose ports |

> 结论：**卷名/镜像/凭据/数据根已经 env 化，端口与 project 名还没。**
> 若目标机端口被占（WinNAT 保留段或他软件），需要改代码或直接改 compose——**交接前应先在那台机上
> 跑一次端口体检**（§6-B）。

### 5.5 建议新增的 env 键（`CGDA_*` 命名空间，与后端 `BACKEND_*` 隔离）

| 键 | 默认 | 作用 | 落地文件 |
|---|---|---|---|
| `CGDA_MODE` | `bare` | 默认模式（等价 `--mode`） | launcher |
| `CGDA_TAG` | git short sha | 镜像 tag | compose.prod.yml |
| `CGDA_REGISTRY` | 空 | 镜像仓库前缀 | compose.prod.yml |
| `CGDA_IMAGE_PREFIX` | `cgda` | 镜像名前缀 | compose.prod.yml |
| `CGDA_BACKEND_PROJECT` | `backend` | 基础设施 compose project 名 | `docker_manager.py` |
| `CGDA_GATEWAY_PROJECT` / `CGDA_GATEWAY_CONTAINER` | `gateway` / `cgda-gateway-nginx` | 网关栈标识 | `gateway_manager.py` |
| `CGDA_GATEWAY_PORT` | `5175` | 网关宿主端口 | `gateway_manager.py` + compose |
| `CGDA_DATA_MOUNT` | 空 | prod 数据盘 bind mount 源 | compose.prod.yml |
| `CGDA_UID` | 10001 | 容器内运行 UID（Linux 属主对齐） | Dockerfile build-arg |

> 命名理由：launcher 自己的开关统一用 `CGDA_*`，后端进程读的仍走 `BACKEND_*`，
> 避免"launcher 改了但后端没读到"的排查陷阱。

---

## 6. Win10 目标机交接作业指引（裸机态）

> 目标：把服务在那台 Win10 台式机上跑起来，并让接手人能自己维护。
> 每阶段都有**产出**与**验收点**，不要跳过验收直接进入下一阶段。

### 阶段 A —— 源机准备（在当前这台机器上做）

| 要准备 | 说明 |
|---|---|
| 代码 | `git push` 到 `origin/dev` 后由目标机 clone；**记录提交 sha** |
| `.env` 真值 | `Code/backend/.env`（**不入库**，含 API Key / 管理员密码 / CDS Key）→ **安全通道单独交** |
| 部署配置真源 | `Code/backend/deployment.config.json` —— ⚠️ **当前本机该文件不存在**（只有 `.bak.1`）。交接时须确认：目标机是沿用 `.env` 单轨，还是补建该文件（补建则须格式合法，否则 fail-closed 拒启，见 G-G） |
| 机构源映射 | `Code/backend/source_uri_map.json` 从 `.example` 复制并逐键替换（**先补 `.gitignore`，见 G-F**） |
| 密钥台账 | GEE 加密主密钥（64 hex）、`BACKEND_API_KEY`、MinIO 凭据、CDS Key —— 走机构密钥台账，**不进 git、不进聊天记录** |
| 数据盘 | 数据根 / 产物根的实际内容（拷贝或按机构流程重新同步） |
| 依赖配方 | `Code/backend/requirements.txt`（已 pin）+ `requirements-dev.txt` + `Code/algorithms/providers/Python/requirements.txt` |
| 文档 | 本文 + `部署手册与硬约束清单.md` + `Docs/07-工程保障/运维手册.md` |

### 阶段 B —— 目标机环境准备

1. **管理员终端**：Docker Desktop 与执行启动命令的终端都必须以管理员身份运行（硬约束 A1）。
2. **Docker Desktop**：安装 → 启动 → `docker info` 无报错。
   - 若要改镜像存储位置，**先**在 `Settings → Resources → Disk image location` 设好再拉镜像（§5.1）。
   - 内网/慢网先配 `registry-mirrors`（§5.3）。
3. **端口体检**（Windows 特有，必须做）：
   ```bat
   netsh interface ipv4 show excludedportrange protocol=tcp
   ```
   确认 `5175 / 8000 / 8080 / 9100 / 9101 / 16379` **不在**保留段内。
   若被占：最小改动是换 `16379/9100/9101`（改 compose）或 `--frontend-port`；网关 5175 需改代码（§5.4）。
4. **环回可用性**：确认安全软件没有丢环回（历史故障：uvicorn 事件循环挂死、零输出不监听）。
5. **Node 22**：仅当要在目标机 `npm run build`（生成 `dist`）或跑前端 HMR 时才需要。

### 阶段 C —— 代码与数据落地

1. `git clone` → `git checkout dev` → **记录 `git rev-parse --short HEAD`**。
2. 数据盘目录**必须先存在**（C1：不会自动创建根；production 空根拒启）。
3. `Code/frontend/dist` 在 `.gitignore` 内（`Code/frontend/.gitignore:11`），目标机需自行构建：
   ```bat
   cd Code\frontend && npm ci && npm run build
   ```
   （或首次启动时靠 `launch.py start --rebuild-frontend` 自动构建。）

### 阶段 D —— 配置落地

1. 按手册 §6「交付机必改清单（10 项）」逐条改 `Code/backend/.env`。要点：
   `BACKEND_ENV=production`、强 `BACKEND_API_KEY`、数据根/产物根、关 demo/stub 开关、
   显式 `BACKEND_RELOAD=false`、非默认 MinIO 凭据、机构化 `source_uri_map`。
2. 生成 GEE 加密主密钥（64 hex），**非 development 缺则拒启**：
   ```bat
   Env\Python312\python.exe -c "import secrets; print(secrets.token_hex(32))"
   ```
3. **先补 `.gitignore` 再建 `source_uri_map.json`**（G-F）：
   ```
   # .gitignore 追加
   Code/backend/source_uri_map.json
   ```

### 阶段 E —— 启动与验收

```bat
:: 一次性：建立 Python 运行时（Env/ 不入库，必做，见手册 §3 与下文）
:: 官方安装包 3.12.9 → 安装路径填 <repo>\Env\Python312
Env\Python312\python.exe -m pip install --upgrade pip
Env\Python312\python.exe -m pip install -r Code\backend\requirements.txt
Env\Python312\python.exe -m pip install -r Code\backend\requirements-dev.txt
Env\Python312\python.exe -m pip install -r Code\algorithms\providers\Python\requirements.txt
Env\Python312\python.exe -c "import fastapi, rasterio, geopandas, celery; print('deps ok')"

:: 启动
start.bat
Env\Python312\python.exe launch.py status
```

**为什么用官方安装包而不是 venv**：本机 `Env/Python312` 是**完整发行版布局**
（含 `Doc/`、`NEWS.txt`、`*.pdb`，`sys.prefix` 指向该目录，`Lib/site-packages` 595 个包），
即"官方安装包装到仓库内路径"，不是 venv（无 `pyvenv.cfg`）。按同法重建可最大程度复现。
版本必须 **3.12.9**（本机实测 `Python 3.12.9`）。

验收：手册 §8 可勾选清单。至少确认：
`GET /health` 200、`GET /config/about` 正常、`:5175` 首页可开、工作流 dry-run 通过、
`launch.py status` 中 Redis/MinIO/Open-Meteo/Worker/EARLY Gateway 全部就绪。

> **自检提示**：`Env/Python312` 虽在 `.gitignore:2` 被忽略，但 `Env/backend/` 下仍有 **8 个 PowerShell
> 脚本是入库的**（`dev.ps1`、`worker*.ps1`、`redis.ps1` 等）。它们是历史遗留的联调辅助脚本，
> 目标机 clone 后会拿到，但不含运行时——**不要**误以为 `Env/` 可从 git 复现。

### 阶段 F —— 交接材料清单（交给接手人）

| # | 材料 | 位置 | 交付方式 |
|---|---|---|---|
| 1 | 代码 | `origin/dev` @ `<sha>` | git |
| 2 | 后端 `.env` 真值 | `Code/backend/.env` | **安全通道**（不入 git） |
| 3 | 部署配置真源 | `Code/backend/deployment.config.json` | 安全通道；或明确"沿用 .env 单轨" |
| 4 | 机构源映射 | `Code/backend/source_uri_map.json` | 安全通道（先补 gitignore） |
| 5 | 密钥台账 | GEE 主密钥 / API Key / MinIO / CDS | 机构密钥台账 |
| 6 | 数据盘 | 数据根 + 产物根 | 拷贝或重新同步 |
| 7 | 三份文档 | 本文 / 部署手册 / 运维手册 | git（`Docs/04-执行部署/`、`Docs/07-工程保障/`） |
| 8 | 管理员账号 | `BACKEND_ADMIN_USERNAME` / `PASSWORD` | 安全通道 |
| 9 | 启动速查 | 本文 §1.2–1.4 + 手册 §12.7 | 文档 |
| 10 | 回滚索引 | 手册 §9 | 文档 |

### 阶段 G —— 后续切交付态

补齐 G-A…G-E 后，在目标机执行：

```bash
docker build -f Code/backend/Dockerfile -t cgda-backend:$(git rev-parse --short HEAD) .
docker build -f Code/infra/gateway/Dockerfile.web -t cgda-web:$(git rev-parse --short HEAD) .
Env\Python312\python.exe launch.py stop          # 先停裸机态（端口互斥）
Env\Python312\python.exe launch.py start --mode prod
```

切换前必须处理 §3.3 的 upstream 改动，并确认 `BACKEND_ENV=production` 下不开热重载（手册 §12.9）。

---

## 7. 风险与回滚

| 风险 | 触发条件 | 处置 |
|---|---|---|
| `Env/Python312` 重建失败（科学库 ABI 不兼容） | 目标机 Python 小版本不一致 | 严格用 3.12.9；`pip install` 失败先看 `rasterio`/`geopandas` 的 wheel 匹配 |
| 端口被 WinNAT 保留段吞掉 | 目标机 Hyper-V 动态段与默认端口重叠 | 阶段 B 体检；换 16379/9100/9101 或网关端口 |
| 环回被安全软件丢包 | 装了会拦 loopback 的安全软件 | 历史故障复现参考运维手册 §6.3/§9.1 |
| 凭据泄露 | `.env` / `source_uri_map.json` 误提交 | **交接前先补 `.gitignore`**（G-F）；提交前跑手册 §5-B10 扫描 |
| 交付态与裸机态端口冲突 | 两者同时启动 | 手册 §12.8：先 `launch.py stop` 再切 |
| 改镜像存储位置丢 Open-Meteo 数据 | 迁移 data-root 未确认卷 | §5.1 三条后果；迁移后 `docker volume inspect` 复验 |
| `deployment.config.json` 格式损坏导致拒启 | 手工编辑 / 半应用 | 恢复指引在拒启错误信息内（`.bak.1/.2/.3` 轮换） |

**回滚**：裸机态回退 = `launch.py stop` + `start.bat`；交付态回退 = `CGDA_TAG=<old-sha> docker compose up -d`。
数据根不变则工作流状态连续（手册 §12.8）。

---

## 8. 待确认项

| # | 项 | 影响 | 建议 |
|---|---|---|---|
| U1 | 目标机 Win10 是否已有 Python / Node / Docker Desktop？版本？ | §6-B 工作量 | 交接前先问，或先跑一次环境探测 |
| U2 | 目标机网络：能否直连 Docker Hub / `public.ecr.aws`？ | §5.3 走加速器还是离线包 | 交接时确认 |
| U3 | 目标机磁盘：是否已有 D 盘等非系统盘做 data-root 与数据盘？ | §5.1 | |
| U4 | 是否补建 `deployment.config.json`（现为空缺） | 配置真源单轨/双轨 | 建议先沿用 `.env` 单轨，避免引入新变量 |
| U5 | 交接对象是谁、是否需要长期运维？ | §6-F 材料深度 | |
| U6 | 是否要求目标机也能改代码（开发态）？ | 是否需要 Node + HMR | 若纯交付，可只装 Python |

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-09-16 | v0.1 | 首版：启动脚本现状盘点（含三态支持矩阵与 7 项缺口）、裸机先行选型、交付态要点、三态统一进 launcher 设计、Docker 自定义清单、Win10 交接六阶段作业指引、风险与回滚 |

---

*维护约定：本文为**执行侧**文档，不复制真源。三态支持的实现状态变化时，同步更新 §1.5 与 §1.6；
Docker 自定义项落地后，§5.4 的"可否自定义"列须同步。*
