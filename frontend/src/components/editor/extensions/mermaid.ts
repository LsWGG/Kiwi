/**
 * Mermaid 文本绘图块。
 * Markdown 以 ```mermaid 围栏持久化源码（与 GitHub / Typora 兼容）。
 */
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import MermaidNodeView from './MermaidNodeView.vue'

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
    kiwiMermaid: {
      insertMermaid: (attrs?: { code?: string }) => ReturnType
    }
  }
}

export const DEFAULT_MERMAID = `flowchart LR
  A[需求] --> B{方案评审}
  B -->|通过| C[开发]
  B -->|驳回| A
  C --> D[验收]`

export const KiwiMermaid = Node.create({
  name: 'kiwiMermaid',
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      code: {
        default: '',
        parseHTML: (element) => element.textContent || '',
      },
    }
  },

  parseHTML() {
    return [{ tag: 'pre[data-kiwi-mermaid]' }]
  },

  renderHTML({ node }) {
    return [
      'pre',
      { 'data-kiwi-mermaid': 'true', class: 'kiwi-mermaid-node' },
      node.attrs.code || '',
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(MermaidNodeView)
  },

  addCommands() {
    return {
      insertMermaid:
        (attrs = {}) =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: { code: attrs.code ?? DEFAULT_MERMAID },
          }),
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const code = String(node.attrs.code || '')
          const fence = fenceFor(code)
          state.write(`${fence}mermaid\n`)
          state.write(code)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiMermaid) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === 'mermaid') {
                return `<pre data-kiwi-mermaid="true">${escapeHtml(
                  token.content.trim(),
                )}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiMermaid = true
            rules.fence = fence
          },
        },
      },
    }
  },
})
