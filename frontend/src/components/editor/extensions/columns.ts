/**
 * 分栏卡片：2 - 4 栏并排的富文本块。
 * Markdown 以引用块标记持久化，栏内可继续使用标题、列表、提示块等全部块级内容：
 *   > [!COLUMNS]
 *   >
 *   > [!COLUMN]
 *   > 左栏…
 *   >
 *   > [!COLUMN]
 *   > 右栏…
 */
import { Node } from '@tiptap/core'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiColumns: {
      insertColumns: (attrs?: { count?: number }) => ReturnType
    }
  }
}

export const KiwiColumn = Node.create({
  name: 'kiwiColumn',
  content: 'block+',
  isolating: true,

  parseHTML() {
    return [{ tag: 'div[data-kiwi-column]' }]
  },

  renderHTML() {
    return [
      'div',
      { 'data-kiwi-column': 'true', class: 'kiwi-column', style: 'min-width:0' },
      0,
    ]
  },
})

export const KiwiColumns = Node.create({
  name: 'kiwiColumns',
  group: 'block',
  content: 'kiwiColumn{2,4}',
  defining: true,

  parseHTML() {
    return [{ tag: 'div[data-kiwi-columns]' }]
  },

  renderHTML({ node }) {
    const count = Math.max(2, Math.min(4, node.childCount || 2))
    return [
      'div',
      {
        'data-kiwi-columns': String(count),
        class: 'kiwi-columns',
        style: `display:grid;grid-template-columns:repeat(${count},minmax(0,1fr));gap:12px;margin:0.75rem 0;align-items:start`,
      },
      0,
    ]
  },

  addCommands() {
    return {
      insertColumns:
        (attrs = {}) =>
        ({ chain }) => {
          const count = Math.max(2, Math.min(4, Number(attrs.count) || 2))
          const content = Array.from({ length: count }, () => ({
            type: 'kiwiColumn',
            content: [{ type: 'paragraph' }],
          }))
          return chain()
            .insertContent({ type: this.name, content })
            .run()
        },
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const baseDelim = state.delim
          state.write('> [!COLUMNS]')
          state.ensureNewLine()
          state.write('>')
          state.ensureNewLine()
          // 整个分栏块保持引用前缀。不能逐栏 wrapBlock：wrapBlock 退出时
          // 会恢复外层 delim，导致栏之间的空行不带 “>”，把引用块截断。
          state.delim = baseDelim + '> '
          node.forEach((column: any) => {
            state.write('[!COLUMN]')
            state.ensureNewLine()
            // 标记行与正文之间留一个空引用行，否则会被解析成同一段落。
            const contentDelim = state.delim
            state.delim = baseDelim + '>'
            state.write('')
            state.ensureNewLine()
            state.delim = contentDelim
            state.renderContent(column)
          })
          state.delim = baseDelim
          state.closeBlock(node)
        },
        parse: {
          updateDOM(element: HTMLElement) {
            const doc = element.ownerDocument
            element.querySelectorAll('blockquote').forEach((quote) => {
              const children = Array.from(quote.children)
              const marker = children[0]
              if (!marker || marker.tagName !== 'P') return
              if ((marker.textContent || '').trim() !== '[!COLUMNS]') return

              const wrap = doc.createElement('div')
              wrap.setAttribute('data-kiwi-columns', 'true')
              let current: HTMLElement | null = null
              children.slice(1).forEach((child) => {
                const isDivider =
                  child.tagName === 'P' &&
                  (child.textContent || '').trim() === '[!COLUMN]'
                if (isDivider) {
                  current = doc.createElement('div')
                  current.setAttribute('data-kiwi-column', 'true')
                  wrap.appendChild(current)
                  return
                }
                if (!current) {
                  current = doc.createElement('div')
                  current.setAttribute('data-kiwi-column', 'true')
                  wrap.appendChild(current)
                }
                current.appendChild(child)
              })
              // 空栏补一个空段落，避免 block+ 内容约束导致整块被丢弃
              Array.from(wrap.children).forEach((column) => {
                if (!column.childElementCount) {
                  const paragraph = doc.createElement('p')
                  paragraph.innerHTML = '<br>'
                  column.appendChild(paragraph)
                }
              })
              if (wrap.childElementCount >= 2) quote.replaceWith(wrap)
            })
          },
        },
      },
    }
  },
})
