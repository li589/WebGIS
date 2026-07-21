# Data-sync — 数据与运行隔离

| 栈 | 路径 | 职责 |
|----|------|------|
| **运行** | `Code/backend/docker-compose.yml`（`-p backend`） | Redis、MinIO、**`cgda-open-meteo` API**（长期运行） |
| **数据** | `Code/infra/data-sync/`（`-p data-sync`） | 一次性 `run --rm` 任务（当前仅 `open-meteo-sync`；可继续加） |

原则：核心数据只进 **Docker named volume**（本机 Docker Desktop → `I:\Docker\DockerDesktop`），不进项目目录 / D:。

## 当前任务

| Compose service | 写入 volume | 读取方 |
|-----------------|-------------|--------|
| `open-meteo-sync` | `backend_open-meteo-data` | `cgda-open-meteo` |

## 同步

Windows:

```powershell
cd Code\infra\data-sync
Copy-Item .env.example .env   # 首次
# 建议先: docker compose -p backend up -d   （创建 volume + 启 API）
.\sync.ps1                    # 默认 open-meteo-sync
.\sync.ps1 open-meteo-sync    # 显式任务名
.\list-jobs.ps1               # 列出可跑的 sync profile 服务
```

Linux / macOS:

```bash
cd Code/infra/data-sync
cp -n .env.example .env
./sync.sh
./sync.sh open-meteo-sync
./list-jobs.sh
```

Celery Beat / 设置页「立即同步」/ 一键：`python launch.py sync`（默认任务 `open-meteo-sync`，队列 `weather-batch`）。

## 如何添加更多数据任务

1. 在 `docker-compose.yml` 的 `services:` 下按模板新增 service（`profiles: ["sync"]`，`restart: "no"`）。
2. 数据用 **named volume**（可 `external: true` 与运行栈共用，或本文件新建）。
3. 需要时增加 `.env.example` 变量与 `.\sync.ps1 <service-name>` 用法。
4. 若需自动调度：仿 `app/tasks/open_meteo_sync_tasks.py` 再加 Celery 任务指向新 service。

不要把长期 API 放进本 compose。

## 清理

```powershell
.\prune-cache.ps1   # 仅应用侧 weatherengine 缓存

# 清空 Open-Meteo 库（需重新 sync）
docker compose -p backend stop open-meteo
docker volume rm backend_open-meteo-data
```
