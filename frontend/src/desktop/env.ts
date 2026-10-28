/**
 * 桌面构建标记。
 *
 * `import.meta.env.VITE_KIWI_DESKTOP` 在构建时由 Vite 静态替换，
 * Docker / Web 构建恒为 false，桌面专属代码与路由可被 tree-shaking 移除。
 */
export const IS_DESKTOP = import.meta.env.VITE_KIWI_DESKTOP === '1'

/**
 * 模型地址是否指向本机（桌面版允许无需风险确认）。
 *
 * 与后端 `offline_guard.is_loopback_host` 保持一致：localhost、`*.localhost`、
 * 127.0.0.0/8 与 IPv6 回环。
 */
export function isLoopbackUrl(value: string): boolean {
  try {
    const url = new URL(value)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return false
    let host = url.hostname.toLowerCase()
    if (host.startsWith('[') && host.endsWith(']')) host = host.slice(1, -1)
    if (host === 'localhost' || host === '::1') return true
    if (host.endsWith('.localhost')) return true
    const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host)
    return !!match && match[1] === '127'
  } catch {
    return false
  }
}

/**
 * 桌面构建中是否应阻止加载该外部资源。
 *
 * 相对地址、同源地址与 loopback 始终放行；Docker 构建恒为 false。
 * 远程图片、favicon、iframe 与视频封面等资源地址都通过它统一判定，
 * 避免编辑态与阅读态出现不同的外联行为。
 */
export function isBlockedExternalAsset(src: string): boolean {
  if (!IS_DESKTOP || !src) return false
  try {
    const base =
      typeof window === 'undefined' ? 'http://localhost/' : window.location.href
    const url = new URL(src, base)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return false
    if (url.origin === new URL(base).origin) return false
    return !isLoopbackUrl(url.href)
  } catch {
    return false
  }
}
