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
  sandboxed?: boolean
  /** 执行引擎：Linux / Docker 为 bubblewrap，Windows 桌面为 windows-job。 */
  engine?: string
  /** 非隔离执行的提示；仅 Windows 桌面版返回。 */
  warning?: string | null
}

export function runPython(code: string): Promise<RunCodeResult> {
  return request<RunCodeResult>('/run/code', {
    method: 'POST',
    body: JSON.stringify({ language: 'python', code }),
  })
}
