/**
 * 表格序列化补丁。
 *
 * tiptap-markdown 的表格序列化器用 `firstChild.textContent` 判断单元格是否为空。
 * 当单元格只有一个 mention / 日期 / 公式等原子节点时，ProseMirror 节点的
 * textContent 为空，整格内容会被跳过（例如“对应笔记”列里的 @ 提及）。
 * 这里改为按节点内容大小判断，并把复杂表格（合并单元格等）降级为 HTML。
 */
import Table from '@tiptap/extension-table'
import { DOMSerializer } from '@tiptap/pm/model'

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

function isMarkdownSerializable(node: PmNode): boolean {
  const rows = childNodes(node)
  const firstRow = rows[0]
  if (!firstRow) return false
  const headerInvalid = childNodes(firstRow).some(
    (cell) => cell.type?.name !== 'tableHeader' || hasSpan(cell) || cell.childCount > 1,
  )
  if (headerInvalid) return false
  return !rows.slice(1).some((row) =>
    childNodes(row).some(
      (cell) =>
        cell.type?.name === 'tableHeader' || hasSpan(cell) || cell.childCount > 1,
    ),
  )
}

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
