/**
 * 笔记内容卡片：在正文中嵌入当前知识库的另一篇笔记（文档 / 数据表 / 画布 / Notebook…）。
 * Markdown 以 ```kiwi-note 围栏 + JSON 持久化笔记 ID 与标题快照。
 */
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import NoteEmbedNodeView from './NoteEmbedNodeView.vue'

const NOTE_LANGUAGE = 'kiwi-note'

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

export interface NoteEmbedPayload {
  noteId: string
  title: string
  kind: string
}

function payloadFrom(value: Record<string, unknown>): NoteEmbedPayload {
  return {
    noteId: String(value?.noteId ?? value?.id ?? ''),
    title: String(value?.title ?? ''),
    kind: String(value?.kind ?? 'doc'),
  }
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiNoteEmbed: {
      insertNoteEmbed: (attrs: NoteEmbedPayload) => ReturnType
    }
  }
}

export const KiwiNoteEmbed = Node.create({
  name: 'kiwiNoteEmbed',
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      noteId: {
        default: '',
        parseHTML: (element) => {
          try {
            return payloadFrom(JSON.parse(element.textContent || '{}')).noteId
          } catch {
            return ''
          }
        },
      },
      title: {
        default: '',
        parseHTML: (element) => {
          try {
            return payloadFrom(JSON.parse(element.textContent || '{}')).title
          } catch {
            return ''
          }
        },
      },
      kind: {
        default: 'doc',
        parseHTML: (element) => {
          try {
            return payloadFrom(JSON.parse(element.textContent || '{}')).kind
          } catch {
            return 'doc'
          }
        },
      },
    }
  },

  parseHTML() {
    return [{ tag: 'pre[data-kiwi-note]' }]
  },

  renderHTML({ node }) {
    return [
      'pre',
      { 'data-kiwi-note': 'true', class: 'kiwi-note-embed-node' },
      JSON.stringify(payloadFrom(node.attrs)),
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(NoteEmbedNodeView)
  },

  addCommands() {
    return {
      insertNoteEmbed:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: payloadFrom(attrs as unknown as Record<string, unknown>),
          }),
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const json = JSON.stringify(payloadFrom(node.attrs))
          const fence = fenceFor(json)
          state.write(`${fence}${NOTE_LANGUAGE}\n`)
          state.write(json)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiNote) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === NOTE_LANGUAGE) {
                return `<pre data-kiwi-note="true">${escapeHtml(
                  token.content.trim(),
                )}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiNote = true
            rules.fence = fence
          },
        },
      },
    }
  },
})
