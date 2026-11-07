/**
 * 笔记内容里保存的颜色适配。
 *
 * 表格笔记允许用户给单元格设置填充与文字色，这些颜色是按浅色界面挑的；
 * 深色主题直接沿用会出现整行亮块或浅底浅字。这里在**渲染时**把颜色映射到
 * 同一色相的深色 / 浅色等价物，原始格式数据保持不变，切回浅色主题即恢复。
 */

interface RgbColor {
  r: number
  g: number
  b: number
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function parseColor(value: string): RgbColor | null {
  const text = value.trim()
  const hex = text.match(/^#([0-9a-f]{3,8})$/i)
  if (hex) {
    let raw = hex[1]
    if (raw.length === 3 || raw.length === 4) {
      raw = raw
        .slice(0, 3)
        .split('')
        .map((part) => part + part)
        .join('')
    }
    if (raw.length === 6 || raw.length === 8) {
      return {
        r: Number.parseInt(raw.slice(0, 2), 16),
        g: Number.parseInt(raw.slice(2, 4), 16),
        b: Number.parseInt(raw.slice(4, 6), 16),
      }
    }
    return null
  }
  const rgb = text.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i)
  if (!rgb) return null
  return {
    r: clamp(Number(rgb[1]), 0, 255),
    g: clamp(Number(rgb[2]), 0, 255),
    b: clamp(Number(rgb[3]), 0, 255),
  }
}

function rgbToHsl({ r, g, b }: RgbColor): { h: number; s: number; l: number } {
  const red = r / 255
  const green = g / 255
  const blue = b / 255
  const max = Math.max(red, green, blue)
  const min = Math.min(red, green, blue)
  const l = (max + min) / 2
  if (max === min) return { h: 0, s: 0, l }
  const delta = max - min
  const s = l > 0.5 ? delta / (2 - max - min) : delta / (max + min)
  let h = 0
  if (max === red) h = (green - blue) / delta + (green < blue ? 6 : 0)
  else if (max === green) h = (blue - red) / delta + 2
  else h = (red - green) / delta + 4
  return { h: h * 60, s, l }
}

function formatHsl(h: number, s: number, l: number): string {
  return `hsl(${h.toFixed(0)}, ${(s * 100).toFixed(1)}%, ${(l * 100).toFixed(1)}%)`
}

/**
 * 深色主题下的单元格颜色映射：
 * - 填充色偏亮（L > 0.62）→ 同色相的深色填充，保留用户标注的色相区分；
 * - 文字色偏暗（L < 0.55）→ 同色相的浅色文字，保证深底可读。
 */
export function adaptContentColor(
  value: string,
  role: 'background' | 'text',
): string {
  const rgb = parseColor(value)
  if (!rgb) return value
  const { h, s, l } = rgbToHsl(rgb)
  if (role === 'background') {
    if (l <= 0.62) return value
    const nextL = clamp(0.15 + (1 - l) * 0.45, 0.15, 0.34)
    const nextS = Math.min(s, 0.5) * 0.85
    return formatHsl(h, nextS, nextL)
  }
  if (l >= 0.55) return value
  const nextL = clamp(0.78 + (0.55 - l) * 0.22, 0.78, 0.9)
  const nextS = Math.min(s, 0.65)
  return formatHsl(h, nextS, nextL)
}
