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

function errorFromBody(statusText: string, body: unknown, status?: number): Error {
  const detail = body && typeof body === 'object' ? (body as any).detail : null
  const fallback = statusText || (status ? `请求失败（${status}）` : '请求失败')
  return new Error(errorMessage(detail, fallback))
}

async function parseError(res: Response, body: unknown): Promise<Error> {
  return errorFromBody(res.statusText, body, res.status)
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

export type UploadProgressHandler = (loaded: number, total: number) => void

/**
 * 上传前先读 1 字节，确认浏览器真的有权访问这个文件。
 * Snap / Flatpak 版浏览器会拒绝读取不属于当前用户或沙盒外的文件（例如
 * root 所有的下载文件），此时 XHR 会一直停在 0% 且不发请求；提前失败才能
 * 给出可操作的提示。
 */
async function assertFileReadable(file: File): Promise<void> {
  if (file.size === 0) return
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    await Promise.race([
      file.slice(0, 1).arrayBuffer(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('read-timeout')), 8000)
      }),
    ])
  } catch {
    throw new Error(
      `浏览器无法读取文件「${file.name}」。请把文件复制到主目录后重新选择；` +
        'Snap / Flatpak 版浏览器不能读取不属于当前用户或沙盒外的文件。',
    )
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
}

/**
 * 带上传进度的 POST。fetch 无法上报请求体进度，因此附件等大文件走 XHR。
 * 上传完成后接口可能还要写库 / 落盘，进度条会停在 100%，由调用方提示
 * 「正在处理」。传入 signal 可中止上传。
 */
export async function uploadWithProgress<T>(
  path: string,
  formData: FormData,
  kbId?: string | null,
  onProgress?: UploadProgressHandler,
  signal?: AbortSignal,
): Promise<T> {
  for (const entry of formData.values()) {
    if (entry instanceof File) await assertFileReadable(entry)
  }
  const url = `${API_BASE}${withKbId(path, kbId)}`
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    const abortError = () => {
      const error = new Error('上传已取消')
      error.name = 'AbortError'
      return error
    }
    if (signal?.aborted) {
      reject(abortError())
      return
    }
    const onAbort = () => xhr.abort()
    signal?.addEventListener('abort', onAbort, { once: true })
    const cleanup = () => signal?.removeEventListener('abort', onAbort)
    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total)
      }
    }
    xhr.onload = () => {
      cleanup()
      let body: unknown = null
      if (xhr.responseText) {
        try {
          body = JSON.parse(xhr.responseText)
        } catch {
          body = xhr.responseText
        }
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve((body ?? undefined) as T)
        return
      }
      if (
        xhr.status === 401 &&
        body &&
        typeof body === 'object' &&
        (body as any).code === 'access_token_required'
      ) {
        window.dispatchEvent(new CustomEvent('kiwi:unauthorized'))
      }
      reject(errorFromBody(xhr.statusText, body, xhr.status))
    }
    xhr.onerror = () => {
      cleanup()
      reject(new Error('网络错误，上传中断'))
    }
    xhr.onabort = () => {
      cleanup()
      reject(abortError())
    }
    try {
      xhr.send(formData)
    } catch (error) {
      cleanup()
      reject(error)
    }
  })
}

/** 下载二进制响应（插件包 / 内置包 / 开发套件），返回实际文件名。 */
export async function download(
  path: string,
  fallbackName = 'download.zip',
): Promise<string> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw await readError(res)
  const disposition = res.headers.get('content-disposition') || ''
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
  let filename = fallbackName
  if (match?.[1]) {
    try {
      filename = decodeURIComponent(match[1])
    } catch {
      filename = match[1]
    }
  }
  const blob = await res.blob()
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  return filename
}

export default { request, upload, uploadWithProgress }