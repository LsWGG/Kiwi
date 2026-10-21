/**
 * 字符级字体 / 字号：随选区落在 TextStyle mark 上，只影响选中的文字。
 * 与段落排版一样走 props_json 侧车（text_formats），加载后按「文本 + 出现序号」恢复。
 */
import type { Editor } from '@tiptap/core'
import type { Node as PMNode } from '@tiptap/pm/model'
import type { DocxFont } from '../modes'
import { normalizeTextStyleAttrs } from './textStyle'

export interface TextFormatRecord {
  /** 带格式的文本片段（通常就是选区文字） */
  text: string
  /** 同一段文字在文档中第几次出现，用于区分重复内容 */
  occurrence: number
  font?: DocxFont
  size?: number
  /** 文字颜色 #RRGGBB */
  color?: string
}

interface DocumentText {
  text: string
  /** 每个字符对应的 ProseMirror 位置；段落分隔符为 -1 */
  positions: number[]
  /** 每个文本节点起点在全文中的下标 */
  nodeStarts: Map<number, number>
}

/**
 * 把文档拍平成纯文本并记录位置映射。
 * 字符格式只存在于 Markdown 之外的侧车里，重新加载后文本节点会被合并，
 * 因此不能按文本节点匹配，必须按「子串 + 出现序号」定位。
 */
function flattenText(doc: PMNode): DocumentText {
  let text = ''
  const positions: number[] = []
  const nodeStarts = new Map<number, number>()
  doc.descendants((node, pos) => {
    if (node.isText && node.text) {
      nodeStarts.set(pos, text.length)
      for (let i = 0; i < node.text.length; i += 1) positions.push(pos + i)
      text += node.text
    } else if (node.isBlock) {
      text += '\n'
      positions.push(-1)
    }
  })
  return { text, positions, nodeStarts }
}

function countOccurrences(haystack: string, needle: string): number {
  if (!needle) return 0
  let count = 0
  let from = 0
  while (true) {
    const index = haystack.indexOf(needle, from)
    if (index < 0) return count
    count += 1
    from = index + needle.length
  }
}

function normalizeRecords(raw: unknown): TextFormatRecord[] {
  if (!Array.isArray(raw)) return []
  const records: TextFormatRecord[] = []
  raw.forEach((item) => {
    if (!item || typeof item !== 'object') return
    const record = item as Partial<TextFormatRecord>
    if (typeof record.text !== 'string' || !record.text) return
    const attrs = normalizeTextStyleAttrs(record as Record<string, unknown>)
    if (!attrs.font && !attrs.size && !attrs.color) return
    const occurrence = Number(record.occurrence)
    records.push({
      text: record.text,
      occurrence:
        Number.isFinite(occurrence) && occurrence >= 0 ? Math.round(occurrence) : 0,
      ...attrs,
    })
  })
  return records
}

/** 收集文档里所有带字符格式的文本片段。 */
export function collectTextFormats(editor: Editor | null): TextFormatRecord[] {
  if (!editor) return []
  const markType = editor.schema.marks.textStyle
  if (!markType) return []
  const doc = editor.state.doc
  const flat = flattenText(doc)
  const records: TextFormatRecord[] = []
  doc.descendants((node, pos) => {
    if (!node.isText || !node.text) return
    const mark = markType.isInSet(node.marks)
    if (!mark) return
    const attrs = normalizeTextStyleAttrs(mark.attrs)
    if (!attrs.font && !attrs.size && !attrs.color) return
    const start = flat.nodeStarts.get(pos) ?? 0
    // 统计这段文字在它之前出现过多少次，重复内容也能正确定位
    const occurrence = countOccurrences(flat.text.slice(0, start), node.text)
    records.push({ text: node.text, occurrence, ...attrs })
  })
  return records
}

/**
 * 加载笔记后恢复字符格式。
 * 同一个文本片段可能有重复（例如两个「重点」），按出现序号依次对应。
 */
export function applyTextFormats(editor: Editor | null, raw: unknown): number {
  if (!editor) return 0
  const markType = editor.schema.marks.textStyle
  const records = normalizeRecords(raw)
  if (!markType || !records.length) return 0

  const doc = editor.state.doc
  const flat = flattenText(doc)
  const tr = editor.state.tr
  let applied = 0
  for (const record of records) {
    let start = -1
    let from = 0
    for (let index = 0; index <= record.occurrence; index += 1) {
      start = flat.text.indexOf(record.text, from)
      if (start < 0) break
      from = start + record.text.length
    }
    if (start < 0) continue
    const last = start + record.text.length - 1
    const posFrom = flat.positions[start]
    const posTo = flat.positions[last]
    // 匹配跨越段落分隔符时跳过，避免把格式套到不相邻的块
    if (posFrom === undefined || posTo === undefined || posFrom < 0 || posTo < 0) continue
    const end = posTo + 1
    const existing = markType.isInSet(
      doc.nodeAt(posFrom)?.marks ?? [],
    )
    const attrs = normalizeTextStyleAttrs({
      ...(existing?.attrs ?? {}),
      ...(record.font ? { font: record.font } : {}),
      ...(record.size ? { size: record.size } : {}),
      ...(record.color ? { color: record.color } : {}),
    })
    // 同类型 mark 的旧属性会被替换，先移除再按合并后的属性重新添加
    tr.removeMark(posFrom, end, markType)
    tr.addMark(posFrom, end, markType.create(attrs))
    applied += 1
  }

  if (applied) editor.view.dispatch(tr)
  return applied
}

/**
 * 选区非空时只给选中的文字设置字体 / 字号。
 * 返回 false 表示没有可作用的选择（调用方可回退到段落设置）。
 */
export function applyTextFormat(
  editor: Editor | null,
  patch: { font?: DocxFont; size?: number; color?: string | null },
): boolean {
  if (!editor) return false
  const markType = editor.schema.marks.textStyle
  if (!markType) return false
  const { state } = editor
  const { from, to, empty } = state.selection
  const mergedRaw: Record<string, unknown> = {
    ...editor.getAttributes('textStyle'),
    ...patch,
  }
  // color: null 表示显式清除颜色；其余字段保持不变
  if ('color' in patch && patch.color === null) delete mergedRaw.color
  const attrs = normalizeTextStyleAttrs(mergedRaw)
  const chain = editor.chain().focus()
  if (!attrs.font && !attrs.size && !attrs.color) {
    chain.unsetMark('textStyle').run()
    return true
  }
  if (empty) {
    // 无选区：设置为「后续输入」的格式，不改动已有整段文字
    chain.setMark('textStyle', attrs).run()
    return true
  }
  if (!state.doc.textBetween(from, to, '\n', '\n').trim()) return false
  chain.setMark('textStyle', attrs).run()
  return true
}
