<script setup lang="ts">
/**
 * 表格笔记：Excel 风格工作簿。
 *
 * - 数据保存在 `props_json.sheet`，结构与后端 `parse_sheet_workbook` 一致
 * - 前端公式引擎负责实时计算；导入时保留的 `cached` 仅作为回退
 * - 工具栏 / 右键菜单提供行列、合并、格式与数字格式；主编辑器工具栏不插入表格操作
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import { useAutosave } from '@/composables/useAutosave'
import { useSaveShortcut } from '@/composables/useSaveShortcut'
import NoteTitleBreadcrumb from '@/components/notes/NoteTitleBreadcrumb.vue'
import NoteTagButton from '@/components/notes/NoteTagButton.vue'
import EditorColorPicker from '@/components/editor/EditorColorPicker.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'
import type {
  CellPosition,
  CellRange,
  CellValue,
  SheetCell,
  SheetCellStyle,
  SheetData,
  SheetNumberFormat,
  SheetWorkbook,
} from '@/components/notes/sheet/types'
import {
  MAX_COLS,
  MAX_COL_WIDTH,
  MAX_ROWS,
  MIN_COL_WIDTH,
  cellAddress,
  clampPosition,
  columnLabel,
  mergeLayout,
  normalizedRange,
  parseAddress,
  parseRange,
  rangeAddress,
  rangeContains,
  rangesIntersect,
  normalizeWorkbook,
} from '@/components/notes/sheet/types'
import {
  evaluateWorkbook,
  formatSheetValue,
} from '@/components/notes/sheet/formula'
import {
  addSheet,
  applyStyle,
  clearContents,
  clearRangeAll,
  clearStyleKeys,
  copyRange,
  deleteCols,
  deleteRows,
  duplicateSheet,
  ensureCell,
  insertCols,
  insertRows,
  isCellEmpty,
  mergeRange,
  moveSheet,
  pasteSnapshot,
  rangeHasMerge,
  removeSheet,
  renameSheet,
  unmergeRange,
  type ClipboardSnapshot,
} from '@/components/notes/sheet/ops'
const props = defineProps<{ note: NoteOut }>()
const notes = useNotesStore()

const title = ref(props.note.title)
const workbook = ref<SheetWorkbook>(
  normalizeWorkbook(props.note.props_json?.sheet),
)

const autosave = useAutosave(async () => {
  await notes.updateNote(props.note.id, {
    title: title.value.trim() || '无标题表格',
    props_json: { ...props.note.props_json, sheet: workbook.value },
  })
})

useSaveShortcut(() => autosave.flushNow())

function scheduleSave() {
  autosave.schedule()
}

watch(workbook, scheduleSave, { deep: true })
watch(
  () => props.note.title,
  (value) => {
    if (value !== title.value && !autosave.saving.value) title.value = value
  },
)

const activeSheet = computed<SheetData>(() => {
  const sheet = workbook.value.sheets.find((item) => item.id === workbook.value.active)
  return sheet ?? workbook.value.sheets[0]
})
const results = computed(() => evaluateWorkbook(workbook.value))
const layout = computed(() => mergeLayout(activeSheet.value))

const gridEl = ref<HTMLElement | null>(null)

const anchor = ref<CellPosition>({ row: 0, col: 0 })
const focus = ref<CellPosition>({ row: 0, col: 0 })
const selection = computed<CellRange>(() =>
  normalizedRange({ start: anchor.value, end: focus.value }),
)
const activeAddress = computed(() => cellAddress(focus.value.row, focus.value.col))
const activeCell = computed<SheetCell | undefined>(() =>
  activeSheet.value.cells[activeAddress.value],
)
const selectionLabel = computed(() => rangeAddress(selection.value))

const editing = ref(false)
const editValue = ref('')
const editAddress = ref('')

const barValue = ref('')
const barFocused = ref(false)
const barDirty = ref(false)
/** 公式栏开始编辑时锁定的单元格，避免失焦时因选区变化写错格子。 */
const barAddress = ref('A1')
const nameValue = ref('A1')
const nameFocused = ref(false)

// 渲染窗口：大表格只渲染可见范围，避免 5000×120 全量 DOM
const visibleRows = ref(120)
const visibleCols = ref(32)
const usedBounds = computed(() => {
  let maxRow = 0
  let maxCol = 0
  for (const address of Object.keys(activeSheet.value.cells)) {
    const parsed = parseAddress(address)
    if (!parsed) continue
    maxRow = Math.max(maxRow, parsed.row)
    maxCol = Math.max(maxCol, parsed.col)
  }
  for (const raw of activeSheet.value.merges) {
    const parsed = parseRange(raw)
    if (!parsed) continue
    maxRow = Math.max(maxRow, parsed.end.row)
    maxCol = Math.max(maxCol, parsed.end.col)
  }
  return { maxRow, maxCol }
})
const renderRows = computed(() =>
  Math.min(
    activeSheet.value.rows,
    Math.max(visibleRows.value, Math.min(usedBounds.value.maxRow + 16, 600)),
  ),
)
const renderCols = computed(() =>
  Math.min(
    activeSheet.value.cols,
    Math.max(visibleCols.value, Math.min(usedBounds.value.maxCol + 8, 80)),
  ),
)
const hiddenRows = computed(() => activeSheet.value.rows - renderRows.value)
const hiddenCols = computed(() => activeSheet.value.cols - renderCols.value)

// ---------- 排序 / 筛选 ----------

/** 首行视为表头：筛选不隐藏首行，排序时保持首行不动。 */
function rowHasData(row: number): boolean {
  const maxCol = Math.min(usedBounds.value.maxCol, activeSheet.value.cols - 1)
  for (let col = 0; col <= maxCol; col += 1) {
    const cell = activeSheet.value.cells[cellAddress(row, col)]
    if (cell && !isCellEmpty(cell)) return true
  }
  return false
}
const lastDataRow = computed(() =>
  Math.min(usedBounds.value.maxRow, activeSheet.value.rows - 1),
)
const lastDataCol = computed(() =>
  Math.min(usedBounds.value.maxCol, activeSheet.value.cols - 1),
)
const usesHeaderRow = computed(() => lastDataRow.value > 0 && rowHasData(0))

function displayValueAt(row: number, col: number): string {
  const address = cellAddress(row, col)
  const cell = activeSheet.value.cells[address]
  const result = results.value.get(`${activeSheet.value.id}!${address}`)
  if (result?.error) return result.error
  return formatSheetValue(result?.value ?? cell?.cached ?? null, cell?.s?.fmt)
}

/** 当前列被筛选后隐藏的行（首行始终显示）。 */
function rowHidden(row: number): boolean {
  if (row <= 0) return false
  const filters = activeSheet.value.filters
  if (!filters) return false
  for (const [key, values] of Object.entries(filters)) {
    const col = Number(key)
    if (!Number.isInteger(col) || col < 0) continue
    if (!values.includes(displayValueAt(row, col))) return true
  }
  return false
}

const renderRowNumbers = computed(() => {
  const rows: number[] = []
  for (let index = 0; index < renderRows.value; index += 1) {
    if (!rowHidden(index)) rows.push(index + 1)
  }
  return rows
})
const filteredOutRows = computed(
  () => renderRows.value - renderRowNumbers.value.length,
)

function columnFiltered(col: number): boolean {
  return Boolean(activeSheet.value.filters?.[String(col)])
}
const activeFilterCount = computed(
  () => Object.keys(activeSheet.value.filters ?? {}).length,
)
const hasActiveFilters = computed(() => activeFilterCount.value > 0)

interface FilterOption {
  key: string
  label: string
  count: number
}

const filterMenu = ref<{ col: number; left: string; top: string } | null>(null)
/** 最近一次排序的列与方向，用于表头指示（Excel 同款）。 */
const sortState = ref<{ col: number; ascending: boolean } | null>(null)
const filterSearch = ref('')
const filterDraft = ref<string[]>([])
const filterValues = ref<FilterOption[]>([])

const visibleFilterValues = computed(() => {
  const query = filterSearch.value.trim().toLowerCase()
  if (!query) return filterValues.value
  return filterValues.value.filter((item) => item.label.toLowerCase().includes(query))
})
const allVisibleFilterSelected = computed(() => {
  const keys = visibleFilterValues.value.map((item) => item.key)
  return keys.length > 0 && keys.every((key) => filterDraft.value.includes(key))
})

function columnValueOptions(col: number): FilterOption[] {
  const counts = new Map<string, number>()
  const lastRow = lastDataRow.value
  for (let row = 1; row <= lastRow; row += 1) {
    const text = displayValueAt(row, col)
    counts.set(text, (counts.get(text) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([key, count]) => ({
      key,
      label: key === '' ? '（空白）' : key,
      count,
    }))
    .sort((a, b) => {
      if (a.key === '') return 1
      if (b.key === '') return -1
      const numberA = Number(a.key.replace(/[,%¥￥$€£\s]/g, ''))
      const numberB = Number(b.key.replace(/[,%¥￥$€£\s]/g, ''))
      const numericA = a.key.trim() !== '' && Number.isFinite(numberA)
      const numericB = b.key.trim() !== '' && Number.isFinite(numberB)
      if (numericA && numericB) return numberA - numberB
      if (numericA) return -1
      if (numericB) return 1
      return a.label.localeCompare(b.label, 'zh-CN')
    })
}

function openFilterMenuAt(col: number, anchor: { left: number; bottom: number }) {
  commitEdit('none')
  const options = columnValueOptions(col)
  const stored = activeSheet.value.filters?.[String(col)]
  filterValues.value = options
  filterDraft.value = stored ? [...stored] : options.map((item) => item.key)
  filterSearch.value = ''
  const width = 252
  const left = Math.max(8, Math.min(anchor.left, window.innerWidth - width - 8))
  const top = Math.max(8, Math.min(anchor.bottom + 4, window.innerHeight - 420))
  filterMenu.value = { col, left: `${left}px`, top: `${top}px` }
}

function openFilterMenu(col: number, event: MouseEvent) {
  event.preventDefault()
  event.stopPropagation()
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  openFilterMenuAt(col, { left: rect.left, bottom: rect.bottom })
}

function closeFilterMenu() {
  filterMenu.value = null
  filterSearch.value = ''
}

function toggleFilterValue(key: string) {
  filterDraft.value = filterDraft.value.includes(key)
    ? filterDraft.value.filter((item) => item !== key)
    : [...filterDraft.value, key]
}

function toggleAllFilterValues() {
  const keys = visibleFilterValues.value.map((item) => item.key)
  if (!keys.length) return
  const selected = new Set(filterDraft.value)
  if (keys.every((key) => selected.has(key))) {
    filterDraft.value = filterDraft.value.filter((key) => !keys.includes(key))
  } else {
    filterDraft.value = [...new Set([...filterDraft.value, ...keys])]
  }
}

function applyColumnFilter() {
  const menu = filterMenu.value
  if (!menu) return
  const sheet = activeSheet.value
  const allKeys = filterValues.value.map((item) => item.key)
  const selected = new Set(filterDraft.value)
  const filters = { ...(sheet.filters ?? {}) }
  if (allKeys.every((key) => selected.has(key))) {
    delete filters[String(menu.col)]
  } else {
    filters[String(menu.col)] = filterDraft.value.filter((key) => allKeys.includes(key))
  }
  if (Object.keys(filters).length) sheet.filters = filters
  else delete sheet.filters
  closeFilterMenu()
  scheduleSave()
}

function clearColumnFilter(col?: number) {
  const target = col ?? filterMenu.value?.col
  if (target === undefined) return
  const sheet = activeSheet.value
  if (!sheet.filters) {
    closeFilterMenu()
    return
  }
  const filters = { ...sheet.filters }
  delete filters[String(target)]
  if (Object.keys(filters).length) sheet.filters = filters
  else delete sheet.filters
  closeFilterMenu()
  scheduleSave()
}

function clearAllFilters() {
  if (!activeSheet.value.filters) return
  delete activeSheet.value.filters
  closeFilterMenu()
  scheduleSave()
}

interface SortValue {
  rank: number
  number?: number
  text?: string
}

function sortValueAt(row: number, col: number): SortValue {
  const address = cellAddress(row, col)
  const cell = activeSheet.value.cells[address]
  const result = results.value.get(`${activeSheet.value.id}!${address}`)
  const value = result?.error ? null : (result?.value ?? cell?.cached ?? cell?.v ?? null)
  if (value === null || value === undefined || value === '') return { rank: 2 }
  if (typeof value === 'number') return { rank: 0, number: value }
  if (typeof value === 'boolean') return { rank: 0, number: value ? 1 : 0 }
  const text = String(value)
  const stripped = text.replace(/[,%¥￥$€£\s]/g, '')
  const numeric = Number(stripped)
  if (stripped !== '' && Number.isFinite(numeric)) return { rank: 0, number: numeric }
  return { rank: 1, text: text.toLocaleLowerCase('zh-CN') }
}

function compareSortValues(a: SortValue, b: SortValue, ascending: boolean): number {
  if (a.rank !== b.rank) return a.rank - b.rank
  let diff = 0
  if (a.rank === 0) diff = (a.number ?? 0) - (b.number ?? 0)
  else if (a.rank === 1) diff = (a.text ?? '').localeCompare(b.text ?? '', 'zh-CN')
  return ascending ? diff : -diff
}

function mergesInSortRange(startRow: number, endRow: number): boolean {
  return activeSheet.value.merges.some((raw) => {
    const range = parseRange(raw)
    return range ? range.end.row >= startRow && range.start.row <= endRow : false
  })
}

function sortByActiveColumn(ascending: boolean) {
  const sheet = activeSheet.value
  const lastRow = lastDataRow.value
  const col = focus.value.col
  if (lastRow < 1 || col > lastDataCol.value) {
    toast.info('没有可排序的数据')
    return
  }
  const startRow = usesHeaderRow.value ? 1 : 0
  if (lastRow <= startRow) {
    toast.info('没有可排序的数据')
    return
  }
  if (mergesInSortRange(startRow, lastRow)) {
    toast.error('排序区域包含合并单元格，请先取消合并')
    return
  }
  const maxCol = lastDataCol.value
  const rows: number[] = []
  for (let row = startRow; row <= lastRow; row += 1) rows.push(row)
  const entries = rows.map((row) => {
    const cells = new Map<number, SheetCell>()
    for (let index = 0; index <= maxCol; index += 1) {
      const cell = sheet.cells[cellAddress(row, index)]
      if (cell) cells.set(index, cell)
    }
    return { row, cells, key: sortValueAt(row, col) }
  })
  const sorted = [...entries].sort((a, b) =>
    compareSortValues(a.key, b.key, ascending),
  )
  if (sorted.every((item, index) => item.row === rows[index])) {
    toast.info('数据已经是当前顺序')
    return
  }
  withHistory(() => {
    for (const row of rows) {
      for (let index = 0; index <= maxCol; index += 1) {
        delete sheet.cells[cellAddress(row, index)]
      }
    }
    sorted.forEach((item, index) => {
      const targetRow = rows[index]
      for (const [index_, cell] of item.cells) {
        sheet.cells[cellAddress(targetRow, index_)] = cell
      }
    })
  })
  focus.value = { row: startRow, col }
  anchor.value = { row: startRow, col }
  sortState.value = { col, ascending }
  toast.success(`已按 ${columnLabel(col)} 列${ascending ? '升序' : '降序'}排序`)
}

/** 状态栏聚合：选中区域的计数 / 求和 / 平均值（大区域按步长采样）。 */
const selectionStats = computed(() => {
  const range = selection.value
  const rows = range.end.row - range.start.row + 1
  const cols = range.end.col - range.start.col + 1
  const stride = Math.max(1, Math.ceil(Math.sqrt((rows * cols) / 20000)))
  let count = 0
  let numericCount = 0
  let sum = 0
  for (let row = range.start.row; row <= range.end.row; row += stride) {
    if (rowHidden(row)) continue
    for (let col = range.start.col; col <= range.end.col; col += stride) {
      const address = cellAddress(row, col)
      const cell = activeSheet.value.cells[address]
      const result = results.value.get(`${activeSheet.value.id}!${address}`)
      const value = result?.value ?? cell?.cached ?? cell?.v ?? null
      if (value === null || value === undefined || value === '') continue
      count += 1
      const numeric =
        typeof value === 'number'
          ? value
          : Number(String(value).replace(/[,%¥￥$€£\s]/g, ''))
      if (Number.isFinite(numeric) && String(value).trim() !== '') {
        numericCount += 1
        sum += numeric
      }
    }
  }
  return {
    count,
    numericCount,
    sum,
    average: numericCount ? sum / numericCount : 0,
    sampled: stride > 1,
  }
})

function sortAtColumn(col: number, ascending: boolean) {
  anchor.value = { row: focus.value.row, col }
  focus.value = { row: focus.value.row, col }
  sortByActiveColumn(ascending)
}

function sortFromFilter(ascending: boolean) {
  const col = filterMenu.value?.col
  if (col === undefined) return
  closeFilterMenu()
  sortAtColumn(col, ascending)
}

watch(activeSheet, () => {
  anchor.value = { row: 0, col: 0 }
  focus.value = { row: 0, col: 0 }
  visibleRows.value = 120
  visibleCols.value = 32
  sortState.value = null
})

function columnWidth(col: number): number {
  return activeSheet.value.colWidths[String(col)] ?? 104
}
function rowHeight(row: number): number {
  return activeSheet.value.rowHeights[String(row)] ?? 28
}

function mergeAnchorAt(sheet: SheetData, position: CellPosition): CellPosition {
  for (const raw of sheet.merges) {
    const range = parseRange(raw)
    if (!range) continue
    if (rangeContains(range, position)) return range.start
  }
  return position
}

function cellSpan(row: number, col: number) {
  return layout.value.anchors.get(cellAddress(row, col))
}

function isCellSelected(row: number, col: number): boolean {
  const span = cellSpan(row, col)
  if (!span) return rangeContains(selection.value, { row, col })
  return rangesIntersect(
    {
      start: { row, col },
      end: { row: row + span.rowSpan - 1, col: col + span.colSpan - 1 },
    },
    selection.value,
  )
}

function displayCell(address: string): string {
  const cell = activeSheet.value.cells[address]
  const result = results.value.get(`${activeSheet.value.id}!${address}`)
  if (result?.error) return result.error
  return formatSheetValue(result?.value ?? cell?.cached ?? null, cell?.s?.fmt)
}

function cellIsError(address: string): boolean {
  return Boolean(results.value.get(`${activeSheet.value.id}!${address}`)?.error)
}

function numericValue(address: string): CellValue {
  return results.value.get(`${activeSheet.value.id}!${address}`)?.value ?? null
}

function cellAlign(address: string): 'left' | 'center' | 'right' {
  const cell = activeSheet.value.cells[address]
  if (cell?.s?.align) return cell.s.align
  const value = numericValue(address)
  if (typeof value === 'number') return 'right'
  if (typeof value === 'boolean') return 'center'
  return 'left'
}

function cellStyle(address: string): Record<string, string> {
  const cell = activeSheet.value.cells[address]
  const style = cell?.s
  if (!style) return {}
  const output: Record<string, string> = {}
  if (style.bold) output.fontWeight = '600'
  if (style.italic) output.fontStyle = 'italic'
  if (style.underline) output.textDecoration = 'underline'
  if (style.color) output.color = style.color
  if (style.bg) output.backgroundColor = style.bg
  return output
}

// ---------- 历史 ----------

const undoStack = ref<string[]>([])
const redoStack = ref<string[]>([])

function snapshot(): string {
  return JSON.stringify(workbook.value)
}

function pushHistory() {
  undoStack.value.push(snapshot())
  if (undoStack.value.length > 60) undoStack.value.shift()
  redoStack.value = []
}

function restore(raw: string) {
  workbook.value = normalizeWorkbook(JSON.parse(raw))
  visibleRows.value = 120
  visibleCols.value = 32
  focus.value = clampPosition(focus.value, activeSheet.value)
  anchor.value = clampPosition(anchor.value, activeSheet.value)
  scheduleSave()
}

function undo() {
  const entry = undoStack.value.pop()
  if (!entry) return
  redoStack.value.push(snapshot())
  cancelEdit()
  restore(entry)
}

function redo() {
  const entry = redoStack.value.pop()
  if (!entry) return
  undoStack.value.push(snapshot())
  cancelEdit()
  restore(entry)
}

const canUndo = computed(() => undoStack.value.length > 0)
const canRedo = computed(() => redoStack.value.length > 0)

// ---------- 编辑 ----------

function rawEditText(address: string): string {
  const cell = activeSheet.value.cells[address]
  if (!cell) return ''
  if (cell.f) return cell.f
  if (cell.v === null || cell.v === undefined) return ''
  return typeof cell.v === 'boolean' ? (cell.v ? 'TRUE' : 'FALSE') : String(cell.v)
}

function applyRawValue(address: string, raw: string) {
  const cell = ensureCell(activeSheet.value, address)
  const text = raw
  if (text.startsWith('=') && text.length > 1) {
    delete cell.v
    delete cell.cached
    cell.f = text
    return
  }
  delete cell.f
  delete cell.cached
  if (text.startsWith("'")) {
    cell.v = text.slice(1)
    return
  }
  const trimmed = text.trim()
  if (!trimmed) {
    delete cell.v
  } else if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(trimmed)) {
    cell.v = Number(trimmed)
  } else if (/^(true|false)$/i.test(trimmed)) {
    cell.v = trimmed.toLowerCase() === 'true'
  } else {
    cell.v = text
  }
  if (isCellEmpty(cell) && !cell.s) delete activeSheet.value.cells[address]
}

function beginEdit(initial?: string) {
  if (editing.value) return
  const position = mergeAnchorAt(activeSheet.value, focus.value)
  anchor.value = position
  focus.value = position
  editAddress.value = cellAddress(position.row, position.col)
  editValue.value = initial !== undefined ? initial : rawEditText(editAddress.value)
  editing.value = true
  void nextTick(() => {
    const input = gridEl.value?.querySelector<HTMLInputElement>('.cell-editor')
    input?.focus()
    if (initial === undefined) input?.select()
    else {
      const length = input?.value.length ?? 0
      input?.setSelectionRange(length, length)
    }
    scrollCellIntoView(position)
  })
}

function commitEdit(move: 'down' | 'up' | 'right' | 'left' | 'none' = 'none') {
  if (!editing.value) return
  const address = editAddress.value
  const value = editValue.value
  const before = rawEditText(address)
  editing.value = false
  editValue.value = ''
  if (value !== before) {
    pushHistory()
    applyRawValue(address, value)
    scheduleSave()
  }
  if (move !== 'none') {
    const target = mergeAnchorAt(activeSheet.value, focus.value)
    const delta = {
      down: { row: 1, col: 0 },
      up: { row: -1, col: 0 },
      right: { row: 0, col: 1 },
      left: { row: 0, col: -1 },
    }[move]
    setFocus({ row: target.row + delta.row, col: target.col + delta.col })
  }
  syncBar()
}

function cancelEdit() {
  editing.value = false
  editValue.value = ''
  void nextTick(() => gridEl.value?.focus())
}

function onEditorKeydown(event: KeyboardEvent) {
  if (event.isComposing) return
  if (event.key === 'Enter') {
    event.preventDefault()
    commitEdit(event.shiftKey ? 'up' : 'down')
  } else if (event.key === 'Tab') {
    event.preventDefault()
    commitEdit(event.shiftKey ? 'left' : 'right')
  } else if (event.key === 'Escape') {
    event.preventDefault()
    cancelEdit()
  }
}

// ---------- 选择与导航 ----------

function setFocus(position: CellPosition, extend = false) {
  const target = clampPosition(position, activeSheet.value)
  focus.value = target
  if (!extend) anchor.value = target
  visibleRows.value = Math.max(visibleRows.value, Math.min(target.row + 20, activeSheet.value.rows))
  visibleCols.value = Math.max(visibleCols.value, Math.min(target.col + 6, activeSheet.value.cols))
  void nextTick(() => scrollCellIntoView(target))
}

function scrollCellIntoView(position: CellPosition) {
  const address = cellAddress(position.row, position.col)
  const cell = gridEl.value?.querySelector<HTMLElement>(`[data-sheet-cell="${address}"]`)
  cell?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
}

function nextVisibleRow(row: number, direction: 1 | -1): number {
  let next = row
  for (let step = 0; step < activeSheet.value.rows; step += 1) {
    next += direction
    if (next < 0 || next >= activeSheet.value.rows) return row
    if (!rowHidden(next)) return next
  }
  return row
}

function moveFocus(deltaRow: number, deltaCol: number, extend = false) {
  let row = focus.value.row
  if (deltaRow) {
    const direction: 1 | -1 = deltaRow > 0 ? 1 : -1
    for (let step = 0; step < Math.abs(deltaRow); step += 1) {
      row = nextVisibleRow(row, direction)
    }
  }
  setFocus({ row, col: focus.value.col + deltaCol }, extend)
}

function selectColumn(col: number, extend = false) {
  const sheet = activeSheet.value
  if (extend) {
    focus.value = { row: 0, col }
  } else {
    anchor.value = { row: sheet.rows - 1, col }
    focus.value = { row: 0, col }
  }
  visibleCols.value = Math.max(visibleCols.value, Math.min(col + 6, sheet.cols))
  void nextTick(() => gridEl.value?.focus())
}

function selectRow(row: number, extend = false) {
  const sheet = activeSheet.value
  if (extend) {
    focus.value = { row, col: 0 }
  } else {
    anchor.value = { row, col: sheet.cols - 1 }
    focus.value = { row, col: 0 }
  }
  visibleRows.value = Math.max(visibleRows.value, Math.min(row + 20, sheet.rows))
  void nextTick(() => gridEl.value?.focus())
}

function selectAll() {
  anchor.value = {
    row: activeSheet.value.rows - 1,
    col: activeSheet.value.cols - 1,
  }
  focus.value = { row: 0, col: 0 }
  void nextTick(() => gridEl.value?.focus())
}

let dragging = false
function onCellMouseDown(row: number, col: number, event: MouseEvent) {
  if (event.button !== 0) return
  const position = mergeAnchorAt(activeSheet.value, { row, col })
  if (event.shiftKey) {
    focus.value = position
  } else {
    anchor.value = position
    focus.value = position
  }
  dragging = true
  void nextTick(() => gridEl.value?.focus())
}

function onCellMouseEnter(row: number, col: number) {
  if (!dragging) return
  focus.value = mergeAnchorAt(activeSheet.value, { row, col })
}

function onCellDoubleClick(row: number, col: number) {
  const position = mergeAnchorAt(activeSheet.value, { row, col })
  focus.value = position
  beginEdit()
}

function stopDragging() {
  dragging = false
}

function onGridKeydown(event: KeyboardEvent) {
  if (editing.value || barFocused.value) return
  const modifier = event.ctrlKey || event.metaKey
  const key = event.key

  if (modifier) {
    switch (key.toLowerCase()) {
      case 'c':
        event.preventDefault()
        void copySelection(false)
        return
      case 'x':
        event.preventDefault()
        void copySelection(true)
        return
      case 'v':
        event.preventDefault()
        void pasteFromClipboard()
        return
      case 'z':
        event.preventDefault()
        if (event.shiftKey) redo()
        else undo()
        return
      case 'y':
        event.preventDefault()
        redo()
        return
      case 'a':
        event.preventDefault()
        selectAll()
        return
      case 'b':
        event.preventDefault()
        toggleStyle('bold')
        return
      case 'i':
        event.preventDefault()
        toggleStyle('italic')
        return
      case 'u':
        event.preventDefault()
        toggleStyle('underline')
        return
      case 'home':
        event.preventDefault()
        setFocus({ row: 0, col: 0 })
        return
      default:
        return
    }
  }

  switch (key) {
    case 'ArrowUp':
      event.preventDefault()
      moveFocus(-1, 0, event.shiftKey)
      return
    case 'ArrowDown':
      event.preventDefault()
      moveFocus(1, 0, event.shiftKey)
      return
    case 'ArrowLeft':
      event.preventDefault()
      moveFocus(0, -1, event.shiftKey)
      return
    case 'ArrowRight':
      event.preventDefault()
      moveFocus(0, 1, event.shiftKey)
      return
    case 'Enter':
      event.preventDefault()
      moveFocus(event.shiftKey ? -1 : 1, 0)
      return
    case 'Tab':
      event.preventDefault()
      moveFocus(0, event.shiftKey ? -1 : 1)
      return
    case 'Home':
      event.preventDefault()
      setFocus({ row: focus.value.row, col: 0 }, event.shiftKey)
      return
    case 'End':
      event.preventDefault()
      setFocus(
        { row: focus.value.row, col: Math.max(0, usedBounds.value.maxCol) },
        event.shiftKey,
      )
      return
    case 'PageDown':
      event.preventDefault()
      moveFocus(20, 0, event.shiftKey)
      return
    case 'PageUp':
      event.preventDefault()
      moveFocus(-20, 0, event.shiftKey)
      return
    case 'Delete':
    case 'Backspace':
      event.preventDefault()
      deleteSelectionContents()
      return
    case 'F2':
      event.preventDefault()
      beginEdit()
      return
    case 'Escape':
      anchor.value = focus.value
      return
    default:
      break
  }

  if (key === 'Process' || event.isComposing || event.keyCode === 229) return
  if (key.length === 1 && !event.altKey) {
    event.preventDefault()
    beginEdit(key)
  }
}

// ---------- 剪贴板 ----------

const internalClip = ref<ClipboardSnapshot | null>(null)
const cutMode = ref(false)

function selectionTsv(): string {
  const range = selection.value
  const lines: string[] = []
  for (let row = range.start.row; row <= range.end.row; row += 1) {
    const values: string[] = []
    for (let col = range.start.col; col <= range.end.col; col += 1) {
      const address = cellAddress(row, col)
      const cell = activeSheet.value.cells[address]
      const result = results.value.get(`${activeSheet.value.id}!${address}`)
      const text = cell?.f
        ? displayCell(address)
        : result?.error
          ? result.error
          : formatSheetValue(result?.value ?? null)
      values.push(text.replace(/\t/g, ' ').replace(/\r?\n/g, ' '))
    }
    lines.push(values.join('\t'))
  }
  return lines.join('\n')
}

async function copySelection(cut: boolean) {
  internalClip.value = copyRange(activeSheet.value, selection.value)
  cutMode.value = cut
  const text = selectionTsv()
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 浏览器未授权剪贴板时，内部剪贴板仍然可用
  }
  toast.info(cut ? '已剪切' : '已复制')
}

function pasteTsv(text: string) {
  const rows = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')
  const matrix = rows.map((line) => line.split('\t'))
  if (matrix.length && matrix[matrix.length - 1].length === 1 && matrix[matrix.length - 1][0] === '') {
    matrix.pop()
  }
  if (!matrix.length) return
  pushHistory()
  const start = selection.value.start
  for (let row = 0; row < matrix.length; row += 1) {
    for (let col = 0; col < matrix[row].length; col += 1) {
      const targetRow = start.row + row
      const targetCol = start.col + col
      if (targetRow >= activeSheet.value.rows || targetCol >= activeSheet.value.cols) continue
      applyRawValue(cellAddress(targetRow, targetCol), matrix[row][col])
    }
  }
  const end = {
    row: Math.min(activeSheet.value.rows - 1, start.row + matrix.length - 1),
    col: Math.min(
      activeSheet.value.cols - 1,
      start.col + Math.max(...matrix.map((line) => line.length)) - 1,
    ),
  }
  anchor.value = start
  focus.value = end
  scheduleSave()
}

async function pasteFromClipboard() {
  if (internalClip.value) {
    pushHistory()
    const start = selection.value.start
    pasteSnapshot(activeSheet.value, workbook.value, internalClip.value, start, cutMode.value)
    const snapshot = internalClip.value
    cutMode.value = false
    if (snapshot) {
      anchor.value = start
      focus.value = clampPosition(
        {
          row: start.row + (snapshot.range.end.row - snapshot.range.start.row),
          col: start.col + (snapshot.range.end.col - snapshot.range.start.col),
        },
        activeSheet.value,
      )
    }
    scheduleSave()
    return
  }
  try {
    const text = await navigator.clipboard.readText()
    if (text) pasteTsv(text)
  } catch {
    toast.error('无法读取剪贴板，请使用 Ctrl+C / Ctrl+V')
  }
}

// ---------- 结构操作 ----------

function withHistory(action: () => void) {
  if (editing.value) commitEdit('none')
  pushHistory()
  action()
  scheduleSave()
}

function insertRowAt(index: number, count = 1) {
  withHistory(() => insertRows(activeSheet.value, workbook.value, index, count))
  setFocus({ row: Math.min(index, activeSheet.value.rows - 1), col: focus.value.col })
}

function insertColAt(index: number, count = 1) {
  withHistory(() => insertCols(activeSheet.value, workbook.value, index, count))
  setFocus({ row: focus.value.row, col: Math.min(index, activeSheet.value.cols - 1) })
}

function deleteSelectedRows() {
  const range = selection.value
  const count = range.end.row - range.start.row + 1
  withHistory(() => deleteRows(activeSheet.value, workbook.value, range.start.row, count))
  setFocus({ row: Math.min(range.start.row, activeSheet.value.rows - 1), col: focus.value.col })
}

function deleteSelectedCols() {
  const range = selection.value
  const count = range.end.col - range.start.col + 1
  withHistory(() => deleteCols(activeSheet.value, workbook.value, range.start.col, count))
  setFocus({ row: focus.value.row, col: Math.min(range.start.col, activeSheet.value.cols - 1) })
}

function deleteRowAt(row: number) {
  if (activeSheet.value.rows <= 1) return
  withHistory(() => deleteRows(activeSheet.value, workbook.value, row, 1))
  setFocus({ row: Math.min(row, activeSheet.value.rows - 1), col: focus.value.col })
}

function deleteColAt(col: number) {
  if (activeSheet.value.cols <= 1) return
  withHistory(() => deleteCols(activeSheet.value, workbook.value, col, 1))
  setFocus({ row: focus.value.row, col: Math.min(col, activeSheet.value.cols - 1) })
}

function deleteSelectionContents() {
  if (selection.value.start.row === selection.value.end.row &&
      selection.value.start.col === selection.value.end.col &&
      isCellEmpty(activeCell.value)) {
    return
  }
  withHistory(() => clearContents(activeSheet.value, selection.value))
}

function clearSelectionFormat() {
  withHistory(() =>
    clearStyleKeys(activeSheet.value, selection.value, [
      'bold',
      'italic',
      'underline',
      'color',
      'bg',
      'align',
      'fmt',
    ]),
  )
}

function clearSelectionAll() {
  withHistory(() => clearRangeAll(activeSheet.value, selection.value))
}

function toggleMerge() {
  const sheet = activeSheet.value
  if (rangeHasMerge(sheet, selection.value)) {
    withHistory(() => unmergeRange(sheet, selection.value))
    return
  }
  if (selectionLabel.value === cellAddress(focus.value.row, focus.value.col)) {
    toast.info('请先选择多个单元格')
    return
  }
  withHistory(() => mergeRange(sheet, selection.value))
}

const selectionMerged = computed(() =>
  rangeHasMerge(activeSheet.value, selection.value),
)

// ---------- 格式 ----------

function selectedCells(): Array<{ address: string; cell?: SheetCell }> {
  const sheet = activeSheet.value
  const range = selection.value
  const output: Array<{ address: string; cell?: SheetCell }> = []
  // 大范围只做样式判定时限制采样，避免整列选择造成卡顿
  const maxRows = Math.min(range.end.row - range.start.row + 1, 200)
  const maxCols = Math.min(range.end.col - range.start.col + 1, 50)
  for (let row = range.start.row; row < range.start.row + maxRows; row += 1) {
    for (let col = range.start.col; col < range.start.col + maxCols; col += 1) {
      const address = cellAddress(row, col)
      output.push({ address, cell: sheet.cells[address] })
    }
  }
  return output
}

const allBold = computed(() =>
  selectedCells().every((item) => item.cell?.s?.bold),
)
const allItalic = computed(() =>
  selectedCells().every((item) => item.cell?.s?.italic),
)
const allUnderline = computed(() =>
  selectedCells().every((item) => item.cell?.s?.underline),
)

function toggleStyle(key: 'bold' | 'italic' | 'underline') {
  const enabled = {
    bold: allBold.value,
    italic: allItalic.value,
    underline: allUnderline.value,
  }[key]
  withHistory(() =>
    applyStyle(activeSheet.value, selection.value, { [key]: !enabled }),
  )
}

function applyAlign(align: 'left' | 'center' | 'right') {
  withHistory(() => applyStyle(activeSheet.value, selection.value, { align }))
}

function applyNumberFormat(fmt: SheetNumberFormat) {
  withHistory(() => applyStyle(activeSheet.value, selection.value, { fmt }))
}

function setSheetColor(kind: 'color' | 'bg', color: string | null) {
  if (!color) {
    withHistory(() => clearStyleKeys(activeSheet.value, selection.value, [kind]))
    return
  }
  withHistory(() =>
    applyStyle(activeSheet.value, selection.value, { [kind]: color.toUpperCase() }),
  )
}

const currentFmt = computed(() => activeCell.value?.s?.fmt ?? 'general')

function onFmtChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value as SheetNumberFormat
  applyNumberFormat(value)
}

// ---------- 名称框 / 公式栏 ----------

function syncBar() {
  if (!barFocused.value) {
    barValue.value = editing.value ? editValue.value : rawEditText(activeAddress.value)
  }
  if (!nameFocused.value) nameValue.value = selectionLabel.value
}

watch([activeAddress, editing, editValue, () => results.value], syncBar, { immediate: true })
watch(selectionLabel, syncBar)
watch(editing, (value) => {
  if (!value) syncBar()
})

function onBarFocus() {
  if (editing.value) commitEdit()
  barFocused.value = true
  barDirty.value = false
  barAddress.value = activeAddress.value
  barValue.value = rawEditText(barAddress.value)
}

function onBarInput(event: Event) {
  barDirty.value = true
  barValue.value = (event.target as HTMLInputElement).value
}

function commitBar() {
  if (!barDirty.value) return
  const value = barValue.value
  const address = barAddress.value
  if (value !== rawEditText(address)) {
    withHistory(() => applyRawValue(address, value))
  }
  barDirty.value = false
  syncBar()
}

function onBarKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    event.preventDefault()
    commitBar()
    barFocused.value = false
    void nextTick(() => gridEl.value?.focus())
  } else if (event.key === 'Escape') {
    event.preventDefault()
    barDirty.value = false
    syncBar()
    barFocused.value = false
    void nextTick(() => gridEl.value?.focus())
  }
}

function onBarBlur() {
  commitBar()
  barFocused.value = false
  syncBar()
}

function onNameFocus() {
  nameFocused.value = true
  nameValue.value = selectionLabel.value
}

function onNameKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    event.preventDefault()
    const parsed = parseAddress(nameValue.value)
    if (parsed) {
      setFocus(parsed)
      anchor.value = parsed
    } else {
      nameValue.value = selectionLabel.value
      toast.error('请输入有效单元格地址，例如 B12')
    }
    nameFocused.value = false
    void nextTick(() => gridEl.value?.focus())
  } else if (event.key === 'Escape') {
    nameValue.value = selectionLabel.value
    nameFocused.value = false
    void nextTick(() => gridEl.value?.focus())
  }
}

// ---------- 列宽 / 行高 ----------

let resizeCleanup: (() => void) | null = null

/** 选区是否覆盖整列 / 整行，用于批量调整列宽、行高（Excel 同款）。 */
function selectionSpansAllRows() {
  const sheet = activeSheet.value
  return selection.value.start.row === 0 && selection.value.end.row >= sheet.rows - 1
}

function selectionSpansAllCols() {
  const sheet = activeSheet.value
  return selection.value.start.col === 0 && selection.value.end.col >= sheet.cols - 1
}

/** 全选 / 选中多列时，拖动任意选中列边界会让所有选中列一起生效。 */
function resizeTargetCols(col: number) {
  const range = selection.value
  if (!selectionSpansAllRows() || col < range.start.col || col > range.end.col) {
    return [col]
  }
  return Array.from(
    { length: range.end.col - range.start.col + 1 },
    (_, index) => range.start.col + index,
  )
}

/** 全选 / 选中多行时，拖动任意选中行边界会让所有选中行一起生效。 */
function resizeTargetRows(row: number) {
  const range = selection.value
  if (!selectionSpansAllCols() || row < range.start.row || row > range.end.row) {
    return [row]
  }
  return Array.from(
    { length: range.end.row - range.start.row + 1 },
    (_, index) => range.start.row + index,
  )
}

function startColResize(col: number, event: MouseEvent) {
  event.preventDefault()
  const startX = event.clientX
  const startWidth = columnWidth(col)
  const sheet = activeSheet.value
  const targets = resizeTargetCols(col)
  const move = (moveEvent: MouseEvent) => {
    const width = Math.max(48, Math.min(520, Math.round(startWidth + moveEvent.clientX - startX)))
    for (const target of targets) sheet.colWidths[String(target)] = width
  }
  const up = () => {
    scheduleSave()
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
    resizeCleanup = null
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
  resizeCleanup = up
}

/** 双击列边界 / 表头菜单：按内容自适应列宽（Excel 同款操作）。 */
function autofitCol(col: number, event?: MouseEvent) {
  event?.preventDefault()
  event?.stopPropagation()
  const sheet = activeSheet.value
  const lastRow = Math.min(lastDataRow.value, 800)
  for (const target of resizeTargetCols(col)) {
    let longest = 4
    for (let row = 0; row <= lastRow; row += 1) {
      const text = displayValueAt(row, target)
      if (text) longest = Math.max(longest, Math.min(text.length, 60))
    }
    sheet.colWidths[String(target)] = Math.max(
      MIN_COL_WIDTH,
      Math.min(MAX_COL_WIDTH, longest * 7 + 20),
    )
  }
  scheduleSave()
}

function startRowResize(row: number, event: MouseEvent) {
  event.preventDefault()
  const startY = event.clientY
  const startHeight = rowHeight(row)
  const sheet = activeSheet.value
  const targets = resizeTargetRows(row)
  const move = (moveEvent: MouseEvent) => {
    const height = Math.max(20, Math.min(200, Math.round(startHeight + moveEvent.clientY - startY)))
    for (const target of targets) sheet.rowHeights[String(target)] = height
  }
  const up = () => {
    scheduleSave()
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
    resizeCleanup = null
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
  resizeCleanup = up
}

// ---------- 工作表页签 ----------

const renamingSheetId = ref('')
const renameDraft = ref('')
const dragSheetIndex = ref<number | null>(null)

function selectSheet(id: string) {
  if (editing.value) commitEdit()
  workbook.value.active = id
  scheduleSave()
}

function startRenameSheet(sheet: SheetData) {
  renamingSheetId.value = sheet.id
  renameDraft.value = sheet.name
  void nextTick(() => {
    const input = document.querySelector<HTMLInputElement>('[data-sheet-rename]')
    input?.focus()
    input?.select()
  })
}

function commitRenameSheet() {
  const id = renamingSheetId.value
  if (!id) return
  const sheet = workbook.value.sheets.find((item) => item.id === id)
  renamingSheetId.value = ''
  if (!sheet || !renameDraft.value.trim()) return
  if (renameDraft.value.trim() === sheet.name) return
  withHistory(() => renameSheet(workbook.value, id, renameDraft.value))
}

function onAddSheet() {
  withHistory(() => addSheet(workbook.value))
}

function onDuplicateSheet(id: string) {
  withHistory(() => duplicateSheet(workbook.value, id))
}

function onRemoveSheet(id: string) {
  const sheet = workbook.value.sheets.find((item) => item.id === id)
  if (!sheet) return
  if (workbook.value.sheets.length <= 1) {
    toast.error('至少保留一张工作表')
    return
  }
  if (!window.confirm(`删除工作表「${sheet.name}」？该操作可通过撤销恢复。`)) return
  withHistory(() => removeSheet(workbook.value, id))
}

function onTabDrop(index: number) {
  const from = dragSheetIndex.value
  dragSheetIndex.value = null
  if (from === null || from === index) return
  withHistory(() => moveSheet(workbook.value, from, index))
}

function moveActiveSheet(direction: -1 | 1) {
  const index = workbook.value.sheets.findIndex((item) => item.id === workbook.value.active)
  if (index < 0) return
  const target = index + direction
  if (target < 0 || target >= workbook.value.sheets.length) return
  withHistory(() => moveSheet(workbook.value, index, target))
}

// ---------- 右键菜单 ----------

const contextMenu = ref<{ x: number; y: number; row: number; col: number } | null>(null)
const contextPanel = ref<HTMLElement | null>(null)
const contextPos = ref<Record<string, string>>({})

function openContextMenu(event: MouseEvent, row: number, col: number) {
  event.preventDefault()
  const position = mergeAnchorAt(activeSheet.value, { row, col })
  if (!isCellSelected(position.row, position.col)) {
    anchor.value = position
    focus.value = position
  }
  contextMenu.value = { x: event.clientX, y: event.clientY, row: position.row, col: position.col }
  void nextTick(() => {
    const rect = contextPanel.value?.getBoundingClientRect()
    const width = rect?.width ?? 176
    const height = rect?.height ?? 300
    contextPos.value = {
      left: `${Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8))}px`,
      top: `${Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8))}px`,
    }
  })
}

function closeContextMenu() {
  contextMenu.value = null
}

function contextAction(action: () => void) {
  closeContextMenu()
  action()
}

// ---------- 表头右键菜单 ----------

const headerMenu = ref<{
  kind: 'row' | 'col'
  index: number
  x: number
  y: number
} | null>(null)
const headerPanel = ref<HTMLElement | null>(null)
const headerPos = ref<Record<string, string>>({})

function openHeaderMenu(event: MouseEvent, kind: 'row' | 'col', index: number) {
  event.preventDefault()
  event.stopPropagation()
  headerMenu.value = { kind, index, x: event.clientX, y: event.clientY }
  void nextTick(() => {
    const rect = headerPanel.value?.getBoundingClientRect()
    const width = rect?.width ?? 176
    const height = rect?.height ?? 240
    headerPos.value = {
      left: `${Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8))}px`,
      top: `${Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8))}px`,
    }
  })
}

function closeHeaderMenu() {
  headerMenu.value = null
}

function headerAction(action: () => void) {
  closeHeaderMenu()
  action()
}

function filterFromHeader(col: number) {
  const anchor = headerMenu.value
    ? { left: headerMenu.value.x, bottom: headerMenu.value.y }
    : { left: 8, bottom: 40 }
  closeHeaderMenu()
  openFilterMenuAt(col, anchor)
}

function headerSelect() {
  const menu = headerMenu.value
  if (!menu) return
  closeHeaderMenu()
  if (menu.kind === 'col') selectColumn(menu.index, false)
  else selectRow(menu.index, false)
}

function headerInsert(offset: number) {
  const menu = headerMenu.value
  if (!menu) return
  closeHeaderMenu()
  if (menu.kind === 'col') insertColAt(menu.index + offset)
  else insertRowAt(menu.index + offset)
}

function headerDelete() {
  const menu = headerMenu.value
  if (!menu) return
  closeHeaderMenu()
  if (menu.kind === 'col') deleteColAt(menu.index)
  else deleteRowAt(menu.index)
}

function headerSort(ascending: boolean) {
  const menu = headerMenu.value
  if (!menu || menu.kind !== 'col') return
  closeHeaderMenu()
  sortAtColumn(menu.index, ascending)
}

function headerFilter() {
  const menu = headerMenu.value
  if (!menu || menu.kind !== 'col') return
  filterFromHeader(menu.index)
}

function headerClearFilter() {
  const menu = headerMenu.value
  if (!menu || menu.kind !== 'col') return
  closeHeaderMenu()
  clearColumnFilter(menu.index)
}

function headerAutofit() {
  const menu = headerMenu.value
  if (!menu || menu.kind !== 'col') return
  closeHeaderMenu()
  autofitCol(menu.index)
}

function loadMoreRows() {
  visibleRows.value = Math.min(activeSheet.value.rows, visibleRows.value + 200)
}
function loadMoreCols() {
  visibleCols.value = Math.min(activeSheet.value.cols, visibleCols.value + 20)
}
function addRows(count = 20) {
  withHistory(() => {
    activeSheet.value.rows = Math.min(MAX_ROWS, activeSheet.value.rows + count)
    visibleRows.value = Math.min(activeSheet.value.rows, visibleRows.value + count)
  })
}
function addCols(count = 5) {
  withHistory(() => {
    activeSheet.value.cols = Math.min(MAX_COLS, activeSheet.value.cols + count)
    visibleCols.value = Math.min(activeSheet.value.cols, visibleCols.value + count)
  })
}

// ---------- 生命周期 ----------

onMounted(() => {
  window.addEventListener('mouseup', stopDragging)
})

onBeforeUnmount(() => {
  window.removeEventListener('mouseup', stopDragging)
  resizeCleanup?.()
})

// 外部切换笔记时重载
watch(
  () => props.note.id,
  () => {
    workbook.value = normalizeWorkbook(props.note.props_json?.sheet)
    undoStack.value = []
    redoStack.value = []
    editing.value = false
    anchor.value = { row: 0, col: 0 }
    focus.value = { row: 0, col: 0 }
  },
)
</script>

<template>
  <div class="h-full min-h-0 flex flex-col bg-white">
    <header class="shrink-0 h-11 flex items-center gap-2 px-4 border-b border-slate-200/50 bg-white/40">
      <NoteTitleBreadcrumb
        v-model:title="title"
        :note-id="note.id"
        :emoji="note.props_json?.emoji"
        kind="sheet"
        :folder-id="note.folder_id"
        placeholder="无标题表格"
        @input="scheduleSave"
      />
      <span
        class="shrink-0 rounded-md border border-emerald-100 bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-600"
      >
        表格
      </span>
      <div class="flex-1" />
      <span class="text-[10px] text-slate-400 tabular-nums">
        <template v-if="autosave.saving.value">
          <KiwiIcon name="loader" :size="10" spin class="inline -mt-px mr-1" />保存中…
        </template>
        <template v-else-if="autosave.savedAt.value">已保存 {{ autosave.savedAt.value }}</template>
        <template v-else>自动保存</template>
      </span>
      <NoteTagButton :note="note" />
    </header>

    <!-- 工具栏：与文档编辑器保持同一套毛玻璃视觉，操作按 Excel 分组 -->
    <div class="sheet-toolbar-wrap">
      <div class="sheet-toolbar" data-sheet-toolbar>
      <div class="toolbar-group">
        <button type="button" class="tool-btn" title="撤销 (Ctrl+Z)" :disabled="!canUndo" @click="undo">
          <KiwiIcon name="undo" :size="15" />
        </button>
        <button type="button" class="tool-btn" title="重做 (Ctrl+Y)" :disabled="!canRedo" @click="redo">
          <KiwiIcon name="redo" :size="15" />
        </button>
      </div>

      <span class="toolbar-sep" />

      <div class="toolbar-group">
        <button
          type="button"
          class="tool-btn"
          :class="{ 'is-on': allBold }"
          title="加粗"
          @mousedown.prevent
          @click="toggleStyle('bold')"
        >
          <KiwiIcon name="bold" :size="15" />
        </button>
        <button
          type="button"
          class="tool-btn"
          :class="{ 'is-on': allItalic }"
          title="斜体"
          @mousedown.prevent
          @click="toggleStyle('italic')"
        >
          <KiwiIcon name="italic" :size="15" />
        </button>
        <button
          type="button"
          class="tool-btn"
          :class="{ 'is-on': allUnderline }"
          title="下划线"
          @mousedown.prevent
          @click="toggleStyle('underline')"
        >
          <KiwiIcon name="underline" :size="15" />
        </button>
        <EditorColorPicker
          variant="toolbar"
          title="文字颜色"
          :value="activeCell?.s?.color"
          :active="!!activeCell?.s?.color"
          @select="setSheetColor('color', $event)"
          @clear="setSheetColor('color', null)"
        />
        <EditorColorPicker
          variant="toolbar"
          icon="palette"
          title="填充颜色"
          label="填充颜色"
          fallback="#E2E8F0"
          clear-label="清除填充"
          clear-hint="恢复无填充"
          :value="activeCell?.s?.bg"
          :active="!!activeCell?.s?.bg"
          @select="setSheetColor('bg', $event)"
          @clear="setSheetColor('bg', null)"
        />
      </div>

      <span class="toolbar-sep" />

      <div class="toolbar-group">
        <button type="button" class="tool-btn" title="左对齐" @mousedown.prevent @click="applyAlign('left')">
          <KiwiIcon name="alignLeft" :size="15" />
        </button>
        <button type="button" class="tool-btn" title="居中" @mousedown.prevent @click="applyAlign('center')">
          <KiwiIcon name="alignCenter" :size="15" />
        </button>
        <button type="button" class="tool-btn" title="右对齐" @mousedown.prevent @click="applyAlign('right')">
          <KiwiIcon name="alignRight" :size="15" />
        </button>
        <select class="fmt-select" :value="currentFmt" title="数字格式" @change="onFmtChange">
          <option value="general">常规</option>
          <option value="number">数字</option>
          <option value="percent">百分比</option>
          <option value="currency">货币</option>
          <option value="date">日期</option>
          <option value="text">文本</option>
        </select>
      </div>

      <span class="toolbar-sep" />

      <div class="toolbar-group">
        <button type="button" class="tool-btn" :class="{ 'is-on': selectionMerged }" title="合并 / 取消合并单元格" @mousedown.prevent @click="toggleMerge">
          <KiwiIcon name="columns" :size="15" />
        </button>
        <button type="button" class="tool-btn" title="在上方插入行" @mousedown.prevent @click="insertRowAt(selection.start.row)">
          <KiwiIcon name="plus" :size="13" /><span class="text-[10px]">行</span>
        </button>
        <button type="button" class="tool-btn" title="在左侧插入列" @mousedown.prevent @click="insertColAt(selection.start.col)">
          <KiwiIcon name="plus" :size="13" /><span class="text-[10px]">列</span>
        </button>
        <button type="button" class="tool-btn" title="删除选中行" @mousedown.prevent @click="deleteSelectedRows">
          <KiwiIcon name="minus" :size="13" /><span class="text-[10px]">行</span>
        </button>
        <button type="button" class="tool-btn" title="删除选中列" @mousedown.prevent @click="deleteSelectedCols">
          <KiwiIcon name="minus" :size="13" /><span class="text-[10px]">列</span>
        </button>
      </div>

      </div>
    </div>

    <!-- 名称框 + 公式栏 -->
    <div class="formula-bar">
      <input
        class="name-box"
        :value="nameValue"
        spellcheck="false"
        @focus="onNameFocus"
        @input="nameValue = ($event.target as HTMLInputElement).value"
        @keydown="onNameKeydown"
        @blur="nameFocused = false"
      />
      <span class="fx-label">ƒx</span>
      <input
        class="formula-input"
        :value="barValue"
        spellcheck="false"
        placeholder="输入内容或以 = 开头的公式，例如 =SUM(B2:B10)"
        data-sheet-formula
        @focus="onBarFocus"
        @input="onBarInput"
        @keydown="onBarKeydown"
        @blur="onBarBlur"
      />
      <span class="selection-chip">{{ selectionLabel }}</span>
    </div>

    <!-- 网格 -->
    <div
      ref="gridEl"
      class="sheet-scroll"
      tabindex="0"
      data-sheet-grid
      @keydown="onGridKeydown"
      @contextmenu.prevent
    >
      <table class="sheet-table">
        <colgroup>
          <col style="width: 46px" />
          <col v-for="col in renderCols" :key="`col-${col}`" :style="{ width: `${columnWidth(col - 1)}px` }" />
        </colgroup>
        <thead>
          <tr>
            <th class="corner-cell" title="全选" @click="selectAll" />
            <th
              v-for="col in renderCols"
              :key="`head-${col}`"
              class="col-head"
              :class="{ 'is-active': selection.start.col <= col - 1 && selection.end.col >= col - 1 }"
              :title="`${columnLabel(col - 1)} 列 · 点击选择整列，右键更多操作`"
              @click="selectColumn(col - 1, $event.shiftKey)"
              @contextmenu.prevent="openHeaderMenu($event, 'col', col - 1)"
            >
              <span class="col-head-label">
                {{ columnLabel(col - 1) }}
                <KiwiIcon
                  v-if="sortState?.col === col - 1"
                  :name="sortState.ascending ? 'arrowUp' : 'arrowDown'"
                  :size="8"
                  class="col-sort"
                />
              </span>
              <button
                type="button"
                class="col-filter"
                :class="{
                  'is-on': columnFiltered(col - 1),
                  'is-open': filterMenu?.col === col - 1,
                }"
                title="排序与筛选"
                :data-col-filter="col - 1"
                @mousedown.stop.prevent
                @click.stop.prevent="openFilterMenu(col - 1, $event)"
              >
                <KiwiIcon name="filter" :size="9" />
              </button>
              <span
                class="col-resize"
                title="拖动调整列宽，双击自适应"
                @mousedown.stop.prevent="startColResize(col - 1, $event)"
                @dblclick.stop="autofitCol(col - 1, $event)"
                @click.stop
              />
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in renderRowNumbers"
            :key="`row-${row}`"
            :style="{ height: `${rowHeight(row - 1)}px` }"
          >
            <th
              class="row-head"
              :class="{ 'is-active': selection.start.row <= row - 1 && selection.end.row >= row - 1 }"
              :title="`第 ${row} 行 · 点击选择整行，右键更多操作`"
              @click="selectRow(row - 1, $event.shiftKey)"
              @contextmenu.prevent="openHeaderMenu($event, 'row', row - 1)"
            >
              {{ row }}
              <span
                class="row-resize"
                @mousedown.stop.prevent="startRowResize(row - 1, $event)"
                @click.stop
              />
            </th>
            <template v-for="col in renderCols" :key="`cell-${row}-${col}`">
              <td
                v-if="!layout.covered.has(cellAddress(row - 1, col - 1))"
                :data-sheet-cell="cellAddress(row - 1, col - 1)"
                :rowspan="cellSpan(row - 1, col - 1)?.rowSpan"
                :colspan="cellSpan(row - 1, col - 1)?.colSpan"
                class="sheet-cell"
                :class="{
                  'is-selected': isCellSelected(row - 1, col - 1),
                  'is-active': activeAddress === cellAddress(row - 1, col - 1),
                  'is-error': cellIsError(cellAddress(row - 1, col - 1)),
                }"
                :style="{
                  ...cellStyle(cellAddress(row - 1, col - 1)),
                  textAlign: cellAlign(cellAddress(row - 1, col - 1)),
                }"
                @mousedown="onCellMouseDown(row - 1, col - 1, $event)"
                @mouseenter="onCellMouseEnter(row - 1, col - 1)"
                @dblclick="onCellDoubleClick(row - 1, col - 1)"
                @contextmenu="openContextMenu($event, row - 1, col - 1)"
              >
                <input
                  v-if="editing && editAddress === cellAddress(row - 1, col - 1)"
                  v-model="editValue"
                  class="cell-editor"
                  spellcheck="false"
                  @keydown="onEditorKeydown"
                  @blur="commitEdit('none')"
                  @mousedown.stop
                  @dblclick.stop
                />
                <span v-else class="cell-text">{{ displayCell(cellAddress(row - 1, col - 1)) }}</span>
              </td>
            </template>
          </tr>
        </tbody>
      </table>
      <div v-if="hiddenRows > 0 || hiddenCols > 0" class="load-more">
        <span v-if="hiddenRows > 0">
          还有 {{ hiddenRows }} 行未渲染
          <button type="button" class="link-btn" @click="loadMoreRows">显示更多</button>
        </span>
        <span v-if="hiddenCols > 0">
          还有 {{ hiddenCols }} 列未渲染
          <button type="button" class="link-btn" @click="loadMoreCols">显示更多</button>
        </span>
        <span v-if="filteredOutRows > 0">
          筛选隐藏 {{ filteredOutRows }} 行
          <button v-if="hasActiveFilters" type="button" class="link-btn" @click="clearAllFilters">
            清除筛选
          </button>
        </span>
      </div>
    </div>

    <!-- 状态栏：选区统计 + 筛选状态 -->
    <div class="sheet-status">
      <span class="selection-chip">{{ selectionLabel }}</span>
      <span v-if="selectionStats.count" class="status-item">
        计数 <b>{{ selectionStats.count }}</b>
      </span>
      <span v-if="selectionStats.numericCount" class="status-item">
        求和 <b>{{ formatSheetValue(selectionStats.sum, 'number') }}</b>
      </span>
      <span v-if="selectionStats.numericCount" class="status-item">
        平均值 <b>{{ formatSheetValue(selectionStats.average, 'number') }}</b>
      </span>
      <span v-if="selectionStats.sampled" class="status-item text-slate-400">抽样统计</span>
      <div class="flex-1" />
      <button
        v-if="hasActiveFilters"
        type="button"
        class="status-filter"
        title="清除全部筛选"
        data-sheet-clear-filters
        @click="clearAllFilters"
      >
        <KiwiIcon name="filter" :size="10" />
        已筛选 {{ activeFilterCount }} 列 · 清除
      </button>
      <span v-else class="status-hint">双击列边界自适应列宽 · 右键行列标题查看更多</span>
      <span class="status-item text-slate-400">
        {{ renderRowNumbers.length }} 行 × {{ renderCols }} 列
      </span>
    </div>

    <!-- 工作表页签 -->
    <footer class="sheet-tabs">
      <button type="button" class="tab-arrow" title="工作表左移" @click="moveActiveSheet(-1)">
        <KiwiIcon name="chevronRight" :size="13" class="rotate-180" />
      </button>
      <div class="tabs-scroll">
        <div
          v-for="(sheet, index) in workbook.sheets"
          :key="sheet.id"
          class="sheet-tab"
          :class="{ 'is-active': sheet.id === workbook.active }"
          draggable="true"
          :data-sheet-tab="sheet.name"
          @click="selectSheet(sheet.id)"
          @dblclick.stop="startRenameSheet(sheet)"
          @dragstart="dragSheetIndex = index"
          @dragover.prevent
          @drop="onTabDrop(index)"
          @contextmenu.prevent="startRenameSheet(sheet)"
        >
          <input
            v-if="renamingSheetId === sheet.id"
            v-model="renameDraft"
            data-sheet-rename
            class="tab-rename"
            @keydown.enter.prevent="commitRenameSheet"
            @keydown.esc.prevent="renamingSheetId = ''"
            @blur="commitRenameSheet"
            @click.stop
          />
          <span v-else class="truncate">{{ sheet.name }}</span>
        </div>
      </div>
      <button type="button" class="tab-add" title="新建工作表" @click="onAddSheet">
        <KiwiIcon name="plus" :size="14" />
      </button>
      <div class="flex-1" />
      <div class="tab-actions">
        <button type="button" class="tab-action" title="重命名当前工作表" @click="startRenameSheet(activeSheet)">
          <KiwiIcon name="edit" :size="13" />
        </button>
        <button type="button" class="tab-action" title="复制当前工作表" @click="onDuplicateSheet(activeSheet.id)">
          <KiwiIcon name="copy" :size="13" />
        </button>
        <button type="button" class="tab-action" title="工作表右移" @click="moveActiveSheet(1)">
          <KiwiIcon name="chevronRight" :size="13" />
        </button>
        <button type="button" class="tab-action" title="删除当前工作表" @click="onRemoveSheet(activeSheet.id)">
          <KiwiIcon name="trash" :size="13" />
        </button>
        <span class="text-[10px] text-slate-400 tabular-nums">
          {{ renderRowNumbers.length }} / {{ renderRows }} 行 × {{ renderCols }} 列 ·
          {{ Object.keys(activeSheet.cells).length }} 个单元格
        </span>
      </div>
    </footer>

    <!-- 右键菜单：挂到 html 下，避免 body zoom 造成坐标漂移 -->
    <Teleport to="html">
      <div
        v-if="contextMenu"
        class="fixed inset-0 z-[95]"
        @mousedown="closeContextMenu"
        @contextmenu.prevent="closeContextMenu"
      >
        <div class="absolute" :style="contextPos">
          <div
            ref="contextPanel"
            class="sheet-context"
            :style="{ zoom: 'var(--ui-scale)' }"
            @mousedown.stop
          >
            <button type="button" class="ctx-row" @click="contextAction(() => insertRowAt(selection.start.row))">
              上方插入行
            </button>
            <button type="button" class="ctx-row" @click="contextAction(() => insertRowAt(selection.end.row + 1))">
              下方插入行
            </button>
            <button type="button" class="ctx-row" @click="contextAction(deleteSelectedRows)">
              删除选中行
            </button>
            <div class="ctx-sep" />
            <button type="button" class="ctx-row" @click="contextAction(() => insertColAt(selection.start.col))">
              左侧插入列
            </button>
            <button type="button" class="ctx-row" @click="contextAction(() => insertColAt(selection.end.col + 1))">
              右侧插入列
            </button>
            <button type="button" class="ctx-row" @click="contextAction(deleteSelectedCols)">
              删除选中列
            </button>
            <div class="ctx-sep" />
            <button type="button" class="ctx-row" @click="contextAction(toggleMerge)">
              {{ selectionMerged ? '取消合并单元格' : '合并单元格' }}
            </button>
            <button type="button" class="ctx-row" @click="contextAction(deleteSelectionContents)">
              清除内容
            </button>
            <button type="button" class="ctx-row" @click="contextAction(clearSelectionFormat)">
              清除格式
            </button>
            <button type="button" class="ctx-row" @click="contextAction(clearSelectionAll)">
              删除单元格
            </button>
            <div class="ctx-sep" />
            <button type="button" class="ctx-row" @click="contextAction(() => copySelection(false))">
              复制
            </button>
            <button type="button" class="ctx-row" @click="contextAction(() => copySelection(true))">
              剪切
            </button>
            <button type="button" class="ctx-row" @click="contextAction(pasteFromClipboard)">
              粘贴
            </button>
            <div class="ctx-sep" />
            <button type="button" class="ctx-row" @click="contextAction(() => addRows(20))">
              追加 20 行
            </button>
            <button type="button" class="ctx-row" @click="contextAction(() => addCols(5))">
              追加 5 列
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 列筛选面板：与「扩展组件」菜单同一套毛玻璃 UI -->
    <Teleport to="html">
      <div
        v-if="filterMenu"
        class="fixed inset-0 z-[96]"
        data-sheet-filter-panel
        @mousedown="closeFilterMenu"
        @contextmenu.prevent="closeFilterMenu"
        @keydown.esc.stop="closeFilterMenu"
      >
        <div class="absolute" :style="{ left: filterMenu.left, top: filterMenu.top }">
          <div
            class="w-[252px] rounded-xl border border-slate-200/90 bg-white/40 p-1.5 shadow-xl backdrop-blur-2xl"
            :style="{ zoom: 'var(--ui-scale)' }"
            @mousedown.stop
          >
            <p
              class="flex items-center justify-between px-2 pb-1 pt-1 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400"
            >
              <span class="flex items-center gap-1.5">
                <KiwiIcon name="filter" :size="10" />
                筛选 · {{ columnLabel(filterMenu.col) }} 列
              </span>
              <button
                type="button"
                class="grid h-5 w-5 place-items-center rounded-md text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
                title="关闭"
                @click="closeFilterMenu"
              >
                <KiwiIcon name="close" :size="11" />
              </button>
            </p>
            <div class="grid grid-cols-2 gap-1 px-1 pb-1">
              <button type="button" class="filter-action" @click="sortFromFilter(true)">
                <KiwiIcon name="arrowUp" :size="12" />升序
              </button>
              <button type="button" class="filter-action" @click="sortFromFilter(false)">
                <KiwiIcon name="arrowDown" :size="12" />降序
              </button>
            </div>
            <div class="my-1 h-px bg-slate-100" />
            <label
              class="mx-1 flex h-7 items-center gap-1.5 rounded-lg border border-slate-200/80 bg-white/70 px-2"
            >
              <KiwiIcon name="search" :size="11" class="shrink-0 text-slate-400" />
              <input
                v-model="filterSearch"
                class="min-w-0 flex-1 border-0 bg-transparent text-[11.5px] text-slate-700 outline-none placeholder:text-slate-400"
                placeholder="搜索值…"
                @keydown.stop
                @mousedown.stop
              />
            </label>
            <label
              class="filter-check mt-1 font-medium"
              @click.prevent="toggleAllFilterValues"
            >
              <input type="checkbox" :checked="allVisibleFilterSelected" tabindex="-1" />
              <span class="flex-1">全选</span>
              <span class="text-[10px] text-slate-400 tabular-nums">
                {{ filterDraft.length }}/{{ filterValues.length }}
              </span>
            </label>
            <div class="mt-0.5 max-h-[220px] overflow-y-auto">
              <label v-for="item in visibleFilterValues" :key="item.key" class="filter-check">
                <input
                  type="checkbox"
                  :checked="filterDraft.includes(item.key)"
                  @change="toggleFilterValue(item.key)"
                />
                <span class="min-w-0 flex-1 truncate" :title="item.label">{{ item.label }}</span>
                <span class="shrink-0 text-[10px] text-slate-400 tabular-nums">{{ item.count }}</span>
              </label>
              <p
                v-if="!visibleFilterValues.length"
                class="px-3 py-4 text-center text-[11px] text-slate-400"
              >
                没有匹配的值
              </p>
            </div>
            <div class="mt-1 flex items-center gap-1 border-t border-slate-100 px-1 pt-1.5">
              <button
                type="button"
                class="filter-link"
                :disabled="!columnFiltered(filterMenu.col)"
                @click="clearColumnFilter(filterMenu.col)"
              >
                清除筛选
              </button>
              <div class="flex-1" />
              <button type="button" class="filter-cancel" @click="closeFilterMenu">取消</button>
              <button type="button" class="filter-apply" @click="applyColumnFilter">确定</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 行 / 列表头右键菜单 -->
    <Teleport to="html">
      <div
        v-if="headerMenu"
        class="fixed inset-0 z-[96]"
        @mousedown="closeHeaderMenu"
        @contextmenu.prevent="closeHeaderMenu"
      >
        <div class="absolute" :style="headerPos">
          <div
            ref="headerPanel"
            class="sheet-context"
            :style="{ zoom: 'var(--ui-scale)' }"
            @mousedown.stop
          >
            <p class="px-2 pb-1 pt-1 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
              {{
                headerMenu.kind === 'col'
                  ? `${columnLabel(headerMenu.index)} 列`
                  : `第 ${headerMenu.index + 1} 行`
              }}
            </p>
            <button type="button" class="ctx-row" @click="headerSelect">
              选中整{{ headerMenu.kind === 'col' ? '列' : '行' }}
            </button>
            <div class="ctx-sep" />
            <button type="button" class="ctx-row" @click="headerInsert(0)">
              {{ headerMenu.kind === 'col' ? '左侧插入列' : '上方插入行' }}
            </button>
            <button type="button" class="ctx-row" @click="headerInsert(1)">
              {{ headerMenu.kind === 'col' ? '右侧插入列' : '下方插入行' }}
            </button>
            <button type="button" class="ctx-row" @click="headerDelete">
              删除此{{ headerMenu.kind === 'col' ? '列' : '行' }}
            </button>
            <template v-if="headerMenu.kind === 'col'">
              <div class="ctx-sep" />
              <button type="button" class="ctx-row" @click="headerSort(true)">按此列升序</button>
              <button type="button" class="ctx-row" @click="headerSort(false)">按此列降序</button>
              <button type="button" class="ctx-row" @click="headerFilter">筛选此列…</button>
              <button
                type="button"
                class="ctx-row"
                :disabled="!columnFiltered(headerMenu.index)"
                @click="headerClearFilter"
              >
                清除此列筛选
              </button>
              <div class="ctx-sep" />
              <button type="button" class="ctx-row" @click="headerAutofit">自适应列宽</button>
            </template>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.sheet-toolbar-wrap {
  flex-shrink: 0;
  padding: 6px 10px 8px;
}
.sheet-toolbar {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: nowrap;
  overflow-x: auto;
  scrollbar-width: none;
  padding: 6px;
  border-radius: 12px;
  border: 1px solid rgb(226 232 240 / 0.7);
  background: rgb(255 255 255 / 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.toolbar-group {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 2px;
  padding: 0 1px;
}
.toolbar-sep {
  flex-shrink: 0;
  width: 1px;
  height: 16px;
  margin: 0 4px;
  background: rgb(226 232 240 / 0.8);
}
.tool-btn {
  display: inline-flex;
  flex-shrink: 0;
  white-space: nowrap;
  align-items: center;
  justify-content: center;
  gap: 3px;
  height: 28px;
  min-width: 28px;
  padding: 0 6px;
  border-radius: 8px;
  color: #64748b;
  transition: background-color 120ms, color 120ms;
}
.tool-btn:hover {
  background: rgb(var(--kiwi-50));
  color: rgb(var(--kiwi-700));
}
.tool-btn.is-on {
  background: rgb(var(--kiwi-100) / 0.8);
  color: rgb(var(--kiwi-700));
}
.tool-btn:disabled {
  opacity: 0.35;
  cursor: default;
}
.fmt-select {
  height: 28px;
  border: 1px solid rgb(226 232 240 / 0.8);
  border-radius: 8px;
  background: rgb(255 255 255 / 0.8);
  font-size: 11px;
  color: #64748b;
  padding: 0 6px;
  outline: none;
  transition: border-color 120ms, color 120ms;
}
.fmt-select:hover {
  border-color: rgb(var(--kiwi-200));
  color: rgb(var(--kiwi-700));
}
.formula-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border-bottom: 1px solid rgb(226 232 240 / 0.7);
  flex-shrink: 0;
  background: white;
}
.name-box {
  width: 92px;
  height: 26px;
  border: 1px solid rgb(226 232 240);
  border-radius: 6px;
  padding: 0 8px;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: #334155;
  outline: none;
}
.name-box:focus {
  border-color: rgb(56 189 248);
  box-shadow: 0 0 0 2px rgb(186 230 253 / 0.6);
}
.fx-label {
  font-size: 12px;
  font-style: italic;
  color: #94a3b8;
  flex-shrink: 0;
}
.formula-input {
  flex: 1;
  min-width: 0;
  height: 26px;
  border: 1px solid rgb(226 232 240);
  border-radius: 6px;
  padding: 0 10px;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: #0f172a;
  outline: none;
}
.formula-input:focus {
  border-color: rgb(56 189 248);
  box-shadow: 0 0 0 2px rgb(186 230 253 / 0.6);
}
.selection-chip {
  flex-shrink: 0;
  border-radius: 5px;
  background: rgb(241 245 249);
  padding: 2px 6px;
  font-size: 10px;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
.sheet-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  outline: none;
  background: #fff;
  scrollbar-width: thin;
}
.sheet-table {
  border-collapse: separate;
  border-spacing: 0;
  table-layout: fixed;
  width: max-content;
  min-width: 100%;
  font-size: 12px;
}
.sheet-table th,
.sheet-table td {
  border-right: 1px solid rgb(226 232 240);
  border-bottom: 1px solid rgb(226 232 240);
  padding: 0;
  overflow: hidden;
}
.corner-cell {
  position: sticky;
  left: 0;
  top: 0;
  z-index: 5;
  width: 46px;
  min-width: 46px;
  background: #f8fafc;
  cursor: pointer;
}
.col-head {
  position: sticky;
  top: 0;
  z-index: 3;
  height: 28px;
  padding: 0 12px;
  background: #f8fafc;
  color: #475569;
  font-weight: 500;
  font-size: 11px;
  cursor: pointer;
  user-select: none;
}
.col-head.is-active {
  background: #e0f2fe;
  color: #0369a1;
}
.col-head-label {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  vertical-align: middle;
}
.col-sort {
  color: #0284c7;
}
.col-filter {
  position: absolute;
  right: 7px;
  top: 50%;
  z-index: 3;
  display: inline-grid;
  place-items: center;
  width: 14px;
  height: 14px;
  border-radius: 4px;
  color: #94a3b8;
  opacity: 0.75;
  transform: translateY(-50%);
  transition: opacity 120ms, background-color 120ms, color 120ms;
}
.col-head:hover .col-filter,
.col-head.is-active .col-filter,
.col-filter.is-on,
.col-filter.is-open {
  opacity: 1;
}
.col-filter:hover {
  background: rgb(224 242 254);
  color: #0369a1;
}
.col-filter.is-on,
.col-filter.is-open {
  background: rgb(224 242 254);
  color: #0284c7;
}
.row-head {
  position: sticky;
  left: 0;
  z-index: 2;
  width: 46px;
  min-width: 46px;
  background: #f8fafc;
  color: #64748b;
  font-weight: 400;
  font-size: 10.5px;
  text-align: center;
  cursor: pointer;
  user-select: none;
  font-variant-numeric: tabular-nums;
}
.row-head.is-active {
  background: #e0f2fe;
  color: #0369a1;
}
.col-resize {
  position: absolute;
  top: 0;
  right: 0;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 4;
}
.col-head {
  position: sticky;
}
.col-head .col-resize:hover {
  background: rgb(56 189 248 / 0.4);
}
.row-resize {
  position: absolute;
  left: 0;
  bottom: 0;
  width: 100%;
  height: 6px;
  cursor: row-resize;
  z-index: 4;
}
.row-resize:hover {
  background: rgb(56 189 248 / 0.4);
}
.row-head {
  position: sticky;
}
.sheet-cell {
  position: relative;
  padding: 0 6px;
  background: white;
  color: #0f172a;
  white-space: nowrap;
  cursor: cell;
  user-select: none;
  overflow: hidden;
}
.sheet-cell.is-selected {
  background-image: linear-gradient(rgb(224 242 254 / 0.55), rgb(224 242 254 / 0.55));
}
.sheet-cell.is-active {
  outline: 2px solid #0ea5e9;
  outline-offset: -2px;
  z-index: 1;
}
.sheet-cell.is-error {
  color: #dc2626;
}
.cell-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.35;
  pointer-events: none;
}
.cell-editor {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 2px solid #0ea5e9;
  padding: 0 4px;
  font: inherit;
  font-size: 12px;
  color: #0f172a;
  background: white;
  outline: none;
  z-index: 2;
}
.load-more {
  position: sticky;
  left: 0;
  display: flex;
  gap: 18px;
  padding: 8px 12px;
  font-size: 10.5px;
  color: #94a3b8;
  background: #f8fafc;
}
.link-btn {
  color: #0284c7;
  text-decoration: underline;
  margin-left: 4px;
}
.sheet-status {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  height: 26px;
  padding: 0 10px;
  border-top: 1px solid rgb(226 232 240 / 0.7);
  background: rgb(248 250 252 / 0.85);
  font-size: 10.5px;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
.status-item b {
  font-weight: 600;
  color: #334155;
}
.status-filter {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  background: rgb(224 242 254);
  color: #0369a1;
  font-size: 10px;
}
.status-filter:hover {
  background: rgb(186 230 253);
}
.status-hint {
  font-size: 10px;
  color: #94a3b8;
}
.sheet-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  height: 34px;
  padding: 0 8px;
  border-top: 1px solid rgb(226 232 240 / 0.8);
  background: rgb(248 250 252);
}
.tab-arrow,
.tab-add,
.tab-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 5px;
  color: #64748b;
}
.tab-arrow:hover,
.tab-add:hover,
.tab-action:hover {
  background: rgb(226 232 240);
  color: #0f172a;
}
.tabs-scroll {
  display: flex;
  align-items: center;
  gap: 3px;
  max-width: 60%;
  overflow-x: auto;
  scrollbar-width: none;
}
.sheet-tab {
  display: inline-flex;
  align-items: center;
  height: 25px;
  max-width: 150px;
  padding: 0 10px;
  border-radius: 6px;
  font-size: 11px;
  color: #64748b;
  cursor: pointer;
  user-select: none;
  border: 1px solid transparent;
}
.sheet-tab:hover {
  background: rgb(241 245 249);
}
.sheet-tab.is-active {
  background: white;
  border-color: rgb(186 230 253);
  color: #0369a1;
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.04);
}
.tab-rename {
  width: 92px;
  border: 0;
  outline: none;
  background: transparent;
  font-size: 11px;
  color: inherit;
}
.tab-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}
.sheet-context {
  width: 188px;
  border-radius: 12px;
  border: 1px solid rgb(226 232 240 / 0.9);
  background: rgb(255 255 255 / 0.42);
  backdrop-filter: blur(28px);
  -webkit-backdrop-filter: blur(28px);
  box-shadow: 0 20px 45px -20px rgb(15 23 42 / 0.35);
  padding: 4px;
}
.ctx-row {
  width: 100%;
  text-align: left;
  padding: 6px 10px;
  border-radius: 7px;
  font-size: 11.5px;
  color: #334155;
}
.ctx-row:hover:not(:disabled) {
  background: rgb(240 249 255);
}
.ctx-row:disabled {
  opacity: 0.4;
  cursor: default;
}
.ctx-sep {
  height: 1px;
  margin: 3px 6px;
  background: rgb(241 245 249);
}
.filter-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 26px;
  border-radius: 7px;
  color: #475569;
  font-size: 11px;
  transition: background-color 120ms, color 120ms;
}
.filter-action:hover {
  background: rgb(240 249 255);
  color: #0369a1;
}
.filter-check {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 4px 8px;
  border-radius: 7px;
  font-size: 11.5px;
  color: #334155;
  text-align: left;
  cursor: pointer;
}
.filter-check:hover {
  background: rgb(240 249 255);
}
.filter-check input[type='checkbox'] {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
  accent-color: #0ea5e9;
  cursor: pointer;
}
.filter-link {
  padding: 0 4px;
  border-radius: 4px;
  font-size: 10.5px;
  color: #0284c7;
}
.filter-link:hover:not(:disabled) {
  text-decoration: underline;
}
.filter-link:disabled {
  color: #cbd5e1;
  cursor: default;
}
.filter-cancel,
.filter-apply {
  height: 24px;
  padding: 0 10px;
  border-radius: 7px;
  font-size: 11px;
}
.filter-cancel {
  color: #64748b;
}
.filter-cancel:hover {
  background: rgb(241 245 249);
}
.filter-apply {
  background: #0ea5e9;
  color: #fff;
}
.filter-apply:hover {
  background: #0284c7;
}
</style>
