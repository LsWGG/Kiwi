/**
 * 通用插件区块节点：schema 固定为 kiwiPluginBlock，具体渲染由已加载的
 * 第三方组件决定。Markdown 使用 ```kiwi-plugin 围栏 + JSON 持久化：
 *
 *   { "plugin": "counter", "block": "counter", "props": { "count": 2 }, "align": "center" }
 *
 * 即使插件被停用 / 卸载，节点和 props 仍保留，可在重新安装后恢复渲染。
 */
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import PluginBlockNodeView from './PluginBlockNodeView.vue'

const PLUGIN_LANGUAGE = 'kiwi-plugin'

export type PluginBlockAlign = 'left' | 'center' | 'right'

export interface PluginBlockPayload {
  plugin: string
  block: string
  props: Record<string, unknown>
  /** 水平对齐；缺省 / 历史数据按左对齐处理。 */
  align?: PluginBlockAlign
}

export function normalizePluginAlign(value: unknown): PluginBlockAlign {
  return value === 'center' || value === 'right' ? value : 'left'
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function fenceFor(value: string): string {
  const runs = value.match(/`+/g) ?? []
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0)
  return '`'.repeat(Math.max(3, longest + 1))
}

function plainProps(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  try {
    const parsed = JSON.parse(JSON.stringify(value))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function parsePayload(element: HTMLElement): PluginBlockPayload {
  try {
    const data = JSON.parse(element.textContent || '{}')
    return {
      plugin: String(data?.plugin || '').slice(0, 80),
      block: String(data?.block || '').slice(0, 80),
      props: plainProps(data?.props),
      align: normalizePluginAlign(data?.align ?? element.dataset?.align),
    }
  } catch {
    return { plugin: '', block: '', props: {}, align: 'left' }
  }
}

function payloadFor(attrs: Record<string, unknown>): PluginBlockPayload {
  const align = normalizePluginAlign(attrs.align)
  const payload: PluginBlockPayload = {
    plugin: String(attrs.pluginKey || ''),
    block: String(attrs.blockType || ''),
    props: plainProps(attrs.props),
  }
  // 左对齐是默认值；不写入围栏 JSON，保持旧文件与 diff 稳定。
  if (align !== 'left') payload.align = align
  return payload
}

export const KiwiPluginBlock = Node.create({
  name: 'kiwiPluginBlock',
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      pluginKey: {
        default: '',
        parseHTML: (element) => parsePayload(element).plugin,
      },
      blockType: {
        default: '',
        parseHTML: (element) => parsePayload(element).block,
      },
      props: {
        default: {},
        parseHTML: (element) => parsePayload(element).props,
      },
      align: {
        default: 'left',
        parseHTML: (element) =>
          normalizePluginAlign(parsePayload(element).align),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'pre[data-kiwi-plugin]' }]
  },

  renderHTML({ node }) {
    return [
      'pre',
      {
        'data-kiwi-plugin': 'true',
        'data-align': normalizePluginAlign(node.attrs.align),
        class: 'kiwi-plugin-node',
      },
      JSON.stringify(payloadFor(node.attrs)),
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(PluginBlockNodeView)
  },

  addCommands() {
    return {
      insertPluginBlock:
        (attrs) =>
        ({ commands }) => {
          if (!attrs.pluginKey || !attrs.blockType) return false
          return commands.insertContent({
            type: this.name,
            attrs: {
              pluginKey: attrs.pluginKey,
              blockType: attrs.blockType,
              props: plainProps(attrs.props),
            },
          })
        },
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const json = JSON.stringify(payloadFor(node.attrs))
          const fence = fenceFor(json)
          state.write(`${fence}${PLUGIN_LANGUAGE}\n`)
          state.write(json)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiPluginBlock) return
            const originalFence = rules.fence
            const fence = (
              tokens: any[],
              idx: number,
              options: any,
              env: any,
              self: any,
            ) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === PLUGIN_LANGUAGE) {
                let align: PluginBlockAlign = 'left'
                try {
                  align = normalizePluginAlign(JSON.parse(token.content)?.align)
                } catch {
                  align = 'left'
                }
                return `<pre data-kiwi-plugin="true" data-align="${align}">${escapeHtml(
                  token.content.trim(),
                )}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiPluginBlock = true
            rules.fence = fence
          },
        },
      },
    }
  },
})

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiPluginBlock: {
      insertPluginBlock: (attrs: {
        pluginKey: string
        blockType: string
        props?: Record<string, unknown>
        align?: PluginBlockAlign
      }) => ReturnType
    }
  }
}
