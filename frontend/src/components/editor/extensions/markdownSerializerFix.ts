/**
 * 修复 tiptap-markdown 0.8.10 的 Markdown 序列化缺陷。
 *
 * 问题：`MarkdownSerializerState.markString()` 在「加粗 / 斜体」开始处记录
 * `start = out.length` 时，上一段落的块级收尾（`flushClose`）还没有执行。
 * 顶层段落之间只会补 `\n\n`，`trimInline` 的 normalize 会跳过空白，因此看不出来；
 * 但引用块 / 提示块 / 分栏使用 `> ` 前缀，待补的分隔符是 `\n>\n`，
 * normalize 停在 `>` 上，`trimInline` 便把加粗标记推到前缀上，输出成
 * `> ****文本**`，同时吞掉段落空行。普通引用块、列表等带前缀的块都会中招。
 *
 * 修复：记录起始位置前先执行一次 `write()`，把待收尾的块分隔符与前缀补上，
 * 让 `start` 落在真正的标记符上。该 `write()` 与紧跟其后的标记写入所用的
 * flush 完全等价，不会多输出内容。
 *
 * `trimInline` / `scanDelims` 复制自 tiptap-markdown（MIT License，
 * https://github.com/aguingand/tiptap-markdown）。
 */
import { Extension } from '@tiptap/core'
import { MarkdownSerializerState } from 'prosemirror-markdown'
import markdownit from 'markdown-it'

const md = markdownit()

function scanDelims(text: string, pos: number) {
  const state = new (md.inline.State as any)(text, null, null, [])
  return state.scanDelims(pos, true)
}

function shiftDelim(text: string, delim: string, start: number, offset: number) {
  let res = text.substring(0, start) + text.substring(start + delim.length)
  res = res.substring(0, start + offset) + delim + res.substring(start + offset)
  return res
}

function trimStart(text: string, delim: string, from: number, to: number) {
  let pos = from
  let res = text
  while (pos < to) {
    if (scanDelims(res, pos).can_open) break
    res = shiftDelim(res, delim, pos, 1)
    pos++
  }
  return { text: res, from: pos, to }
}

function trimEnd(text: string, delim: string, from: number, to: number) {
  let pos = to
  let res = text
  while (pos > from) {
    if (scanDelims(res, pos).can_close) break
    res = shiftDelim(res, delim, pos, -1)
    pos--
  }
  return { text: res, from, to: pos }
}

function trimInline(text: string, delim: string, from: number, to: number) {
  let state = { text, from, to }
  state = trimStart(state.text, delim, state.from, state.to)
  state = trimEnd(state.text, delim, state.from, state.to)
  if (state.to - state.from < delim.length + 1) {
    state.text =
      state.text.substring(0, state.from) + state.text.substring(state.to + delim.length)
  }
  return state.text
}

interface InlineInfo {
  start: number
  end?: number
  delimiter: string
}

class FixedMarkdownSerializerState extends MarkdownSerializerState {
  // prosemirror-markdown 把 out / marks 标记为 internal，未写入类型声明。
  declare out: string
  declare marks: Record<string, { open: string; close: string; expelEnclosingWhitespace?: boolean }>

  inlines: InlineInfo[] = []

  render(node: any, parent: any, index: number) {
    super.render(node, parent, index)
    const top = this.inlines[this.inlines.length - 1]
    if (top && top.end !== undefined) {
      const { delimiter, start, end } = this.normalizeInline(top)
      this.out = trimInline(this.out, delimiter, start, end)
      this.inlines.pop()
    }
  }

  markString(mark: any, open: boolean, parent: any, index: number) {
    const info = this.marks[mark.type.name]
    if (info.expelEnclosingWhitespace) {
      if (open) {
        // 先补齐上一段落的收尾与前缀，再记录标记的真实起点。
        this.write()
        this.inlines.push({ start: this.out.length, delimiter: info.open })
      } else {
        const top = this.inlines.pop()
        if (top) this.inlines.push({ ...top, end: this.out.length })
      }
    }
    return super.markString(mark, open, parent, index)
  }

  normalizeInline(inline: InlineInfo): Required<InlineInfo> {
    const full = inline as Required<InlineInfo>
    let start = full.start
    while (this.out.charAt(start).match(/\s/)) start++
    return { ...full, start }
  }
}

function serializeWithFix(editor: any, content: any) {
  const stored = editor.storage.markdown
  const serializer = stored.serializer
  const state = new (FixedMarkdownSerializerState as any)(serializer.nodes, serializer.marks, {
    hardBreakNodeName: 'hardBreak',
    // 上游 serialize() 没把 Markdown.configure 的 tightLists 传给状态，
    // 导致没有 tight 属性的 taskList 总是被序列化成松散列表。
    tightLists: Boolean(stored.options?.tightLists),
  })
  state.renderContent(content)
  return state.out
}

export const MarkdownSerializerFix = Extension.create({
  name: 'markdownSerializerFix',

  // 低于 tiptap-markdown 的 50，确保其 onBeforeCreate 先创建 storage.markdown。
  priority: 40,

  onBeforeCreate() {
    const stored = (this.editor.storage as any).markdown
    if (!stored?.serializer) return
    stored.getMarkdown = () => serializeWithFix(this.editor, this.editor.state.doc)
    stored.serializer.serialize = (content: any) => serializeWithFix(this.editor, content)
  },
})
