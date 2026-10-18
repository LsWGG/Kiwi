/**
 * Python 代码块的运行结果块：
 * - 作为正文中的独立节点持久化（Markdown 中以 ```kiwi-output 围栏保存）；
 * - 展示在对应代码块下方，可复制 / 删除；
 * - 重新运行同一代码块时覆盖旧结果。
 */
import { Node, type Editor } from '@tiptap/core'
import type { Node as PMNode } from '@tiptap/pm/model'
import type { NodeView } from '@tiptap/pm/view'
import type { RunCodeResult } from '@/api/run'

const OUTPUT_LANGUAGE = 'kiwi-output'

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** 输出中若含反引号，围栏自动加长，避免提前闭合。 */
function fenceFor(value: string): string {
  const runs = value.match(/`+/g) ?? []
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0)
  return '`'.repeat(Math.max(3, longest + 1))
}

/** 把后端运行结果整理成正文中持久展示的纯文本。 */
export function formatRunResult(result: RunCodeResult): string {
  const status = result.timed_out
    ? `运行超时（${result.duration_ms} ms）`
    : `exit ${result.exit_code ?? 'unknown'} · ${result.duration_ms} ms`
  const lines = [`[${status}]`]
  if (result.stdout) lines.push(result.stdout.replace(/\n$/, ''))
  if (result.stderr) lines.push(result.stderr.replace(/\n$/, ''))
  if (result.truncated) lines.push('…（输出过长，已截断）')
  if (lines.length === 1) lines.push('（无输出）')
  return lines.join('\n')
}

/**
 * 在代码块之后插入或更新运行结果块。
 * 异步运行结束后文档可能已变化，位置失效时按代码内容回退查找。
 */
export function upsertCodeOutput(
  editor: Editor,
  pos: number | undefined,
  code: string,
  output: string,
): boolean {
  const { state, view } = editor
  const outputType = state.schema.nodes.codeOutput
  if (!outputType) return false

  let target = typeof pos === 'number' ? pos : -1
  let node: PMNode | null = target >= 0 ? state.doc.nodeAt(target) : null
  if (!node || node.type.name !== 'codeBlock' || node.textContent !== code) {
    target = -1
    state.doc.descendants((candidate, candidatePos) => {
      if (candidate.type.name !== 'codeBlock' || candidate.textContent !== code) return true
      target = candidatePos
      return false
    })
    node = target >= 0 ? state.doc.nodeAt(target) : null
  }
  if (!node || node.type.name !== 'codeBlock') return false

  const after = target + node.nodeSize
  const existing = state.doc.nodeAt(after)
  const tr = state.tr
  if (existing && existing.type.name === 'codeOutput') {
    tr.setNodeMarkup(after, undefined, { output })
  } else {
    tr.insert(after, outputType.create({ output }))
  }
  view.dispatch(tr)
  return true
}

class CodeOutputView implements NodeView {
  dom: HTMLElement
  private node: PMNode
  private editor: Editor
  private getPos: () => number | undefined
  private codeEl: HTMLElement
  private copyButton: HTMLButtonElement

  constructor(node: PMNode, editor: Editor, getPos: () => number | undefined) {
    this.node = node
    this.editor = editor
    this.getPos = getPos

    this.dom = document.createElement('div')
    this.dom.className = 'code-output-node'
    this.dom.contentEditable = 'false'

    const bar = document.createElement('div')
    bar.className = 'code-output-bar'

    const label = document.createElement('span')
    label.className = 'code-output-label'
    label.textContent = '运行结果'

    const actions = document.createElement('span')
    actions.className = 'code-output-actions'

    this.copyButton = document.createElement('button')
    this.copyButton.type = 'button'
    this.copyButton.className = 'code-output-action'
    this.copyButton.textContent = '复制'
    this.copyButton.title = '复制运行结果'
    this.copyButton.addEventListener('mousedown', (e) => e.preventDefault())
    this.copyButton.addEventListener('click', (e) => {
      e.preventDefault()
      e.stopPropagation()
      void this.copy()
    })

    const remove = document.createElement('button')
    remove.type = 'button'
    remove.className = 'code-output-action is-danger'
    remove.textContent = '删除'
    remove.title = '删除这段运行结果'
    remove.addEventListener('mousedown', (e) => e.preventDefault())
    remove.addEventListener('click', (e) => {
      e.preventDefault()
      e.stopPropagation()
      this.remove()
    })

    actions.append(this.copyButton, remove)
    bar.append(label, actions)

    const pre = document.createElement('pre')
    this.codeEl = document.createElement('code')
    pre.appendChild(this.codeEl)

    this.dom.append(bar, pre)
    this.render()
  }

  private render() {
    this.codeEl.textContent = String(this.node.attrs.output ?? '')
  }

  private async copy() {
    try {
      await navigator.clipboard.writeText(String(this.node.attrs.output ?? ''))
      this.copyButton.textContent = '已复制'
    } catch {
      this.copyButton.textContent = '复制失败'
    }
    window.setTimeout(() => {
      this.copyButton.textContent = '复制'
    }, 1200)
  }

  private remove() {
    const pos = this.getPos()
    if (typeof pos !== 'number') return
    const { state, view } = this.editor
    const node = state.doc.nodeAt(pos)
    if (!node || node.type.name !== 'codeOutput') return
    view.dispatch(state.tr.delete(pos, pos + node.nodeSize))
  }

  update(node: PMNode): boolean {
    if (node.type !== this.node.type) return false
    this.node = node
    this.render()
    return true
  }

  stopEvent(event: Event): boolean {
    return !!(event.target as HTMLElement | null)?.closest?.('.code-output-bar')
  }

  ignoreMutation(): boolean {
    return true
  }
}

export const CodeOutput = Node.create({
  name: 'codeOutput',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: false,

  addAttributes() {
    return {
      output: { default: '' },
    }
  },

  parseHTML() {
    return [
      {
        tag: 'pre[data-code-output]',
        getAttrs: (element) => ({
          output: ((element as HTMLElement).textContent ?? '').replace(/\n$/, ''),
        }),
      },
    ]
  },

  renderHTML({ node }) {
    return [
      'pre',
      { 'data-code-output': 'true', class: 'code-output-node' },
      String(node.attrs.output ?? ''),
    ]
  },

  addNodeView() {
    return ({ node, editor, getPos }) =>
      new CodeOutputView(node, editor, getPos as () => number | undefined)
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const output = String(node.attrs.output ?? '')
          const fence = fenceFor(output)
          state.write(`${fence}${OUTPUT_LANGUAGE}\n`)
          state.text(output, false)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiOutput) return
            const originalFence = rules.fence
            const fence = (
              tokens: any[],
              idx: number,
              options: any,
              env: any,
              self: any,
            ) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === OUTPUT_LANGUAGE) {
                return `<pre data-code-output="true">${escapeHtml(token.content)}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiOutput = true
            rules.fence = fence
          },
        },
      },
    }
  },
})
