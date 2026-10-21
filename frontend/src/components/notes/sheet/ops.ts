/**
 * 工作表结构操作：插入 / 删除行列、合并单元格、样式、复制粘贴、
 * 工作表增删改名。所有函数直接修改传入的工作簿副本，调用方负责快照撤销。
 */
import type {
  CellRange,
  CellValue,
  SheetCell,
  SheetCellStyle,
  SheetData,
  SheetWorkbook,
} from './types'
import {
  DEFAULT_COLS,
  DEFAULT_ROWS,
  MAX_COLS,
  MAX_ROWS,
  cellAddress,
  cloneSheet,
  columnLabel,
  mergeLayout,
  normalizedRange,
  parseAddress,
  parseRange,
  rangeAddress,
} from './types'
import { shiftFormula, translateFormula } from './formula'

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

function eachCellInRange(
  range: CellRange,
  callback: (address: string, row: number, col: number) => void,
) {
  const normalized = normalizedRange(range)
  for (let row = normalized.start.row; row <= normalized.end.row; row += 1) {
    for (let col = normalized.start.col; col <= normalized.end.col; col += 1) {
      callback(cellAddress(row, col), row, col)
    }
  }
}

export function ensureCell(sheet: SheetData, address: string): SheetCell {
  sheet.cells[address] ??= {}
  return sheet.cells[address]
}

export function setCellValue(
  sheet: SheetData,
  address: string,
  value: CellValue,
  formula?: string,
) {
  const cell = ensureCell(sheet, address)
  if (formula) {
    cell.f = formula
    delete cell.v
  } else {
    delete cell.f
    if (value === null || value === '') delete cell.v
    else cell.v = value
    delete cell.cached
  }
}

export function isCellEmpty(cell: SheetCell | undefined): boolean {
  return !cell || (!cell.f && (cell.v === undefined || cell.v === null || cell.v === ''))
}

export function clearContents(sheet: SheetData, range: CellRange) {
  eachCellInRange(range, (address) => {
    const cell = sheet.cells[address]
    if (!cell) return
    delete cell.v
    delete cell.f
    delete cell.cached
    if (!cell.s || !Object.keys(cell.s).length) delete sheet.cells[address]
  })
}

export function clearRangeAll(sheet: SheetData, range: CellRange) {
  eachCellInRange(range, (address) => {
    delete sheet.cells[address]
  })
  sheet.merges = sheet.merges.filter((raw) => {
    const parsed = parseRange(raw)
    if (!parsed) return false
    const normalized = normalizedRange(range)
    return (
      parsed.end.row < normalized.start.row ||
      parsed.start.row > normalized.end.row ||
      parsed.end.col < normalized.start.col ||
      parsed.start.col > normalized.end.col
    )
  })
}

export function applyStyle(sheet: SheetData, range: CellRange, patch: Partial<SheetCellStyle>) {
  eachCellInRange(range, (address) => {
    const cell = ensureCell(sheet, address)
    cell.s ??= {}
    Object.assign(cell.s, patch)
  })
}

export function clearStyleKeys(
  sheet: SheetData,
  range: CellRange,
  keys: Array<keyof SheetCellStyle>,
) {
  eachCellInRange(range, (address) => {
    const cell = sheet.cells[address]
    if (!cell?.s) return
    for (const key of keys) delete cell.s[key]
    if (!Object.keys(cell.s).length && isCellEmpty(cell)) delete sheet.cells[address]
  })
}

// ---------- 行列结构 ----------

function shiftAllFormulas(
  workbook: SheetWorkbook,
  sheetName: string,
  axis: 'row' | 'col',
  index: number,
  delta: number,
) {
  for (const sheet of workbook.sheets) {
    const ownSheet = sheet.name.toLowerCase() === sheetName.toLowerCase()
    for (const cell of Object.values(sheet.cells)) {
      if (cell.f) cell.f = shiftFormula(cell.f, sheetName, axis, index, delta, !ownSheet)
    }
  }
}

function adjustMergesInsert(
  sheet: SheetData,
  axis: 'row' | 'col',
  index: number,
  count: number,
) {
  const max = axis === 'row' ? sheet.rows : sheet.cols
  const merges: string[] = []
  for (const raw of sheet.merges) {
    const range = parseRange(raw)
    if (!range) continue
    if (axis === 'row') {
      if (range.start.row >= index) {
        range.start.row += count
        range.end.row += count
      } else if (range.end.row >= index) {
        range.end.row += count
      }
    } else if (range.start.col >= index) {
      range.start.col += count
      range.end.col += count
    } else if (range.end.col >= index) {
      range.end.col += count
    }
    if (range.end.row >= max || range.end.col >= sheet.cols) {
      range.end.row = Math.min(range.end.row, max - 1)
      range.end.col = Math.min(range.end.col, sheet.cols - 1)
    }
    if (range.end.row < range.start.row || range.end.col < range.start.col) continue
    merges.push(rangeAddress(range))
  }
  sheet.merges = merges
}

/** 插入 / 删除列时同步移动筛选列索引，避免筛选落到错误的列。 */
function shiftFilters(sheet: SheetData, at: number, amount: number) {
  if (!sheet.filters) return
  const next: Record<string, string[]> = {}
  for (const [key, values] of Object.entries(sheet.filters)) {
    const col = Number(key)
    if (amount > 0) {
      next[String(col >= at ? col + amount : col)] = values
      continue
    }
    const removed = -amount
    if (col >= at && col < at + removed) continue
    next[String(col >= at + removed ? col - removed : col)] = values
  }
  if (Object.keys(next).length) sheet.filters = next
  else delete sheet.filters
}

function adjustMergesDelete(
  sheet: SheetData,
  axis: 'row' | 'col',
  index: number,
  count: number,
) {
  const deletedEnd = index + count - 1
  const merges: string[] = []
  for (const raw of sheet.merges) {
    const range = parseRange(raw)
    if (!range) continue
    let start = axis === 'row' ? range.start.row : range.start.col
    let end = axis === 'row' ? range.end.row : range.end.col
    if (end < index) {
      merges.push(raw)
      continue
    }
    if (start > deletedEnd) {
      start -= count
      end -= count
    } else if (start >= index && end <= deletedEnd) {
      continue
    } else if (start < index && end <= deletedEnd) {
      end = index - 1
    } else if (start >= index) {
      start = index
      end -= count
    } else {
      end -= count
    }
    if (start < 0 || end < start) continue
    if (axis === 'row') {
      merges.push(rangeAddress({ start: { row: start, col: range.start.col }, end: { row: end, col: range.end.col } }))
    } else {
      merges.push(rangeAddress({ start: { row: range.start.row, col: start }, end: { row: range.end.row, col: end } }))
    }
  }
  sheet.merges = merges
}

export function insertRows(
  sheet: SheetData,
  workbook: SheetWorkbook,
  index: number,
  count = 1,
) {
  const at = clamp(index, 0, sheet.rows)
  const amount = Math.max(1, Math.min(count, MAX_ROWS - sheet.rows))
  if (!amount) return
  shiftAllFormulas(workbook, sheet.name, 'row', at, amount)
  const cells: Record<string, SheetCell> = {}
  for (const [address, cell] of Object.entries(sheet.cells)) {
    const parsed = parseAddress(address)
    if (!parsed) continue
    if (parsed.row >= at) parsed.row += amount
    if (parsed.row >= MAX_ROWS) continue
    cells[cellAddress(parsed.row, parsed.col)] = cell
  }
  sheet.cells = cells
  const heights: Record<string, number> = {}
  for (const [key, value] of Object.entries(sheet.rowHeights)) {
    const row = Number(key)
    if (row >= at) {
      if (row + amount < MAX_ROWS) heights[String(row + amount)] = value
    } else {
      heights[key] = value
    }
  }
  sheet.rowHeights = heights
  sheet.rows = Math.min(MAX_ROWS, sheet.rows + amount)
  adjustMergesInsert(sheet, 'row', at, amount)
}

export function deleteRows(
  sheet: SheetData,
  workbook: SheetWorkbook,
  index: number,
  count = 1,
) {
  if (sheet.rows <= 1) return
  const at = clamp(index, 0, sheet.rows - 1)
  const amount = clamp(count, 1, sheet.rows - at)
  shiftAllFormulas(workbook, sheet.name, 'row', at, -amount)
  const cells: Record<string, SheetCell> = {}
  for (const [address, cell] of Object.entries(sheet.cells)) {
    const parsed = parseAddress(address)
    if (!parsed) continue
    if (parsed.row >= at && parsed.row < at + amount) continue
    if (parsed.row >= at + amount) parsed.row -= amount
    cells[cellAddress(parsed.row, parsed.col)] = cell
  }
  sheet.cells = cells
  const heights: Record<string, number> = {}
  for (const [key, value] of Object.entries(sheet.rowHeights)) {
    const row = Number(key)
    if (row >= at && row < at + amount) continue
    heights[String(row >= at + amount ? row - amount : row)] = value
  }
  sheet.rowHeights = heights
  adjustMergesDelete(sheet, 'row', at, amount)
}

export function insertCols(
  sheet: SheetData,
  workbook: SheetWorkbook,
  index: number,
  count = 1,
) {
  const at = clamp(index, 0, sheet.cols)
  const amount = Math.max(1, Math.min(count, MAX_COLS - sheet.cols))
  if (!amount) return
  shiftAllFormulas(workbook, sheet.name, 'col', at, amount)
  const cells: Record<string, SheetCell> = {}
  for (const [address, cell] of Object.entries(sheet.cells)) {
    const parsed = parseAddress(address)
    if (!parsed) continue
    if (parsed.col >= at) parsed.col += amount
    if (parsed.col >= MAX_COLS) continue
    cells[cellAddress(parsed.row, parsed.col)] = cell
  }
  sheet.cells = cells
  const widths: Record<string, number> = {}
  for (const [key, value] of Object.entries(sheet.colWidths)) {
    const col = Number(key)
    if (col >= at) {
      if (col + amount < MAX_COLS) widths[String(col + amount)] = value
    } else {
      widths[key] = value
    }
  }
  sheet.colWidths = widths
  sheet.cols = Math.min(MAX_COLS, sheet.cols + amount)
  adjustMergesInsert(sheet, 'col', at, amount)
  shiftFilters(sheet, at, amount)
}

export function deleteCols(
  sheet: SheetData,
  workbook: SheetWorkbook,
  index: number,
  count = 1,
) {
  if (sheet.cols <= 1) return
  const at = clamp(index, 0, sheet.cols - 1)
  const amount = clamp(count, 1, sheet.cols - at)
  shiftAllFormulas(workbook, sheet.name, 'col', at, -amount)
  const cells: Record<string, SheetCell> = {}
  for (const [address, cell] of Object.entries(sheet.cells)) {
    const parsed = parseAddress(address)
    if (!parsed) continue
    if (parsed.col >= at && parsed.col < at + amount) continue
    if (parsed.col >= at + amount) parsed.col -= amount
    cells[cellAddress(parsed.row, parsed.col)] = cell
  }
  sheet.cells = cells
  const widths: Record<string, number> = {}
  for (const [key, value] of Object.entries(sheet.colWidths)) {
    const col = Number(key)
    if (col >= at && col < at + amount) continue
    widths[String(col >= at + amount ? col - amount : col)] = value
  }
  sheet.colWidths = widths
  adjustMergesDelete(sheet, 'col', at, amount)
  shiftFilters(sheet, at, -amount)
}

// ---------- 合并单元格 ----------

/** 合并区域：与现有合并冲突时先拆开，返回是否成功。 */
export function mergeRange(sheet: SheetData, range: CellRange): boolean {
  const normalized = normalizedRange(range)
  if (normalized.start.row === normalized.end.row && normalized.start.col === normalized.end.col) {
    return false
  }
  sheet.merges = sheet.merges.filter((raw) => {
    const parsed = parseRange(raw)
    if (!parsed) return false
    return (
      parsed.end.row < normalized.start.row ||
      parsed.start.row > normalized.end.row ||
      parsed.end.col < normalized.start.col ||
      parsed.start.col > normalized.end.col
    )
  })
  // 保留左上角内容，清空被覆盖格子的内容（样式保留）
  for (let row = normalized.start.row; row <= normalized.end.row; row += 1) {
    for (let col = normalized.start.col; col <= normalized.end.col; col += 1) {
      if (row === normalized.start.row && col === normalized.start.col) continue
      const cell = sheet.cells[cellAddress(row, col)]
      if (!cell) continue
      delete cell.v
      delete cell.f
      delete cell.cached
      if (!cell.s || !Object.keys(cell.s).length) delete sheet.cells[cellAddress(row, col)]
    }
  }
  sheet.merges.push(rangeAddress(normalized))
  return true
}

export function unmergeRange(sheet: SheetData, range: CellRange) {
  const normalized = normalizedRange(range)
  sheet.merges = sheet.merges.filter((raw) => {
    const parsed = parseRange(raw)
    if (!parsed) return false
    return (
      parsed.end.row < normalized.start.row ||
      parsed.start.row > normalized.end.row ||
      parsed.end.col < normalized.start.col ||
      parsed.start.col > normalized.end.col
    )
  })
}

export function rangeHasMerge(sheet: SheetData, range: CellRange): boolean {
  const normalized = normalizedRange(range)
  return sheet.merges.some((raw) => {
    const parsed = parseRange(raw)
    if (!parsed) return false
    return !(
      parsed.end.row < normalized.start.row ||
      parsed.start.row > normalized.end.row ||
      parsed.end.col < normalized.start.col ||
      parsed.start.col > normalized.end.col
    )
  })
}

// ---------- 复制 / 粘贴 ----------

export interface ClipboardSnapshot {
  range: CellRange
  cells: Array<{ row: number; col: number; cell: SheetCell }>
  merges: string[]
}

export function copyRange(sheet: SheetData, range: CellRange): ClipboardSnapshot {
  const normalized = normalizedRange(range)
  const cells: ClipboardSnapshot['cells'] = []
  eachCellInRange(normalized, (address, row, col) => {
    const cell = sheet.cells[address]
    if (!cell) return
    cells.push({ row, col, cell: JSON.parse(JSON.stringify(cell)) as SheetCell })
  })
  const merges = sheet.merges.filter((raw) => {
    const parsed = parseRange(raw)
    if (!parsed) return false
    return (
      parsed.start.row >= normalized.start.row &&
      parsed.end.row <= normalized.end.row &&
      parsed.start.col >= normalized.start.col &&
      parsed.end.col <= normalized.end.col
    )
  })
  return { range: normalized, cells, merges }
}

export function pasteSnapshot(
  sheet: SheetData,
  workbook: SheetWorkbook,
  snapshot: ClipboardSnapshot,
  target: { row: number; col: number },
  cut = false,
) {
  const source = snapshot.range
  const deltaRow = target.row - source.start.row
  const deltaCol = target.col - source.start.col
  const width = source.end.col - source.start.col + 1
  const height = source.end.row - source.start.row + 1
  const destination: CellRange = {
    start: { row: target.row, col: target.col },
    end: {
      row: Math.min(sheet.rows - 1, target.row + height - 1),
      col: Math.min(sheet.cols - 1, target.col + width - 1),
    },
  }
  if (cut) {
    // 先清空源区域再写入目标，避免两者重叠时把新数据清掉
    clearContents(sheet, source)
    unmergeRange(sheet, source)
  }
  clearContents(sheet, destination)
  unmergeRange(sheet, destination)
  for (const item of snapshot.cells) {
    const row = item.row + deltaRow
    const col = item.col + deltaCol
    if (row < 0 || col < 0 || row >= sheet.rows || col >= sheet.cols) continue
    const cloned = JSON.parse(JSON.stringify(item.cell)) as SheetCell
    if (cloned.f) cloned.f = translateFormula(cloned.f, deltaRow, deltaCol)
    sheet.cells[cellAddress(row, col)] = cloned
  }
  for (const raw of snapshot.merges) {
    const parsed = parseRange(raw)
    if (!parsed) continue
    const start = { row: parsed.start.row + deltaRow, col: parsed.start.col + deltaCol }
    const end = { row: parsed.end.row + deltaRow, col: parsed.end.col + deltaCol }
    if (start.row < 0 || start.col < 0 || end.row >= sheet.rows || end.col >= sheet.cols) continue
    sheet.merges.push(rangeAddress({ start, end }))
  }
  // 修正因写入目标覆盖后可能残留的越界合并
  sheet.merges = sheet.merges.filter((raw) => {
    const parsed = parseRange(raw)
    return !!parsed && parsed.end.row < sheet.rows && parsed.end.col < sheet.cols
  })
  return workbook
}

// ---------- 工作表 ----------

function quoteSheetName(name: string): string {
  return /^[A-Za-z_一-龥][A-Za-z0-9_.一-龥]*$/.test(name)
    ? name
    : `'${name.replace(/'/g, "''")}'`
}

function rewriteSheetRef(formula: string, oldName: string, newName: string): string {
  const quoted = quoteSheetName(newName)
  return formula.replace(
    /(^|[^A-Za-z0-9_.一-龥])(?:'((?:[^']|'')+)'|([A-Za-z_一-龥][A-Za-z0-9_.一-龥]*))\s*!/g,
    (match, prefix: string, quotedName: string | undefined, bareName: string | undefined) => {
      const name = quotedName !== undefined ? quotedName.replace(/''/g, "'") : bareName ?? ''
      if (name.toLowerCase() !== oldName.toLowerCase()) return match
      return `${prefix}${quoted}!`
    },
  )
}

export function renameSheet(workbook: SheetWorkbook, sheetId: string, rawName: string): string {
  const sheet = workbook.sheets.find((item) => item.id === sheetId)
  if (!sheet) return rawName
  const base = (rawName || 'Sheet')
    .replace(/[\\/:*?[\]"']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 31) || 'Sheet'
  let name = base
  let suffix = 2
  while (
    workbook.sheets.some(
      (item) => item.id !== sheetId && item.name.toLowerCase() === name.toLowerCase(),
    )
  ) {
    name = `${base.slice(0, 31 - String(suffix).length - 2)} (${suffix})`
    suffix += 1
  }
  if (name === sheet.name) return name
  const oldName = sheet.name
  sheet.name = name
  for (const item of workbook.sheets) {
    for (const cell of Object.values(item.cells)) {
      if (cell.f) cell.f = rewriteSheetRef(cell.f, oldName, name)
    }
  }
  return name
}

export function addSheet(workbook: SheetWorkbook, rawName?: string): SheetData {
  let index = workbook.sheets.length + 1
  let name = rawName?.trim() || `Sheet${index}`
  while (workbook.sheets.some((item) => item.name.toLowerCase() === name.toLowerCase())) {
    index += 1
    name = rawName?.trim() ? `${rawName.trim()} (${index})` : `Sheet${index}`
  }
  const sheet = cloneSheet({
    id: '',
    name,
    rows: DEFAULT_ROWS,
    cols: DEFAULT_COLS,
    cells: {},
    colWidths: {},
    rowHeights: {},
    merges: [],
  })
  workbook.sheets.push(sheet)
  workbook.active = sheet.id
  return sheet
}

export function duplicateSheet(workbook: SheetWorkbook, sheetId: string): SheetData | null {
  const source = workbook.sheets.find((item) => item.id === sheetId)
  if (!source) return null
  const copy = cloneSheet(source)
  let name = `${source.name} 副本`
  let suffix = 2
  while (workbook.sheets.some((item) => item.name.toLowerCase() === name.toLowerCase())) {
    name = `${source.name} 副本 ${suffix}`
    suffix += 1
  }
  copy.name = name
  const index = workbook.sheets.findIndex((item) => item.id === sheetId)
  workbook.sheets.splice(index + 1, 0, copy)
  workbook.active = copy.id
  return copy
}

export function removeSheet(workbook: SheetWorkbook, sheetId: string): boolean {
  if (workbook.sheets.length <= 1) return false
  const index = workbook.sheets.findIndex((item) => item.id === sheetId)
  if (index < 0) return false
  workbook.sheets.splice(index, 1)
  if (workbook.active === sheetId) {
    workbook.active = workbook.sheets[Math.max(0, index - 1)].id
  }
  return true
}

export function moveSheet(workbook: SheetWorkbook, from: number, to: number) {
  if (from === to || from < 0 || from >= workbook.sheets.length) return
  const target = clamp(to, 0, workbook.sheets.length - 1)
  const [sheet] = workbook.sheets.splice(from, 1)
  workbook.sheets.splice(target, 0, sheet)
}

/** 自动扩展工作表以容纳给定单元格（粘贴 / 导入时使用）。 */
export function ensureSheetSize(sheet: SheetData, rows: number, cols: number) {
  sheet.rows = Math.max(sheet.rows, Math.min(MAX_ROWS, rows))
  sheet.cols = Math.max(sheet.cols, Math.min(MAX_COLS, cols))
}

/** 合并区域的锚点地址集合，便于模板渲染。 */
export function mergedAnchors(sheet: SheetData) {
  return mergeLayout(sheet)
}

export { columnLabel }
