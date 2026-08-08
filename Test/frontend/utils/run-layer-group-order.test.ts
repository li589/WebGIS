import { describe, expect, it } from 'vitest'
import {
  applyMoveGroupBlock,
  applyReorderWithinGroup,
  shouldRejectInsertIntoLockedGroup,
} from '@/utils/run-layer-group-order'

describe('run-layer-group-order', () => {
  const layers = [
    { instanceId: 'a', order: 0 },
    { instanceId: 'g1', order: 1, runGroupId: 'rg' },
    { instanceId: 'g2', order: 2, runGroupId: 'rg' },
    { instanceId: 'g3', order: 3, runGroupId: 'rg' },
    { instanceId: 'b', order: 4 },
  ]
  const group = { groupId: 'rg', memberInstanceIds: ['g1', 'g2', 'g3'] }

  it('reorders within group without breaking block', () => {
    const next = applyReorderWithinGroup(layers, group, 0, 2)
    const ids = next.sort((x, y) => x.order - y.order).map((l) => l.instanceId)
    expect(ids).toEqual(['a', 'g2', 'g3', 'g1', 'b'])
  })

  it('moves whole group before anchor', () => {
    const next = applyMoveGroupBlock(layers, group, 'a', false)
    const ids = next.sort((x, y) => x.order - y.order).map((l) => l.instanceId)
    expect(ids).toEqual(['g1', 'g2', 'g3', 'a', 'b'])
  })

  it('rejects inserting outsider into locked group', () => {
    expect(
      shouldRejectInsertIntoLockedGroup(
        { instanceId: 'a', order: 0 },
        { instanceId: 'g2', order: 2, runGroupId: 'rg' },
        new Set(['rg']),
      ),
    ).toBe(true)
    expect(
      shouldRejectInsertIntoLockedGroup(
        { instanceId: 'g1', order: 1, runGroupId: 'rg' },
        { instanceId: 'g2', order: 2, runGroupId: 'rg' },
        new Set(['rg']),
      ),
    ).toBe(false)
  })
})
