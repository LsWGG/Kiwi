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
} {
  const attrs: { font?: DocxFont; size?: number } = {}
  if (isDocxFont(raw.font)) attrs.font = raw.font
  const size = Number(raw.size)
  if (Number.isFinite(size) && size > 0) attrs.size = Math.min(96, Math.max(6, Math.round(size)))
  return attrs
}
