/**
 * 主题引擎：把主题插件的声明式规格写入 CSS 变量、data 属性与样式链接。
 *
 * 设计原则：
 * - 内置主题的令牌与 `:root` 默认值完全一致，因此切换内置主题不会改变现有界面。
 * - 颜色统一转成 `R G B` 三元组，兼容层用 `rgb(var(--theme-*) / alpha)` 消费。
 * - 背景图 / 暗化 / 模糊放在 body 伪元素上，不包裹业务组件。
 * - 主题 CSS 用 `<link>` 注入；规则约定限定在 `html[data-kiwi-theme="<key>"]`。
 */
import {
  DEFAULT_LEARN_THEME_COLOR,
  DEFAULT_THEME_COLOR,
  applyLearnThemeColor,
  applyThemeColor,
} from '@/stores/system'
import {
  DEFAULT_THEME_COLORS,
  EMPTY_THEME_OVERRIDES,
  normalizeThemeSpec,
  type ThemeActive,
  type ThemeColorKey,
  type ThemeOverrides,
} from './types'

export const THEME_CACHE_KEY = 'kiwi.theme.active.v1'

/** 主题令牌 → CSS 变量。 */
const TOKEN_VARS: Record<ThemeColorKey, string> = {
  'app.background': '--theme-app',
  'surface.background': '--theme-surface',
  'surface.muted': '--theme-surface-muted',
  'surface.strong': '--theme-surface-strong',
  'border.subtle': '--theme-border-subtle',
  'border.default': '--theme-border',
  'border.strong': '--theme-border-strong',
  'text.primary': '--theme-text-primary',
  'text.strong': '--theme-text-strong',
  'text.secondary': '--theme-text-secondary',
  'text.muted': '--theme-text-muted',
  'text.subtle': '--theme-text-subtle',
  'text.faint': '--theme-text-faint',
  'accent': '--theme-accent',
  'accent.foreground': '--theme-accent-foreground',
}

/**
 * 规范里没有单独定义的旧 slate 档位：默认留在 CSS fallback 里（与当前界面一致），
 * 自定义主题再按语义令牌推导，避免内置主题出现任何色差。
 */
const EXTRA_VARS = [
  '--theme-bg-300',
  '--theme-bg-400',
  '--theme-text-200',
  '--theme-text-900',
  '--theme-border-50',
  '--theme-border-500',
  '--theme-background-image',
  '--theme-background-size',
  '--theme-background-position',
  '--theme-background-repeat',
  '--theme-background-dim',
  '--theme-background-blur',
  '--theme-surface-opacity',
  '--theme-surface-blur',
  '--learn-theme-accent',
  '--theme-radius',
  '--theme-font-body',
  '--theme-font-heading',
  '--theme-font-mono',
]

const HEX_RE = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i
const RGB_RE = /rgba?\(\s*([\d.]+)%?(?:\s*,\s*|\s+)([\d.]+)%?(?:\s*,\s*|\s+)([\d.]+)%?/i

function toTriplet(r: number, g: number, b: number): string {
  const clamp = (value: number) => Math.min(255, Math.max(0, Math.round(value)))
  return `${clamp(r)} ${clamp(g)} ${clamp(b)}`
}

function parseColor(text: string): string | null {
  const value = text.trim()
  if (!value) return null
  const hex = HEX_RE.exec(value)
  if (hex) {
    let digits = hex[1]
    if (digits.length === 3) digits = digits.split('').map((part) => part + part).join('')
    return toTriplet(
      Number.parseInt(digits.slice(0, 2), 16),
      Number.parseInt(digits.slice(2, 4), 16),
      Number.parseInt(digits.slice(4, 6), 16),
    )
  }
  const rgb = RGB_RE.exec(value)
  if (rgb) {
    const percent = value.includes('%')
    const scale = (raw: string) => {
      const number = Number.parseFloat(raw)
      return percent ? (number * 255) / 100 : number
    }
    return toTriplet(scale(rgb[1]), scale(rgb[2]), scale(rgb[3]))
  }
  // hsl() / 命名色：交给浏览器解析，再读回 rgb() 形式。
  if (typeof document === 'undefined' || !document.body) return null
  const probe = document.createElement('span')
  probe.style.color = value
  probe.style.position = 'absolute'
  probe.style.visibility = 'hidden'
  probe.style.pointerEvents = 'none'
  document.body.appendChild(probe)
  const computed = getComputedStyle(probe).color
  probe.remove()
  const parsed = RGB_RE.exec(computed)
  if (!parsed) return null
  return toTriplet(
    Number.parseFloat(parsed[1]),
    Number.parseFloat(parsed[2]),
    Number.parseFloat(parsed[3]),
  )
}

/** 把任意合法 CSS 颜色转成 `R G B` 三元组；失败返回 null。 */
export function colorToRgbTriplet(value: string | null | undefined): string | null {
  if (!value) return null
  return parseColor(value)
}

/** 主题包里的相对资源 → 可访问 URL。 */
export function resolveThemeAsset(assetBaseUrl: string, path: string): string {
  const value = (path || '').trim()
  if (!value) return ''
  if (/^(data:|https?:|blob:|\/)/i.test(value)) return value
  const base = (assetBaseUrl || '').trim()
  if (!base) return value
  return `${base.replace(/\/+$/, '')}/${value.replace(/^\.?\//, '')}`
}

function cssUrl(value: string): string {
  return value.replace(/["\\\n\r]/g, (char) => encodeURIComponent(char))
}

let styleLink: HTMLLinkElement | null = null
let backgroundVideo: HTMLVideoElement | null = null

/**
 * 背景视频层：固定在 body 的负 z-index，位于暗化遮罩之下、页面内容之上。
 * 没有视频时移除元素并释放解码器，避免切换主题后仍在后台播放。
 */
function syncBackgroundVideo(src: string, blur: number, poster = ''): void {
  if (typeof document === 'undefined') return
  const value = src.trim()
  if (!value) {
    if (backgroundVideo) {
      backgroundVideo.pause()
      backgroundVideo.removeAttribute('src')
      backgroundVideo.removeAttribute('poster')
      backgroundVideo.load()
      backgroundVideo.remove()
      backgroundVideo = null
    }
    return
  }
  if (!backgroundVideo) {
    backgroundVideo = document.createElement('video')
    backgroundVideo.className = 'theme-background-video'
    backgroundVideo.autoplay = true
    backgroundVideo.loop = true
    backgroundVideo.muted = true
    backgroundVideo.playsInline = true
    backgroundVideo.preload = 'auto'
    backgroundVideo.setAttribute('aria-hidden', 'true')
    backgroundVideo.setAttribute('tabindex', '-1')
    document.body.appendChild(backgroundVideo)
  }
  // 主题图片作为视频封面：首帧解码前不会露出应用底色。
  const posterValue = poster.trim()
  if (posterValue) backgroundVideo.poster = posterValue
  else backgroundVideo.removeAttribute('poster')
  if (backgroundVideo.getAttribute('src') !== value) {
    backgroundVideo.src = value
    void backgroundVideo.play().catch(() => {
      // 自动播放被浏览器拦截时保留首帧，不影响页面使用。
    })
  }
  backgroundVideo.style.filter = blur > 0 ? `blur(${blur}px)` : ''
  backgroundVideo.style.transform = blur > 0 ? 'scale(1.06)' : ''
}

function syncStyleLink(href: string): void {
  if (!href) {
    styleLink?.remove()
    styleLink = null
    return
  }
  if (!styleLink) {
    styleLink = document.createElement('link')
    styleLink.rel = 'stylesheet'
    styleLink.dataset.kiwiThemeStyle = ''
    document.head.appendChild(styleLink)
  }
  if (styleLink.getAttribute('href') !== href) styleLink.href = href
}

function normalizedOverrides(active: ThemeActive): ThemeOverrides {
  return { ...EMPTY_THEME_OVERRIDES, ...(active.overrides || {}) }
}

export function readCachedTheme(): ThemeActive | null {
  try {
    const raw = localStorage.getItem(THEME_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as ThemeActive
    if (!parsed || typeof parsed !== 'object') return null
    if (typeof parsed.key !== 'string' || !parsed.theme) return null
    return parsed
  } catch {
    return null
  }
}

export function cacheActiveTheme(active: ThemeActive | null): void {
  try {
    if (!active) {
      localStorage.removeItem(THEME_CACHE_KEY)
      return
    }
    localStorage.setItem(THEME_CACHE_KEY, JSON.stringify(active))
  } catch {
    // 超大背景图可能超出 localStorage 配额：退化为只缓存颜色 / 透明度，
    // 首屏仍能立即套用主题，背景图等接口返回后再补齐。
    if (!active) return
    try {
      localStorage.setItem(
        THEME_CACHE_KEY,
        JSON.stringify({
          ...active,
          overrides: { ...normalizedOverrides(active), background_image: '' },
        }),
      )
    } catch {
      // 存储不可用时忽略，不影响本次会话。
    }
  }
}

/** 启动首屏立即套用缓存主题，避免刷新时先闪默认配色。 */
export function applyCachedTheme(): ThemeActive | null {
  const cached = readCachedTheme()
  if (cached) applyActiveTheme(cached)
  return cached
}

function clearThemeVars(root: HTMLElement): void {
  for (const name of Object.values(TOKEN_VARS)) root.style.removeProperty(name)
  for (const name of EXTRA_VARS) root.style.removeProperty(name)
  for (const attr of [
    'kiwiTheme',
    'kiwiThemeMode',
    'kiwiThemeCustom',
    'kiwiThemeBg',
    'kiwiThemeGlass',
    'kiwiThemeBlur',
    'kiwiThemeFontBody',
    'kiwiThemeFontHeading',
    'kiwiThemeFontMono',
  ]) {
    delete (root.dataset as Record<string, string | undefined>)[attr]
  }
}

/**
 * 套用主题。`active` 为 null 时恢复 Kiwi 默认视觉。
 * 强调色完全由主题决定：覆盖值 > 主题包声明 > 内置默认色。
 * 编辑模式与学习模式分别解析、分别写入各自的色板，
 * 任一侧的自定义都不会影响另一侧。
 */
export function applyActiveTheme(active: ThemeActive | null): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement

  if (!active) {
    clearThemeVars(root)
    syncStyleLink('')
    syncBackgroundVideo('', 0)
    applyThemeColor(DEFAULT_THEME_COLOR)
    applyLearnThemeColor(DEFAULT_LEARN_THEME_COLOR)
    return
  }

  const spec = normalizeThemeSpec(active.theme)
  const colors = { ...DEFAULT_THEME_COLORS, ...spec.colors }
  const overrides = normalizedOverrides(active)

  // 1. 颜色令牌
  for (const key of Object.keys(TOKEN_VARS) as ThemeColorKey[]) {
    const triplet = colorToRgbTriplet(colors[key]) || colorToRgbTriplet(DEFAULT_THEME_COLORS[key])
    if (triplet) root.style.setProperty(TOKEN_VARS[key], triplet)
  }

  // 2. 旧 slate 档位：内置主题移除，让 CSS fallback 保持当前色值。
  if (active.builtin) {
    for (const name of [
      '--theme-bg-300',
      '--theme-bg-400',
      '--theme-text-200',
      '--theme-text-900',
      '--theme-border-50',
      '--theme-border-500',
    ]) {
      root.style.removeProperty(name)
    }
  } else {
    const set = (name: string, value: string) => {
      const triplet = colorToRgbTriplet(value)
      if (triplet) root.style.setProperty(name, triplet)
    }
    set('--theme-bg-300', colors['border.strong'])
    set('--theme-bg-400', colors['text.subtle'])
    set('--theme-text-200', spec.mode === 'dark' ? colors['text.primary'] : colors['text.faint'])
    set('--theme-text-900', colors['text.primary'])
    set('--theme-border-50', colors['border.subtle'])
    set('--theme-border-500', colors['border.strong'])
  }

  // 3. 背景 / 表面 / 字体
  const themeBackground = spec.background
  const overrideVideo = (overrides.background_video || '').trim()
  const overrideImage = (overrides.background_image || '').trim()
  const themeVideo = resolveThemeAsset(active.asset_base_url, themeBackground.video || '')
  const themeImage = resolveThemeAsset(active.asset_base_url, themeBackground.image)
  // 优先级：用户视频 > 用户图片 > 主题视频 > 主题图片。
  // 用户只要覆盖了图片或视频，就完整替换主题背景，避免两层背景叠加。
  const video = overrideVideo || (overrideImage ? '' : themeVideo)
  const image = video ? '' : overrideImage || themeImage
  // 主题视频用主题图片做 poster；用户覆盖的背景没有配套封面。
  const poster = video && video === themeVideo ? themeImage : ''
  const size = overrides.background_size || themeBackground.size
  const position = overrides.background_position || themeBackground.position
  const repeat = overrides.background_repeat || themeBackground.repeat
  const dim = overrides.background_dim ?? themeBackground.dim
  const backgroundBlur = overrides.background_blur ?? themeBackground.blur
  const surfaceOpacity = overrides.surface_opacity ?? spec.surface.opacity
  const surfaceBlur = overrides.surface_blur ?? spec.surface.blur
  const radius = spec.surface.radius

  root.style.setProperty('--theme-background-image', image ? `url("${cssUrl(image)}")` : 'none')
  root.style.setProperty('--theme-background-size', size)
  root.style.setProperty('--theme-background-position', position || 'center')
  root.style.setProperty('--theme-background-repeat', repeat)
  root.style.setProperty('--theme-background-dim', String(dim))
  root.style.setProperty('--theme-background-blur', `${backgroundBlur}px`)
  root.style.setProperty('--theme-surface-opacity', String(surfaceOpacity))
  root.style.setProperty('--theme-surface-blur', `${surfaceBlur}px`)
  root.style.setProperty('--theme-radius', `${radius ?? 16}px`)

  root.dataset.kiwiTheme = active.key
  root.dataset.kiwiThemeMode = spec.mode
  if (active.builtin) delete root.dataset.kiwiThemeCustom
  else root.dataset.kiwiThemeCustom = 'true'
  if (image || video) root.dataset.kiwiThemeBg = 'true'
  else delete root.dataset.kiwiThemeBg
  syncBackgroundVideo(video, backgroundBlur, poster)
  if (surfaceOpacity < 1) root.dataset.kiwiThemeGlass = 'true'
  else delete root.dataset.kiwiThemeGlass
  // 始终写出 true / false：毛玻璃模糊为 0 时 app 样式需要明确关掉
  // 组件自带的 backdrop-blur-*，否则「自定义外观」预览与实机不一致。
  root.dataset.kiwiThemeBlur = surfaceBlur > 0 ? 'true' : 'false'

  const bodyFont = spec.typography.body.trim()
  const headingFont = spec.typography.heading.trim() || bodyFont
  const monoFont = spec.typography.mono.trim()
  for (const [name, value] of [
    ['--theme-font-body', bodyFont],
    ['--theme-font-heading', headingFont],
    ['--theme-font-mono', monoFont],
  ] as const) {
    if (value) root.style.setProperty(name, value)
    else root.style.removeProperty(name)
  }
  if (bodyFont) root.dataset.kiwiThemeFontBody = 'true'
  else delete root.dataset.kiwiThemeFontBody
  if (headingFont) root.dataset.kiwiThemeFontHeading = 'true'
  else delete root.dataset.kiwiThemeFontHeading
  if (monoFont) root.dataset.kiwiThemeFontMono = 'true'
  else delete root.dataset.kiwiThemeFontMono

  // 4. 强调色：编辑 / 学习模式各自解析，互不影响。
  //    每一侧都是 覆盖值 > 主题包声明 > 内置默认色。
  const declaredAccent = (spec.colors.accent || '').trim()
  const editAccent = (overrides.accent || declaredAccent).trim()
  const editTriplet = colorToRgbTriplet(editAccent)
  if (editTriplet) root.style.setProperty('--theme-accent', editTriplet)
  else root.style.removeProperty('--theme-accent')

  // 内置主题未声明 accent 时保留原有编辑紫 / 学习绿；安装了主题后，
  // 学习模式默认跟随主题强调色，但仍可被 learn_accent 单独覆盖。
  const learnFallback = active.builtin ? DEFAULT_LEARN_THEME_COLOR : DEFAULT_THEME_COLOR
  const learnAccent = (overrides.learn_accent || declaredAccent || learnFallback).trim()
  const learnTriplet = colorToRgbTriplet(learnAccent)
  if (learnTriplet) root.style.setProperty('--learn-theme-accent', learnTriplet)
  else root.style.removeProperty('--learn-theme-accent')

  const accentForeground =
    colorToRgbTriplet(spec.colors['accent.foreground']) ||
    colorToRgbTriplet(DEFAULT_THEME_COLORS['accent.foreground']) ||
    '255 255 255'
  root.style.setProperty('--theme-accent-foreground', accentForeground)
  applyThemeColor(editAccent || DEFAULT_THEME_COLOR)
  applyLearnThemeColor(learnAccent)

  // 5. 主题装饰样式
  syncStyleLink(active.style_url)
}
