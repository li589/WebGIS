# OMEGA Offline Result Template

## 用途

本模板用于记录一次完整的 OMEGA 离线正式基线结果，避免后续只凭单次输出或主观印象判断是否保留优化。

建议配套使用：

- `docs/omega_baseline_and_candidates.md`
- `docs/omega_offline_execution_checklist.md`
- `scripts/run_omega_offline_baseline.ps1`

## 基本信息

- 日期：
- 记录人：
- 工作区状态：
- 分支或提交号：
- 本轮是否包含新代码改动：
- 改动摘要：

## 运行环境

- 机器：
- 电源模式：
- Python 解释器：
- 依赖环境是否固定：
- 是否关闭其他高负载程序：

## 执行命令

填写实际执行的完整命令：

```powershell
```

如果是用脚本执行，填写 profile 组合：

- Profiles：
- OutputRoot：
- 日志目录：

## 结果摘要

### `execute_omega_retrieval`

- `avg_ms`：
- `std_ms`：
- `min_ms`：
- `max_ms`：
- `shape`：
- `finite_ratio`：

### `single_pixel_solver`

- `avg_ms_per_pixel`：
- `std_ms_per_pixel`：
- `min_ms_per_pixel`：
- `max_ms_per_pixel`：
- `mean_n_use`：

## cProfile Top 10

按 `tottime` 填前 10 个热点：

1. 
2. 
3. 
4. 
5. 
6. 
7. 
8. 
9. 
10. 

## 与上一轮对比

- 对比基线来源：
- `execute_omega_retrieval` 是否更快：
- `std_ms` 是否明显放大：
- `single_pixel_solver` 是否同步变化：
- 热点排序是否符合预期：
- 是否命中了已证伪候选：

## 判定规则

按以下顺序判断：

1. 先看 `execute_omega_retrieval`
   - 如果均值没有稳定变好，不保留

2. 再看波动
   - 如果均值略有改善，但 `std_ms` 明显变大，不保留

3. 再看热点
   - 如果总时间变化与热点变化对不上，优先判为噪声

4. 最后看 `single_pixel_solver`
   - 只用于辅助解释，不单独决定保留/回退

## 最终结论

- 判定：`保留 / 回退 / 待复测`
- 原因：
- 下一步建议：

## 附注

- 是否需要补跑 `formal192`：
- 是否需要补跑 `dual96`：
- 是否需要补跑 `cprofile96`：
