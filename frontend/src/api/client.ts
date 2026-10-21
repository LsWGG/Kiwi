/** 统一 API 客户端：fetch 封装，kbId 自动追加为 ?kb_id= query 参数（后端约定）。 */
const API_BASE = '/api'

/** 把 kbId 追加为 query 参数（保留 path 上已有的 query）。 */
function withKbId(path: string, kbId?: string | null): string {
  if (!kbId) return path
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}kb_id=${encodeURIComponent(kbId)}`
}

/** 把 FastAPI 的字符串 / 校验错误数组转成可直接展示的文案。 */
export function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (!item || typeof item !== 'object') return ''
        const { loc, msg } = item as { loc?: unknown; msg?: unknown }
        const field = Array.isArray(loc)
          ? loc.filter((part) => !['body', 'query', 'path'].includes(String(part))).join('.')
          : ''
        const text = typeof msg === 'string' ? msg : ''
        if (!text) return ''
        return field ? `${field}: ${text}` : text
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }
  if (detail && typeof detail === 'object') {
    const { message, msg, error } = detail as Record<string, unknown>
    const text = message ?? msg ?? error
    if (typeof text === 'string' && text) return text
  }
  return fallback
}

async function parseError(res: Response, body: unknown): Promise<Error> {
  const detail = body && typeof body === 'object' ? (body as any).detail : null
  return new Error(errorMessage(detail, res.statusText || `请求失败（${res.status}）`))
}

/**
 * 访问控制开启时，后端返回 401 + code=access_token_required。
 * 通过全局事件通知 App 切换到登录页；笔记密码错误等 401 不受影响。
 */
async function readError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null)
  if (
    res.status === 401 &&
    body &&
    typeof body === 'object' &&
    (body as any).code === 'access_token_required'
  ) {
    window.dispatchEvent(new CustomEvent('kiwi:unauthorized'))
  }
  return parseError(res, body)
}

export async function request<T>(
  path: string,
  options: RequestInit & { kbId?: string | null } = {},
): Promise<T> {
  const { kbId, ...rest } = options
  const url = withKbId(path, kbId)
  const headers = new Headers(rest.headers)
  headers.set('Content-Type', 'application/json')

  const res = await fetch(`${API_BASE}${url}`, { ...rest, headers })
  if (!res.ok) throw await readError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export function upload<T>(
  path: string,
  formData: FormData,
  kbId?: string | null,
): Promise<T> {
  const url = withKbId(path, kbId)
  return fetch(`${API_BASE}${url}`, { method: 'POST', body: formData })
    .then(async (res) => {
      if (!res.ok) throw await readError(res)
      return res.json() as Promise<T>
    })
}

export default { request, upload }