/** 代码块运行接口（目前仅 Python，由后端受限子进程执行）。 */
import { request } from './client'

export interface RunCodeResult {
  ok: boolean
  stdout: string
  stderr: string
  exit_code: number | null
  duration_ms: number
  timed_out: boolean
  truncated: boolean
}

export function runPython(code: string): Promise<RunCodeResult> {
  return request<RunCodeResult>('/run/code', {
    method: 'POST',
    body: JSON.stringify({ language: 'python', code }),
  })
}
