/**
 * 日期行内组件。
 * Markdown 持久化为可读的 `📅 2026-10-18`，重新解析时还原成可点击修改的日期胶囊。
 */
import { Node, mergeAttributes } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import DateNodeView from './DateNodeView.vue'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiDate: {
      insertDate: (attrs: { date: string }) => ReturnType
    }
  }
}

const DATE_RE = /📅\s*(\d{4}-\d{2}-\d{2})/g

export function todayISO(): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export const KiwiDate = Node.create({
  name: 'kiwiDate',
  inline: true,
  group: 'inline',
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      date: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-kiwi-date') || '',
      },
    }
  },

  parseHTML() {
    return [{ tag: 'span[data-kiwi-date]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'span',
      mergeAttributes(HTMLAttributes, {
        'data-kiwi-date': HTMLAttributes.date,
        class: 'kiwi-date-chip',
      }),
      `📅 ${HTMLAttributes.date || ''}`,
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(DateNodeView)
  },

  addCommands() {
    return {
      insertDate:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          state.write(`📅 ${node.attrs.date || ''}`.trim())
        },
        parse: {
          updateDOM(element: HTMLElement) {
            const doc = element.ownerDocument
            const walker = doc.createTreeWalker(element, NodeFilter.SHOW_TEXT)
            const textNodes: Text[] = []
            while (walker.nextNode()) {
              const text = walker.currentNode as Text
              if (text.parentElement?.closest('pre, code')) continue
              if ((text.data || '').includes('📅')) textNodes.push(text)
            }
            textNodes.forEach((text) => {
              const value = text.data
              DATE_RE.lastIndex = 0
              let match: RegExpExecArray | null
              let last = 0
              let fragment: DocumentFragment | null = null
              while ((match = DATE_RE.exec(value))) {
                if (!fragment) fragment = doc.createDocumentFragment()
                if (match.index > last) {
                  fragment.appendChild(doc.createTextNode(value.slice(last, match.index)))
                }
                const chip = doc.createElement('span')
                chip.setAttribute('data-kiwi-date', match[1])
                chip.textContent = `📅 ${match[1]}`
                fragment.appendChild(chip)
                last = match.index + match[0].length
              }
              if (!fragment) return
              if (last < value.length) {
                fragment.appendChild(doc.createTextNode(value.slice(last)))
              }
              text.replaceWith(fragment)
            })
          },
        },
      },
    }
  },
})
