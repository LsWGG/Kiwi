/**
 * Excel 风格表格笔记的数据模型。
 *
 * 工作簿保存在 `props_json.sheet`，每个单元格用 A1 地址索引：
 * - `v`：常量值（文本 / 数字 / 布尔）
 * - `f`：公式源码（以 `=` 开头），由前端公式引擎计算，不写入 Markdown
 * - `cached`：导入 Excel 时保存的缓存值，公式暂不支持时可回退展示
 * - `s`：基础样式（粗体、斜体、文字色、底色、对齐、数字格式）
 *
 * 该结构同时被后端 `parse_sheet_workbook` 产出，字段名需保持一致。
 */

export type CellValue = string | number | boolean | null

export type SheetNumberFormat =
  | 'general'
  | 'text'
  | 'number'
  | 'percent'
  | 'currency'
  | 'date'

export interface SheetCellStyle {
  bold?: boolean
  italic?: boolean
  underline?: boolean
  /** #RRGGBB */
  color?: string
  /** #RRGGBB */
  bg?: string
  align?: 'left' | 'center' | 'right'
  fmt?: SheetNumberFormat
}

export interface SheetCell {
  v?: CellValue
  f?: string
  cached?: CellValue
  s?: SheetCellStyle
}

export interface SheetData {
  id: string
  name: string
  rows: number
  cols: number
  /** A1 → 单元格 */
  cells: Record<string, SheetCell>
  /** 列索引（0 基，字符串键）→ 像素宽度 */
  colWidths: Record<string, number>
  /** 行索引（0 基，字符串键）→ 像素高度 */
  rowHeights: Record<string, number>
  /** 合并区域，如 `A1:C2` */
  merges: string[]
  /** 冻结窗格：顶部冻结的数据行数（0 表示不冻结）。 */
  frozenRows?: number
  /** 冻结窗格：左侧冻结的数据列数（0 表示不冻结）。 */
  frozenCols?: number
  /**
   * 列筛选：列索引（0 基，字符串键）→ 选中的显示值列表。
   * 未出现的列不筛选；数组为空表示该列没有可显示的数据。
   */
  filters?: Record<string, string[]>
}

export interface SheetWorkbook {
  version: 1
  active: string
  sheets: SheetData[]
}

export const DEFAULT_ROWS = 100
export const DEFAULT_COLS = 26
export const MAX_ROWS = 5000
export const MAX_COLS = 120
export const MIN_COL_WIDTH = 48
export const MAX_COL_WIDTH = 520
export const DEFAULT_COL_WIDTH = 104
export const DEFAULT_ROW_HEIGHT = 28

export interface CellPosition {
  row: number
  col: number
}

export interface CellRange {
  start: CellPosition
  end: CellPosition
}

export interface MergeSpan {
  rowSpan: number
  colSpan: number
}

export function columnLabel(index: number): string {
  let label = ''
  let value = Math.max(0, Math.floor(index)) + 1
  while (value > 0) {
    value -= 1
    label = String.fromCharCode(65 + (value % 26)) + label
    value = Math.floor(value / 26)
  }
  return label
}

export function columnIndex(label: string): number {
  const text = label.toUpperCase().replace(/\$/g, '')
  let value = 0
  for (const char of text) {
    const code = char.charCodeAt(0)
    if (code < 65 || code > 90) return -1
    value = value * 26 + (code - 64)
  }
  return value - 1
}

export function cellAddress(row: number, col: number): string {
  return `${columnLabel(col)}${row + 1}`
}

export function parseAddress(address: string): CellPosition | null {
  const match = /^\$?([A-Za-z]+)\$?(\d+)$/.exec(address.trim())
  if (!match) return null
  const col = columnIndex(match[1])
  const row = Number(match[2]) - 1
  if (col < 0 || !Number.isInteger(row) || row < 0) return null
  return { row, col }
}

export function parseRange(range: string): { start: CellPosition; end: CellPosition } | null {
  const [a, b] = range.split(':')
  const first = parseAddress(a || '')
  if (!first) return null
  const second = parseAddress(b || a || '')
  if (!second) return null
  return normalizedRange({ start: first, end: second })
}

export function rangeAddress(range: CellRange): string {
  const { start, end } = normalizedRange(range)
  const first = cellAddress(start.row, start.col)
  const second = cellAddress(end.row, end.col)
  return first === second ? first : `${first}:${second}`
}

export function normalizedRange(range: CellRange): CellRange {
  return {
    start: {
      row: Math.min(range.start.row, range.end.row),
      col: Math.min(range.start.col, range.end.col),
    },
    end: {
      row: Math.max(range.start.row, range.end.row),
      col: Math.max(range.start.col, range.end.col),
    },
  }
}

export function isSingleCell(range: CellRange): boolean {
  return range.start.row === range.end.row && range.start.col === range.end.col
}

export function rangeContains(range: CellRange, position: CellPosition): boolean {
  return (
    position.row >= range.start.row &&
    position.row <= range.end.row &&
    position.col >= range.start.col &&
    position.col <= range.end.col
  )
}

export function rangesIntersect(a: CellRange, b: CellRange): boolean {
  return !(
    a.end.row < b.start.row ||
    b.end.row < a.start.row ||
    a.end.col < b.start.col ||
    b.end.col < a.start.col
  )
}

export function shiftCellAddress(
  address: string,
  axis: 'row' | 'col',
  index: number,
  delta: number,
): string | null {
  const parsed = parseAddress(address)
  if (!parsed) return null
  const target = axis === 'row' ? parsed.row : parsed.col
  if (delta > 0) {
    if (target >= index) {
      if (axis === 'row') parsed.row += delta
      else parsed.col += delta
    }
  } else if (delta < 0) {
    if (target === index) return null
    if (target > index) {
      if (axis === 'row') parsed.row += delta
      else parsed.col += delta
    }
  }
  return cellAddress(parsed.row, parsed.col)
}

export function clampPosition(position: CellPosition, sheet: SheetData): CellPosition {
  return {
    row: Math.max(0, Math.min(sheet.rows - 1, position.row)),
    col: Math.max(0, Math.min(sheet.cols - 1, position.col)),
  }
}

function asFrozenCount(value: unknown, max: number): number {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return 0
  return Math.min(Math.max(0, max), Math.floor(number))
}

/**
 * 冻结行列数：限制在 0..rows-1 / 0..cols-1，且不切开合并单元格。
 * 合并区域跨过冻结边界时，冻结范围收缩到合并区域起始位置之前。
 */
export function clampFrozenCount(
  sheet: Pick<SheetData, 'rows' | 'cols' | 'merges'>,
  axis: 'row' | 'col',
  value: unknown,
): number {
  const limit = Math.max(0, (axis === 'row' ? sheet.rows : sheet.cols) - 1)
  let count = asFrozenCount(value, limit)
  let changed = true
  while (changed && count > 0) {
    changed = false
    for (const raw of sheet.merges) {
      const range = parseRange(raw)
      if (!range) continue
      const start = axis === 'row' ? range.start.row : range.start.col
      const end = axis === 'row' ? range.end.row : range.end.col
      if (start < count && end >= count) {
        count = Math.max(0, start)
        changed = true
      }
    }
  }
  return Math.min(count, limit)
}

/** 合并单元格的渲染索引：锚点 → 跨度；被覆盖的格子集合。 */
export function mergeLayout(sheet: SheetData): {
  anchors: Map<string, MergeSpan>
  covered: Set<string>
} {
  const anchors = new Map<string, MergeSpan>()
  const covered = new Set<string>()
  for (const raw of sheet.merges) {
    const range = parseRange(raw)
    if (!range) continue
    const rowSpan = range.end.row - range.start.row + 1
    const colSpan = range.end.col - range.start.col + 1
    if (rowSpan <= 1 && colSpan <= 1) continue
    anchors.set(cellAddress(range.start.row, range.start.col), { rowSpan, colSpan })
    for (let row = range.start.row; row <= range.end.row; row += 1) {
      for (let col = range.start.col; col <= range.end.col; col += 1) {
        if (row === range.start.row && col === range.start.col) continue
        covered.add(cellAddress(row, col))
      }
    }
  }
  return { anchors, covered }
}

export function makeSheet(name: string, rows = DEFAULT_ROWS, cols = DEFAULT_COLS): SheetData {
  return {
    id: newId(),
    name,
    rows,
    cols,
    cells: {},
    colWidths: {},
    rowHeights: {},
    merges: [],
    frozenRows: 0,
    frozenCols: 0,
  }
}

export function emptyWorkbook(): SheetWorkbook {
  const sheet = makeSheet('Sheet1')
  return { version: 1, active: sheet.id, sheets: [sheet] }
}

let idCounter = 0
export function newId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID().replace(/-/g, '')
  }
  idCounter += 1
  return `s${Date.now().toString(36)}${idCounter}`
}

function asPositiveInt(value: unknown, fallback: number, max: number): number {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return fallback
  return Math.min(max, Math.max(1, Math.round(number)))
}

function normalizeStyle(raw: unknown): SheetCellStyle | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const style: SheetCellStyle = {}
  if (value.bold === true) style.bold = true
  if (value.italic === true) style.italic = true
  if (value.underline === true) style.underline = true
  if (typeof value.color === 'string' && /^#[0-9a-f]{6}$/i.test(value.color)) {
    style.color = value.color.toUpperCase()
  }
  if (typeof value.bg === 'string' && /^#[0-9a-f]{6}$/i.test(value.bg)) {
    style.bg = value.bg.toUpperCase()
  }
  if (value.align === 'left' || value.align === 'center' || value.align === 'right') {
    style.align = value.align
  }
  if (
    value.fmt === 'text' ||
    value.fmt === 'number' ||
    value.fmt === 'percent' ||
    value.fmt === 'currency' ||
    value.fmt === 'date'
  ) {
    style.fmt = value.fmt
  }
  return Object.keys(style).length ? style : undefined
}

function normalizeCell(raw: unknown): SheetCell | null {
  if (!raw || typeof raw !== 'object') return null
  const value = raw as Record<string, unknown>
  const cell: SheetCell = {}
  if (value.f !== undefined) {
    const formula = String(value.f).trim()
    if (formula.startsWith('=')) cell.f = formula.slice(0, 20000)
  }
  if (value.v !== undefined) {
    const v = value.v
    if (v === null || typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
      cell.v = typeof v === 'string' ? v.slice(0, 20000) : v
    }
  }
  if (value.cached !== undefined) {
    const cached = value.cached
    if (
      cached === null ||
      typeof cached === 'string' ||
      typeof cached === 'number' ||
      typeof cached === 'boolean'
    ) {
      cell.cached = cached
    }
  }
  const style = normalizeStyle(value.s)
  if (style) cell.s = style
  return Object.keys(cell).length ? cell : null
}

/** 兼容历史 / 损坏数据：始终返回可渲染的工作簿。 */
export function normalizeWorkbook(raw: unknown): SheetWorkbook {
  if (!raw || typeof raw !== 'object') return emptyWorkbook()
  const value = raw as Record<string, unknown>
  const rawSheets = Array.isArray(value.sheets) ? value.sheets : []
  const sheets: SheetData[] = []
  const usedIds = new Set<string>()
  const usedNames = new Set<string>()
  rawSheets.forEach((item, index) => {
    if (!item || typeof item !== 'object') return
    const entry = item as Record<string, unknown>
    let id = typeof entry.id === 'string' && entry.id.trim() ? entry.id.trim() : newId()
    while (usedIds.has(id)) id = newId()
    usedIds.add(id)
    let name = typeof entry.name === 'string' && entry.name.trim() ? entry.name.trim() : `Sheet${index + 1}`
    name = name.slice(0, 80)
    let suffix = 2
    const baseName = name
    while (usedNames.has(name.toLowerCase())) {
      name = `${baseName} (${suffix})`.slice(0, 80)
      suffix += 1
    }
    usedNames.add(name.toLowerCase())

    const cells: Record<string, SheetCell> = {}
    let maxRow = 0
    let maxCol = 0
    const rawCells = entry.cells && typeof entry.cells === 'object' ? entry.cells : {}
    for (const [address, cell] of Object.entries(rawCells as Record<string, unknown>)) {
      const normalizedAddress = address.toUpperCase().replace(/\$/g, '')
      const parsed = parseAddress(normalizedAddress)
      if (!parsed) continue
      const normalized = normalizeCell(cell)
      if (!normalized) continue
      cells[normalizedAddress] = normalized
      maxRow = Math.max(maxRow, parsed.row + 1)
      maxCol = Math.max(maxCol, parsed.col + 1)
    }
    const rows = Math.min(MAX_ROWS, Math.max(DEFAULT_ROWS, asPositiveInt(entry.rows, DEFAULT_ROWS, MAX_ROWS), maxRow))
    const cols = Math.min(MAX_COLS, Math.max(DEFAULT_COLS, asPositiveInt(entry.cols, DEFAULT_COLS, MAX_COLS), maxCol))

    const colWidths: Record<string, number> = {}
    if (entry.colWidths && typeof entry.colWidths === 'object') {
      for (const [key, width] of Object.entries(entry.colWidths as Record<string, unknown>)) {
        const indexValue = Number(key)
        const pixels = Number(width)
        if (!Number.isInteger(indexValue) || indexValue < 0 || indexValue >= cols) continue
        if (!Number.isFinite(pixels)) continue
        colWidths[String(indexValue)] = Math.max(
          MIN_COL_WIDTH,
          Math.min(MAX_COL_WIDTH, Math.round(pixels)),
        )
      }
    }
    const rowHeights: Record<string, number> = {}
    if (entry.rowHeights && typeof entry.rowHeights === 'object') {
      for (const [key, height] of Object.entries(entry.rowHeights as Record<string, unknown>)) {
        const indexValue = Number(key)
        const pixels = Number(height)
        if (!Number.isInteger(indexValue) || indexValue < 0 || indexValue >= rows) continue
        if (!Number.isFinite(pixels)) continue
        rowHeights[String(indexValue)] = Math.max(20, Math.min(200, Math.round(pixels)))
      }
    }

    const merges: string[] = []
    if (Array.isArray(entry.merges)) {
      for (const rawMerge of entry.merges) {
        const range = typeof rawMerge === 'string' ? parseRange(rawMerge) : null
        if (!range) continue
        if (range.end.row >= rows || range.end.col >= cols) continue
        merges.push(rangeAddress(range))
      }
    }

    const filters: Record<string, string[]> = {}
    if (entry.filters && typeof entry.filters === 'object') {
      for (const [key, selected] of Object.entries(entry.filters as Record<string, unknown>)) {
        const indexValue = Number(key)
        if (!Number.isInteger(indexValue) || indexValue < 0 || indexValue >= cols) continue
        if (!Array.isArray(selected)) continue
        const values = selected
          .filter((item): item is string => typeof item === 'string')
          .map((item) => item.slice(0, 500))
          .slice(0, 5000)
        filters[String(indexValue)] = values
      }
    }

    const frozenRows = clampFrozenCount({ rows, cols, merges }, 'row', entry.frozenRows)
    const frozenCols = clampFrozenCount({ rows, cols, merges }, 'col', entry.frozenCols)

    sheets.push({
      id,
      name,
      rows,
      cols,
      cells,
      colWidths,
      rowHeights,
      merges,
      frozenRows,
      frozenCols,
      ...(Object.keys(filters).length ? { filters } : {}),
    })
  })

  if (!sheets.length) return emptyWorkbook()
  const active =
    typeof value.active === 'string' && sheets.some((sheet) => sheet.id === value.active)
      ? value.active
      : sheets[0].id
  return { version: 1, active, sheets }
}

export function cloneWorkbook(workbook: SheetWorkbook): SheetWorkbook {
  return JSON.parse(JSON.stringify(workbook)) as SheetWorkbook
}

export function cloneSheet(sheet: SheetData): SheetData {
  return {
    ...sheet,
    id: newId(),
    cells: JSON.parse(JSON.stringify(sheet.cells)),
    colWidths: { ...sheet.colWidths },
    rowHeights: { ...sheet.rowHeights },
    merges: [...sheet.merges],
    frozenRows: sheet.frozenRows ?? 0,
    frozenCols: sheet.frozenCols ?? 0,
    ...(sheet.filters ? { filters: JSON.parse(JSON.stringify(sheet.filters)) } : {}),
  }
}

export function sheetCellValue(cell: SheetCell | undefined): CellValue {
  if (!cell) return null
  if (cell.v !== undefined) return cell.v
  return null
}
