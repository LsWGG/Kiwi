/**
 * 折叠块（Details）：标题 + 可展开内容。
 * 持久化沿用 Obsidian 折叠标注：
 *   > [!DETAILS]+ 标题      （+ 展开，- 收起）
 *   >
 *   > 正文…
 * 解析时还原成 details / detailsSummary / detailsContent 三个节点。
 */
import { Details } from '@tiptap/extension-details'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiDetails: {
      /** 在当前块后插入一个展开的折叠块，光标落在标题里 */
      insertDetails: () => ReturnType
      /** 不在折叠块内则插入，在折叠块内则解除折叠 */
      toggleKiwiDetails: () => ReturnType
      /** 展开 / 收起光标所在的折叠块 */
      toggleDetailsOpen: () => ReturnType
    }
  }
}

export const KiwiDetails = Details.extend({
  addOptions() {
    return {
      ...this.parent?.(),
      // 记录 open 状态，才能在 Markdown 往返中保留「展开 / 收起」
      persist: true,
      openClassName: 'is-open',
    }
  },

  addCommands() {
    return {
      ...this.parent?.(),
      insertDetails:
        () =>
        ({ state, chain }) => {
          const { from } = state.selection
          return chain()
            .insertContentAt(from, {
              type: 'details',
              attrs: { open: true },
              content: [
                { type: 'detailsSummary' },
                { type: 'detailsContent', content: [{ type: 'paragraph' }] },
              ],
            })
            .setTextSelection(from + 2)
            .run()
        },
      toggleKiwiDetails:
        () =>
        ({ editor, commands }) =>
          editor.isActive('details')
            ? commands.unsetDetails()
            : commands.insertDetails(),
      toggleDetailsOpen:
        () =>
        ({ state, chain }) => {
          const { from, to } = state.selection
          let target = -1
          let open = true
          state.doc.descendants((node, pos) => {
            if (node.type.name !== 'details') return true
            if (pos < from && pos + node.nodeSize > to) {
              target = pos
              open = !node.attrs.open
              return false
            }
            return true
          })
          if (target < 0) return false
          return chain()
            .focus()
            .command(({ tr, state: next }) => {
              const node = next.doc.nodeAt(target)
              if (!node) return false
              tr.setNodeMarkup(target, undefined, { ...node.attrs, open })
              return true
            })
            .run()
        },
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const summary = (node.firstChild?.textContent || '').trim() || '折叠内容'
          const open = node.attrs.open !== false
          state.write(`> [!DETAILS]${open ? '+' : '-'} ${summary}`)
          state.ensureNewLine()
          // 空引用行，避免标记行与正文首行合并
          state.write('>')
          state.ensureNewLine()
          const content = node.child(1)
          if (content && content.content.size > 0) {
            state.wrapBlock('> ', null, content, () => state.renderContent(content))
          }
          state.closeBlock(node)
        },
        parse: {
          updateDOM(element: HTMLElement) {
            element.querySelectorAll('blockquote').forEach((quote) => {
              const first = quote.firstElementChild
              if (!first || first.tagName !== 'P') return
              const text = first.textContent || ''
              const match = text.match(/^\[!DETAILS\]([+-])?\s*([\s\S]*)$/)
              if (!match) return
              const open = match[1] !== '-'
              const title = (match[2] || '').trim()
              const doc = quote.ownerDocument
              const details = doc.createElement('details')
              if (open) details.setAttribute('open', '')
              const summary = doc.createElement('summary')
              summary.textContent = title
              const content = doc.createElement('div')
              content.setAttribute('data-type', 'detailsContent')
              first.remove()
              while (quote.firstChild) content.appendChild(quote.firstChild)
              details.append(summary, content)
              quote.replaceWith(details)
            })
          },
        },
      },
    }
  },
})
