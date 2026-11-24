<script setup lang="ts">
/**
 * Agent 流转详情弹窗：可拖动 / 缩放的流程画布 + 节点输入输出面板。
 *
 * 运维页与问答页共用：问答页点击「Agent 流转」在原地弹出，关闭后仍停留在
 * 当前会话，不改变路由。轨迹只保存在后端内存（最近 100 轮），过期时由调用方
 * 负责提示。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AgentTraceCanvas from '@/components/settings/AgentTraceCanvas.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'
import { copyTextToClipboard } from '@/utils/clipboard'
import type { AgentTrace, AgentTraceEvent } from '@/api/operations'

const props = defineProps<{ trace: AgentTrace | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const selectedTraceEvent = ref(-1)
type TraceDetailTab = 'input' | 'output' | 'meta' | 'raw'
const traceDetailTab = ref<TraceDetailTab>('input')
const TRACE_DETAIL_TABS: Array<{ key: TraceDetailTab; label: string }> = [
  { key: 'input', label: '输入' },
  { key: 'output', label: '输出' },
  { key: 'meta', label: '元数据' },
  { key: 'raw', label: '原始 JSON' },
]

interface TraceTimelineEvent extends AgentTraceEvent {
  start: number
  end: number
  synthetic?: boolean
}

const TRACE_STATUS: Record<string, { label: string; tone: string }> = {
  running: { label: '进行中', tone: 'info' },
  done: { label: '完成', tone: 'success' },
  awaiting_approval: { label: '待确认', tone: 'warning' },
  error: { label: '失败', tone: 'danger' },
  cancelled: { label: '已取消', tone: 'muted' },
}

const TRACE_KIND: Record<string, { label: string; tone: string }> = {
  request: { label: '请求', tone: 'info' },
  planner: { label: '规划', tone: 'info' },
  query: { label: '查询', tone: 'info' },
  model: { label: '模型', tone: 'accent' },
  tool: { label: '工具', tone: 'success' },
  fast_path: { label: '快路径', tone: 'warning' },
  approval: { label: '审批', tone: 'warning' },
  retry: { label: '重试', tone: 'warning' },
  fallback: { label: '回退', tone: 'warning' },
  answer: { label: '回答', tone: 'accent' },
  error: { label: '错误', tone: 'danger' },
}

const TRACE_META_LABELS: Record<string, string> = {
  model: '模型',
  temperature: '温度',
  finish_reason: '结束原因',
  attempts: '尝试次数',
  error: '错误',
  reason: '原因',
  read_only: '只读',
  summary: '摘要',
  label: '标签',
  source: '来源',
  queries: '查询',
}

function traceStatusMeta(status: string) {
  return TRACE_STATUS[status] || { label: status, tone: 'muted' }
}

function traceKindMeta(kind: string) {
  return TRACE_KIND[kind] || { label: kind || '事件', tone: 'muted' }
}

function traceToneToken(tone: string) {
  if (tone === 'success') return 'var(--theme-success)'
  if (tone === 'warning') return 'var(--theme-warning)'
  if (tone === 'danger') return 'var(--theme-danger)'
  if (tone === 'info') return 'var(--theme-info)'
  if (tone === 'accent') return 'var(--theme-accent)'
  return 'var(--theme-text-secondary, 100 116 139)'
}

function traceToneStyle(tone: string) {
  const token = traceToneToken(tone)
  return { color: `rgb(${token})`, backgroundColor: `rgb(${token} / 0.12)` }
}

function traceToneColor(tone: string, alpha = 1) {
  return `rgb(${traceToneToken(tone)} / ${alpha})`
}

function formatTraceTime(ts: number | null) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatMs(ms: number) {
  if (!ms) return '0ms'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

function traceTimeline(trace: AgentTrace) {
  const events: TraceTimelineEvent[] = []
  const hasPlanner = trace.events.some((event) => event.kind === 'planner')
  if (!hasPlanner && trace.planner_ms > 0) {
    events.push({
      at: trace.planner_ms / 1000,
      kind: 'planner',
      name: '检索规划',
      ms: Math.round(trace.planner_ms),
      ok: true,
      detail: `${trace.planner_source || '规则'} · ${trace.planner_queries} 条查询`,
      start: 0,
      end: Math.round(trace.planner_ms),
      synthetic: true,
    })
  }
  for (const event of trace.events) {
    const end = Math.max(0, event.at * 1000)
    events.push({
      ...event,
      start: Math.max(0, end - event.ms),
      end,
    })
  }
  const total = Math.max(
    trace.duration_ms,
    ...events.map((event) => event.end),
    1,
  )
  return { total, events }
}

const activeTraceFlow = computed<TraceTimelineEvent[]>(() => {
  const trace = props.trace
  if (!trace) return []
  const request: TraceTimelineEvent = {
    at: 0,
    kind: 'request',
    name: '用户请求',
    ms: 0,
    ok: true,
    detail: trace.query || '',
    input: {
      query: trace.query || '',
      model: trace.model,
      scope: trace.scope,
    },
    start: 0,
    end: 0,
    synthetic: true,
  }
  const flow: TraceTimelineEvent[] = [request]
  for (const event of traceTimeline(trace).events) {
    flow.push(event)
    if (event.kind !== 'planner') continue
    const output = (event.output || {}) as any
    const queries = Array.isArray(output.queries) ? output.queries : []
    const webQueries = Array.isArray(output.web_queries) ? output.web_queries : []
    queries.forEach((query: unknown, index: number) => {
      flow.push({
        at: event.at,
        kind: 'query',
        name: `知识库查询 ${index + 1}`,
        ms: 0,
        ok: true,
        detail: String(query || ''),
        input: { query: String(query || ''), source: 'kb' },
        output: { applied: true },
        start: event.start,
        end: event.end,
        synthetic: true,
      })
    })
    webQueries.forEach((query: unknown, index: number) => {
      flow.push({
        at: event.at,
        kind: 'query',
        name: `联网查询 ${index + 1}`,
        ms: 0,
        ok: true,
        detail: String(query || ''),
        input: { query: String(query || ''), source: 'web' },
        output: { applied: true },
        start: event.start,
        end: event.end,
        synthetic: true,
      })
    })
  }
  return flow
})

const activeTimelineEvent = computed(() => {
  if (selectedTraceEvent.value < 0) return null
  return activeTraceFlow.value[selectedTraceEvent.value] || null
})

function traceKindCount(trace: AgentTrace, kind: string) {
  return trace.events.filter((event) => event.kind === kind).length
}

function selectTraceEvent(index: number) {
  selectedTraceEvent.value = index
  if (index >= 0) traceDetailTab.value = 'input'
}

function eventTokens(event: AgentTraceEvent): number {
  const usage = (event.meta as any)?.usage || {}
  return Number(usage.total_tokens || 0)
}

function traceTotalTokens(trace: AgentTrace): number {
  return trace.events
    .filter((event) => event.kind === 'model')
    .reduce((sum, event) => sum + eventTokens(event), 0)
}

interface TraceMessage {
  role: string
  content: string
}

function eventInputMessages(event: TraceTimelineEvent | null): TraceMessage[] {
  const input = event?.input as any
  if (!input || !Array.isArray(input.messages)) return []
  return input.messages
    .filter((item: any) => item && typeof item.content === 'string')
    .map((item: any) => ({
      role: String(item.role || 'message'),
      content: String(item.content),
    }))
}

function prettyTraceValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') {
    const text = value.trim()
    if (text.startsWith('{') || text.startsWith('[')) {
      try {
        return JSON.stringify(JSON.parse(text), null, 2)
      } catch {
        // 普通文本，原样展示。
      }
    }
    return value
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function eventMetaRows(event: TraceTimelineEvent) {
  const meta = event.meta || {}
  const rows: Array<{ label: string; value: string }> = []
  const usage = (meta as any).usage || {}
  if (usage.total_tokens) {
    rows.push({
      label: 'Tokens',
      value: `${usage.prompt_tokens || 0} 输入 / ${usage.completion_tokens || 0} 输出 / ${usage.total_tokens} 总计`,
    })
  }
  for (const [key, value] of Object.entries(meta)) {
    if (['usage', 'finish_reason', 'attempts'].includes(key)) continue
    rows.push({
      label: TRACE_META_LABELS[key] || key,
      value: prettyTraceValue(value),
    })
  }
  if ((meta as any).finish_reason) {
    rows.push({
      label: '结束原因',
      value: String((meta as any).finish_reason),
    })
  }
  if ((meta as any).attempts) {
    rows.push({
      label: '尝试次数',
      value: String((meta as any).attempts),
    })
  }
  rows.push({ label: '状态', value: event.ok ? '成功' : '异常' })
  rows.push({
    label: '开始 / 耗时',
    value: `${formatMs(event.start)} / ${formatMs(event.ms)}`,
  })
  return rows
}

function activeDetailValue(event: TraceTimelineEvent) {
  if (traceDetailTab.value === 'input') return event.input
  if (traceDetailTab.value === 'output') return event.output
  if (traceDetailTab.value === 'meta') return event.meta
  return event
}

async function copyTraceValue(value: unknown) {
  const ok = await copyTextToClipboard(prettyTraceValue(value))
  if (ok) toast.success('已复制')
  else toast.error('复制失败，请手动选择文本')
}

function downloadTrace() {
  const trace = props.trace
  if (!trace) return
  const blob = new Blob([JSON.stringify(trace, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `agent-trace-${trace.id}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

function close() {
  emit('close')
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.trace) close()
}

watch(
  () => props.trace?.id,
  () => {
    selectedTraceEvent.value = -1
    traceDetailTab.value = 'input'
  },
)

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div
      v-if="trace"
      class="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm md:p-8"
      @click.self="close"
    >
      <div
        class="flex max-h-[92vh] w-full max-w-[96vw] flex-col overflow-hidden rounded-2xl border border-slate-200/70 bg-white/95 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="Agent 流转详情"
      >
        <header class="flex flex-wrap items-center gap-3 border-b border-slate-200/70 px-5 py-4">
          <span class="grid h-8 w-8 place-items-center rounded-xl bg-kiwi-50 text-kiwi-600">
            <KiwiIcon name="sparkle" :size="15" />
          </span>
          <div class="min-w-0">
            <h3 class="text-[14px] font-semibold text-slate-700">Agent 流转详情</h3>
            <p class="truncate text-[10.5px] text-slate-400">
              {{ trace.id }} · {{ formatTraceTime(trace.started_at) }} ·
              {{ trace.model || '未知模型' }}
            </p>
          </div>
          <span
            class="rounded-full px-2 py-0.5 text-[10px] font-medium"
            :style="traceToneStyle(traceStatusMeta(trace.status).tone)"
          >
            {{ traceStatusMeta(trace.status).label }}
          </span>
          <span class="text-[11px] text-slate-400">
            {{ formatMs(trace.duration_ms) }} · {{ trace.query_chars }} 字提问 ·
            {{ trace.scope }}
            <template v-if="traceTotalTokens(trace)">
              · {{ traceTotalTokens(trace) }} tokens
            </template>
          </span>
          <div class="ml-auto flex items-center gap-1">
            <button
              type="button"
              class="grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
              title="导出轨迹 JSON"
              aria-label="导出轨迹 JSON"
              @click="downloadTrace"
            >
              <KiwiIcon name="download" :size="13" />
            </button>
            <button
              type="button"
              class="grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
              aria-label="关闭"
              @click="close"
            >
              <KiwiIcon name="close" :size="14" />
            </button>
          </div>
        </header>

        <div class="overflow-y-auto px-5 py-4">
          <div class="mb-4 grid gap-2 sm:grid-cols-4">
            <div class="rounded-xl border border-slate-200/70 bg-white/60 px-3 py-2">
              <div class="text-[10px] text-slate-400">检索规划</div>
              <div class="mt-0.5 text-[12px] text-slate-700">
                {{ trace.planner_source || '规则' }} ·
                {{ formatMs(trace.planner_ms) }}
              </div>
            </div>
            <div class="rounded-xl border border-slate-200/70 bg-white/60 px-3 py-2">
              <div class="text-[10px] text-slate-400">模型调用</div>
              <div class="mt-0.5 text-[12px] text-slate-700">
                {{ traceKindCount(trace, 'model') }} 次
              </div>
            </div>
            <div class="rounded-xl border border-slate-200/70 bg-white/60 px-3 py-2">
              <div class="text-[10px] text-slate-400">工具调用</div>
              <div class="mt-0.5 text-[12px] text-slate-700">
                {{ traceKindCount(trace, 'tool') }} 次
              </div>
            </div>
            <div class="rounded-xl border border-slate-200/70 bg-white/60 px-3 py-2">
              <div class="text-[10px] text-slate-400">审批 / 异常</div>
              <div class="mt-0.5 text-[12px] text-slate-700">
                {{ traceKindCount(trace, 'approval') }} /
                {{ traceKindCount(trace, 'error') }}
              </div>
            </div>
          </div>

          <div class="relative">
            <div class="h-[62vh] min-h-[440px]">
              <AgentTraceCanvas
                :trace="trace"
                :events="activeTraceFlow"
                :selected-index="selectedTraceEvent"
                @select="selectTraceEvent"
              />
            </div>

            <div
              v-if="activeTimelineEvent"
              class="absolute bottom-3 right-3 top-3 z-10 flex w-[min(460px,54%)] flex-col overflow-hidden rounded-xl border border-slate-200/70 bg-white/95 p-3 shadow-2xl backdrop-blur max-lg:left-2 max-lg:right-2 max-lg:top-auto max-lg:h-[58%] max-lg:w-auto"
            >
              <div class="flex flex-wrap items-center gap-2">
                <span
                  class="h-2 w-2 rounded-full"
                  :style="{
                    backgroundColor: traceToneColor(
                      traceKindMeta(activeTimelineEvent.kind).tone,
                    ),
                  }"
                ></span>
                <span class="text-[12px] font-medium text-slate-700">
                  {{ traceKindMeta(activeTimelineEvent.kind).label }} ·
                  {{ activeTimelineEvent.name }}
                </span>
                <span
                  class="rounded-full px-1.5 py-0.5 text-[9px]"
                  :style="traceToneStyle(activeTimelineEvent.ok ? 'success' : 'danger')"
                >
                  {{ activeTimelineEvent.ok ? '成功' : '异常' }}
                </span>
                <span class="ml-auto text-[9.5px] text-slate-400">
                  {{ formatMs(activeTimelineEvent.ms) }}
                  <template v-if="eventTokens(activeTimelineEvent)">
                    · {{ eventTokens(activeTimelineEvent) }} tokens
                  </template>
                </span>
                <button
                  type="button"
                  class="grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                  aria-label="关闭详情"
                  @click="selectedTraceEvent = -1"
                >
                  <KiwiIcon name="close" :size="12" />
                </button>
              </div>

              <div class="mt-2 flex items-center gap-1 border-b border-slate-200/70 pb-1">
                <button
                  v-for="tab in TRACE_DETAIL_TABS"
                  :key="tab.key"
                  type="button"
                  class="rounded-md px-2 py-0.5 text-[10.5px] transition-colors"
                  :class="
                    traceDetailTab === tab.key
                      ? 'bg-kiwi-50 text-kiwi-700'
                      : 'text-slate-400 hover:text-slate-600'
                  "
                  @click="traceDetailTab = tab.key"
                >
                  {{ tab.label }}
                </button>
                <button
                  type="button"
                  class="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                  @click="copyTraceValue(activeDetailValue(activeTimelineEvent))"
                >
                  <KiwiIcon name="copy" :size="10" />
                  复制
                </button>
              </div>

              <div class="mt-2 min-h-0 flex-1 overflow-y-auto">
                <template v-if="traceDetailTab === 'input'">
                  <div v-if="eventInputMessages(activeTimelineEvent).length" class="space-y-1.5">
                    <div
                      v-for="(message, index) in eventInputMessages(activeTimelineEvent)"
                      :key="index"
                      class="overflow-hidden rounded-lg border border-slate-200/70 bg-white/70"
                    >
                      <div
                        class="flex items-center gap-2 border-b border-slate-200/60 bg-slate-50/60 px-2 py-1 text-[9.5px]"
                      >
                        <span class="font-medium text-slate-500">
                          {{ message.role }}
                        </span>
                        <span class="ml-auto text-slate-400">
                          {{ message.content.length }} 字
                        </span>
                      </div>
                      <pre
                        class="max-h-56 overflow-auto whitespace-pre-wrap break-words px-2 py-1.5 font-mono text-[10px] leading-relaxed text-slate-600"
                      >{{ message.content }}</pre>
                    </div>
                  </div>
                  <pre
                    v-else
                    class="whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-slate-600"
                  >{{ prettyTraceValue(activeTimelineEvent.input) }}</pre>
                </template>

                <pre
                  v-else-if="traceDetailTab === 'output'"
                  class="whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-slate-600"
                >{{ prettyTraceValue(activeTimelineEvent.output) }}</pre>

                <dl
                  v-else-if="traceDetailTab === 'meta'"
                  class="grid gap-x-3 gap-y-1 text-[10.5px] sm:grid-cols-[90px_1fr]"
                >
                  <template v-for="row in eventMetaRows(activeTimelineEvent)" :key="row.label">
                    <dt class="text-slate-400">{{ row.label }}</dt>
                    <dd class="break-words font-mono text-slate-600">
                      {{ row.value }}
                    </dd>
                  </template>
                </dl>

                <pre
                  v-else
                  class="whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-slate-600"
                >{{ prettyTraceValue(activeTimelineEvent) }}</pre>
              </div>
            </div>

            <div
              v-else
              class="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-slate-200/70 bg-white/85 px-3 py-1 text-[10px] text-slate-400 shadow-sm backdrop-blur"
            >
              点击节点查看输入 / 输出、token 与元数据 · 拖动画布或节点可调整布局
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
