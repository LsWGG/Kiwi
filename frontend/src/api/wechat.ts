/** 微信 ClawBot 渠道：状态、扫码登录、允许联系人与定时推送。 */
import { request } from './client'

export interface WeChatLoginState {
  status: string
  message?: string
  qrcode?: string
  qr?: string
  started_at?: number
  at?: number
}

export interface WeChatSchedule {
  id: string
  sender: string
  kb_ids: string[]
  kb_id?: string
  prompt: string
  cron: string
  description: string
  enabled: boolean
  last_fire?: string
  created_at: number
}

export interface WeChatStatus {
  system_enabled: boolean
  enabled: boolean
  connected: boolean
  login_at: number
  remaining_seconds: number
  login: WeChatLoginState
  default_kb_ids: string[]
  default_kb_id?: string
  allow_write: boolean
  schedules: WeChatSchedule[]
  last_contact: { sender: string; at: number } | null
}

export interface WeChatSettingsPayload {
  enabled?: boolean
  default_kb_ids?: string[]
  allow_write?: boolean
}

export interface WeChatSchedulePayload {
  cron: string
  prompt: string
  kb_ids?: string[]
}

export interface WeChatSchedulePreview {
  cron: string
  description: string
  next_runs: string[]
}

export function getWeChatStatus() {
  return request<WeChatStatus>('/wechat/status')
}

export function updateWeChatSettings(payload: WeChatSettingsPayload) {
  return request<WeChatStatus>('/wechat/settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function startWeChatLogin() {
  return request<{ system_enabled: boolean; login: WeChatLoginState }>(
    '/wechat/login',
    { method: 'POST', body: JSON.stringify({}) },
  )
}

export function logoutWeChat() {
  return request<WeChatStatus>('/wechat/logout', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function listWeChatSchedules() {
  return request<{ items: WeChatSchedule[] }>('/wechat/schedules')
}

export function createWeChatSchedule(payload: WeChatSchedulePayload) {
  return request<WeChatSchedule>('/wechat/schedules', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function previewWeChatSchedule(text: string) {
  return request<WeChatSchedulePreview>('/wechat/schedules/preview', {
    method: 'POST',
    body: JSON.stringify({ text }),
  })
}

export function toggleWeChatSchedule(id: string, enabled: boolean) {
  return request<{ ok: boolean }>(
    `/wechat/schedules/${encodeURIComponent(id)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    },
  )
}

export function deleteWeChatSchedule(id: string) {
  return request<void>(`/wechat/schedules/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

export function sendWeChatTest(text: string) {
  return request<{ ok: boolean; queued: boolean }>('/wechat/test', {
    method: 'POST',
    body: JSON.stringify({ text }),
  })
}
