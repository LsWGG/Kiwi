/**
 * 文档内嵌块（链接卡片 / 附件内容预览）。
 * Markdown 以 ```kiwi-embed 围栏 + JSON 持久化，保证标题、站点、摘要、文件信息往返不丢失。
 */
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import EmbedNodeView from './EmbedNodeView.vue'

const EMBED_LANGUAGE = 'kiwi-embed'

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

export const EMBED_ATTRS = {
  kind: 'file',
  url: '',
  title: '',
  site: '',
  excerpt: '',
  favicon: '',
  filename: '',
  contentType: '',
  size: 0,
  display: 'content',
  height: 0,
} as const

export type EmbedDisplay = 'content' | 'title' | 'web'

function embedDisplay(kind: string, value: unknown): EmbedDisplay {
  if (value === 'title') return 'title'
  // 网页内容嵌入仅对链接有效
  if (value === 'web' && kind === 'link') return 'web'
  return 'content'
}

export function embedAttrs(payload: Record<string, any>) {
  const kind = payload.kind === 'link' ? 'link' : 'file'
  return {
    kind,
    url: String(payload.url ?? ''),
    title: String(payload.title ?? ''),
    site: String(payload.site ?? ''),
    excerpt: String(payload.excerpt ?? ''),
    favicon: String(payload.favicon ?? ''),
    filename: String(payload.filename ?? ''),
    contentType: String(payload.contentType ?? ''),
    size: Number(payload.size) || 0,
    display: embedDisplay(kind, payload.display),
    /** 嵌入窗口自定义高度（px）；0 表示自动 */
    height: Math.min(1600, Math.max(0, Math.round(Number(payload.height) || 0))),
  }
}

export const EmbedBlock = Node.create({
  name: 'embedBlock',
  // 必须排在 codeBlock 之前：ProseMirror 按 schema 节点顺序匹配 parseDOM，
  // 否则代码块的 `pre` 规则会先吞掉 <pre data-kiwi-embed>。
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      kind: { default: 'file' },
      url: { default: '' },
      title: { default: '' },
      site: { default: '' },
      excerpt: { default: '' },
      favicon: { default: '' },
      filename: { default: '' },
      contentType: { default: '' },
      size: { default: 0 },
      display: { default: 'content' },
      height: { default: 0 },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'pre[data-kiwi-embed]',
        getAttrs: (element) => {
          try {
            const data = JSON.parse((element as HTMLElement).textContent || '{}')
            return embedAttrs(data)
          } catch {
            return false
          }
        },
      },
    ]
  },

  renderHTML({ node }) {
    const attrs = embedAttrs(node.attrs)
    return [
      'pre',
      { 'data-kiwi-embed': 'true', class: 'kiwi-embed-node' },
      JSON.stringify(attrs),
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(EmbedNodeView)
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const attrs = embedAttrs(node.attrs)
          const json = JSON.stringify(attrs)
          const fence = fenceFor(json)
          state.write(`${fence}${EMBED_LANGUAGE}\n`)
          state.write(json)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiEmbed) return
            const originalFence = rules.fence
            const fence = (
              tokens: any[],
              idx: number,
              options: any,
              env: any,
              self: any,
            ) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === EMBED_LANGUAGE) {
                return `<pre data-kiwi-embed="true">${escapeHtml(token.content.trim())}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiEmbed = true
            rules.fence = fence
          },
        },
      },
    }
  },
})
