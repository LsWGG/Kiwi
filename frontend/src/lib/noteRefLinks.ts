/**
 * 问答回答里的笔记引用链接化。
 *
 * Agent 回答经常把笔记写成「LJ (82a90ecf-…-0dd3d33d7e0d)」这种裸 ID，
 * 甚至新写入的笔记不会出现在 citations 里。回答里的 UUID 统一视为
 * 笔记 / Wiki ID 转成站内链接；citations 只用来补标题，不决定是否链接。
 * 代码块与行内代码里的 ID 不会被处理（只扫描 text token）。
 */
import type MarkdownIt from 'markdown-it'

export interface NoteRefTarget {
  title: string
  collection: 'note' | 'wiki'
}

const UUID_SOURCE =
  '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'

/** 括号里只有 ID 的形式：`（ID: 82a90ecf-…）`。 */
const PAREN_ID = new RegExp(`[（(]\\s*(?:ID|id)?\\s*[:：]?\\s*(${UUID_SOURCE})\\s*[)）]`, 'g')
const BARE_ID = new RegExp(`(${UUID_SOURCE})`, 'g')

function makeTextToken(state: any, content: string, source: any) {
  const token = new state.Token('text', '', 0)
  token.content = content
  token.level = source.level
  return token
}

function makeRefTokens(state: any, id: string, target: NoteRefTarget, source: any) {
  const open = new state.Token('link_open', 'a', 1)
  open.attrSet('href', `kiwi://${target.collection}/${id}`)
  open.level = source.level
  const text = new state.Token('text', '', 0)
  text.content = target.title || (target.collection === 'wiki' ? 'Wiki' : '笔记')
  text.level = source.level + 1
  const close = new state.Token('link_close', 'a', -1)
  close.level = source.level
  return [open, text, close]
}

/** 把文本 token 拆成「正文 + 链接 + 正文」。 */
function splitNoteRefs(
  state: any,
  source: any,
  targets: Record<string, NoteRefTarget>,
): any[] {
  const value: string = source.content
  type Piece = { start: number; end: number; id: string; label: string }
  const pieces: Piece[] = []
  const wrapped: [number, number][] = []

  PAREN_ID.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = PAREN_ID.exec(value))) {
    const id = match[1]
    const target = targets[id.toLowerCase()]
    // `标题（ID）` 把标题本身做成链接，ID 与括号一起收进链接里。
    const before = value.slice(0, match.index)
    const knownTitle = (target?.title || '').trim()
    const trimmedBefore = before.replace(/\s+$/, '')
    const known =
      knownTitle && trimmedBefore.endsWith(knownTitle)
        ? { title: knownTitle, start: trimmedBefore.length - knownTitle.length }
        : null
    const quoted = /[「『“"《]([^「」『』“”"《》\n]{1,80})[」』”"》]\s*$/.exec(before)
    const plain = /([^\s：:（()）\[\]【】,，。；;、\n]{1,80})\s*$/.exec(before)
    const found =
      known ??
      (quoted
        ? { title: quoted[1].trim(), start: match.index - quoted[0].length }
        : plain
          ? { title: plain[1].trim(), start: match.index - plain[0].length }
          : null)
    pieces.push({
      start: found?.start ?? match.index,
      end: match.index + match[0].length,
      id,
      label: found?.title || target?.title || `笔记 ${id.slice(0, 8)}`,
    })
    wrapped.push([match.index, match.index + match[0].length])
  }

  BARE_ID.lastIndex = 0
  while ((match = BARE_ID.exec(value))) {
    const start = match.index
    if (wrapped.some(([from, to]) => start >= from && start < to)) continue
    const id = match[1]
    const target = targets[id.toLowerCase()]
    pieces.push({
      start,
      end: start + match[0].length,
      id,
      label: target?.title || `笔记 ${id.slice(0, 8)}`,
    })
  }

  if (!pieces.length) return [source]
  pieces.sort((a, b) => a.start - b.start)

  const out: any[] = []
  let last = 0
  for (const piece of pieces) {
    const start = Math.max(piece.start, last)
    if (start > last) {
      out.push(makeTextToken(state, value.slice(last, start), source))
    }
    const target = targets[piece.id.toLowerCase()]
    const label = piece.label || target?.title || `笔记 ${piece.id.slice(0, 8)}`
    out.push(
      ...makeRefTokens(
        state,
        piece.id,
        { title: label, collection: target?.collection || 'note' },
        source,
      ),
    )
    last = piece.end
  }
  if (last < value.length) out.push(makeTextToken(state, value.slice(last), source))
  return out
}

/**
 * 注册 core 规则。anchor 是已有的 core 规则名（引用角标规则），
 * 保证引用编号先拆分，再把剩余的文本链接化。
 */
export function installNoteRefLinks(
  md: MarkdownIt,
  anchor: string,
  getTargets: () => Record<string, NoteRefTarget> | null | undefined,
) {
  md.core.ruler.after(anchor, 'kiwi_note_ref_links', (state: any) => {
    // null 表示当前视图不启用（普通笔记阅读）；空对象仍要链接化。
    const targets = getTargets()
    if (!targets) return
    for (const block of state.tokens) {
      if (block.type !== 'inline' || !Array.isArray(block.children)) continue
      const out: any[] = []
      let linkDepth = 0
      for (const child of block.children) {
        if (child.type === 'link_open') linkDepth += 1
        else if (child.type === 'link_close') linkDepth = Math.max(0, linkDepth - 1)
        if (child.type !== 'text' || linkDepth > 0 || !child.content) {
          out.push(child)
          continue
        }
        out.push(...splitNoteRefs(state, child, targets))
      }
      block.children = out
    }
  })
}
