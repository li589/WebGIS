# Layers store 三切片拆分（2026-08-10）

## 结果

`useLayersStore()` 对外 API 不变；实现拆为：

| 切片 | 文件 | 职责 |
|------|------|------|
| catalog | `catalog-runtime.ts` | runtime catalog / library / readiness / weather capability |
| active | `active-layers.ts` | activeLayers CRUD、display、本地导入、显隐与样式 |
| run | `run-layers.ts` | jobLayers、run groups、materialize / progressive sync |

`index.ts` 负责组合、workspace persist/hydrate、weather reconcile、poller/runner 接线。

## 验证

```text
cd Code/frontend
npm run test -- layers workspace-persist   # 7 files / 22 tests passed
npx eslint src/stores/layers/{index,active-layers,run-layers,catalog-runtime}.ts
npx vue-tsc --noEmit -p tsconfig.app.json  # clean for these changes
```

## 备注

- 切片间通过 late-bound deps（catalog / viewport / poller / runner / persist）解耦初始化顺序。
- Batch G 活栈冒烟见 `2026-08-10-stub-v1-live-smoke.md`。
- 提交：`3117aeb`（stub_v1 Batch G）、`3b21419`（含 layers 三切片 + 品牌 chore）、`7152a4d`（DATA_ROOT seeds）。

## 下一刀

- ~~抽出 `workspace-hydrate.ts`~~ ✅（persist/hydrate 已切出）
- ~~抽出 `weather-reconcile.ts`~~ ✅（provider arg/query、reconcile、apply preference、activateWeatherTileViewport）
- ~~stub_v1 Batch H~~ ✅ 5/5 活栈见 `2026-08-10-stub-v1-batch-h.md`
- ~~stub_v1 Batch I~~ ✅ 4/4 活栈见 `2026-08-10-stub-v1-batch-i.md`
