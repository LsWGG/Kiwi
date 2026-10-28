/**
 * YouTube 嵌入：持久化为 `![youtube](url)`，解析后恢复成官方 Youtube 节点。
 */
import Youtube from '@tiptap/extension-youtube'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import { IS_DESKTOP, isBlockedExternalAsset } from '@/desktop/env'
import YoutubePlaceholder from './YoutubePlaceholder.vue'

export const KiwiYoutube = Youtube.extend({
  // 桌面版不渲染官方 iframe 节点视图；保留节点数据与 Markdown 往返。
  ...(IS_DESKTOP
    ? { addNodeView: () => VueNodeViewRenderer(YoutubePlaceholder) }
    : {}),

  renderHTML(props) {
    const { HTMLAttributes } = props
    const src = String(HTMLAttributes.src || '')
    if (!IS_DESKTOP || !isBlockedExternalAsset(src)) {
      return this.parent?.(props) ?? ['div', { 'data-youtube-video': '' }]
    }
    // TipTap 在 NodeView 挂载前会先用 renderHTML 渲染一帧；桌面版不能在这一帧
    // 创建远程 iframe。地址保留在 data-src，解析与复制仍可恢复节点。
    const { src: _blocked, ...rest } = HTMLAttributes
    return ['div', { ...rest, 'data-youtube-video': '', 'data-src': src }]
  },

  parseHTML() {
    const rules = this.parent?.() ?? []
    if (!IS_DESKTOP) return rules
    return [
      ...rules,
      {
        tag: 'div[data-youtube-video][data-src]',
        getAttrs: (element: HTMLElement) => ({
          src: element.getAttribute('data-src') || '',
        }),
      },
    ]
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          state.write(`![youtube](${node.attrs.src || ''})`)
          state.closeBlock(node)
        },
        parse: {
          updateDOM(element: HTMLElement) {
            element.querySelectorAll('img[alt="youtube"]').forEach((img) => {
              const src = img.getAttribute('src') || ''
              if (!src) {
                img.remove()
                return
              }
              const doc = img.ownerDocument
              const wrapper = doc.createElement('div')
              wrapper.setAttribute('data-youtube-video', '')
              if (IS_DESKTOP) {
                // 解析阶段也不创建 iframe；桌面 NodeView 会渲染本地占位。
                wrapper.setAttribute('data-src', src)
              } else {
                const iframe = doc.createElement('iframe')
                iframe.setAttribute('src', src)
                wrapper.appendChild(iframe)
              }
              img.replaceWith(wrapper)
            })
          },
        },
      },
    }
  },
}).configure({
  nocookie: true,
  width: 640,
  height: 360,
  HTMLAttributes: { class: 'kiwi-youtube' },
})
