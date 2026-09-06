# 2026-08-15 门户下载表单 / ssh_sync profile 收口

## 状态

- `dev` 上近期已合入：远程存储 profile 解析（algo）、门户表单 HttpOpenDataForm / PortalCredHint / SshSyncForm 动态服务器（FE）。
- 本轮复查修复：
  1. `ssh_sync` 原先只读 `date_start`/`date_end`，与表单 `start_date`/`end_date` 不一致 → 日期过滤失效；现双向兼容，并下传 `file_filter`。
  2. `HttpOpenDataForm` 在门户目录加载失败时空目录误报「未知预设」→ 仅在目录有条目时校验。
  3. `test_ssh_sync_profile_resolution.py` 修正算法包 `sys.path`（补 `Code/algorithms/providers/Python`），并补日期/过滤用例。
- 文档：`Docs/03-规范协议/远程存储接入说明.md`、`.ai/skills/multi-source-data-ingestion.md` 已对齐工作流下载节点与设置页「远程与存储」。

## 验证

```
Env/Python312/python.exe -m pytest Test/backend/test_ssh_sync_profile_resolution.py -q
# 8 passed
```

## 联调

Beat 曾退出；全量 `launch.py restart --rebuild-frontend --clean-cache` 后确认 `launch.py status`。
