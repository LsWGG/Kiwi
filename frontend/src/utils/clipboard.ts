/**
 * 复制文本到剪贴板。
 *
 * `navigator.clipboard` 只在安全上下文（HTTPS / localhost）可用；Kiwi 常见
 * 部署方式是通过内网 IP + HTTP 访问（如 http://192.168.31.33:18473），此时
 * Clipboard API 不存在。这里优先使用 Clipboard API，失败或不可用时回落到
 * 隐藏 textarea + `document.execCommand('copy')`。
 */
export async function copyTextToClipboard(value: string): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return true
    } catch {
      // 权限被拒绝或非安全上下文：继续走 execCommand 回落。
    }
  }
  if (typeof document === 'undefined') return false

  const area = document.createElement('textarea')
  area.value = value
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.top = '-1000px'
  area.style.left = '-1000px'
  area.style.opacity = '0'
  document.body.appendChild(area)
  try {
    area.focus()
    area.select()
    // iOS Safari 需要显式设置选区才能复制。
    area.setSelectionRange(0, area.value.length)
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
  }
}
