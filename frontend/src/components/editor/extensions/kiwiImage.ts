/**
 * 图片节点：支持拖动缩放、裁剪、点击放大、下载与图注。
 *
 * 普通图片仍序列化为标准 Markdown（`![alt](src "图注")`）；设置宽度后
 * 序列化为 ```kiwi-image 围栏 + JSON，保证尺寸在保存 / 重新打开后不丢失。
 */
import Image, { type ImageOptions } from '@tiptap/extension-image'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import ImageNodeView from './ImageNodeView.vue'
import { foldImageCaptionTokens } from '../imageCaptions'
import { IS_DESKTOP, isBlockedExternalAsset } from '@/desktop/env'

const IMAGE_LANGUAGE = 'kiwi-image'

export interface KiwiImageOptions extends ImageOptions {
  /** 上传裁剪后的图片，由编辑器注入附件上传逻辑。 */
  upload?: (file: File) => Promise<{ url: string; filename?: string }>
}

function escapeAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, ' ')
}

function fenceFor(value: string): string {
  const runs = value.match(/`+/g) ?? []
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0)
  return '`'.repeat(Math.max(3, longest + 1))
}

function escapeAlt(value: string): string {
  return value.replace(/[[\]]/g, '\\$&')
}

function imageAttrsHtml(data: Record<string, unknown>): string {
  const src = String(data.src || '')
  if (!src) return ''
  const alt = String(data.alt || '')
  const title = String(data.title || '')
  const width = Number(data.width) || 0
  return (
    `<img src="${escapeAttr(src)}" alt="${escapeAttr(alt)}"` +
    (title ? ` title="${escapeAttr(title)}"` : '') +
    (width > 0 ? ` width="${Math.round(width)}"` : '') +
    ` />`
  )
}

export const KiwiImage = Image.extend<KiwiImageOptions>({
  addOptions() {
    return {
      ...this.parent?.(),
      upload: undefined,
    }
  },

  addAttributes() {
    return {
      ...this.parent?.(),
      width: {
        default: null,
        parseHTML: (element) => {
          const raw = element.getAttribute('width') || element.style.width || ''
          const value = Number.parseInt(raw, 10)
          return Number.isFinite(value) && value > 0 ? value : null
        },
        renderHTML: (attributes) => {
          if (!attributes.width) return {}
          return { width: attributes.width }
        },
      },
    }
  },

  addNodeView() {
    return VueNodeViewRenderer(ImageNodeView)
  },

  renderHTML(props) {
    const { HTMLAttributes } = props
    const src = String(HTMLAttributes.src || '')
    if (!IS_DESKTOP || !isBlockedExternalAsset(src)) {
      return this.parent?.(props) ?? ['img', HTMLAttributes]
    }
    // TipTap 创建 EditorView 时会先用 renderHTML 渲染一帧，随后才挂载
    // NodeView。桌面版这一帧不能把远程 src 交给浏览器，否则图片会立即外联；
    // 地址保留在 data 属性中，NodeView 与复制 / 粘贴仍能拿到原始地址。
    const { src: _blocked, ...rest } = HTMLAttributes
    return ['img', { ...rest, 'data-kiwi-blocked-src': src }]
  },

  parseHTML() {
    return [
      ...(this.parent?.() ?? []),
      {
        tag: 'img[data-kiwi-blocked-src]',
        getAttrs: (element: HTMLElement) => ({
          src: element.getAttribute('data-kiwi-blocked-src') || '',
          alt: element.getAttribute('alt') || null,
          title: element.getAttribute('title') || null,
        }),
      },
    ]
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const src = String(node.attrs.src || '')
          if (!src) return
          const alt = String(node.attrs.alt || '')
          const title = String(node.attrs.title || '')
          const width = Number(node.attrs.width) || 0
          if (width > 0) {
            const json = JSON.stringify({ src, alt, title, width: Math.round(width) })
            const fence = fenceFor(json)
            // 逐行 write：序列化器只在行首补 `state.delim`（引用块 / 列表缩进）。
            // 一次写入含换行符的整段围栏，会让后续行丢掉 `> ` 前缀，把图片
            // JSON 挤出引用块，重新打开时整段内容变成乱码。
            state.write(`${fence}${IMAGE_LANGUAGE}`)
            state.ensureNewLine()
            state.write(json)
            state.ensureNewLine()
            state.write(fence)
            state.closeBlock(node)
            return
          }
          const titlePart = title ? ` "${title.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"` : ''
          state.write(`![${escapeAlt(alt)}](${src}${titlePart})`)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            // 兼容「图片 + 独立图注段落」的历史写法：解析时折叠为图片 title。
            if (!markdownit.__kiwiImageCaptionFold) {
              markdownit.core.ruler.push('kiwi_image_caption_fold', foldImageCaptionTokens)
              markdownit.__kiwiImageCaptionFold = true
            }
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiImage) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === IMAGE_LANGUAGE) {
                try {
                  const data = JSON.parse(token.content.trim() || '{}')
                  const html = imageAttrsHtml(data)
                  return html ? `${html}\n` : ''
                } catch {
                  return ''
                }
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiImage = true
            rules.fence = fence
          },
        },
      },
    }
  },
})
