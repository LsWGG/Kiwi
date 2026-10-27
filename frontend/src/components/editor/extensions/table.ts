/**
 * 表格序列化补丁。
 *
 * tiptap-markdown 的表格序列化器用 `firstChild.textContent` 判断单元格是否为空。
 * 当单元格只有一个 mention / 日期 / 公式等原子节点时，ProseMirror 节点的
 * textContent 为空，整格内容会被跳过（例如“对应笔记”列里的 @ 提及）。
 * 这里改为按节点内容大小判断，并把复杂表格（合并单元格等）降级为 HTML。
 */
import Table from '@tiptap/extension-table'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'
import TableRow from '@tiptap/extension-table-row'
import { DOMSerializer, Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet, type EditorView } from '@tiptap/pm/view'
import { normalizeColor } from './textStyle'

interface MarkdownState {
  inTable: boolean
  write: (text: string) => void
  ensureNewLine: () => void
  closeBlock: (node: unknown) => void
  renderInline: (node: unknown) => void
}

interface PmNode {
  type?: { name?: string }
  attrs: Record<string, unknown>
  marks?: Array<{ type?: { name?: string } }>
  childCount: number
  content?: { content?: PmNode[]; size?: number }
  firstChild?: PmNode
  forEach: (fn: (node: PmNode, offset: number, index: number) => void) => void
}

function childNodes(node: PmNode): PmNode[] {
  return node.content?.content ?? []
}

function hasSpan(node: PmNode): boolean {
  return Number(node.attrs.colspan || 1) > 1 || Number(node.attrs.rowspan || 1) > 1
}

function hasTextStyle(node: PmNode): boolean {
  if ((node.marks ?? []).some((mark) => mark.type?.name === 'textStyle')) return true
  return childNodes(node).some(hasTextStyle)
}

function hasCustomColwidth(cell: PmNode): boolean {
  const colwidth = cell.attrs.colwidth
  return Array.isArray(colwidth) && colwidth.some((width) => Number(width) > 0)
}

function hasRichCell(cell: PmNode): boolean {
  return (
    hasSpan(cell) ||
    hasCustomColwidth(cell) ||
    cell.childCount > 1 ||
    Boolean(normalizeColor(cell.attrs.background)) ||
    hasTextStyle(cell)
  )
}

function isMarkdownSerializable(node: PmNode): boolean {
  const rows = childNodes(node)
  const firstRow = rows[0]
  if (!firstRow) return false
  if (rows.some((row) => Boolean(row.attrs.height))) return false
  const headerInvalid = childNodes(firstRow).some(
    (cell) => cell.type?.name !== 'tableHeader' || hasRichCell(cell),
  )
  if (headerInvalid) return false
  return !rows.slice(1).some((row) =>
    childNodes(row).some(
      (cell) => cell.type?.name === 'tableHeader' || hasRichCell(cell),
    ),
  )
}

/** 单元格底色：Markdown 表格无法表达样式，持久化为 data-bg + 行内背景色。 */
function cellBackgroundAttribute() {
  return {
    default: null,
    parseHTML: (element: HTMLElement) =>
      normalizeColor(element.getAttribute('data-bg')) ??
      normalizeColor(element.style.backgroundColor),
    renderHTML: (attributes: Record<string, unknown>) => {
      const background = normalizeColor(attributes.background)
      if (!background) return {}
      return {
        'data-bg': background,
        style: `background-color: ${background}`,
      }
    },
  }
}

export const KiwiTableCell = TableCell.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      background: cellBackgroundAttribute(),
    }
  },
})

export const KiwiTableHeader = TableHeader.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      background: cellBackgroundAttribute(),
    }
  },
})

const ROW_MIN_HEIGHT = 28

function normalizeRowHeight(value: unknown): string | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return `${Math.max(1, Math.round(value))}px`
  }
  if (typeof value === 'string') {
    const match = value.trim().match(/^(\d+(?:\.\d+)?)(?:px)?$/)
    if (match) return `${Math.max(1, Math.round(Number(match[1])))}px`
  }
  return null
}

function rowHeightPixels(value: unknown): number | null {
  const normalized = normalizeRowHeight(value)
  return normalized ? Number.parseFloat(normalized) : null
}

function rowHeightAttribute() {
  return {
    default: null,
    parseHTML: (element: HTMLElement) =>
      normalizeRowHeight(
        element.getAttribute('data-row-height') || element.style.height,
      ),
    renderHTML: (attributes: Record<string, unknown>) => {
      const height = normalizeRowHeight(attributes.height)
      if (!height) return {}
      return { 'data-row-height': height, style: `height: ${height}` }
    },
  }
}

/**
 * 在每行底边框生成横向拖拽手柄，拖动时直接改 tableRow 的 height 属性。
 *
 * 手柄放在行底部而不是左侧：编辑器左侧的全局块拖动手柄（.drag-handle）
 * 覆盖了单元格左缘，放在那里会被它抢走 mousedown，触发原生拖放并破坏表格结构。
 */
function createRowHandle(view: EditorView, rowPos: number): HTMLElement {
  const handle = document.createElement('span')
  handle.className = 'kiwi-row-resize-handle'
  handle.setAttribute('aria-hidden', 'true')
  handle.setAttribute('draggable', 'false')
  handle.addEventListener('dragstart', (event) => event.preventDefault())
  handle.addEventListener('mousedown', (event) => {
    if (event.button !== 0 || !view.editable) return
    event.preventDefault()
    event.stopPropagation()
    const row = view.state.doc.nodeAt(rowPos)
    const rowDom = view.nodeDOM(rowPos)
    if (!row || !(rowDom instanceof HTMLElement)) return

    const startY = event.clientY
    const startHeight = rowDom.getBoundingClientRect().height
    let latest =
      rowHeightPixels(row.attrs.height) ?? Math.max(ROW_MIN_HEIGHT, Math.round(startHeight))

    const onMove = (moveEvent: MouseEvent) => {
      const next = Math.max(
        ROW_MIN_HEIGHT,
        Math.round(startHeight + moveEvent.clientY - startY),
      )
      if (next === latest) return
      latest = next
      const currentNode = view.state.doc.nodeAt(rowPos)
      if (!currentNode) return
      const tr = view.state.tr.setNodeMarkup(rowPos, undefined, {
        ...currentNode.attrs,
        height: `${next}px`,
      })
      tr.setMeta('addToHistory', false)
      view.dispatch(tr)
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.classList.remove('kiwi-row-resizing')
      handle.classList.remove('is-active')
      const currentNode = view.state.doc.nodeAt(rowPos)
      if (!currentNode) return
      // 结束时补一条可撤销的历史记录。
      view.dispatch(
        view.state.tr.setNodeMarkup(rowPos, undefined, {
          ...currentNode.attrs,
          height: `${latest}px`,
        }),
      )
    }

    // widget 的 key 稳定，拖动过程中重建装饰时仍复用这个 DOM。
    handle.classList.add('is-active')
    document.body.classList.add('kiwi-row-resizing')
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  })
  return handle
}

const rowResizePluginKey = new PluginKey('kiwiTableRowResize')

function buildRowDecorations(doc: ProseMirrorNode): DecorationSet {
  const decorations: Decoration[] = []
  doc.descendants((node, pos) => {
    if (node.type.name !== 'tableRow' || !node.firstChild) return true
    // 行起点 + 1 进入行内容，再 + 1 进入第一个单元格内容。
    // 不能放在单元格之间：表格行只允许单元格子节点，浏览器会把 widget
    // 包成匿名单元格，整行多出一列。
    decorations.push(
      Decoration.widget(pos + 2, (view) => createRowHandle(view, pos), {
        side: -1,
        key: `table-row-resize-${pos}`,
      }),
    )
    return false
  })
  return DecorationSet.create(doc, decorations)
}

export const KiwiTableRow = TableRow.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      height: rowHeightAttribute(),
    }
  },
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: rowResizePluginKey,
        state: {
          init: (_config, { doc }) => buildRowDecorations(doc),
          apply: (tr, previous) =>
            tr.docChanged ? buildRowDecorations(tr.doc) : previous,
        },
        props: {
          decorations(state) {
            return rowResizePluginKey.getState(state)
          },
        },
      }),
    ]
  },
})

function tableHtml(editor: { schema: unknown }, node: PmNode): string {
  try {
    const serializer = DOMSerializer.fromSchema(editor.schema as never)
    const holder = document.createElement('div')
    holder.appendChild(serializer.serializeNode(node as never))
    return holder.innerHTML
  } catch {
    return ''
  }
}

export const KiwiTable = Table.extend({
  addStorage() {
    return {
      markdown: {
        serialize(
          this: { editor: { schema: unknown } },
          state: MarkdownState,
          node: PmNode,
          parent: unknown,
        ) {
          if (!isMarkdownSerializable(node)) {
            const html = tableHtml(this.editor, node)
            if (html) state.write(html)
            state.closeBlock(node)
            return
          }
          state.inTable = true
          node.forEach((row, _offset, rowIndex) => {
            state.write('| ')
            row.forEach((col, _cellOffset, colIndex) => {
              if (colIndex) state.write(' | ')
              const cell = col.firstChild
              // 原子节点（mention、日期、公式）没有 textContent，不能据此判空。
              if (cell && (cell.content?.size || 0) > 0) {
                state.renderInline(cell)
              }
            })
            state.write(' |')
            state.ensureNewLine()
            if (!rowIndex) {
              const delimiter = Array.from({ length: row.childCount })
                .map(() => '---')
                .join(' | ')
              state.write(`| ${delimiter} |`)
              state.ensureNewLine()
            }
          })
          state.closeBlock(node)
          state.inTable = false
          void parent
        },
      },
    }
  },
})
