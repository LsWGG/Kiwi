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
  durable_job_id?: string | null
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
