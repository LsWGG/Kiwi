/**
 * 主题插件状态：当前主题、画廊列表、导入导出与覆盖值。
 *
 * 主题是全局共享配置，切换后立即写入 `<html>` 的 CSS 变量与 data 属性，
 * 并缓存到 localStorage，保证刷新首屏不闪默认配色。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  download,
  request,
  upload,
  uploadWithProgress,
  type UploadProgressHandler,
} from '@/api/client'
import {
  applyActiveTheme,
  applyCachedTheme,
  cacheActiveTheme,
} from '@/theme/apply'
import {
  EMPTY_THEME_OVERRIDES,
  type ThemeActive,
  type ThemeBackgroundUpload,
  type ThemeDevSpec,
  type ThemeInspection,
  type ThemeItem,
  type ThemeOverrides,
} from '@/theme/types'

export const useThemeStore = defineStore('theme', () => {
  const themes = ref<ThemeItem[]>([])
  const active = ref<ThemeActive | null>(null)
  const loading = ref(false)
  const loaded = ref(false)
  const applyingKey = ref('')

  let listPromise: Promise<ThemeItem[]> | null = null
  let initPromise: Promise<void> | null = null

  const activeKey = computed(() => active.value?.key || '')
  const activeTheme = computed(
    () => themes.value.find((item) => item.key === activeKey.value) || null,
  )
  const builtinThemes = computed(() => themes.value.filter((item) => item.builtin))
  const installedThemes = computed(() => themes.value.filter((item) => !item.builtin))
  const overrides = computed<ThemeOverrides>(
    () => active.value?.overrides || { ...EMPTY_THEME_OVERRIDES },
  )
  /** 用户是否对当前主题做了个性化覆盖（背景、透明度、强调色）。 */
  const customized = computed(() => {
    const value = overrides.value
    return Boolean(
      value.background_image ||
        value.background_video ||
        value.background_size ||
        value.background_position ||
        value.background_repeat ||
        value.background_dim !== null ||
        value.background_blur !== null ||
        value.surface_opacity !== null ||
        value.surface_blur !== null ||
        value.accent ||
        value.learn_accent,
    )
  })

  function applyActive(data: ThemeActive | null): void {
    active.value = data
    cacheActiveTheme(data)
    applyActiveTheme(data)
  }

  function syncActiveFlags(): void {
    const key = activeKey.value
    themes.value = themes.value.map((item) => ({
      ...item,
      active: item.key === key,
    }))
    reorderThemes()
  }

  /** 与后端画廊排序保持一致：当前主题 → 内置主题 → 已安装主题。 */
  function reorderThemes(): void {
    themes.value = [...themes.value].sort((a, b) => {
      if (a.active !== b.active) return a.active ? -1 : 1
      if (a.builtin !== b.builtin) return a.builtin ? -1 : 1
      // 与后端 name.casefold() 的码点排序保持一致，避免刷新前后顺序跳动。
      const left = a.name.toLowerCase()
      const right = b.name.toLowerCase()
      return left < right ? -1 : left > right ? 1 : 0
    })
  }

  async function refreshActive(): Promise<ThemeActive> {
    const data = await request<ThemeActive>('/themes/active')
    applyActive(data)
    return data
  }

  /**
   * 启动时先套用缓存主题，再向后端确认。
   * 未登录 / 离线时保留缓存，不抛出错误阻塞启动。
   */
  function init(): Promise<void> {
    if (initPromise) return initPromise
    applyCachedTheme()
    initPromise = (async () => {
      try {
        await refreshActive()
        syncActiveFlags()
      } catch {
        // 保留缓存主题即可，等进入设置页或下次启动再同步。
      }
    })()
    return initPromise
  }

  async function loadList(force = false): Promise<ThemeItem[]> {
    if (loaded.value && !force) return themes.value
    if (listPromise && !force) return listPromise
    listPromise = (async () => {
      try {
        themes.value = await request<ThemeItem[]>('/themes')
        loaded.value = true
        return themes.value
      } finally {
        listPromise = null
      }
    })()
    return listPromise
  }

  async function load(): Promise<ThemeItem[]> {
    loading.value = true
    try {
      return await loadList(true)
    } finally {
      loading.value = false
    }
  }

  /** 应用主题。overrides 不传表示沿用已保存的覆盖；传空对象表示清空。 */
  async function activate(
    key: string,
    nextOverrides?: ThemeOverrides,
  ): Promise<ThemeActive> {
    applyingKey.value = key
    try {
      const body: Record<string, unknown> = { key }
      if (nextOverrides !== undefined) body.overrides = nextOverrides
      const data = await request<ThemeActive>('/themes/active', {
        method: 'PUT',
        body: JSON.stringify(body),
      })
      // 后端会用权威数据回填（例如主题被停用时回落到内置主题）。
      applyActive(data)
      syncActiveFlags()
      return data
    } finally {
      applyingKey.value = ''
    }
  }

  async function saveOverrides(next: ThemeOverrides): Promise<ThemeActive> {
    if (!active.value) throw new Error('当前还没有启用主题')
    return activate(active.value.key, next)
  }

  async function resetOverrides(): Promise<ThemeActive> {
    if (!active.value) throw new Error('当前还没有启用主题')
    return activate(active.value.key, { ...EMPTY_THEME_OVERRIDES })
  }

  /** 上传自定义背景（图片 / 动图 / 视频，≤100MB），返回 /media 站内 URL。 */
  async function uploadBackground(
    file: File,
    onProgress?: UploadProgressHandler,
    signal?: AbortSignal,
  ): Promise<ThemeBackgroundUpload> {
    const form = new FormData()
    form.append('file', file)
    return uploadWithProgress<ThemeBackgroundUpload>(
      '/themes/background',
      form,
      null,
      onProgress,
      signal,
    )
  }

  /** 删除未被当前覆盖值引用的上传背景（用于取消编辑后的清理）。 */
  async function deleteBackground(url: string): Promise<void> {
    await request<void>(
      `/themes/background?url=${encodeURIComponent(url)}`,
      { method: 'DELETE' },
    )
  }

  /** 启用 / 停用已安装主题。停用当前主题时后端会回落到内置主题。 */
  async function setEnabled(item: ThemeItem, enabled: boolean): Promise<void> {
    if (item.builtin) return
    await request(`/plugins/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    })
    await Promise.all([loadList(true), refreshActive()])
    syncActiveFlags()
  }

  async function remove(item: ThemeItem): Promise<void> {
    if (item.builtin) throw new Error('内置主题不能删除')
    await request<void>(`/plugins/${item.id}`, { method: 'DELETE' })
    await Promise.all([loadList(true), refreshActive()])
    syncActiveFlags()
  }

  async function inspectFile(file: File): Promise<ThemeInspection> {
    const form = new FormData()
    form.append('file', file)
    return upload<ThemeInspection>('/themes/inspect', form)
  }

  async function importFile(file: File, overwrite = false): Promise<ThemeItem> {
    const form = new FormData()
    form.append('file', file)
    const suffix = overwrite ? '?overwrite=true' : ''
    const item = await upload<ThemeItem>(`/themes/import${suffix}`, form)
    // 覆盖同 key 主题后样式 URL 会变化：刷新当前主题与列表。
    await Promise.all([loadList(true), refreshActive()])
    syncActiveFlags()
    return item
  }

  async function exportTheme(item: ThemeItem): Promise<string> {
    const fallback = `${item.key}-${item.version || '1.0.0'}.zip`
    if (item.builtin) {
      return download(
        `/themes/builtin/${encodeURIComponent(item.key)}/export`,
        fallback,
      )
    }
    return download(`/plugins/${item.id}/export`, fallback)
  }

  async function downloadDevKit(): Promise<string> {
    return download('/themes/dev-kit', 'kiwi-theme-dev-kit.zip')
  }

  async function spec(): Promise<ThemeDevSpec> {
    return request<ThemeDevSpec>('/themes/spec')
  }

  return {
    themes,
    active,
    loading,
    loaded,
    applyingKey,
    activeKey,
    activeTheme,
    builtinThemes,
    installedThemes,
    overrides,
    customized,
    init,
    loadList,
    load,
    refreshActive,
    activate,
    saveOverrides,
    resetOverrides,
    uploadBackground,
    deleteBackground,
    setEnabled,
    remove,
    inspectFile,
    importFile,
    exportTheme,
    downloadDevKit,
    spec,
  }
})
