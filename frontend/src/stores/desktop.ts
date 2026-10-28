/**
 * 桌面运行状态。
 *
 * Docker / Web 构建不请求 `/api/desktop/*`，`ready` 直接为 true，所有能力
 * 按「可用」处理。桌面构建在登录后加载状态与本地设置；加载失败时保留最
 * 保守的离线默认值，绝不因为接口失败而误开联网能力。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { request } from '@/api/client'
import { IS_DESKTOP } from '@/desktop/env'

export interface DesktopCapabilities {
  online_models: boolean
  link_fetch: boolean
  remote_import: boolean
  online_ocr: boolean
  feishu: boolean
  web_push: boolean
  study_web_search: boolean
  youtube_embed: boolean
  external_images: boolean
  local_code_execution: boolean
}

export interface DesktopEmbeddingState {
  enabled: boolean
  provider: string
  state: string
}

export interface DesktopLlmState {
  configured: boolean
  remote_allowed: boolean
}

export interface DesktopLocalCodeState {
  enabled: boolean
  available: boolean
  implementation: string
}

export interface DesktopStatus {
  desktop: boolean
  version: string
  data_dir: string
  log_dir: string
  embedding: DesktopEmbeddingState
  llm: DesktopLlmState
  local_code: DesktopLocalCodeState
  capabilities: DesktopCapabilities
}

export interface DesktopSettings {
  version: number
  allow_online_models: boolean
  acknowledged_online_models_at: string | null
  local_code_execution: boolean
  acknowledged_local_code_at: string | null
  local_code_timeout_seconds: number
  updated_at: string | null
}

export interface DesktopSettingsPatch {
  allow_online_models?: boolean
  local_code_execution?: boolean
  local_code_timeout_seconds?: number
  acknowledge_risk?: boolean
}

/** 后端不可达时的能力假设：除本机执行外全部关闭。 */
export const OFFLINE_CAPABILITIES: DesktopCapabilities = {
  online_models: false,
  link_fetch: false,
  remote_import: false,
  online_ocr: false,
  feishu: false,
  web_push: false,
  study_web_search: false,
  youtube_embed: false,
  external_images: false,
  local_code_execution: false,
}

export const SAFE_DESKTOP_SETTINGS: DesktopSettings = {
  version: 1,
  allow_online_models: false,
  acknowledged_online_models_at: null,
  local_code_execution: false,
  acknowledged_local_code_at: null,
  local_code_timeout_seconds: 60,
  updated_at: null,
}

export const useDesktopStore = defineStore('desktop', () => {
  const status = ref<DesktopStatus | null>(null)
  const settings = ref<DesktopSettings>({ ...SAFE_DESKTOP_SETTINGS })
  const ready = ref(!IS_DESKTOP)
  const loading = ref(false)
  const error = ref('')
  let inflight: Promise<void> | null = null

  const isDesktop = IS_DESKTOP
  const capabilities = computed(
    () => status.value?.capabilities ?? OFFLINE_CAPABILITIES,
  )
  const version = computed(() => status.value?.version ?? '')
  const dataDir = computed(() => status.value?.data_dir ?? '')
  const logDir = computed(() => status.value?.log_dir ?? '')
  const embeddingEnabled = computed(
    () => status.value?.embedding.enabled ?? false,
  )
  const embeddingProvider = computed(
    () => status.value?.embedding.provider ?? 'none',
  )
  const llmConfigured = computed(() => status.value?.llm.configured ?? false)
  const onlineModelsAllowed = computed(
    () => settings.value.allow_online_models,
  )
  const localCodeEnabled = computed(() => settings.value.local_code_execution)
  const localCodeAvailable = computed(
    () => status.value?.local_code.available ?? false,
  )
  const localCodeImplementation = computed(
    () => status.value?.local_code.implementation ?? '',
  )
  const localCodeTimeout = computed(
    () => settings.value.local_code_timeout_seconds,
  )

  async function fetchStatus(): Promise<void> {
    status.value = await request<DesktopStatus>('/desktop/status')
  }

  async function load(force = false): Promise<void> {
    if (!IS_DESKTOP) {
      ready.value = true
      return
    }
    if (inflight) return inflight
    if (ready.value && !force && status.value) return

    loading.value = true
    error.value = ''
    inflight = (async () => {
      try {
        const [nextStatus, nextSettings] = await Promise.all([
          request<DesktopStatus>('/desktop/status'),
          request<DesktopSettings>('/desktop/settings'),
        ])
        status.value = nextStatus
        settings.value = nextSettings
      } catch (e: any) {
        error.value = e?.message || '读取桌面状态失败'
      } finally {
        loading.value = false
        ready.value = true
        inflight = null
      }
    })()
    return inflight
  }

  async function updateSettings(
    patch: DesktopSettingsPatch,
  ): Promise<DesktopSettings> {
    const updated = await request<DesktopSettings>('/desktop/settings', {
      method: 'PUT',
      body: JSON.stringify(patch),
    })
    settings.value = updated
    // capabilities / llm.remote_allowed 随设置变化，重新读取一次状态。
    try {
      await fetchStatus()
    } catch {
      // 设置已经保存成功，状态刷新失败不回滚。
    }
    return updated
  }

  return {
    isDesktop,
    status,
    settings,
    ready,
    loading,
    error,
    capabilities,
    version,
    dataDir,
    logDir,
    embeddingEnabled,
    embeddingProvider,
    llmConfigured,
    onlineModelsAllowed,
    localCodeEnabled,
    localCodeAvailable,
    localCodeImplementation,
    localCodeTimeout,
    load,
    updateSettings,
  }
})
