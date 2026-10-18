/**
 * 内嵌数据表 Tiptap 节点：数据模型见 dataTableModel.ts。
 * Markdown 以 ```kiwi-datatable 围栏 + JSON 持久化。
 */
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import DataTableNodeView from './DataTableNodeView.vue'
import {
  defaultDataTableModel,
  normalizeDataTable,
  type DataTableAttrs,
} from './dataTableModel'

export * from './dataTableModel'

const DATATABLE_LANGUAGE = 'kiwi-datatable'

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function fenceFor(value: string): string {
  const runs = value.match(/`+/g) ?? []
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0)
  return '`'.repeat(Math.max(3, longest + 1))
}

function parseDataTable(element: HTMLElement) {
  try {
    return JSON.parse(element.textContent || '{}')
  } catch {
    return {}
  }
}

export const KiwiDataTable = Node.create({
  name: 'kiwiDataTable',
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    const defaults = defaultDataTableModel()
    return {
      title: {
        default: '',
        parseHTML: (element) => normalizeDataTable(parseDataTable(element)).title,
      },
      fields: {
        default: defaults.fields,
        parseHTML: (element) => normalizeDataTable(parseDataTable(element)).fields,
      },
      views: {
        default: defaults.views,
        parseHTML: (element) => normalizeDataTable(parseDataTable(element)).views,
      },
      rows: {
        default: [],
        parseHTML: (element) => normalizeDataTable(parseDataTable(element)).rows,
      },
      view: {
        default: 'table',
        parseHTML: (element) => normalizeDataTable(parseDataTable(element)).view,
      },
    }
  },

  parseHTML() {
    return [{ tag: 'pre[data-kiwi-datatable]' }]
  },

  renderHTML({ node }) {
    const model = normalizeDataTable({
      title: node.attrs.title,
      fields: node.attrs.fields,
      views: node.attrs.views,
      rows: node.attrs.rows,
      view: node.attrs.view,
    })
    return [
      'pre',
      { 'data-kiwi-datatable': 'true', class: 'kiwi-datatable-node' },
      JSON.stringify(model),
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(DataTableNodeView)
  },

  addCommands() {
    return {
      insertDataTable:
        (attrs: DataTableAttrs = {}) =>
        ({ commands }) => {
          const model = normalizeDataTable({
            ...defaultDataTableModel(),
            ...attrs,
            // 未显式传入标题时保持为空占位
            title: attrs.title ?? '',
          })
          return commands.insertContent({
            type: this.name,
            attrs: model,
          })
        },
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const model = normalizeDataTable({
            title: node.attrs.title,
            fields: node.attrs.fields,
            views: node.attrs.views,
            rows: node.attrs.rows,
            view: node.attrs.view,
          })
          const json = JSON.stringify(model)
          const fence = fenceFor(json)
          state.write(`${fence}${DATATABLE_LANGUAGE}\n`)
          state.write(json)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiDataTable) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === DATATABLE_LANGUAGE) {
                return `<pre data-kiwi-datatable="true">${escapeHtml(
                  token.content.trim(),
                )}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiDataTable = true
            rules.fence = fence
          },
        },
      },
    }
  },
})

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiDataTable: {
      insertDataTable: (attrs?: DataTableAttrs) => ReturnType
    }
  }
}
