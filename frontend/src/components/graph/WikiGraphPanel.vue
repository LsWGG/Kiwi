<script setup lang="ts">
/**
 * WikiGraphPanel：嵌入 Wiki 总览页顶部的知识图谱大画布。
 * - 自含数据加载（/wiki/graph/data），随 currentKbId 切换重拉。
 * - 浮层筛选：页面类型 / 仅人工编辑 / 是否包含笔记 / 焦点邻域。
 * - 后端返回 performance_mode / truncated，前端明确提示降级原因。
 * - G6 不可用时降级为关系列表；加载/错误/空态各就各位。
 * - 节点点击上抛 select:node（id 带 "wiki:" / "note:" 前缀，父级负责路由）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiSkeleton from '@/components/ui/KiwiSkeleton.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import KiwiGraph, {
  type GraphNodeData,
  type GraphEdgeData,
} from '@/components/graph/KiwiGraph.vue'

interface GraphData {
  nodes: GraphNodeData[]
  edges: GraphEdgeData[]
  performance_mode: boolean
  truncated: boolean
  total_nodes: number
}

interface GraphFilters {
  includeNotes: boolean
  types: string[]
  humanOnly: 'all' | 'edited' | 'generated'
  focus: string
  depth: 1 | 2 | 3
}

const emit = defineEmits<{ (e: 'select:node', nodeId: string): void }>()

const kbs = useKbsStore()
const graph = ref<GraphData | null>(null)
const graphLoading = ref(false)
/** G6 是否渲染成功（KiwiGraph 降级或加载失败时置 false） */
const graphReady = ref(true)
/** 数据已到但画布尚未 ready（显示「布局计算中」遮罩） */
const renderBusy = ref(false)
const errorMsg = ref('')
/** 全屏目标 wrapper */
const wrapper = ref<HTMLDivElement>()
const graphRef = ref<{ layout(): void } | null>(null)
const isFullscreen = ref(false)

const TYPE_ORDER = ['entity', 'concept', 'summary', 'synthesis', 'note']
const TYPE_LABEL: Record<string, string> = {
  entity: '实体',
  concept: '概念',
  summary: '摘要',
  synthesis: '综合',
  note: '笔记',
  wiki: 'Wiki',
}
// 与 KiwiGraph 的 NODE_PALETTE 同源：柔和淡彩（品牌紫/青/绿/琥珀/玫红）
const TYPE_CLASS: Record<string, string> = {
  entity: 'bg-[#6f72dc]/10 text-[#6f72dc]',
  concept: 'bg-[#3fa0c9]/10 text-[#3fa0c9]',
  summary: 'bg-[#559d71]/10 text-[#559d71]',
  synthesis: 'bg-[#c6944e]/10 text-[#c6944e]',
  note: 'bg-[#7a8b9e]/10 text-[#7a8b9e]',
  wiki: 'bg-[#bd6f9e]/10 text-[#bd6f9e]',
}
const NODE_COLOR: Record<string, string> = {
  entity: '#6f72dc',
  concept: '#3fa0c9',
  summary: '#559d71',
  synthesis: '#c6944e',
  note: '#7a8b9e',
  wiki: '#bd6f9e',
}
// 与 KiwiGraph EDGE_STYLES 同源
const EDGE_LABEL: Record<string, string> = {
  reference: '引用',
  note_link: '笔记双向链接',
  note_wiki: '笔记关联 Wiki',
  related: '相关',
  contradiction: '矛盾',
}
const EDGE_COLOR: Record<string, string> = {
  reference: '#7c86ee',
  note_link: '#4fb3a5',
  note_wiki: '#c58ad0',
  related: '#d0a24a',
  contradiction: '#ef6a6a',
}
const EDGE_DASHED: Record<string, boolean> = {
  reference: false,
  note_link: true,
  note_wiki: true,
  related: true,
  contradiction: true,
}

// ---------- 筛选 ----------
const filterOpen = ref(false)
const FILTER_TYPES = ['entity', 'concept', 'summary', 'synthesis']
const defaultFilters = (): GraphFilters => ({
  includeNotes: true,
  types: [],
  humanOnly: 'all',
  focus: '',
  depth: 2,
})
const draft = reactive<GraphFilters>(defaultFilters())
const applied = ref<GraphFilters>(defaultFilters())

const activeFilterCount = computed(() => {
  const f = applied.value
  let count = 0
  if (!f.includeNotes) count += 1
  if (f.types.length) count += 1
  if (f.humanOnly !== 'all') count += 1
  if (f.focus) count += 1
  return count
})

function toggleType(type: string) {
  const idx = draft.types.indexOf(type)
  if (idx >= 0) draft.types.splice(idx, 1)
  else draft.types.push(type)
}

function applyFilters() {
  applied.value = {
    includeNotes: draft.includeNotes,
    types: [...draft.types],
    humanOnly: draft.humanOnly,
    focus: draft.focus,
    depth: draft.depth,
  }
  filterOpen.value = false
  void load()
}

function resetFilters() {
  Object.assign(draft, defaultFilters())
  applied.value = defaultFilters()
  filterOpen.value = false
  void load()
}

function buildPath(filters: GraphFilters): string {
  const qs = new URLSearchParams()
  qs.set('include_notes', String(filters.includeNotes))
  for (const type of filters.types) qs.append('page_types', type)
  if (filters.humanOnly === 'edited') qs.set('human_edited', 'true')
  if (filters.humanOnly === 'generated') qs.set('human_edited', 'false')
  if (filters.focus) {
    qs.set('focus', filters.focus)
    qs.set('depth', String(filters.depth))
  }
  return `/wiki/graph/data?${qs.toString()}`
}

async function load() {
  if (!kbs.currentKbId) return
  graphLoading.value = true
  errorMsg.value = ''
  renderBusy.value = true
  graphReady.value = true
  try {
    graph.value = await request<GraphData>(buildPath(applied.value), {
      kbId: kbs.currentKbId,
    })
  } catch (e: any) {
    errorMsg.value = e.message
    graph.value = null
  } finally {
    graphLoading.value = false
  }
}

onMounted(load)
watch(() => kbs.currentKbId, () => {
  resetFilters()
})

/** KiwiGraph 渲染失败 → 降级为关系列表 */
function degrade() {
  graphReady.value = false
  renderBusy.value = false
}

function reLayout() {
  graphRef.value?.layout()
}

async function toggleFullscreen() {
  if (!document.fullscreenElement) {
    try {
      await wrapper.value?.requestFullscreen?.()
    } catch {
      /* 浏览器策略拒绝则忽略 */
    }
  } else {
    await document.exitFullscreen()
  }
}

function onFsChange() {
  isFullscreen.value = !!document.fullscreenElement
}
onMounted(() => document.addEventListener('fullscreenchange', onFsChange))
onBeforeUnmount(() => document.removeEventListener('fullscreenchange', onFsChange))

const isolatedCount = computed(() => {
  if (!graph.value) return 0
  const linked = new Set<string>()
  for (const e of graph.value.edges) {
    linked.add(e.source)
    linked.add(e.target)
  }
  return graph.value.nodes.filter((n) => !linked.has(n.id)).length
})

/** 图例只展示当前图谱真实出现的类型，避免「图例有色、画布没有」的错位。 */
const legendTypes = computed(() => {
  const present = new Set(graph.value?.nodes.map((n) => n.page_type) ?? [])
  return TYPE_ORDER.filter((type) => present.has(type))
})

/** 边类型图例：仅展示当前图谱真实出现的边类型。 */
const legendEdges = computed(() => {
  const present = new Set(graph.value?.edges.map((e) => e.type) ?? [])
  return Object.keys(EDGE_LABEL).filter((type) => present.has(type))
})

const focusOptions = computed(() =>
  (graph.value?.nodes ?? []).map((n) => ({
    id: n.id,
    title: n.title,
    kind: n.kind,
  })),
)

// ---------- G6 降级时展示的关系列表 ----------
function edgesForNode(id: string) {
  if (!graph.value) return []
  return graph.value.edges.filter((e) => e.source === id || e.target === id)
}
function titleOf(id: string) {
  return graph.value?.nodes.find((n) => n.id === id)?.title ?? id
}
</script>

<template>
  <div
    ref="wrapper"
    class="relative overflow-hidden rounded-2xl kiwi-card !shadow-soft h-[34rem] lg:h-[44rem] animate-fade-up"
  >
    <!-- 背景点阵：kiwi 色细点铺底，画布之上交互全保留 -->
    <div
      class="absolute inset-0 pointer-events-none bg-[radial-gradient(circle,rgba(120,108,247,0.08)_1px,transparent_1px)]"
      style="background-size: 22px 22px"
    />

    <!-- 接口加载骨架 -->
    <KiwiSkeleton
      v-if="graphLoading && !graph"
      variant="card"
      :cols="1"
      class="h-full !bg-transparent"
    />

    <!-- 错误态 -->
    <KiwiEmpty
      v-else-if="errorMsg"
      icon="alert"
      :title="`图谱加载失败：${errorMsg}`"
      class="absolute inset-0 grid place-items-center"
    >
      <button class="kiwi-btn-primary" @click="load">
        <KiwiIcon name="refresh" :size="14" />
        重试
      </button>
    </KiwiEmpty>

    <!-- 空态 -->
    <KiwiEmpty
      v-else-if="!graph?.nodes.length"
      icon="graph"
      title="当前筛选下没有节点"
      desc="调整筛选条件，或在笔记工作区创建条目 / 编译 Wiki"
    >
      <button class="kiwi-btn-secondary" @click="resetFilters">
        <KiwiIcon name="refresh" :size="14" />
        重置筛选
      </button>
    </KiwiEmpty>

    <!-- G6 可用：画布 -->
    <KiwiGraph
      v-else-if="graphReady"
      ref="graphRef"
      class="absolute inset-0"
      :nodes="graph!.nodes"
      :edges="graph!.edges"
      :storage-key="kbs.currentKbId || ''"
      @node:click="(id: string) => emit('select:node', id)"
      @unavailable="degrade"
      @ready="renderBusy = false"
    />

    <!-- G6 降级：关系列表 -->
    <div v-else class="absolute inset-0 overflow-y-auto p-4">
      <div class="flex items-center gap-2 mb-5">
        <KiwiIcon name="graph" :size="16" class="text-kiwi-500" />
        <p class="text-sm font-medium text-slate-600">图谱可视化组件未就绪，展示文本关系</p>
        <span class="text-[11px] text-slate-400 ml-auto">
          {{ graph!.nodes.length }} 节点 · {{ graph!.edges.length }} 关系
        </span>
      </div>
      <div class="space-y-2.5">
        <div
          v-for="n in graph!.nodes"
          :key="n.id"
          class="flex items-center gap-3 px-4 py-2.5 rounded-xl bg-white/60 border border-slate-200/60 cursor-pointer hover:border-kiwi-300 hover:bg-white/90 transition-all"
          @click="emit('select:node', n.id)"
        >
          <span
            class="w-2.5 h-2.5 rounded-full shrink-0"
            :style="{ background: NODE_COLOR[n.page_type] ?? '#6f72dc' }"
          />
          <span class="flex-1 min-w-0 truncate text-sm text-slate-700 font-medium">{{ n.title }}</span>
          <span
            class="text-[10px] px-1.5 py-[1px] rounded-full shrink-0"
            :class="TYPE_CLASS[n.page_type] ?? 'bg-slate-100 text-slate-500'"
          >
            {{ TYPE_LABEL[n.page_type] ?? n.page_type }}
          </span>
          <span class="text-[11px] text-slate-400 shrink-0 tabular-nums">🔗 {{ n.link_count }}</span>
        </div>
      </div>
      <div v-if="graph!.edges.length" class="mt-5 pt-4 border-t border-slate-100">
        <p class="text-xs font-medium text-slate-500 mb-2 flex items-center gap-1.5">
          <KiwiIcon name="link2" :size="12" />
          引用关系（{{ graph!.edges.length }} 条）
        </p>
        <div class="flex flex-wrap gap-1.5 text-[11px] text-slate-500">
          <span
            v-for="(e, i) in graph!.edges"
            :key="i"
            class="px-2 py-0.5 rounded-full bg-kiwi-50 text-kiwi-700"
          >
            <span class="text-slate-400">{{ EDGE_LABEL[e.type] || '链接' }}：</span>
            {{ titleOf(e.source) }} → {{ titleOf(e.target) }}
          </span>
        </div>
      </div>
    </div>

    <!-- 渲染中遮罩（数据已到，G6 布局未完成） -->
    <div
      v-if="graph && graphReady && renderBusy"
      class="absolute inset-0 z-10 grid place-items-center bg-white/40 backdrop-blur-sm"
    >
      <div
        class="flex items-center gap-2.5 glass-strong rounded-full px-5 py-2.5 text-sm text-slate-500 shadow-soft"
      >
        <KiwiIcon name="loader" :size="16" spin class="text-kiwi-500" />
        布局计算中…
      </div>
    </div>

    <!-- 浮层 overlay：仅画布就绪且有数据时显示 -->
    <template v-if="graphReady && !renderBusy && graph?.nodes.length">
      <!-- 左上：标题徽章 + 统计 -->
      <div class="absolute top-4 left-4 flex items-center gap-2 animate-fade-up pointer-events-none">
        <div class="glass-strong rounded-2xl px-3.5 py-2 flex items-center gap-2.5 shadow-soft">
          <span
            class="w-7 h-7 rounded-lg bg-gradient-to-br from-kiwi-400 to-kiwi-600 grid place-items-center text-white shadow-glow"
          >
            <KiwiIcon name="graph" :size="14" />
          </span>
          <div class="leading-none">
            <p class="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
              知识图谱
              <span
                v-if="graph.performance_mode"
                class="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-600 font-normal"
                title="节点较多，已启用性能模式"
              >
                性能模式
              </span>
            </p>
            <p class="text-[11px] text-slate-400 mt-1 tabular-nums">
              {{ graph.nodes.length }} / {{ graph.total_nodes }} 节点 · {{ graph.edges.length }} 关系
              <span v-if="graph.truncated" class="text-amber-500">· 已裁剪</span>
            </p>
          </div>
        </div>
      </div>

      <!-- 右上：操作组 -->
      <div
        class="absolute top-4 right-4 flex items-center gap-1.5 animate-fade-up"
        style="animation-delay: 60ms"
      >
        <div class="relative">
          <button
            class="h-8 px-2.5 flex items-center gap-1 rounded-xl glass-strong text-slate-500 hover:text-kiwi-700 hover:border-kiwi-200 transition-all active:scale-95"
            title="筛选图谱"
            @click="filterOpen = !filterOpen"
          >
            <KiwiIcon name="filter" :size="14" />
            <span
              v-if="activeFilterCount"
              class="text-[9px] px-1 rounded-full bg-kiwi-500 text-white leading-4"
            >
              {{ activeFilterCount }}
            </span>
          </button>

          <!-- 筛选面板 -->
          <div
            v-if="filterOpen"
            class="absolute right-0 top-10 z-20 w-72 rounded-2xl glass-strong p-4 shadow-lifted animate-scale-in"
          >
            <div class="flex items-center justify-between mb-3">
              <p class="text-xs font-semibold text-slate-700">图谱筛选</p>
              <button class="text-slate-300 hover:text-slate-500" @click="filterOpen = false">
                <KiwiIcon name="close" :size="12" />
              </button>
            </div>

            <p class="text-[10.5px] text-slate-400 mb-1.5">页面类型</p>
            <div class="flex flex-wrap gap-1.5 mb-3">
              <button
                v-for="type in FILTER_TYPES"
                :key="type"
                class="px-2 py-0.5 rounded-full text-[10.5px] border transition-colors"
                :class="
                  draft.types.includes(type)
                    ? 'bg-kiwi-500 text-white border-kiwi-500'
                    : 'bg-white/70 text-slate-500 border-slate-200 hover:border-kiwi-300'
                "
                @click="toggleType(type)"
              >
                {{ TYPE_LABEL[type] }}
              </button>
              <span v-if="!draft.types.length" class="text-[10px] text-slate-300 self-center">
                未选择 = 全部
              </span>
            </div>

            <label class="flex items-center justify-between text-[11px] text-slate-500 mb-2">
              包含笔记节点
              <input v-model="draft.includeNotes" type="checkbox" class="accent-kiwi-500" />
            </label>

            <p class="text-[10.5px] text-slate-400 mb-1.5 mt-3">人工编辑状态</p>
            <select
              v-model="draft.humanOnly"
              class="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[11px] text-slate-600 focus:border-kiwi-400 focus:outline-none"
            >
              <option value="all">全部页面</option>
              <option value="edited">仅人工保护</option>
              <option value="generated">仅编译生成</option>
            </select>

            <p class="text-[10.5px] text-slate-400 mb-1.5 mt-3">聚焦节点（1–3 跳邻域）</p>
            <div class="flex gap-1.5">
              <select
                v-model="draft.focus"
                class="flex-1 min-w-0 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[11px] text-slate-600 focus:border-kiwi-400 focus:outline-none"
              >
                <option value="">不聚焦</option>
                <option v-for="n in focusOptions" :key="n.id" :value="n.id">
                  {{ n.kind === 'note' ? '笔记' : 'Wiki' }}：{{ n.title }}
                </option>
              </select>
              <select
                v-model.number="draft.depth"
                class="w-16 rounded-lg border border-slate-200 bg-white px-1.5 py-1.5 text-[11px] text-slate-600 focus:border-kiwi-400 focus:outline-none"
                :disabled="!draft.focus"
              >
                <option :value="1">1 跳</option>
                <option :value="2">2 跳</option>
                <option :value="3">3 跳</option>
              </select>
            </div>

            <div class="flex justify-end gap-1.5 mt-4">
              <button class="kiwi-btn-ghost !px-2 !py-1 !text-[10.5px]" @click="resetFilters">
                重置
              </button>
              <button class="kiwi-btn-primary !px-3 !py-1 !text-[10.5px]" @click="applyFilters">
                应用
              </button>
            </div>
          </div>
        </div>

        <button
          class="w-8 h-8 grid place-items-center rounded-xl glass-strong text-slate-500 hover:text-kiwi-700 hover:border-kiwi-200 transition-all active:scale-95"
          title="重新布局"
          :disabled="renderBusy"
          @click="reLayout"
        >
          <KiwiIcon name="refresh" :size="15" />
        </button>
        <button
          class="w-8 h-8 grid place-items-center rounded-xl glass-strong text-slate-500 hover:text-kiwi-700 hover:border-kiwi-200 transition-all active:scale-95"
          :title="isFullscreen ? '退出全屏' : '全屏'"
          @click="toggleFullscreen"
        >
          <KiwiIcon :name="isFullscreen ? 'shrink' : 'expand'" :size="15" />
        </button>
      </div>

      <!-- 底部：图例胶囊 -->
      <div
        class="absolute bottom-4 left-1/2 -translate-x-1/2 animate-fade-up"
        style="animation-delay: 120ms"
      >
        <div
          class="flex items-center gap-3.5 px-4 py-2 rounded-full glass-strong shadow-soft pointer-events-none"
        >
          <span v-for="t in legendTypes" :key="t" class="flex items-center gap-1.5">
            <i class="w-2.5 h-2.5 rounded-full shrink-0" :style="{ background: NODE_COLOR[t] }" />
            <span class="text-[11px] text-slate-500">{{ TYPE_LABEL[t] }}</span>
          </span>
          <template v-if="legendEdges.length">
            <span class="h-3 w-px bg-slate-200" />
            <span v-for="t in legendEdges" :key="t" class="flex items-center gap-1.5">
              <i
                class="w-4 shrink-0 border-t-2"
                :style="{
                  borderColor: EDGE_COLOR[t],
                  borderTopStyle: EDGE_DASHED[t] ? 'dashed' : 'solid',
                }"
              />
              <span class="text-[11px] text-slate-500">{{ EDGE_LABEL[t] }}</span>
            </span>
          </template>
        </div>
      </div>

      <!-- 右下：操作提示 -->
      <div
        class="absolute bottom-4 right-4 flex items-center gap-1.5 rounded-full glass-strong px-3 py-1.5 text-[11px] text-slate-400 shadow-soft pointer-events-none animate-fade-up"
        style="animation-delay: 180ms"
      >
        <KiwiIcon name="graph" :size="11" class="text-kiwi-400" />
        拖拽节点固定位置 · 拖拽平移 · 滚轮缩放 · 点击查看
      </div>
    </template>
  </div>
</template>
