# 基础设施安全审计修复计划（nginx 页面定向 / API 文档暴露 / 供应链）

> 审计框架：腾讯云鼎实验室 Skill 安全审计方法论（Malicious/Suspicious/Benign 分级 + 静态分析）
> 仓库：D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system · 分支 dev

## 审计结论摘要

**良好项（不动）**：CORS 白名单 fail-closed、后端安全响应头中间件、500 通用兜底（无堆栈泄露）、cookie httponly+lax+secure、限流防 XFF 伪造、SPA 错误边界/404 catch-all/会话过期处理、维护模式开关机制、data-sync .env 已 gitignore 且无凭据。

**发现（全部 Suspicious 级，无 Malicious）**：
1. **P0 页面定向不完整**（nginx.conf）：`error_page 502 503 504 /50x.html`（L55/L71）仅接管 nginx 自生错误；`location /` 缺 500/501/502/504/505/413 定向；`client_max_body_size 200m` 超限时裸 413
2. **P1 安全头继承丢失**（nginx.conf L43-47）：maintenance location 内 add_header 使 server 级 CSP/nosniff/Referrer-Policy 全部失效（nginx 继承规则）
3. **P1 API 文档暴露**：/docs /redoc /openapi.json 全环境开放（main.py L159-165 未传 docs_url/redoc_url）
4. **P3 供应链**：gateway README 列第三方镜像加速 URL 清单；data-sync 镜像 `:latest` 未固定

**用户决策**：端口保持 0.0.0.0（不做收紧）；文档仅禁交互页（openapi.json 保留）；供应链两项都做。

---

## 阶段 A（P0）：nginx 错误页全覆盖 + 安全头继承修复

**核心决策**：API 反代 location **不开** `proxy_intercept_errors`——应用层错误 JSON（request_id/error_code/Retry-After）原样透传，由前端 `_http.ts` 统一解析；error_page 仅接管 nginx 自生错误。error_page 不跨级继承，各 location 显式声明完整集合。

### A1. 新增 `Code/infra/gateway/snippets/security-headers.conf`
安全头统一 include 片段（CSP/X-Content-Type-Options/Referrer-Policy，内容 = 现 nginx.conf L35-37 三行 + `always`）。原理：location 级出现任一 add_header 即丢失 server 级安全头 → 含 add_header 的 location 必须 include 本片段。

### A2. 新增 `Code/infra/gateway/maintenance/html/413.html`
复用 50x.html 样式，文案「上传内容超过 200 MB 限制，请压缩数据或分块上传」。

### A3. 修改 `Code/infra/gateway/nginx.conf`
- server 级：add_header 三行改为 `include /etc/nginx/snippets/cgda/security-headers.conf;`
- `location = /maintenance.html`：include 片段 + 保留 Cache-Control/Retry-After（修复继承丢失）
- `location = /50x.html`：加 `include 片段` + `add_header Cache-Control "no-store" always;`
- 新增 `location = /413.html`：internal + root maintenance/html + include 片段 + no-store
- 新增命名 location `@json413`：include 片段 + `default_type application/json` + `return 413 '{"detail":"上传内容超过 200 MB 上限，请压缩数据或使用分块上传"}'`（API 上传超限走 JSON 保持前端错误契约）
- 两个 API location（L54/L70）：现有 `error_page 502 503 504 /50x.html;` 后加 `error_page 413 @json413;`
- `location /`（L82-89）：加 `error_page 500 501 502 504 505 /50x.html;` + `error_page 413 /413.html;`（保留现有 503→maintenance 与 try_files）

### A4. 修改 `Code/infra/gateway/docker-compose.yml`
volumes 加 `- ./snippets:/etc/nginx/snippets/cgda:ro`（端口绑定保持 0.0.0.0 不变）。

### A5. 验证
```bash
docker exec cgda-gateway-nginx nginx -t && docker exec cgda-gateway-nginx nginx -s reload
```
curl 验收清单：①`/` → 200 text/html；②深链 → 200（try_files 不破坏）；③`/maintenance.html` 响应头含 CSP+nosniff+Referrer-Policy+Cache-Control+Retry-After 共 5 类（继承修复）；④停后端 → `/health` 502 text/html 含 50x 页；⑤后端运行 → API 404 仍为 JSON+request_id（透传不破坏）；⑥POST 210MB → 413 application/json 含 detail；⑦maintenance/on 开关回归；⑧50x 响应含 Cache-Control: no-store。
（容器未跑时离线校验：`docker run --rm -v <nginx.conf>:/etc/nginx/nginx.conf:ro -v <snippets>:... -v <maintenance>:... nginx:1.27-alpine nginx -t`）

---

## 阶段 B（P1）：/docs /redoc 按环境禁用（openapi.json 保留）

### B1. `Code/backend/app/core/config.py`
新增推导函数 + Settings 字段（frozen dataclass 字段默认值 import 时求值——测试必须用 `replace(settings, docs_enabled=…)` 显式构造变体，只改 env 无效）：
```python
def _default_docs_enabled() -> bool:
    raw = os.getenv("BACKEND_DOCS_ENABLED")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    env = (os.getenv("BACKEND_ENV") or "production").lower()
    return env in {"development", "dev"}

# Settings 内：
docs_enabled: bool = _default_docs_enabled()  # production/test 默认 False
```

### B2. `Code/backend/app/main.py` create_app（L159-165）
```python
docs_url="/docs" if settings.docs_enabled else None,
redoc_url="/redoc" if settings.docs_enabled else None,
# openapi_url 不传（保持 /openapi.json 开放——用户决策：供工具调用）
```

### B3. 新增 `Test/backend/test_docs_exposure.py`
- disabled 时 /docs /redoc 404、/openapi.json 200
- enabled 时三者 200
- `_default_docs_enabled` 推导矩阵参数化（production→False / development→True / BACKEND_DOCS_ENABLED 覆盖双向）
- fixture 模式参照 test_error_handlers.py：`monkeypatch.setattr("app.main.settings", replace(settings, docs_enabled=…))`

### B4. 验证
`pytest Test/backend/test_docs_exposure.py` + `cd Code/frontend && npm run check:openapi`（openapi.json 保留，F14 闸门零影响）+ 后端全量回归。

---

## 阶段 C：取消（用户决策保持 0.0.0.0）
gateway README「已知暴露面」一节补一行记录：5175 端口 LAN 可见为已知接受的风险（内网部署 + 无 TLS 由部署拓扑承担）。

---

## 阶段 D（P3）：供应链加固

### D1. `Code/infra/gateway/README.md` L21-41 镜像加速段重写
保留 daemon.json 配置方法；删除 docker.1ms.run/daocloud/xuanyuan/rat.dev 等具体 URL 清单，改为「自行选择可信任的镜像源；第三方 mirror 无签名校验存在投毒风险，生产建议直连 Docker Hub 或自建 registry」；「拉取后打同名 tag」手段标注仅限隔离开发机。

### D2. `Code/infra/data-sync/docker-compose.yml` L27 镜像 digest 固定
先取证：`docker inspect --format '{{index .RepoDigests 0}}' <image>` → 改为
`image: ${OPEN_METEO_IMAGE:-public.ecr.aws/w5w8t1y7/openmeteo@sha256:<digest>}`（保留覆盖变量逃生门）。

---

## 文档同步
- `Code/infra/gateway/README.md`：错误页矩阵表（状态码→页面/JSON，@json413 决策一句话）、snippets 目录说明、已知暴露面记录
- `Code/infra/gateway/maintenance/README.md`：补 413.html 行 + 「API 上传超限返回 JSON」说明
- 后端 README 环境变量节：补 `BACKEND_DOCS_ENABLED`（默认推导 + 逃生门）

## 提交策略
4 个独立提交（A→B→D + 文档并入各阶段）：A `feat(infra): gateway 错误页全覆盖与安全头继承修复`；B `feat(security): API 交互文档按环境禁用`；D `chore(supply-chain): 镜像来源指引与 digest 固定`。提交前置 `env -u ACC_PRODUCT_CONFIG_V3`；推送后手动修正 origin/dev loose ref（已知坑）。

## 明确不做
proxy_intercept_errors（API JSON 透传是决策非遗漏）、端口收紧（用户决策）、CORS/安全头中间件/错误兜底/cookie/限流（已良好）、前端错误处理链（已完善）。
