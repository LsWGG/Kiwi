/**
 * 画布块：拖拽式 jvs-draw 白板。
 * Markdown 以 ```kiwi-draw 围栏 + JSON 持久化完整文档（元素、背景、图片）。
 */
import { Node } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import DrawNodeView from './DrawNodeView.vue'
import {
  emptyDrawDoc,
  normalizeDrawDoc,
  type JvsDrawDoc,
} from '@/components/draw/types'

export interface KiwiDrawOptions {
  /** 插入图片时上传到 Kiwi 附件库，返回可访问 URL。 */
  upload: ((file: File) => Promise<{ url: string } | string>) | null
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function fenceFor(value: string): string {
  const runs = value.match(/`+/g) ?? []
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0)
  return '`'.repeat(Math.max(3, longest + 1))
}

function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.isContentEditable ||
    !!target.closest('[contenteditable="true"]')
  )
}

function insideDraw(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && !!target.closest('.kiwi-draw-editor')
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiDraw: {
      insertDraw: (attrs?: { doc?: JvsDrawDoc }) => ReturnType
    }
  }
}

export const KiwiDraw = Node.create<KiwiDrawOptions>({
  name: 'kiwiDraw',
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addOptions() {
    return { upload: null }
  },

  addAttributes() {
    return {
      doc: {
        default: null,
        parseHTML: (element) => {
          try {
            return normalizeDrawDoc(JSON.parse(element.textContent || 'null'))
          } catch {
            return null
          }
        },
        renderHTML: () => ({}),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'pre[data-kiwi-draw]' }]
  },

  renderHTML({ node }) {
    const doc = normalizeDrawDoc(node.attrs.doc) ?? emptyDrawDoc()
    return [
      'pre',
      { 'data-kiwi-draw': 'true', class: 'kiwi-draw-node' },
      JSON.stringify(doc),
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(DrawNodeView)
  },

  addCommands() {
    return {
      insertDraw:
        (attrs = {}) =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: { doc: attrs.doc ?? emptyDrawDoc() },
          }),
    }
  },

  addProseMirrorPlugins() {
    const guard = new PluginKey('kiwiDrawGuard')
    return [
      new Plugin({
        key: guard,
        props: {
          // 画布聚焦时，Backspace / Delete / Enter 交给 jvs-draw；
          // 返回 true 让 ProseMirror 不删除当前画布节点。
          handleKeyDown(_view, event) {
            if (!insideDraw(event.target) || isTextEntry(event.target)) return false
            return (
              event.key === 'Backspace' ||
              event.key === 'Delete' ||
              event.key === 'Enter'
            )
          },
          // 粘贴 / 拖入画布由 jvs-draw 自己处理，避免 ProseMirror 替换掉画布节点。
          handlePaste(_view, event) {
            return insideDraw(event.target) && !isTextEntry(event.target)
          },
          handleDrop(_view, event) {
            return insideDraw(event.target) && !isTextEntry(event.target)
          },
        },
      }),
    ]
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const doc = normalizeDrawDoc(node.attrs.doc) ?? emptyDrawDoc()
          const payload = JSON.stringify(doc)
          const fence = fenceFor(payload)
          state.write(`${fence}kiwi-draw\n`)
          state.write(payload)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiDraw) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === 'kiwi-draw') {
                return `<pre data-kiwi-draw="true">${escapeHtml(
                  token.content.trim(),
                )}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiDraw = true
            rules.fence = fence
          },
        },
      },
    }
  },
})
