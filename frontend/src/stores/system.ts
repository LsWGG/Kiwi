/** 系统设置：品牌信息、主题色与线上 OCR 配置，启动时一次性水合。 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { request, upload } from '@/api/client'

export const DEFAULT_APP_NAME = 'Kiwi'
export const DEFAULT_APP_DESCRIPTION = '知识编译与检索系统'
export const DEFAULT_THEME_COLOR = '#5a55c7'
export const DEFAULT_LEARN_THEME_COLOR = '#10b981'

export interface SystemSettings {
  app_name: string
  app_description: string
  logo_url: string
  theme_color: string
  learn_theme_color: string
  ocr_enabled: boolean
  ocr_provider: string
  ocr_api_base: string
  ocr_api_model: string
  has_ocr_api_key: boolean
  ocr_timeout: number
  ocr_language: string
  source: string
}

export interface OcrTestResult {
  ok: boolean
  message: string
  sample_text: string
}

export interface OcrTestPayload {
  api_base?: string
  api_model?: string
  api_key?: string
  timeout?: number
  language?: string
}

export const DEFAULT_SYSTEM_SETTINGS: SystemSettings = {
  app_name: DEFAULT_APP_NAME,
  app_description: DEFAULT_APP_DESCRIPTION,
  logo_url: '',
  theme_color: DEFAULT_THEME_COLOR,
  learn_theme_color: DEFAULT_LEARN_THEME_COLOR,
  ocr_enabled: false,
  ocr_provider: 'openai',
  ocr_api_base: '',
  ocr_api_model: '',
  has_ocr_api_key: false,
  ocr_timeout: 120,
  ocr_language: 'auto',
  source: 'default',
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function normalizeHex(input: string): string {
  const value = input.trim()
  if (/^#[0-9a-fA-F]{6}$/.test(value)) return value.toLowerCase()
  if (/^#[0-9a-fA-F]{3}$/.test(value)) {
    const [r, g, b] = value.slice(1).split('')
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase()
  }
  return DEFAULT_THEME_COLOR
}

function hexToRgb(hex: string): [number, number, number] {
  const value = normalizeHex(hex)
  return [
    Number.parseInt(value.slice(1, 3), 16),
    Number.parseInt(value.slice(3, 5), 16),
    Number.parseInt(value.slice(5, 7), 16),
  ]
}

function rgbTriplet(r: number, g: number, b: number): string {
  return `${Math.round(r)} ${Math.round(g)} ${Math.round(b)}`
}

function hexFromRgb(r: number, g: number, b: number): string {
  const toHex = (v: number) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

/** RGB → HSL（h: 0-360, s/l: 0-1）。 */
function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  const rn = r / 255
  const gn = g / 255
  const bn = b / 255
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
  const delta = max - min
  let h = 0
  if (delta > 0) {
    if (max === rn) h = ((gn - bn) / delta) % 6
    else if (max === gn) h = (bn - rn) / delta + 2
    else h = (rn - gn) / delta + 4
    h *= 60
    if (h < 0) h += 360
  }
  const l = (max + min) / 2
  const s = delta === 0 ? 0 : delta / (1 - Math.abs(2 * l - 1))
  return [h, s, l]
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const hue = ((h % 360) + 360) % 360
  const c = (1 - Math.abs(2 * l - 1)) * clamp(s, 0, 1)
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1))
  const m = l - c / 2
  let rgb: [number, number, number]
  if (hue < 60) rgb = [c, x, 0]
  else if (hue < 120) rgb = [x, c, 0]
  else if (hue < 180) rgb = [0, c, x]
  else if (hue < 240) rgb = [0, x, c]
  else if (hue < 300) rgb = [x, 0, c]
  else rgb = [c, 0, x]
  return [(rgb[0] + m) * 255, (rgb[1] + m) * 255, (rgb[2] + m) * 255]
}

/**
 * 由单一品牌色生成 50–900 色阶。
 * 500 保留用户选择的明度，其余档位按固定明度阶梯推导；
 * 彩度设下限，避免选了接近灰黑的颜色后整个界面失去层次。
 */
export function themeShades(color: string): Record<string, string> {
  const [r, g, b] = hexToRgb(color)
  const [h, rawS, rawL] = rgbToHsl(r, g, b)
  const s = clamp(rawS, 0.32, 0.88)
  const baseL = clamp(rawL, 0.34, 0.62)
  const lightness: Record<string, number> = {
    50: 0.975,
    100: 0.944,
    200: 0.88,
    300: Math.min(0.81, baseL + 0.22),
    400: Math.min(0.71, baseL + 0.1),
    500: baseL,
    600: Math.max(0.26, baseL - 0.1),
    700: Math.max(0.21, baseL - 0.18),
    800: Math.max(0.17, baseL - 0.25),
    900: Math.max(0.14, baseL - 0.31),
  }
  const shades: Record<string, string> = {}
  for (const [step, l] of Object.entries(lightness)) {
    const [rr, gg, bb] = hslToRgb(h, s, l)
    shades[step] = rgbTriplet(rr, gg, bb)
  }
  return shades
}

/** 写入一组主题变量；prefix 为空时写编辑模式，否则写学习模式专用槽位。 */
function applyShades(prefix: string, color: string) {
  const normalized = normalizeHex(color)
  const root = document.documentElement
  const shades = themeShades(normalized)
  for (const [step, value] of Object.entries(shades)) {
    root.style.setProperty(`--${prefix}kiwi-${step}`, value)
  }
  const [r, g, b] = hexToRgb(normalized)
  const rgb = `${Math.round(r)} ${Math.round(g)} ${Math.round(b)}`
  const [h, s] = rgbToHsl(r, g, b)
  const ambient = `--${prefix ? `${prefix}` : ''}ambient`
  root.style.setProperty(`${ambient}-a`, `rgba(${rgb.replace(/ /g, ', ')}, 0.09)`)
  root.style.setProperty(`${ambient}-b`, `rgba(${rgb.replace(/ /g, ', ')}, 0.08)`)
  root.style.setProperty(`${ambient}-c`, `rgba(${rgb.replace(/ /g, ', ')}, 0.06)`)
  root.style.setProperty(
    `--${prefix ? `${prefix}` : ''}selection-bg`,
    `rgba(${rgb.replace(/ /g, ', ')}, 0.18)`,
  )
  root.style.setProperty(
    `--${prefix ? `${prefix}` : ''}selection-ink`,
    hexFromRgb(...hslToRgb(h, clamp(s, 0.32, 0.88), 0.34)),
  )
}

/** 编辑模式主题色（:root 上的 --kiwi-*）。 */
export function applyThemeColor(color: string) {
  applyShades('', color)
}

/** 学习模式主题色；body.theme-learn 通过 var(--learn-*) 读取。 */
export function applyLearnThemeColor(color: string) {
  applyShades('learn-', color || DEFAULT_LEARN_THEME_COLOR)
}

/** 品牌信息同步到顶栏、浏览器标题与两种模式的配色。 */
export function applyBranding(settings: SystemSettings) {
  applyThemeColor(settings.theme_color || DEFAULT_THEME_COLOR)
  applyLearnThemeColor(settings.learn_theme_color || DEFAULT_LEARN_THEME_COLOR)
  const name = settings.app_name?.trim() || DEFAULT_APP_NAME
  const description = settings.app_description?.trim() || DEFAULT_APP_DESCRIPTION
  document.title = `${name} · ${description}`
  const meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
  if (meta) meta.content = description
}

export const useSystemStore = defineStore('system', () => {
  const settings = ref<SystemSettings>({ ...DEFAULT_SYSTEM_SETTINGS })
  const loaded = ref(false)
  const loading = ref(false)
  // 并发调用共享同一个请求：设置页在 App 启动请求未完成时也能拿到真实配置，
  // 否则会先水合默认值，表现为已上传的 LOGO 没有回显。
  let inflight: Promise<SystemSettings> | null = null

  const appName = computed(() => settings.value.app_name || DEFAULT_APP_NAME)
  const appDescription = computed(
    () => settings.value.app_description || DEFAULT_APP_DESCRIPTION,
  )
  const logoUrl = computed(() => settings.value.logo_url || '')

  async function fetchSettings(force = false): Promise<SystemSettings> {
    if (inflight) return inflight
    if (loaded.value && !force) return settings.value
    loading.value = true
    inflight = (async () => {
      try {
        const data = await request<SystemSettings>('/settings/system')
        settings.value = data
        applyBranding(data)
        loaded.value = true
        return data
      } finally {
        loading.value = false
        loaded.value = true
        inflight = null
      }
    })()
    return inflight
  }

  async function saveSettings(
    patch: Partial<SystemSettings> & { ocr_api_key?: string | null },
  ): Promise<SystemSettings> {
    const updated = await request<SystemSettings>('/settings/system', {
      method: 'PUT',
      body: JSON.stringify(patch),
    })
    settings.value = updated
    applyBranding(updated)
    loaded.value = true
    return updated
  }

  async function uploadLogo(file: File): Promise<string> {
    const form = new FormData()
    form.append('file', file)
    const result = await upload<{ url: string }>('/settings/system/logo', form)
    return result.url
  }

  /**
   * 一键恢复默认 Logo：只清空 logo_url 并同步全局顶栏，
   * 不覆盖设置页里其它尚未保存的品牌预览。
   */
  async function resetLogo(): Promise<void> {
    const updated = await request<SystemSettings>('/settings/system', {
      method: 'PUT',
      body: JSON.stringify({ logo_url: '' }),
    })
    settings.value = { ...settings.value, logo_url: updated.logo_url }
  }

  async function testOcr(payload: OcrTestPayload): Promise<OcrTestResult> {
    return request<OcrTestResult>('/settings/system/ocr/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  }

  return {
    settings,
    loaded,
    loading,
    appName,
    appDescription,
    logoUrl,
    fetchSettings,
    saveSettings,
    uploadLogo,
    resetLogo,
    testOcr,
  }
})
