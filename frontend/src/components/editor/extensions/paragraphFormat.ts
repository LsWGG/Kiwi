/**
 * DOCX 模式的段落级排版：
 * - 字体 / 字号 / 行距 / 段间距 / 缩进以节点属性存在，工具栏与段落对话框读取光标所在段落；
 * - 只在渲染时写内联样式，Markdown 仍是正文事实来源；
 * - 额外的排版信息按「段落序号 + 文本指纹」随笔记 props_json 持久化，加载时重新套用。
 */
import { mergeAttributes, type Editor } from '@tiptap/core'
import Heading from '@tiptap/extension-heading'
import Paragraph from '@tiptap/extension-paragraph'
import type { Node as PMNode } from '@tiptap/pm/model'
import {
  docxFontStack,
  type DocxFont,
  type DocxLineHeightMode,
  type DocxPrefs,
} from '../modes'

export type ParagraphAlign = 'left' | 'center' | 'right' | 'justify'

export interface ParagraphFormat {
  font: DocxFont | null
  size: number | null
  lineHeight: number | null
  lineHeightMode: DocxLineHeightMode | null
  lineHeightFixed: number | null
  spaceBefore: number | null
  spaceAfter: number | null
  indentLeft: number | null
  indentRight: number | null
  firstLineIndent: number | null
  hangingIndent: boolean | null
  align: ParagraphAlign | null
}

export type ParagraphFormatPatch = Partial<ParagraphFormat>

/** 持久化记录：index 是文档中第几个可排版块（仅段落 / 标题）。 */
export interface ParagraphFormatRecord extends ParagraphFormatPatch {
  index: number
  text: string
}

interface AttrMapEntry {
  key: keyof ParagraphFormat
  attr: string
}

const ATTR_MAP: AttrMapEntry[] = [
  { key: 'font', attr: 'pfFont' },
  { key: 'size', attr: 'pfSize' },
  { key: 'lineHeight', attr: 'pfLineHeight' },
  { key: 'lineHeightMode', attr: 'pfLineMode' },
  { key: 'lineHeightFixed', attr: 'pfLineFixed' },
  { key: 'spaceBefore', attr: 'pfSpaceBefore' },
  { key: 'spaceAfter', attr: 'pfSpaceAfter' },
  { key: 'indentLeft', attr: 'pfIndentLeft' },
  { key: 'indentRight', attr: 'pfIndentRight' },
  { key: 'firstLineIndent', attr: 'pfFirstIndent' },
  { key: 'hangingIndent', attr: 'pfHanging' },
  { key: 'align', attr: 'textAlign' },
]

const FORMAT_ATTRS = ATTR_MAP.filter((entry) => entry.attr !== 'textAlign')

function isFormattable(node: PMNode): boolean {
  return node.type.name === 'paragraph' || node.type.name === 'heading'
}

function formatAttributes() {
  return Object.fromEntries(
    FORMAT_ATTRS.map(({ attr }) => [
      attr,
      {
        default: null,
        // 排版属性只用于渲染样式，不写成自定义 HTML 属性
        renderHTML: () => ({}),
      },
    ]),
  )
}

function paragraphStyle(attrs: Record<string, any>): string {
  const css: string[] = []
  if (typeof attrs.pfFont === 'string' && attrs.pfFont) {
    css.push(`font-family: ${docxFontStack(attrs.pfFont as DocxFont)}`)
  }
  if (typeof attrs.pfSize === 'number') {
    css.push(`font-size: ${attrs.pfSize}px`)
  }
  if (attrs.pfLineMode === 'fixed' && typeof attrs.pfLineFixed === 'number') {
    // 1pt = 4/3 px，与页面设置里的固定值保持一致
    css.push(`line-height: ${(attrs.pfLineFixed * 4) / 3}px`)
  } else if (typeof attrs.pfLineHeight === 'number') {
    css.push(`line-height: ${attrs.pfLineHeight}`)
  }
  if (typeof attrs.pfSpaceBefore === 'number') {
    css.push(`margin-top: ${attrs.pfSpaceBefore}px`)
  }
  if (typeof attrs.pfSpaceAfter === 'number') {
    css.push(`margin-bottom: ${attrs.pfSpaceAfter}px`)
  }
  if (typeof attrs.pfIndentLeft === 'number') {
    css.push(`margin-left: ${attrs.pfIndentLeft}em`)
  }
  if (typeof attrs.pfIndentRight === 'number') {
    css.push(`margin-right: ${attrs.pfIndentRight}em`)
  }
  if (typeof attrs.pfFirstIndent === 'number') {
    if (attrs.pfHanging === true) {
      css.push(`padding-left: ${attrs.pfFirstIndent}em`)
      css.push(`text-indent: -${attrs.pfFirstIndent}em`)
    } else {
      css.push(`text-indent: ${attrs.pfFirstIndent}em`)
    }
  }
  return css.join('; ')
}

function withFormatStyle(attrs: Record<string, any>): Record<string, any> {
  const style = paragraphStyle(attrs)
  return style ? { style } : {}
}

/** 带段落排版属性的正文段落。 */
export const KiwiParagraph = Paragraph.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      ...formatAttributes(),
    }
  },

  renderHTML({ node, HTMLAttributes }) {
    return [
      'p',
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, withFormatStyle(node.attrs)),
      0,
    ]
  },
})

/** 带段落排版属性的标题。 */
export const KiwiHeading = Heading.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      ...formatAttributes(),
    }
  },

  renderHTML({ node, HTMLAttributes }) {
    const level = this.options.levels.includes(node.attrs.level)
      ? node.attrs.level
      : this.options.levels[0]
    return [
      `h${level}`,
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, withFormatStyle(node.attrs)),
      0,
    ]
  },
})

/** 读取一组节点属性中的显式排版值（未设置的字段不返回）。 */
export function formatFromAttrs(attrs: Record<string, any>): ParagraphFormatPatch {
  const format: ParagraphFormatPatch = {}
  for (const { key, attr } of ATTR_MAP) {
    const value = attrs[attr]
    if (value !== null && value !== undefined && value !== '') {
      ;(format as Record<string, unknown>)[key] = value
    }
  }
  return format
}

function patchToAttrs(patch: ParagraphFormatPatch): Record<string, unknown> {
  const attrs: Record<string, unknown> = {}
  for (const { key, attr } of ATTR_MAP) {
    if (key in patch) attrs[attr] = patch[key] ?? null
  }
  return attrs
}

/** 指定位置（默认光标处）所在的段落 / 标题节点。 */
export function blockAtPosition(
  editor: Editor | null,
  pos?: number | null,
): { node: PMNode; pos: number } | null {
  if (!editor) return null
  const target = Math.min(
    Math.max(typeof pos === 'number' ? pos : editor.state.selection.from, 0),
    editor.state.doc.content.size,
  )
  const $pos = editor.state.doc.resolve(target)
  for (let depth = $pos.depth; depth > 0; depth -= 1) {
    const node = $pos.node(depth)
    if (isFormattable(node)) return { node, pos: $pos.before(depth) }
  }
  return null
}

/** 当前光标所在的段落 / 标题节点。 */
export function currentBlock(editor: Editor | null): { node: PMNode; pos: number } | null {
  return blockAtPosition(editor)
}

/** 光标处段落的显式格式；没有设置过的字段为 null。 */
export function currentParagraphFormat(editor: Editor | null): ParagraphFormatPatch {
  const block = currentBlock(editor)
  return block ? formatFromAttrs(block.node.attrs) : {}
}

/** 标题在 DOCX 模式下有自身的相对字号，工具栏按实际显示值回填。 */
export function defaultBlockSize(block: PMNode | null, prefs: DocxPrefs): number {
  if (block?.type.name === 'heading') {
    if (block.attrs.level === 1) return Math.round(prefs.size * 1.6)
    if (block.attrs.level === 2) return Math.round(prefs.size * 1.28)
    if (block.attrs.level === 3) return 18
  }
  return prefs.size
}

/**
 * 把格式应用到当前选区覆盖的段落（无选区时只作用于光标所在段落）。
 * range 用于右键菜单：对话框打开后仍锁定右击时的段落范围。
 */
export function applyParagraphFormat(
  editor: Editor,
  patch: ParagraphFormatPatch,
  range?: { from: number; to: number } | null,
): boolean {
  const { state } = editor
  const from = range?.from ?? state.selection.from
  const to = range?.to ?? state.selection.to
  const targets: { pos: number; node: PMNode }[] = []

  if (from === to) {
    const $pos = state.doc.resolve(Math.min(Math.max(from, 0), state.doc.content.size))
    for (let depth = $pos.depth; depth > 0; depth -= 1) {
      const node = $pos.node(depth)
      if (isFormattable(node)) {
        targets.push({ pos: $pos.before(depth), node })
        break
      }
    }
  } else {
    state.doc.nodesBetween(from, to, (node, pos) => {
      if (isFormattable(node)) {
        targets.push({ pos, node })
        return false
      }
      return true
    })
  }

  if (!targets.length) return false
  const attrs = patchToAttrs(patch)
  const tr = state.tr
  for (const target of targets) {
    tr.setNodeMarkup(target.pos, undefined, { ...target.node.attrs, ...attrs })
  }
  editor.view.dispatch(tr)
  return true
}

interface FormattableBlock {
  node: PMNode
  pos: number
  text: string
}

/** 按文档顺序收集所有可排版块（跳过表格内部，保持与 Markdown 导出顺序一致）。 */
function collectBlocks(doc: PMNode): FormattableBlock[] {
  const blocks: FormattableBlock[] = []
  doc.descendants((node, pos) => {
    if (node.type.name === 'table') return false
    if (isFormattable(node)) {
      blocks.push({ node, pos, text: node.textContent.trim().slice(0, 40) })
      return false
    }
    return true
  })
  return blocks
}

/** 导出给持久化层：只记录真正改过的段落。 */
export function collectParagraphFormats(editor: Editor | null): ParagraphFormatRecord[] {
  if (!editor) return []
  const records: ParagraphFormatRecord[] = []
  collectBlocks(editor.state.doc).forEach((block, index) => {
    const format = formatFromAttrs(block.node.attrs)
    if (!Object.keys(format).length) return
    records.push({ index, text: block.text, ...format })
  })
  return records
}

function normalizeRecords(raw: unknown): ParagraphFormatRecord[] {
  if (!Array.isArray(raw)) return []
  const records: ParagraphFormatRecord[] = []
  raw.forEach((item) => {
    if (!item || typeof item !== 'object') return
    const record = item as Partial<ParagraphFormatRecord>
    if (typeof record.index !== 'number' || !Number.isFinite(record.index)) return
    const format = formatFromAttrs(
      Object.fromEntries(
        ATTR_MAP.map(({ key, attr }) => [attr, (record as Record<string, unknown>)[key]]),
      ),
    )
    if (!Object.keys(format).length) return
    records.push({
      index: Math.max(0, Math.round(record.index)),
      text: typeof record.text === 'string' ? record.text.slice(0, 40) : '',
      ...format,
    })
  })
  return records.sort((a, b) => a.index - b.index)
}

/**
 * 加载笔记后套用持久化的段落格式。
 * 优先按序号匹配；若文档前面增删了段落，则在附近按文本指纹找回。
 */
export function applyParagraphFormats(editor: Editor | null, raw: unknown): number {
  if (!editor) return 0
  const records = normalizeRecords(raw)
  if (!records.length) return 0
  const blocks = collectBlocks(editor.state.doc)
  const used = new Set<number>()
  const tr = editor.state.tr
  let applied = 0

  for (const record of records) {
    let index = record.index
    const exact = blocks[index]
    if (
      !exact ||
      used.has(index) ||
      (record.text && exact.text && exact.text !== record.text)
    ) {
      let found = -1
      const start = Math.max(0, record.index - 6)
      const end = Math.min(blocks.length, record.index + 7)
      for (let i = start; i < end; i += 1) {
        if (used.has(i)) continue
        if (record.text && blocks[i]?.text === record.text) {
          found = i
          break
        }
      }
      if (found < 0 && exact && !used.has(index)) found = index
      if (found < 0) continue
      index = found
    }
    const block = blocks[index]
    if (!block) continue
    used.add(index)
    tr.setNodeMarkup(block.pos, undefined, {
      ...block.node.attrs,
      ...patchToAttrs(record),
    })
    applied += 1
  }

  if (applied) editor.view.dispatch(tr)
  return applied
}

/** 清除段落格式：恢复为“跟随页面设置”的默认排版。 */
export function clearParagraphFormat(
  editor: Editor,
  range?: { from: number; to: number } | null,
): boolean {
  const reset: ParagraphFormatPatch = {
    font: null,
    size: null,
    lineHeight: null,
    lineHeightMode: null,
    lineHeightFixed: null,
    spaceBefore: null,
    spaceAfter: null,
    indentLeft: null,
    indentRight: null,
    firstLineIndent: null,
    hangingIndent: null,
    align: null,
  }
  return applyParagraphFormat(editor, reset, range)
}
