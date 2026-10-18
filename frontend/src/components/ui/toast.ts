// 轻量 toast 系统：响应式队列 + 定时自动消失。
import { reactive } from 'vue'

export interface ToastItem {
  id: number
  type: 'success' | 'error' | 'info'
  message: string
}

export const toasts = reactive<ToastItem[]>([])

let seq = 0

function push(type: ToastItem['type'], message: string, duration = 2600) {
  const id = ++seq
  toasts.push({ id, type, message })
  setTimeout(() => dismiss(id), duration)
}

export function dismiss(id: number) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

export const toast = {
  success: (msg: string) => push('success', msg),
  error: (msg: string) => push('error', msg, 3600),
  info: (msg: string) => push('info', msg),
}