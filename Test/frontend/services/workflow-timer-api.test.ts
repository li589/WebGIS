import { describe, expect, it } from 'vitest'

import { insertDateTemplateIntoOverridesJson } from '@/services/workflow-timer-api'

describe('insertDateTemplateIntoOverridesJson', () => {
  it('inserts template under parameters without breaking JSON', () => {
    const result = insertDateTemplateIntoOverridesJson('{}', '{{today}}')
    expect(result.error).toBeNull()
    const parsed = JSON.parse(result.json) as {
      parameters: Record<string, string>
    }
    expect(parsed.parameters.today).toBe('{{today}}')
  })

  it('merges into existing parameters and avoids key collision', () => {
    const result = insertDateTemplateIntoOverridesJson(
      JSON.stringify({ parameters: { today: '20260101' }, priority: 5 }),
      '{{today}}',
    )
    expect(result.error).toBeNull()
    const parsed = JSON.parse(result.json) as {
      parameters: Record<string, unknown>
      priority: number
    }
    expect(parsed.priority).toBe(5)
    expect(parsed.parameters.today).toBe('20260101')
    expect(parsed.parameters.today_1).toBe('{{today}}')
  })

  it('returns error when JSON is invalid', () => {
    const result = insertDateTemplateIntoOverridesJson('{bad', '{{yesterday}}')
    expect(result.error).toMatch(/无效/)
    expect(result.json).toBe('{bad')
  })
})
