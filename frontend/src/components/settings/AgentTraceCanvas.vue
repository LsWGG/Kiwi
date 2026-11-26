<script setup lang="ts">
/**
 * Agent 轨迹画布：Vue Flow 驱动的可拖动节点图。
 *
 * 主链按真实时间排序，重叠事件作为并行组；规划节点会按 planner 输出展开成
 * 多个并行查询分支（知识库 / 联网），再汇入下一组（向量化 / 检索 / 模型），
 * 因此不是单纯的时间线列表。点击节点由父组件弹出输入 / 输出详情。
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
  if (event.kind === 'understand') {
    const output = event.output as any
    const count = Array.isArray(output?.kb_ids) ? output.kb_ids.length : 0
    return count ? `范围：${count} 个知识库` : event.detail
  }
  if (event.kind === 'planner') {
    const output = event.output as any
    if (output && typeof output === 'object') {
      const reason = String(output.reason || '').trim()
      const queries = Array.isArray(output.queries) ? output.queries.length : 0
      const steps = Array.isArray(output.plan) ? output.plan.length : 0
      const parts = [reason]
      if (queries) parts.push(`${queries} 条查询`)
      if (steps) parts.push(`${steps} 步计划`)
      const text = parts.filter(Boolean).join(' · ')
      if (text) return text
    }
    return event.detail
  }
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

const EDGE_COLOR = 'rgb(var(--theme-text-secondary, 71 85 105) / 0.9)'
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
    type: 'smoothstep',
    pathOptions: { borderRadius: 12 },
    style: {
      stroke: EDGE_COLOR,
      strokeWidth: 2,
      ...(dashed ? { strokeDasharray: '5 5' } : {}),
    },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: EDGE_MARKER_COLOR,
      width: 14,
      height: 14,
    },
  }
}

const layout = computed(() => {
  const events = props.events
  if (!events.length) return { nodes: [], edges: [] }

  const requestIndex = 0
  const plannerIndex = events.findIndex((event) => event.kind === 'planner')
  const queryIndexes = events
    .map((event, index) => (isQuery(event) ? index : -1))
    .filter((index) => index >= 0)
  const nodeId = (index: number) => `trace-node-${index}`
  const logicalNodes = new Set<number>([requestIndex])
  const logicalEdges: Array<{
    id: string
    source: string
    target: string
    dashed?: boolean
  }> = []
  const addEdge = (id: string, source: string, target: string, dashed = false) => {
    logicalEdges.push({ id, source, target, dashed })
  }

  // 规划节点派生查询分支；查询分支会汇总到规划之后的检索组。
  if (plannerIndex > 0 && queryIndexes.length) {
    queryIndexes.forEach((index) => {
      logicalNodes.add(index)
      addEdge(
        `edge-planner-query-${index}`,
        nodeId(plannerIndex),
        nodeId(index),
        true,
      )
    })
  }

  // 主链按真实时间排序分组：understand 在 planner 之前，重叠事件为并行组。
  const mainIndexes = events
    .map((event, index) => ({ event, index }))
    .filter(({ index }) => index !== requestIndex && !isQuery(events[index]))
    .map(({ index }) => index)

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

  for (let groupIndex = 0; groupIndex < groups.length; groupIndex += 1) {
    const current = groups[groupIndex]
    current.forEach((index) => logicalNodes.add(index))
    if (groupIndex === 0) {
      current.forEach((index) => {
        addEdge(
          `edge-request-${index}`,
          nodeId(requestIndex),
          nodeId(index),
        )
      })
      continue
    }
    const previous = groups[groupIndex - 1]
    const plannerInPrevious = previous.includes(plannerIndex)
    const useQueries =
      plannerInPrevious && plannerIndex > 0 && queryIndexes.length > 0
    previous.forEach((parent) => {
      current.forEach((target) => {
        // 有查询分支时，规划节点通过查询分支汇入下一组，避免重复连线。
        if (useQueries && parent === plannerIndex) return
        addEdge(
          `edge-main-${parent}-${target}`,
          nodeId(parent),
          nodeId(target),
        )
      })
    })
    if (useQueries) {
      queryIndexes.forEach((queryIndex) => {
        current.forEach((target) => {
          addEdge(
            `edge-query-${queryIndex}-${target}`,
            nodeId(queryIndex),
            nodeId(target),
          )
        })
      })
    }
  }

  // 使用 dagre 做分层布局：规划后的多条查询会落在同一层并自动展开，
  // 再汇入下一次模型调用；不再手写坐标，避免节点挤压 / 连线交叉。
  const graph = new dagre.graphlib.Graph()
  graph.setGraph({
    rankdir: 'LR',
    nodesep: 22,
    ranksep: 48,
    marginx: 24,
    marginy: 24,
  })
  graph.setDefaultEdgeLabel(() => ({}))
  for (const index of logicalNodes) {
    graph.setNode(nodeId(index), { width: 188, height: 96 })
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
        y: Number(position?.y || 0) - 48,
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
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
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

/** 新节点完成尺寸测量后再 fit，避免用零尺寸计算出错误视口。 */
function onNodesInitialized() {
  fitView({ padding: 0.08 })
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
      :min-zoom="0.2"
      :max-zoom="1"
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
      @nodes-initialized="onNodesInitialized"
    >
      <template #node-trace="nodeProps">
        <div
          class="flex h-24 w-full cursor-pointer flex-col rounded-xl border px-3 py-2 shadow-sm transition-all"
          :class="
            props.selectedIndex === nodeProps.data.index
              ? 'border-kiwi-300 bg-kiwi-50/90 ring-2 ring-kiwi-100'
              : 'border-slate-200/80 bg-white/90 hover:-translate-y-0.5 hover:shadow-md'
          "
        >
          <Handle
            type="target"
            :position="Position.Left"
            class="!h-1.5 !w-1.5 !border-2 !border-white !bg-kiwi-400"
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
            <span class="shrink-0 text-[11px] font-medium text-slate-700">
              {{ nodeProps.data.label }}
            </span>
            <span class="min-w-0 truncate text-[9.5px] text-slate-400">
              {{ nodeProps.data.name }}
            </span>
            <span
              v-if="!nodeProps.data.synthetic || nodeProps.data.ms"
              class="ml-auto shrink-0 font-mono text-[8.5px]"
              :style="nodeProps.data.ok ? undefined : { color: toneColor('danger') }"
            >
              {{ formatShortMs(Number(nodeProps.data.ms || 0)) }}
            </span>
          </div>
          <p
            v-if="nodeProps.data.preview"
            class="mt-1 line-clamp-2 text-[9.5px] leading-relaxed text-slate-500"
          >
            {{ nodeProps.data.preview }}
          </p>
          <div
            v-if="
              nodeProps.data.tokens ||
              (nodeProps.data.synthetic && nodeProps.data.kind === 'query') ||
              !nodeProps.data.ok
            "
            class="mt-auto flex items-center gap-1.5 text-[8.5px] text-slate-400"
          >
            <span v-if="nodeProps.data.tokens">
              {{ nodeProps.data.tokens }} tokens
            </span>
            <span v-if="nodeProps.data.synthetic && nodeProps.data.kind === 'query'">查询分支</span>
            <span v-if="!nodeProps.data.ok" :style="{ color: toneColor('danger') }">
              异常
            </span>
          </div>
          <Handle
            type="source"
            :position="Position.Right"
            class="!h-1.5 !w-1.5 !border-2 !border-white !bg-kiwi-400"
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
