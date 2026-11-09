<script setup lang="ts">
/**
 * 知识库总览：只读聚合视图。
 *
 * 数据来自 `GET /api/kbs/{kb_id}/dashboard`，页面不写任何业务数据；
 * 图表全部用 SVG / CSS 手绘，颜色统一走主题令牌，亮暗主题都能跟随。
 */
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import type { NoteSummary } from '@/stores/notes'

interface DashboardActivity {
  date: string
  count: number
}

interface DashboardDayNote {
  note: NoteSummary
  events: number
}

interface DashboardDay {
  date: string
  total: number
  note_count: number
  notes: DashboardDayNote[]
}

interface DashboardTag {
  name: string
  count: number
}

interface DashboardCounts {
  notes: number
  archived: number
  trash: number
  folders: number
  tags: number
  attachments: number
  wiki: number
  words: number
  by_kind: Record<string, number>
}

interface DashboardStudy {
  due_reviews: number
  attempted_topics: number
  mastered_topics: number
  mastery_coverage: number
  todo_open: number
  todo_done: number
}

interface KbDashboard {
  kb_id: string
  kb_name: string
  description: string
  counts: DashboardCounts
  study: DashboardStudy
  activity: DashboardActivity[]
  tags: DashboardTag[]
  latest: NoteSummary[]
  pinned: NoteSummary[]
  frequent: NoteSummary[]
  generated_at: string
}

const kbs = useKbsStore()

const data = ref<KbDashboard | null>(null)
const loading = ref(false)
const error = ref('')
let requestToken = 0

// ---------- 活动视图与当天明细 ----------
type ActivityView = 'trend' | 'calendar'
const activityView = ref<ActivityView>('trend')
const selectedDay = ref('')
const dayDetail = ref<DashboardDay | null>(null)
const dayLoading = ref(false)
const dayError = ref('')
let dayRequestToken = 0

const KIND_LABEL: Record<string, string> = {
  doc: '文档',
  database: '数据表',
  canvas: '画布',
  import: '导入',
  link: '链接',
  notebook: 'Notebook',
  sheet: '表格',
}
const KIND_ICON: Record<string, string> = {
  doc: 'fileText',
  database: 'table',
  canvas: 'pen',
  import: 'fileImport',
  link: 'link2',
  notebook: 'notebook',
  sheet: 'columns',
}

function kindLabel(kind: string) {
  return KIND_LABEL[kind] || kind
}

function kindIcon(kind: string) {
  return KIND_ICON[kind] || 'note'
}

function compact(value: number): string {
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)} 亿`
  if (value >= 10_000) return `${(value / 10_000).toFixed(1)} 万`
  return value.toLocaleString('zh-CN')
}

function relativeTime(value?: string | null): string {
  if (!value) return ''
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return ''
  const diff = Date.now() - time
  if (diff < 60_000) return '刚刚'
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months} 个月前`
  return `${Math.floor(months / 12)} 年前`
}

async function load() {
  const kbId = kbs.currentKbId
  if (!kbId) {
    data.value = null
    loading.value = false
    return
  }
  const token = ++requestToken
  loading.value = true
  error.value = ''
  try {
    const result = await request<KbDashboard>(`/kbs/${kbId}/dashboard`)
    if (token === requestToken) data.value = result
  } catch (e: any) {
    if (token === requestToken) error.value = e?.message || '加载总览失败'
  } finally {
    if (token === requestToken) loading.value = false
  }
}

watch(() => kbs.currentKbId, () => void load(), { immediate: true })

const counts = computed(() => data.value?.counts ?? null)
const study = computed(() => data.value?.study ?? null)
const generatedLabel = computed(() => {
  if (!data.value) return ''
  return new Date(data.value.generated_at).toLocaleString('zh-CN', { hour12: false })
})

const noteKinds = computed(() => {
  const rows = Object.entries(data.value?.counts.by_kind ?? {})
    .map(([kind, count]) => ({
      kind,
      count,
      label: kindLabel(kind),
      icon: kindIcon(kind),
    }))
    .filter((item) => item.count > 0)
    .sort((a, b) => b.count - a.count)
  return rows
})
const kindMax = computed(() => Math.max(1, ...noteKinds.value.map((item) => item.count)))

const tagRows = computed(() => data.value?.tags ?? [])
const tagMax = computed(() => Math.max(1, ...tagRows.value.map((item) => item.count)))

const activityMap = computed(() => {
  const map = new Map<string, number>()
  for (const item of data.value?.activity ?? []) map.set(item.date, item.count)
  return map
})
const activityTotal = computed(() =>
  (data.value?.activity ?? []).reduce((sum, item) => sum + item.count, 0),
)

function parseDateKey(key: string): Date {
  const [year, month, day] = key.split('-').map(Number)
  return new Date(year, month - 1, day)
}

const activityStats = computed(() => {
  let activeDays = 0
  let peak = 0
  let last7 = 0
  const cutoff = new Date()
  cutoff.setHours(0, 0, 0, 0)
  cutoff.setDate(cutoff.getDate() - 6)
  for (const [key, count] of activityMap.value) {
    if (count > 0) activeDays += 1
    if (count > peak) peak = count
    if (parseDateKey(key).getTime() >= cutoff.getTime()) last7 += count
  }
  return [
    { label: '活跃天数', value: activeDays, hint: '近 26 周' },
    { label: '近 7 天', value: last7, hint: '活动次数' },
    { label: '单日最高', value: peak, hint: '活动次数' },
  ]
})

function dateKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

// ---------- 活动热力图（近 26 周） ----------
const HEATMAP_WEEKS = 26
const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']

interface HeatCell {
  key: string
  count: number
  future: boolean
  level: number
}

const heatmap = computed(() => {
  const map = activityMap.value
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const monday = new Date(today)
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7))
  const first = new Date(monday)
  first.setDate(monday.getDate() - (HEATMAP_WEEKS - 1) * 7)

  const countsList = [...map.values()]
  const max = Math.max(1, ...countsList)
  const toLevel = (count: number) => {
    if (!count) return 0
    const ratio = count / max
    if (ratio >= 0.75) return 4
    if (ratio >= 0.5) return 3
    if (ratio >= 0.25) return 2
    return 1
  }

  const weeks: { label: string; cells: HeatCell[] }[] = []
  let lastMonth = -1
  for (let week = 0; week < HEATMAP_WEEKS; week++) {
    const cells: HeatCell[] = []
    for (let day = 0; day < 7; day++) {
      const current = new Date(first)
      current.setDate(first.getDate() + week * 7 + day)
      const key = dateKey(current)
      const count = map.get(key) ?? 0
      cells.push({
        key,
        count,
        future: current.getTime() > today.getTime(),
        level: toLevel(count),
      })
    }
    const firstOfWeek = new Date(first)
    firstOfWeek.setDate(first.getDate() + week * 7)
    const month = firstOfWeek.getMonth()
    // 只在月份变化的第一列打标签，避免每列都重复。
    const label = month !== lastMonth ? `${month + 1} 月` : ''
    lastMonth = month
    weeks.push({ label, cells })
  }
  return weeks
})

/** 扁平化热力格：改为 CSS Grid 后按周 / 星期定位，格子随卡片宽度自适应。 */
const heatCells = computed(() =>
  heatmap.value.flatMap((week, weekIndex) =>
    week.cells.map((cell, dayIndex) => ({ ...cell, week: weekIndex, day: dayIndex })),
  ),
)

const HEAT_ALPHA = [0, 0.18, 0.36, 0.58, 0.85]
function heatCellStyle(cell: HeatCell) {
  if (cell.future) return { backgroundColor: 'transparent' }
  if (!cell.level) return { backgroundColor: 'rgb(var(--theme-surface-muted))' }
  return { backgroundColor: `rgb(var(--theme-accent) / ${HEAT_ALPHA[cell.level]})` }
}

// ---------- 月历 ----------
const calendarCursor = ref(new Date(new Date().getFullYear(), new Date().getMonth(), 1))
const calendarLabel = computed(
  () => `${calendarCursor.value.getFullYear()} 年 ${calendarCursor.value.getMonth() + 1} 月`,
)

interface CalendarCell {
  day: number
  key: string
  count: number
  today: boolean
}

const calendarCells = computed(() => {
  const cursor = calendarCursor.value
  const year = cursor.getFullYear()
  const month = cursor.getMonth()
  const first = new Date(year, month, 1)
  const days = new Date(year, month + 1, 0).getDate()
  const leading = (first.getDay() + 6) % 7
  const todayKey = dateKey(new Date())
  const cells: (CalendarCell | null)[] = []
  for (let i = 0; i < leading; i++) cells.push(null)
  for (let day = 1; day <= days; day++) {
    const date = new Date(year, month, day)
    const key = dateKey(date)
    cells.push({
      day,
      key,
      count: activityMap.value.get(key) ?? 0,
      today: key === todayKey,
    })
  }
  return cells
})

const calendarStats = computed(() => {
  const cells = calendarCells.value.filter((cell): cell is CalendarCell => cell !== null)
  const activeDays = cells.filter((cell) => cell.count > 0).length
  const total = cells.reduce((sum, cell) => sum + cell.count, 0)
  return { activeDays, total }
})

/** 当前月份有活动的日子，按活动量排序；与日历同处一张卡片，填充右侧留白。 */
const calendarMonthDays = computed(() =>
  calendarCells.value
    .filter((cell): cell is CalendarCell => cell !== null && cell.count > 0)
    .sort((a, b) => b.count - a.count || b.day - a.day),
)
const calendarMonthPeak = computed(() =>
  Math.max(1, ...calendarMonthDays.value.map((cell) => cell.count)),
)
function weekdayLabel(cell: CalendarCell): string {
  return WEEKDAY_LABELS[(parseDateKey(cell.key).getDay() + 6) % 7]
}

const canGoNextMonth = computed(() => {
  const now = new Date()
  const cursor = calendarCursor.value
  return (
    cursor.getFullYear() < now.getFullYear() ||
    (cursor.getFullYear() === now.getFullYear() && cursor.getMonth() < now.getMonth())
  )
})

function shiftMonth(delta: number) {
  if (delta > 0 && !canGoNextMonth.value) return
  calendarCursor.value = new Date(
    calendarCursor.value.getFullYear(),
    calendarCursor.value.getMonth() + delta,
    1,
  )
}

function calendarLevel(count: number): string {
  if (!count) return ''
  if (count >= 8) return 'cal-l4'
  if (count >= 5) return 'cal-l3'
  if (count >= 2) return 'cal-l2'
  return 'cal-l1'
}

// ---------- 单日活动明细 ----------
const selectedDayLabel = computed(() => {
  if (!selectedDay.value) return ''
  return parseDateKey(selectedDay.value).toLocaleDateString('zh-CN', {
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  })
})

const selectedDayCount = computed(() => activityMap.value.get(selectedDay.value) ?? 0)

const peakDay = computed(() => {
  let best: { key: string; count: number } | null = null
  for (const [key, count] of activityMap.value) {
    if (!best || count > best.count) best = { key, count }
  }
  return best
})

const peakDayLabel = computed(() => {
  if (!peakDay.value) return ''
  return parseDateKey(peakDay.value.key).toLocaleDateString('zh-CN', {
    month: 'long',
    day: 'numeric',
  })
})

async function loadDayDetail(day: string) {
  const kbId = kbs.currentKbId
  if (!kbId || !day) return
  const token = ++dayRequestToken
  dayLoading.value = true
  dayError.value = ''
  try {
    const result = await request<DashboardDay>(
      `/kbs/${kbId}/dashboard/activity?date=${encodeURIComponent(day)}`,
    )
    if (token === dayRequestToken) dayDetail.value = result
  } catch (e: any) {
    if (token === dayRequestToken) dayError.value = e?.message || '加载当天活动失败'
  } finally {
    if (token === dayRequestToken) dayLoading.value = false
  }
}

function selectDay(day: string) {
  if (!day) return
  const changed = selectedDay.value !== day
  selectedDay.value = day
  const date = parseDateKey(day)
  // 热力图点选后把日历翻到对应月份，切换视图时不会停在别的月份。
  calendarCursor.value = new Date(date.getFullYear(), date.getMonth(), 1)
  if (changed || !dayDetail.value) void loadDayDetail(day)
}

function clearSelectedDay() {
  dayRequestToken += 1
  selectedDay.value = ''
  dayDetail.value = null
  dayLoading.value = false
  dayError.value = ''
}

function goToday() {
  const now = new Date()
  calendarCursor.value = new Date(now.getFullYear(), now.getMonth(), 1)
  selectDay(dateKey(now))
}

watch(
  () => kbs.currentKbId,
  () => {
    clearSelectedDay()
    activityView.value = 'trend'
  },
)

// ---------- 推荐笔记 ----------
const recommendGroups = computed(() => [
  {
    key: 'latest',
    title: '最新创建',
    icon: 'clock',
    hint: '按创建时间排序',
    notes: data.value?.latest ?? [],
  },
  {
    key: 'frequent',
    title: '常用笔记',
    icon: 'flame',
    hint: '近 90 天更新最频繁',
    notes: data.value?.frequent ?? [],
  },
  {
    key: 'pinned',
    title: '置顶笔记',
    icon: 'pin',
    hint: '手动置顶的快捷入口',
    notes: data.value?.pinned ?? [],
  },
])

// ---------- 快捷操作 ----------
const quickActions = [
  { to: '/notes', icon: 'note', label: '笔记工作区', hint: '写作、整理与检索' },
  { to: '/wiki', icon: 'wiki', label: 'Wiki 知识库', hint: '编译后的结构化知识' },
  { to: '/sources', icon: 'bookOpen', label: '编译任务', hint: '导入资料并生成 Wiki' },
  { to: '/chat', icon: 'chat', label: 'AI 问答', hint: '基于知识库提问' },
  { to: '/learn', icon: 'learn', label: '学习模式', hint: '复习与掌握度训练' },
  { to: '/kbs', icon: 'database', label: '知识库管理', hint: '切换、创建与设置' },
]

// ---------- 指标卡 ----------
const kpiTiles = computed(() => {
  const value = counts.value
  if (!value) return []
  return [
    {
      key: 'words',
      label: '总字数',
      value: compact(value.words),
      hint: '正文按字符统计',
      icon: 'fileText',
    },
    {
      key: 'tags',
      label: '标签',
      value: value.tags.toLocaleString('zh-CN'),
      hint: `${value.folders.toLocaleString('zh-CN')} 个分组`,
      icon: 'hash',
    },
    {
      key: 'attachments',
      label: '附件',
      value: value.attachments.toLocaleString('zh-CN'),
      hint: '图片与文件',
      icon: 'paperclip',
    },
    {
      key: 'wiki',
      label: 'Wiki 页面',
      value: value.wiki.toLocaleString('zh-CN'),
      hint: '结构化知识页',
      icon: 'wiki',
    },
  ]
})

const masteryPercent = computed(() => {
  const value = study.value?.mastery_coverage ?? 0
  return Math.max(0, Math.min(100, Math.round(value * 100)))
})

const todoTotal = computed(() => (study.value?.todo_open ?? 0) + (study.value?.todo_done ?? 0))
const todoDonePercent = computed(() =>
  todoTotal.value ? Math.round(((study.value?.todo_done ?? 0) / todoTotal.value) * 100) : 0,
)

const kindBarWidth = (count: number) => `${Math.max(4, (count / kindMax.value) * 100)}%`
const tagBarWidth = (count: number) => `${Math.max(4, (count / tagMax.value) * 100)}%`
</script>

<template>
  <div class="page-wrap px-4 py-6 sm:px-8">
    <div class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div class="flex min-w-0 items-center gap-3">
        <span class="accent-icon-strong grid h-10 w-10 shrink-0 place-items-center rounded-xl shadow-glow">
          <KiwiIcon name="chart" :size="20" />
        </span>
        <div class="min-w-0">
          <h1 class="text-2xl font-semibold text-slate-800">总览</h1>
          <p class="mt-1 truncate text-sm text-slate-500">
            <template v-if="data">
              {{ data.kb_name }}<template v-if="data.description"> · {{ data.description }}</template>
            </template>
            <template v-else>知识库数据概览与快捷入口</template>
          </p>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span v-if="generatedLabel" class="hidden text-[10px] text-slate-400 md:inline">
          更新于 {{ generatedLabel }}
        </span>
        <button
          class="kiwi-btn-ghost whitespace-nowrap !py-1.5 text-[11.5px]"
          :disabled="loading"
          @click="load"
        >
          <KiwiIcon name="refresh" :size="12" :spin="loading" /> 刷新
        </button>
        <RouterLink to="/notes" class="kiwi-btn-primary whitespace-nowrap !py-1.5 text-[11.5px]">
          <KiwiIcon name="note" :size="12" /> 打开笔记
        </RouterLink>
      </div>
    </div>

    <!-- 首次加载骨架 -->
    <div v-if="!data && loading" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
      <div class="h-32 animate-pulse rounded-2xl glass xl:col-span-2" />
      <div v-for="n in 4" :key="n" class="h-32 animate-pulse rounded-2xl glass" />
      <div class="h-64 animate-pulse rounded-2xl glass sm:col-span-2 xl:col-span-4" />
      <div class="h-64 animate-pulse rounded-2xl glass sm:col-span-2 xl:col-span-2" />
    </div>

    <!-- 加载失败 / 未选择知识库 -->
    <div
      v-else-if="!data"
      class="kiwi-card flex flex-col items-center justify-center gap-3 px-6 py-16 text-center"
    >
      <span class="accent-chip grid h-12 w-12 place-items-center rounded-2xl">
        <KiwiIcon :name="error ? 'alert' : 'database'" :size="22" />
      </span>
      <p class="text-sm font-medium text-slate-700">
        {{ error || '还没有选择知识库' }}
      </p>
      <p class="max-w-md text-[11px] leading-relaxed text-slate-500">
        {{ error ? '请检查后端服务后重试。' : '先去知识库管理选择或创建一个知识库，总览会展示它的数据。' }}
      </p>
      <div class="mt-1 flex items-center gap-2">
        <button v-if="error" class="kiwi-btn-secondary !py-1.5 text-[11.5px]" @click="load">
          <KiwiIcon name="refresh" :size="12" /> 重试
        </button>
        <RouterLink to="/kbs" class="kiwi-btn-primary !py-1.5 text-[11.5px]">
          <KiwiIcon name="database" :size="12" /> 知识库管理
        </RouterLink>
      </div>
    </div>

    <div
      v-else
      class="transition-opacity duration-300"
      :class="loading ? 'pointer-events-none opacity-60' : ''"
    >
      <!-- KPI 行 -->
      <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <div
          class="relative overflow-hidden rounded-2xl border border-slate-200/60 bg-gradient-to-br from-white/95 via-white/85 to-white/75 p-5 shadow-soft backdrop-blur-xl sm:col-span-2"
        >
          <div
            class="accent-blob pointer-events-none absolute -right-10 -top-12 h-40 w-40 rounded-full blur-2xl"
          />
          <div class="relative">
            <p class="text-[10.5px] font-medium uppercase tracking-wide text-slate-400">笔记总数</p>
            <p class="mt-1 text-5xl font-semibold leading-none text-slate-800">
              {{ counts?.notes.toLocaleString('zh-CN') }}
            </p>
            <div class="mt-3 flex flex-wrap items-center gap-1.5">
              <span
                v-for="item in noteKinds.slice(0, 4)"
                :key="item.kind"
                class="inline-flex items-center gap-1 rounded-full bg-white/70 px-2 py-0.5 text-[10px] text-slate-500"
              >
                <KiwiIcon :name="item.icon" :size="10" class="text-slate-400" />
                {{ item.label }} {{ item.count }}
              </span>
            </div>
            <p class="mt-2 text-[10px] text-slate-400">
              归档 {{ counts?.archived }} · 回收站 {{ counts?.trash }} · 分组
              {{ counts?.folders }}
            </p>
          </div>
        </div>

        <div
          v-for="tile in kpiTiles"
          :key="tile.key"
          class="rounded-2xl border border-slate-200/60 bg-white/80 p-4 shadow-soft backdrop-blur-xl"
        >
          <span class="accent-icon grid h-8 w-8 place-items-center rounded-xl">
            <KiwiIcon :name="tile.icon" :size="15" />
          </span>
          <p class="mt-3 text-2xl font-semibold leading-none text-slate-800">{{ tile.value }}</p>
          <p class="mt-1.5 text-[11px] font-medium text-slate-600">{{ tile.label }}</p>
          <p class="mt-0.5 text-[10px] text-slate-400">{{ tile.hint }}</p>
        </div>
      </section>

      <!-- 活动：趋势 / 日历双视图 + 单日明细 -->
      <div class="mt-4 grid gap-4 lg:grid-cols-3">
        <section class="flex flex-col rounded-2xl border border-slate-200/60 bg-white/80 p-4 shadow-soft backdrop-blur-xl lg:col-span-2">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 class="flex items-center gap-1.5 text-[13px] font-semibold text-slate-700"><span class="section-mark" />活动</h2>
              <p class="mt-0.5 text-[10.5px] text-slate-400">
                <template v-if="activityView === 'trend'">
                  近 26 周共 {{ activityTotal.toLocaleString('zh-CN') }} 次活动 · 点击格子查看当天明细
                </template>
                <template v-else>
                  {{ calendarLabel }} · {{ calendarStats.activeDays }} 天有活动，共 {{ calendarStats.total }} 次
                </template>
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-1.5">
              <div class="view-switch flex items-center rounded-lg p-0.5">
                <button
                  type="button"
                  class="view-switch-btn"
                  :class="activityView === 'trend' ? 'is-active' : ''"
                  :aria-pressed="activityView === 'trend'"
                  @click="activityView = 'trend'"
                >
                  趋势
                </button>
                <button
                  type="button"
                  class="view-switch-btn"
                  :class="activityView === 'calendar' ? 'is-active' : ''"
                  :aria-pressed="activityView === 'calendar'"
                  @click="activityView = 'calendar'"
                >
                  日历
                </button>
              </div>
              <template v-if="activityView === 'calendar'">
                <button type="button" class="view-today" @click="goToday">今天</button>
                <button
                  type="button"
                  class="accent-hover grid h-6 w-6 place-items-center rounded-lg text-slate-400 transition-colors"
                  title="上个月"
                  aria-label="上个月"
                  @click="shiftMonth(-1)"
                >
                  <KiwiIcon name="chevronLeft" :size="12" />
                </button>
                <button
                  type="button"
                  class="accent-hover grid h-6 w-6 place-items-center rounded-lg text-slate-400 transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                  title="下个月"
                  aria-label="下个月"
                  :disabled="!canGoNextMonth"
                  @click="shiftMonth(1)"
                >
                  <KiwiIcon name="chevronRight" :size="12" />
                </button>
              </template>
            </div>
          </div>

          <!-- 趋势：近 26 周热力图（格子随卡片宽度自适应，铺满不留空） -->
          <div v-if="activityView === 'trend'" class="mt-3 flex flex-1 flex-col justify-center">
            <div
              class="mx-auto grid w-full max-w-[920px] gap-1"
              :style="{ gridTemplateColumns: 'auto repeat(26, minmax(0, 1fr))' }"
            >
              <span
                v-for="(week, weekIndex) in heatmap"
                :key="`month-${weekIndex}`"
                class="h-3.5 text-[8.5px] leading-[14px] text-slate-400"
                :style="{ gridColumn: weekIndex + 2, gridRow: 1 }"
              >
                {{ week.label }}
              </span>
              <span
                v-for="(label, index) in WEEKDAY_LABELS"
                :key="label"
                class="flex items-center pr-1 text-[8.5px] leading-none text-slate-400"
                :class="index % 2 === 0 ? 'opacity-100' : 'opacity-0'"
                :style="{ gridColumn: 1, gridRow: index + 2 }"
              >
                {{ label }}
              </span>
              <button
                v-for="cell in heatCells"
                :key="cell.key"
                type="button"
                class="heat-cell aspect-square w-full rounded-[3px] transition-transform"
                :class="[
                  cell.future ? 'opacity-30' : 'hover:scale-105',
                  selectedDay === cell.key ? 'is-selected' : '',
                ]"
                :style="[heatCellStyle(cell), { gridColumn: cell.week + 2, gridRow: cell.day + 2 }]"
                :disabled="cell.future"
                :title="cell.future ? '' : `${cell.key} · ${cell.count} 次活动`"
                :aria-label="cell.future ? '' : `${cell.key}，${cell.count} 次活动，点击查看当天笔记`"
                :aria-pressed="selectedDay === cell.key"
                @click="selectDay(cell.key)"
              />
              <div
                class="flex items-center justify-end gap-1 pt-0.5 text-[9.5px] text-slate-400"
                :style="{ gridColumn: '2 / -1', gridRow: 9 }"
              >
                <span>少</span>
                <span
                  v-for="alpha in [0.18, 0.36, 0.58, 0.85]"
                  :key="alpha"
                  class="h-2.5 w-2.5 rounded-[2px]"
                  :style="{ backgroundColor: `rgb(var(--theme-accent) / ${alpha})` }"
                />
                <span>多</span>
              </div>
            </div>
          </div>

          <!-- 日历：按月浏览；右侧按活动量列出本月活跃日，点选后共用右侧当天明细 -->
          <div v-else class="mt-3 grid flex-1 items-start gap-4 lg:grid-cols-[minmax(0,520px)_minmax(0,1fr)]">
            <div class="mx-auto w-full max-w-[520px] lg:mx-0">
              <div class="grid grid-cols-7 gap-1.5 text-center text-[10px] text-slate-400">
                <span v-for="label in WEEKDAY_LABELS" :key="label">{{ label }}</span>
              </div>
              <div class="mt-1.5 grid grid-cols-7 gap-1.5">
                <template v-for="(cell, index) in calendarCells" :key="index">
                  <span v-if="!cell" class="h-11 rounded-xl" />
                  <button
                    v-else
                    type="button"
                    class="cal-cell flex h-11 flex-col items-center justify-center rounded-xl text-[11px] transition-colors"
                    :class="[
                      calendarLevel(cell.count),
                      selectedDay === cell.key
                        ? 'cal-selected'
                        : cell.today
                          ? 'cal-today'
                          : cell.count
                            ? 'text-slate-700'
                            : 'text-slate-400',
                    ]"
                    :title="cell.count ? `${cell.key} · ${cell.count} 次活动` : cell.key"
                    :aria-label="`${cell.key}${cell.count ? `，${cell.count} 次活动` : ''}`"
                    :aria-pressed="selectedDay === cell.key"
                    @click="selectDay(cell.key)"
                  >
                    <span class="leading-none">{{ cell.day }}</span>
                    <span
                      v-if="cell.count"
                      class="mt-1 text-[8px] leading-none tabular-nums"
                      :class="
                        selectedDay === cell.key ? 'text-current opacity-75' : 'text-slate-400'
                      "
                    >
                      {{ cell.count }}
                    </span>
                  </button>
                </template>
              </div>
            </div>

            <div class="min-w-0">
              <div class="flex items-baseline justify-between gap-2 px-1">
                <p class="text-[10.5px] font-medium text-slate-500">本月活跃日</p>
                <p class="text-[9.5px] tabular-nums text-slate-400">
                  {{ calendarStats.activeDays }} 天 · {{ calendarStats.total }} 次
                </p>
              </div>
              <p
                v-if="!calendarMonthDays.length"
                class="mt-6 text-center text-[10.5px] text-slate-400"
              >
                本月还没有活动记录
              </p>
              <div v-else class="mt-1.5 max-h-[220px] space-y-0.5 overflow-y-auto pr-0.5">
                <button
                  v-for="cell in calendarMonthDays"
                  :key="cell.key"
                  type="button"
                  class="month-day-row flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left"
                  :class="selectedDay === cell.key ? 'is-selected' : ''"
                  :title="`${cell.key} · ${cell.count} 次活动`"
                  :aria-pressed="selectedDay === cell.key"
                  @click="selectDay(cell.key)"
                >
                  <span class="w-16 shrink-0 whitespace-nowrap text-[10px] tabular-nums text-slate-500">
                    {{ cell.day }} 日 · 周{{ weekdayLabel(cell) }}
                  </span>
                  <span class="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full background-track">
                    <span
                      class="block h-full rounded-full"
                      :style="{
                        width: `${Math.max(8, Math.round((cell.count / calendarMonthPeak) * 100))}%`,
                        backgroundColor: 'rgb(var(--theme-accent) / 0.55)',
                      }"
                    />
                  </span>
                  <span class="w-10 shrink-0 text-right text-[9.5px] tabular-nums text-slate-400">
                    {{ cell.count }} 次
                  </span>
                </button>
              </div>
            </div>
          </div>

          <p class="mt-auto pt-3 text-[9.5px] text-slate-400">
            <template v-if="activityView === 'trend'">
              统计口径：笔记创建 + 历史版本快照；点击格子查看当天笔记。
            </template>
            <template v-else>格子深浅与数字表示当天活动量；点击日期查看当天笔记。</template>
          </p>
        </section>

        <!-- 活动概览 / 当天明细 -->
        <section class="flex max-h-[360px] min-h-[280px] flex-col rounded-2xl border border-slate-200/60 bg-white/80 p-4 shadow-soft backdrop-blur-xl">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <h2 class="flex items-center gap-1.5 text-[13px] font-semibold text-slate-700">
                <span class="section-mark" />{{ selectedDay ? '当天活动' : '活动概览' }}
              </h2>
              <p class="mt-0.5 truncate text-[10.5px] text-slate-400">
                <template v-if="selectedDay">
                  {{ selectedDayLabel }} · {{ selectedDayCount }} 次活动
                </template>
                <template v-else>点选日期，查看当天新建或编辑过的笔记</template>
              </p>
            </div>
            <button
              v-if="selectedDay"
              type="button"
              class="accent-hover grid h-6 w-6 shrink-0 place-items-center rounded-lg text-slate-400 transition-colors"
              title="关闭当天明细"
              aria-label="关闭当天明细"
              @click="clearSelectedDay"
            >
              <KiwiIcon name="close" :size="12" />
            </button>
          </div>

          <template v-if="selectedDay">
            <div v-if="dayLoading" class="mt-3 space-y-1.5" aria-hidden="true">
              <div
                v-for="row in 3"
                :key="row"
                class="h-10 animate-pulse rounded-xl bg-slate-100/70"
              />
            </div>
            <div
              v-else-if="dayError"
              class="mt-3 rounded-xl border border-slate-200/60 bg-white/60 p-3 text-center"
            >
              <p class="text-[10.5px] text-slate-400">{{ dayError }}</p>
              <button
                type="button"
                class="accent-text mt-1 text-[10.5px] font-medium"
                @click="loadDayDetail(selectedDay)"
              >
                重试
              </button>
            </div>
            <p
              v-else-if="!dayDetail?.notes.length"
              class="mt-6 text-center text-[11px] text-slate-400"
            >
              这一天没有活动记录
            </p>
            <div v-else class="mt-2 min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-0.5">
              <RouterLink
                v-for="item in dayDetail?.notes ?? []"
                :key="item.note.id"
                :to="{ name: 'notes', params: { id: item.note.id } }"
                class="group flex items-center gap-2.5 rounded-xl px-2 py-1.5 transition-colors hover:bg-white/70"
              >
                <span
                  class="row-icon grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-100/80 text-slate-500"
                >
                  <KiwiIcon :name="kindIcon(item.note.kind)" :size="13" />
                </span>
                <span class="min-w-0 flex-1">
                  <span class="row-title block truncate text-[11.5px] font-medium text-slate-700">
                    {{ item.note.title || '无标题' }}
                  </span>
                  <span class="block truncate text-[9.5px] text-slate-400">
                    {{ kindLabel(item.note.kind) }} · {{ relativeTime(item.note.updated_at) }}
                  </span>
                </span>
                <span
                  class="shrink-0 rounded-full bg-slate-100/80 px-1.5 py-0.5 text-[9px] tabular-nums text-slate-500"
                >
                  {{ item.events }} 次
                </span>
              </RouterLink>
              <p
                v-if="dayDetail && dayDetail.note_count > dayDetail.notes.length"
                class="px-2 pt-1 text-[9.5px] text-slate-400"
              >
                共 {{ dayDetail.note_count }} 篇，仅显示活动最多的
                {{ dayDetail.notes.length }} 篇
              </p>
            </div>
          </template>

          <template v-else>
            <div class="mt-3 grid grid-cols-3 gap-2">
              <div
                v-for="stat in activityStats"
                :key="stat.label"
                class="rounded-xl border border-slate-200/60 bg-white/60 px-2 py-2"
              >
                <p class="text-[9px] text-slate-400">{{ stat.label }}</p>
                <p class="mt-0.5 text-[15px] font-semibold leading-none text-slate-800">
                  {{ stat.value }}
                </p>
                <p class="mt-0.5 text-[8.5px] text-slate-400">{{ stat.hint }}</p>
              </div>
            </div>
            <button
              v-if="peakDay && peakDay.count"
              type="button"
              class="mt-2 flex w-full items-center gap-2 rounded-xl border border-slate-200/60 bg-white/60 px-2.5 py-2 text-left transition-colors hover:bg-white/70"
              title="查看最活跃一天的笔记"
              @click="peakDay && selectDay(peakDay.key)"
            >
              <span class="accent-chip grid h-6 w-6 shrink-0 place-items-center rounded-lg">
                <KiwiIcon name="flame" :size="12" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block text-[9px] text-slate-400">最活跃的一天</span>
                <span class="block truncate text-[10.5px] font-medium text-slate-600">
                  {{ peakDayLabel }} · {{ peakDay.count }} 次
                </span>
              </span>
              <KiwiIcon name="chevronRight" :size="11" class="shrink-0 text-slate-400" />
            </button>
            <p class="mt-auto pt-3 text-[9.5px] text-slate-400">
              活跃天数按近 26 周统计；单日最高指一天的创建与版本快照次数。
            </p>
          </template>
        </section>
      </div>

      <!-- 构成 / 标签 / 学习 -->
      <div class="mt-4 grid gap-4 xl:grid-cols-3">
        <section class="rounded-2xl border border-slate-200/60 bg-white/80 p-4 shadow-soft backdrop-blur-xl">
          <div class="flex items-end justify-between gap-2">
            <div>
              <h2 class="flex items-center gap-1.5 text-[13px] font-semibold text-slate-700"><span class="section-mark" />知识构成</h2>
              <p class="mt-0.5 text-[10.5px] text-slate-400">按笔记类型统计，占比按数量排序</p>
            </div>
            <span class="text-[10px] text-slate-400">{{ counts?.notes }} 篇</span>
          </div>
          <div v-if="noteKinds.length" class="mt-3 space-y-2.5">
            <div v-for="item in noteKinds" :key="item.kind">
              <div class="flex items-center gap-2 text-[11px]">
                <span class="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-slate-100/80 text-slate-500">
                  <KiwiIcon :name="item.icon" :size="11" />
                </span>
                <span class="min-w-0 flex-1 truncate text-slate-600">{{ item.label }}</span>
                <span class="tabular-nums text-slate-500">{{ item.count }}</span>
              </div>
              <div class="mt-1 h-2 rounded-r-[4px] bg-slate-100/70">
                <div
                  class="h-full rounded-r-[4px]"
                  :style="{ width: kindBarWidth(item.count), backgroundColor: 'rgb(var(--theme-accent))' }"
                />
              </div>
            </div>
          </div>
          <p v-else class="mt-6 text-center text-[11px] text-slate-400">还没有笔记</p>
        </section>

        <section class="rounded-2xl border border-slate-200/60 bg-white/80 p-4 shadow-soft backdrop-blur-xl">
          <div class="flex items-end justify-between gap-2">
            <div>
              <h2 class="flex items-center gap-1.5 text-[13px] font-semibold text-slate-700"><span class="section-mark" />标签分布</h2>
              <p class="mt-0.5 text-[10.5px] text-slate-400">使用最多的前 10 个标签</p>
            </div>
            <span class="text-[10px] text-slate-400">{{ counts?.tags }} 个</span>
          </div>
          <div v-if="tagRows.length" class="mt-3 space-y-2.5">
            <div v-for="tag in tagRows" :key="tag.name">
              <div class="flex items-center gap-2 text-[11px]">
                <span class="min-w-0 flex-1 truncate text-slate-600"># {{ tag.name }}</span>
                <span class="tabular-nums text-slate-500">{{ tag.count }}</span>
              </div>
              <div class="mt-1 h-2 rounded-r-[4px] bg-slate-100/70">
                <div
                  class="h-full rounded-r-[4px]"
                  :style="{ width: tagBarWidth(tag.count), backgroundColor: 'rgb(var(--theme-accent))' }"
                />
              </div>
            </div>
          </div>
          <p v-else class="mt-6 text-center text-[11px] text-slate-400">还没有标签</p>
        </section>

        <section class="rounded-2xl border border-slate-200/60 bg-white/80 p-4 shadow-soft backdrop-blur-xl">
          <div class="flex items-end justify-between gap-2">
            <div>
              <h2 class="flex items-center gap-1.5 text-[13px] font-semibold text-slate-700"><span class="section-mark" />学习与待办</h2>
              <p class="mt-0.5 text-[10.5px] text-slate-400">复习进度与待办完成情况</p>
            </div>
            <RouterLink to="/learn" class="accent-text text-[10px]">
              进入学习 →
            </RouterLink>
          </div>

          <div class="mt-3 grid grid-cols-2 gap-2">
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2.5">
              <p class="text-[10px] text-slate-400">待复习</p>
              <p class="mt-0.5 text-xl font-semibold leading-none text-slate-800">
                {{ study?.due_reviews ?? 0 }}
              </p>
              <p class="mt-1 text-[9.5px] text-slate-400">
                {{ study?.due_reviews ? '已到复习时间' : '当前没有到期复习' }}
              </p>
            </div>
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2.5">
              <p class="text-[10px] text-slate-400">待办</p>
              <p class="mt-0.5 text-xl font-semibold leading-none text-slate-800">
                {{ study?.todo_open ?? 0 }}
              </p>
              <p class="mt-1 text-[9.5px] text-slate-400">已完成 {{ study?.todo_done ?? 0 }}</p>
            </div>
          </div>

          <div class="mt-3">
            <div class="flex items-center justify-between text-[10px]">
              <span class="text-slate-500">Wiki 掌握度</span>
              <span class="tabular-nums text-slate-500">{{ masteryPercent }}%</span>
            </div>
            <div class="mt-1 h-2 rounded-full bg-slate-100/70">
              <div
                class="h-full rounded-full transition-[width] duration-500"
                :style="{ width: `${masteryPercent}%`, backgroundColor: 'rgb(var(--theme-accent))' }"
              />
            </div>
            <p class="mt-1 text-[9.5px] text-slate-400">
              已掌握 {{ study?.mastered_topics ?? 0 }} / {{ counts?.wiki ?? 0 }} 个主题 ·
              共练习 {{ study?.attempted_topics ?? 0 }} 个
            </p>
          </div>

          <div class="mt-3">
            <div class="flex items-center justify-between text-[10px]">
              <span class="text-slate-500">待办完成率</span>
              <span class="tabular-nums text-slate-500">{{ todoDonePercent }}%</span>
            </div>
            <div class="mt-1 h-2 rounded-full bg-slate-100/70">
              <div
                class="h-full rounded-full transition-[width] duration-500"
                :style="{ width: `${todoDonePercent}%`, backgroundColor: 'rgb(var(--theme-accent))' }"
              />
            </div>
            <p class="mt-1 text-[9.5px] text-slate-400">
              共 {{ todoTotal }} 条 · {{ study?.todo_done ?? 0 }} 条已完成
            </p>
          </div>
        </section>
      </div>

      <!-- 推荐笔记 -->
      <div class="mt-4 grid gap-4 xl:grid-cols-3">
        <section
          v-for="group in recommendGroups"
          :key="group.key"
          class="rounded-2xl border border-slate-200/60 bg-white/80 p-4 shadow-soft backdrop-blur-xl"
        >
          <div class="flex items-center gap-2">
            <span class="accent-chip grid h-7 w-7 place-items-center rounded-lg">
              <KiwiIcon :name="group.icon" :size="13" />
            </span>
            <div class="min-w-0 flex-1">
              <h2 class="text-[12.5px] font-semibold text-slate-700">{{ group.title }}</h2>
              <p class="text-[9.5px] text-slate-400">{{ group.hint }}</p>
            </div>
            <span class="text-[10px] tabular-nums text-slate-400">{{ group.notes.length }}</span>
          </div>

          <div v-if="group.notes.length" class="mt-2 space-y-0.5">
            <RouterLink
              v-for="note in group.notes"
              :key="note.id"
              :to="{ name: 'notes', params: { id: note.id } }"
              class="group flex items-start gap-2.5 rounded-xl px-2 py-2 transition-colors hover:bg-white/70"
            >
              <span
                class="row-icon mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-100/80 text-slate-500"
              >
                <KiwiIcon :name="kindIcon(note.kind)" :size="13" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="row-title block truncate text-[12px] font-medium text-slate-700">
                  {{ note.title || '无标题' }}
                </span>
                <span class="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-400">
                  <span>{{ kindLabel(note.kind) }}</span>
                  <span>·</span>
                  <span>{{ relativeTime(group.key === 'latest' ? note.created_at : note.updated_at) }}</span>
                </span>
              </span>
            </RouterLink>
          </div>
          <p v-else class="mt-6 text-center text-[11px] text-slate-400">
            暂无{{ group.title }}
          </p>
        </section>
      </div>

      <!-- 快捷操作 -->
      <section class="mt-4 rounded-2xl border border-slate-200/60 bg-white/80 p-4 shadow-soft backdrop-blur-xl">
        <div class="flex items-center justify-between gap-2">
          <div>
            <h2 class="flex items-center gap-1.5 text-[13px] font-semibold text-slate-700"><span class="section-mark" />快捷操作</h2>
            <p class="mt-0.5 text-[10.5px] text-slate-400">常用入口，一键直达</p>
          </div>
        </div>
        <div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <RouterLink
            v-for="action in quickActions"
            :key="action.to"
            :to="action.to"
            class="quick-card group flex items-center gap-2.5 rounded-xl border border-slate-200/60 bg-white/65 px-3 py-2.5 transition-all hover:-translate-y-0.5 hover:bg-white/85 hover:shadow-soft"
          >
            <span
              class="row-icon grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100/80 text-slate-500 transition-colors"
            >
              <KiwiIcon :name="action.icon" :size="14" />
            </span>
            <span class="min-w-0">
              <span class="row-title block truncate text-[11.5px] font-medium text-slate-700">{{ action.label }}</span>
              <span class="block truncate text-[9.5px] text-slate-400">{{ action.hint }}</span>
            </span>
          </RouterLink>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* 总览的强调色全部取主题令牌，避免自定义主题下出现硬编码的紫 / 蓝 / 橙。 */
.accent-icon {
  background-image: linear-gradient(
    135deg,
    rgb(var(--theme-accent) / 0.22),
    rgb(var(--theme-accent) / 0.06)
  );
  color: rgb(var(--theme-accent));
  box-shadow: inset 0 0 0 1px rgb(var(--theme-accent) / 0.16);
}
.accent-icon-strong {
  background-image: linear-gradient(
    135deg,
    rgb(var(--theme-accent)),
    rgb(var(--theme-accent) / 0.62)
  );
  color: rgb(var(--theme-accent-foreground));
}
.accent-chip {
  background-color: rgb(var(--theme-accent) / 0.12);
  color: rgb(var(--theme-accent));
}
.accent-blob {
  background-color: rgb(var(--theme-accent) / 0.18);
}
.accent-hover:not(:disabled):hover {
  background-color: rgb(var(--theme-accent) / 0.1);
  color: rgb(var(--theme-accent));
}
.accent-text {
  color: rgb(var(--theme-accent));
}
.accent-text:hover {
  opacity: 0.8;
}
.section-mark {
  display: inline-block;
  width: 3px;
  height: 11px;
  border-radius: 9999px;
  background-color: rgb(var(--theme-accent));
}
.quick-card:hover {
  border-color: rgb(var(--theme-accent) / 0.35);
}
.group:hover .row-icon {
  background-color: rgb(var(--theme-accent) / 0.12);
  color: rgb(var(--theme-accent));
}
.group:hover .row-title {
  color: rgb(var(--theme-accent));
}

/* ---------- 活动视图切换 / 热力格子 / 日历选中态 ---------- */
.view-switch {
  background-color: rgb(var(--theme-surface-muted) / 0.7);
  box-shadow: inset 0 0 0 1px rgb(var(--theme-border) / 0.6);
}
.view-switch-btn {
  padding: 2px 9px;
  border-radius: 6px;
  font-size: 10px;
  line-height: 16px;
  color: rgb(var(--theme-text-subtle));
  transition: color 150ms ease, background-color 150ms ease;
}
.view-switch-btn:hover {
  color: rgb(var(--theme-text-muted));
}
.view-switch-btn.is-active {
  background-color: rgb(var(--theme-accent) / 0.16);
  color: rgb(var(--theme-accent));
  font-weight: 600;
  box-shadow: inset 0 0 0 1px rgb(var(--theme-accent) / 0.3);
}
.view-today {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  line-height: 16px;
  color: rgb(var(--theme-text-muted));
  box-shadow: inset 0 0 0 1px rgb(var(--theme-border) / 0.7);
  transition: color 150ms ease, background-color 150ms ease, box-shadow 150ms ease;
}
.view-today:hover {
  background-color: rgb(var(--theme-accent) / 0.1);
  color: rgb(var(--theme-accent));
  box-shadow: inset 0 0 0 1px rgb(var(--theme-accent) / 0.35);
}
.heat-cell {
  padding: 0;
  border: 0;
  cursor: pointer;
}
.heat-cell:disabled {
  cursor: default;
}
.heat-cell.is-selected {
  outline: 2px solid rgb(var(--theme-accent));
  outline-offset: 0;
}
.heat-cell:focus-visible,
.cal-cell:focus-visible,
.view-switch-btn:focus-visible,
.view-today:focus-visible {
  outline: 2px solid rgb(var(--theme-accent));
  outline-offset: 1px;
}
.cal-cell {
  background-color: rgb(var(--theme-surface-strong) / 0.5);
  border: 1px solid rgb(var(--theme-border) / 0.6);
}
.cal-cell.cal-l1 {
  background-color: rgb(var(--theme-accent) / 0.1);
}
.cal-cell.cal-l2 {
  background-color: rgb(var(--theme-accent) / 0.18);
}
.cal-cell.cal-l3 {
  background-color: rgb(var(--theme-accent) / 0.28);
}
.cal-cell.cal-l4 {
  background-color: rgb(var(--theme-accent) / 0.4);
}
.cal-cell:not(.cal-selected):hover {
  border-color: rgb(var(--theme-accent) / 0.45);
}
.cal-cell.cal-today:not(.cal-selected) {
  color: rgb(var(--theme-accent));
  box-shadow: inset 0 0 0 1.5px rgb(var(--theme-accent) / 0.6);
}
.cal-cell.cal-selected {
  background-color: rgb(var(--theme-accent));
  color: rgb(var(--theme-accent-foreground));
  font-weight: 600;
}
.background-track {
  background-color: rgb(var(--theme-surface-strong) / 0.55);
}
.month-day-row {
  transition: background-color 150ms ease, box-shadow 150ms ease;
}
.month-day-row:hover {
  background-color: rgb(var(--theme-surface-muted) / 0.65);
}
.month-day-row.is-selected {
  background-color: rgb(var(--theme-accent) / 0.12);
  box-shadow: inset 0 0 0 1px rgb(var(--theme-accent) / 0.35);
}
.month-day-row:focus-visible {
  outline: 2px solid rgb(var(--theme-accent));
  outline-offset: 1px;
}
</style>
