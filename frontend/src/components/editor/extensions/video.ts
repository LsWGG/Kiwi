/**
 * 视频块：持久化为 `![video](url)`（Markdown 图片语法的一种约定），
 * 解析时识别 alt="video" 并恢复成可播放的视频块。
 */
import { Node, mergeAttributes } from '@tiptap/core'

export interface VideoOptions {
  HTMLAttributes: Record<string, unknown>
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    video: {
      setVideo: (attrs: { src: string }) => ReturnType
    }
  }
}

export const Video = Node.create<VideoOptions>({
  name: 'video',

  group: 'block',

  atom: true,

  draggable: true,

  selectable: true,

  addOptions() {
    return { HTMLAttributes: {} }
  },

  addAttributes() {
    return {
      src: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-src') || '',
        renderHTML: (attributes) => ({ 'data-src': attributes.src }),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-type="video"]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
        'data-type': 'video',
        class: 'video-block',
      }),
      [
        'video',
        {
          src: HTMLAttributes['data-src'],
          controls: 'true',
          preload: 'metadata',
          class: 'kiwi-video',
        },
      ],
    ]
  },

  addCommands() {
    return {
      setVideo:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          state.write(`![video](${node.attrs.src || ''})`)
          state.closeBlock(node)
        },
        parse: {
          updateDOM(element: HTMLElement) {
            element.querySelectorAll('img[alt="video"]').forEach((img) => {
              const src = img.getAttribute('src') || ''
              if (!src) {
                img.remove()
                return
              }
              const doc = element.ownerDocument
              const div = doc.createElement('div')
              div.setAttribute('data-type', 'video')
              div.setAttribute('data-src', src)
              img.replaceWith(div)
            })
          },
        },
      },
    }
  },
})
