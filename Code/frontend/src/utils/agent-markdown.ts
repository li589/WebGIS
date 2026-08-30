/**
 * Agent 对话 Markdown 渲染：GFM + KaTeX + 代码块，经 DOMPurify 消毒。
 */
import DOMPurifyImport from 'dompurify'
import { marked } from 'marked'
import markedKatex from 'marked-katex-extension'

type SanitizeFn = (dirty: string, config?: object) => string

function resolveSanitize(): SanitizeFn {
  const lib = DOMPurifyImport as unknown as {
    sanitize?: SanitizeFn
  } & ((root: Window) => { sanitize: SanitizeFn })
  if (typeof lib.sanitize === 'function') {
    return (dirty, config) => lib.sanitize!(dirty, config)
  }
  if (typeof window !== 'undefined' && typeof lib === 'function') {
    const bound = lib(window)
    return (dirty, config) => bound.sanitize(dirty, config)
  }
  // 极端环境（无 DOM）：仅粗剥离 script，避免抛错阻断对话
  return (dirty) => dirty.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
}

const sanitizeHtml = resolveSanitize()

let configured = false

function ensureMarked(): void {
  if (configured) return
  configured = true
  marked.use(
    markedKatex({
      throwOnError: false,
      nonStandard: true,
    }),
  )
  marked.setOptions({
    gfm: true,
    breaks: true,
  })
}

const PURIFY = {
  USE_PROFILES: { html: true, mathMl: true, svg: false },
  ADD_ATTR: [
    'class',
    'style',
    'aria-hidden',
    'aria-label',
    'role',
    'tabindex',
    'xmlns',
    'encoding',
    'display',
  ],
}

/** 将助手回复 Markdown（含 $ / $$ LaTeX、围栏代码）转为安全 HTML。 */
export function renderAgentMarkdown(source: string): string {
  const raw = (source ?? '').trim()
  if (!raw) return ''
  ensureMarked()
  const parsed = marked.parse(raw, { async: false })
  const html = typeof parsed === 'string' ? parsed : String(parsed)
  return sanitizeHtml(html, PURIFY)
}
