/**
 * SSE 客户端：用 fetch ReadableStream 手写，支持 POST + 自定义 header。
 * 解析 "event: type\ndata: {...}\n\n" 帧，逐条回调。
 */

export interface SSEMessage {
  event: string
  data: any
}

export interface SSEHandler {
  onMessage: (msg: SSEMessage) => void
  onError?: (err: Error) => void
  onDone?: () => void
  signal?: AbortSignal
}

/**
 * 打开一个 POST SSE 流。返回一个 abort 函数。
 * 请求体带 JSON；X-KB-Id 可传入。
 */
export function openSSE(
  path: string,
  body: any,
  { onMessage, onError, onDone, signal }: SSEHandler,
): () => void {
  const ctrl = new AbortController()
  const abort = () => ctrl.abort()
  if (signal) {
    signal.addEventListener('abort', abort)
  }
  if (!body.kbId) {
    // kbId 通过 header
  }

  void (async () => {
    try {
      const res = await fetch(`/api${path}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(body.__kbId ? { 'X-KB-Id': body.__kbId } : {}),
        },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      })
      if (!res.ok) {
        throw new Error(`SSE HTTP ${res.status}`)
      }
      if (!res.body) throw new Error('No response body')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // 按空白行拆帧
        let idx: number
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, idx)
          buffer = buffer.slice(idx + 2)
          const parsed = parseFrame(frame)
          if (parsed) onMessage(parsed)
        }
      }
      onDone?.()
    } catch (e: any) {
      if (e.name === 'AbortError') return
      onError?.(e instanceof Error ? e : new Error(String(e)))
    }
  })()

  return abort
}

function parseFrame(frame: string): SSEMessage | null {
  let event = 'message'
  let data = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return null
  let parsedData: any
  try {
    parsedData = JSON.parse(data)
  } catch {
    parsedData = data
  }
  return { event, data: parsedData }
}