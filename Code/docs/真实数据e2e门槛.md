# 真实数据 e2e 门槛（Phase 3）

目标：证明「提交 → Celery → artifact/view → 前端可展示」可在**真实课题组数据集**上跑通，而不是 lab_output 合成结果。

## 前置条件

1. `BACKEND_WORKFLOW_EXECUTOR=celery`，Redis/worker 在线
2. `BACKEND_DATA_ROOT` / `BACKEND_OUTPUT_ROOT` 指向可读写目录
3. 至少一条本地可 materialize 的数据源（`file://` 或已配置的 MinIO）
4. 选定图层：优先 `ndvi` 或土壤水分 Python module（非 `lab-output`）

## 门槛步骤

```text
1. GET /layers → 目标图层 run_readiness != blocked
2. POST /workflow-runs（带 algorithm_request / python_provider 字段）
3. 轮询 GET /workflow-runs/{id}/events 至 succeeded|failed
4. GET /workflow-runs/{id}/view → 含 artifact_refs 或 result 链接
5. GET /artifacts/{id} 或 preview 可访问
6. 前端激活同 catalogId 图层可看到结果或明确错误态
```

## 自动化占位

当前仓库以契约与 bridge 单测为主。完整 e2e 需数据挂载后在 CI 或本机执行：

```powershell
cd Code/backend
$env:PYTHONPATH="..;app/gee/core/src"
# 在具备真实数据时新增 tests/test_real_data_e2e.py 并取消 skip
python -m pytest tests/test_workflow_request_resolver.py -q
```

未挂载数据时，禁止把 `lab-output` 绿测当作生产就绪证据。
