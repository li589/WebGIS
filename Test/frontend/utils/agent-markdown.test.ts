import { describe, expect, it } from 'vitest'
import { renderAgentMarkdown } from '@/utils/agent-markdown'

describe('renderAgentMarkdown', () => {
  it('returns empty for blank input', () => {
    expect(renderAgentMarkdown('')).toBe('')
    expect(renderAgentMarkdown('   ')).toBe('')
  })

  it('renders basic markdown emphasis and lists', () => {
    const html = renderAgentMarkdown('**bold** and `code`\n\n- a\n- b')
    expect(html).toContain('<strong>bold</strong>')
    expect(html).toContain('<code>code</code>')
    expect(html).toMatch(/<li>\s*a\s*<\/li>/)
  })

  it('renders fenced code blocks', () => {
    const html = renderAgentMarkdown('```js\nconst x = 1\n```')
    expect(html).toContain('<pre>')
    expect(html).toContain('<code')
    expect(html).toContain('const x = 1')
  })

  it('renders inline and block katex', () => {
    const inline = renderAgentMarkdown('area $E=mc^2$ ok')
    expect(inline).toContain('katex')
    const block = renderAgentMarkdown('$$\nE=mc^2\n$$')
    expect(block).toContain('katex')
  })

  it('strips script tags', () => {
    const html = renderAgentMarkdown('hi <script>alert(1)</script> **x**')
    expect(html.toLowerCase()).not.toContain('<script')
    expect(html).toContain('<strong>x</strong>')
  })
})
