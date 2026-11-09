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
  DEFAULT_APPEARANCE,
  EMPTY_THEME_OVERRIDES,
  type ThemeActive,
  type ThemeAppearance,
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

  // ---------- 亮 / 暗色切换 ----------
  const appearance = ref<ThemeAppearance>({ ...DEFAULT_APPEARANCE })
  const appearanceLoaded = ref(false)
  /** 当前生效主题自身的明暗模式；顶部切换图标与自动规则都以它为准。 */
  const currentMode = computed<'light' | 'dark'>(() =>
    active.value?.theme?.mode === 'dark' ? 'dark' : 'light',
  )
  let autoStarted = false
  let autoTimer: number | null = null
  let mediaQuery: MediaQueryList | null = null
  let manualHold = false
  let holdTimer: number | null = null
  let autoSwitching = false
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
      try {
        await refreshAppearance()
        startAutoSwitch()
        await applyAutoMode(true)
      } catch {
        // 外观偏好不可用时保持当前主题，不阻塞启动。
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
    // 手动启用主题（画廊 / 顶栏切换）后，自动规则等到下一个切换边界再接管，
    // 避免刚点完立刻被定时规则改回去。
    if (!autoSwitching && autoStarted && appearance.value.switch_mode !== 'off') {
      manualHold = true
      releaseHoldAfterBoundary()
    }
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

  // ---------- 亮 / 暗色外观偏好 ----------

  async function refreshAppearance(): Promise<ThemeAppearance> {
    const data = await request<ThemeAppearance>('/themes/appearance')
    appearance.value = { ...DEFAULT_APPEARANCE, ...data }
    appearanceLoaded.value = true
    return appearance.value
  }

  async function saveAppearance(next: ThemeAppearance): Promise<ThemeAppearance> {
    const data = await request<ThemeAppearance>('/themes/appearance', {
      method: 'PUT',
      body: JSON.stringify(next),
    })
    appearance.value = { ...DEFAULT_APPEARANCE, ...data }
    appearanceLoaded.value = true
    manualHold = false
    restartAutoTimer()
    await applyAutoMode(true)
    return appearance.value
  }

  function parseMinutes(value: string): number {
    const [hour, minute] = value.split(':').map((part) => Number.parseInt(part, 10))
    return (
      (Number.isFinite(hour) ? hour : 0) * 60 +
      (Number.isFinite(minute) ? minute : 0)
    )
  }

  function systemPrefersDark(): boolean {
    return typeof window !== 'undefined' && !!window.matchMedia
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
      : false
  }

  /** 定时规则：支持跨午夜（如 19:00 → 07:00）；起止相同表示不自动变暗。 */
  function inDarkRange(now = new Date()): boolean {
    const start = parseMinutes(appearance.value.dark_start)
    const end = parseMinutes(appearance.value.dark_end)
    if (start === end) return false
    const current = now.getHours() * 60 + now.getMinutes()
    return start < end
      ? current >= start && current < end
      : current >= start || current < end
  }

  function autoTargetMode(): 'light' | 'dark' | null {
    if (appearance.value.switch_mode === 'system') {
      return systemPrefersDark() ? 'dark' : 'light'
    }
    if (appearance.value.switch_mode === 'schedule') {
      return inDarkRange() ? 'dark' : 'light'
    }
    return null
  }

  async function switchToMode(mode: 'light' | 'dark'): Promise<void> {
    const key =
      mode === 'dark' ? appearance.value.dark_theme : appearance.value.light_theme
    if (!key || key === active.value?.key) return
    autoSwitching = true
    try {
      await activate(key)
    } finally {
      autoSwitching = false
    }
  }

  async function applyAutoMode(force = false): Promise<void> {
    const target = autoTargetMode()
    if (!target || (!force && manualHold) || currentMode.value === target) return
    try {
      await switchToMode(target)
    } catch {
      // 自动切换失败（离线 / 主题被删除）时保持当前外观，由下次检查重试。
    }
  }

  /** 顶栏亮 / 暗切换：立即切到另一套主题，并让自动规则等到下一边界。 */
  async function toggleAppearance(): Promise<void> {
    const target = currentMode.value === 'dark' ? 'light' : 'dark'
    const key =
      target === 'dark' ? appearance.value.dark_theme : appearance.value.light_theme
    if (!key) throw new Error('请先在设置 → 主题中绑定亮色与暗色主题')
    await activate(key)
  }

  function nextBoundaryDelay(): number {
    const now = new Date()
    const current = now.getHours() * 60 + now.getMinutes()
    const points = [
      parseMinutes(appearance.value.dark_start),
      parseMinutes(appearance.value.dark_end),
    ]
    const delays = points
      .filter((point) => point !== current)
      .map((point) => (point > current ? point - current : 24 * 60 - current + point))
    const minutes = delays.length ? Math.min(...delays) : 24 * 60
    return Math.max(5_000, minutes * 60_000 + 1_000)
  }

  function releaseHoldAfterBoundary(): void {
    if (holdTimer !== null) {
      window.clearTimeout(holdTimer)
      holdTimer = null
    }
    if (appearance.value.switch_mode !== 'schedule') return
    holdTimer = window.setTimeout(() => {
      holdTimer = null
      manualHold = false
      void applyAutoMode(true)
    }, nextBoundaryDelay())
  }

  function onSystemSchemeChange(): void {
    // 系统明暗变化是自动规则的信号：解除手动保持并立即应用。
    manualHold = false
    void applyAutoMode(true)
  }

  function restartAutoTimer(): void {
    if (autoTimer !== null) {
      window.clearInterval(autoTimer)
      autoTimer = null
    }
    if (!appearanceLoaded.value || appearance.value.switch_mode === 'off') return
    // 定时规则每 30 秒检查一次；跟随系统也保留兜底轮询。
    autoTimer = window.setInterval(() => {
      void applyAutoMode()
    }, 30_000)
  }

  function startAutoSwitch(): void {
    if (autoStarted) return
    autoStarted = true
    if (typeof window !== 'undefined' && window.matchMedia) {
      mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
      mediaQuery.addEventListener('change', onSystemSchemeChange)
    }
    restartAutoTimer()
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
    appearance,
    appearanceLoaded,
    currentMode,
    refreshAppearance,
    saveAppearance,
    toggleAppearance,
    applyAutoMode,
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
