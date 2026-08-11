# 审查修复执行记录（B1–B4，2026-08-09）

依据：[code-review-fullstack-2026-08-09.md](./code-review-fullstack-2026-08-09.md)

## B1 — P0 天气同步鉴权

| 项 | 状态 |
|----|------|
| `POST /weather/sync/trigger` + `require_write_access` | ✅ |
| `_WRITE_LIMITED_PREFIXES` 含 `/weather/sync` | ✅ |
| `test_config_security` / `test_rate_limit_coverage` | ✅ |
| OpenAPI → `gen:types` → `check:openapi` | ✅ |

## B2 — P1 鉴权 / 限流 / 前端读 Key

| 项 | 状态 |
|----|------|
| B2.1 `_direct_client_host` dev bypass（防 XFF 伪造） | ✅ |
| B2.2 runtime/cleanup GET + `require_config_read_access` | ✅ |
| B2.2 FE `sensitiveGet` / `requestConfigJson` / `listNodeCaches` | ✅ |
| B2.3 写限流扩展 `/cleanup` `/runtime` `/workflow-timers` | ✅ |
| B2.4 `config_routes` doc + `AGENTS.md` | ✅ |

## B3 — P1 SSRF

| 项 | 状态 |
|----|------|
| 代理场景 fail-closed（`allow_proxy=False` 默认） | ✅ |
| `safe_urlopen` 覆盖面（source_fetcher / weather providers / client） | ✅ |
| `test_ssrf` / `test_fetch_gateway` / `test_remote_sources` | ✅ |

## B4 — P2 工程债

| 项 | 状态 |
|----|------|
| B4.1 `settings-api` 内联 body → gen 类型 | ✅ |
| B4.2 pre-commit ruff → `algorithms/providers/Python` + format 16 文件 | ✅ |
| B4.3 ESLint warnings 36 → **16**（wind console 收敛；measure `any` 修复） | ✅ |
| B4.4a `display-projection.ts` + `result-adapter` helpers | ✅ |

## 验证（2026-08-09）

```text
pytest Test/backend/test_config_security.py Test/backend/test_config_contracts.py \
  Test/backend/test_rate_limit_coverage.py Test/backend/test_ssrf.py \
  Test/backend/test_fetch_gateway.py → 64 passed

pytest Test/algorithms/ → 328 passed

cd Code/frontend && npm run test -- layers weather-tile settings api-config → 87 passed
npm run lint → 0 errors, 16 warnings
npm run build → OK
npm run check:openapi → OK
```

## 主要文件

- BE: `weather_router.py`, `deps.py`, `rate_limit.py`, `runtime_router.py`, `cleanup_router.py`, `ssrf.py`, `config_service.py`, `source_fetcher.py`, `weatherengine/client.py`
- FE: `_http.ts`, `api-config.ts`, `runtime-api.ts`, `settings-api.ts`, `display-projection.ts`, `result-adapter.ts`, `perf-probe.ts`
- 配置: `.pre-commit-config.yaml`, `AGENTS.md`
