<script setup lang="ts">
/** Markdown 只读渲染（markdown-it + GFM 任务列表 + Kiwi 扩展块）。 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import MarkdownIt from 'markdown-it'
import taskLists from 'markdown-it-task-lists'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  buildCalendarMonth,
  eventRangeLabel,
  isValidCalendarDate,
  rangeBarStyle,
  sanitizeEvents,
  type CalendarEvent,
} from './extensions/calendar'
import { normalizeDataTable, type DataTableModel } from './extensions/dataTableModel'
import type { DbField, DbView } from '@/stores/noteDatabase'

const props = defineProps<{ content: string; citationCount?: number }>()
const emit = defineEmits<{ (e: 'citation-click', n: number): void }>()
const router = useRouter()
const root = ref<HTMLElement | null>(null)

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
  typographer: false,
}).use(taskLists, { enabled: true, label: true })

/**
 * 问答引用标注：把 [1] / [1,2] / [1-3] 渲染成可点击的引用角标。
 * 仅在传入 citationCount 时启用，普通笔记阅读不受影响；
 * 代码、链接文字内部的方括号保持原样。
 */
// 兼容中文模型常用的全角括号：【1】、［1］，以及顿号分隔的 [1、2]。
const CITE_PATTERN =
  /(?:\[|【|［)(\d+(?:\s*[-–]\s*\d+)?(?:\s*[,，、]\s*\d+(?:\s*[-–]\s*\d+)?)*)(?:\]|】|］)/g

function citationNumbers(raw: string): number[] {
  const numbers: number[] = []
  for (const part of raw.split(/[,，、]/)) {
    const bounds = part.split(/[-–]/).map((item) => Number(item.trim()))
    if (bounds.length === 2 && bounds[0] <= bounds[1]) {
      for (let n = bounds[0]; n <= bounds[1] && n - bounds[0] < 20; n += 1) numbers.push(n)
    } else if (bounds.length === 1) {
      numbers.push(bounds[0])
    }
  }
  return numbers
}

function makeTextToken(state: any, content: string, source: any) {
  const token = new state.Token('text', '', 0)
  token.content = content
  token.level = source.level
  return token
}

function makeCiteToken(state: any, n: number, source: any) {
  const token = new state.Token('html_inline', '', 0)
  token.content =
    `<a class="md-cite-ref" href="#kiwi-cite-${n}" data-cite="${n}"` +
    ` title="查看引用 ${n}">[${n}]</a>`
  token.level = source.level
  return token
}

function splitCitations(state: any, token: any, total: number): any[] {
  const value: string = token.content
  const out: any[] = []
  let last = 0
  CITE_PATTERN.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = CITE_PATTERN.exec(value))) {
    const valid = citationNumbers(match[1])
      .filter((n) => Number.isInteger(n) && n >= 1 && n <= total)
      .slice(0, 20)
    if (!valid.length) continue
    if (match.index > last) {
      out.push(makeTextToken(state, value.slice(last, match.index), token))
    }
    valid.forEach((n, index) => {
      if (index) out.push(makeTextToken(state, ',', token))
      out.push(makeCiteToken(state, n, token))
    })
    last = match.index + match[0].length
  }
  if (!out.length) return [token]
  if (last < value.length) out.push(makeTextToken(state, value.slice(last), token))
  return out
}

md.core.ruler.after('inline', 'kiwi_citations', (state: any) => {
  const total = Number(props.citationCount || 0)
  if (total <= 0) return
  for (const block of state.tokens) {
    if (block.type !== 'inline' || !Array.isArray(block.children)) continue
    const out: any[] = []
    let linkDepth = 0
    for (const child of block.children) {
      if (child.type === 'link_open') linkDepth += 1
      else if (child.type === 'link_close') linkDepth = Math.max(0, linkDepth - 1)
      if (child.type !== 'text' || linkDepth > 0) {
        out.push(child)
        continue
      }
      out.push(...splitCitations(state, child, total))
    }
    block.children = out
  }
})

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function escapeAttr(value: string): string {
  return escapeHtml(value).replace(/"/g, '&quot;').replace(/\n/g, '&#10;')
}

const KIND_LABEL: Record<string, string> = {
  doc: '文档',
  import: '导入文档',
  database: '数据表',
  canvas: '画布',
  notebook: 'Notebook',
  link: '链接',
}

function galleryHtml(content: string): string {
  try {
    const data = JSON.parse(content)
    const images = Array.isArray(data.images) ? data.images : []
    if (!images.length) return ''
    const columns = Number(data.columns) >= 2 && Number(data.columns) <= 4 ? Number(data.columns) : 3
    const carousel = data.layout === 'carousel'
    const items = images
      .map((item: any) => {
        const url = escapeAttr(String(item?.url || ''))
        const caption = escapeHtml(String(item?.caption || ''))
        const name = escapeHtml(String(item?.name || '图片'))
        return (
          `<figure class="md-gallery-item">` +
          `<a href="${url}" target="_blank" rel="noopener noreferrer">` +
          `<img src="${url}" alt="${caption || name}" loading="lazy" />` +
          `</a>` +
          (caption ? `<figcaption>${caption}</figcaption>` : '') +
          `</figure>`
        )
      })
      .join('')
    return (
      `<div class="md-gallery${carousel ? ' is-carousel' : ''}"` +
      (carousel ? '' : ` style="grid-template-columns:repeat(${columns},minmax(0,1fr))"`) +
      `>${items}</div>`
    )
  } catch {
    return ''
  }
}

function imageFigureHtml(data: Record<string, unknown>): string {
  const src = String(data.src || '')
  if (!src) return ''
  const alt = escapeHtml(String(data.alt || ''))
  const title = escapeHtml(String(data.title || ''))
  const width = Number(data.width) || 0
  const style = width > 0 ? ` style="width:min(${Math.round(width)}px,100%)"` : ''
  return (
    `<figure class="md-image"${style}>` +
    `<img src="${escapeAttr(src)}" alt="${alt}" loading="lazy" data-zoom="1"` +
    (title ? ` title="${title}"` : '') +
    ` />` +
    (title ? `<figcaption>${title}</figcaption>` : '') +
    `</figure>`
  )
}

function noteCardHtml(content: string): string {
  try {
    const data = JSON.parse(content)
    const id = String(data.noteId || data.id || '')
    if (!id) return ''
    const title = escapeHtml(String(data.title || '未命名笔记'))
    const kind = String(data.kind || 'doc')
    return (
      `<a class="md-note-card" href="/notes/${encodeURIComponent(id)}">` +
      `<span class="md-note-card-icon">▤</span>` +
      `<span class="md-note-card-body">` +
      `<span class="md-note-card-title">${title}</span>` +
      `<span class="md-note-card-kind">${escapeHtml(KIND_LABEL[kind] || '笔记')} · 点击打开</span>` +
      `</span>` +
      `<span class="md-note-card-arrow">→</span>` +
      `</a>`
    )
  } catch {
    return ''
  }
}

function shortRangeLabel(event: CalendarEvent): string {
  const start = event.start.slice(5)
  return event.end === event.start ? start : `${start} → ${event.end.slice(5)}`
}

function toneClass(color: string | null | undefined): string {
  return `md-tone-${color || 'default'}`
}

/** 月历静态 HTML：单日安排进入日期格，跨天安排按周绘制连续横条。 */
function calendarMonthHtml(
  month: string,
  events: CalendarEvent[],
  title: string,
): string {
  const model = buildCalendarMonth(month, events)
  const weekdays = ['一', '二', '三', '四', '五', '六', '日']
    .map((label) => `<span class="md-calendar-weekday">${label}</span>`)
    .join('')
  const weeks = model.weeks
    .map((week) => {
      const band = week.ranges.length
        ? `<div class="md-calendar-band" style="height:${week.bandHeight}px">` +
          week.ranges
            .map((segment) => {
              const style = rangeBarStyle(segment)
              const css =
                `left:${style.left};width:${style.width};top:${style.top};height:${style.height}`
              const classes = [
                'md-calendar-range',
                toneClass(segment.event.color),
                segment.continuesLeft ? 'is-continued-left' : '',
                segment.continuesRight ? 'is-continued-right' : '',
              ]
                .filter(Boolean)
                .join(' ')
              return (
                `<span class="${classes}" style="${escapeAttr(css)}"` +
                ` title="${escapeAttr(eventRangeLabel(segment.event) + ' · ' + segment.event.title)}">` +
                (segment.continuesLeft ? '<i>…</i>' : '') +
                escapeHtml(segment.event.title) +
                (segment.continuesRight ? '<i>…</i>' : '') +
                '</span>'
              )
            })
            .join('') +
          '</div>'
        : ''
      const days = week.days
        .map((day) => {
          const list = model.singleByDate.get(day.key) ?? []
          const chips = list
            .slice(0, 2)
            .map(
              (event) =>
                `<span class="md-calendar-chip ${toneClass(event.color)}" title="${escapeAttr(
                  event.title,
                )}">${escapeHtml(event.title)}</span>`,
            )
            .join('')
          const more =
            list.length > 2
              ? `<span class="md-calendar-more">+${list.length - 2}</span>`
              : ''
          const classes = [
            'md-calendar-day',
            day.inMonth ? '' : 'is-outside',
            day.today ? 'is-today' : '',
          ]
            .filter(Boolean)
            .join(' ')
          return (
            `<span class="${classes}" title="${escapeAttr(day.key)}">` +
            `<span class="md-calendar-daynum">${day.day}</span>` +
            (chips ? `<span class="md-calendar-daychips">${chips}${more}</span>` : '') +
            '</span>'
          )
        })
        .join('')
      return (
        `<div class="md-calendar-week">${band}` +
        `<div class="md-calendar-weekdays">${days}</div></div>`
      )
    })
    .join('')
  const monthEvents = model.monthEvents
    .map(
      (event) =>
        `<span class="md-calendar-event">` +
        `<b class="${toneClass(event.color)}">${escapeHtml(shortRangeLabel(event))}</b>` +
        `<span>${escapeHtml(event.title)}</span></span>`,
    )
    .join('')
  return (
    `<div class="md-calendar">` +
    `<div class="md-calendar-head">` +
    (title ? `<span class="md-calendar-title">${escapeHtml(title)}</span>` : '<span></span>') +
    `<span class="md-calendar-month">${model.year} 年 ${model.monthIndex + 1} 月</span>` +
    '</div>' +
    `<div class="md-calendar-grid">${weekdays}</div>` +
    `<div class="md-calendar-weeks">${weeks}</div>` +
    (monthEvents ? `<div class="md-calendar-events">${monthEvents}</div>` : '') +
    '</div>'
  )
}

function calendarHtml(content: string): string {
  let data: Record<string, any> = {}
  try {
    data = JSON.parse(content) || {}
  } catch {
    return ''
  }
  const monthRaw = String(data.month || '')
  const now = new Date()
  const month = /^\d{4}-\d{2}$/.test(monthRaw)
    ? monthRaw
    : `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  return calendarMonthHtml(
    month,
    sanitizeEvents(data.events),
    String(data.title || ''),
  )
}

// ---------------------------------------------------------------------------
// 内嵌数据表（与数据表笔记同模型）
// ---------------------------------------------------------------------------

function dbFieldText(field: DbField | null | undefined, value: unknown): string {
  if (!field || value === null || value === undefined || value === '') return ''
  if (field.type === 'checkbox') return value ? '是' : '否'
  if (field.type === 'select') {
    return field.options?.find((option) => option.id === value)?.name ?? ''
  }
  if (field.type === 'multi_select') {
    if (!Array.isArray(value)) return ''
    return value
      .map((id) => field.options?.find((option) => option.id === id)?.name)
      .filter(Boolean)
      .join('、')
  }
  if (field.type === 'attachment') {
    if (!Array.isArray(value)) return ''
    return value
      .map((item: any) => String(item?.filename ?? ''))
      .filter(Boolean)
      .join('、')
  }
  if (field.type === 'progress') {
    const number = Number(value)
    return Number.isFinite(number) ? `${Math.max(0, Math.min(100, Math.round(number)))}%` : ''
  }
  return String(value)
}

function dbProgress(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, Math.min(100, Math.round(number))) : 0
}

function dbCellHtml(field: DbField, value: unknown): string {
  if (field.type === 'checkbox') {
    return `<td>${value ? '✓' : '<span class="md-datatable-empty">—</span>'}</td>`
  }
  if (field.type === 'select') {
    const option = field.options?.find((item) => item.id === value)
    return option
      ? `<td><span class="md-db-chip ${toneClass(option.color)}">${escapeHtml(option.name)}</span></td>`
      : '<td><span class="md-datatable-empty">—</span></td>'
  }
  if (field.type === 'multi_select') {
    const names = Array.isArray(value)
      ? value
          .map((id) => field.options?.find((item) => item.id === id))
          .filter((option): option is NonNullable<typeof option> => !!option)
      : []
    return names.length
      ? `<td>${names
          .map(
            (option) =>
              `<span class="md-db-chip ${toneClass(option.color)}">${escapeHtml(option.name)}</span>`,
          )
          .join('')}</td>`
      : '<td><span class="md-datatable-empty">—</span></td>'
  }
  if (field.type === 'progress') {
    if (value === null || value === undefined || value === '') {
      return '<td><span class="md-datatable-empty">—</span></td>'
    }
    const number = dbProgress(value)
    return (
      `<td><span class="md-db-progress${number >= 100 ? ' is-complete' : ''}">` +
      `<span class="md-db-progress-track"><i style="width:${number}%"></i></span>` +
      `<span class="md-db-progress-label">${number}%</span>` +
      '</span></td>'
    )
  }
  const text = dbFieldText(field, value)
  if (!text) return '<td><span class="md-datatable-empty">—</span></td>'
  if (field.type === 'url') {
    return `<td><a href="${escapeAttr(text)}" target="_blank" rel="noopener noreferrer">${escapeHtml(text)}</a></td>`
  }
  if (field.type === 'attachment' && Array.isArray(value)) {
    const links = value
      .map((item: any) =>
        item?.filename && item?.url
          ? `<a href="${escapeAttr(String(item.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(String(item.filename))}</a>`
          : '',
      )
      .filter(Boolean)
      .join('、')
    return `<td>${links || '<span class="md-datatable-empty">—</span>'}</td>`
  }
  return `<td>${escapeHtml(text)}</td>`
}

function dbTableHtml(model: DataTableModel, view: DbView): string {
  const hidden = new Set(view.hidden_fields ?? [])
  const fields = model.fields.filter((field) => !hidden.has(field.id))
  if (!model.rows.length) {
    return '<p class="md-datatable-empty-state">还没有记录</p>'
  }
  const head = fields
    .map((field) => `<th>${escapeHtml(field.name)}</th>`)
    .join('')
  const body = model.rows
    .map(
      (row) =>
        `<tr>${fields.map((field) => dbCellHtml(field, row.data[field.id])).join('')}</tr>`,
    )
    .join('')
  return (
    `<div class="md-datatable-scroll"><table>` +
    `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>` +
    '</table></div>'
  )
}

function dbTextField(model: DataTableModel): DbField | null {
  return (
    model.fields.find((field) => field.type === 'text') ??
    model.fields.find((field) => field.type === 'long_text') ??
    model.fields.find((field) => field.type === 'url') ??
    null
  )
}

function dbKanbanHtml(model: DataTableModel, view: DbView): string {
  const group =
    model.fields.find((field) => field.id === view.group_field && field.type === 'select') ??
    model.fields.find((field) => field.type === 'select')
  if (!group) return dbTableHtml(model, { ...view, type: 'table' })
  const titleField = dbTextField(model)
  const columns = [
    ...(group.options ?? []).map((option) => ({
      id: option.id as string | null,
      name: option.name,
      color: option.color,
    })),
    { id: null as string | null, name: '未分组', color: 'slate' },
  ]
  return (
    `<div class="md-db-kanban">` +
    columns
      .map((column) => {
        const rows = model.rows.filter((row) =>
          column.id ? row.data[group.id] === column.id : !row.data[group.id],
        )
        const cards = rows
          .map((row) => {
            const title = dbFieldText(titleField, row.data[titleField?.id ?? '']) || '未命名'
            const previews = model.fields
              .filter(
                (field) =>
                  field.id !== group.id &&
                  field.id !== titleField?.id &&
                  field.type !== 'checkbox' &&
                  field.type !== 'attachment',
              )
              .map((field) => dbFieldText(field, row.data[field.id]))
              .filter(Boolean)
              .slice(0, 2)
            return (
              `<div class="md-db-kanban-card">` +
              `<p>${escapeHtml(title)}</p>` +
              (previews.length
                ? `<div class="md-db-kanban-meta">${previews
                    .map((text) => `<span>${escapeHtml(text)}</span>`)
                    .join('')}</div>`
                : '') +
              '</div>'
            )
          })
          .join('')
        return (
          `<div class="md-db-kanban-col">` +
          `<div class="md-db-kanban-head"><i class="${toneClass(column.color)}"></i>` +
          `<span>${escapeHtml(column.name)}</span><em>${rows.length}</em></div>` +
          (cards || '<p class="md-db-empty">暂无记录</p>') +
          '</div>'
        )
      })
      .join('') +
    '</div>'
  )
}

function dbGalleryHtml(model: DataTableModel, view: DbView): string {
  if (!model.rows.length) {
    return '<p class="md-datatable-empty-state">还没有记录</p>'
  }
  const titleField =
    model.fields.find((field) => field.id === view.title_field) ?? dbTextField(model)
  const coverField = model.fields.find((field) => field.id === view.cover_field)
  const selectFields = model.fields.filter((field) => field.type === 'select')
  return (
    `<div class="md-db-gallery">` +
    model.rows
      .map((row) => {
        const title = dbFieldText(titleField, row.data[titleField?.id ?? '']) || '未命名'
        const coverRaw = coverField ? row.data[coverField.id] : ''
        const cover =
          typeof coverRaw === 'string' && /^https?:\/\//i.test(coverRaw)
            ? `<img src="${escapeAttr(coverRaw)}" alt="" loading="lazy" />`
            : ''
        const chips = selectFields
          .map((field) => {
            const option = field.options?.find(
              (item) => item.id === row.data[field.id],
            )
            return option
              ? `<span class="md-db-chip ${toneClass(option.color)}">${escapeHtml(option.name)}</span>`
              : ''
          })
          .filter(Boolean)
          .join('')
        const date = model.fields.find(
          (field) => field.type === 'date' && row.data[field.id],
        )
        return (
          `<div class="md-db-gallery-card">` +
          (cover || '<div class="md-db-gallery-cover"></div>') +
          `<div class="md-db-gallery-body"><p>${escapeHtml(title)}</p>` +
          (chips || date
            ? `<div class="md-db-gallery-meta">${chips}${
                date ? `<span>${escapeHtml(String(row.data[date.id]))}</span>` : ''
              }</div>`
            : '') +
          '</div></div>'
        )
      })
      .join('') +
    '</div>'
  )
}

function dbCalendarHtml(model: DataTableModel, view: DbView): string {
  const dateField =
    model.fields.find((field) => field.id === view.date_field && field.type === 'date') ??
    model.fields.find((field) => field.type === 'date')
  if (!dateField) return dbTableHtml(model, { ...view, type: 'table' })
  const endField = model.fields.find(
    (field) => field.id === view.end_field && field.type === 'date',
  )
  const titleField =
    model.fields.find((field) => field.id === view.title_field) ?? dbTextField(model)
  const events: CalendarEvent[] = model.rows
    .map((row) => {
      const start = String(row.data[dateField.id] ?? '')
      if (!isValidCalendarDate(start)) return null
      const endRaw = endField ? String(row.data[endField.id] ?? '') : ''
      const end =
        endField && isValidCalendarDate(endRaw) && endRaw > start ? endRaw : start
      return {
        id: row.id,
        title: dbFieldText(titleField, row.data[titleField?.id ?? '']) || '未命名记录',
        start,
        end,
        color: (view.bar_color as string) || null,
      }
    })
    .filter((event): event is CalendarEvent => !!event)
  const now = new Date()
  const month = events.length
    ? events.map((event) => event.start).sort()[0].slice(0, 7)
    : `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  return calendarMonthHtml(month, events, '')
}

function dataTableHtml(content: string): string {
  let data: Record<string, any> = {}
  try {
    data = JSON.parse(content) || {}
  } catch {
    return ''
  }
  const model = normalizeDataTable(data)
  const view =
    model.views.find((item) => item.id === model.view) ?? model.views[0]
  let body = ''
  if (view?.type === 'kanban') body = dbKanbanHtml(model, view)
  else if (view?.type === 'gallery') body = dbGalleryHtml(model, view)
  else if (view?.type === 'calendar') body = dbCalendarHtml(model, view)
  else if (view) body = dbTableHtml(model, view)
  const title = escapeHtml(model.title)
  return (
    `<figure class="md-datatable">` +
    (title ? `<figcaption>${title}</figcaption>` : '') +
    body +
    '</figure>'
  )
}

function taskProgressCardHtml(content: string): string {
  let data: Record<string, any> = {}
  try {
    data = JSON.parse(content) || {}
  } catch {
    data = {}
  }
  const label = escapeHtml(String(data.label || '待办进度').slice(0, 80))
  const color = ['indigo', 'violet', 'green', 'blue', 'amber', 'rose', 'slate'].includes(
    String(data.color),
  )
    ? String(data.color)
    : 'indigo'
  const bind = ['auto', 'next', 'prev'].includes(String(data.bind))
    ? String(data.bind)
    : 'auto'
  return (
    `<div class="kiwi-task-progress-card tone-${color}" data-kiwi-task-progress="true"` +
    ` data-label="${label}" data-bind="${bind}"` +
    ` data-show-count="${data.showCount !== false}" data-show-percent="${data.showPercent !== false}">` +
    `<div class="kiwi-task-progress-head">` +
    `<span class="kiwi-task-progress-badge">✓</span>` +
    `<span class="kiwi-task-progress-label">${label}</span>` +
    `<span class="kiwi-task-progress-meta" data-progress-meta></span>` +
    `<span class="kiwi-task-progress-spacer"></span>` +
    `</div>` +
    `<div class="kiwi-task-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100">` +
    `<i class="kiwi-task-progress-fill" data-progress-fill></i>` +
    `</div>` +
    `<p class="kiwi-task-progress-empty" data-progress-empty hidden>未找到附近的任务清单</p>` +
    `</div>`
  )
}

/** 普通 Markdown 图片：统一输出为可点击放大的 figure，图注取 title。 */
md.renderer.rules.image = (tokens, idx, options, _env, self) => {
  const token = tokens[idx]
  const src = token.attrGet('src') || ''
  if (!src) return ''
  return imageFigureHtml({
    src,
    alt: token.content || '',
    title: token.attrGet('title') || '',
    width: Number(token.attrGet('width')) || 0,
  })
}

const defaultFence =
  md.renderer.rules.fence ??
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.fence = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const lang = String(token.info ?? '').trim()
  const body = token.content.trim()
  if (lang === 'kiwi-task-progress') {
    return `${taskProgressCardHtml(body)}\n`
  }
  if (lang === 'kiwi-math') {
    return `<div class="md-formula" data-formula="${escapeAttr(body)}"></div>\n`
  }
  if (lang === 'mermaid') {
    return (
      `<div class="md-mermaid" data-mermaid="${escapeAttr(body)}">` +
      `<pre class="md-mermaid-source">${escapeHtml(body)}</pre>` +
      `</div>\n`
    )
  }
  if (lang === 'kiwi-gallery') {
    return `${galleryHtml(body)}\n`
  }
  if (lang === 'kiwi-image') {
    try {
      return `${imageFigureHtml(JSON.parse(body))}\n`
    } catch {
      return `<pre>${escapeHtml(body)}</pre>\n`
    }
  }
  if (lang === 'kiwi-note') {
    return `${noteCardHtml(body)}\n`
  }
  if (lang === 'kiwi-calendar') {
    return `${calendarHtml(body)}\n`
  }
  if (lang === 'kiwi-datatable') {
    return `${dataTableHtml(body)}\n`
  }
  return defaultFence(tokens, idx, options, env, self)
}

const defaultLinkOpen =
  md.renderer.rules.link_open ??
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const href = tokens[idx].attrGet('href') || ''
  // 待办收件箱的来源链接：带 ?note= 时直接还原为来源笔记的站内地址。
  if (href.startsWith('kiwi://todo/')) {
    const noteId = /[?&]note=([0-9a-fA-F-]{36})/.exec(href)?.[1]
    if (noteId) {
      tokens[idx].attrSet('href', `/notes/${noteId}`)
      tokens[idx].attrSet('class', 'md-todo-source')
    }
    return defaultLinkOpen(tokens, idx, options, env, self)
  }
  // @ 提及在 Markdown 里是 kiwi:// 自定义协议，阅读态要还原成站内 SPA 链接。
  if (href.startsWith('kiwi://note/') || href.startsWith('kiwi://wiki/')) {
    const target = href.startsWith('kiwi://wiki/') ? 'wiki' : 'note'
    const prefix = target === 'wiki' ? 'kiwi://wiki/' : 'kiwi://note/'
    const id = href.slice(prefix.length).split('?')[0]
    tokens[idx].attrSet('href', target === 'wiki' ? `/wiki/${id}` : `/notes/${id}`)
    tokens[idx].attrSet('class', 'md-mention')
    tokens[idx].attrSet('data-type', 'mention')
    tokens[idx].attrSet('data-target', target)
    tokens[idx].attrSet('data-id', id)
    return defaultLinkOpen(tokens, idx, options, env, self)
  }
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

const html = computed(() => {
  // 引用数量变化时也要重渲染（引用事件可能先于最后一个文本 chunk 到达）。
  void props.citationCount
  return md.render(props.content || '')
})

// ---------- 特殊块的 DOM 增强 ----------
/**
 * 待办进度块：静态 Markdown 里无法直接拿到 ProseMirror 文档，
 * 因此按 DOM 顺序绑定「下方 / 上方 / 最近的」任务清单并计算完成度。
 */
function decorateTaskProgressComponents(el: HTMLElement) {
  const cards = Array.from(
    el.querySelectorAll<HTMLElement>('[data-kiwi-task-progress]'),
  )
  if (!cards.length) return
  const lists = Array.from(el.querySelectorAll<HTMLElement>('ul.contains-task-list'))

  for (const card of cards) {
    const bind = card.dataset.bind || 'auto'
    const after = lists.find(
      (list) => card.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING,
    )
    const before = lists.filter(
      (list) => card.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_PRECEDING,
    )
    let list: HTMLElement | undefined
    if (bind === 'prev') list = before[before.length - 1]
    else if (bind === 'next') list = after
    else list = after ?? before[before.length - 1]

    const meta = card.querySelector<HTMLElement>('[data-progress-meta]')
    const fill = card.querySelector<HTMLElement>('[data-progress-fill]')
    const empty = card.querySelector<HTMLElement>('[data-progress-empty]')

    if (!list) {
      card.classList.add('is-empty')
      if (empty) empty.hidden = false
      if (meta) meta.textContent = '未找到任务清单'
      if (fill) fill.style.width = '0%'
      card.dataset.taskDone = '0'
      card.dataset.taskTotal = '0'
      card.dataset.taskPercent = '0'
      continue
    }

    const items = Array.from(list.children).filter((child) =>
      child.classList.contains('task-list-item'),
    )
    const done = items.filter((item) =>
      item.querySelector('input[type="checkbox"]')?.hasAttribute('checked'),
    ).length
    const total = items.length
    const percent = total ? Math.round((done / total) * 100) : 0

    card.classList.remove('is-empty')
    if (empty) empty.hidden = true
    if (meta) {
      const parts: string[] = []
      if (card.dataset.showCount !== 'false') parts.push(`${done} / ${total}`)
      if (card.dataset.showPercent !== 'false') parts.push(`${percent}%`)
      meta.textContent = parts.join(' · ') || `${percent}%`
    }
    if (fill) fill.style.width = `${percent}%`
    card.dataset.taskDone = String(done)
    card.dataset.taskTotal = String(total)
    card.dataset.taskPercent = String(percent)
    card.querySelector('.kiwi-task-progress-track')?.setAttribute(
      'aria-valuenow',
      String(percent),
    )
  }
}

function decorateDates(el: HTMLElement) {
  const walker = el.ownerDocument.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  while (walker.nextNode()) {
    const text = walker.currentNode as Text
    if (text.parentElement?.closest('pre, code, a')) continue
    if ((text.data || '').includes('📅')) nodes.push(text)
  }
  const re = /📅\s*(\d{4}-\d{2}-\d{2})/g
  nodes.forEach((text) => {
    const value = text.data
    re.lastIndex = 0
    let match: RegExpExecArray | null
    let last = 0
    let fragment: DocumentFragment | null = null
    while ((match = re.exec(value))) {
      if (!fragment) fragment = document.createDocumentFragment()
      if (match.index > last) {
        fragment.appendChild(document.createTextNode(value.slice(last, match.index)))
      }
      const chip = document.createElement('span')
      chip.className = 'md-date-chip'
      chip.textContent = `📅 ${match[1]}`
      fragment.appendChild(chip)
      last = match.index + match[0].length
    }
    if (!fragment) return
    if (last < value.length) fragment.appendChild(document.createTextNode(value.slice(last)))
    text.replaceWith(fragment)
  })
}

function decorateColumns(el: HTMLElement) {
  el.querySelectorAll('blockquote').forEach((quote) => {
    const first = quote.firstElementChild
    if (!first || first.tagName !== 'P') return
    if ((first.textContent || '').trim() !== '[!COLUMNS]') return
    const wrap = document.createElement('div')
    const columns: HTMLElement[] = []
    let current: HTMLElement | null = null
    Array.from(quote.children)
      .slice(1)
      .forEach((child) => {
        const isDivider =
          child.tagName === 'P' && (child.textContent || '').trim() === '[!COLUMN]'
        if (isDivider) {
          current = document.createElement('div')
          current.className = 'md-column'
          columns.push(current)
          return
        }
        if (!current) {
          current = document.createElement('div')
          current.className = 'md-column'
          columns.push(current)
        }
        current.appendChild(child)
      })
    wrap.className = 'md-columns'
    wrap.style.gridTemplateColumns = `repeat(${Math.max(2, columns.length)},minmax(0,1fr))`
    columns.forEach((column) => wrap.appendChild(column))
    quote.replaceWith(wrap)
  })
}

function decorateCallouts(el: HTMLElement) {
  el.querySelectorAll('blockquote').forEach((quote) => {
    const first = quote.firstElementChild
    if (!first || first.tagName !== 'P') return
    const text = (first.textContent || '').trim()
    const tip = text.match(/^\[!TIP\]\s*(.*)$/)
    if (tip) {
      const box = document.createElement('div')
      box.className = 'md-callout'
      const icon = document.createElement('span')
      icon.className = 'md-callout-icon'
      icon.textContent = tip[1].trim() || '💡'
      const body = document.createElement('div')
      body.className = 'md-callout-body'
      first.remove()
      while (quote.firstChild) body.appendChild(quote.firstChild)
      box.append(icon, body)
      quote.replaceWith(box)
      return
    }
    const detail = text.match(/^\[!DETAILS\]([+-])?\s*([\s\S]*)$/)
    if (detail) {
      const details = document.createElement('details')
      details.className = 'md-details'
      if (detail[1] !== '-') details.setAttribute('open', '')
      const summary = document.createElement('summary')
      summary.textContent = (detail[2] || '').trim() || '折叠内容'
      const content = document.createElement('div')
      content.className = 'md-details-body'
      first.remove()
      while (quote.firstChild) content.appendChild(quote.firstChild)
      details.append(summary, content)
      quote.replaceWith(details)
    }
  })
}

function renderFormulas(el: HTMLElement) {
  el.querySelectorAll<HTMLElement>('[data-formula]').forEach((node) => {
    const latex = node.dataset.formula || ''
    if (!latex) return
    try {
      katex.render(latex, node, {
        displayMode: true,
        throwOnError: false,
        strict: false,
        trust: false,
      })
    } catch {
      node.textContent = latex
      node.classList.add('is-error')
    }
  })
}

let mermaidApi: any = null
async function getMermaid() {
  if (!mermaidApi) {
    const mod = await import('mermaid')
    mermaidApi = mod.default ?? mod
  }
  return mermaidApi
}

async function renderMermaids(el: HTMLElement) {
  const nodes = Array.from(el.querySelectorAll<HTMLElement>('[data-mermaid]'))
  if (!nodes.length) return
  const mermaid = await getMermaid()
  const dark =
    document.documentElement.classList.contains('dark') ||
    document.body.classList.contains('dark')
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    theme: dark ? 'dark' : 'default',
    flowchart: { htmlLabels: false },
  })
  for (const node of nodes) {
    const code = node.dataset.mermaid || ''
    if (!code || !node.isConnected) continue
    try {
      const id = `kiwi-md-mermaid-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      const result = await mermaid.render(id, code)
      if (!node.isConnected) continue
      node.innerHTML = result.svg
      node.classList.add('is-rendered')
    } catch {
      node.classList.add('is-error')
    }
  }
}

let decorateTimer: number | undefined
let renderSeq = 0
async function decorate() {
  await nextTick()
  const el = root.value
  if (!el) return
  const seq = ++renderSeq
  decorateColumns(el)
  decorateCallouts(el)
  decorateTaskProgressComponents(el)
  decorateDates(el)
  renderFormulas(el)
  try {
    await renderMermaids(el)
  } catch {
    /* 图表渲染失败时保留源码 */
  }
  if (seq !== renderSeq) return
}

watch(
  () => props.content,
  () => {
    window.clearTimeout(decorateTimer)
    decorateTimer = window.setTimeout(() => void decorate(), 180)
  },
  { immediate: true },
)

onBeforeUnmount(() => window.clearTimeout(decorateTimer))

// ---------- 图片灯箱：点击任意正文图片放大，可下载 ----------
const zoomSrc = ref('')
const zoomCaption = ref('')

function openImageZoom(img: HTMLImageElement) {
  const src = img.getAttribute('src') || ''
  if (!src) return
  zoomSrc.value = src
  zoomCaption.value =
    img.closest('figure')?.querySelector('figcaption')?.textContent?.trim() ||
    img.getAttribute('title') ||
    img.getAttribute('alt') ||
    ''
}

function closeImageZoom() {
  zoomSrc.value = ''
  zoomCaption.value = ''
}

async function downloadZoomImage() {
  if (!zoomSrc.value) return
  try {
    const res = await fetch(zoomSrc.value)
    if (!res.ok) throw new Error()
    const blob = await res.blob()
    const objectUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const path = zoomSrc.value.split('?')[0]
    a.href = objectUrl
    a.download = path.slice(path.lastIndexOf('/') + 1) || 'image.png'
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  } catch {
    window.open(zoomSrc.value, '_blank', 'noopener')
  }
}

function onZoomKey(event: KeyboardEvent) {
  if (event.key === 'Escape') closeImageZoom()
}

watch(zoomSrc, (value) => {
  if (value) window.addEventListener('keydown', onZoomKey)
  else window.removeEventListener('keydown', onZoomKey)
})

onBeforeUnmount(() => window.removeEventListener('keydown', onZoomKey))

/** 站内链接（来源引用、Wiki、笔记卡片）走 SPA 路由，避免整页刷新。 */
function onClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  const image = target?.closest<HTMLImageElement>('figure.md-image img, .md-gallery-item img')
  if (image) {
    event.preventDefault()
    event.stopPropagation()
    openImageZoom(image)
    return
  }
  const anchor = target?.closest('a')
  const href = anchor?.getAttribute('href') || ''
  const cite = anchor?.getAttribute('data-cite')
  if (cite) {
    event.preventDefault()
    emit('citation-click', Number(cite))
    return
  }
  if (
    href.startsWith('/sources/') ||
    href.startsWith('/wiki/') ||
    href.startsWith('/notes/')
  ) {
    event.preventDefault()
    void router.push(href)
  }
}
</script>

<template>
  <div ref="root" class="prose-wiki markdown-view" @click="onClick" v-html="html" />

  <Teleport to="body">
    <div
      v-if="zoomSrc"
      class="fixed inset-0 z-[130] flex flex-col bg-slate-950/85 p-5 backdrop-blur-sm"
      @click.self="closeImageZoom"
    >
      <div class="flex shrink-0 items-center justify-end gap-2">
        <button
          type="button"
          class="grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-white/80 transition-colors hover:bg-white/20 hover:text-white"
          title="下载原图"
          @click="downloadZoomImage"
        >
          <KiwiIcon name="download" :size="15" />
        </button>
        <button
          type="button"
          class="grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-white/80 transition-colors hover:bg-white/20 hover:text-white"
          title="关闭"
          @click="closeImageZoom"
        >
          <KiwiIcon name="close" :size="15" />
        </button>
      </div>
      <div class="flex min-h-0 flex-1 items-center justify-center">
        <img
          :src="zoomSrc"
          :alt="zoomCaption"
          class="max-h-full max-w-full rounded-lg object-contain shadow-2xl"
        />
      </div>
      <p v-if="zoomCaption" class="mt-3 shrink-0 text-center text-[12px] text-white/60">
        {{ zoomCaption }}
      </p>
    </div>
  </Teleport>
</template>

<style>
/* 问答引用角标：与引用卡片一一对应，可点击定位 */
.markdown-view .md-cite-ref {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.15em;
  margin: 0 0.08em;
  padding: 0 0.28em;
  border-radius: 0.4em;
  background: rgb(236 238 247);
  color: rgb(76 70 166);
  font-size: 0.76em;
  font-weight: 600;
  line-height: 1.45;
  text-decoration: none !important;
  vertical-align: 0.1em;
  transition: background-color 0.15s ease, color 0.15s ease;
}
.markdown-view .md-cite-ref:hover {
  background: rgb(217 220 240);
  color: rgb(62 59 133);
}

/* 阅读预览不展示组件外框，只呈现内容 */
.markdown-view .md-formula {
  margin: 0.9rem 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  overflow-x: auto;
  color: rgb(30 41 59);
}
.markdown-view .md-formula .katex-display {
  margin: 0.2em 0;
}
.markdown-view .md-formula.is-error {
  color: rgb(220 38 38);
  font-family: ui-monospace, monospace;
  font-size: 12px;
  white-space: pre-wrap;
}
.markdown-view .md-mermaid {
  margin: 0.9rem 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  display: flex;
  justify-content: center;
  overflow: auto;
}
.markdown-view .md-mermaid svg {
  max-width: 100%;
  height: auto;
}
.markdown-view .md-mermaid .md-mermaid-source {
  margin: 0;
  width: 100%;
  background: transparent;
  border: 0;
  padding: 0;
  font-size: 12px;
  color: rgb(100 116 139);
  white-space: pre-wrap;
}
.markdown-view .md-mermaid.is-rendered .md-mermaid-source {
  display: none;
}
.markdown-view .md-mermaid.is-error {
  border-color: rgb(254 202 202);
  background: rgb(254 242 242 / 0.6);
}
/* 正文图片：可点击放大，图注居中弱化 */
.markdown-view .md-image {
  margin: 1.1rem auto;
  max-width: 100%;
  text-align: center;
}
.markdown-view .md-image img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 0 auto;
  border-radius: 0.6rem;
  cursor: zoom-in;
}
.markdown-view .md-image figcaption {
  margin-top: 0.4rem;
  color: rgb(148 163 184);
  font-size: 0.78em;
  line-height: 1.55;
}

.markdown-view .md-gallery {
  display: grid;
  gap: 8px;
  margin: 0.85rem 0;
}
.markdown-view .md-gallery.is-carousel {
  display: flex;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  padding-bottom: 4px;
}
.markdown-view .md-gallery.is-carousel .md-gallery-item {
  flex: 0 0 min(78%, 420px);
  scroll-snap-align: center;
}
.markdown-view .md-gallery-item {
  margin: 0;
  overflow: hidden;
  border-radius: 9px;
  border: 0;
  background: transparent;
}
.markdown-view .md-gallery-item img {
  display: block;
  width: 100%;
  height: 150px;
  object-fit: cover;
}
.markdown-view .md-gallery-item figcaption {
  padding: 5px 8px;
  font-size: 11px;
  color: rgb(100 116 139);
}
.markdown-view .md-note-card {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0.7rem 0;
  padding: 10px 12px;
  border-radius: 11px;
  border: 1px solid rgb(226 232 240);
  background: linear-gradient(180deg, #fff, rgb(248 250 252));
  text-decoration: none !important;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.markdown-view .md-note-card:hover {
  border-color: rgb(217 249 157);
  box-shadow: 0 4px 14px rgb(101 163 13 / 0.08);
}
.markdown-view .md-note-card-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: rgb(236 252 203);
  color: rgb(101 163 13);
  font-size: 14px;
}
.markdown-view .md-note-card-body {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}
.markdown-view .md-note-card-title {
  color: rgb(51 65 85);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.markdown-view .md-note-card-kind {
  color: rgb(148 163 184);
  font-size: 10.5px;
}
.markdown-view .md-note-card-arrow {
  color: rgb(203 213 225);
  font-size: 14px;
}
/* 日历 / 数据表共用色调 */
.markdown-view .md-tone-default { --tone-bg: rgb(248 250 252); --tone-line: rgb(203 213 225); --tone-fg: rgb(71 85 105); }
.markdown-view .md-tone-slate { --tone-bg: rgb(241 245 249); --tone-line: rgb(203 213 225); --tone-fg: rgb(51 65 85); }
.markdown-view .md-tone-blue { --tone-bg: rgb(239 246 255); --tone-line: rgb(147 197 253); --tone-fg: rgb(30 64 175); }
.markdown-view .md-tone-green { --tone-bg: rgb(240 253 244); --tone-line: rgb(134 239 172); --tone-fg: rgb(22 101 52); }
.markdown-view .md-tone-amber { --tone-bg: rgb(255 251 235); --tone-line: rgb(252 211 77); --tone-fg: rgb(146 64 14); }
.markdown-view .md-tone-rose { --tone-bg: rgb(255 241 242); --tone-line: rgb(253 164 175); --tone-fg: rgb(159 18 57); }
.markdown-view .md-tone-violet { --tone-bg: rgb(245 243 255); --tone-line: rgb(196 181 253); --tone-fg: rgb(91 33 182); }
.markdown-view .md-tone-cyan { --tone-bg: rgb(236 254 255); --tone-line: rgb(103 232 249); --tone-fg: rgb(21 94 117); }
.markdown-view .md-tone-orange { --tone-bg: rgb(255 247 237); --tone-line: rgb(253 186 116); --tone-fg: rgb(154 52 18); }

/* 日历（只读） */
.markdown-view .md-calendar {
  margin: 0.9rem 0;
}
.markdown-view .md-calendar-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}
.markdown-view .md-calendar-title {
  font-size: 12.5px;
  font-weight: 600;
  color: rgb(51 65 85);
}
.markdown-view .md-calendar-month {
  font-size: 11px;
  color: rgb(100 116 139);
  font-variant-numeric: tabular-nums;
}
.markdown-view .md-calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 2px;
}
.markdown-view .md-calendar-weekday {
  padding: 2px 0;
  text-align: center;
  font-size: 9.5px;
  color: rgb(148 163 184);
}
.markdown-view .md-calendar-weeks {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.markdown-view .md-calendar-week {
  min-width: 0;
}
.markdown-view .md-calendar-band {
  position: relative;
}
.markdown-view .md-calendar-range {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 0 5px;
  border-left: 2px solid var(--tone-line);
  border-radius: 5px;
  background: var(--tone-bg);
  color: var(--tone-fg);
  font-size: 9.5px;
  line-height: 18px;
  white-space: nowrap;
  overflow: hidden;
}
.markdown-view .md-calendar-range.is-continued-left {
  border-left-width: 0;
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}
.markdown-view .md-calendar-range.is-continued-right {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}
.markdown-view .md-calendar-range i {
  font-style: normal;
  opacity: 0.55;
}
.markdown-view .md-calendar-weekdays {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 2px;
}
.markdown-view .md-calendar-day {
  display: flex;
  flex-direction: column;
  gap: 1px;
  height: 54px;
  padding: 3px 4px;
  border-radius: 6px;
  overflow: hidden;
  color: rgb(51 65 85);
  font-variant-numeric: tabular-nums;
}
.markdown-view .md-calendar-day.is-outside {
  opacity: 0.45;
}
.markdown-view .md-calendar-day.is-today {
  background: rgb(247 254 231 / 0.65);
  box-shadow: inset 0 0 0 1px rgb(190 242 100 / 0.9);
}
.markdown-view .md-calendar-daynum {
  font-size: 10px;
  line-height: 13px;
  font-weight: 500;
}
.markdown-view .md-calendar-day.is-today .md-calendar-daynum {
  color: rgb(63 98 18);
  font-weight: 700;
}
.markdown-view .md-calendar-daychips {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.markdown-view .md-calendar-chip {
  padding: 0 3px;
  border-radius: 3px;
  background: var(--tone-bg);
  color: var(--tone-fg);
  font-size: 8.5px;
  line-height: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.markdown-view .md-calendar-more {
  padding-left: 3px;
  font-size: 8px;
  color: rgb(148 163 184);
}
.markdown-view .md-calendar-events {
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px dashed rgb(226 232 240);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.markdown-view .md-calendar-event {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 11.5px;
  color: rgb(51 65 85);
}
.markdown-view .md-calendar-event b {
  flex-shrink: 0;
  border-radius: 5px;
  background: var(--tone-bg);
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 500;
  color: var(--tone-fg);
  font-variant-numeric: tabular-nums;
}

/* 数据表（只读，与数据表笔记一致的四种视图） */
.markdown-view .md-datatable {
  margin: 0.9rem 0;
  padding: 8px;
  border: 1px solid rgb(241 245 249);
  border-radius: 10px;
  background: rgb(255 255 255 / 0.6);
}
.markdown-view .md-datatable figcaption {
  margin: 0 2px 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: rgb(51 65 85);
}
.markdown-view .md-datatable-scroll {
  overflow-x: auto;
}
.markdown-view .md-datatable table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
}
.markdown-view .md-datatable th,
.markdown-view .md-datatable td {
  border-bottom: 1px solid rgb(241 245 249);
  padding: 6px 8px;
  min-width: 90px;
  text-align: left;
  color: rgb(51 65 85);
}
.markdown-view .md-datatable thead th {
  background: rgb(248 250 252 / 0.6);
  font-weight: 500;
  color: rgb(100 116 139);
  font-size: 10.5px;
}
.markdown-view .md-datatable tbody tr:last-child td {
  border-bottom: 0;
}
.markdown-view .md-datatable td a {
  color: rgb(77 124 15);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.markdown-view .md-datatable-empty {
  color: rgb(203 213 225);
}
.markdown-view .md-datatable-empty-state {
  margin: 10px 0;
  text-align: center;
  font-size: 11px;
  color: rgb(148 163 184);
}
.markdown-view .md-db-chip {
  display: inline-flex;
  align-items: center;
  margin: 1px 3px 1px 0;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--tone-bg);
  color: var(--tone-fg);
  font-size: 9.5px;
  line-height: 16px;
  white-space: nowrap;
}
.markdown-view .md-db-progress {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 74px;
  max-width: 130px;
  vertical-align: middle;
}
.markdown-view .md-db-progress-track {
  flex: 1;
  height: 5px;
  border-radius: 999px;
  background: rgb(226 232 240);
  overflow: hidden;
}
.markdown-view .md-db-progress-track i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #6f72dc, #8a8cf0);
}
.markdown-view .md-db-progress.is-complete .md-db-progress-track i {
  background: linear-gradient(90deg, #34a06b, #4cbf83);
}
.markdown-view .md-db-progress-label {
  font-size: 9.5px;
  color: rgb(100 116 139);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.markdown-view .md-db-progress.is-complete .md-db-progress-label {
  color: rgb(21 128 61);
}
.markdown-view .md-db-kanban {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(150px, 1fr);
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
}
.markdown-view .md-db-kanban-col {
  border-radius: 8px;
  background: rgb(248 250 252 / 0.7);
  padding: 6px;
  min-height: 54px;
}
.markdown-view .md-db-kanban-head {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 5px;
  font-size: 10.5px;
  color: rgb(71 85 105);
}
.markdown-view .md-db-kanban-head i {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--tone-line);
}
.markdown-view .md-db-kanban-head em {
  margin-left: auto;
  font-style: normal;
  font-size: 9.5px;
  color: rgb(148 163 184);
}
.markdown-view .md-db-kanban-card {
  border: 1px solid rgb(241 245 249);
  border-radius: 7px;
  background: white;
  padding: 6px 7px;
  margin-bottom: 5px;
}
.markdown-view .md-db-kanban-card p {
  margin: 0;
  font-size: 11px;
  color: rgb(51 65 85);
}
.markdown-view .md-db-kanban-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  margin-top: 3px;
  font-size: 9px;
  color: rgb(148 163 184);
}
.markdown-view .md-db-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 8px;
}
.markdown-view .md-db-gallery-card {
  border: 1px solid rgb(241 245 249);
  border-radius: 9px;
  overflow: hidden;
  background: white;
}
.markdown-view .md-db-gallery-cover {
  height: 64px;
  background: linear-gradient(135deg, rgb(236 252 203), rgb(224 242 254));
}
.markdown-view .md-db-gallery-card img {
  display: block;
  width: 100%;
  height: 64px;
  object-fit: cover;
}
.markdown-view .md-db-gallery-body {
  padding: 6px 8px;
}
.markdown-view .md-db-gallery-body p {
  margin: 0;
  font-size: 11px;
  font-weight: 500;
  color: rgb(51 65 85);
}
.markdown-view .md-db-gallery-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  font-size: 9px;
  color: rgb(148 163 184);
}
.markdown-view .md-db-empty {
  margin: 6px 2px;
  font-size: 10px;
  color: rgb(148 163 184);
}

.markdown-view .md-columns {
  display: grid;
  gap: 12px;
  margin: 0.85rem 0;
  align-items: start;
}
.markdown-view .md-column {
  min-width: 0;
}
.markdown-view .md-date-chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgb(190 242 100 / 0.65);
  background: rgb(247 254 231);
  color: rgb(63 98 18);
  font-size: 0.86em;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
}
.markdown-view .md-callout {
  display: flex;
  gap: 9px;
  margin: 0.8rem 0;
  padding: 11px 13px;
  border-radius: 11px;
  border: 1px solid rgb(217 249 157);
  background: rgb(247 254 231 / 0.7);
}
.markdown-view .md-callout-icon {
  flex: 0 0 auto;
  line-height: 1.5;
}
.markdown-view .md-callout-body {
  min-width: 0;
  flex: 1;
}
.markdown-view .md-callout-body > :first-child {
  margin-top: 0;
}
.markdown-view .md-callout-body > :last-child {
  margin-bottom: 0;
}
.markdown-view .md-details {
  margin: 0.75rem 0;
  padding: 8px 12px;
  border-radius: 10px;
  border: 1px solid rgb(226 232 240);
  background: rgb(248 250 252 / 0.55);
}
.markdown-view .md-details > summary {
  cursor: pointer;
  font-weight: 600;
  color: rgb(51 65 85);
  font-size: 13px;
}
.markdown-view .md-details-body {
  margin-top: 8px;
}
@media (max-width: 760px) {
  .markdown-view .md-columns {
    grid-template-columns: minmax(0, 1fr) !important;
  }
}
</style>
