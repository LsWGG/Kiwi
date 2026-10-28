/** Notebook 内核 API：执行单元格、状态、重启与 `.ipynb` 导出。 */
import { request } from '@/api/client'
import { useNotesStore } from '@/stores/notes'
import type { NotebookOutput } from './types'

export interface ExecuteResult {
  ok: boolean
  cell_id: string
  outputs: NotebookOutput[]
  execution_count: number
  duration_ms: number
  timed_out: boolean
  kernel_restarted: boolean
  busy: boolean
  error: string | null
  /** 执行引擎：Linux / Docker 为 bubblewrap，Windows 桌面为 windows-job。 */
  engine?: string
  /** 非隔离执行的提示；仅 Windows 桌面版返回。 */
  warning?: string | null
}

export interface KernelStatus {
  running: boolean
  execution_count: number
  python_version: string
  workdir: string
  busy: boolean
  idle_seconds: number
  sandbox: {
    available: boolean
    engine: string | null
    network: boolean
    sandboxed?: boolean
    warning?: string | null
    writable_paths: string[]
    venv: string
    python_version: string
  }
}

function authHeaders(noteId: string) {
  return useNotesStore().noteHeaders(noteId)
}

export function executeCell(
  kbId: string,
  noteId: string,
  cellId: string,
  code: string,
  timeoutSeconds: number,
) {
  return request<ExecuteResult>(`/notebooks/${noteId}/execute`, {
    method: 'POST',
    kbId,
    headers: authHeaders(noteId),
    body: JSON.stringify({
      cell_id: cellId,
      code,
      timeout_seconds: timeoutSeconds,
    }),
  })
}

export function kernelStatus(kbId: string, noteId: string) {
  return request<KernelStatus>(`/notebooks/${noteId}/status`, {
    kbId,
    headers: authHeaders(noteId),
  })
}

export function restartKernel(kbId: string, noteId: string) {
  return request<KernelStatus>(`/notebooks/${noteId}/restart`, {
    method: 'POST',
    kbId,
    headers: authHeaders(noteId),
  })
}

export function exportUrl(kbId: string, noteId: string) {
  return `/api/notebooks/${noteId}/export?kb_id=${encodeURIComponent(kbId)}`
}
