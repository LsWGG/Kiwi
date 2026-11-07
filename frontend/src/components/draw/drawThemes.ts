/**
 * 画布魔法棒：一组同色系配色 + 一组形状 / 线条风格。
 *
 * 配色负责图形、连线与文字的颜色；风格负责 jvs-draw 属性面板里的
 * 填充样式、描边线型、线宽、手绘粗糙度、圆角与透明度。两者可以单独
 * 应用，也可以点「随机主题」一次生成全套。只改样式字段，不动几何 /
 * 绑定 / 分组；图片、画框与全透明元素保持原样。
 */

export type DrawFillStyle = 'solid' | 'hachure' | 'cross-hatch'
export type DrawStrokeStyle = 'solid' | 'dashed' | 'dotted'

/** 一套形状与线条风格，字段对应 jvs-draw 属性面板里的样式项。 */
export interface DrawThemeStyle {
  /** 闭合图形的填充样式 */
  fillStyle: DrawFillStyle
  /** 描边线型：实线 / 虚线 / 点线 */
  strokeStyle: DrawStrokeStyle
  /** 描边宽度 */
  strokeWidth: number
  /** 手绘风格：0 规整、1 手绘、2 涂鸦 */
  roughness: number
  /** 圆角档位，0 为直角 */
  roundness: number
  /** 整体透明度（百分比） */
  opacity: number
}

export interface WandStylePreset {
  id: string
  name: string
  style: DrawThemeStyle
}

/**
 * 预设风格都控制在「干净、可直接用于工程图」的范围内：
 * 填充只变化纹理，不改透明；线型变化同时作用于图形与连线。
 */
export const WAND_STYLES: WandStylePreset[] = [
  {
    id: 'regular',
    name: '规整',
    style: {
      fillStyle: 'solid',
      strokeStyle: 'solid',
      strokeWidth: 2,
      roughness: 0,
      roundness: 8,
      opacity: 100,
    },
  },
  {
    id: 'soft',
    name: '圆润',
    style: {
      fillStyle: 'solid',
      strokeStyle: 'solid',
      strokeWidth: 2,
      roughness: 0,
      roundness: 20,
      opacity: 100,
    },
  },
  {
    id: 'sketch',
    name: '手绘',
    style: {
      fillStyle: 'hachure',
      strokeStyle: 'solid',
      strokeWidth: 2,
      roughness: 1,
      roundness: 8,
      opacity: 100,
    },
  },
  {
    id: 'grid',
    name: '网格',
    style: {
      fillStyle: 'cross-hatch',
      strokeStyle: 'solid',
      strokeWidth: 2,
      roughness: 0,
      roundness: 8,
      opacity: 100,
    },
  },
  {
    id: 'dashed',
    name: '虚线',
    style: {
      fillStyle: 'solid',
      strokeStyle: 'dashed',
      strokeWidth: 2,
      roughness: 0,
      roundness: 8,
      opacity: 100,
    },
  },
  {
    id: 'bold',
    name: '粗线',
    style: {
      fillStyle: 'solid',
      strokeStyle: 'solid',
      strokeWidth: 3,
      roughness: 0,
      roundness: 8,
      opacity: 100,
    },
  },
]

export const DEFAULT_WAND_STYLE_ID = 'regular'

export function wandStylePreset(id: string): WandStylePreset {
  return WAND_STYLES.find((preset) => preset.id === id) ?? WAND_STYLES[0]
}

/** 风格按钮的悬浮说明：把实际会统一的属性写清楚。 */
export function wandStyleTitle(preset: WandStylePreset): string {
  const style = preset.style
  const fill = { solid: '纯色填充', hachure: '斜线填充', 'cross-hatch': '交叉线填充' }[style.fillStyle]
  const line = { solid: '实线', dashed: '虚线', dotted: '点线' }[style.strokeStyle]
  const rough = style.roughness === 0 ? '规整线条' : style.roughness === 1 ? '手绘线条' : '涂鸦线条'
  const corner = style.roundness > 0 ? `圆角 ${style.roundness}` : '直角'
  return `${preset.name}：${fill} · ${line} ${style.strokeWidth}px · ${rough} · ${corner}；连线使用同一套线型与线宽。`
}

export interface DrawThemePalette {
  id: string
  name: string
  /** 图形描边（主色） */
  stroke: string
  /** 图形填充（同色系浅色） */
  fill: string
  /** 连线 / 箭头（同色系中间色） */
  accent: string
  /** 文字（同色系深色） */
  text: string
}

export const DRAW_THEMES: DrawThemePalette[] = [
  {
    id: 'iris',
    name: '鸢尾紫',
    stroke: '#4F46E5',
    fill: '#EEF2FF',
    accent: '#8B5CF6',
    text: '#312E81',
  },
  {
    id: 'lake',
    name: '湖蓝',
    stroke: '#0369A1',
    fill: '#E0F2FE',
    accent: '#0EA5E9',
    text: '#0C4A6E',
  },
  {
    id: 'pine',
    name: '松绿',
    stroke: '#047857',
    fill: '#ECFDF5',
    accent: '#10B981',
    text: '#064E3B',
  },
  {
    id: 'amber',
    name: '暖橙',
    stroke: '#C2410C',
    fill: '#FFF7ED',
    accent: '#F59E0B',
    text: '#7C2D12',
  },
  {
    id: 'rose',
    name: '玫瑰',
    stroke: '#BE123C',
    fill: '#FFF1F2',
    accent: '#FB7185',
    text: '#881337',
  },
  {
    id: 'slate',
    name: '石墨',
    stroke: '#334155',
    fill: '#F1F5F9',
    accent: '#64748B',
    text: '#0F172A',
  },
]

export interface DrawThemableElement {
  id?: string
  type?: string
  isDeleted?: boolean
  containerId?: string
  strokeColor?: string
  backgroundColor?: string
  fontColor?: string
  strokeWidth?: number
  strokeStyle?: string
  roughness?: number
  roundness?: unknown
  fillStyle?: string
  opacity?: number
  strokeOpacity?: number
  backgroundOpacity?: number
  [key: string]: unknown
}

/** 应用风格时的画布上下文：决定文字该用深色还是浅色。 */
export interface DrawThemeContext {
  /** 画布当前是深色底 */
  darkCanvas?: boolean
  /** 按 id 索引的全部元素，用于判断文本是否落在实底图形里 */
  elementsById?: Map<string, DrawThemableElement>
}

const TRANSPARENT_COLORS = new Set(['', 'transparent', 'none'])

function isTransparent(color: unknown): boolean {
  return typeof color !== 'string' || TRANSPARENT_COLORS.has(color.toLowerCase())
}

const LINEAR_TYPES = new Set(['arrow', 'line', 'freedraw'])

/** #RGB / #RRGGBB → 0–255 的三个通道；无法解析时返回 null。 */
function hexChannels(color: unknown): [number, number, number] | null {
  if (typeof color !== 'string') return null
  const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim())
  if (!match) return null
  let hex = match[1]
  if (hex.length === 3) hex = hex.split('').map((part) => part + part).join('')
  const value = Number.parseInt(hex, 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

/**
 * sRGB 相对亮度，用于判断画布与文字的深浅关系。
 * 无法解析的颜色按「未知」处理（返回 null），不强行改色。
 */
function colorLuminance(color: unknown): number | null {
  const channels = hexChannels(color)
  if (!channels) return null
  const toLinear = (channel: number) => {
    const c = channel / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  const [r, g, b] = channels.map(toLinear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** 画布底色是否为深色（深色画布上的文字要用浅色）。 */
export function isDarkBackground(color: unknown): boolean {
  const luminance = colorLuminance(color)
  return luminance !== null && luminance < 0.35
}

/** 深色背景上的中性文字色；有配色时改用配色的浅色。 */
const LIGHT_BACKGROUND_TEXT = '#E2E8F0'
/** 浅色背景上的中性文字色。 */
const DARK_BACKGROUND_TEXT = '#1E293B'

function readableOn(darkBackground: boolean): string {
  return darkBackground ? LIGHT_BACKGROUND_TEXT : DARK_BACKGROUND_TEXT
}

/** 文字与底色是否已经形成足够反差，已经看得清的自定义文字色不覆盖。 */
function textReadable(text: unknown, darkBackground: boolean): boolean {
  const luminance = colorLuminance(text)
  if (luminance === null) return false
  return darkBackground ? luminance >= 0.35 : luminance <= 0.65
}

/**
 * 无配色时给「纹理填充 → 实底填充」找回同色系浅色底：
 * 把描边色大量混白。纹理填充本身用描边色做纹理，两者来回切换不会
 * 留下上一档的深色 / 浅色块。
 */
function lightenHex(color: unknown, whiteRatio = 0.92): string | null {
  const channels = hexChannels(color)
  if (!channels) return null
  const hex = channels
    .map((channel) =>
      Math.round(channel + (255 - channel) * whiteRatio)
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')
  return `#${hex}`.toUpperCase()
}

const TEXTURED_FILLS = new Set(['hachure', 'cross-hatch', 'zigzag'])

/**
 * 一次样式应用后闭合图形实际的实底颜色；纹理填充透出画布，返回 null。
 * 与下面填充色的补丁逻辑保持一致，文字取色才能跟随切换后的底色。
 */
function solidFillAfterPatch(
  element: DrawThemableElement,
  style: DrawThemeStyle,
): string | null {
  if (style.fillStyle !== 'solid') return null
  if (isTransparent(element.backgroundColor)) return null
  if (TEXTURED_FILLS.has(element.fillStyle ?? '')) {
    return lightenHex(element.strokeColor) ?? element.backgroundColor ?? null
  }
  return element.backgroundColor ?? null
}

/** 常规闭合图形才统一圆角；工程符号、画框等保持原有造型。 */
const ROUNDABLE_TYPES = new Set([
  'rectangle',
  'square',
  'process',
  'diamond',
  'decision',
  'document2',
  'terminator',
  'predefinedProcess',
  'manualInput',
  'preparation',
  'display',
  'card',
  'note',
  'trapezoid',
  'parallelogram',
  'hexagon',
  'pentagon',
  'triangle',
  'step1',
  'step2',
])

/**
 * 计算单个元素的样式补丁（颜色 + 形状 / 线条属性）；无需调整时返回 null。
 * theme 为空时只应用形状与线条风格，尽量保留原有颜色；只有纹理与实底
 * 互相切换时，才按描边色补出纹理色 / 同色系浅底。
 * 透明描边 / 填充保持透明，避免把原本不可见的元素改出来。
 *
 * 文字颜色按「实际底色」决定：实底图形里用深色，纹理填充 / 连线标签 /
 * 独立文字落在画布上，深色画布改用浅色，避免深底深字看不清。
 */
export function drawThemePatch(
  element: DrawThemableElement | null | undefined,
  theme: DrawThemePalette | null,
  style: DrawThemeStyle,
  context: DrawThemeContext = {},
): Record<string, string | number> | null {
  if (!element || element.isDeleted) return null
  const type = element.type

  // 图片与画框不参与换色：图片本身有内容，画框是画布容器。
  if (type === 'image' || type === 'frame' || type === 'embeddable') return null

  if (type === 'text') {
    if (isTransparent(element.fontColor)) return null
    const container = context.elementsById?.get(String(element.containerId ?? ''))
    const onSolidFill =
      Boolean(container) &&
      !LINEAR_TYPES.has(container?.type ?? '') &&
      style.fillStyle === 'solid' &&
      solidFillAfterPatch(container as DrawThemableElement, style) !== null
    if (theme) {
      const target = onSolidFill ? theme.text : context.darkCanvas ? theme.fill : theme.text
      return element.fontColor === target ? null : { fontColor: target }
    }
    // 只改样式时不覆盖已经看得清的自定义文字色，只修掉会看不清的文字。
    if (onSolidFill) {
      const darkFill = isDarkBackground(solidFillAfterPatch(container as DrawThemableElement, style))
      return textReadable(element.fontColor, darkFill)
        ? null
        : { fontColor: readableOn(darkFill) }
    }
    return textReadable(element.fontColor, Boolean(context.darkCanvas))
      ? null
      : { fontColor: readableOn(Boolean(context.darkCanvas)) }
  }

  const patch: Record<string, string | number> = {}
  const isLinear = LINEAR_TYPES.has(type ?? '')

  if (theme) {
    const stroke = isLinear ? theme.accent : theme.stroke
    if (!isTransparent(element.strokeColor) && element.strokeColor !== stroke) {
      patch.strokeColor = stroke
    }
    // 实色填充用浅色底；斜线 / 交叉线填充改用中间色做纹理，
    // 否则浅色纹理落在深色画布上几乎看不见，文字也会和纹理糊在一起。
    const fill = style.fillStyle === 'solid' ? theme.fill : theme.accent
    if (!isTransparent(element.backgroundColor) && element.backgroundColor !== fill) {
      patch.backgroundColor = fill
    }
  } else if (!isLinear && !isTransparent(element.backgroundColor)) {
    // 没选配色时也保证纹理看得见：纹理用描边色画，切回实底时再混出同色系浅底。
    if (style.fillStyle === 'solid' && TEXTURED_FILLS.has(element.fillStyle ?? '')) {
      const tint = lightenHex(element.strokeColor)
      if (tint) patch.backgroundColor = tint
    } else if (style.fillStyle !== 'solid' && element.fillStyle !== style.fillStyle) {
      const stroke = element.strokeColor
      if (!isTransparent(stroke) && typeof stroke === 'string') patch.backgroundColor = stroke
    }
  }

  // 线型、线宽与手绘风格：图形与连线共用同一套配置。
  if (element.strokeWidth !== style.strokeWidth) {
    patch.strokeWidth = style.strokeWidth
  }
  if (type !== 'freedraw') {
    if (element.strokeStyle !== style.strokeStyle) {
      patch.strokeStyle = style.strokeStyle
    }
    if (element.roughness !== style.roughness) {
      patch.roughness = style.roughness
    }
  }
  // 填充样式只对真正有填充的闭合图形生效，透明填充保持原样。
  if (!isLinear && !isTransparent(element.backgroundColor) && element.fillStyle !== style.fillStyle) {
    patch.fillStyle = style.fillStyle
  }
  // 透明度归一：填充 / 描边分别有独立透明度，旧画布可能残留半透明设置。
  if (element.opacity !== style.opacity) {
    patch.opacity = style.opacity
  }
  if (element.strokeOpacity !== style.opacity) {
    patch.strokeOpacity = style.opacity
  }
  if (element.backgroundOpacity !== style.opacity) {
    patch.backgroundOpacity = style.opacity
  }
  if (type !== undefined && ROUNDABLE_TYPES.has(type) && element.roundness !== style.roundness) {
    patch.roundness = style.roundness
  }

  return Object.keys(patch).length ? patch : null
}

function elementStyleKey(element: DrawThemableElement, isLinear: boolean): string {
  return [
    isLinear ? '' : element.fillStyle,
    element.strokeStyle,
    element.strokeWidth,
    element.roughness,
    isLinear ? 0 : element.roundness,
    element.opacity,
  ].join('|')
}

function presetShapeKey(style: DrawThemeStyle): string {
  return [style.fillStyle, style.strokeStyle, style.strokeWidth, style.roughness, style.roundness, style.opacity].join('|')
}

function presetLineKey(style: DrawThemeStyle): string {
  return ['', style.strokeStyle, style.strokeWidth, style.roughness, 0, style.opacity].join('|')
}

function mostCommonKey(counts: Map<string, number>): string | null {
  let best: string | null = null
  let bestCount = 0
  for (const [key, count] of counts) {
    if (count > bestCount) {
      best = key
      bestCount = count
    }
  }
  return best
}

export interface DrawCurrentStyle {
  /** 闭合图形当前最常见的样式签名 */
  shape: string | null
  /** 连线当前最常见的样式签名 */
  line: string | null
}

/**
 * 读取画布当前的主样式，随机风格据此避开「已经长这样」的预设，
 * 保证每次点随机都能看出形状与线条的变化。
 */
export function currentDrawStyle(elements: DrawThemableElement[]): DrawCurrentStyle {
  const shapes = new Map<string, number>()
  const lines = new Map<string, number>()
  for (const element of elements) {
    if (!element || element.isDeleted || !element.type) continue
    if (element.type === 'text' || element.type === 'image' || element.type === 'frame' || element.type === 'embeddable') {
      continue
    }
    const isLinear = element.type === 'arrow' || element.type === 'line' || element.type === 'freedraw'
    const key = elementStyleKey(element, isLinear)
    const bucket = isLinear ? lines : shapes
    bucket.set(key, (bucket.get(key) ?? 0) + 1)
  }
  return { shape: mostCommonKey(shapes), line: mostCommonKey(lines) }
}

/** 画布当前主样式对应的预设；形状与连线同时匹配才返回，混合样式返回 null。 */
export function matchWandStyle(current: DrawCurrentStyle): WandStylePreset | null {
  if (current.shape === null && current.line === null) return null
  return (
    WAND_STYLES.find((preset) => {
      const shapeMatches = current.shape === null || current.shape === presetShapeKey(preset.style)
      const lineMatches = current.line === null || current.line === presetLineKey(preset.style)
      return shapeMatches && lineMatches
    }) ?? null
  )
}

let lastRandomStyleId: string | null = null

export function pickRandomWandStyle(current: DrawCurrentStyle): WandStylePreset {
  const matchesCurrent = (preset: WandStylePreset) => {
    const style = preset.style
    const shapeMatches = current.shape === null || current.shape === presetShapeKey(style)
    const lineMatches = current.line === null || current.line === presetLineKey(style)
    return shapeMatches && lineMatches
  }
  let pool = WAND_STYLES.filter((preset) => preset.id !== lastRandomStyleId && !matchesCurrent(preset))
  if (!pool.length) pool = WAND_STYLES.filter((preset) => !matchesCurrent(preset))
  if (!pool.length) pool = WAND_STYLES.filter((preset) => preset.id !== lastRandomStyleId)
  if (!pool.length) pool = WAND_STYLES
  const chosen = pool[Math.floor(Math.random() * pool.length)]
  lastRandomStyleId = chosen.id
  return chosen
}

function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min)
}

/** OKLCH → 线性 sRGB。OKLCH 的明度与彩度是感知均匀的，跨色相更稳定。 */
function oklchToLinearRgb(lightness: number, chroma: number, hue: number): [number, number, number] {
  const radians = (hue * Math.PI) / 180
  const a = Math.cos(radians) * chroma
  const b = Math.sin(radians) * chroma
  const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ]
}

/**
 * 把 OKLCH 写成十六进制色值。
 * 超出 sRGB 色域时二分降低彩度，避免随机到刺眼或失真的颜色。
 */
function oklchToHex(lightness: number, chroma: number, hue: number): string {
  const inGamut = (rgb: number[]) => rgb.every((value) => value >= -0.0001 && value <= 1.0001)
  let rgb = oklchToLinearRgb(lightness, chroma, hue)
  if (!inGamut(rgb)) {
    let low = 0
    let high = chroma
    for (let i = 0; i < 20; i += 1) {
      const mid = (low + high) / 2
      if (inGamut(oklchToLinearRgb(lightness, mid, hue))) low = mid
      else high = mid
    }
    rgb = oklchToLinearRgb(lightness, low, hue)
  }
  const gamma = (value: number) => {
    const clamped = Math.min(1, Math.max(0, value))
    return clamped <= 0.0031308 ? clamped * 12.92 : 1.055 * clamped ** (1 / 2.4) - 0.055
  }
  const hex = rgb
    .map((value) =>
      Math.round(gamma(value) * 255)
        .toString(16)
        .padStart(2, '0'),
    )
    .join('')
  return `#${hex.toUpperCase()}`
}

/**
 * 随机主题只从这些色相家族里抽：红 / 橙 / 琥珀 / 黄、翠绿 / 青、蓝 / 靛 /
 * 紫 / 玫红，跳过容易发灰发脏的黄绿色区，再叠加 ±5° 的轻微抖动。
 */
const RANDOM_HUES = [8, 20, 32, 45, 58, 72, 88, 145, 158, 172, 188, 202, 218, 232, 248, 262, 276, 290, 305, 320, 335, 350]

/**
 * 每个色相的描边彩度上限不同：紫 / 玫红可以更饱和，青绿和琥珀则收一点，
 * 这样随机出来的每套配色都接近手调色板，而不是同一种饱和度一刀切。
 */
const STROKE_CHROMA_STOPS: Array<[number, number]> = [
  [0, 0.19],
  [40, 0.18],
  [70, 0.15],
  [90, 0.13],
  [150, 0.12],
  [175, 0.11],
  [200, 0.11],
  [225, 0.13],
  [250, 0.17],
  [270, 0.2],
  [295, 0.2],
  [320, 0.19],
  [340, 0.18],
  [360, 0.19],
]

function strokeChromaFor(hue: number): number {
  for (let i = 1; i < STROKE_CHROMA_STOPS.length; i += 1) {
    const [endHue, endChroma] = STROKE_CHROMA_STOPS[i]
    if (hue <= endHue) {
      const [startHue, startChroma] = STROKE_CHROMA_STOPS[i - 1]
      const ratio = (hue - startHue) / (endHue - startHue)
      return startChroma + (endChroma - startChroma) * ratio
    }
  }
  return 0.18
}

function hueDistance(a: number, b: number): number {
  const delta = Math.abs(a - b) % 360
  return Math.min(delta, 360 - delta)
}

let lastRandomHue: number | null = null

function pickRandomHue(): number {
  let hue = 0
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const base = RANDOM_HUES[Math.floor(Math.random() * RANDOM_HUES.length)]
    hue = (base + randomBetween(-5, 5) + 360) % 360
    // 连续两次随机到相近色相时重新抽，避免点了半天「看起来没变」。
    if (lastRandomHue === null || hueDistance(hue, lastRandomHue) >= 18) break
  }
  lastRandomHue = hue
  return hue
}

/**
 * 随机配色不是纯随机的 HSL 抽样，而是在 OKLCH 里按「色相家族 + 感知明度」
 * 生成一套同色系配色：深色描边、相邻色相的中间色连线、极浅填充与深色文字。
 * 所有组合都保证文字 / 填充、描边 / 填充有足够对比度，点随机也能直接使用。
 */
export function createRandomDrawTheme(): DrawThemePalette {
  const hue = pickRandomHue()
  const strokeChroma = strokeChromaFor(hue) * randomBetween(0.94, 1.04)
  // 连线取相邻色相，和描边同属一个色温，比单色明暗变化更有层次。
  const accentHue = (hue + (Math.random() < 0.5 ? -1 : 1) * randomBetween(18, 36) + 360) % 360
  const accentChroma = Math.min(0.21, strokeChroma + randomBetween(0.005, 0.02))
  return {
    id: 'random',
    name: '随机主题',
    stroke: oklchToHex(randomBetween(0.49, 0.53), strokeChroma, hue),
    accent: oklchToHex(randomBetween(0.61, 0.66), accentChroma, accentHue),
    fill: oklchToHex(randomBetween(0.955, 0.97), randomBetween(0.022, 0.034), hue),
    text: oklchToHex(randomBetween(0.3, 0.345), randomBetween(0.09, 0.11), hue),
  }
}
