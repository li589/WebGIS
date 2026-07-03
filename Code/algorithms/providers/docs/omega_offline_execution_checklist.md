# OMEGA Offline Execution Checklist

## 用途

这是一页式执行清单，用于后续所有 OMEGA 性能优化前后的正式基线流程。

原则：

- 先跑基线，再决定是否保留代码改动
- 不重复尝试已证伪候选
- 在线结果只做快速筛查，正式判断以离线结果为准

配套文档：

- `docs/omega_baseline_and_candidates.md`

配套脚本：

- `scripts/run_omega_offline_baseline.ps1`

## 执行前

1. 确认当前工作区状态
   - 记录当前分支或提交标识
   - 明确本轮是否有新的 OMEGA 改动

2. 确认环境稳定
   - 接电源
   - 打开高性能电源模式
   - 关闭无关的大型程序
   - 使用固定 Python 解释器和依赖版本

3. 查阅禁做项
   - 先看 `docs/omega_baseline_and_candidates.md` 中的“已证伪候选”
   - 不重复尝试已回退的微优化

## 快速筛查

先跑交互参考层，只判断是否出现明显回退：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_omega_offline_baseline.ps1 -Profiles quick
```

参考区间：

- `single_pixel_solver`：约 `128 ~ 135 ms/pixel`
- `execute_omega_retrieval`：约 `6.25 ~ 6.45 s`

如果明显慢于参考区间，先不要继续放大规模。

## 正式基线

中等正式层：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_omega_offline_baseline.ps1 -Profiles formal96,cprofile96
```

大规模正式层：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_omega_offline_baseline.ps1 -Profiles formal192
```

双温补充层：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_omega_offline_baseline.ps1 -Profiles dual96
```

如需整批执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_omega_offline_baseline.ps1 -Profiles all
```

## 结果判定

1. 先看 `execute_omega_retrieval`
   - 以均值为主
   - 同时看标准差是否明显放大

2. 再看 `single_pixel_solver`
   - 只用于辅助解释热点变化
   - 不能单独决定保留或回退

3. 必须对照 `cProfile`
   - 总时间变快，但热点没有对上时，优先怀疑噪声

4. 仅在正式基线也稳定变好时保留改动
   - 否则回退

## 结果记录

每轮至少记录以下字段：

- 工作区状态或提交号
- 执行命令
- 运行时间
- `avg_ms` / `std_ms`
- `avg_ms_per_pixel` / `std_ms_per_pixel`
- `finite_ratio`
- cProfile 前 10 热点
- 结论：保留 / 回退 / 待复测

## 当前策略

当前阶段默认策略如下：

1. 停止继续微调 `omega.py` 的 Python 接线层
2. 先跑离线正式基线
3. 只有正式基线显示稳定收益，才进入下一轮优化
4. 优先回避已证伪候选
