/**
 * Notion 风格提示块（Callout）。
 * 持久化为 blockquote + `[!TIP] emoji` 标记，保证 Markdown 往返不丢内容；
 * 解析时再还原成带背景的 callout 节点。
 */
import { Node, mergeAttributes } from '@tiptap/core'

export interface CalloutOptions {
  HTMLAttributes: Record<string, unknown>
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    callout: {
      setCallout: (attrs?: { emoji?: string }) => ReturnType
      toggleCallout: (attrs?: { emoji?: string }) => ReturnType
    }
  }
}

export const Callout = Node.create<CalloutOptions>({
  name: 'callout',

  group: 'block',

  content: 'block+',

  defining: true,

  addOptions() {
    return { HTMLAttributes: {} }
  },

  addAttributes() {
    return {
      emoji: {
        default: '💡',
        parseHTML: (element) => element.getAttribute('data-emoji') || '💡',
        renderHTML: (attributes) => ({ 'data-emoji': attributes.emoji }),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-type="callout"]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
        'data-type': 'callout',
        class: 'callout-block',
      }),
      0,
    ]
  },

  addCommands() {
    return {
      setCallout:
        (attrs) =>
        ({ commands }) =>
          commands.wrapIn(this.name, attrs),
      toggleCallout:
        (attrs) =>
        ({ commands }) =>
          commands.toggleWrap(this.name, attrs),
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const emoji = node.attrs.emoji || '💡'
          state.write(`> [!TIP] ${emoji}`)
          state.ensureNewLine()
          // 空引用行，避免解析时标记行与正文首行合并成同一段
          state.write('>')
          state.ensureNewLine()
          state.wrapBlock('> ', null, node, () => state.renderContent(node))
          state.closeBlock(node)
        },
        parse: {
          updateDOM(element: HTMLElement) {
            element.querySelectorAll('blockquote').forEach((quote) => {
              const first = quote.firstElementChild
              if (!first || first.tagName !== 'P') return
              const text = first.textContent || ''
              const match = text.match(/^\[!TIP\]\s*([^\n]*)/)
              if (!match) return
              const emoji = (match[1] || '').trim() || '💡'
              const rest = text.slice(match[0].length).replace(/^\n+/, '')
              const doc = element.ownerDocument
              const div = doc.createElement('div')
              div.setAttribute('data-type', 'callout')
              div.setAttribute('data-emoji', emoji)
              if (rest.trim()) {
                // 兼容旧的「标记行 + 正文同一段」写法
                first.textContent = rest
              } else {
                first.remove()
              }
              while (quote.firstChild) div.appendChild(quote.firstChild)
              quote.replaceWith(div)
            })
          },
        },
      },
    }
  },
})
