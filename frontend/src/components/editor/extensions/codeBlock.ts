/**
 * 代码块增强：
 * - 语法高亮（CodeBlockLowlight）
 * - 行号（由编辑器 CSS 根据本地偏好控制）
 * - 悬停工具：复制 / 运行 Python / 在正文内渲染 HTML、JS 预览
 * 预览使用沙箱 iframe，直接在笔记正文中显示；preview 属性不会写入 Markdown。
 */
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import type { Editor } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { Node as PMNode } from '@tiptap/pm/model'
import {
  Decoration,
  DecorationSet,
  type NodeView,
  type ViewMutationRecord,
} from '@tiptap/pm/view'
import type { createLowlight } from 'lowlight'
import { runPython } from '@/api/run'
import { formatRunResult, upsertCodeOutput } from './codeOutput'
import { buildPreviewDocument } from './preview'

/** 可运行 / 可预览的语言。 */
const RUNNABLE: Record<string, 'python' | 'html' | 'js'> = {
  python: 'python',
  python3: 'python',
  py: 'python',
  html: 'html',
  javascript: 'js',
  js: 'js',
}

const lineNumberKey = new PluginKey('kiwiCodeLineNumbers')

/** 每行开头插入行号组件，显示与否由编辑器根节点的 code-linenos 类控制。 */
function buildLineNumbers(doc: PMNode): DecorationSet {
  const decorations: Decoration[] = []
  doc.descendants((node, pos) => {
    if (node.type.name !== 'codeBlock') return true
    const code = node.textContent
    let line = 1
    let offset = 0
    for (;;) {
      const lineNumber = line
      decorations.push(
        Decoration.widget(
          pos + 1 + offset,
          () => {
            const span = document.createElement('span')
            span.className = 'code-line-number'
            span.contentEditable = 'false'
            span.textContent = String(lineNumber)
            return span
          },
          { side: -1 },
        ),
      )
      const nextBreak = code.indexOf('\n', offset)
      if (nextBreak < 0) break
      offset = nextBreak + 1
      line += 1
    }
    return false
  })
  return DecorationSet.create(doc, decorations)
}

function lineNumberPlugin(): Plugin {
  return new Plugin({
    key: lineNumberKey,
    state: {
      init: (_config, state) => buildLineNumbers(state.doc),
      apply: (tr, old) => (tr.docChanged ? buildLineNumbers(tr.doc) : old),
    },
    props: {
      decorations(state) {
        return lineNumberKey.getState(state) as DecorationSet
      },
    },
  })
}

function makeToolButton(className: string, label: string): HTMLButtonElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = className
  button.textContent = label
  button.addEventListener('mousedown', (e) => e.preventDefault())
  return button
}

class CodeBlockView implements NodeView {
  dom: HTMLElement
  contentDOM: HTMLElement

  private node: PMNode
  private editor: Editor
  private getPos: () => number | undefined
  private previewWrap: HTMLElement
  private previewFrame: HTMLIFrameElement
  private previewLabel: HTMLElement
  private runButton: HTMLButtonElement
  private copyButton: HTMLButtonElement
  private renderTimer: number | undefined
  private renderedCode = ''
  private renderedLang = ''
  private rendered = false
  private running = false

  constructor(node: PMNode, editor: Editor, getPos: () => number | undefined) {
    this.node = node
    this.editor = editor
    this.getPos = getPos

    this.dom = document.createElement('div')
    this.dom.className = 'code-block-node'

    const pre = document.createElement('pre')
    this.contentDOM = document.createElement('code')
    pre.appendChild(this.contentDOM)
    this.dom.appendChild(pre)

    const tools = document.createElement('span')
    tools.className = 'code-tools'
    tools.contentEditable = 'false'
    this.runButton = makeToolButton('code-run-btn', '运行')
    this.runButton.addEventListener('click', (e) => {
      e.preventDefault()
      e.stopPropagation()
      this.onRun()
    })
    this.copyButton = makeToolButton('code-copy-btn', '复制')
    this.copyButton.title = '复制代码'
    this.copyButton.addEventListener('click', async (e) => {
      e.preventDefault()
      e.stopPropagation()
      try {
        await navigator.clipboard.writeText(this.node.textContent)
        this.copyButton.textContent = '已复制'
        window.setTimeout(() => {
          this.copyButton.textContent = '复制'
        }, 1200)
      } catch {
        this.copyButton.textContent = '复制失败'
        window.setTimeout(() => {
          this.copyButton.textContent = '复制'
        }, 1200)
      }
    })
    tools.append(this.runButton, this.copyButton)
    this.dom.appendChild(tools)

    this.previewWrap = document.createElement('div')
    this.previewWrap.className = 'code-block-preview'
    this.previewWrap.contentEditable = 'false'

    const bar = document.createElement('div')
    bar.className = 'code-preview-bar'
    this.previewLabel = document.createElement('span')
    this.previewLabel.className = 'code-preview-label'
    const actions = document.createElement('span')
    actions.className = 'code-preview-actions'
    const reload = makeToolButton('code-preview-action', '刷新')
    reload.title = '重新渲染预览'
    reload.addEventListener('click', (e) => {
      e.preventDefault()
      e.stopPropagation()
      this.renderPreview(true)
    })
    const fullscreen = makeToolButton('code-preview-action', '全屏')
    fullscreen.title = '在弹层中预览'
    fullscreen.addEventListener('click', (e) => {
      e.preventDefault()
      e.stopPropagation()
      const kind = this.kind
      if (!kind || kind === 'python') return
      window.dispatchEvent(
        new CustomEvent('kiwi-run-code', {
          detail: { language: kind, source: this.source, code: this.node.textContent },
        }),
      )
    })
    const collapse = makeToolButton('code-preview-action', '收起')
    collapse.title = '收起预览'
    collapse.addEventListener('click', (e) => {
      e.preventDefault()
      e.stopPropagation()
      this.setPreview(false)
    })
    actions.append(reload, fullscreen, collapse)
    bar.append(this.previewLabel, actions)

    this.previewFrame = document.createElement('iframe')
    this.previewFrame.className = 'code-preview-frame'
    this.previewFrame.setAttribute('sandbox', 'allow-scripts allow-forms allow-modals allow-popups')
    this.previewFrame.setAttribute('title', '代码预览')
    this.previewWrap.append(bar, this.previewFrame)
    this.dom.appendChild(this.previewWrap)
    window.addEventListener('message', this.onPreviewMessage)

    this.sync()
  }

  /** 预览页通过 postMessage 上报正文高度，iframe 随内容自适应。 */
  private onPreviewMessage = (event: MessageEvent) => {
    if (event.source !== this.previewFrame.contentWindow) return
    const data = event.data as { type?: string; height?: number } | null
    if (!data || data.type !== 'kiwi-code-preview-height') return
    const height = Number(data.height)
    if (!Number.isFinite(height) || height <= 0) return
    this.previewFrame.style.height = `${Math.min(900, Math.max(60, Math.ceil(height)))}px`
  }

  private get source(): string {
    return String(this.node.attrs.language || '').toLowerCase()
  }

  private get kind(): 'python' | 'html' | 'js' | null {
    return RUNNABLE[this.source] ?? null
  }

  private get previewable(): boolean {
    const kind = this.kind
    return kind === 'html' || kind === 'js'
  }

  private get previewOn(): boolean {
    return this.previewable && this.node.attrs.preview !== false
  }

  private sync() {
    const lang = this.source
    this.contentDOM.className = lang ? `language-${lang}` : ''
    this.dom.dataset.kind = this.kind ?? ''

    const kind = this.kind
    if (!kind) {
      this.runButton.style.display = 'none'
    } else {
      this.runButton.style.display = ''
      this.runButton.textContent =
        kind === 'python'
          ? this.running
            ? '运行中…'
            : '运行'
          : this.previewOn
            ? '收起预览'
            : '预览'
      this.runButton.disabled = kind === 'python' && this.running
      this.runButton.title =
        kind === 'python'
          ? '运行 Python，结果显示在代码块下方'
          : this.previewOn
            ? '收起正文预览'
            : '在正文中渲染预览'
    }

    this.dom.classList.toggle('is-previewing', this.previewOn)
    if (!this.previewOn) {
      this.previewWrap.hidden = true
      return
    }
    this.previewWrap.hidden = false
    this.previewLabel.textContent = kind === 'js' ? 'JavaScript 预览' : 'HTML 预览'
    const code = this.node.textContent
    if (!this.rendered || code !== this.renderedCode || lang !== this.renderedLang) {
      this.renderPreview(!this.rendered)
    }
  }

  private renderPreview(immediate = false) {
    window.clearTimeout(this.renderTimer)
    const run = () => {
      const kind = this.kind
      if (kind !== 'html' && kind !== 'js') return
      this.previewFrame.srcdoc = buildPreviewDocument(kind, this.node.textContent)
      this.renderedCode = this.node.textContent
      this.renderedLang = this.source
      this.rendered = true
    }
    if (immediate) run()
    else this.renderTimer = window.setTimeout(run, 350)
  }

  private setPreview(value: boolean) {
    const pos = this.getPos()
    if (typeof pos !== 'number') return
    const view = this.editor.view
    view.dispatch(
      view.state.tr.setNodeMarkup(pos, undefined, { ...this.node.attrs, preview: value }),
    )
  }

  private onRun() {
    const kind = this.kind
    if (!kind) return
    if (kind === 'python') {
      void this.runPythonInline()
      return
    }
    this.setPreview(!this.previewOn)
  }

  /** 运行 Python，并把 stdout / stderr 持久化到代码块下方的结果块。 */
  private async runPythonInline() {
    if (this.running) return
    this.running = true
    this.sync()
    const code = this.node.textContent
    const pos = this.getPos()
    let output: string
    try {
      output = formatRunResult(await runPython(code))
    } catch (e: any) {
      output = `运行失败：${e?.message || '无法连接运行服务'}`
    }
    upsertCodeOutput(this.editor, pos, code, output)
    this.running = false
    this.sync()
  }

  update(node: PMNode): boolean {
    if (node.type !== this.node.type) return false
    this.node = node
    this.sync()
    return true
  }

  stopEvent(event: Event): boolean {
    const target = event.target as HTMLElement | null
    return !!target?.closest?.('.code-tools, .code-block-preview')
  }

  ignoreMutation(mutation: ViewMutationRecord): boolean {
    if (mutation.type === 'selection') return false
    return !this.contentDOM.contains(mutation.target)
  }

  destroy() {
    window.clearTimeout(this.renderTimer)
    window.removeEventListener('message', this.onPreviewMessage)
  }
}

export function createCodeBlock(lowlight: ReturnType<typeof createLowlight>) {
  return CodeBlockLowlight.extend({
    addKeyboardShortcuts() {
      // TipTap 默认用 Mod-Alt-c 切换代码块，与格式刷的「复制格式」
      // （Ctrl/Cmd+Alt+C）冲突，会导致复制格式时把段落变成代码块。
      // 代码块仍可通过工具栏和斜杠菜单插入，这里移除该快捷键。
      const shortcuts: Record<string, unknown> = {
        ...(this.parent?.() ?? {}),
      }
      delete shortcuts['Mod-Alt-c']
      return shortcuts as Record<string, () => boolean>
    },
    addProseMirrorPlugins() {
      return [...(this.parent?.() ?? []), lineNumberPlugin()]
    },
    addAttributes() {
      return {
        ...(this.parent?.() ?? {}),
        /** 是否在正文中渲染 HTML / JS 预览（仅内存状态，不写入 Markdown） */
        preview: {
          default: true,
          parseHTML: (element: HTMLElement) => element.getAttribute('data-preview') !== 'false',
          renderHTML: (attributes: Record<string, unknown>) =>
            attributes.preview === false ? { 'data-preview': 'false' } : {},
        },
      }
    },
    parseHTML() {
      // 运行结果块也是 <pre>，不能被普通代码块抢走
      return [{ tag: 'pre:not([data-code-output])', preserveWhitespace: 'full' }]
    },
    addNodeView() {
      return ({ node, editor, getPos }) =>
        new CodeBlockView(node, editor, getPos as () => number | undefined)
    },
  }).configure({ lowlight, defaultLanguage: 'plaintext' })
}
