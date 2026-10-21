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
import { DOMSerializer } from '@tiptap/pm/model'
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

function hasRichCell(cell: PmNode): boolean {
  return (
    hasSpan(cell) ||
    cell.childCount > 1 ||
    Boolean(normalizeColor(cell.attrs.background)) ||
    hasTextStyle(cell)
  )
}

function isMarkdownSerializable(node: PmNode): boolean {
  const rows = childNodes(node)
  const firstRow = rows[0]
  if (!firstRow) return false
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
