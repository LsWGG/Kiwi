/**
 * 分页符（DOCX 模式）：编辑区显示为分页标记，导出 Word 时落成真正的分页符。
 * Markdown 以 ```kiwi-pagebreak 围栏持久化，避免与普通代码块混淆。
 */
import { Node } from '@tiptap/core'

const PAGE_BREAK_LANGUAGE = 'kiwi-pagebreak'

export const PageBreak = Node.create({
  name: 'pageBreak',
  group: 'block',
  atom: true,
  selectable: true,

  parseHTML() {
    return [{ tag: 'div[data-kiwi-page-break]' }]
  },

  renderHTML() {
    return ['div', { 'data-kiwi-page-break': 'true', class: 'kiwi-page-break' }]
  },

  addKeyboardShortcuts() {
    return {
      'Mod-Enter': () => this.editor.commands.insertContent({ type: this.name }),
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          state.write('```' + PAGE_BREAK_LANGUAGE + '\n')
          state.write('```')
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiPageBreak) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === PAGE_BREAK_LANGUAGE) {
                return '<div data-kiwi-page-break="true"></div>\n'
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiPageBreak = true
            rules.fence = fence
          },
        },
      },
    }
  },
})
