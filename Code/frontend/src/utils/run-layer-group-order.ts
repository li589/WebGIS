/**
 * Active TOC 计算组：组内调序 / 整组移动的纯逻辑（与 Pinia 解耦便于单测）。
 */

export type OrderableLayer = {
  instanceId: string
  order: number
  runGroupId?: string
}

export type RunGroupMembers = {
  groupId: string
  memberInstanceIds: string[]
}

/** 组内成员重排后写回全局连续 order（组块保持连续）。 */
export function applyReorderWithinGroup(
  layers: OrderableLayer[],
  group: RunGroupMembers,
  fromMemberIndex: number,
  toMemberIndex: number,
): OrderableLayer[] {
  const ids = [...group.memberInstanceIds]
  if (
    fromMemberIndex < 0 ||
    toMemberIndex < 0 ||
    fromMemberIndex >= ids.length ||
    toMemberIndex >= ids.length
  ) {
    return layers.map((l) => ({ ...l }))
  }
  const [moved] = ids.splice(fromMemberIndex, 1)
  if (!moved) return layers.map((l) => ({ ...l }))
  ids.splice(toMemberIndex, 0, moved)

  const byId = new Map(layers.map((l) => [l.instanceId, { ...l }]))
  const memberSet = new Set(ids)
  const sorted = [...layers].sort((a, b) => a.order - b.order)
  const minOrder = Math.min(
    ...ids.map((id) => byId.get(id)?.order ?? 0).filter((n) => Number.isFinite(n)),
  )
  ids.forEach((id, i) => {
    const layer = byId.get(id)
    if (layer) layer.order = minOrder + i
  })
  // 非成员保持相对位置，再压缩
  const next = sorted.map((l) => byId.get(l.instanceId)!).filter(Boolean)
  // 确保组块连续：抽出成员按新序插入原块起点
  const firstIdx = next.findIndex((l) => memberSet.has(l.instanceId))
  const without = next.filter((l) => !memberSet.has(l.instanceId))
  const block = ids.map((id) => byId.get(id)!).filter(Boolean)
  const insertAt = firstIdx < 0 ? without.length : Math.min(firstIdx, without.length)
  const merged = [...without.slice(0, insertAt), ...block, ...without.slice(insertAt)]
  merged.forEach((l, i) => {
    l.order = i
  })
  return merged
}

/** 整组相对组外锚点移动。 */
export function applyMoveGroupBlock(
  layers: OrderableLayer[],
  group: RunGroupMembers,
  toAnchorInstanceId: string | null,
  placeAfter: boolean,
): OrderableLayer[] {
  const memberSet = new Set(group.memberInstanceIds)
  const sorted = [...layers].sort((a, b) => a.order - b.order).map((l) => ({ ...l }))
  const block = sorted.filter((l) => memberSet.has(l.instanceId))
  const rest = sorted.filter((l) => !memberSet.has(l.instanceId))
  if (!block.length) return sorted

  let insertAt = rest.length
  if (toAnchorInstanceId) {
    const idx = rest.findIndex((l) => l.instanceId === toAnchorInstanceId)
    if (idx >= 0) insertAt = placeAfter ? idx + 1 : idx
  }
  const next = [...rest.slice(0, insertAt), ...block, ...rest.slice(insertAt)]
  next.forEach((l, i) => {
    l.order = i
  })
  return next
}

/** 禁止把外部层插进锁定组中间：若目标在组内且拖动层不属于该组，则拒绝。 */
export function shouldRejectInsertIntoLockedGroup(
  moved: OrderableLayer,
  target: OrderableLayer | undefined,
  lockedGroupIds: Set<string>,
): boolean {
  if (!target?.runGroupId) return false
  if (!lockedGroupIds.has(target.runGroupId)) return false
  return !moved.runGroupId || moved.runGroupId !== target.runGroupId
}
