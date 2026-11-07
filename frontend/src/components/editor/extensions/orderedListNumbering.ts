/**
 * 有序列表编号起点：支持「从头开始」与「继续编号」。
 *
 * - Markdown / TipTap 已经用 `start` 属性保存起始序号；
 * - 这里的自定义扩展把 `start` 映射成 CSS 变量，让计数器真正从该序号开始；
 * - Menu / 工具栏通过 `orderedListContext()` 得到当前列表与上一列表的结束序号。
 */
import { mergeAttributes, type Editor } from '@tiptap/core'
import OrderedList from '@tiptap/extension-ordered-list'
import ListItem from '@tiptap/extension-list-item'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'

export const KiwiOrderedList = OrderedList.extend({
  /**
   * 原生 `start` 只影响浏览器默认编号；当前主题使用 CSS 计数器，
   * 因此把起点写进 `--kiwi-ol-base`，由样式表从该值继续计数。
   */
  renderHTML({ HTMLAttributes }) {
    const raw = Number(HTMLAttributes.start)
    const start = Number.isFinite(raw) && raw > 0 ? Math.round(raw) : 1
    const { start: _omit, style, ...rest } = HTMLAttributes
    const css = `${style ? `${style};` : ''}--kiwi-ol-base:${start - 1}`
    const attrs: Record<string, unknown> = { ...rest, style: css }
    if (start > 1) attrs.start = start
    return ['ol', mergeAttributes(this.options.HTMLAttributes, attrs), 0]
  },
})

/**
 * 让列表项的首个块可以是标题：选中标题后点「有序列表」即可得到
 * `1. # 标题` 这样的编号标题，而不是先把标题降级成普通段落。
 */
export const KiwiListItem = ListItem.extend({
  content: '(paragraph | heading) block*',
})

export interface OrderedListContext {
  /** 光标是否位于有序列表内 */
  inList: boolean
  /** 当前列表的起始序号 */
  start: number
  /** 同层级上一有序列表的「下一个序号」；没有则 null */
  continueFrom: number | null
}

function listStart(node: ProseMirrorNode): number {
  const value = Number(node.attrs.start)
  return Number.isFinite(value) && value > 0 ? Math.round(value) : 1
}

function listEnd(node: ProseMirrorNode): number {
  return listStart(node) + node.childCount
}

const STOP_AT = new Set([
  'heading',
  'bulletList',
  'taskList',
  'codeBlock',
  'blockquote',
  'details',
])

/** 从 index 向前找最近的同级有序列表；越过标题 / 其他列表类型即视为新的编号段落。 */
function findPreviousList(parent: ProseMirrorNode, index: number): ProseMirrorNode | null {
  for (let i = index - 1; i >= 0; i -= 1) {
    const sibling = parent.child(i)
    if (sibling.type.name === 'orderedList') return sibling
    if (STOP_AT.has(sibling.type.name)) return null
  }
  return null
}

function listAncestor(editor: Editor): { node: ProseMirrorNode; pos: number } | null {
  const { $from } = editor.state.selection
  for (let depth = $from.depth; depth > 0; depth -= 1) {
    const node = $from.node(depth)
    if (node.type.name === 'orderedList') {
      return { node, pos: $from.before(depth) }
    }
  }
  return null
}

export function orderedListContext(editor: Editor): OrderedListContext {
  const { $from } = editor.state.selection
  const ancestor = listAncestor(editor)
  if (ancestor) {
    const $pos = editor.state.doc.resolve(ancestor.pos)
    const previous = findPreviousList($pos.parent, $pos.index())
    return {
      inList: true,
      start: listStart(ancestor.node),
      continueFrom: previous ? listEnd(previous) : null,
    }
  }
  const parent = editor.state.doc
  const previous = findPreviousList(parent, $from.index(0))
  return { inList: false, start: 1, continueFrom: previous ? listEnd(previous) : null }
}

/** 把当前有序列表（或光标所在列表）的起点改为 start。 */
export function setOrderedListStart(editor: Editor, start: number): boolean {
  const value = Math.max(1, Math.round(start))
  const { state } = editor
  const { from, to } = state.selection
  const tr = state.tr
  let changed = false
  state.doc.nodesBetween(from, to, (node, pos) => {
    if (node.type.name !== 'orderedList') return true
    if (listStart(node) !== value) {
      tr.setNodeMarkup(pos, undefined, { ...node.attrs, start: value })
      changed = true
    }
    return false
  })
  if (!changed && from === to) {
    const ancestor = listAncestor(editor)
    if (ancestor && listStart(ancestor.node) !== value) {
      tr.setNodeMarkup(ancestor.pos, undefined, { ...ancestor.node.attrs, start: value })
      changed = true
    }
  }
  if (!changed) return false
  editor.view.dispatch(tr)
  return true
}

/**
 * 套用编号方式：不在列表中时先创建有序列表，再设置起点。
 * 返回是否成功；标题等块级节点需要 KiwiListItem 允许 heading。
 */
export function applyOrderedListStart(editor: Editor, start: number): boolean {
  const value = Math.max(1, Math.round(start))
  if (!orderedListContext(editor).inList) {
    const created = editor.chain().focus().toggleOrderedList().run()
    if (!created) return false
  }
  return setOrderedListStart(editor, value)
}
