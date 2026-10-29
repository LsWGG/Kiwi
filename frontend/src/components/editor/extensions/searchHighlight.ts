/**
 * 搜索结果高亮：用 ProseMirror 行内装饰标出关键词。
 *
 * 为什么不用 CSS Custom Highlight API：Firefox 在这个笔记编辑器的
 * contenteditable 实例里不绘制自定义高亮（连原生选区也不绘制），
 * 但普通行内背景能正常绘制；装饰节点既稳定可见，又会随编辑器
 * 重新渲染自动重建，不会出现 Range 失效后高亮消失的问题。
 */
import { Extension, type Editor } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { Node as PMNode } from '@tiptap/pm/model'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

export const SEARCH_HIGHLIGHT_CLASS = 'kiwi-search-hit'
/** 当前选中的那一处命中，查找条切换上下项时同步。 */
export const SEARCH_HIGHLIGHT_ACTIVE_CLASS = 'kiwi-search-hit-active'
const MAX_SEARCH_MATCHES = 200
const searchHighlightKey = new PluginKey<DecorationSet>('kiwi-search-highlight')

interface SearchHighlightMeta {
  term: string
  /** 当前项下标；-1 表示不区分，用于全局搜索的一次性高亮。 */
  active?: number
  /** 整句未命中时是否按空格拆词兜底；页内查找要求精确匹配。 */
  splitWords?: boolean
}

/** 完整搜索词优先；整句没命中时再按空格拆词，与正文搜索的兜底一致。 */
function buildDecorations(
  doc: PMNode,
  raw: string,
  active = -1,
  splitWords = true,
): DecorationSet {
  const keyword = raw.trim()
  if (!keyword) return DecorationSet.empty
  const candidates = splitWords
    ? [keyword, ...keyword.split(/\s+/)].filter(
        (term, index, list) => !!term && list.indexOf(term) === index,
      )
    : [keyword]

  for (const term of candidates) {
    const needle = term.toLocaleLowerCase()
    const decorations: Decoration[] = []
    doc.descendants((node, pos) => {
      if (!node.isText || !node.text) return true
      const haystack = node.text.toLocaleLowerCase()
      let from = 0
      while (decorations.length < MAX_SEARCH_MATCHES) {
        const index = haystack.indexOf(needle, from)
        if (index < 0) break
        const matchIndex = decorations.length
        decorations.push(
          Decoration.inline(pos + index, pos + index + term.length, {
            class:
              matchIndex === active
                ? `${SEARCH_HIGHLIGHT_CLASS} ${SEARCH_HIGHLIGHT_ACTIVE_CLASS}`
                : SEARCH_HIGHLIGHT_CLASS,
          }),
        )
        from = index + needle.length
      }
      return decorations.length < MAX_SEARCH_MATCHES
    })
    if (decorations.length) return DecorationSet.create(doc, decorations)
  }
  return DecorationSet.empty
}

/**
 * 标记关键词；返回是否命中（滚动交给持有实时面板的调用方）。
 * 页内查找传入 `active` 与 `splitWords = false`，让当前项有独立样式。
 */
export function highlightSearchTerm(
  editor: Editor,
  raw: string,
  active = -1,
  splitWords = true,
): boolean {
  const view = editor.view
  const meta: SearchHighlightMeta = { term: raw, active, splitWords }
  view.dispatch(
    view.state.tr.setMeta(searchHighlightKey, meta).setMeta('addToHistory', false),
  )
  return (searchHighlightKey.getState(view.state)?.find().length ?? 0) > 0
}

/**
 * 页内替换：与查找高亮保持同一匹配语义（单个文本节点内、忽略大小写），
 * 一次替换当前项或全部命中。所有改动放进一个事务，Ctrl+Z 可整体撤销。
 * 返回实际替换的数量。
 */
export function replaceSearchMatches(
  editor: Editor,
  raw: string,
  replacement: string,
  active = 0,
  all = false,
): number {
  const keyword = raw.trim()
  if (!keyword) return 0
  const needle = keyword.toLocaleLowerCase()
  const matches: { from: number; to: number }[] = []
  editor.state.doc.descendants((node, pos) => {
    if (!node.isText || !node.text) return true
    const haystack = node.text.toLocaleLowerCase()
    let from = 0
    while (matches.length < MAX_SEARCH_MATCHES) {
      const index = haystack.indexOf(needle, from)
      if (index < 0) break
      matches.push({ from: pos + index, to: pos + index + keyword.length })
      from = index + needle.length
    }
    return matches.length < MAX_SEARCH_MATCHES
  })
  if (!matches.length) return 0
  const targets = all
    ? matches
    : [matches[Math.min(Math.max(active, 0), matches.length - 1)]]
  let tr = editor.state.tr
  // 从后往前改，前面命中的位置不受影响。
  for (let i = targets.length - 1; i >= 0; i -= 1) {
    const { from, to } = targets[i]
    tr = replacement ? tr.insertText(replacement, from, to) : tr.delete(from, to)
  }
  editor.view.dispatch(tr.scrollIntoView())
  return targets.length
}

export function clearSearchHighlight(editor: Editor) {
  const view = editor.view
  const current = searchHighlightKey.getState(view.state)
  // 已经是空集合时不再派发事务，避免无意义的重渲染。
  if (!current || !current.find().length) return
  view.dispatch(view.state.tr.setMeta(searchHighlightKey, null).setMeta('addToHistory', false))
}

export const SearchHighlight = Extension.create({
  name: 'searchHighlight',

  addProseMirrorPlugins() {
    return [
      new Plugin<DecorationSet>({
        key: searchHighlightKey,
        state: {
          init: () => DecorationSet.empty,
          apply(tr, value) {
            const meta = tr.getMeta(searchHighlightKey) as
              | SearchHighlightMeta
              | string
              | null
              | undefined
            if (meta === null) return DecorationSet.empty
            if (typeof meta === 'string') return buildDecorations(tr.doc, meta)
            if (meta && typeof meta === 'object') {
              return buildDecorations(
                tr.doc,
                meta.term,
                meta.active ?? -1,
                meta.splitWords ?? true,
              )
            }
            return value.map(tr.mapping, tr.doc)
          },
        },
        props: {
          decorations(state) {
            return searchHighlightKey.getState(state)
          },
        },
      }),
    ]
  },
})
