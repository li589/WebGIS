# 阶段 3/6：访问模式扩展与存量迁移 — 集成计划

> 这是对 toasty-aurora-turing.md 主计划的补充，聚焦阶段 3 的实现路径。
> 已完成的产出：remote_source_migration.py（迁移函数 + 内置映射表 + 幂等 KV）。
> 待完成：启动钩子 + 手动迁移 API + remote_sources 表 ALTER 验证 + 测试。

---

## 1. 已完成（本次会话）

| 文件 | 状态 |
|------|------|
| `Code/backend/app/services/remote_source_migration.py` | ✅ 已写入：`migrate_legacy_remote_sources(dry_run/safe)` + `_BUILTIN_DATASET_HINTS` + `_infer_dataset` + 幂等 KV（`remote_source_migration_kv` 表） |
| `Code/backend/app/services/remote_source_registry.py` | ✅ `_init_schema` 已加 `_ensure_column`（access_mode / archived 两列，幂等 ALTER） |

## 2. 待集成（执行计划）

### 2A. main.py 启动钩子（L95 之后）

**插入点**：`main.py` L95（`sync_algorithm_datasets` except 块之后），加：
```python
    # 远程数据源存量迁移：文件级条目 → 数据集授权/站点兼容（失败仅告警）
    try:
        from app.services.remote_source_migration import migrate_legacy_remote_sources
        migration_report = migrate_legacy_remote_sources()
        if migration_report.get("migrated_to_grants") or migration_report.get("upgraded_site_compatible"):
            logger.info(
                "[RemoteSourceMigration] startup: %d grants, %d site_compatible, %d legacy",
                migration_report["migrated_to_grants"],
                migration_report["upgraded_site_compatible"],
                migration_report["kept_legacy"],
            )
    except Exception:
        logger.exception("Failed to migrate legacy remote sources on startup")
```

**前置条件**：main.py 需 `import` remote_source_migration（延迟导入对齐 dataset_registry_service 范式）。

### 2B. 手动迁移 API（config_routes.py，L1176 之后）

参照 `/config/data-source/datasets/rescan`（L1099-1106）范式：

```python
class MigrationReportResponse(BaseModel):
    dry_run: bool
    total: int
    migrated_to_grants: int
    upgraded_site_compatible: int
    kept_legacy: int
    already_done: bool
    details: list[dict[str, Any]]
    safe_mode: bool

@router.post(
    "/remote-sources/migrate-legacy",
    response_model=MigrationReportResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def migrate_legacy_remote_sources_endpoint(dry_run: bool = False, safe: bool = False):
    """手动重跑存量迁移（dry_run/safe 查询参数）。"""
    from app.services.remote_source_migration import migrate_legacy_remote_sources as _migrate
    return await anyio.to_thread.run_sync(lambda: _migrate(dry_run=dry_run, safe=safe))
```

**依赖**：`anyio.to_thread.run_sync`（同步函数线程化）+ `require_config_management_access`。

### 2C. 契约模型（config_contracts.py）

新增（复用 RemoteDatasetGrant 之外的独立响应）：

```python
class MigrationReport(BaseModel):
    dry_run: bool
    total: int
    migrated_to_grants: int
    upgraded_site_compatible: int
    kept_legacy: int
    already_done: bool
    safe_mode: bool
    details: list[dict[str, Any]] = Field(default_factory=list)
```

### 2D. 测试（Test/backend/）

新文件 `test_remote_source_migration.py`：

| 测试用例 | 说明 |
|----------|------|
| `test_infer_dataset_builtins` | `_infer_dataset` 对各门户路径 → 正确 dataset_key/path_prefix |
| `test_infer_dataset_generic_shortname` | 通用短名规则：首段 CMR 短名形态 |
| `test_infer_dataset_fallback` | 无法推断 → None |
| `test_migrate_dry_run_no_writes` | dry_run=True 不改 remote_sources/grants |
| `test_migrate_site_compatible_upgrades` | remote_path='' → access_mode='site_compatible' |
| `test_migrate_grants_created` | 内置路径推断成功 → 写入 remote_dataset_grants + archived |
| `test_migrate_kept_legacy_on_fail` | 推断失败 → kept_legacy，不归档 |
| `test_migrate_safe_mode` | safe=True → 推断失败的门户升级 site_compatible |
| `test_migrate_idempotent` | 二次跑 already_done=True |
| `test_migrate_alter_schema` | `_ensure_column` 幂等：第二次调用不报错 |

### 2E. 验证清单

1. `pytest Test/backend/test_remote_source_migration.py` → 全绿
2. `pytest Test/backend/test_remote_source_registry.py` → 回归（ALTER 不破坏既有）
3. 手动 dry-run：`POST /config/remote-sources/migrate-legacy?dry_run=true` → 报告
4. 手动执行：`POST /config/remote-sources/migrate-legacy?dry_run=false&safe=true`
5. `main.py` 启动后日志检查迁移输出

---

## 3. 关键文件清单（本次修改）

| 文件 | 改动 |
|------|------|
| `Code/backend/app/main.py` | L95 后加启动迁移钩子（try/except 块） |
| `Code/backend/app/services/service_restart.py` | 无改动 |
| `Code/backend/app/api/config_routes.py` | 加 `MigrationReport` 契约 + `POST /remote-sources/migrate-legacy` 端点 |
| `Code/shared/contracts/config_contracts.py` | 加 `MigrationReport` 模型 |
| `Test/backend/test_remote_source_migration.py` | 新建：10 个测试用例 |
| `Code/backend/app/services/remote_source_migration.py` | 无改动（已完成） |
| `Code/backend/app/services/remote_source_registry.py` | 无改动（ALTER 已完成） |
