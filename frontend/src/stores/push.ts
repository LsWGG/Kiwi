import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { request } from '@/api/client'

export interface PushDevice {
  id: string
  endpoint: string
  user_agent: string
  created_at: string
  last_success_at: string | null
  failure_count: number
}

export interface PushStatus {
  enabled: boolean
  reminder_hour: number
  weekly_report: boolean
  public_key: string
  contact: string
  subscriptions: PushDevice[]
  last_daily_date: string | null
  last_weekly_date: string | null
}

export interface PushResult {
  sent: number
  failed: number
  removed: number
}

/** VAPID 公钥是 base64url（无填充），PushManager 需要 ArrayBuffer。 */
function urlBase64ToArrayBuffer(value: string): ArrayBuffer {
  const padding = '='.repeat((4 - (value.length % 4)) % 4)
  const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(base64)
  const buffer = new ArrayBuffer(raw.length)
  const bytes = new Uint8Array(buffer)
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i)
  return buffer
}

export const usePushStore = defineStore('push', () => {
  const status = ref<PushStatus | null>(null)
  const loading = ref(false)
  const busy = ref(false)
  const subscribed = ref(false)
  const browserEndpoint = ref('')
  const permission = ref<NotificationPermission | 'unsupported'>('default')

  const supported = computed(
    () =>
      typeof window !== 'undefined' &&
      'Notification' in window &&
      'serviceWorker' in navigator &&
      'PushManager' in window,
  )
  const devices = computed(() => status.value?.subscriptions ?? [])

  async function refreshBrowser() {
    if (!supported.value) {
      permission.value = 'unsupported'
      subscribed.value = false
      browserEndpoint.value = ''
      return
    }
    permission.value = Notification.permission
    try {
      const registration = await navigator.serviceWorker.getRegistration('/')
      const subscription = registration
        ? await registration.pushManager.getSubscription()
        : null
      subscribed.value = !!subscription
      browserEndpoint.value = subscription?.endpoint ?? ''
    } catch {
      subscribed.value = false
      browserEndpoint.value = ''
    }
  }

  async function load() {
    loading.value = true
    try {
      status.value = await request<PushStatus>('/push/status')
      await refreshBrowser()
    } finally {
      loading.value = false
    }
  }

  async function setEnabled(enabled: boolean) {
    status.value = await request<PushStatus>('/push/settings', {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    })
  }

  async function saveSchedule(reminderHour: number, weeklyReport: boolean) {
    status.value = await request<PushStatus>('/push/settings', {
      method: 'PATCH',
      body: JSON.stringify({
        reminder_hour: reminderHour,
        weekly_report: weeklyReport,
      }),
    })
  }

  /** 请求浏览器权限并在当前设备建立推送订阅。 */
  async function subscribe() {
    if (!supported.value) throw new Error('当前浏览器不支持 Web Push')
    busy.value = true
    try {
      const result = await Notification.requestPermission()
      permission.value = result
      if (result !== 'granted') {
        throw new Error('需要允许通知权限才能接收提醒')
      }
      if (!status.value || !status.value.public_key) {
        await load()
      }
      const publicKey = status.value?.public_key
      if (!publicKey) throw new Error('推送服务尚未初始化，请稍后重试')

      const registration = await navigator.serviceWorker.register('/sw.js')
      const existing = await registration.pushManager.getSubscription()
      const subscription =
        existing ??
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToArrayBuffer(publicKey),
        }))
      const json = subscription.toJSON()
      const keys = json.keys
      if (!json.endpoint || !keys?.p256dh || !keys?.auth) {
        throw new Error('浏览器未返回完整的推送密钥，请重试')
      }
      await request('/push/subscribe', {
        method: 'POST',
        body: JSON.stringify({
          endpoint: json.endpoint,
          keys: { p256dh: keys.p256dh, auth: keys.auth },
          user_agent: navigator.userAgent,
        }),
      })
      subscribed.value = true
      browserEndpoint.value = json.endpoint
      await load()
    } finally {
      busy.value = false
    }
  }

  async function unsubscribe() {
    busy.value = true
    try {
      const registration = await navigator.serviceWorker.getRegistration('/')
      const subscription = registration
        ? await registration.pushManager.getSubscription()
        : null
      if (subscription) {
        try {
          await request('/push/unsubscribe', {
            method: 'POST',
            body: JSON.stringify({ endpoint: subscription.endpoint }),
          })
        } finally {
          await subscription.unsubscribe()
        }
      }
      subscribed.value = false
      browserEndpoint.value = ''
      await load()
    } finally {
      busy.value = false
    }
  }

  async function removeDevice(endpoint: string) {
    busy.value = true
    try {
      await request('/push/unsubscribe', {
        method: 'POST',
        body: JSON.stringify({ endpoint }),
      })
      if (endpoint === browserEndpoint.value) {
        const registration = await navigator.serviceWorker.getRegistration('/')
        const subscription = registration
          ? await registration.pushManager.getSubscription()
          : null
        await subscription?.unsubscribe()
        subscribed.value = false
        browserEndpoint.value = ''
      }
      await load()
    } finally {
      busy.value = false
    }
  }

  async function sendTest(): Promise<PushResult> {
    return request<PushResult>('/push/test', { method: 'POST' })
  }

  return {
    status,
    loading,
    busy,
    subscribed,
    browserEndpoint,
    permission,
    supported,
    devices,
    load,
    refreshBrowser,
    setEnabled,
    saveSchedule,
    subscribe,
    unsubscribe,
    removeDevice,
    sendTest,
  }
})
