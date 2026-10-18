/**
 * YouTube 嵌入：持久化为 `![youtube](url)`，解析后恢复成官方 Youtube 节点。
 */
import Youtube from '@tiptap/extension-youtube'

export const KiwiYoutube = Youtube.extend({
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
              const iframe = doc.createElement('iframe')
              iframe.setAttribute('src', src)
              wrapper.appendChild(iframe)
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
