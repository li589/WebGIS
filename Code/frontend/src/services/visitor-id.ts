/**
 * 匿名访客号（未登录访客的 AI 助手日额度计数键）。
 *
 * 为什么需要：本项目所有未登录访客共用同一个 `demo` 账号，服务端无法按「人」
 * 区分，所以「每人每天多少次」这种额度按账号记会退化成「全站共享一份」。
 * 浏览器侧生成一个随机号并存在 localStorage，随请求头 `X-Visitor-Id` 上报，
 * 后端按「访客号 + 北京自然日」计数，就能做到「每个浏览器一份额度」。
 *
 * 边界（如实说明，不夸大）：
 *   - 清空浏览器存储会换新号 ⇒ 能重置额度。这就是为什么后端在**没收到**该头时
 *     退回按客户端 IP 计数，两条路同时兜。
 *   - localStorage 不可用（隐私模式/被禁用）时退回「本次页面会话内存里的号」，
 *     刷新即变；此时后端仍按 IP 兜底。
 *   - 登录后（有会话 Cookie）后端不计这份额度，本号不参与判定。
 */

const STORAGE_KEY = 'cgda.visitor.id'

/** 只接受 16~64 位十六进制，避免脏数据被当成访客号上报。 */
const VALID = /^[0-9a-f]{16,64}$/i

let cached: string | null = null

function randomId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID().replace(/-/g, '')
    }
  } catch {
    // 非安全上下文下 randomUUID 可能不可用，走下面的 getRandomValues
  }
  const bytes = new Uint8Array(16)
  try {
    crypto.getRandomValues(bytes)
  } catch {
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256)
    }
  }
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

/**
 * 取（必要时生成并持久化）当前浏览器的访客号。
 *
 * 结果在模块内缓存，多次调用不会重复读写 localStorage。
 */
export function getVisitorId(): string {
  if (cached) return cached
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && VALID.test(saved)) {
      cached = saved
      return saved
    }
    const id = randomId()
    localStorage.setItem(STORAGE_KEY, id)
    cached = id
    return id
  } catch {
    // 存储不可用：本次会话内保持同一个号，刷新后由后端按 IP 兜底
    cached = randomId()
    return cached
  }
}
