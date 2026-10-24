/** Wiki 正文渲染：Markdown-it 配置、[[双链]] 解析、标题锚点提取。 */
import MarkdownIt from 'markdown-it'
import taskLists from 'markdown-it-task-lists'

export interface WikiLinkTarget {
  id: string
  slug: string
  title: string
}

export interface HeadingItem {
  level: number
  text: string
  id: string
}

export function normalizeWikiKey(value: string): string {
  return value.trim().toLowerCase().replace(/_/g, '-')
}

export function headingId(index: number): string {
  return `wiki-sec-${index + 1}`
}

function cleanInline(value: string): string {
  return value
    .replace(/\[\[([^\[\]]+?)\]\]/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[`*_~]/g, '')
    .trim()
}

/**
 * 编译产物与导入笔记常以 `# 标题` 开头，而页面头部/笔记头部已经展示标题。
 * 若正文首个一级标题与外部标题一致，渲染时去掉它，避免同一标题出现两次。
 */
export function stripLeadingTitleHeading(content: string, title: string): string {
  const body = content || ''
  const wanted = cleanInline(title || '').replace(/\s+/g, ' ')
  if (!wanted) return body
  const match = /^\s*#\s+(.+?)\s*(?:\r?\n|$)/.exec(body)
  if (!match) return body
  const heading = cleanInline(match[1]).replace(/\s+/g, ' ')
  if (heading !== wanted) return body
  return body.slice(match[0].length).replace(/^\s+/, '')
}

export function extractHeadings(content: string): HeadingItem[] {
  const items: HeadingItem[] = []
  let inFence = false
  let index = 0
  for (const raw of (content || '').split(/\r?\n/)) {
    if (/^\s*```/.test(raw)) {
      inFence = !inFence
      continue
    }
    if (inFence) continue
    const match = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(raw)
    if (!match) continue
    items.push({
      level: match[1].length,
      text: cleanInline(match[2]) || `第 ${index + 1} 节`,
      id: headingId(index),
    })
    index += 1
  }
  return items
}

/** 创建 Wiki 专用 markdown-it 实例。resolver 通过 render env 传入，无需重建实例。 */
export function createWikiMarkdown(): MarkdownIt {
  const md = new MarkdownIt({
    html: false,
    linkify: true,
    breaks: false,
    typographer: false,
  }).use(taskLists, { enabled: true, label: true })

  // [[目标]] → 内部链接；未命中时渲染为不可点击的“死链”样式，便于发现缺口。
  md.inline.ruler.before('link', 'wiki_link', (state, silent) => {
    const start = state.pos
    if (state.src.charCodeAt(start) !== 0x5b || state.src.charCodeAt(start + 1) !== 0x5b) {
      return false
    }
    const end = state.src.indexOf(']]', start + 2)
    if (end < 0) return false
    const raw = state.src.slice(start + 2, end).trim()
    if (!raw || raw.includes('[[') || raw.includes(']')) return false

    if (!silent) {
      const resolver = (state.env as { resolveWikiLink?: (t: string) => WikiLinkTarget | null })
        .resolveWikiLink
      const target = resolver?.(raw) ?? null
      const open = state.push('link_open', 'a', 1)
      if (target) {
        open.attrSet('href', `/wiki/${target.id}`)
        open.attrSet('class', 'wiki-link')
        open.attrSet('data-wiki-id', target.id)
        open.attrSet('title', `Wiki：${target.title}`)
      } else {
        open.attrSet('href', '#')
        open.attrSet('class', 'wiki-link wiki-link-missing')
        open.attrSet('data-wiki-missing', raw)
        open.attrSet('title', `页面不存在：${raw}`)
      }
      const text = state.push('text', '', 0)
      text.content = target?.title ?? raw
      state.push('link_close', 'a', -1)
    }
    state.pos = end + 2
    return true
  })

  md.core.ruler.push('wiki_heading_ids', (state) => {
    let index = 0
    for (const token of state.tokens) {
      if (token.type !== 'heading_open') continue
      token.attrSet('id', headingId(index))
      token.attrSet('class', 'wiki-heading')
      index += 1
    }
  })

  const defaultLinkOpen =
    md.renderer.rules.link_open ??
    ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))

  md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
    const href = tokens[idx].attrGet('href') ?? ''
    // @ 提及在 Markdown 里是 kiwi:// 自定义协议：阅读态还原成站内路由，
    // 并复用 .wiki-link 样式，避免浏览器把自定义协议当成外部地址。
    const mention = /^kiwi:\/\/(wiki|note)\/([0-9a-fA-F-]{36})(?:[?#][^)]*)?$/.exec(href)
    if (mention) {
      const kind = mention[1]
      const id = mention[2]
      if (kind === 'wiki') {
        tokens[idx].attrSet('href', `/wiki/${id}`)
        tokens[idx].attrSet('data-wiki-id', id)
        tokens[idx].attrSet('class', 'wiki-link')
      } else {
        tokens[idx].attrSet('href', `/notes/${id}`)
        tokens[idx].attrSet('data-note-id', id)
        tokens[idx].attrSet('class', 'wiki-link wiki-link-note')
      }
      return defaultLinkOpen(tokens, idx, options, env, self)
    }
    if (/^https?:\/\//i.test(href)) {
      tokens[idx].attrSet('target', '_blank')
      tokens[idx].attrSet('rel', 'noopener noreferrer')
    }
    return defaultLinkOpen(tokens, idx, options, env, self)
  }

  md.renderer.rules.table_open = () => '<div class="overflow-x-auto"><table>\n'
  md.renderer.rules.table_close = () => '</table></div>\n'

  return md
}
