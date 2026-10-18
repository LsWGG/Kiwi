/**
 * 日历组件：月视图 + 单日 / 跨天安排。
 *
 * 事件模型与数据表笔记的日历视图一致：每条安排有开始 / 结束日期，
 * 跨天安排按周显示为连续横条。旧版 `{ YYYY-MM-DD: 文本 }` 结构自动升级。
 *
 * Markdown 以 ```kiwi-calendar 围栏 + JSON 持久化，复制与往返不丢数据。
 */
import { Node } from '@tiptap/core'
import { VueNodeViewRenderer } from '@tiptap/vue-3'
import CalendarNodeView from './CalendarNodeView.vue'

const CALENDAR_LANGUAGE = 'kiwi-calendar'
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const MONTH_RE = /^\d{4}-\d{2}$/
const MAX_EVENTS = 500

export const CALENDAR_COLORS = [
  'slate',
  'blue',
  'green',
  'amber',
  'rose',
  'violet',
  'cyan',
  'orange',
] as const

const COLOR_SET = new Set<string>(CALENDAR_COLORS)

export interface CalendarEvent {
  id: string
  title: string
  start: string
  /** 结束日期；与 start 相同表示单日 */
  end: string
  color: string | null
}

export interface CalendarAttrs {
  /** YYYY-MM，空字符串表示当前月 */
  month?: string
  events?: CalendarEvent[]
  title?: string
}

export function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

export function dateKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function fenceFor(value: string): string {
  const runs = value.match(/`+/g) ?? []
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0)
  return '`'.repeat(Math.max(3, longest + 1))
}

export function isValidCalendarDate(value: unknown): value is string {
  if (typeof value !== 'string' || !DATE_RE.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(year, month - 1, day)
  return (
    date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day
  )
}

function dayDiff(a: string, b: string): number {
  const [ay, am, ad] = a.split('-').map(Number)
  const [by, bm, bd] = b.split('-').map(Number)
  return Math.round(
    (Date.UTC(ay, am - 1, ad) - Date.UTC(by, bm - 1, bd)) / 86400000,
  )
}

function dayNumber(key: string): number {
  const [year, month, day] = key.split('-').map(Number)
  return Date.UTC(year, month - 1, day) / 86400000
}

let seq = 0
export function newCalendarEventId(): string {
  seq += 1
  return `e_${Date.now().toString(36)}_${seq}`
}

/** 接受新事件数组与旧版 `{ date: text }` 映射。 */
export function sanitizeEvents(value: unknown): CalendarEvent[] {
  const out: CalendarEvent[] = []
  const used = new Set<string>()

  function push(raw: Record<string, unknown>, index: number) {
    const title = String(raw.title ?? '').trim().slice(0, 500)
    const start = raw.start
    if (!title || !isValidCalendarDate(start)) return
    const endRaw = raw.end
    const end =
      isValidCalendarDate(endRaw) && dayDiff(endRaw, start) > 0 ? endRaw : start
    let id =
      typeof raw.id === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(raw.id)
        ? raw.id
        : `e${index + 1}`
    while (used.has(id)) id = `${id}_${index + 1}`
    used.add(id)
    const color = String(raw.color ?? '')
    out.push({
      id,
      title,
      start,
      end,
      color: COLOR_SET.has(color) ? color : null,
    })
  }

  if (Array.isArray(value)) {
    value.slice(0, MAX_EVENTS).forEach((item, index) => {
      if (item && typeof item === 'object') push(item as Record<string, unknown>, index)
    })
  } else if (value && typeof value === 'object') {
    // 旧格式：一天一条文本
    Object.entries(value as Record<string, unknown>)
      .slice(0, MAX_EVENTS)
      .forEach(([key, text], index) => {
        if (!isValidCalendarDate(key)) return
        push({ id: `e${index + 1}`, title: String(text ?? ''), start: key, end: key }, index)
      })
  }
  return out
}

/** 事件覆盖指定日期。 */
export function eventsOnDate(events: CalendarEvent[], day: string): CalendarEvent[] {
  return events.filter((event) => event.start <= day && day <= event.end)
}

export interface CalendarDayCell {
  key: string
  day: number
  inMonth: boolean
  today: boolean
}

export interface CalendarRangeSegment {
  event: CalendarEvent
  startIdx: number
  span: number
  lane: number
  continuesLeft: boolean
  continuesRight: boolean
}

export interface CalendarWeek {
  key: string
  days: CalendarDayCell[]
  ranges: CalendarRangeSegment[]
  bandHeight: number
}

export interface CalendarMonthModel {
  month: string
  year: number
  monthIndex: number
  days: CalendarDayCell[]
  weeks: CalendarWeek[]
  singleByDate: Map<string, CalendarEvent[]>
  monthEvents: CalendarEvent[]
}

/**
 * 生成月视图数据：单日事件进入日期格，跨天事件按周生成泳道横条。
 * 与数据表笔记 DatabaseCalendarView 的排布规则保持一致。
 */
export function buildCalendarMonth(
  monthValue: string,
  events: CalendarEvent[],
  today: string = dateKey(new Date()),
): CalendarMonthModel {
  const month = MONTH_RE.test(monthValue) ? monthValue : currentMonth()
  const [year, monthNumber] = month.split('-').map(Number)
  // monthIndex 采用 JS Date 的 0 基下标，翻月与标题展示共用同一语义
  const monthIndex = monthNumber - 1
  const first = new Date(year, monthIndex, 1)
  const offset = (first.getDay() + 6) % 7 // 周一开头
  const days: CalendarDayCell[] = Array.from({ length: 42 }, (_, index) => {
    const date = new Date(year, monthIndex, 1 - offset + index)
    const key = dateKey(date)
    return {
      key,
      day: date.getDate(),
      inMonth: date.getMonth() === monthIndex,
      today: key === today,
    }
  })

  const singleByDate = new Map<string, CalendarEvent[]>()
  for (const event of events) {
    if (event.start !== event.end) continue
    const list = singleByDate.get(event.start) ?? []
    list.push(event)
    singleByDate.set(event.start, list)
  }

  const spans = events
    .filter((event) => event.end > event.start)
    .map((event) => ({
      event,
      start: dayNumber(event.start),
      end: dayNumber(event.end),
    }))
    .sort(
      (a, b) =>
        a.start - b.start ||
        b.end - a.end ||
        a.event.id.localeCompare(b.event.id),
    )

  // 全局泳道：同一跨天事件在每一周保持同一行，视觉上连续
  const laneEnds: number[] = []
  const rowLanes = new Map<string, number>()
  for (const span of spans) {
    let lane = laneEnds.findIndex((last) => last < span.start)
    if (lane < 0) {
      lane = laneEnds.length
      laneEnds.push(0)
    }
    laneEnds[lane] = span.end
    rowLanes.set(span.event.id, lane)
  }

  const chunks: CalendarDayCell[][] = []
  for (let index = 0; index < days.length; index += 7) {
    chunks.push(days.slice(index, index + 7))
  }

  const weeks: CalendarWeek[] = chunks.map((weekDays) => {
    const weekStart = weekDays[0].key
    const weekEnd = weekDays[6].key
    const ranges: CalendarRangeSegment[] = []
    for (const event of events) {
      if (event.end <= event.start) continue
      if (event.start > weekEnd || event.end < weekStart) continue
      const startIdx = Math.max(0, dayDiff(event.start, weekStart))
      const endIdx = Math.min(6, dayDiff(event.end, weekStart))
      ranges.push({
        event,
        startIdx,
        span: endIdx - startIdx + 1,
        lane: rowLanes.get(event.id) ?? 0,
        continuesLeft: event.start < weekStart,
        continuesRight: event.end > weekEnd,
      })
    }
    ranges.sort(
      (a, b) =>
        a.lane - b.lane ||
        a.startIdx - b.startIdx ||
        b.span - a.span ||
        a.event.id.localeCompare(b.event.id),
    )
    const maxLane = ranges.reduce((max, segment) => Math.max(max, segment.lane), -1)
    return {
      key: weekDays[0].key,
      days: weekDays,
      ranges,
      bandHeight: maxLane >= 0 ? (maxLane + 1) * 22 + 6 : 0,
    }
  })

  const monthEvents = events
    .filter((event) => event.start.startsWith(`${month}-`) || event.end.startsWith(`${month}-`))
    .sort((a, b) => a.start.localeCompare(b.start) || a.title.localeCompare(b.title))

  return {
    month,
    year,
    monthIndex,
    days,
    weeks,
    singleByDate,
    monthEvents,
  }
}

export function rangeBarStyle(segment: CalendarRangeSegment) {
  const leftInset = segment.continuesLeft ? 0 : 3
  const rightInset = segment.continuesRight ? 0 : 3
  return {
    left: `calc(${(segment.startIdx / 7) * 100}% + ${leftInset}px)`,
    width: `calc(${(segment.span / 7) * 100}% - ${leftInset + rightInset}px)`,
    top: `${segment.lane * 22 + 3}px`,
    height: '18px',
  }
}

export function eventRangeLabel(event: CalendarEvent): string {
  return event.end === event.start
    ? event.start
    : `${event.start} → ${event.end}`
}

function parseCalendar(element: HTMLElement) {
  try {
    return JSON.parse(element.textContent || '{}')
  } catch {
    return {}
  }
}

export const KiwiCalendar = Node.create({
  name: 'kiwiCalendar',
  priority: 1000,
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      month: {
        default: '',
        parseHTML: (element) => {
          const value = String(parseCalendar(element).month || '')
          return MONTH_RE.test(value) ? value : ''
        },
      },
      events: {
        default: [],
        parseHTML: (element) => sanitizeEvents(parseCalendar(element).events),
      },
      title: {
        default: '',
        parseHTML: (element) => String(parseCalendar(element).title || '').slice(0, 200),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'pre[data-kiwi-calendar]' }]
  },

  renderHTML({ node }) {
    return [
      'pre',
      { 'data-kiwi-calendar': 'true', class: 'kiwi-calendar-node' },
      JSON.stringify({
        month: node.attrs.month || '',
        events: sanitizeEvents(node.attrs.events),
        title: node.attrs.title || '',
      }),
    ]
  },

  addNodeView() {
    return VueNodeViewRenderer(CalendarNodeView)
  },

  addCommands() {
    return {
      insertCalendar:
        (attrs: CalendarAttrs = {}) =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: {
              month: MONTH_RE.test(String(attrs.month || ''))
                ? attrs.month
                : currentMonth(),
              events: sanitizeEvents(attrs.events),
              title: attrs.title || '',
            },
          }),
    }
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const json = JSON.stringify({
            month: String(node.attrs.month || ''),
            events: sanitizeEvents(node.attrs.events),
            title: String(node.attrs.title || '').slice(0, 200),
          })
          const fence = fenceFor(json)
          state.write(`${fence}${CALENDAR_LANGUAGE}\n`)
          state.write(json)
          state.ensureNewLine()
          state.write(fence)
          state.closeBlock(node)
        },
        parse: {
          setup(markdownit: any) {
            const rules = markdownit.renderer.rules
            if (rules.fence?.__kiwiCalendar) return
            const originalFence = rules.fence
            const fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
              const token = tokens[idx]
              if (String(token.info ?? '').trim() === CALENDAR_LANGUAGE) {
                return `<pre data-kiwi-calendar="true">${escapeHtml(
                  token.content.trim(),
                )}</pre>\n`
              }
              if (originalFence) return originalFence(tokens, idx, options, env, self)
              return self.renderToken(tokens, idx, options)
            }
            ;(fence as any).__kiwiCalendar = true
            rules.fence = fence
          },
        },
      },
    }
  },
})

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    kiwiCalendar: {
      insertCalendar: (attrs?: CalendarAttrs) => ReturnType
    }
  }
}
