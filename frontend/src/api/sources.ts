/** 素材 / 导入批次 API。 */
import { request } from '@/api/client'
import type { ImportBatch } from '@/stores/notes'

export interface SourceItem {
  id: string
  kb_id: string
  type: string
  title: string
  raw_path: string
  status: string
  parse_quality: string
  parse_engine: string
  quality_report: Record<string, any>
  scan_status: string
  scan_detail: string
  import_batch_id: string | null
  external_id: string | null
  source_url: string
  content_updated_at: string | null
  parsed_at: string | null
  sha256: string
  created_at: string
}

export interface IngestJob {
  id: string
  kb_id: string
  source_id: string
  kind: string
  status: string
  progress: number
  error: string | null
  touched_page_ids: string[]
  import_batch_id: string | null
  note_id: string | null
  created_at: string
  updated_at: string | null
  source_title: string | null
  source_type: string | null
  note_title: string | null
  touched_pages: Array<{
    id: string
    title: string
    slug: string
    page_type: string
  }>
}

export function listSources(kbId: string, batchId?: string | null) {
  const query = batchId ? `&batch_id=${encodeURIComponent(batchId)}` : ''
  return request<SourceItem[]>(`/sources?kb_id=${encodeURIComponent(kbId)}${query}`)
}

export function listBatches(kbId: string, limit = 100) {
  return request<ImportBatch[]>(
    `/ingest/batches?kb_id=${encodeURIComponent(kbId)}&limit=${limit}`,
  )
}

export function listJobs(kbId: string) {
  return request<IngestJob[]>(`/ingest/jobs?kb_id=${encodeURIComponent(kbId)}`)
}

export function getJob(kbId: string, jobId: string) {
  return request<IngestJob>(
    `/ingest/jobs/${encodeURIComponent(jobId)}?kb_id=${encodeURIComponent(kbId)}`,
  )
}

export interface CompileResult {
  jobs: Array<{ job_id: string; source_id: string }>
  count: number
  requested: number
  skipped: number
}

/** 触发编译；后端单次最多接收 20 个，调用方负责分批。 */
export function compileSources(kbId: string, sourceIds: string[]) {
  return request<CompileResult>('/ingest/compile', {
    method: 'POST',
    kbId,
    body: JSON.stringify({ source_ids: sourceIds }),
  })
}

/** 重新解析素材（OCR 复核 / 解析失败重试）。 */
export function reparseSource(kbId: string, sourceId: string) {
  return request<{ job_id: string; status: string }>(
    `/sources/${sourceId}/reparse`,
    { method: 'POST', kbId },
  )
}

export function deleteSource(kbId: string, sourceId: string) {
  return request<void>(`/sources/${sourceId}`, { method: 'DELETE', kbId })
}

export function cancelBatch(kbId: string, batchId: string) {
  return request<ImportBatch>(`/ingest/batches/${batchId}/cancel`, {
    method: 'POST',
    kbId,
  })
}

export function closeBatch(kbId: string, batchId: string) {
  return request<ImportBatch>(`/ingest/batches/${batchId}/close`, {
    method: 'POST',
    kbId,
  })
}
