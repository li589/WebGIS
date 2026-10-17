/**
 * 图层显示名统一改写（2026-10-17 用户要求）。
 *
 * 只作用于**展现层**：侧栏「已添加图层」的分组标题 / 图层名、以及「添加图层」
 * 目录列表的条目名。**不改** catalog 目录、不改工作流名称（工作流页保持原样）、
 * 不改磁盘上的 `display_name`。因此这里只在模板渲染时调用，绝不写回
 * `layer.name` / `runGroup.title`，否则会影响瓦片请求键、去重与工作区快照。
 *
 * 规则（按顺序）：
 *   1. 去掉「（本地）」/「(本地)」后缀 —— 侧栏不再强调数据来源；
 *   2. `产品反演` → `反演产品`（语序纠正）；
 *   3. 平台名补全：`风云` → `风云卫星`、`SMAP` → `SMAP卫星`。
 *      只在后面紧跟空格或已到结尾时替换，避免把「风云卫星」「SMAP卫星」
 *      或「风云三号」这类已完整/带型号的名字改坏。
 */
export function toLayerDisplayName(raw: string | null | undefined): string {
  let name = String(raw ?? '').trim()
  if (!name) return ''

  // 1. 去掉「（本地）」/「(本地)」
  name = name.replace(/[（(]\s*本地\s*[）)]/g, '')

  // 2. 产品反演 → 反演产品
  name = name.replace(/产品反演/g, '反演产品')

  // 3. 风云 → 风云卫星、SMAP → SMAP卫星（已有「卫星」时跳过）
  name = name.replace(/风云(?=\s|$)/g, '风云卫星').replace(/SMAP(?=\s|$)/gi, 'SMAP卫星')

  return name.replace(/\s{2,}/g, ' ').trim()
}
