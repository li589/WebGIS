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
 *
 * 另有一条**只给分组标题用**的规则（`toRunGroupDisplayName`），见下。
 */

/**
 * 反演产品图层组的统一显示名（2026-10-20 用户要求）。
 *
 * 为什么要在显示层做：同一个图层组的标题有**四个来源**，文案各不相同——
 *   ① 图层库「添加」→ `DEFAULT_LAYERS[].groupTitle`
 *   ② 稳定编号兜底探测 → `resolveInversionGroupMeta()` 现拼的模板串
 *   ③ 工作流跑完回挂 → 工作流定义 JSON 的 `extra.group_title`（在 Data 目录里，
 *      后端同步维护，改前端代码管不到）
 *   ④ 工作区快照恢复 → 存的是旧标题，换设备还会把旧名带回来
 * 逐个改必然漏一处（用户原话：「从图层容器添加是对的，从工作流添加又是旧的」），
 * 所以在渲染前统一归一，任何入口进来都显示新名字。
 *
 * 只按平台归一，不区分「平均/动态」「单源/双源」——用户明确要求统一。
 * GLDAS 那条保持原样：名字里带着第三套数据源，归并会丢信息。
 */
function canonicalInversionGroupTitle(raw: string): string {
  if (!/散射约束/.test(raw)) return ''
  if (/GLDAS/i.test(raw)) return ''
  if (/SMAP/i.test(raw)) return 'SMAP卫星反演产品'
  if (/风云|FY/i.test(raw)) return '风云卫星微波反演产品'
  return ''
}

/**
 * 图层组标题专用改写（侧栏「数据名称」分组头）。
 *
 * 与 `toLayerDisplayName` 分开的原因：目录条目（图层库列表）里
 * 「风云 平均反演（本地）/（在线）/动态（本地）…」是**不同数据集**，
 * 若一并归一会变成四个同名条目，反而分不清。分组头只表示「这一堆产物
 * 属于同一个反演产品」，归一才安全。
 */
export function toRunGroupDisplayName(raw: string | null | undefined): string {
  const name = String(raw ?? '').trim()
  const canonical = canonicalInversionGroupTitle(name)
  if (canonical) return canonical
  return toLayerDisplayName(name)
}

/**
 * 反演产品的「族」标识（只看平台，不看平均/动态）。
 *
 * 用途：侧栏去重。占位层（用户点「添加」时建的空壳）名字是目录名
 * 「SMAP 动态散射约束产品」，而产物组归一后的名字是「SMAP卫星反演产品」，
 * 两者**字符串永远不相等**，所以按名字/按 id 都无法判定重复。
 * 而用户眼里它们就是同一个产品 ⇒ 用「平台」这一层做判定。
 *
 * 返回 'smap' / 'fy' / ''（空串＝不是反演产品，不参与去重）。
 * GLDAS 明确排除：名字里带第三套数据源，归并会丢信息。
 */
export function inversionFamilyKey(raw: string | null | undefined): string {
  const name = String(raw ?? '').trim()
  if (!name) return ''
  if (/GLDAS/i.test(name)) return ''
  if (!/散射约束|omega/i.test(name)) return ''
  if (/SMAP/i.test(name)) return 'smap'
  if (/风云|FY/i.test(name)) return 'fy'
  return ''
}

/**
 * 分组头的**方法副标题**（2026-10-27 用户要求）。
 *
 * 起因：`toRunGroupDisplayName` 把「平均」与「动态」两组都归一成**同一个平台名**
 * （都叫「风云卫星微波反演产品」/「SMAP卫星反演产品」），侧栏于是出现两行一模一样
 * 的组标题，guest 根本看不出哪一行是平均、哪一行是动态。⇒ 在标题底下补一行小字。
 *
 * 判定**优先看工作流 / 目录 id，标题文案只作兜底**：
 * 同一个组的标题有四个来源（见 `toRunGroupDisplayName` 注释），而工作流定义里的
 * 文案五花八门——`风云 散射约束产品产物（本地）` 这种压根不含「平均」二字，
 * 靠文案猜必然漏掉。id 里的 `avg` / `fenkuai` 才是硬事实。
 */
export const GROUP_METHOD_LABEL = {
  mean: '平均散射约束',
  dynamic: '动态散射约束',
} as const

export function runGroupMethodLabel(group: {
  title?: string | null
  workflowId?: string | null
  sourceLayerId?: string | null
}): string {
  const workflow = String(group.workflowId ?? '').toLowerCase()
  if (workflow) {
    if (/fenkuai|block|dynamic/.test(workflow)) return GROUP_METHOD_LABEL.dynamic
    if (/avg|mean/.test(workflow)) return GROUP_METHOD_LABEL.mean
  }
  const source = String(group.sourceLayerId ?? '').toLowerCase()
  if (source) {
    if (/dynamic|fenkuai/.test(source)) return GROUP_METHOD_LABEL.dynamic
    if (/-avg|mean/.test(source)) return GROUP_METHOD_LABEL.mean
  }
  const title = String(group.title ?? '')
  if (/动态|分块/.test(title)) return GROUP_METHOD_LABEL.dynamic
  if (/平均/.test(title)) return GROUP_METHOD_LABEL.mean
  return ''
}

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
