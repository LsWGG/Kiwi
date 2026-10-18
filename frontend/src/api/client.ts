/** 统一 API 客户端：fetch 封装，kbId 自动追加为 ?kb_id= query 参数（后端约定）。 */
const API_BASE = '/api'

/** 把 kbId 追加为 query 参数（保留 path 上已有的 query）。 */
function withKbId(path: string, kbId?: string | null): string {
  if (!kbId) return path
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}kb_id=${encodeURIComponent(kbId)}`
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
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((detail as any).detail || res.statusText)
  }
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
      if (!res.ok) {
        const detail = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error((detail as any).detail || res.statusText)
      }
      return res.json() as Promise<T>
    })
}

export default { request, upload }