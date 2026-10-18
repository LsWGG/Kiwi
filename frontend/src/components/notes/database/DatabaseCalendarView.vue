<script setup lang="ts">
/** 日历视图：按日期字段聚合，支持当月切换与当天新建。 */
import { computed, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { OPTION_COLORS, chipClass } from './colors'
import type { DbField, DbRow, DbView } from '@/stores/noteDatabase'

const props = withDefaults(
  defineProps<{
    fields: DbField[]
    rows: DbRow[]
    view: DbView
    selectionMode?: boolean
    selectedIds?: string[]
    /** 内嵌数据表在笔记阅读模式下只呈现内容 */
    editable?: boolean
  }>(),
  { selectionMode: false, selectedIds: () => [], editable: true },
)

const emit = defineEmits<{
  (e: 'create-row', preset?: Record<string, any>): void
  (e: 'open-row', row: DbRow): void
  (e: 'toggle-select', rowId: string): void
  (e: 'delete-row', row: DbRow): void
}>()

const selectedSet = computed(() => new Set(props.selectedIds))

function onEventClick(row: DbRow) {
  if (!props.editable) return
  if (props.selectionMode) emit('toggle-select', row.id)
  else emit('open-row', row)
}

const dateField = computed(
  () =>
    props.fields.find((f) => f.id === props.view.date_field) ??
    props.fields.find((f) => f.type === 'date') ??
    null,
)
const endField = computed(() => {
  if (!props.view.end_field) return null
  const field = props.fields.find((f) => f.id === props.view.end_field)
  return field?.type === 'date' ? field : null
})
const titleField = computed(
  () =>
    props.fields.find((f) => f.id === props.view.title_field) ??
    props.fields.find((f) => f.type === 'text') ??
    props.fields.find((f) => f.type === 'long_text') ??
    props.fields.find((f) => f.type === 'url') ??
    null,
)

const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth())

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

/**
 * 初次打开日历时定位到最早一条有日期的记录所在月份。
 * 历史数据若都集中在过去（如试运行复盘），默认停在“今天”会看到一张空日历。
 * 用户手动翻月后不再自动跳转。
 */
let monthTouched = false

const datedStarts = computed(() =>
  props.rows
    .map((row) => (dateField.value ? parseDateKey(row.data[dateField.value.id]) : null))
    .filter((key): key is string => !!key)
    .sort(),
)

watch(
  datedStarts,
  (starts) => {
    if (monthTouched || !starts.length) return
    const [y, m] = starts[0].split('-').map(Number)
    year.value = y
    month.value = m - 1
  },
  { immediate: true },
)

function ymd(y: number, m: number, d: number): string {
  return `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

const todayKey = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`

interface DayCell {
  key: string
  day: number
  inMonth: boolean
  today: boolean
}

const days = computed<DayCell[]>(() => {
  const first = new Date(year.value, month.value, 1)
  const offset = (first.getDay() + 6) % 7
  const out: DayCell[] = []
  for (let i = 0; i < 42; i += 1) {
    const cursor = new Date(year.value, month.value, 1 - offset + i)
    const key = ymd(cursor.getFullYear(), cursor.getMonth(), cursor.getDate())
    out.push({
      key,
      day: cursor.getDate(),
      inMonth: cursor.getMonth() === month.value,
      today: key === todayKey,
    })
  }
  return out
})

function parseDateKey(value: unknown): string | null {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null
}

function dayDiff(a: string, b: string): number {
  const [ay, am, ad] = a.split('-').map(Number)
  const [by, bm, bd] = b.split('-').map(Number)
  return Math.round((Date.UTC(ay, am - 1, ad) - Date.UTC(by, bm - 1, bd)) / 86400000)
}

function rowStart(row: DbRow): string | null {
  return dateField.value ? parseDateKey(row.data[dateField.value.id]) : null
}

/** 记录结束日期；未设置或早于开始日期时等同于单日。 */
function rowEnd(row: DbRow, start: string): string {
  if (!endField.value) return start
  const end = parseDateKey(row.data[endField.value.id])
  return end && dayDiff(end, start) > 0 ? end : start
}

const byDate = computed(() => {
  const map = new Map<string, DbRow[]>()
  if (!dateField.value) return map
  for (const row of props.rows) {
    const start = rowStart(row)
    if (!start) continue
    // 跨天记录以横条展示，不再在起始日重复显示条目
    if (rowEnd(row, start) !== start) continue
    const list = map.get(start) ?? []
    list.push(row)
    map.set(start, list)
  }
  return map
})

const undatedCount = computed(
  () => props.rows.filter((row) => !rowStart(row)).length,
)

function rowsOf(key: string): DbRow[] {
  return byDate.value.get(key) ?? []
}

function eventTitle(row: DbRow): string {
  if (!titleField.value) return '未命名'
  const value = row.data[titleField.value.id]
  return value === null || value === undefined || value === '' ? '未命名' : String(value)
}

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

/** 记录自身的语义色：优先取单选字段的选项颜色。 */
function naturalColor(row: DbRow): string | null {
  for (const field of props.fields) {
    if (field.type !== 'select') continue
    const option = field.options?.find((o) => o.id === row.data[field.id])
    if (option?.color) return option.color
  }
  return null
}

/**
 * 逐条记录分配横条颜色：
 * - 颜色跟随数据（记录）而不是整个视图；
 * - 同一天有交集的多条记录自动换色，保证同一天颜色不同；
 * - 视图设置的颜色作为首选色，冲突时按记录稳定轮换调色板。
 */
const rowColors = computed<Map<string, string>>(() => {
  const map = new Map<string, string>()
  if (!dateField.value) return map
  const spans = props.rows
    .map((row) => {
      const start = rowStart(row)
      return start ? { row, start, end: rowEnd(row, start) } : null
    })
    .filter((span): span is { row: DbRow; start: string; end: string } => !!span)
    .sort((a, b) => a.start.localeCompare(b.start) || a.row.id.localeCompare(b.row.id))

  const palette = [...OPTION_COLORS] as string[]
  const placed: { start: string; end: string; color: string }[] = []
  for (const span of spans) {
    const used = new Set(
      placed
        .filter((item) => item.start <= span.end && span.start <= item.end)
        .map((item) => item.color),
    )
    const candidates: string[] = []
    const preferred = props.view.bar_color || naturalColor(span.row)
    if (preferred) candidates.push(preferred)
    const offset = hashString(span.row.id) % palette.length
    for (let i = 0; i < palette.length; i += 1) {
      candidates.push(palette[(offset + i) % palette.length])
    }
    const color = candidates.find((c) => !used.has(c)) ?? palette[offset]
    placed.push({ ...span, color })
    map.set(span.row.id, color)
  }
  return map
})

function eventChipClass(row: DbRow): string {
  return chipClass(rowColors.value.get(row.id))
}

function eventTitleWithRange(row: DbRow): string {
  const start = rowStart(row)
  if (!start) return eventTitle(row)
  const end = rowEnd(row, start)
  return end === start ? `${start} · ${eventTitle(row)}` : `${start} → ${end} · ${eventTitle(row)}`
}

/** 全局泳道：跨周记录在每一周保持同一行，视觉上连续。 */
const rowLanes = computed<Map<string, number>>(() => {
  const map = new Map<string, number>()
  const spans = props.rows
    .map((row) => {
      const start = rowStart(row)
      if (!start) return null
      const end = rowEnd(row, start)
      return end === start
        ? null
        : { row, start: dayNumber(start), end: dayNumber(end) }
    })
    .filter((span): span is { row: DbRow; start: number; end: number } => !!span)
    .sort((a, b) => a.start - b.start || b.end - a.end || a.row.id.localeCompare(b.row.id))

  const laneEnds: number[] = []
  for (const span of spans) {
    let lane = laneEnds.findIndex((last) => last < span.start)
    if (lane < 0) {
      lane = laneEnds.length
      laneEnds.push(0)
    }
    laneEnds[lane] = span.end
    map.set(span.row.id, lane)
  }
  return map
})

const hoveredRowId = ref<string | null>(null)

function dayNumber(key: string): number {
  const [y, m, d] = key.split('-').map(Number)
  return Date.UTC(y, m - 1, d) / 86400000
}

interface RangeSegment {
  row: DbRow
  startIdx: number
  span: number
  lane: number
  continuesLeft: boolean
  continuesRight: boolean
}

interface WeekRow {
  key: string
  days: DayCell[]
  ranges: RangeSegment[]
  bandHeight: number
}

/** 按周分组；跨天记录在每周顶部按泳道生成横条。 */
const weeks = computed<WeekRow[]>(() => {
  const chunks: DayCell[][] = []
  for (let i = 0; i < days.value.length; i += 7) chunks.push(days.value.slice(i, i + 7))
  return chunks.map((weekDays) => {
    const weekStart = weekDays[0].key
    const weekEnd = weekDays[6].key
    const ranges: RangeSegment[] = []
    for (const row of props.rows) {
      const start = rowStart(row)
      if (!start) continue
      const end = rowEnd(row, start)
      if (end === start) continue
      if (start > weekEnd || end < weekStart) continue
      const startIdx = Math.max(0, dayDiff(start, weekStart))
      const endIdx = Math.min(6, dayDiff(end, weekStart))
      ranges.push({
        row,
        startIdx,
        span: endIdx - startIdx + 1,
        lane: rowLanes.value.get(row.id) ?? 0,
        continuesLeft: start < weekStart,
        continuesRight: end > weekEnd,
      })
    }
    ranges.sort(
      (a, b) =>
        a.lane - b.lane ||
        a.startIdx - b.startIdx ||
        b.span - a.span ||
        a.row.id.localeCompare(b.row.id),
    )
    const maxLane = ranges.reduce((max, seg) => Math.max(max, seg.lane), -1)
    return {
      key: weekDays[0].key,
      days: weekDays,
      ranges,
      bandHeight: maxLane >= 0 ? (maxLane + 1) * 22 + 6 : 0,
    }
  })
})

function barStyle(seg: RangeSegment) {
  // 跨周边缘不留内缩，让相邻周的同一根横条首尾相接
  const leftInset = seg.continuesLeft ? 0 : 3
  const rightInset = seg.continuesRight ? 0 : 3
  return {
    left: `calc(${(seg.startIdx / 7) * 100}% + ${leftInset}px)`,
    width: `calc(${(seg.span / 7) * 100}% - ${leftInset + rightInset}px)`,
    top: `${seg.lane * 22 + 3}px`,
    height: '18px',
  }
}

function move(delta: number) {
  monthTouched = true
  const d = new Date(year.value, month.value + delta, 1)
  year.value = d.getFullYear()
  month.value = d.getMonth()
}

function goToday() {
  monthTouched = true
  year.value = now.getFullYear()
  month.value = now.getMonth()
}

function createOn(key: string) {
  if (!props.editable || !dateField.value) return
  emit('create-row', { [dateField.value.id]: key })
}
</script>

<template>
  <div v-if="!dateField" class="flex-1 grid place-items-center">
    <div class="text-center">
      <KiwiIcon name="calendar" :size="26" class="mx-auto text-slate-300" />
      <p class="mt-2 text-[12px] text-slate-400">日历需要一个日期字段</p>
      <p class="mt-0.5 text-[11px] text-slate-300">可在“视图设置”中选择日期字段</p>
    </div>
  </div>

  <div v-else class="flex-1 min-h-0 flex flex-col" :class="{ 'is-readonly': !editable }">
    <div class="shrink-0 flex items-center gap-2 px-3 py-2">
      <span class="text-[13px] font-semibold text-slate-700 tabular-nums">
        {{ year }} 年 {{ month + 1 }} 月
      </span>
      <span v-if="undatedCount > 0" class="text-[10px] text-slate-400">
        · {{ undatedCount }} 条未排期
      </span>
      <div class="flex-1" />
      <button class="cal-nav" title="上个月" @click="move(-1)">
        <KiwiIcon name="chevron" :size="13" class="rotate-90" />
      </button>
      <button class="cal-nav !w-auto px-2 text-[10.5px]" @click="goToday">今天</button>
      <button class="cal-nav" title="下个月" @click="move(1)">
        <KiwiIcon name="chevron" :size="13" class="-rotate-90" />
      </button>
    </div>

    <div class="flex-1 min-h-0 overflow-auto px-3 pb-3">
      <div class="min-w-[720px] rounded-xl border border-slate-200/70 bg-white/50 overflow-hidden">
        <div class="grid grid-cols-7 border-b border-slate-200/70 bg-white/70">
          <div
            v-for="w in WEEKDAYS"
            :key="w"
            class="px-2 py-1.5 text-center text-[10px] font-medium text-slate-400"
          >
            周{{ w }}
          </div>
        </div>

        <div
          v-for="week in weeks"
          :key="week.key"
          class="border-b border-slate-100 last:border-b-0"
        >
          <!-- 跨天记录：顶部横条按周贯穿展示 -->
          <div
            v-if="week.ranges.length"
            class="relative bg-white/40"
            :style="{ height: `${week.bandHeight}px` }"
          >
            <div
              v-for="seg in week.ranges"
              :key="seg.row.id"
              role="button"
              tabindex="0"
              class="cal-range group absolute flex items-center gap-1 truncate rounded-md border px-1.5 text-left text-[10px] leading-[18px] shadow-sm"
              :class="[
                eventChipClass(seg.row),
                seg.continuesLeft ? 'rounded-l-none border-l-0' : '',
                seg.continuesRight ? 'rounded-r-none border-r-0' : '',
                hoveredRowId === seg.row.id ? 'is-linked-hover' : '',
                selectedSet.has(seg.row.id) ? 'ring-2 ring-kiwi-300' : '',
              ]"
              :style="barStyle(seg)"
              :title="eventTitleWithRange(seg.row)"
              @mouseenter="hoveredRowId = seg.row.id"
              @mouseleave="hoveredRowId = null"
              @click.stop="onEventClick(seg.row)"
              @keydown.enter.prevent="onEventClick(seg.row)"
            >
              <input
                v-if="editable && selectionMode"
                type="checkbox"
                class="h-2.5 w-2.5 shrink-0 rounded border-slate-300 text-kiwi-600 focus:ring-kiwi-300"
                :checked="selectedSet.has(seg.row.id)"
                @click.stop
                @change="emit('toggle-select', seg.row.id)"
              />
              <span class="min-w-0 flex-1 truncate">
                <span v-if="seg.continuesLeft" class="opacity-60">…</span>{{ eventTitle(seg.row) }}<span v-if="seg.continuesRight" class="opacity-60">…</span>
              </span>
              <button
                v-if="editable"
                type="button"
                class="hidden h-3.5 w-3.5 shrink-0 place-items-center rounded text-current opacity-50 hover:opacity-100 group-hover:grid"
                title="删除记录"
                @click.stop="emit('delete-row', seg.row)"
              >
                <KiwiIcon name="trash" :size="9" />
              </button>
            </div>
          </div>

          <div class="grid grid-cols-7">
            <div
              v-for="(day, dayIndex) in week.days"
              :key="day.key"
              class="min-h-[96px] p-1.5 transition-colors"
              :class="[
                editable ? 'cursor-pointer hover:bg-kiwi-50/30' : 'cursor-default',
                dayIndex === 6 ? '' : 'border-r border-slate-100',
                day.inMonth ? '' : 'bg-slate-50/50',
                day.today ? 'bg-kiwi-50/50' : '',
              ]"
              @click="createOn(day.key)"
            >
              <div class="flex items-center justify-between">
                <span
                  class="w-5 h-5 grid place-items-center rounded-full text-[10.5px] tabular-nums"
                  :class="[
                    day.today ? 'bg-kiwi-500 text-white font-medium' : day.inMonth ? 'text-slate-500' : 'text-slate-300',
                  ]"
                >
                  {{ day.day }}
                </span>
                <span
                  v-if="rowsOf(day.key).length"
                  class="text-[9px] text-slate-300 tabular-nums"
                >
                  {{ rowsOf(day.key).length }}
                </span>
              </div>
              <div class="mt-1 space-y-0.5">
                <div
                  v-for="row in rowsOf(day.key).slice(0, 3)"
                  :key="row.id"
                  role="button"
                  tabindex="0"
                  class="cal-chip group flex w-full items-center gap-1 rounded border px-1 py-px text-left text-[10px] leading-4"
                  :class="[
                    eventChipClass(row),
                    selectedSet.has(row.id) ? 'ring-2 ring-kiwi-300' : '',
                  ]"
                  :title="eventTitleWithRange(row)"
                  @click.stop="onEventClick(row)"
                  @keydown.enter.prevent="onEventClick(row)"
                >
                  <input
                    v-if="editable && selectionMode"
                    type="checkbox"
                    class="h-2.5 w-2.5 shrink-0 rounded border-slate-300 text-kiwi-600 focus:ring-kiwi-300"
                    :checked="selectedSet.has(row.id)"
                    @click.stop
                    @change="emit('toggle-select', row.id)"
                  />
                  <span class="min-w-0 flex-1 truncate">{{ eventTitle(row) }}</span>
                  <button
                    v-if="editable"
                    type="button"
                    class="hidden h-3 w-3 shrink-0 place-items-center rounded text-current opacity-50 hover:opacity-100 group-hover:grid"
                    title="删除记录"
                    @click.stop="emit('delete-row', row)"
                  >
                    <KiwiIcon name="trash" :size="8" />
                  </button>
                </div>
                <p v-if="rowsOf(day.key).length > 3" class="px-1 text-[9px] text-slate-400">
                  +{{ rowsOf(day.key).length - 3 }} 条
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cal-nav {
  @apply w-6 h-6 grid place-items-center rounded-md text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-600;
}
.cal-range,
.cal-chip {
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease,
    filter 0.15s ease;
}
.cal-range:hover,
.cal-range.is-linked-hover,
.cal-chip:hover {
  transform: translateY(-1px);
  filter: saturate(1.5);
  box-shadow:
    0 0 0 2px #fff,
    0 5px 14px rgb(15 23 42 / 0.2);
}
.cal-range:hover,
.cal-range.is-linked-hover {
  z-index: 20;
}
.is-readonly .cal-range,
.is-readonly .cal-chip {
  cursor: default;
}
.is-readonly .cal-range:hover,
.is-readonly .cal-chip:hover {
  transform: none;
  filter: none;
  box-shadow: none;
}
</style>
