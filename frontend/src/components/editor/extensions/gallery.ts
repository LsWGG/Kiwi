/**
 * 图册块：多图上传 / 网格或横向滑动展示 / 说明文字 / 大图预览。
 * Markdown 以 ```kiwi-gallery 围栏 + JSON 持久化图片列表与布局。
 */
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import GalleryNodeView from './GalleryNodeView.vue'

export interface GalleryImage {
  url: string
  caption?: string
  name?: string
}

export interface GalleryOptions {
  /** 上传单张图片，返回可访问 URL（由编辑器注入项目的附件上传逻辑） */
  upload?: (file: File) => Promise<{ url: string; filename?: string }>
}

const GALLERY_LANGUAGE = 'kiwi-gallery'

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

function sanitizeImages(value: unknown): GalleryImage[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (typeof item === 'string') return { url: item, caption: '' }
      const row = item as Record<string, unknown>
      return {
        url: String(row?.url ?? ''),
        caption: String(row?.caption ?? ''),
        name: String(row?.name ?? ''),
      }
    })
    .filter((item) => item.url)
}

export const KiwiGallery = Node.create<GalleryOptions>({
  name: 'kiwiGallery',
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addOptions() {
    return { upload: undefined }
  },

  addAttributes() {
    return {
      images: {
        default: [],
        parseHTML: (element) => {
          try {
            return sanitizeImages(JSON.parse(element.textContent || '{}').images)
          } catch {
            return []
          }
        },
      },
      columns: {
        default: 3,
        parseHTML: (element) => {
          try {
            const value = Number(JSON.parse(element.textContent || '{}').columns)
            return value >= 2 && value <= 4 ? value : 3
          } catch {
            return 3
          }
        },
      },
      layout: {
        default: 'grid',
        parseHTML: (element) => {
          try {
            return JSON.parse(element.textContent || '{}').layout === 'carousel'
              ? 'carousel'
              : 'grid'
          } catch {
            return 'grid'
          }
        },
      },
    }
  },

  parseHTML() {
    return [{ tag: 'pre[data-kiwi-gallery]' }]
  },

  renderHTML({ node }) {
    return [
      'pre',
      { 'data-kiwi-gallery': 'true', class: 'kiwi-gallery-node' },
      JSON.stringify({
        images: sanitizeImages(node.attrs.images),
        columns: node.attrs.columns || 3,
        layout: node.attrs.layout || 'grid',
      }),
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(GalleryNodeView)
  },

  addCommands() {
    return {
      insertGallery:
        (attrs = {}) =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: {
              images: [],
              columns: 3,
              layout: 'grid',
              ...attrs,
            },
          }),
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const json = JSON.stringify({
            images: sanitizeImages(node.attrs.images),
            columns: node.attrs.columns || 3,
            layout: node.attrs.layout || 'grid',
          })
          const fence = fenceFor(json)
          state.write(`${fence}${GALLERY_LANGUAGE}\n`)
          state.write(json)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiGallery) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === GALLERY_LANGUAGE) {
                return `<pre data-kiwi-gallery="true">${escapeHtml(
                  token.content.trim(),
                )}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiGallery = true
            rules.fence = fence
          },
        },
      },
    }
  },
})

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiGallery: {
      insertGallery: (attrs?: {
        images?: GalleryImage[]
        columns?: number
        layout?: 'grid' | 'carousel'
      }) => ReturnType
    }
  }
}
