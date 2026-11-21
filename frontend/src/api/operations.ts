/** 运维接口：持久化任务、审计、备份与构建信息。 */
import { request, uploadWithProgress, type UploadProgressHandler } from './client'

export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface Job {
  id: string
  kind: string
  status: JobStatus
  payload: Record<string, unknown>
  result: Record<string, unknown>
  error: string | null
  message: string | null
  kb_id: string | null
  ref_id: string | null
  idempotency_key: string | null
  priority: number
  attempts: number
  max_attempts: number
  progress: number
  cancel_requested: boolean
  run_after: string
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface JobList {
  items: Job[]
  total: number
  retention_days: number
}

export interface AuditEntry {
  id: string
  kb_id: string | null
  action: string
  target_type: string
  target_id: string | null
  detail: Record<string, unknown>
  actor: string
  ip: string | null
  request_id: string | null
  note: string
  created_at: string
}

export interface AuditList {
  items: AuditEntry[]
  total: number
  retention_days: number
}

export interface BackupFile {
  name: string
  size: number
  sha256?: string
}

export interface BackupEntry {
  name: string
  format?: string
  version?: number
  created_at?: string
  imported_at?: string
  original_name?: string | null
  trigger?: string
  app_version?: string
  git_commit?: string
  uploads_included?: boolean
  retention_days?: number
  files?: BackupFile[]
  path?: string
  [key: string]: unknown
}

export interface BackupList {
  enabled: boolean
  directory: string
  retention_days: number
  interval_hours: number
  items: BackupEntry[]
}

export interface BuildInfo {
  name: string
  version: string
  commit: string
  built_at: string
  started_at?: string
}

export function listJobs(
  params: { limit?: number; offset?: number; status?: string; kind?: string; kbId?: string | null } = {},
) {
  const query = new URLSearchParams()
  if (params.limit) query.set('limit', String(params.limit))
  if (params.offset) query.set('offset', String(params.offset))
  if (params.status) query.set('status', params.status)
  if (params.kind) query.set('kind', params.kind)
  if (params.kbId) query.set('kb_id', params.kbId)
  const suffix = query.toString() ? `?${query}` : ''
  return request<JobList>(`/jobs${suffix}`)
}

export function retryJob(id: string) {
  return request<Job>(`/jobs/${id}/retry`, { method: 'POST' })
}

export function cancelJob(id: string) {
  return request<Job>(`/jobs/${id}/cancel`, { method: 'POST' })
}

export function listAudit(params: { limit?: number; offset?: number; kbId?: string | null; action?: string } = {}) {
  const query = new URLSearchParams()
  if (params.limit) query.set('limit', String(params.limit))
  if (params.offset) query.set('offset', String(params.offset))
  if (params.kbId) query.set('kb_id', params.kbId)
  if (params.action) query.set('action', params.action)
  const suffix = query.toString() ? `?${query}` : ''
  return request<AuditList>(`/audit${suffix}`)
}

export function auditExportUrl(kbId?: string | null, action?: string) {
  const query = new URLSearchParams()
  if (kbId) query.set('kb_id', kbId)
  if (action) query.set('action', action)
  const suffix = query.toString() ? `?${query}` : ''
  return `/api/audit/export.csv${suffix}`
}

export function listBackups() {
  return request<BackupList>('/maintenance/backups')
}

export function triggerBackup() {
  return request<{ job_id: string; status: string }>('/maintenance/backups', { method: 'POST' })
}

/** 浏览器直接下载 zip；使用 <a download>，不经过 fetch 以免大文件进内存。 */
export function backupDownloadUrl(name: string) {
  return `/api/maintenance/backups/${encodeURIComponent(name)}/download`
}

/** 导入 zip 备份：只保存为一份快照，不覆盖当前数据库。 */
export function importBackup(file: File, onProgress?: UploadProgressHandler) {
  const formData = new FormData()
  formData.append('file', file)
  return uploadWithProgress<BackupEntry>('/maintenance/backups/import', formData, null, onProgress)
}

export function getBackendBuildInfo() {
  return request<BuildInfo>('/maintenance/build-info')
}

/** 不走 /api 前缀：build-info.json 是前端静态产物。 */
export async function getFrontendBuildInfo(): Promise<BuildInfo | null> {
  try {
    const res = await fetch('/build-info.json', { cache: 'no-store' })
    if (!res.ok) return null
    return (await res.json()) as BuildInfo
  } catch {
    return null
  }
}
