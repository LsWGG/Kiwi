<script setup lang="ts">
/**
 * Agent 轨迹画布：Vue Flow 驱动的可拖动节点图。
 *
 * 规划节点会按 planner 输出展开成多个并行查询节点（知识库 / 联网），再汇入
 * 第一次模型调用，因此不是单纯的时间线列表；后续模型 / 工具 / 审批 / 回答
 * 节点按执行顺序连接。点击节点由父组件弹出输入 / 输出详情。
 */
import { computed } from 'vue'
import dagre from '@dagrejs/dagre'
import {
  Handle,
  MarkerType,
  Position,
  VueFlow,
  useVueFlow,
  type Edge,
} from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import type { AgentTrace, AgentTraceEvent } from '@/api/operations'

export interface TraceCanvasEvent extends AgentTraceEvent {
  start: number
  end: number
  synthetic?: boolean
}

const props = defineProps<{
  trace: AgentTrace
  events: TraceCanvasEvent[]
  selectedIndex: number
}>()

const emit = defineEmits<{ select: [index: number] }>()

const flowId = `agent-trace-${Math.random().toString(36).slice(2, 9)}`
const { fitView, zoomIn, zoomOut } = useVueFlow(flowId)

const TRACE_KIND: Record<string, { label: string; tone: string; icon: string }> = {
  request: { label: '请求', tone: 'info', icon: 'chat' },
  planner: { label: '规划', tone: 'info', icon: 'target' },
  query: { label: '查询', tone: 'info', icon: 'search' },
  embedding: { label: '向量', tone: 'info', icon: 'sparkle' },
  model: { label: '模型', tone: 'accent', icon: 'sparkle' },
  tool: { label: '工具', tone: 'success', icon: 'terminal' },
  approval: { label: '审批', tone: 'warning', icon: 'shield' },
  answer: { label: '回答', tone: 'accent', icon: 'check' },
  retry: { label: '重试', tone: 'warning', icon: 'refresh' },
  fallback: { label: '回退', tone: 'warning', icon: 'refresh' },
  error: { label: '错误', tone: 'danger', icon: 'alert' },
  fast_path: { label: '快路径', tone: 'warning', icon: 'trendingUp' },
}

function kindMeta(kind: string) {
  return TRACE_KIND[kind] || { label: kind || '事件', tone: 'muted', icon: 'circle' }
}

function toneToken(tone: string) {
  if (tone === 'success') return 'var(--theme-success)'
  if (tone === 'warning') return 'var(--theme-warning)'
  if (tone === 'danger') return 'var(--theme-danger)'
  if (tone === 'info') return 'var(--theme-info)'
  if (tone === 'accent') return 'var(--theme-accent)'
  return 'var(--theme-text-secondary, 100 116 139)'
}

function toneColor(tone: string, alpha = 1) {
  return `rgb(${toneToken(tone)} / ${alpha})`
}

function formatShortMs(ms: number) {
  if (!ms) return '0ms'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

function messageList(event: TraceCanvasEvent) {
  const input = event.input as any
  if (!input || !Array.isArray(input.messages)) return []
  return input.messages.filter(
    (item: any) => item && typeof item.content === 'string',
  )
}

function modelPreview(output: unknown) {
  if (typeof output !== 'string') return ''
  try {
    const data = JSON.parse(output)
    if (data && typeof data === 'object') {
      if (typeof data.answer === 'string' && data.answer.trim()) {
        return `回答：${data.answer}`
      }
      if (typeof data.thought === 'string' && data.thought.trim()) {
        return `思考：${data.thought}`
      }
      if (data.action && typeof data.action.summary === 'string') {
        return `动作：${data.action.summary}`
      }
    }
  } catch {
    // 普通文本。
  }
  return output
}

function nodePreview(event: TraceCanvasEvent) {
  if (event.kind === 'request') return event.detail || ''
  if (event.kind === 'model') {
    const text = modelPreview(event.output)
    if (text) return text.replace(/\s+/g, ' ').slice(0, 140)
    const messages = messageList(event)
    return messages.length
      ? String(messages[messages.length - 1].content).replace(/\s+/g, ' ').slice(0, 140)
      : event.detail
  }
  if (event.kind === 'tool') {
    const input = event.input as any
    const args = input?.args ? JSON.stringify(input.args) : ''
    return `${args.slice(0, 80)}${args ? ' → ' : ''}${event.detail || ''}`
  }
  return String(event.detail || '').slice(0, 140)
}

function eventTokens(event: TraceCanvasEvent) {
  const usage = (event.meta as any)?.usage || {}
  return Number(usage.total_tokens || 0)
}

function isQuery(event: TraceCanvasEvent) {
  return event.kind === 'query'
}

const EDGE_COLOR = 'rgb(var(--theme-text-secondary, 71 85 105) / 0.62)'
const EDGE_MARKER_COLOR = 'rgb(var(--theme-text-secondary, 71 85 105) / 0.85)'

function makeEdge(
  id: string,
  source: string,
  target: string,
  dashed = false,
): Edge {
  return {
    id,
    source,
    target,
    type: 'default',
    style: {
      stroke: EDGE_COLOR,
      strokeWidth: 2,
      ...(dashed ? { strokeDasharray: '5 5' } : {}),
    },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: EDGE_MARKER_COLOR,
      width: 18,
      height: 18,
    },
  }
}

const layout = computed(() => {
  const events = props.events
  if (!events.length) return { nodes: [], edges: [] }

  const plannerIndex = events.findIndex((event) => event.kind === 'planner')
  const queryIndexes = events
    .map((event, index) => (isQuery(event) ? index : -1))
    .filter((index) => index >= 0)
  const nodeId = (index: number) => `trace-node-${index}`
  const logicalNodes = new Set<number>([0])
  const logicalEdges: Array<{
    id: string
    source: string
    target: string
    dashed?: boolean
  }> = []

  if (plannerIndex > 0) {
    logicalNodes.add(plannerIndex)
    logicalEdges.push({
      id: 'edge-request-planner',
      source: nodeId(0),
      target: nodeId(plannerIndex),
    })
    if (queryIndexes.length) {
      queryIndexes.forEach((index) => {
        logicalNodes.add(index)
        logicalEdges.push({
          id: `edge-planner-query-${index}`,
          source: nodeId(plannerIndex),
          target: nodeId(index),
          dashed: true,
        })
      })
    }
  }

  const mainIndexes = events
    .map((event, index) => ({ event, index }))
    .filter(
      ({ event, index }) =>
        index !== 0 && index !== plannerIndex && !isQuery(event),
    )
    .map(({ index }) => index)

  // 按时间区间分组：重叠的节点属于同一并行组，组之间才串行。
  const spans = mainIndexes
    .map((index) => ({
      index,
      start: Math.max(0, events[index].start),
      end: Math.max(0, events[index].end),
    }))
    .sort((a, b) => a.start - b.start || a.end - b.end)

  const groups: number[][] = []
  let groupEnd = -1
  for (const span of spans) {
    const current = groups[groups.length - 1]
    if (!current || span.start >= groupEnd) {
      groups.push([span.index])
      groupEnd = span.end
    } else {
      current.push(span.index)
      groupEnd = Math.max(groupEnd, span.end)
    }
  }

  const addEdge = (id: string, source: string, target: string, dashed = false) => {
    logicalEdges.push({ id, source, target, dashed })
  }

  const firstGroup = groups[0] ?? []
  const firstParents = queryIndexes.length
    ? queryIndexes
    : plannerIndex > 0
      ? [plannerIndex]
      : [0]
  firstGroup.forEach((index) => {
    logicalNodes.add(index)
    firstParents.forEach((parent) => {
      addEdge(`edge-main-in-${parent}-${index}`, nodeId(parent), nodeId(index))
    })
  })

  for (let groupIndex = 1; groupIndex < groups.length; groupIndex += 1) {
    const previous = groups[groupIndex - 1]
    const current = groups[groupIndex]
    current.forEach((index) => {
      logicalNodes.add(index)
      previous.forEach((parent) => {
        addEdge(`edge-main-${parent}-${index}`, nodeId(parent), nodeId(index))
      })
    })
  }

  // 使用 dagre 做分层布局：规划后的多条查询会落在同一层并自动展开，
  // 再汇入下一次模型调用；不再手写坐标，避免节点挤压 / 连线交叉。
  const graph = new dagre.graphlib.Graph()
  graph.setGraph({
    rankdir: 'TB',
    nodesep: 38,
    ranksep: 62,
    marginx: 28,
    marginy: 24,
  })
  graph.setDefaultEdgeLabel(() => ({}))
  for (const index of logicalNodes) {
    graph.setNode(nodeId(index), { width: 188, height: 104 })
  }
  for (const edge of logicalEdges) {
    graph.setEdge(edge.source, edge.target)
  }
  dagre.layout(graph)

  const nodes = [...logicalNodes].map((index) => {
    const event = events[index]
    const meta = kindMeta(event.kind)
    const position = graph.node(nodeId(index))
    return {
      id: nodeId(index),
      type: 'trace',
      position: {
        x: Number(position?.x || 0) - 94,
        y: Number(position?.y || 0) - 52,
      },
      draggable: true,
      selectable: false,
      data: {
        index,
        kind: event.kind,
        label: meta.label,
        icon: meta.icon,
        tone: meta.tone,
        name: event.name,
        preview: nodePreview(event),
        ms: event.ms,
        tokens: eventTokens(event),
        ok: event.ok,
        synthetic: Boolean(event.synthetic),
      },
      style: { width: '188px' },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    }
  })

  const edges = logicalEdges.map((edge) =>
    makeEdge(edge.id, edge.source, edge.target, edge.dashed),
  )

  return { nodes, edges }
})

function onNodeClick({ node }: { node: any }) {
  emit('select', Number(node?.data?.index ?? -1))
}
</script>

<template>
  <div
    class="relative h-full w-full overflow-hidden rounded-xl border border-slate-200/70 bg-white/40"
    :style="{
      backgroundImage:
        'radial-gradient(rgb(var(--theme-border, 226 232 240) / 0.7) 1px, transparent 1px)',
      backgroundSize: '18px 18px',
    }"
  >
    <VueFlow
      :id="flowId"
      :nodes="layout.nodes"
      :edges="layout.edges"
      :min-zoom="0.5"
      :max-zoom="1.4"
      :nodes-draggable="true"
      :nodes-connectable="false"
      :elements-selectable="false"
      :zoom-on-scroll="true"
      :pan-on-drag="true"
      :fit-view-on-init="true"
      :fit-view-options="{ padding: 0.08 }"
      class="h-full w-full"
      :style="{ background: 'transparent' }"
      @node-click="onNodeClick"
    >
      <template #node-trace="nodeProps">
        <div
          class="w-full cursor-pointer rounded-xl border px-3 py-2 shadow-sm transition-all"
          :class="
            props.selectedIndex === nodeProps.data.index
              ? 'border-kiwi-300 bg-kiwi-50/90 ring-2 ring-kiwi-100'
              : 'border-slate-200/80 bg-white/90 hover:-translate-y-0.5 hover:shadow-md'
          "
        >
          <Handle
            type="target"
            :position="Position.Top"
            class="!h-1.5 !w-1.5 !border-0 !bg-transparent"
          />
          <div class="flex items-center gap-1.5">
            <span
              class="grid h-6 w-6 shrink-0 place-items-center rounded-lg"
              :style="{
                backgroundColor: toneColor(nodeProps.data.tone, 0.13),
                color: toneColor(nodeProps.data.tone),
              }"
            >
              <KiwiIcon :name="nodeProps.data.icon" :size="12" />
            </span>
            <span class="text-[11px] font-medium text-slate-700">
              {{ nodeProps.data.label }}
            </span>
            <span class="min-w-0 truncate text-[9.5px] text-slate-400">
              {{ nodeProps.data.name }}
            </span>
            <span
              class="ml-auto shrink-0 font-mono text-[8.5px]"
              :style="nodeProps.data.ok ? undefined : { color: toneColor('danger') }"
            >
              {{ formatShortMs(Number(nodeProps.data.ms || 0)) }}
            </span>
          </div>
          <p class="mt-1 line-clamp-2 text-[9.5px] leading-relaxed text-slate-500">
            {{ nodeProps.data.preview || '—' }}
          </p>
          <div class="mt-1 flex items-center gap-1.5 text-[8.5px] text-slate-400">
            <span v-if="nodeProps.data.tokens">
              {{ nodeProps.data.tokens }} tokens
            </span>
            <span v-if="nodeProps.data.synthetic">派生节点</span>
            <span v-if="!nodeProps.data.ok" :style="{ color: toneColor('danger') }">
              异常
            </span>
          </div>
          <Handle
            type="source"
            :position="Position.Bottom"
            class="!h-1.5 !w-1.5 !border-0 !bg-transparent"
          />
        </div>
      </template>
    </VueFlow>

    <div class="absolute left-2 top-2 flex items-center gap-1 rounded-lg border border-slate-200/70 bg-white/85 p-1 text-slate-500 shadow-sm backdrop-blur">
      <button
        type="button"
        class="grid h-6 w-6 place-items-center rounded-md transition-colors hover:bg-slate-100"
        title="缩小"
        aria-label="缩小"
        @click="zoomOut()"
      >
        <KiwiIcon name="minus" :size="12" />
      </button>
      <button
        type="button"
        class="grid h-6 w-6 place-items-center rounded-md transition-colors hover:bg-slate-100"
        title="放大"
        aria-label="放大"
        @click="zoomIn()"
      >
        <KiwiIcon name="plus" :size="12" />
      </button>
      <button
        type="button"
        class="grid h-6 w-6 place-items-center rounded-md transition-colors hover:bg-slate-100"
        title="适应画布"
        aria-label="适应画布"
        @click="fitView({ padding: 0.08 })"
      >
        <KiwiIcon name="maximize" :size="12" />
      </button>
    </div>
  </div>
</template>

<style scoped>
:deep(.vue-flow__node) {
  font-family: inherit;
}

:deep(.vue-flow__edge-path) {
  transition: stroke 0.2s ease;
}

:deep(.vue-flow__node.dragging) {
  cursor: grabbing;
}
</style>
