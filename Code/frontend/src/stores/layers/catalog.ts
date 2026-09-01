/**
 * X1: 图层目录数据 — 从后端 JSON codegen 派生，不再硬编码。
 *
 * 数据真源：Code/backend/app/catalog_seeds/*.json
 * Codegen：Tools/generate_catalog_seeds.py → catalog-seeds.generated.json
 * 构建时：npm run gen:catalog（prebuild 钩子自动执行）
 * Drift 校验：npm run check:catalog
 *
 * 新增/修改图层只需改后端 JSON + 运行 npm run gen:catalog。
 */
import type { LayerCatalogItem, LayerCategory } from './types'
import { ORG_CATEGORY_NAME } from '../../ui-copy/brand'
import generatedDataRaw from './catalog-seeds.generated.json'

// ── 类型断言：codegen 脚本保证 JSON 结构与 TypeScript 接口一致 ──────────────────
const generatedData = generatedDataRaw as unknown as {
  categories: LayerCategory[]
  items: LayerCatalogItem[]
}

// ── 类别定义（X1: 从后端 JSON codegen 派生）────────────────────────────────────
// research-group 显示名统一走 ORG_CATEGORY_NAME（默认「核心资产」），勿在 JSON/组件里写死旧名。
export function applyResearchGroupCategoryLabel<T extends { id: string; name: string }>(
  categories: readonly T[],
): T[] {
  return categories.map((cat) =>
    cat.id === 'research-group' ? { ...cat, name: ORG_CATEGORY_NAME } : cat,
  )
}

export const LAYER_CATEGORIES: LayerCategory[] = applyResearchGroupCategoryLabel(
  generatedData.categories,
)

/** 分类 id → 侧栏/图层 chip 展示名（含 research-group → 核心资产） */
export function resolveCategoryDisplayName(categoryId: string): string {
  return LAYER_CATEGORIES.find((c) => c.id === categoryId)?.name ?? categoryId
}

// ── 图层库（X1: 从后端 JSON codegen 派生）─────────────────────────────────────
export const LAYER_LIBRARY: LayerCatalogItem[] = generatedData.items

// ── 天气引擎图层 ID 白名单（从 sources 派生，用于 runtime catalog 加载前的判断）──
export const WEATHER_ENGINE_CATALOG_IDS = new Set(
  LAYER_LIBRARY.filter((item) => item.sources.some((s) => s.id.startsWith('weatherengine'))).map(
    (item) => item.catalogId,
  ),
)

// ── 多源合并查找表（X1: 从 isMergedGroup 派生，不再硬编码 Map）──────────────────

/** 合并条目 catalogId → 其包含的所有成员 catalogId 列表 */
export const MERGED_LAYER_GROUPS = new Map<string, string[]>(
  LAYER_LIBRARY.filter((item) => item.isMergedGroup).map((item) => [
    item.catalogId,
    item.members ?? [],
  ]),
)

/** 成员 catalogId → 所属合并条目 catalogId（反向查找） */
export const MERGED_LAYER_SOURCES = new Map<string, string>(
  [...MERGED_LAYER_GROUPS.entries()].flatMap(([mergedId, sourceIds]) =>
    sourceIds.map((sid) => [sid, mergedId] as [string, string]),
  ),
)

/** 返回成员 catalogId 所属的合并条目 catalogId，无则 undefined */
export function getMergedCatalogId(sourceId: string): string | undefined {
  return MERGED_LAYER_SOURCES.get(sourceId)
}

/** 返回合并条目的所有成员 catalogId 列表，非合并条目返回 undefined */
export function getMergedSourceIds(mergedCatalogId: string): string[] | undefined {
  return MERGED_LAYER_GROUPS.get(mergedCatalogId)
}

/** 按类别分组的图层库（用于侧栏分类展示） */
export const LAYER_LIBRARY_BY_CATEGORY = (() => {
  const map = new Map<string, LayerCatalogItem[]>()
  for (const item of LAYER_LIBRARY) {
    if (!map.has(item.category)) {
      map.set(item.category, [])
    }
    map.get(item.category)!.push(item)
  }
  return map
})()
