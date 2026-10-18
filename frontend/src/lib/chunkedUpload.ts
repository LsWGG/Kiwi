/** 大文件分片上传：4MB 分片、断点续传、失败重试。 */
import { request } from '@/api/client'
import { Sha256 } from '@/lib/sha256'

export interface ChunkInit {
  upload_id: string
  filename: string
  size: number
  sha256: string
  chunk_size: number
  total_chunks: number
  received_chunks: number[]
  received_bytes: number
  completed: boolean
}

export interface UploadProgress {
  uploaded: number
  total: number
  percent: number
}

const HASH_LIMIT = 64 * 1024 * 1024

async function sha256Hex(file: File): Promise<string> {
  if (!crypto?.subtle) return sha256HexStreaming(file)
  const buffer = await file.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

/** 大文件流式计算指纹：逐片读取，避免一次性把整文件读入内存。 */
async function sha256HexStreaming(file: File): Promise<string> {
  const hasher = new Sha256()
  const step = 4 * 1024 * 1024
  for (let offset = 0; offset < file.size; offset += step) {
    const buffer = await file.slice(offset, offset + step).arrayBuffer()
    hasher.update(new Uint8Array(buffer))
    // 让出主线程，避免大文件哈希期间界面完全卡死
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
  return hasher.digestHex()
}

async function putChunk(uploadId: string, index: number, blob: Blob): Promise<void> {
  let lastError = ''
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const res = await fetch(
        `/api/ingest/uploads/${encodeURIComponent(uploadId)}/chunks/${index}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/octet-stream' },
          body: blob,
        },
      )
      if (res.ok) return
      const detail = await res.json().catch(() => ({ detail: res.statusText }))
      lastError = (detail as { detail?: string }).detail || res.statusText
      if (res.status >= 400 && res.status < 500) break
    } catch (e: any) {
      lastError = e?.message || '网络错误'
    }
    await new Promise((resolve) => setTimeout(resolve, 600 * (attempt + 1)))
  }
  throw new Error(`分片 ${index + 1} 上传失败：${lastError}`)
}

/** 上传文件并返回 upload_id；已存在的分片会跳过，实现断点续传。 */
export async function uploadFileInChunks(
  file: File,
  kbId: string,
  onProgress?: (p: UploadProgress) => void,
): Promise<string> {
  const fingerprint =
    file.size <= HASH_LIMIT ? await sha256Hex(file) : await sha256HexStreaming(file)
  const init = await request<ChunkInit>('/ingest/uploads/init', {
    method: 'POST',
    kbId,
    body: JSON.stringify({
      filename: file.name,
      size: file.size,
      sha256: fingerprint,
    }),
  })
  const received = new Set(init.received_chunks || [])
  let uploaded = init.received_bytes || 0
  onProgress?.({ uploaded, total: file.size, percent: uploaded / file.size })

  for (let index = 0; index < init.total_chunks; index += 1) {
    if (received.has(index)) continue
    const start = index * init.chunk_size
    const end = Math.min(start + init.chunk_size, file.size)
    await putChunk(init.upload_id, index, file.slice(start, end))
    uploaded += end - start
    onProgress?.({
      uploaded,
      total: file.size,
      percent: Math.min(1, uploaded / file.size),
    })
  }
  return init.upload_id
}

export const CHUNKED_THRESHOLD = 20 * 1024 * 1024
