/** 字符级字体 / 字号：只作用于选中的文字，而不是整段。 */
import TextStyle from '@tiptap/extension-text-style'
import {
  DOCX_FONTS,
  docxFontStack,
  type DocxFont,
} from '../modes'

function isDocxFont(value: unknown): value is DocxFont {
  return DOCX_FONTS.some((font) => font.id === value)
}

/** 规范化颜色：支持 #rgb / #rrggbb / rgb()/rgba()，其余忽略。 */
export function normalizeColor(value: unknown): string | null {
  const raw = String(value ?? '').trim()
  if (!raw) return null
  if (/^#[0-9a-f]{6}$/i.test(raw)) return raw.toUpperCase()
  if (/^#[0-9a-f]{3}$/i.test(raw)) {
    return `#${raw
      .slice(1)
      .split('')
      .map((char) => char + char)
      .join('')}`.toUpperCase()
  }
  const match = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})/i.exec(raw)
  if (match) {
    const channels = match.slice(1, 4).map((part) => Math.max(0, Math.min(255, Number(part))))
    return `#${channels.map((part) => part.toString(16).padStart(2, '0')).join('')}`.toUpperCase()
  }
  return null
}

/** 从 style="font-family: ..." 还原字体 id，兼容粘贴的富文本。 */
export function fontIdFromStyle(value: string): DocxFont | null {
  const raw = String(value || '').toLowerCase()
  if (!raw) return null
  for (const font of DOCX_FONTS) {
    const first = docxFontStack(font.id)
      .split(',')[0]
      .replace(/['"]/g, '')
      .trim()
      .toLowerCase()
    if (first && raw.includes(first)) return font.id
    if (raw.includes(font.label.toLowerCase())) return font.id
  }
  return null
}

export const KiwiTextStyle = TextStyle.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      font: {
        default: null,
        parseHTML: (element: HTMLElement) => {
          const data = element.getAttribute('data-font')
          if (isDocxFont(data)) return data
          return fontIdFromStyle(element.style.fontFamily || '')
        },
        renderHTML: (attributes: Record<string, unknown>) => {
          if (!isDocxFont(attributes.font)) return {}
          return {
            'data-font': attributes.font,
            style: `font-family: ${docxFontStack(attributes.font)}`,
          }
        },
      },
      color: {
        default: null,
        parseHTML: (element: HTMLElement) =>
          normalizeColor(element.getAttribute('data-color')) ??
          normalizeColor(element.style.color),
        renderHTML: (attributes: Record<string, unknown>) => {
          const color = normalizeColor(attributes.color)
          if (!color) return {}
          return {
            'data-color': color,
            style: `color: ${color}`,
          }
        },
      },
      size: {
        default: null,
        parseHTML: (element: HTMLElement) => {
          const data = Number(element.getAttribute('data-size'))
          if (Number.isFinite(data) && data > 0) return data
          const px = Number.parseFloat(element.style.fontSize || '')
          return Number.isFinite(px) && px > 0 ? Math.round(px) : null
        },
        renderHTML: (attributes: Record<string, unknown>) => {
          const size = Number(attributes.size)
          if (!Number.isFinite(size) || size <= 0) return {}
          return {
            'data-size': String(size),
            style: `font-size: ${size}px`,
          }
        },
      },
    }
  },
})

export function normalizeTextStyleAttrs(raw: Record<string, unknown>): {
  font?: DocxFont
  size?: number
  color?: string
} {
  const attrs: { font?: DocxFont; size?: number; color?: string } = {}
  if (isDocxFont(raw.font)) attrs.font = raw.font
  const size = Number(raw.size)
  if (Number.isFinite(size) && size > 0) attrs.size = Math.min(96, Math.max(6, Math.round(size)))
  const color = normalizeColor(raw.color)
  if (color) attrs.color = color
  return attrs
}
