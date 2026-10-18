/**
 * 内嵌数据表组件：与「数据表笔记」保持同一套数据模型。
 *
 * 字段（fields）、视图（views）、记录（rows）与数据库笔记一致，
 * 因此表格 / 看板 / 画册 / 日历四种视图、字段类型、筛选排序、
 * 多天日历横条等能力在笔记正文内同样可用。
 *
 * Markdown 使用 ```kiwi-datatable 围栏 + JSON 持久化，复制与往返不丢数据。
 * 同时兼容旧版 `{ columns, rows, caption }` 结构。
 */
import type {
  DbField,
  DbFilter,
  DbSort,
  DbView,
  FieldType,
  SelectOption,
  ViewType,
} from '@/stores/noteDatabase'

const DATATABLE_LANGUAGE = 'kiwi-datatable'
export const DATATABLE_MAX_COLUMNS = 40
export const DATATABLE_MAX_ROWS = 500
export const DATATABLE_MAX_VIEWS = 12
export const DEFAULT_DATATABLE_COLUMNS = ['列 1', '列 2', '列 3']

const FIELD_TYPES: FieldType[] = [
  'text',
  'long_text',
  'number',
  'rating',
  'progress',
  'select',
  'multi_select',
  'date',
  'checkbox',
  'url',
  'attachment',
]
const VIEW_TYPES: ViewType[] = ['table', 'kanban', 'gallery', 'calendar']
const VIEW_TYPE_SET = new Set<string>(VIEW_TYPES)
const FIELD_TYPE_SET = new Set<string>(FIELD_TYPES)
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const MAX_TEXT = 5000
const MAX_LONG_TEXT = 20000
const MAX_OPTIONS = 50
const MAX_FILTERS = 20
const MAX_SORTS = 5
const MAX_ATTACHMENTS = 20
const BAR_COLORS = new Set([
  'slate',
  'blue',
  'green',
  'amber',
  'rose',
  'violet',
  'cyan',
  'orange',
])
const FILTER_OPS = new Set([
  'contains',
  'not_contains',
  'is',
  'is_not',
  'is_empty',
  'is_not_empty',
  'gt',
  'gte',
  'lt',
  'lte',
])

let seq = 0
export function newRowId(): string {
  seq += 1
  return `r_${Date.now().toString(36)}_${seq}`
}
export function newInlineViewId(): string {
  seq += 1
  return `v_${Date.now().toString(36)}_${seq}`
}

export interface InlineDbRow {
  id: string
  data: Record<string, any>
}

export interface DataTableModel {
  title: string
  fields: DbField[]
  views: DbView[]
  rows: InlineDbRow[]
  /** 当前展示的视图 id */
  view: string
}

export interface DataTableAttrs {
  title?: string
  fields?: DbField[]
  views?: DbView[]
  rows?: InlineDbRow[]
  view?: string
}

export function defaultDataTableFields(): DbField[] {
  return [
    { id: 'name', name: '名称', type: 'text' },
    {
      id: 'status',
      name: '状态',
      type: 'select',
      options: [
        { id: 'todo', name: '待办', color: 'slate' },
        { id: 'doing', name: '进行中', color: 'blue' },
        { id: 'done', name: '已完成', color: 'green' },
      ],
    },
    { id: 'date', name: '日期', type: 'date' },
  ]
}

export function defaultDataTableViews(): DbView[] {
  return [
    { id: 'table', name: '表格', type: 'table', hidden_fields: [] },
    { id: 'kanban', name: '看板', type: 'kanban', group_field: 'status' },
    { id: 'gallery', name: '画册', type: 'gallery', cover_field: null, title_field: 'name' },
    {
      id: 'calendar',
      name: '日历',
      type: 'calendar',
      date_field: 'date',
      end_field: null,
      title_field: 'name',
      bar_color: null,
    },
  ]
}

export function defaultDataTableModel(): DataTableModel {
  return {
    title: '',
    fields: defaultDataTableFields(),
    views: defaultDataTableViews(),
    rows: [],
    view: 'table',
  }
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function fenceFor(value: string): string {
  const runs = value.match(/`+/g) ?? []
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0)
  return '`'.repeat(Math.max(3, longest + 1))
}

function firstFieldOf(fields: DbField[], types: FieldType[]): string | null {
  return fields.find((field) => types.includes(field.type))?.id ?? null
}

/** 按现存字段生成可用视图，字段删除后不会留下失效引用。 */
export function defaultViewsFor(fields: DbField[]): DbView[] {
  const text = firstFieldOf(fields, ['text', 'long_text', 'url'])
  const select = firstFieldOf(fields, ['select'])
  const date = firstFieldOf(fields, ['date'])
  const views: DbView[] = [
    { id: 'table', name: '表格', type: 'table', hidden_fields: [] },
  ]
  if (select) {
    views.push({ id: 'kanban', name: '看板', type: 'kanban', group_field: select })
  }
  views.push({
    id: 'gallery',
    name: '画册',
    type: 'gallery',
    cover_field: null,
    title_field: text,
  })
  if (date) {
    views.push({
      id: 'calendar',
      name: '日历',
      type: 'calendar',
      date_field: date,
      end_field: null,
      title_field: text,
      bar_color: null,
    })
  }
  return views
}

// ---------------------------------------------------------------------------
// 字段
// ---------------------------------------------------------------------------

function uniqueId(raw: unknown, fallback: string, used: Set<string>): string {
  let base =
    typeof raw === 'string' && /^[a-zA-Z0-9_]{1,40}$/.test(raw) ? raw : fallback
  if (!base) base = fallback
  let id = base
  let n = 2
  while (used.has(id)) {
    id = `${base.slice(0, 36)}_${n}`
    n += 1
  }
  used.add(id)
  return id
}

function sanitizeOptions(raw: unknown): SelectOption[] {
  if (!Array.isArray(raw)) return []
  const out: SelectOption[] = []
  const used = new Set<string>()
  raw.slice(0, MAX_OPTIONS).forEach((item, index) => {
    if (!item || typeof item !== 'object') return
    const source = item as Record<string, unknown>
    const name = String(source.name ?? '').trim().slice(0, 60)
    if (!name) return
    const id = uniqueId(source.id, `o${index + 1}`, used)
    const option: SelectOption = { id, name }
    const color = String(source.color ?? '')
    if (color) option.color = color.slice(0, 20)
    out.push(option)
  })
  return out
}

function sanitizeFields(raw: unknown): DbField[] {
  if (!Array.isArray(raw)) return []
  const out: DbField[] = []
  const used = new Set<string>()
  raw.slice(0, DATATABLE_MAX_COLUMNS).forEach((item, index) => {
    if (!item || typeof item !== 'object') return
    const source = item as Record<string, unknown>
    const type = FIELD_TYPE_SET.has(String(source.type))
      ? (String(source.type) as FieldType)
      : 'text'
    const name = String(source.name ?? '').trim().slice(0, 120) || `字段 ${index + 1}`
    const field: DbField = {
      id: uniqueId(source.id, `f${index + 1}`, used),
      name,
      type,
    }
    if (type === 'select' || type === 'multi_select') {
      field.options = sanitizeOptions(source.options)
    }
    out.push(field)
  })
  return out
}

/** 旧版列名 -> 字段；全部为文本，保留原有数据。 */
function fieldsFromLegacyColumns(raw: unknown): DbField[] {
  const columns = Array.isArray(raw)
    ? raw.slice(0, DATATABLE_MAX_COLUMNS).map((item) => String(item ?? ''))
    : []
  if (!columns.length) return defaultDataTableFields()
  return columns.map((name, index) => ({
    id: `f${index + 1}`,
    name: name || `列 ${index + 1}`,
    type: 'text' as FieldType,
  }))
}

// ---------------------------------------------------------------------------
// 视图
// ---------------------------------------------------------------------------

function sanitizeViewFilters(raw: unknown, fields: DbField[]): DbFilter[] {
  if (!Array.isArray(raw)) return []
  const allowed = new Set(fields.map((field) => field.id))
  const out: DbFilter[] = []
  raw.slice(0, MAX_FILTERS).forEach((item, index) => {
    if (!item || typeof item !== 'object') return
    const source = item as Record<string, unknown>
    const field = String(source.field ?? '')
    const op = String(source.op ?? '')
    if (!allowed.has(field) || !FILTER_OPS.has(op)) return
    const value = source.value
    if (value !== null && value !== undefined && typeof value === 'object') return
    out.push({
      id: String(source.id ?? `flt_${index + 1}`).slice(0, 40),
      field,
      op: op as DbFilter['op'],
      value: value as DbFilter['value'],
    })
  })
  return out
}

function sanitizeViewSorts(raw: unknown, fields: DbField[]): DbSort[] {
  if (!Array.isArray(raw)) return []
  const allowed = new Set(fields.map((field) => field.id))
  const seen = new Set<string>()
  const out: DbSort[] = []
  raw.slice(0, MAX_SORTS).forEach((item) => {
    if (!item || typeof item !== 'object') return
    const source = item as Record<string, unknown>
    const field = String(source.field ?? '')
    const direction = String(source.direction ?? '')
    if (!allowed.has(field) || seen.has(field)) return
    if (direction !== 'asc' && direction !== 'desc') return
    seen.add(field)
    out.push({ field, direction })
  })
  return out
}

export function sanitizeViews(raw: unknown, fields: DbField[]): DbView[] {
  if (!Array.isArray(raw)) return defaultViewsFor(fields)
  const fieldIds = new Set(fields.map((field) => field.id))
  const fieldById = new Map(fields.map((field) => [field.id, field]))
  const selectFields = fields.filter((field) => field.type === 'select')
  const dateFields = fields.filter((field) => field.type === 'date')
  const firstSelect = selectFields[0]?.id ?? null
  const firstDate = dateFields[0]?.id ?? null
  const firstText = firstFieldOf(fields, ['text', 'long_text', 'url'])
  const used = new Set<string>()
  const out: DbView[] = []

  raw.slice(0, DATATABLE_MAX_VIEWS).forEach((item, index) => {
    if (!item || typeof item !== 'object') return
    const source = item as Record<string, unknown>
    const type = VIEW_TYPE_SET.has(String(source.type))
      ? (String(source.type) as ViewType)
      : 'table'
    const id = uniqueId(source.id, `v${index + 1}`, used)
    const name = String(source.name ?? '').trim().slice(0, 60) || `视图 ${index + 1}`
    const view: DbView = { id, name, type }

    if (type === 'table') {
      view.hidden_fields = Array.isArray(source.hidden_fields)
        ? source.hidden_fields
            .map((value) => String(value))
            .filter((value) => fieldIds.has(value))
        : []
      const widths: Record<string, number> = {}
      if (source.column_widths && typeof source.column_widths === 'object') {
        Object.entries(source.column_widths as Record<string, unknown>).forEach(
          ([fieldId, value]) => {
            if (!fieldIds.has(fieldId)) return
            if (typeof value !== 'number' || !Number.isFinite(value)) return
            widths[fieldId] = Math.max(60, Math.min(600, Math.round(value)))
          },
        )
      }
      view.column_widths = widths
      const heights: Record<string, number> = {}
      if (source.row_heights && typeof source.row_heights === 'object') {
        Object.entries(source.row_heights as Record<string, unknown>).forEach(
          ([rowId, value]) => {
            if (typeof value !== 'number' || !Number.isFinite(value)) return
            heights[String(rowId).slice(0, 64)] = Math.max(
              36,
              Math.min(400, Math.round(value)),
            )
          },
        )
      }
      view.row_heights = heights
      view.filters = sanitizeViewFilters(source.filters, fields)
      view.sorts = sanitizeViewSorts(source.sorts, fields)
    } else if (type === 'kanban') {
      const group = String(source.group_field ?? '')
      const groupField = fieldById.get(group)
      const groupId =
        groupField?.type === 'select' ? groupField.id : firstSelect ?? null
      if (!groupId) return // 没有单选字段时看板不可用
      view.group_field = groupId
      if (Array.isArray(source.display_fields)) {
        view.display_fields = Array.from(
          new Set(
            source.display_fields
              .map((value) => String(value))
              .filter((value) => fieldIds.has(value) && value !== groupId),
          ),
        )
      } else {
        view.display_fields = null
      }
      view.title_field = firstText
    } else if (type === 'gallery') {
      const cover = String(source.cover_field ?? '')
      view.cover_field = fieldIds.has(cover) ? cover : null
      const title = String(source.title_field ?? '')
      view.title_field = fieldIds.has(title) ? title : firstText
    } else {
      const date = String(source.date_field ?? '')
      const dateField = fieldById.get(date)
      const dateId =
        dateField?.type === 'date' ? dateField.id : firstDate ?? null
      if (!dateId) return // 没有日期字段时日历不可用
      const end = String(source.end_field ?? '')
      const endField = fieldById.get(end)
      const endId =
        endField?.type === 'date' && endField.id !== dateId ? endField.id : null
      view.date_field = dateId
      view.end_field = endId
      const title = String(source.title_field ?? '')
      view.title_field = fieldIds.has(title) ? title : firstText
      const bar = String(source.bar_color ?? '')
      view.bar_color = BAR_COLORS.has(bar) ? bar : null
    }
    out.push(view)
  })

  if (!out.length) return defaultViewsFor(fields)
  return out
}

// ---------------------------------------------------------------------------
// 记录
// ---------------------------------------------------------------------------

function sanitizeAttachments(raw: unknown): Record<string, any>[] {
  if (!Array.isArray(raw)) return []
  const out: Record<string, any>[] = []
  raw.slice(0, MAX_ATTACHMENTS).forEach((item) => {
    if (!item || typeof item !== 'object') return
    const source = item as Record<string, any>
    const filename = String(source.filename ?? '').trim()
    const url = String(source.url ?? '').trim()
    if (!filename || !url) return
    out.push({
      id: String(source.id ?? '').slice(0, 64),
      filename: filename.slice(0, 300),
      url: url.slice(0, 1000),
      content_type: String(source.content_type ?? '').slice(0, 120),
      size: Number(source.size) || 0,
    })
  })
  return out
}

function sanitizeCell(field: DbField, value: unknown): any {
  if (field.type === 'checkbox') return value === true
  if (value === null || value === undefined || value === '') return null
  if (field.type === 'number') {
    const num = Number(value)
    return Number.isFinite(num) ? num : null
  }
  if (field.type === 'rating') {
    const num = Number(value)
    if (!Number.isFinite(num)) return null
    return Math.max(0, Math.min(5, Math.round(num)))
  }
  if (field.type === 'progress') {
    const num = Number(value)
    if (!Number.isFinite(num)) return null
    return Math.max(0, Math.min(100, Math.round(num)))
  }
  if (field.type === 'multi_select') {
    if (!Array.isArray(value)) return []
    const allowed = new Set((field.options ?? []).map((option) => option.id))
    return Array.from(
      new Set(value.map((item) => String(item)).filter((item) => allowed.has(item))),
    )
  }
  if (field.type === 'attachment') return sanitizeAttachments(value)
  const text = String(value)
  if (field.type === 'select') {
    const allowed = new Set((field.options ?? []).map((option) => option.id))
    return allowed.has(text) ? text : null
  }
  if (field.type === 'date') return DATE_RE.test(text) ? text : null
  return text.slice(0, field.type === 'long_text' ? MAX_LONG_TEXT : MAX_TEXT)
}

function isEmptyCell(field: DbField, value: any): boolean {
  if (value === null || value === undefined || value === '') return true
  if (field.type === 'checkbox') return value === false
  if (Array.isArray(value)) return value.length === 0
  return false
}

function sanitizeRows(
  raw: unknown,
  fields: DbField[],
  legacy: boolean,
): InlineDbRow[] {
  if (!Array.isArray(raw)) return []
  const used = new Set<string>()
  const out: InlineDbRow[] = []
  raw.slice(0, DATATABLE_MAX_ROWS).forEach((item, index) => {
    let dataSource: Record<string, unknown>
    let rawId: unknown
    if (legacy) {
      const cells = Array.isArray(item) ? item : []
      dataSource = {}
      fields.forEach((field, fieldIndex) => {
        dataSource[field.id] = String(cells[fieldIndex] ?? '')
      })
    } else if (Array.isArray(item)) {
      dataSource = {}
      fields.forEach((field, fieldIndex) => {
        dataSource[field.id] = item[fieldIndex] as unknown
      })
    } else if (item && typeof item === 'object') {
      const source = item as Record<string, unknown>
      dataSource =
        source.data && typeof source.data === 'object' && !Array.isArray(source.data)
          ? (source.data as Record<string, unknown>)
          : source
      rawId = source.id
    } else {
      return
    }
    const data: Record<string, any> = {}
    for (const field of fields) {
      if (!(field.id in dataSource)) continue
      const value = sanitizeCell(field, dataSource[field.id])
      if (!isEmptyCell(field, value)) data[field.id] = value
    }
    out.push({
      id: uniqueId(rawId, `r${index + 1}`, used),
      data,
    })
  })
  return out
}

// ---------------------------------------------------------------------------
// 规范化入口
// ---------------------------------------------------------------------------

/** 兼容 `{ columns, rows, caption }` 旧结构与新版数据库模型。 */
export function normalizeDataTable(value: unknown): DataTableModel {
  const source = (value && typeof value === 'object' ? value : {}) as Record<
    string,
    unknown
  >
  const legacy = !Array.isArray(source.fields) && Array.isArray(source.columns)
  const fields = legacy
    ? fieldsFromLegacyColumns(source.columns)
    : sanitizeFields(source.fields)
  if (!fields.length) fields.push(...defaultDataTableFields())

  const views = legacy
    ? [{ id: 'table', name: '表格', type: 'table' as ViewType, hidden_fields: [] }]
    : sanitizeViews(source.views, fields)
  const rows = sanitizeRows(source.rows, fields, legacy)
  const title = String(source.title ?? source.caption ?? '').slice(0, 200)
  const requested = String(source.view ?? source.active_view ?? '')
  const view = views.some((item) => item.id === requested)
    ? requested
    : views[0].id

  return { title, fields, views, rows, view }
}

/** 行数据转换为数据库视图组件所需的 DbRow（内嵌表没有独立笔记）。 */
export function inlineRowsForView(model: DataTableModel): Array<{
  id: string
  collection_id: string
  note_id: null
  data: Record<string, any>
  sort_order: number
  created_at: string
  updated_at: string
}> {
  return model.rows.map((row, index) => ({
    id: row.id,
    collection_id: 'inline',
    note_id: null,
    data: row.data,
    sort_order: index,
    created_at: '',
    updated_at: '',
  }))
}

