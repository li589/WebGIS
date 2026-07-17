# 真实数据 e2e 门槛（Phase 3）

目标：证明「提交 → Celery → artifact/view → 前端可展示」可在**真实课题组数据集**上跑通，而不是 lab_output 合成结果。

本地盘（`file://` / `BACKEND_DATA_ROOT`）若已有多条图层跑通，本文件以 **NAS SMB/SFTP + 远程存储 profile** 作为下一道门槛。

## 前置条件（通用）

1. `BACKEND_WORKFLOW_EXECUTOR=celery`，Redis/worker 在线  
2. `BACKEND_DATA_ROOT` / `BACKEND_OUTPUT_ROOT` 指向可读写目录  
3. 选定图层：优先已在本地跑通的 `smap-soil` / `ndvi` 等（**非** `lab-output`）  
4. **跑 Celery 的机器**必须能访问数据源（本机路径或 NAS 网段）

## A. 本地路径门槛（已具备时跳过）

```text
1. GET /layers → 目标图层 run_readiness != blocked
2. POST /workflow-runs（algorithm_request / python_provider）
3. 轮询 GET /workflow-runs/{id}/events 至 succeeded|failed
4. GET /workflow-runs/{id}/view → artifact_refs 或 result 链接
5. GET /artifacts/{id} 或 preview 可访问
6. 前端激活同 catalogId 图层可见结果或明确错误态
```

## B. NAS SMB/SFTP 门槛（多机正式路径）

### B.1 多机拓扑

```text
[前端] → [API] → Redis → [Celery Worker]
                           ↓ materialize（sftp/smb）
                         NAS 文件服务器
                           ↓ 写出
                         BACKEND_OUTPUT_ROOT / MinIO artifacts
```

要点：

- 凭证库是 **API/Worker 本机 SQLite**（`workflow_state/remote_storage_credentials.sqlite3`）  
- 加密密钥与 GEE 相同：`BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY`  
- **每台会 materialize 的进程**都要能读到同一份凭证库（共享盘挂载同一路径，或各机重建相同 profile）并使用**相同加密 key**  
- `BACKEND_REMOTE_MAX_BYTES`：大 HDF/GeoTIFF 默认 512 MiB 不够时调高（例如 `8589934592` = 8 GiB）

### B.2 配置 Profile

1. 设置页 → **远程存储**，或 `PUT /config/remote-storage/{profile_id}`（需 `X-API-Key`）  
2. SMB 必填 **默认 Share**；SFTP 内网可勾选「自动接受主机密钥」  
3. 点 **测试**：  
   - 留空 URI → 只测连通性（SMB 测到 share 根）  
   - 填完整对象 URI → `stat` 该文件（推荐 e2e 前做）  

示例 URI：

```text
smb://192.168.1.10/Geograph/SMAP/SMAP_L3_SM_P_20220101.h5?cred=nas-lab
sftp://nas.lab/data/SMAP/SMAP_L3_SM_P_20220101.h5?cred=nas-lab
```

也可省略 `?cred=`，按 host+protocol 自动匹配已启用 profile。

### B.3 把远端 URI 接到图层（不改坏本地候选）

环境变量 `BACKEND_REMOTE_LAYER_DATA_URIS`（JSON）会把远端 URI **插到**对应 layer 的 `default_data_access_sources` **最前面**，本地路径仍保留作回退：

```powershell
# 示例：用已本地跑通的 smap-soil，改走 NAS 上同一文件
$env:BACKEND_REMOTE_LAYER_DATA_URIS = @{
  "smap-soil" = @{
    "SMAP_SPL3SMP_E" = @(
      "smb://192.168.1.10/Geograph/SMAP/SMAP_L3_SM_P_20220101.h5?cred=nas-lab"
    )
  }
} | ConvertTo-Json -Compress -Depth 5

$env:BACKEND_REMOTE_READINESS_PROBE = "true"   # 可选：就绪时短超时 probe 连通性
$env:BACKEND_REMOTE_MAX_BYTES = "8589934592"   # 按文件体积调
```

重启 API / Worker 后：

```text
1. GET /layers → smap-soil 的 notes 含「已注入远端数据源候选」
2. run_readiness != blocked（凭证可解析；probe=true 时连通性 OK）
3. POST /workflow-runs → Worker materialize 远端文件落盘后跑算法
4. events → succeeded；view / artifacts / 前端展示同 A
```

### B.4 语义澄清（避免误判）

| 概念 | 含义 |
|------|------|
| 图层 `run_readiness` | URI 合法 + 凭证可解析（+ 可选连通性 probe）。**不保证**对象已下载 |
| materialize `ready` | 任务执行时远端文件已落到 worker 本地缓存后才标 ready |
| 对象不存在 | 默认就绪检查**不会**因缺文件而 blocked；会在提交后 materialize 失败。用设置页「测试对象 URI」提前验证 |

### B.5 推荐验收切片

选 **单日 / 单文件**（已在本地跑通过的同一产品），先 NAS 拉通，再扩批量。不要一次 materialize 整个 share。

## 自动化占位

当前仓库以契约与 bridge 单测为主。完整 e2e 需数据挂载后在本机或专用 runner 执行：

```powershell
cd Code/backend
$env:PYTHONPATH="..;app/gee/core/src"
# 无 NAS 时保持 skip；有 profile + URI 后新增 tests/test_real_data_e2e.py
python -m pytest tests/test_remote_sources.py tests/test_layer_remote_uris.py -q
```

未挂载远端数据时，禁止把 `lab-output` 或仅本地绿测当作「多机 NAS 生产就绪」证据。

## 相关文档

- `Doc/远程存储接入说明.md` — scheme、凭证、多机同步  
- `Doc/工程收口仪表盘.md` — Phase 勾选  
- `Tools/DATA_PLANNING.md` — NAS / 本地数据集清单  
