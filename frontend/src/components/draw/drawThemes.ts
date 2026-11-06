/**
 * 画布魔法棒：一组同色系配色，一次性把整张画布的图形、连线与文字
 * 收敛到同一色相，适合在搭好结构后快速统一视觉。
 *
 * 只改颜色字段，不动几何 / 绑定 / 分组；图片与全透明元素保持原样。
 */

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
  strokeColor?: string
  backgroundColor?: string
  fontColor?: string
  [key: string]: unknown
}

const TRANSPARENT_COLORS = new Set(['', 'transparent', 'none'])

function isTransparent(color: unknown): boolean {
  return typeof color !== 'string' || TRANSPARENT_COLORS.has(color.toLowerCase())
}

/**
 * 计算单个元素的换色补丁；无需调整时返回 null。
 * 透明描边 / 填充保持透明，避免把原本不可见的元素改出来。
 */
export function drawThemePatch(
  element: DrawThemableElement | null | undefined,
  theme: DrawThemePalette,
): Record<string, string> | null {
  if (!element || element.isDeleted) return null
  const type = element.type

  // 图片与画框不参与换色：图片本身有内容，画框是画布容器。
  if (type === 'image' || type === 'frame' || type === 'embeddable') return null

  if (type === 'text') {
    if (isTransparent(element.fontColor) || element.fontColor === theme.text) return null
    return { fontColor: theme.text }
  }

  const patch: Record<string, string> = {}
  const isLinear = type === 'arrow' || type === 'line' || type === 'freedraw'
  const stroke = isLinear ? theme.accent : theme.stroke

  if (!isTransparent(element.strokeColor) && element.strokeColor !== stroke) {
    patch.strokeColor = stroke
  }
  if (!isTransparent(element.backgroundColor) && element.backgroundColor !== theme.fill) {
    patch.backgroundColor = theme.fill
  }
  return Object.keys(patch).length ? patch : null
}

function hslToHex(hue: number, saturation: number, lightness: number): string {
  const s = saturation / 100
  const l = lightness / 100
  const chroma = s * Math.min(l, 1 - l)
  const channel = (n: number) => {
    const k = (n + hue / 30) % 12
    const value = l - chroma * Math.max(-1, Math.min(k - 3, 9 - k, 1))
    return Math.round(value * 255)
      .toString(16)
      .padStart(2, '0')
  }
  return `#${channel(0)}${channel(8)}${channel(4)}`.toUpperCase()
}

/**
 * 随机主题不是从内置列表里抽一个，而是按随机色相现场生成一套同色系配色：
 * 深色描边、中间色连线、浅色填充与深色文字，保证整体协调且文字可读。
 */
export function createRandomDrawTheme(): DrawThemePalette {
  const hue = Math.floor(Math.random() * 360)
  const saturation = 55 + Math.round(Math.random() * 15)
  const fillSaturation = 68 + Math.round(Math.random() * 17)
  return {
    id: 'random',
    name: '随机主题',
    stroke: hslToHex(hue, saturation, 33 + Math.round(Math.random() * 9)),
    accent: hslToHex(hue, saturation, 48 + Math.round(Math.random() * 10)),
    fill: hslToHex(hue, fillSaturation, 94 + Math.round(Math.random() * 4)),
    text: hslToHex(hue, 45 + Math.round(Math.random() * 15), 20 + Math.round(Math.random() * 8)),
  }
}
