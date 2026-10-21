/**
 * @ 提及：输入 @ 选择当前知识库的笔记或 Wiki 页面，插入可点击的 mention 节点。
 * 持久化为 `[@标题](kiwi://note/<id>)` / `[@标题](kiwi://wiki/<id>)`，解析时还原。
 */
import Mention from '@tiptap/extension-mention'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import { iconSVG } from '@/components/ui/icons'
import MentionView from '../MentionView.vue'
import { createSuggestionPopup } from './suggestionPopup'
import {
  mentionText,
  normalizeMentionDisplay,
  type MentionDisplay,
} from './mentionTypes'

export type { MentionDisplay } from './mentionTypes'
export { normalizeMentionDisplay } from './mentionTypes'

export type MentionTarget = 'note' | 'wiki'

export interface MentionNote {
  id: string
  title: string
  kind?: 'doc' | 'database' | 'link' | 'import' | 'canvas' | 'notebook' | 'sheet'
}

export interface MentionWikiPage {
  id: string
  title: string
  slug: string
  page_type?: string
}

export interface MentionCandidate {
  target: MentionTarget
  id: string
  title: string
  /** 笔记类型（doc/database/…）或 Wiki 页面类型（entity/concept/…） */
  kind?: string
  subtitle?: string
}

/** 旧数据可能把 id 写进了 label；优先用当前知识库里的标题替换。 */
function resolveLabel(
  rawLabel: string,
  target: MentionTarget,
  id: string,
  getNotes: () => MentionNote[],
  getWikiPages?: () => MentionWikiPage[],
): string {
  const label = rawLabel.replace(/^@/, '').trim()
  const isId = /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(label) || label === id
  if (!isId && label) return label
  const title =
    target === 'wiki'
      ? getWikiPages?.().find((page) => page.id === id)?.title?.trim()
      : getNotes().find((note) => note.id === id)?.title?.trim()
  return title || label || id
}

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (ch) => {
    const map: Record<string, string> = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }
    return map[ch]
  })

const KIND_ICONS: Record<string, string> = {
  doc: 'fileText',
  database: 'database',
  link: 'link2',
  import: 'fileImport',
  canvas: 'pen',
  notebook: 'notebook',
}

const PAGE_TYPE_LABEL: Record<string, string> = {
  entity: '实体',
  concept: '概念',
  summary: '摘要',
  synthesis: '综述',
}

function candidateIcon(candidate: MentionCandidate) {
  const name =
    candidate.target === 'wiki'
      ? 'wiki'
      : KIND_ICONS[candidate.kind || 'doc'] || 'fileText'
  return `<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${iconSVG(name)}</svg>`
}

export function createMentionExtension(
  getNotes: () => MentionNote[],
  getCurrentNoteId?: () => string | null,
  getWikiPages?: () => MentionWikiPage[],
) {
  const KiwiMention = Mention.extend({
    addAttributes() {
      return {
        ...this.parent?.(),
        /** note：工作区笔记；wiki：编译知识页 */
        target: {
          default: 'note',
          parseHTML: (element) =>
            element.getAttribute('data-target') === 'wiki' ? 'wiki' : 'note',
          renderHTML: (attributes) =>
            attributes.target === 'wiki' ? { 'data-target': 'wiki' } : {},
        },
        /** 提及 / 标题链接 / 内容卡片 */
        display: {
          default: 'mention',
          parseHTML: (element) =>
            normalizeMentionDisplay(element.getAttribute('data-display')),
          renderHTML: (attributes) => ({
            'data-display': normalizeMentionDisplay(attributes.display),
          }),
        },
        /** 嵌入窗口的自定义高度（px）；null 表示自动高度 */
        height: {
          default: null,
          parseHTML: (element) => {
            const value = Number(element.getAttribute('data-height'))
            return Number.isFinite(value) && value > 0 ? value : null
          },
          renderHTML: (attributes) => {
            const value = Number(attributes.height)
            return Number.isFinite(value) && value > 0
              ? { 'data-height': String(value) }
              : {}
          },
        },
      }
    },
    addNodeView() {
      return VueNodeViewRenderer(MentionView)
    },
    addStorage() {
      return {
        markdown: {
          serialize(state: any, node: any) {
            const id = String(node.attrs.id ?? '')
            const target: MentionTarget =
              node.attrs.target === 'wiki' ? 'wiki' : 'note'
            const rawLabel = String(node.attrs.label ?? id)
            const label = rawLabel.replace(/[[\]]/g, '')
            const display = normalizeMentionDisplay(node.attrs.display)
            const params = new URLSearchParams()
            if (display !== 'mention') params.set('display', display)
            const height = Number(node.attrs.height)
            if (display === 'embed' && Number.isFinite(height) && height > 0) {
              params.set('height', String(Math.round(height)))
            }
            const query = params.toString() ? `?${params.toString()}` : ''
            state.write(`[@${label}](kiwi://${target}/${id}${query})`)
          },
          parse: {
            updateDOM(element: HTMLElement) {
              element
                .querySelectorAll('a[href^="kiwi://note/"], a[href^="kiwi://wiki/"]')
                .forEach((anchor) => {
                  const href = anchor.getAttribute('href') || ''
                  const isWiki = href.startsWith('kiwi://wiki/')
                  const target: MentionTarget = isWiki ? 'wiki' : 'note'
                  const prefix = isWiki ? 'kiwi://wiki/' : 'kiwi://note/'
                  const raw = href.slice(prefix.length)
                  const [idPart, query = ''] = raw.split('?')
                  const id = idPart
                  if (!id) return
                  const params = new URLSearchParams(query)
                  const display = normalizeMentionDisplay(params.get('display'))
                  const height = Number(params.get('height'))
                  const label = resolveLabel(
                    anchor.textContent || '',
                    target,
                    id,
                    getNotes,
                    getWikiPages,
                  )
                  const span = anchor.ownerDocument.createElement('span')
                  span.setAttribute('data-type', 'mention')
                  span.setAttribute('data-target', target)
                  span.setAttribute('data-id', id)
                  span.setAttribute('data-label', label)
                  span.setAttribute('data-display', display)
                  if (Number.isFinite(height) && height > 0) {
                    span.setAttribute('data-height', String(Math.round(height)))
                  }
                  span.textContent = mentionText(display, label)
                  anchor.replaceWith(span)
                })
            },
          },
        },
      }
    },
  })

  return KiwiMention.configure({
    HTMLAttributes: { class: 'kiwi-mention' },
    renderText: ({ node }) => {
      const display = normalizeMentionDisplay(node.attrs.display)
      const label = String(node.attrs.label ?? node.attrs.id ?? '')
      return mentionText(display, label)
    },
    renderHTML: ({ node, options }) => {
      const display = normalizeMentionDisplay(node.attrs.display)
      const label = String(node.attrs.label ?? node.attrs.id ?? '')
      const height = Number(node.attrs.height)
      return [
        'span',
        {
          ...options.HTMLAttributes,
          class: `${options.HTMLAttributes?.class ?? ''} is-${display}`.trim(),
          'data-type': 'mention',
          'data-target': node.attrs.target === 'wiki' ? 'wiki' : 'note',
          'data-id': String(node.attrs.id ?? ''),
          'data-label': label,
          'data-display': display,
          ...(Number.isFinite(height) && height > 0
            ? { 'data-height': String(Math.round(height)) }
            : {}),
        },
        mentionText(display, label),
      ]
    },
    suggestion: {
      char: '@',
      allowSpaces: false,
      // 允许在中文后直接输入 @（默认只允许空格/行首）
      allowedPrefixes: null,
      /** 默认 command 会把候选对象原样作为节点属性，导致 label 丢失、正文显示 id。 */
      command: ({ editor, range, props }: any) => {
        editor
          .chain()
          .focus()
          .insertContentAt(range, [
            {
              type: 'mention',
              attrs: {
                target: props.target === 'wiki' ? 'wiki' : 'note',
                id: props.id,
                label: props.title || '无标题',
                display: 'mention',
              },
            },
            { type: 'text', text: ' ' },
          ])
          .run()
      },
      items: ({ query }: { query: string }) => {
        const keyword = String(query || '').trim().toLowerCase()
        const match = (text: string) => !keyword || text.toLowerCase().includes(keyword)
        const current = getCurrentNoteId?.() ?? null
        const notes: MentionCandidate[] = getNotes()
          .filter((note) => note.id !== current && match(note.title || '无标题'))
          .map((note) => ({
            target: 'note',
            id: note.id,
            title: note.title || '无标题',
            kind: note.kind,
            subtitle: '笔记',
          }))
        const pages: MentionCandidate[] = (getWikiPages?.() ?? [])
          .filter((page) => match(page.title) || match(page.slug))
          .map((page) => ({
            target: 'wiki',
            id: page.id,
            title: page.title,
            kind: page.page_type || 'concept',
            subtitle: PAGE_TYPE_LABEL[page.page_type || ''] || 'Wiki',
          }))
        // 两类都保留曝光：有 Wiki 页时笔记最多 7 条，剩余名额给 Wiki。
        const noteLimit = pages.length ? 7 : 10
        const pickedNotes = notes.slice(0, noteLimit)
        const pickedPages = pages.slice(0, Math.max(0, 10 - pickedNotes.length))
        return [...pickedNotes, ...pickedPages]
      },
      render: createSuggestionPopup<MentionCandidate>({
        menuClass: 'mention-suggest-menu',
        boxClass: 'mention-suggest-box',
        render: (items, active) => {
          let seenWiki = false
          return (
            `<div class="kiwi-suggest-head">提及笔记或 Wiki</div>` +
            items
              .map((item, i) => {
                let group = ''
                if (item.target === 'wiki' && !seenWiki) {
                  seenWiki = true
                  group = `<div class="kiwi-suggest-group">Wiki 页面</div>`
                } else if (i === 0) {
                  group = `<div class="kiwi-suggest-group">笔记</div>`
                }
                return (
                  group +
                  `<button type="button" data-i="${i}" class="kiwi-suggest-item${i === active ? ' is-active' : ''}">` +
                  `<span class="kiwi-suggest-icon" data-kind="${item.target === 'wiki' ? 'wiki' : item.kind || 'doc'}">${candidateIcon(item)}</span>` +
                  `<span class="truncate">${escapeHtml(item.title)}</span>` +
                  `<span class="kiwi-suggest-sub">${escapeHtml(item.subtitle || '')}</span>` +
                  `</button>`
                )
              })
              .join('')
          )
        },
      }),
    },
  })
}
