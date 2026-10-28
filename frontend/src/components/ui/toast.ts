// 轻量 toast 系统：响应式队列 + 定时自动消失。
import { reactive } from 'vue'

export interface ToastItem {
  id: number
  type: 'success' | 'error' | 'info' | 'progress'
  message: string
  /** 0–1；仅 type='progress' 时使用。 */
  progress?: number
  /** 仅常驻进度提示：用户主动取消时的回调。 */
  onCancel?: () => void
}

export interface ToastHandle {
  id: number
  update: (message: string, progress?: number) => void
  dismiss: () => void
}

export const toasts = reactive<ToastItem[]>([])

let seq = 0

function push(
  type: ToastItem['type'],
  message: string,
  duration: number | null = 2600,
  progress?: number,
  onCancel?: () => void,
) {
  const id = ++seq
  toasts.push({ id, type, message, progress, onCancel })
  if (duration !== null) setTimeout(() => dismiss(id), duration)
  return id
}

export function dismiss(id: number) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

export const toast = {
  success: (msg: string) => push('success', msg),
  error: (msg: string) => push('error', msg, 3600),
  info: (msg: string) => push('info', msg),
  /** 常驻进度提示；调用方需在结束（成功或失败）后 dismiss。 */
  progress: (msg: string, initial = 0, onCancel?: () => void): ToastHandle => {
    const id = push('progress', msg, null, initial, onCancel)
    return {
      id,
      update: (message: string, progress?: number) => {
        const item = toasts.find((t) => t.id === id)
        if (!item) return
        item.message = message
        if (progress !== undefined) item.progress = progress
      },
      dismiss: () => dismiss(id),
    }
  },
}