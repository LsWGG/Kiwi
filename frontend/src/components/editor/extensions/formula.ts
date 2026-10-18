/**
 * 公式块：KaTeX 渲染。
 * Markdown 以 ```kiwi-math 围栏持久化 LaTeX 源码，往返与复制均保持可读。
 */
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import FormulaNodeView from './FormulaNodeView.vue'

const FORMULA_LANGUAGE = 'kiwi-math'

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function fenceFor(value: string): string {
  const runs = value.match(/`+/g) ?? []
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0)
  return '`'.repeat(Math.max(3, longest + 1))
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiFormula: {
      insertFormula: (attrs?: { latex?: string }) => ReturnType
    }
  }
}

export const KiwiFormula = Node.create({
  name: 'kiwiFormula',
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      latex: {
        default: '',
        parseHTML: (element) => element.textContent || '',
      },
    }
  },

  parseHTML() {
    return [{ tag: 'pre[data-kiwi-formula]' }]
  },

  renderHTML({ node }) {
    return [
      'pre',
      { 'data-kiwi-formula': 'true', class: 'kiwi-formula-node' },
      node.attrs.latex || '',
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(FormulaNodeView)
  },

  addCommands() {
    return {
      insertFormula:
        (attrs = {}) =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: { latex: attrs.latex ?? '' },
          }),
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const latex = String(node.attrs.latex || '')
          const fence = fenceFor(latex)
          state.write(`${fence}${FORMULA_LANGUAGE}\n`)
          state.write(latex)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiFormula) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === FORMULA_LANGUAGE) {
                return `<pre data-kiwi-formula="true">${escapeHtml(
                  token.content.trim(),
                )}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiFormula = true
            rules.fence = fence
          },
        },
      },
    }
  },
})
