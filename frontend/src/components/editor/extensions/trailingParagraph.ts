/**
 * 末尾空段落：文档以表格 / 图片 / 分割线等块结尾时自动补一个空段落，
 * 保证双击最后一块下方仍能继续输入文字。
 */
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey, type EditorState } from '@tiptap/pm/state'

const trailingParagraphKey = new PluginKey('trailingParagraph')

/** 这些块结尾时无需补空行（可在块内直接回车继续） */
const NO_TRAILING_AFTER = new Set([
  'paragraph',
  'heading',
  'blockquote',
  'codeBlock',
  'bulletList',
  'orderedList',
  'taskList',
])

function needsTrailingParagraph(state: EditorState): boolean {
  const last = state.doc.lastChild
  if (!last || !state.schema.nodes.paragraph) return false
  return !NO_TRAILING_AFTER.has(last.type.name)
}

function trailingTransaction(state: EditorState, addToHistory: boolean) {
  const paragraph = state.schema.nodes.paragraph
  if (!paragraph) return null
  const tr = state.tr.insert(state.doc.content.size, paragraph.create())
  if (!addToHistory) tr.setMeta('addToHistory', false)
  return tr
}

export const TrailingParagraph = Extension.create({
  name: 'trailingParagraph',

  onCreate() {
    const ed = this.editor
    if (!ed.view || !needsTrailingParagraph(ed.state)) return
    // 打开已有的「表格结尾」文档时也立即补上；不进入撤销栈
    const tr = trailingTransaction(ed.state, false)
    if (tr) ed.view.dispatch(tr)
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: trailingParagraphKey,
        appendTransaction: (transactions, _oldState, newState) => {
          if (!transactions.some((tr) => tr.docChanged)) return null
          if (!needsTrailingParagraph(newState)) return null
          return trailingTransaction(newState, true)
        },
      }),
    ]
  },
})
