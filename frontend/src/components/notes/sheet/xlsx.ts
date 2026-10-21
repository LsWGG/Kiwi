/**
 * Excel 工作簿导入 / 导出。
 *
 * - 后端导入（推荐）会保留公式、样式、合并单元格与列宽；这里用于导出，
 *   以及 IDE / 本地直接打开表格文件时的兜底解析。
 * - `xlsx` 体积较大，按需动态加载，不进入首屏。
 */
import type { CellValue, SheetCell, SheetData, SheetWorkbook } from './types'
import {
  DEFAULT_COLS,
  DEFAULT_ROWS,
  MAX_COLS,
  MAX_ROWS,
  cellAddress,
  columnLabel,
  emptyWorkbook,
  makeSheet,
  newId,
  normalizeWorkbook,
  parseAddress,
  parseRange,
  rangeAddress,
} from './types'
import { evaluateWorkbook } from './formula'

export const SHEET_FILE_ACCEPT = '.xlsx,.xls,.csv'

function safeSheetName(name: string, used: Set<string>): string {
  let base = (name || 'Sheet')
    .replace(/[\\/:*?[\]"']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 31)
  if (!base) base = 'Sheet'
  let candidate = base
  let suffix = 2
  while (used.has(candidate.toLowerCase())) {
    const tail = ` (${suffix})`
    candidate = `${base.slice(0, 31 - tail.length)}${tail}`
    suffix += 1
  }
  used.add(candidate.toLowerCase())
  return candidate
}

function cellValueType(value: CellValue, formula: boolean): 'n' | 's' | 'b' | 'z' {
  if (formula) return 'n'
  if (value === null || value === '') return 'z'
  if (typeof value === 'number') return 'n'
  if (typeof value === 'boolean') return 'b'
  return 's'
}

export interface ExportSheetOptions {
  /** 是否写入公式（默认 true）；关闭后只导出计算结果。 */
  formulas?: boolean
  /** 是否保留计算结果缓存（默认 true）。 */
  cached?: boolean
}

export function workbookToXlsxBlob(
  workbook: SheetWorkbook,
  XLSX: typeof import('xlsx'),
  options: ExportSheetOptions = {},
): Blob {
  const results = evaluateWorkbook(workbook)
  const book = XLSX.utils.book_new()
  const used = new Set<string>()
  for (const sheet of workbook.sheets) {
    const ws: Record<string, unknown> = {}
    let maxRow = 0
    let maxCol = 0
    for (const [address, cell] of Object.entries(sheet.cells)) {
      const position = parseAddress(address)
      if (!position) continue
      maxRow = Math.max(maxRow, position.row)
      maxCol = Math.max(maxCol, position.col)
      const computed = results.get(`${sheet.id}!${address}`)
      const formula = options.formulas !== false ? cell.f : undefined
      const value =
        formula && options.cached !== false && !computed?.error
          ? computed?.value ?? cell.cached ?? null
          : cell.v ?? null
      if (!formula && (value === null || value === '')) continue
      const out: Record<string, unknown> = {
        t: cellValueType(value, Boolean(formula)),
        v: value ?? '',
      }
      if (formula) out.f = formula.replace(/^=/, '')
      ws[address] = out
    }
    if (!maxRow && !maxCol) {
      maxRow = 0
      maxCol = 0
    }
    ws['!ref'] = XLSX.utils.encode_range({
      s: { r: 0, c: 0 },
      e: { r: Math.max(maxRow, 0), c: Math.max(maxCol, 0) },
    })
    const merges = sheet.merges
      .map((raw) => {
        const range = parseRange(raw)
        if (!range) return null
        return {
          s: { r: range.start.row, c: range.start.col },
          e: { r: range.end.row, c: range.end.col },
        }
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item))
    if (merges.length) ws['!merges'] = merges
    const cols: Array<{ wpx: number }> = []
    for (let col = 0; col <= maxCol; col += 1) {
      cols.push({ wpx: sheet.colWidths[String(col)] ?? 104 })
    }
    if (cols.length) ws['!cols'] = cols
    const rows: Array<{ hpx: number }> = []
    for (let row = 0; row <= maxRow; row += 1) {
      rows.push({ hpx: sheet.rowHeights[String(row)] ?? 28 })
    }
    if (rows.length) ws['!rows'] = rows
    XLSX.utils.book_append_sheet(book, ws as never, safeSheetName(sheet.name, used))
  }
  const output = XLSX.write(book, { bookType: 'xlsx', type: 'array' })
  return new Blob([output], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

/** 导出一张工作表为 CSV（公式取计算结果）。 */
export function sheetToCsv(sheet: SheetData, workbook: SheetWorkbook): string {
  const results = evaluateWorkbook(workbook)
  const lines: string[] = []
  for (let row = 0; row < sheet.rows; row += 1) {
    const values: string[] = []
    for (let col = 0; col < sheet.cols; col += 1) {
      const address = cellAddress(row, col)
      const result = results.get(`${sheet.id}!${address}`)
      const value = result?.error ? result.error : result?.value ?? null
      const text = value === null ? '' : String(value)
      values.push(/[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text)
    }
    // 去掉末尾空列，避免 CSV 出现大量无意义分隔符
    while (values.length && values[values.length - 1] === '') values.pop()
    lines.push(values.join(','))
  }
  while (lines.length && !lines[lines.length - 1]) lines.pop()
  return `﻿${lines.join('\r\n')}`
}

export function downloadBlobFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 本地解析 Excel / CSV（后端导入不可用时的兜底）。 */
export async function readWorkbookFile(file: File): Promise<SheetWorkbook> {
  const XLSX = await import('xlsx')
  const buffer = await file.arrayBuffer()
  const book = XLSX.read(buffer, { type: 'array', cellDates: false, cellNF: false })
  const sheets: SheetData[] = []
  for (const name of book.SheetNames) {
    const ws = book.Sheets[name]
    if (!ws || !ws['!ref']) {
      sheets.push(makeSheet(name))
      continue
    }
    const range = XLSX.utils.decode_range(ws['!ref'])
    const rows = Math.min(MAX_ROWS, Math.max(DEFAULT_ROWS, range.e.r + 1))
    const cols = Math.min(MAX_COLS, Math.max(DEFAULT_COLS, range.e.c + 1))
    const sheet = makeSheet(name, rows, cols)
    for (let row = range.s.r; row <= range.e.r && row < rows; row += 1) {
      for (let col = range.s.c; col <= range.e.c && col < cols; col += 1) {
        const source = ws[XLSX.utils.encode_cell({ r: row, c: col }) as string] as
          | { v?: unknown; f?: string; t?: string; w?: string }
          | undefined
        if (!source) continue
        const cell: SheetCell = {}
        if (source.f) {
          cell.f = `=${source.f}`
          if (source.v !== undefined && source.v !== null) {
            cell.cached =
              typeof source.v === 'number' || typeof source.v === 'string'
                ? (source.v as CellValue)
                : String(source.v)
          }
        } else if (source.v !== undefined && source.v !== null) {
          const value = source.v
          if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
            cell.v = value
          } else if (value instanceof Date) {
            cell.v = value.toISOString().slice(0, 10)
          } else {
            cell.v = String(value)
          }
        }
        if (Object.keys(cell).length) sheet.cells[cellAddress(row, col)] = cell
      }
    }
    if (ws['!merges']) {
      for (const merge of ws['!merges']) {
        sheet.merges.push(
          rangeAddress({
            start: { row: merge.s.r, col: merge.s.c },
            end: { row: merge.e.r, col: merge.e.c },
          }),
        )
      }
    }
    if (ws['!cols']) {
      (ws['!cols'] as Array<{ wpx?: number; wch?: number } | undefined>).forEach((col, index) => {
        if (!col) return
        const width = col.wpx ?? (col.wch ? Math.round(col.wch * 8 + 12) : 0)
        if (width) sheet.colWidths[String(index)] = width
      })
    }
    if (ws['!rows']) {
      (ws['!rows'] as Array<{ hpx?: number; hpt?: number } | undefined>).forEach((row, index) => {
        if (!row) return
        const height = row.hpx ?? (row.hpt ? Math.round(row.hpt * 4 / 3) : 0)
        if (height) sheet.rowHeights[String(index)] = height
      })
    }
    sheets.push(sheet)
  }
  if (!sheets.length) return emptyWorkbook()
  const active = sheets[0].id
  return normalizeWorkbook({ version: 1, active, sheets })
}

export function emptySheet(name?: string): SheetData {
  return makeSheet(name || `Sheet${Math.floor(Math.random() * 1000) + 1}`)
}

export { DEFAULT_COLS, DEFAULT_ROWS, columnLabel, newId }
