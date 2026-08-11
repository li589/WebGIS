# CGDA dev 分支 CI 全绿收口报告

**日期**：2026-08-09
**工作流**：工作流 4（部署前检查 Go/No-Go 的 CI 验证子集）
**参与成员**：主理人甄宇航（编排与验证）、Cody（代码审查，Phase 2 修复）、Tessa（测试专家，Phase 2 测试）

---

## 📌 TL;DR（执行摘要）

- 目标：将 Phase 2 代码审查修复（`75136d6`/`5fc2b9d`）推上 `dev` 并让 CI 全绿。
- 结果：**CI 9 个 job 全部 success**（pre-commit / pytest / pytest (algorithms) / vitest / build / check:openapi / check:catalog / security scan / gen:types）。
- 过程：**6 轮修复、8 个新提交**，全部为 CI 环境/依赖/跨平台问题，无 Phase 2 业务代码回归。
- 后端 pytest **688 passed**（与本地一致）、覆盖率 55.74%（门槛 50%）；算法 **326 passed, 1 skipped**。
- 剩余风险：3 项低风险已知局限（见文末），不阻塞。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟢 通过（CI 全绿，可合入/发布流程继续） |
| 阻塞项数量 | 0 |
| 关键行动项 | 4 条（见行动清单） |
| 建议下一步 | 由人类负责人复核本次 8 个提交；之后可正常走 PR/合并流程 |

---

## 🔍 修复历程（6 轮，8 个提交）

> 起点：`5fc2b9d` 推送后 CI 在 `pre-commit` job 的 `npm ci` 阶段即失败——该失败**与 Phase 2 业务代码无关**，是仓库长期存在的 CI 基础设施/依赖声明漂移，此前被 `npm ci` 挡在门外从未暴露。

| # | 提交 | 根因 | 修复 |
|---|------|------|------|
| 1 | `d5ad133`（用户侧合并） | `package.json` 引用 `file:datapool-guangdong.geojson-1.0.1.tgz` 本地 tarball，**从未入库且已从磁盘消失**，`npm ci` 无法解析 | 改为公开 npm 注册表依赖 `@datapool/guangdong.geojson@1.0.1`（版本一致、数据字节级一致，经 diff 验证无行为变化）；lockfile `resolved` 指向 npmjs.org（CI 默认注册表） |
| 2 | `a6e3137` | `trailing-whitespace` 钩子命中 3 个脚本文件的尾随空白（此前被 npm ci 失败掩盖） | `Test/debug/diag_env.py`、`Test/standalone/test_config.py`、`Tools/start_services.py` 清理尾随空白 |
| 3 | `aec8c5e` | 后端 requirements **未声明 `networkx`/`rasterio`**（代码直接 import）；算法 job 未安装 pytest（exit 127）；omega 测试 `_PROVIDER_ROOT` 路径少了 `Code` 段 | requirements.txt 补 `networkx>=3.0`、`rasterio>=1.3.10,<2`；ci.yml 算法 job 补 `pip install pytest pytest-cov`；修正测试路径计算 |
| 4 | `b0872bf` | 后端缺 `pydantic-settings`；**算法包自有 requirements.txt（numba/xarray 等）未在 CI 安装** | requirements.txt 补 `pydantic-settings>=2.0`；pytest / pytest-algorithms / check:openapi 三个 job 统一加装 `Code/algorithms/providers/Python/requirements.txt` |
| 5 | `1895e88` | 后端 GEE 代码直接 `import ee` 但缺 `earthengine-api`；**算法包 `detect_source_kind` 不识别 POSIX 绝对/相对路径**（仅识别 Windows 盘符与 file://，Linux 下 `/tmp/x.csv` 被归为 `blob` → `local_path` 为空 → 全部适配器测试失败） | requirements.txt 补 `earthengine-api>=0.1.390`；`detect_source_kind` 对无 scheme 路径判定为本地文件（8 用例本地验证通过、scheme 无回归） |
| 6 | `5183c37` | `_as_file_uri` 用 `Path.as_uri()` 转换 Windows 盘符路径，Linux 下 `is_absolute()` 为 False → `preview_url` 为 None；算法 requirements 缺 `matplotlib`（preview PNG 静默失败）；gldas 测试未先同步 system seeds（CI 全新 data root 查不到定义） | `_as_file_uri` 对 Windows 风格路径手工构造 `file:///D:/...`；requirements.txt 补 `matplotlib>=3.8`；gldas 测试先 `_ensure_dirs()` 同步 |
| 7 | `c9c6e76` | `resumable_upload` 并发竞态：`upload_chunk_by_index` 在锁**外**读取 meta.json，而 `_save_meta` 非原子写 → 并发上传同索引时读到半写文件 → `JSONDecodeError` | 锁外不再读文件（直接派生 dest 路径）；`_save_meta` 改原子写（临时文件 + `os.replace`）。本地 3×4 用例通过 |

---

## ✅ 行动清单

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|---------|--------|---------|
| 1 | 人类负责人复核 8 个提交（尤其 `d5ad133` 依赖源变更与 `c9c6e76` 并发修复） | 人类工程负责人 | P1 | 合并前 |
| 2 | 前端 `node_modules` 已在后台恢复中（排查期间曾被本地 `npm ci` 清空）；完成后确认 `npm run dev` 可启动 | 主理人/用户 | P1 | 本次会话内 |
| 3 | 后续新增后端/算法依赖时同步更新两处 requirements（backend + algorithms provider），避免再次漂移 | 开发成员 | P2 | 持续 |
| 4 | 关注 `pytest` job 覆盖率门槛（当前 55.74%，阈值 50%），新增测试应保持不倒退 | 开发成员 | P2 | 持续 |

---

## ⚠️ 待完善 / 已知局限

- **本地 pre-commit 的 `ruff-format` 偶发 `.ruff_cache` 文件锁（os error 5）**：Windows 环境问题，CI(Ubuntu) 无此问题；已通过清除 `.ruff_cache` 缓解，建议后续在 `.gitignore` 或文档中固化。
- **`_as_file_uri` 的 POSIX 路径在 Windows 下仍返回 None**（`Path('/tmp/x')` 在 Windows 非绝对路径）：CI 运行于 Linux 无影响；若需 Windows 侧处理 POSIX 路径可后续增强。
- **`detect_source_kind` 的 "blob" 兜底语义**：新增的 `scheme == ""` 分支改变了对无 scheme 路径的归类（blob → local_file），符合直觉且经 8 用例验证，但若存在依赖旧 blob 语义的外部调用需留意。
- 用户"刚才改的一些代码"在本次会话中**未出现在工作区**（`git status` 仅含修复文件）——如为未保存编辑，请保存后另行提交；已提交的 UI 改动（`b06097a`）与 datapool 改动（`d5ad133`）均已在 `origin/dev`。

---

## 📚 数据来源 & 成员产出索引

- Cody（代码审查师）原始产出：Phase 2 修复（`75136d6`/`5fc2b9d`），见 `phase2-cgda-closeout-2026-08-08.md`
- Tessa（测试专家）原始产出：F5/F11 契约与事件循环测试（`5fc2b9d`），见 `phase2-cgda-closeout-2026-08-08.md`
- 主理人（本轮）：6 轮 CI 诊断与修复（`a6e3137`→`c9c6e76`），最终 CI run `31279433111`（completed/success）
- 最终测试数字：后端 `688 passed, 12 warnings`、覆盖率 55.74%（≥50%）；算法 `326 passed, 1 skipped`

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
