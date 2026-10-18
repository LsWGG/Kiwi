/** 表格视图的字段筛选与排序（纯前端，作用于同一批行）。 */
import type { DbField, DbFilter, DbRow, DbSort } from '@/stores/noteDatabase'

export function isEmptyValue(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return true
  return Array.isArray(value) && value.length === 0
}

function textOf(value: unknown): string {
  if (Array.isArray(value)) return value.map((v) => String(v)).join(' ')
  return String(value ?? '').toLowerCase()
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

export function matchesFilter(row: DbRow, field: DbField, filter: DbFilter): boolean {
  const value = row.data[field.id]
  const target = filter.value

  if (filter.op === 'is_empty') return isEmptyValue(value)
  if (filter.op === 'is_not_empty') return !isEmptyValue(value)

  const targetMissing = target === null || target === undefined || target === ''

  if (field.type === 'number' || field.type === 'rating') {
    const left = asNumber(value)
    const right = asNumber(target)
    if (left === null || right === null) return false
    if (filter.op === 'is') return left === right
    if (filter.op === 'is_not') return left !== right
    if (filter.op === 'gt') return left > right
    if (filter.op === 'gte') return left >= right
    if (filter.op === 'lt') return left < right
    if (filter.op === 'lte') return left <= right
    return false
  }

  if (field.type === 'checkbox') {
    const expected = target === true || target === 'true' || target === 1
    if (filter.op === 'is') return Boolean(value) === expected
    if (filter.op === 'is_not') return Boolean(value) !== expected
    return false
  }

  if (field.type === 'multi_select') {
    if (targetMissing) return false
    const list = Array.isArray(value) ? value.map(String) : []
    const has = list.includes(String(target))
    if (filter.op === 'contains' || filter.op === 'is') return has
    if (filter.op === 'not_contains' || filter.op === 'is_not') return !has
    return false
  }

  if (field.type === 'select') {
    if (targetMissing) return false
    const same = String(value ?? '') === String(target)
    if (filter.op === 'is') return same
    if (filter.op === 'is_not') return !same
    return false
  }

  if (field.type === 'attachment') return false

  // 文本 / 长文本 / URL / 日期：按字符串比较（ISO 日期可直接比大小）
  if (targetMissing) return false
  const left = textOf(value)
  const right = String(target).toLowerCase()
  if (filter.op === 'contains') return left.includes(right)
  if (filter.op === 'not_contains') return !left.includes(right)
  if (filter.op === 'is') return left === right
  if (filter.op === 'is_not') return left !== right
  if (filter.op === 'gt') return left > right
  if (filter.op === 'gte') return left >= right
  if (filter.op === 'lt') return left < right
  if (filter.op === 'lte') return left <= right
  return false
}

/** 排序值：空值排最后，其余按字段类型比较。 */
function sortValue(row: DbRow, field: DbField): string | number | null {
  const value = row.data[field.id]
  if (isEmptyValue(value)) return null
  if (field.type === 'number' || field.type === 'rating') return asNumber(value)
  if (field.type === 'checkbox') return value ? 1 : 0
  if (field.type === 'select') {
    return (
      field.options?.find((o) => o.id === value)?.name.toLowerCase() ??
      String(value).toLowerCase()
    )
  }
  if (field.type === 'multi_select') {
    const list = Array.isArray(value) ? value : []
    return list
      .map((id) => field.options?.find((o) => o.id === id)?.name ?? String(id))
      .join('、')
      .toLowerCase()
  }
  if (field.type === 'attachment') return Array.isArray(value) ? value.length : 0
  return String(value).toLowerCase()
}

export function applyTableQuery(
  rows: DbRow[],
  fields: DbField[],
  filters?: DbFilter[] | null,
  sorts?: DbSort[] | null,
): DbRow[] {
  const byId = new Map(fields.map((f) => [f.id, f]))
  const activeFilters = (filters ?? []).filter((f) => byId.has(f.field))
  const activeSorts = (sorts ?? []).filter((s) => byId.has(s.field))

  let result = rows
  if (activeFilters.length) {
    result = result.filter((row) =>
      activeFilters.every((filter) => matchesFilter(row, byId.get(filter.field)!, filter)),
    )
  }
  if (activeSorts.length) {
    result = result
      .map((row, index) => ({ row, index }))
      .sort((a, b) => {
        for (const sort of activeSorts) {
          const field = byId.get(sort.field)!
          const left = sortValue(a.row, field)
          const right = sortValue(b.row, field)
          if (left === null && right === null) continue
          if (left === null) return 1
          if (right === null) return -1
          let diff = 0
          if (typeof left === 'number' && typeof right === 'number') diff = left - right
          else diff = String(left).localeCompare(String(right), 'zh-Hans-CN')
          if (diff !== 0) return sort.direction === 'asc' ? diff : -diff
        }
        return a.index - b.index
      })
      .map((item) => item.row)
  }
  return result
}
