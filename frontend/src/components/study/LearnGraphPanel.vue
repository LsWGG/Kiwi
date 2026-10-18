<script setup lang="ts">
// LearnGraphPanel：学习图谱 —— 按掌握度着色，叠加 Wiki 引用与前置依赖边。
import { computed, onMounted, ref } from 'vue'
import { useStudyStore, type LearnGraphNode } from '@/stores/study'
import KiwiGraph from '@/components/graph/KiwiGraph.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'

const emit = defineEmits<{
  (e: 'start-weak'): void
  (e: 'open-wiki', pageId: string): void
}>()

const study = useStudyStore()
const graphRef = ref<any>(null)
const graphAvailable = ref(true)
const selectedId = ref<string | null>(null)
const query = ref('')
const weakOnly = ref(false)

const nodes = computed(() => study.learnGraph?.nodes || [])
const edges = computed(() => study.learnGraph?.edges || [])

const filteredNodes = computed(() => {
  const q = query.value.trim().toLowerCase()
  return nodes.value.filter((n) => {
    if (weakOnly.value && !n.weak) return false
    if (q && !(n.title.toLowerCase().includes(q) || n.slug.toLowerCase().includes(q))) return false
    return true
  })
})

const filteredEdges = computed(() => {
  const ids = new Set(filteredNodes.value.map((n) => n.id))
  return edges.value.filter((e) => ids.has(e.source) && ids.has(e.target))
})

const graphNodes = computed(() =>
  filteredNodes.value.map((n) => ({
    id: n.id,
    kind: 'topic',
    title: n.title,
    page_type: n.page_type,
    link_count: n.link_count,
    mastery: n.mastery,
    weak: n.weak,
    due: n.due,
    content_updated: n.content_updated,
  })),
)

const selected = computed<LearnGraphNode | null>(
  () => nodes.value.find((n) => n.id === selectedId.value) || null,
)

const selectedNeighbors = computed(() => {
  if (!selected.value) return { prerequisites: [] as LearnGraphNode[], dependents: [] as LearnGraphNode[], related: [] as LearnGraphNode[] }
  const byId = new Map(nodes.value.map((n) => [n.id, n]))
  const prereq: LearnGraphNode[] = []
  const dependents: LearnGraphNode[] = []
  const related: LearnGraphNode[] = []
  for (const e of edges.value) {
    if (e.target === selected.value.id) {
      const n = byId.get(e.source)
      if (n) (e.prerequisite ? prereq : related).push(n)
    } else if (e.source === selected.value.id) {
      const n = byId.get(e.target)
      if (n) (e.prerequisite ? dependents : related).push(n)
    }
  }
  return { prerequisites: prereq, dependents, related }
})

const stats = computed(() => {
  const total = nodes.value.length
  const mastered = nodes.value.filter((n) => n.mastery >= 0.7).length
  const weak = nodes.value.filter((n) => n.weak).length
  const avg = total ? nodes.value.reduce((s, n) => s + n.mastery, 0) / total : 0
  return { total, mastered, weak, avg }
})

const coveragePct = computed(() =>
  Math.round((study.learnGraph?.coverage || 0) * 100),
)

const masterySteps = [
  { color: '#e6e8fb', label: '0–20%' },
  { color: '#c9cdf7', label: '20–40%' },
  { color: '#a9aef0', label: '40–60%' },
  { color: '#878de6', label: '60–80%' },
  { color: '#474dcb', label: '80–100%' },
]

function onNodeClick(id: string) {
  selectedId.value = id
}

function pct(v: number) {
  return Math.round((v || 0) * 100)
}

function masteryTone(v: number) {
  if (v >= 0.7) return 'text-emerald-600'
  if (v >= 0.4) return 'text-amber-600'
  return 'text-rose-500'
}

function relayout() {
  graphRef.value?.layout?.()
}

function focusNode(n: LearnGraphNode) {
  selectedId.value = n.id
}

onMounted(() => {
  study.loadLearnGraph()
})
</script>

<template>
  <div class="space-y-4 animate-fade-up">
    <!-- 头部 -->
    <div class="flex items-start justify-between gap-3 flex-wrap">
      <div class="flex items-center gap-2.5">
        <span class="w-9 h-9 rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white grid place-items-center shadow-sm">
          <KiwiIcon name="graph" :size="16" />
        </span>
        <div>
          <h3 class="font-semibold text-slate-800">学习图谱</h3>
          <p class="text-xs text-slate-400">
            {{ stats.total }} 个知识点 · 已掌握 {{ stats.mastered }} · 薄弱 {{ stats.weak }}
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <div class="relative">
          <KiwiIcon name="search" :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            v-model="query"
            class="kiwi-input !py-1.5 !pl-7 !text-xs w-44"
            placeholder="搜索知识点"
          />
        </div>
        <button
          class="kiwi-btn-ghost !text-xs !py-1.5"
          :class="weakOnly ? '!text-rose-600' : ''"
          @click="weakOnly = !weakOnly"
        >
          <KiwiIcon name="target" :size="12" />
          仅薄弱
        </button>
        <button class="kiwi-btn-ghost !p-1.5" title="重新布局" @click="relayout">
          <KiwiIcon name="refresh" :size="14" />
        </button>
      </div>
    </div>

    <KiwiEmpty
      v-if="!study.graphLoading && !nodes.length"
      icon="graph"
      title="还没有可绘制的知识点"
      desc="编译 Wiki 后，知识点会自动同步到学习图谱；开始训练后节点会按掌握度着色"
    />

    <div v-else class="grid lg:grid-cols-[1fr_260px] gap-4">
      <!-- 图 -->
      <div class="min-w-0">
        <div
          class="relative rounded-2xl overflow-hidden border border-slate-200/60 bg-[#0b1024] h-[520px]"
        >
          <KiwiGraph
            v-if="graphAvailable && filteredNodes.length"
            ref="graphRef"
            :nodes="graphNodes"
            :edges="filteredEdges"
            mode="mastery"
            @node:click="onNodeClick"
            @unavailable="graphAvailable = false"
          />
          <div
            v-else-if="!filteredNodes.length"
            class="absolute inset-0 grid place-items-center text-center px-6"
          >
            <div>
              <KiwiIcon name="filter" :size="26" class="text-slate-500 mx-auto mb-2" />
              <p class="text-xs text-slate-400">当前筛选条件下没有知识点</p>
              <button class="text-[11px] text-kiwi-300 mt-2" @click="query = ''; weakOnly = false">
                清除筛选
              </button>
            </div>
          </div>

          <!-- 图例 -->
          <div class="absolute left-3 bottom-3 rounded-xl bg-black/35 backdrop-blur px-3 py-2.5 border border-white/10">
            <p class="text-[10px] text-slate-400 mb-1.5">掌握度</p>
            <div class="flex items-center gap-1">
              <span
                v-for="s in masterySteps"
                :key="s.color"
                class="w-6 h-1.5 rounded-full"
                :style="{ background: s.color }"
              />
            </div>
            <div class="flex justify-between text-[9px] text-slate-500 mt-1">
              <span>0%</span>
              <span>100%</span>
            </div>
            <div class="flex items-center gap-1.5 mt-2">
              <span class="w-2.5 h-2.5 rounded-full border-2 border-rose-400" />
              <span class="text-[9px] text-slate-400">薄弱知识点（红色描边）</span>
            </div>
            <div class="flex items-center gap-1.5 mt-1">
              <span class="w-2.5 h-2.5 rounded-full border-2 border-dashed border-amber-400" />
              <span class="text-[9px] text-slate-400">复习到期（琥珀虚线）</span>
            </div>
          </div>

          <!-- 统计浮层 -->
          <div class="absolute right-3 top-3 rounded-xl bg-black/35 backdrop-blur px-3 py-2 border border-white/10 text-right">
            <p class="text-[10px] text-slate-400">覆盖率</p>
            <p class="text-lg font-bold text-white/90 tabular-nums leading-tight">{{ coveragePct }}%</p>
            <p class="text-[9px] text-slate-500">平均掌握 {{ pct(stats.avg) }}%</p>
          </div>
        </div>

        <!-- G6 不可用：列表兜底 -->
        <div v-if="!graphAvailable" class="rounded-2xl border border-slate-200/70 bg-white/70 p-4 mt-3">
          <p class="text-xs text-slate-400 mb-2.5">图谱渲染不可用，已切换为列表视图</p>
          <div class="grid sm:grid-cols-2 gap-2 max-h-80 overflow-y-auto">
            <button
              v-for="n in filteredNodes"
              :key="n.id"
              class="text-left rounded-xl border border-slate-200/60 px-3 py-2 hover:border-kiwi-300"
              @click="focusNode(n)"
            >
              <div class="flex items-center gap-2">
                <span class="text-xs text-slate-600 flex-1 truncate">{{ n.title }}</span>
                <span class="text-[10px] tabular-nums" :class="masteryTone(n.mastery)">{{ pct(n.mastery) }}%</span>
              </div>
              <p class="text-[10px] text-slate-400 mt-0.5">{{ n.domain || '未分组' }} · {{ n.link_count }} 条关联</p>
            </button>
          </div>
        </div>
      </div>

      <!-- 右侧详情 -->
      <aside class="space-y-3">
        <div class="kiwi-card p-4">
          <template v-if="selected">
            <div class="flex items-start justify-between gap-2 mb-2">
              <p class="text-sm font-semibold text-slate-700 leading-snug">{{ selected.title }}</p>
              <button class="kiwi-btn-ghost !p-1" @click="selectedId = null">
                <KiwiIcon name="close" :size="12" />
              </button>
            </div>
            <div class="flex items-center gap-2 mb-3">
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
                {{ selected.domain || '未分组' }}
              </span>
              <span v-if="selected.weak" class="text-[10px] px-1.5 py-0.5 rounded bg-rose-50 text-rose-600">
                薄弱
              </span>
            </div>
            <div class="mb-1 flex items-center justify-between text-[11px]">
              <span class="text-slate-400">掌握度</span>
              <span class="font-semibold tabular-nums" :class="masteryTone(selected.mastery)">
                {{ pct(selected.mastery) }}%
              </span>
            </div>
            <div class="h-2 rounded-full bg-slate-200/60 overflow-hidden mb-3">
              <div
                class="h-full rounded-full bg-gradient-to-r from-kiwi-300 to-kiwi-600 transition-all duration-500"
                :style="{ width: `${Math.max(2, pct(selected.mastery))}%` }"
              />
            </div>

            <div v-if="selectedNeighbors.prerequisites.length" class="mb-2.5">
              <p class="text-[10px] text-slate-400 mb-1">前置知识</p>
              <div class="flex flex-wrap gap-1">
                <button
                  v-for="n in selectedNeighbors.prerequisites"
                  :key="n.id"
                  class="px-1.5 py-0.5 rounded bg-slate-50 border border-slate-200/70 text-[10px] text-slate-500 hover:border-kiwi-300"
                  @click="focusNode(n)"
                >
                  {{ n.title }}
                </button>
              </div>
            </div>
            <div v-if="selectedNeighbors.dependents.length" class="mb-2.5">
              <p class="text-[10px] text-slate-400 mb-1">后续知识</p>
              <div class="flex flex-wrap gap-1">
                <button
                  v-for="n in selectedNeighbors.dependents"
                  :key="n.id"
                  class="px-1.5 py-0.5 rounded bg-slate-50 border border-slate-200/70 text-[10px] text-slate-500 hover:border-kiwi-300"
                  @click="focusNode(n)"
                >
                  {{ n.title }}
                </button>
              </div>
            </div>
            <div v-if="selectedNeighbors.related.length" class="mb-3">
              <p class="text-[10px] text-slate-400 mb-1">相关引用</p>
              <div class="flex flex-wrap gap-1">
                <button
                  v-for="n in selectedNeighbors.related.slice(0, 8)"
                  :key="n.id"
                  class="px-1.5 py-0.5 rounded bg-slate-50 border border-slate-200/70 text-[10px] text-slate-500 hover:border-kiwi-300"
                  @click="focusNode(n)"
                >
                  {{ n.title }}
                </button>
              </div>
            </div>

            <div class="flex gap-2">
              <button
                v-if="selected.wiki_page_id"
                class="kiwi-btn-secondary !text-xs !py-1.5 flex-1"
                @click="emit('open-wiki', selected.wiki_page_id)"
              >
                <KiwiIcon name="wiki" :size="12" />
                阅读页面
              </button>
              <button
                v-if="selected.weak"
                class="kiwi-btn-primary !text-xs !py-1.5 flex-1"
                @click="emit('start-weak')"
              >
                <KiwiIcon name="target" :size="12" />
                练这个点
              </button>
            </div>
          </template>
          <template v-else>
            <p class="text-xs font-medium text-slate-500 mb-2">知识点概览</p>
            <div class="space-y-2">
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-slate-400">薄弱知识点</span>
                <span class="text-rose-500 font-medium tabular-nums">{{ stats.weak }}</span>
              </div>
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-slate-400">已掌握（≥70%）</span>
                <span class="text-emerald-600 font-medium tabular-nums">{{ stats.mastered }}</span>
              </div>
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-slate-400">平均掌握度</span>
                <span class="text-slate-600 font-medium tabular-nums">{{ pct(stats.avg) }}%</span>
              </div>
            </div>
            <p class="text-[10px] text-slate-300 leading-relaxed mt-3">
              点击节点查看知识点详情；节点颜色越深表示掌握度越高。
            </p>
          </template>
        </div>

        <button
          v-if="stats.weak"
          class="kiwi-card w-full p-3.5 flex items-center gap-2.5 text-left hover:border-kiwi-300 transition-colors"
          @click="emit('start-weak')"
        >
          <span class="w-8 h-8 rounded-lg bg-rose-50 text-rose-500 grid place-items-center shrink-0">
            <KiwiIcon name="target" :size="15" />
          </span>
          <span class="min-w-0">
            <span class="block text-xs font-medium text-slate-700">薄弱点专项训练</span>
            <span class="block text-[10px] text-slate-400 mt-0.5">优先练习掌握度最低的知识点</span>
          </span>
          <KiwiIcon name="arrowRight" :size="14" class="ml-auto text-slate-300" />
        </button>

        <!-- 薄弱列表 -->
        <div v-if="stats.weak" class="kiwi-card p-4">
          <p class="text-[11px] font-medium text-slate-500 mb-2">最需要巩固</p>
          <div class="space-y-1.5 max-h-64 overflow-y-auto pr-1">
            <button
              v-for="n in nodes.filter((x) => x.weak).sort((a, b) => a.mastery - b.mastery).slice(0, 8)"
              :key="n.id"
              class="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50 text-left"
              @click="focusNode(n)"
            >
              <span class="text-[11px] text-slate-600 flex-1 truncate">{{ n.title }}</span>
              <span class="text-[10px] text-rose-500 tabular-nums">{{ pct(n.mastery) }}%</span>
            </button>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>
