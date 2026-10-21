/**
 * 待办进度组件：绑定附近的 TaskList，实时统计完成度。
 *
 * 与旧版「自动给每个清单加装饰」不同，这是一个可插入、可配置的独立块：
 * 标题、是否显示计数 / 百分比、配色、绑定方向都写在节点属性里，
 * 以 ```kiwi-task-progress 围栏 + JSON 持久化，复制与往返不丢配置。
 */
import { Node } from '@tiptap/core'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import TaskProgressNodeView from './TaskProgressNodeView.vue'

const PROGRESS_LANGUAGE = 'kiwi-task-progress'

export const TASK_PROGRESS_COLORS = [
  'indigo',
  'violet',
  'green',
  'blue',
  'amber',
  'rose',
  'slate',
] as const

export const TASK_PROGRESS_COLOR_LABELS: Record<
  (typeof TASK_PROGRESS_COLORS)[number],
  string
> = {
  indigo: '清单同色',
  violet: '紫罗兰',
  green: '绿色',
  blue: '蓝色',
  amber: '琥珀',
  rose: '玫红',
  slate: '石板灰',
}

export type TaskProgressColor = (typeof TASK_PROGRESS_COLORS)[number]
export type TaskProgressBind = 'auto' | 'next' | 'prev'

const COLOR_SET = new Set<string>(TASK_PROGRESS_COLORS)

export interface TaskProgressAttrs {
  label?: string
  showCount?: boolean
  showPercent?: boolean
  color?: TaskProgressColor
  bind?: TaskProgressBind
}

export interface TaskListStats {
  done: number
  total: number
  percent: number
}

export function normalizeTaskProgressColor(value: unknown): TaskProgressColor {
  const color = String(value ?? '')
  return COLOR_SET.has(color) ? (color as TaskProgressColor) : 'indigo'
}

export function normalizeTaskProgressBind(value: unknown): TaskProgressBind {
  return value === 'next' || value === 'prev' ? value : 'auto'
}

export function taskListStats(node: ProseMirrorNode): TaskListStats {
  // 递归统计多级待办：taskItem 内可以继续嵌套 taskList，
  // 只看直接子节点会漏掉二级 / 三级清单。
  let done = 0
  let total = 0
  node.descendants((child) => {
    if (child.type.name !== 'taskItem') return
    total += 1
    if (child.attrs.checked) done += 1
  })
  return {
    done,
    total,
    percent: total ? Math.round((done / total) * 100) : 0,
  }
}

/**
 * 找当前进度块绑定的任务清单。
 * - next：文档中位于进度块之后的第一个清单；
 * - prev：之前最后一个清单；
 * - auto：距离最近的一个，同距时优先下方。
 * 嵌套在 taskItem 里的子清单不参与绑定，避免统计到子任务。
 */
export function findBoundTaskList(
  doc: ProseMirrorNode,
  nodePos: number,
  bind: TaskProgressBind,
): { pos: number; node: ProseMirrorNode } | null {
  let best: { pos: number; node: ProseMirrorNode; distance: number } | null = null
  doc.descendants((node, pos) => {
    if (node.type.name !== 'taskList') return
    if (doc.resolve(pos).parent.type.name === 'taskItem') return
    const isNext = pos > nodePos
    if (bind === 'next' && !isNext) return
    if (bind === 'prev' && isNext) return
    const distance = isNext ? pos - nodePos : nodePos - (pos + node.nodeSize)
    if (
      !best ||
      distance < best.distance ||
      (distance === best.distance && isNext && best.pos < nodePos)
    ) {
      best = { pos, node, distance }
    }
  })
  return best
}

/** 首次插入且附近没有清单时，附带的示例清单。 */
export function starterTaskListContent() {
  const item = (text: string, checked: boolean) => ({
    type: 'taskItem',
    attrs: { checked },
    content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
  })
  return {
    type: 'taskList',
    content: [
      item('确认目标与范围', true),
      item('拆解下一步行动', false),
      item('完成后勾选并复盘', false),
    ],
  }
}

function parseProgress(element: HTMLElement) {
  try {
    return JSON.parse(element.textContent || '{}') as Record<string, unknown>
  } catch {
    return {}
  }
}

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

/** 插入点附近是否已有任务清单，用于决定要不要附带示例清单。 */
function hasTaskListNearby(doc: ProseMirrorNode, pos: number): boolean {
  const from = Math.max(0, pos - 800)
  const to = Math.min(doc.content.size, pos + 800)
  let found = false
  doc.nodesBetween(from, to, (node) => {
    if (node.type.name === 'taskList') found = true
    return !found
  })
  return found
}

export const KiwiTaskProgress = Node.create({
  name: 'taskProgress',
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      label: {
        default: '待办进度',
        parseHTML: (element) =>
          String(parseProgress(element).label || '待办进度').slice(0, 80),
      },
      showCount: {
        default: true,
        parseHTML: (element) => parseProgress(element).showCount !== false,
      },
      showPercent: {
        default: true,
        parseHTML: (element) => parseProgress(element).showPercent !== false,
      },
      color: {
        default: 'indigo',
        parseHTML: (element) => normalizeTaskProgressColor(parseProgress(element).color),
      },
      bind: {
        default: 'auto',
        parseHTML: (element) => normalizeTaskProgressBind(parseProgress(element).bind),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'pre[data-kiwi-task-progress]' }]
  },

  renderHTML({ node }) {
    return [
      'pre',
      { 'data-kiwi-task-progress': 'true', class: 'kiwi-task-progress-node' },
      JSON.stringify({
        label: String(node.attrs.label || '待办进度'),
        showCount: node.attrs.showCount !== false,
        showPercent: node.attrs.showPercent !== false,
        color: normalizeTaskProgressColor(node.attrs.color),
        bind: normalizeTaskProgressBind(node.attrs.bind),
      }),
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(TaskProgressNodeView)
  },

  addCommands() {
    return {
      insertTaskProgress:
        (attrs: TaskProgressAttrs = {}) =>
        ({ state, commands }) => {
          const content: any[] = [
            {
              type: this.name,
              attrs: {
                label: String(attrs.label || '待办进度').slice(0, 80),
                showCount: attrs.showCount !== false,
                showPercent: attrs.showPercent !== false,
                color: normalizeTaskProgressColor(attrs.color),
                bind: normalizeTaskProgressBind(attrs.bind),
              },
            },
          ]
          if (!hasTaskListNearby(state.doc, state.selection.from)) {
            content.push(starterTaskListContent())
          }
          return commands.insertContent(content)
        },
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const json = JSON.stringify({
            label: String(node.attrs.label || '待办进度').slice(0, 80),
            showCount: node.attrs.showCount !== false,
            showPercent: node.attrs.showPercent !== false,
            color: normalizeTaskProgressColor(node.attrs.color),
            bind: normalizeTaskProgressBind(node.attrs.bind),
          })
          const fence = fenceFor(json)
          state.write(`${fence}${PROGRESS_LANGUAGE}\n`)
          state.write(json)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiTaskProgress) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === PROGRESS_LANGUAGE) {
                return `<pre data-kiwi-task-progress="true">${escapeHtml(
                  token.content.trim(),
                )}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiTaskProgress = true
            rules.fence = fence
          },
        },
      },
    }
  },
})

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    taskProgress: {
      insertTaskProgress: (attrs?: TaskProgressAttrs) => ReturnType
    }
  }
}
