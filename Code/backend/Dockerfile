# syntax=docker/dockerfile:1
# ══════════════════════════════════════════════════════════════════════════
# CGDA 后端镜像 —— 一镜像三角色：fastapi / worker / beat
#   三角色共用本镜像，仅启动命令不同（见 compose.prod.yml）。
#
# 构建上下文 = 仓库根（必须；需 COPY Code/algorithms 与 Code/shared）
#   docker build -f Code/backend/Dockerfile -t cgda-backend:$(git rev-parse --short HEAD) .
#
# 硬约束（Docs/04-执行部署/部署手册与硬约束清单.md §12.2）：
#   镜像内**必须**保持 Code/{backend,algorithms,shared} 兄弟目录结构，
#   工作目录 /srv/Code/backend。依据：
#     · start_fastapi.py:18-24 / start_celery_worker.py:6-13
#       —— 把 backend_root.parent（即 Code/）插入 sys.path
#     · app/core/config.py:42-44
#       —— DEFAULT_PYTHON_PROVIDER_ROOT = BACKEND_ROOT.parent/"algorithms"/…
#   ⇒ 不要把 backend 单独 COPY 到 /app，否则算法 provider 解析失败。
#
# 构建上下文排除规则见仓库根 .dockerignore（密钥 / .env / 数据盘绝不入镜像）。
# ══════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim-bookworm

# 仓库唯一 Python 运行时为 Env/Python312（3.12.9）⇒ 基础镜像必须同为 3.12.x，
# 否则 C 扩展 wheel 的 ABI 与联调环境不一致。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# ── 系统工具 ─────────────────────────────────────────────────────────────
#   libsqlite3-mod-spatialite : SpatiaLite 扩展（空间叠加 / SQLite 空间函数）
#   gdal-bin                  : GDAL CLI（FY 提取链等）
#   libeccodes0               : cfgrib / herbie-data 读 GRIB2 需系统 eccodes
#   p7zip-full                : 7z CLI，archive_safe.py::_find_7z 的 Linux 分支
#   curl                      : compose healthcheck
#   tini                      : PID 1 回收僵尸进程（Celery prefork 会 fork 子进程）
#
# TBD（见手册 §12.10-T1）：unrar —— archive_safe.py::_find_unrar_tool 优先查
#   Code/backend/vendor/unrar/linux-x64/unrar（该目录在 .gitignore 内，克隆后不存在），
#   其次查 PATH 的 unrar。Debian 主源的 unrar-free 对 RAR5 支持有限，故本镜像
#   先只装 7z；RAR5 导入需另装 unrar（contrib/non-free）或把 vendor 二进制打进镜像。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libsqlite3-mod-spatialite \
        gdal-bin \
        libeccodes0 \
        p7zip-full \
        ca-certificates \
        curl \
        tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/Code/backend

# ── Python 依赖（独立层：只要 requirements.txt 不变就命中缓存）──────────────
COPY Code/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── 源码：保持 Code/ 兄弟结构（硬约束，勿拆）─────────────────────────────
COPY Code/backend/    /srv/Code/backend/
COPY Code/algorithms/ /srv/Code/algorithms/
COPY Code/shared/     /srv/Code/shared/

# ── 非 root 运行 ────────────────────────────────────────────────────────
# Linux 上数据盘属主须与容器内用户一致，否则产物写不进去（手册 §12.4-2）。
# 对齐方式：--build-arg CGDA_UID=$(id -u -- 宿主数据盘属主)
ARG CGDA_UID=10001
RUN useradd -u ${CGDA_UID} -U -m -s /usr/sbin/nologin cgda \
 && mkdir -p /srv/Code/backend/.data /data/geo \
 && chown -R cgda:cgda /srv/Code /data \
 && (chmod +x /srv/Code/backend/vendor/unrar/linux-x64/unrar 2>/dev/null || true)
USER cgda

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
# 默认角色 fastapi；worker / beat 由 compose 覆盖 command（见 compose.prod.yml）
CMD ["python", "start_fastapi.py"]
