/**
 * 可选访问控制：后端设置 KIWI_ACCESS_TOKEN 后，前端先展示令牌登录页。
 *
 * 登录成功后由后端下发 HttpOnly Cookie，前端不保存令牌明文；
 * 刷新页面时通过 /api/auth/status 恢复登录态。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { request } from '@/api/client'

interface AuthStatus {
  enabled: boolean
  authenticated: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const enabled = ref(false)
  const authenticated = ref(true)
  const checking = ref(true)
  const loggingIn = ref(false)

  /** 访问控制已开启且尚未登录时，App 只渲染登录页。 */
  const blocked = computed(() => enabled.value && !authenticated.value)

  async function check() {
    try {
      const status = await request<AuthStatus>('/auth/status')
      enabled.value = !!status.enabled
      authenticated.value = !status.enabled || !!status.authenticated
    } catch {
      // 状态接口不可用时按未启用处理，避免网络故障把用户锁在登录页外。
      enabled.value = false
      authenticated.value = true
    } finally {
      checking.value = false
    }
    return authenticated.value
  }

  function markUnauthorized() {
    enabled.value = true
    authenticated.value = false
  }

  async function login(token: string) {
    loggingIn.value = true
    try {
      await request('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ token }),
      })
      enabled.value = true
      authenticated.value = true
    } finally {
      loggingIn.value = false
    }
  }

  async function logout() {
    try {
      await request('/auth/logout', { method: 'POST' })
    } finally {
      authenticated.value = false
    }
  }

  return { enabled, authenticated, checking, loggingIn, blocked, check, markUnauthorized, login, logout }
})
