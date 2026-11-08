/** 主题插件类型：与后端 `app/schemas/theme.py` / `plugin.py` 的 Theme* schema 对齐。 */

export type ThemeColorKey =
  | 'app.background'
  | 'surface.background'
  | 'surface.muted'
  | 'surface.strong'
  | 'border.subtle'
  | 'border.default'
  | 'border.strong'
  | 'text.primary'
  | 'text.strong'
  | 'text.secondary'
  | 'text.muted'
  | 'text.subtle'
  | 'text.faint'
  | 'accent'
  | 'accent.foreground'

export const THEME_COLOR_KEYS: ThemeColorKey[] = [
  'app.background',
  'surface.background',
  'surface.muted',
  'surface.strong',
  'border.subtle',
  'border.default',
  'border.strong',
  'text.primary',
  'text.strong',
  'text.secondary',
  'text.muted',
  'text.subtle',
  'text.faint',
  'accent',
  'accent.foreground',
]

/** 与当前界面完全一致的默认值：内置主题与兼容层都以此为基准。 */
export const DEFAULT_THEME_COLORS: Record<ThemeColorKey, string> = {
  'app.background': '#f8fafc',
  'surface.background': '#ffffff',
  'surface.muted': '#f1f5f9',
  'surface.strong': '#e2e8f0',
  'border.subtle': '#f1f5f9',
  'border.default': '#e2e8f0',
  'border.strong': '#cbd5e1',
  'text.primary': '#1e293b',
  'text.strong': '#334155',
  'text.secondary': '#475569',
  'text.muted': '#64748b',
  'text.subtle': '#94a3b8',
  'text.faint': '#cbd5e1',
  // accent 留空表示由主题引擎回落到内置默认色（编辑紫 / 学习绿）；画廊预览用 DEFAULT_ACCENT。
  'accent': '',
  'accent.foreground': '#ffffff',
}

export const DEFAULT_ACCENT = '#5a55c7'
/** 内置主题未声明强调色时，学习模式沿用原有品牌绿。 */
export const DEFAULT_LEARN_ACCENT = '#10b981'

export const THEME_COLOR_LABELS: Record<ThemeColorKey, string> = {
  'app.background': '应用背景',
  'surface.background': '面板表面',
  'surface.muted': '次级填充',
  'surface.strong': '深层填充',
  'border.subtle': '极浅边框',
  'border.default': '常规边框',
  'border.strong': '强调边框',
  'text.primary': '主文本',
  'text.strong': '强调文本',
  'text.secondary': '次级文本',
  'text.muted': '辅助文本',
  'text.subtle': '弱化文本',
  'text.faint': '最弱文本',
  'accent': '强调色',
  'accent.foreground': '强调色文字',
}

export type ThemeMode = 'light' | 'dark'
export type ThemeBackgroundSize = 'cover' | 'contain' | 'auto'
export type ThemeBackgroundRepeat = 'no-repeat' | 'repeat' | 'repeat-x' | 'repeat-y'

export interface ThemeBackground {
  image: string
  size: ThemeBackgroundSize
  position: string
  repeat: ThemeBackgroundRepeat
  dim: number
  blur: number
}

export interface ThemeSurface {
  opacity: number
  blur: number
  radius?: number | null
}

export interface ThemeTypography {
  body: string
  heading: string
  mono: string
}

export interface ThemeSpec {
  mode: ThemeMode
  colors: Record<string, string>
  background: ThemeBackground
  surface: ThemeSurface
  typography: ThemeTypography
  preview: string
}

export const DEFAULT_THEME_BACKGROUND: ThemeBackground = {
  image: '',
  size: 'cover',
  position: 'center',
  repeat: 'no-repeat',
  dim: 0,
  blur: 0,
}

export const DEFAULT_THEME_SURFACE: ThemeSurface = { opacity: 1, blur: 0, radius: null }
export const DEFAULT_THEME_TYPOGRAPHY: ThemeTypography = { body: '', heading: '', mono: '' }

export interface ThemeOverrides {
  background_image: string
  /** 上传后的背景视频 URL；与 background_image 二选一。 */
  background_video: string
  background_size: ThemeBackgroundSize | null
  background_position: string | null
  background_repeat: ThemeBackgroundRepeat | null
  background_dim: number | null
  background_blur: number | null
  surface_opacity: number | null
  surface_blur: number | null
  /** 编辑模式强调色。 */
  accent: string | null
  /** 学习模式强调色，与编辑模式独立。 */
  learn_accent: string | null
}

export const EMPTY_THEME_OVERRIDES: ThemeOverrides = {
  background_image: '',
  background_video: '',
  background_size: null,
  background_position: null,
  background_repeat: null,
  background_dim: null,
  background_blur: null,
  surface_opacity: null,
  surface_blur: null,
  accent: null,
  learn_accent: null,
}

/** 主题画廊条目（内置与已安装共用）。 */
export interface ThemeItem {
  id: string
  key: string
  name: string
  version: string
  description: string
  author: string
  icon: string
  homepage: string
  builtin: boolean
  enabled: boolean
  active: boolean
  style_url: string
  preview_url: string
  asset_base_url: string
  theme: ThemeSpec
  assets: string[]
}

/** 当前生效主题：启动 / 切换时下发。 */
export interface ThemeActive {
  key: string
  name: string
  builtin: boolean
  enabled: boolean
  theme: ThemeSpec
  style_url: string
  asset_base_url: string
  overrides: ThemeOverrides
}

/** 自定义背景上传结果。 */
export interface ThemeBackgroundUpload {
  url: string
  kind: 'image' | 'video'
  content_type: string
  size: number
}

export interface ThemeInspection {
  kind: 'template' | 'component' | 'theme'
  key: string
  name: string
  version: string
  description: string
  entry: string
  style: string
  has_script: boolean
  has_style: boolean
  block_count: number
  blocks: string[]
  theme: ThemeSpec | null
  asset_count: number
  assets: string[]
}

export interface ThemeDevSpec {
  manifest_version: number
  kind: string
  package: string
  skill: string
  dev_kit_url: string
  ai_prompt: string
  rules: string[]
  fields: Record<string, string>
  example: Record<string, unknown>
  examples?: { theme?: Record<string, unknown> }
}

/** 合并主题声明的颜色与默认值，未知 key 会被忽略。 */
export function mergeThemeColors(
  colors?: Partial<Record<string, string>> | null,
): Record<ThemeColorKey, string> {
  const merged = { ...DEFAULT_THEME_COLORS }
  if (colors) {
    for (const key of THEME_COLOR_KEYS) {
      const value = colors[key]
      if (typeof value === 'string' && value.trim()) merged[key] = value.trim()
    }
  }
  return merged
}

/** 把可能不完整的 theme 规格补齐，避免旧缓存 / 半成品 manifest 让界面崩掉。 */
export function normalizeThemeSpec(theme?: Partial<ThemeSpec> | null): ThemeSpec {
  return {
    mode: theme?.mode === 'dark' ? 'dark' : 'light',
    colors: { ...(theme?.colors || {}) },
    background: { ...DEFAULT_THEME_BACKGROUND, ...(theme?.background || {}) },
    surface: { ...DEFAULT_THEME_SURFACE, ...(theme?.surface || {}) },
    typography: { ...DEFAULT_THEME_TYPOGRAPHY, ...(theme?.typography || {}) },
    preview: theme?.preview || '',
  }
}
