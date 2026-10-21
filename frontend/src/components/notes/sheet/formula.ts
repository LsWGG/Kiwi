/**
 * 表格公式引擎：不依赖 `eval` / `Function`，只解析受支持的表达式。
 *
 * 支持：
 * - 四则、乘方、百分比、比较、文本连接
 * - 单元格 / 区域 / 跨工作表引用（`Sheet1!A1`、`'销售 2026'!A1:B3`）
 * - 常用数学、统计、文本、日期、条件与查找函数
 *
 * 每次工作簿变更后整体重算。公式之间通过缓存与递归求值建立依赖；
 * 循环引用返回 `#CIRC!`。
 */
import type { CellValue, SheetCellStyle, SheetNumberFormat, SheetWorkbook } from './types'
import { cellAddress, parseAddress, columnIndex, columnLabel } from './types'

export type FormulaErrorCode =
  | '#DIV/0!'
  | '#VALUE!'
  | '#REF!'
  | '#NAME?'
  | '#N/A'
  | '#NUM!'
  | '#CIRC!'
  | '#ERROR!'

export interface FormulaResult {
  value: CellValue
  error?: FormulaErrorCode
}

class FormulaError extends Error {
  code: FormulaErrorCode
  constructor(code: FormulaErrorCode) {
    super(code)
    this.code = code
  }
}

// ---------- Tokenizer ----------

type TokenType = 'number' | 'string' | 'ident' | 'op' | 'punct' | 'error'

interface Token {
  type: TokenType
  value: string
  start: number
  end: number
}

const TWO_CHAR_OPS = new Set(['<=', '>=', '<>'])
const ONE_CHAR_OPS = new Set(['+', '-', '*', '/', '^', '&', '%', '=', '<', '>', '!', ':'])

function tokenize(source: string): Token[] {
  const tokens: Token[] = []
  let index = 0
  while (index < source.length) {
    const char = source[index]
    if (/\s/.test(char)) {
      index += 1
      continue
    }
    const start = index
    if (char === '"' || char === "'") {
      const quote = char
      index += 1
      let text = ''
      let closed = false
      while (index < source.length) {
        const next = source[index]
        if (next === quote) {
          if (source[index + 1] === quote) {
            text += quote
            index += 2
            continue
          }
          index += 1
          closed = true
          break
        }
        text += next
        index += 1
      }
      tokens.push({
        type: closed ? 'string' : 'error',
        value: text,
        start,
        end: index,
      })
      continue
    }
    if (/\d/.test(char) || (char === '.' && /\d/.test(source[index + 1] ?? ''))) {
      const match = /^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/.exec(source.slice(index))
      const raw = match?.[0] ?? char
      index += raw.length
      tokens.push({ type: 'number', value: raw, start, end: index })
      continue
    }
    if (/[A-Za-z_$一-龥]/.test(char)) {
      const match = /^[$A-Za-z_一-龥][$A-Za-z0-9_.一-龥]*/.exec(
        source.slice(index),
      )
      const raw = match?.[0] ?? char
      index += raw.length
      tokens.push({ type: 'ident', value: raw, start, end: index })
      continue
    }
    const pair = source.slice(index, index + 2)
    if (TWO_CHAR_OPS.has(pair)) {
      index += 2
      tokens.push({ type: 'op', value: pair, start, end: index })
      continue
    }
    if (ONE_CHAR_OPS.has(char)) {
      index += 1
      tokens.push({ type: 'op', value: char, start, end: index })
      continue
    }
    if (char === '(' || char === ')' || char === ',' || char === ';') {
      index += 1
      tokens.push({
        type: 'punct',
        value: char === ';' ? ',' : char,
        start,
        end: index,
      })
      continue
    }
    index += 1
    tokens.push({ type: 'error', value: char, start, end: index })
  }
  return tokens
}

// ---------- Parser ----------

type AstNode =
  | { kind: 'number'; value: number }
  | { kind: 'string'; value: string }
  | { kind: 'boolean'; value: boolean }
  | { kind: 'ref'; sheet?: string; address: string }
  | { kind: 'range'; sheet?: string; start: string; end: string }
  | { kind: 'unary'; op: string; value: AstNode }
  | { kind: 'percent'; value: AstNode }
  | { kind: 'binary'; op: string; left: AstNode; right: AstNode }
  | { kind: 'call'; name: string; args: AstNode[] }
  | { kind: 'error'; code: FormulaErrorCode }

const CELL_REF_RE = /^\$?([A-Za-z]{1,3})\$?(\d+)$/

const BINARY_PRECEDENCE: Record<string, number> = {
  '=': 1,
  '<>': 1,
  '<': 1,
  '>': 1,
  '<=': 1,
  '>=': 1,
  '&': 2,
  '+': 3,
  '-': 3,
  '*': 4,
  '/': 4,
  '^': 5,
}

class Parser {
  private tokens: Token[]
  private pos = 0

  constructor(tokens: Token[]) {
    this.tokens = tokens
  }

  private peek(offset = 0): Token | undefined {
    return this.tokens[this.pos + offset]
  }

  private take(): Token | undefined {
    const token = this.tokens[this.pos]
    if (token) this.pos += 1
    return token
  }

  private match(type: TokenType, value?: string): boolean {
    const token = this.peek()
    return !!token && token.type === type && (value === undefined || token.value === value)
  }

  private expect(type: TokenType, value?: string): Token | null {
    if (!this.match(type, value)) return null
    return this.take() ?? null
  }

  parse(): AstNode {
    const node = this.parseExpression(0)
    if (this.pos < this.tokens.length) {
      return { kind: 'error', code: '#ERROR!' }
    }
    return node
  }

  private parseExpression(minPrecedence: number): AstNode {
    let left = this.parseUnary()
    while (true) {
      const token = this.peek()
      if (!token || token.type !== 'op') break
      const precedence = BINARY_PRECEDENCE[token.value]
      if (precedence === undefined || precedence < minPrecedence) break
      this.take()
      const right = this.parseExpression(
        token.value === '^' ? precedence : precedence + 1,
      )
      left = { kind: 'binary', op: token.value, left, right }
    }
    return left
  }

  private parseUnary(): AstNode {
    const token = this.peek()
    if (token?.type === 'op' && (token.value === '+' || token.value === '-')) {
      this.take()
      return { kind: 'unary', op: token.value, value: this.parseUnary() }
    }
    let node = this.parsePrimary()
    while (this.match('op', '%')) {
      this.take()
      node = { kind: 'percent', value: node }
    }
    return node
  }

  private parsePrimary(): AstNode {
    const token = this.take()
    if (!token) return { kind: 'error', code: '#ERROR!' }
    if (token.type === 'number') {
      return { kind: 'number', value: Number(token.value) }
    }
    if (token.type === 'string') {
      // `'Sheet 1'!A1`
      if (this.match('op', '!')) {
        return this.parseReference(token.value)
      }
      return { kind: 'string', value: token.value }
    }
    if (token.type === 'punct' && token.value === '(') {
      const inner = this.parseExpression(0)
      if (!this.expect('punct', ')')) return { kind: 'error', code: '#ERROR!' }
      return inner
    }
    if (token.type === 'ident') {
      const upper = token.value.toUpperCase()
      if (upper === 'TRUE' || upper === 'FALSE') {
        return { kind: 'boolean', value: upper === 'TRUE' }
      }
      if (this.match('punct', '(')) {
        this.take()
        const args: AstNode[] = []
        if (!this.match('punct', ')')) {
          while (true) {
            args.push(this.parseExpression(0))
            if (this.match('punct', ',')) {
              this.take()
              continue
            }
            break
          }
        }
        if (!this.expect('punct', ')')) return { kind: 'error', code: '#ERROR!' }
        return { kind: 'call', name: token.value.toUpperCase(), args }
      }
      if (this.match('op', '!')) {
        return this.parseReference(token.value)
      }
      if (CELL_REF_RE.test(token.value)) {
        const address = token.value.replace(/\$/g, '').toUpperCase()
        if (this.match('op', ':')) {
          this.take()
          const second = this.take()
          if (!second || second.type !== 'ident' || !CELL_REF_RE.test(second.value)) {
            return { kind: 'error', code: '#REF!' }
          }
          return {
            kind: 'range',
            start: address,
            end: second.value.replace(/\$/g, '').toUpperCase(),
          }
        }
        return { kind: 'ref', address }
      }
      return { kind: 'error', code: '#NAME?' }
    }
    return { kind: 'error', code: '#ERROR!' }
  }

  private parseReference(sheet: string): AstNode {
    if (!this.expect('op', '!')) return { kind: 'error', code: '#ERROR!' }
    const start = this.take()
    if (!start || start.type !== 'ident' || !CELL_REF_RE.test(start.value)) {
      return { kind: 'error', code: '#REF!' }
    }
    const address = start.value.replace(/\$/g, '').toUpperCase()
    if (this.match('op', ':')) {
      this.take()
      const end = this.take()
      if (!end || end.type !== 'ident' || !CELL_REF_RE.test(end.value)) {
        return { kind: 'error', code: '#REF!' }
      }
      return {
        kind: 'range',
        sheet,
        start: address,
        end: end.value.replace(/\$/g, '').toUpperCase(),
      }
    }
    return { kind: 'ref', sheet, address }
  }
}

const AST_CACHE = new Map<string, AstNode>()

function parseFormula(formula: string): AstNode {
  const source = formula.startsWith('=') ? formula.slice(1) : formula
  const cached = AST_CACHE.get(source)
  if (cached) return cached
  const ast = new Parser(tokenize(source)).parse()
  AST_CACHE.set(source, ast)
  return ast
}

// ---------- 求值 ----------

interface RangeValue {
  __range: true
  values: CellValue[][]
}

type EvalValue = CellValue | RangeValue

interface EvalContext {
  workbook: SheetWorkbook
  sheetId: string
  cache: Map<string, FormulaResult>
  stack: Set<string>
}

function isRangeValue(value: EvalValue): value is RangeValue {
  return !!value && typeof value === 'object' && (value as RangeValue).__range === true
}

function sheetByName(workbook: SheetWorkbook, name: string | undefined, fallback: string) {
  if (!name) return workbook.sheets.find((sheet) => sheet.id === fallback)
  const lowered = name.trim().toLowerCase()
  return workbook.sheets.find((sheet) => sheet.name.toLowerCase() === lowered)
}

function evalCell(ctx: EvalContext, sheetId: string, address: string): CellValue {
  const key = `${sheetId}!${address}`
  const cached = ctx.cache.get(key)
  if (cached) {
    if (cached.error) throw new FormulaError(cached.error)
    return cached.value
  }
  if (ctx.stack.has(key)) throw new FormulaError('#CIRC!')
  const sheet = ctx.workbook.sheets.find((item) => item.id === sheetId)
  const cell = sheet?.cells[address]
  if (!cell) {
    ctx.cache.set(key, { value: null })
    return null
  }
  if (!cell.f) {
    const value = cell.v ?? null
    ctx.cache.set(key, { value })
    return value
  }
  ctx.stack.add(key)
  try {
    const result = evaluateAst(ctx, parseFormula(cell.f), sheetId)
    const value = isRangeValue(result) ? firstValue(result) : result
    ctx.cache.set(key, { value })
    return value
  } catch (error) {
    const code = error instanceof FormulaError ? error.code : '#ERROR!'
    ctx.cache.set(key, { value: cell.cached ?? null, error: code })
    throw error instanceof FormulaError ? error : new FormulaError(code)
  } finally {
    ctx.stack.delete(key)
  }
}

function firstValue(range: RangeValue): CellValue {
  return range.values[0]?.[0] ?? null
}

function evalRange(
  ctx: EvalContext,
  sheetId: string,
  start: string,
  end: string,
): RangeValue {
  const a = parseAddress(start)
  const b = parseAddress(end)
  if (!a || !b) throw new FormulaError('#REF!')
  const sheet = ctx.workbook.sheets.find((item) => item.id === sheetId)
  if (!sheet) throw new FormulaError('#REF!')
  const rows: CellValue[][] = []
  const rowStart = Math.min(a.row, b.row)
  const rowEnd = Math.min(Math.max(a.row, b.row), sheet.rows - 1)
  const colStart = Math.min(a.col, b.col)
  const colEnd = Math.min(Math.max(a.col, b.col), sheet.cols - 1)
  if (rowStart > rowEnd || colStart > colEnd) throw new FormulaError('#REF!')
  for (let row = rowStart; row <= rowEnd; row += 1) {
    const values: CellValue[] = []
    for (let col = colStart; col <= colEnd; col += 1) {
      values.push(evalCell(ctx, sheetId, cellAddress(row, col)))
    }
    rows.push(values)
  }
  return { __range: true, values: rows }
}

function evaluateAst(ctx: EvalContext, node: AstNode, sheetId: string): EvalValue {
  switch (node.kind) {
    case 'number':
      return node.value
    case 'string':
      return node.value
    case 'boolean':
      return node.value
    case 'error':
      throw new FormulaError(node.code)
    case 'ref': {
      const sheet = sheetByName(ctx.workbook, node.sheet, sheetId)
      if (!sheet) throw new FormulaError('#REF!')
      return evalCell(ctx, sheet.id, node.address)
    }
    case 'range': {
      const sheet = sheetByName(ctx.workbook, node.sheet, sheetId)
      if (!sheet) throw new FormulaError('#REF!')
      return evalRange(ctx, sheet.id, node.start, node.end)
    }
    case 'percent': {
      const value = evaluateAst(ctx, node.value, sheetId)
      return toNumber(scalar(value)) / 100
    }
    case 'unary': {
      const value = toNumber(scalar(evaluateAst(ctx, node.value, sheetId)))
      return node.op === '-' ? -value : value
    }
    case 'binary': {
      if (node.op === '&') {
        return toText(scalar(evaluateAst(ctx, node.left, sheetId))) +
          toText(scalar(evaluateAst(ctx, node.right, sheetId)))
      }
      const left = scalar(evaluateAst(ctx, node.left, sheetId))
      const right = scalar(evaluateAst(ctx, node.right, sheetId))
      if (node.op === '=') return compareValues(left, right) === 0
      if (node.op === '<>') return compareValues(left, right) !== 0
      if (node.op === '<') return compareValues(left, right) < 0
      if (node.op === '>') return compareValues(left, right) > 0
      if (node.op === '<=') return compareValues(left, right) <= 0
      if (node.op === '>=') return compareValues(left, right) >= 0
      const a = toNumber(left)
      const b = toNumber(right)
      if (node.op === '+') return a + b
      if (node.op === '-') return a - b
      if (node.op === '*') return a * b
      if (node.op === '/') {
        if (b === 0) throw new FormulaError('#DIV/0!')
        return a / b
      }
      if (node.op === '^') {
        const result = a ** b
        if (!Number.isFinite(result)) throw new FormulaError('#NUM!')
        return result
      }
      throw new FormulaError('#ERROR!')
    }
    case 'call':
      return evaluateFunction(ctx, node, sheetId)
  }
}

function scalar(value: EvalValue): CellValue {
  if (isRangeValue(value)) return firstValue(value)
  return value
}

function toNumber(value: CellValue): number {
  if (value === null || value === '') return 0
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new FormulaError('#NUM!')
    return value
  }
  if (typeof value === 'boolean') return value ? 1 : 0
  const text = value.trim()
  if (!text) return 0
  if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?$/.test(text)) {
    const percent = text.endsWith('%')
    const number = Number(percent ? text.slice(0, -1) : text)
    return percent ? number / 100 : number
  }
  throw new FormulaError('#VALUE!')
}

function toText(value: CellValue): string {
  if (value === null) return ''
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE'
  if (typeof value === 'number') return formatGeneralNumber(value)
  return value
}

function toBoolean(value: CellValue): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    const lower = value.trim().toLowerCase()
    if (lower === 'true') return true
    if (lower === 'false' || lower === '') return false
  }
  return Boolean(value)
}

function compareValues(a: CellValue, b: CellValue): number {
  const left = a === null ? '' : a
  const right = b === null ? '' : b
  if (typeof left === 'number' && typeof right === 'number') return left - right
  if (typeof left === 'boolean' && typeof right === 'boolean') {
    return Number(left) - Number(right)
  }
  return String(left).localeCompare(String(right), 'zh-CN', { numeric: true })
}

function flatten(values: EvalValue[]): CellValue[] {
  const output: CellValue[] = []
  for (const value of values) {
    if (isRangeValue(value)) {
      for (const row of value.values) output.push(...row)
    } else {
      output.push(value)
    }
  }
  return output
}

function numbers(values: EvalValue[]): number[] {
  return flatten(values)
    .filter((value) => value !== null && value !== '' && typeof value !== 'boolean')
    .map((value) => {
      if (typeof value === 'number') return value
      const text = String(value).trim()
      return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?$/.test(text)
        ? Number(text.endsWith('%') ? text.slice(0, -1) : text) / (text.endsWith('%') ? 100 : 1)
        : Number.NaN
    })
    .filter((value) => Number.isFinite(value))
}

function numericArg(value: EvalValue): number {
  return toNumber(scalar(value))
}

function textArg(value: EvalValue): string {
  return toText(scalar(value))
}

function dateFromValue(value: CellValue): Date {
  if (typeof value === 'number') {
    // Excel 序列号（1900 日期系统）
    return new Date(Date.UTC(1899, 11, 30) + Math.round(value * 86400000))
  }
  const text = String(value ?? '').trim()
  const match = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/.exec(text)
  if (match) {
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  }
  const parsed = new Date(text)
  if (Number.isNaN(parsed.getTime())) throw new FormulaError('#VALUE!')
  return parsed
}

function isoDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function matchCriteria(value: CellValue, criteria: CellValue): boolean {
  if (criteria === null || criteria === '') return value === null || value === ''
  if (typeof criteria === 'number' || typeof criteria === 'boolean') {
    return compareValues(value, criteria) === 0
  }
  const text = String(criteria)
  const match = /^(<=|>=|<>|<|>|=)?([\s\S]*)$/.exec(text)
  if (!match) return compareValues(value, criteria) === 0
  const op = match[1] || ''
  const operand = match[2] ?? ''
  if (op) {
    const numericOperand = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(operand)
      ? Number(operand)
      : operand
    const comparison = compareValues(value, numericOperand)
    if (op === '=') return comparison === 0
    if (op === '<>') return comparison !== 0
    if (op === '<') return comparison < 0
    if (op === '>') return comparison > 0
    if (op === '<=') return comparison <= 0
    if (op === '>=') return comparison >= 0
  }
  if (operand.includes('*') || operand.includes('?')) {
    const pattern = operand
      .replace(/[.+^${}()|[\]\\]/g, '\\$&')
      .replace(/\*/g, '.*')
      .replace(/\?/g, '.')
    return new RegExp(`^${pattern}$`, 'i').test(String(value ?? ''))
  }
  return compareValues(value, operand) === 0
}

function evaluateFunction(ctx: EvalContext, node: AstNode & { kind: 'call' }, sheetId: string): EvalValue {
  const name = node.name
  // 惰性函数：只计算命中的分支，错误的未命中分支不应污染结果。
  if (name === 'IF') {
    const condition = scalar(evaluateAst(ctx, node.args[0] ?? { kind: 'boolean', value: false }, sheetId))
    const branch = toBoolean(condition) ? node.args[1] : node.args[2]
    return branch ? evaluateAst(ctx, branch, sheetId) : false
  }
  if (name === 'IFERROR' || name === 'IFNA') {
    try {
      return evaluateAst(ctx, node.args[0] ?? { kind: 'error', code: '#VALUE!' }, sheetId)
    } catch (error) {
      if (!(error instanceof FormulaError)) throw error
      if (name === 'IFNA' && error.code !== '#N/A') throw error
      return node.args[1] ? evaluateAst(ctx, node.args[1], sheetId) : ''
    }
  }
  if (name === 'AND' || name === 'OR') {
    let result = name === 'AND'
    for (const arg of node.args) {
      for (const value of flatten([evaluateAst(ctx, arg, sheetId)])) {
        const truthy = toBoolean(value)
        result = name === 'AND' ? result && truthy : result || truthy
      }
    }
    return result
  }
  if (name === 'ISERROR' || name === 'ISERR' || name === 'ISNA') {
    try {
      evaluateAst(ctx, node.args[0] ?? { kind: 'error', code: '#VALUE!' }, sheetId)
      return false
    } catch (error) {
      if (!(error instanceof FormulaError)) return false
      if (name === 'ISNA') return error.code === '#N/A'
      if (name === 'ISERR') return error.code !== '#N/A'
      return true
    }
  }

  const args = node.args.map((arg) => evaluateAst(ctx, arg, sheetId))
  const values = flatten(args)
  const nums = numbers(args)
  const text = textArg(args[0] ?? null)

  switch (name) {
    case 'SUM':
      return nums.reduce((sum, value) => sum + value, 0)
    case 'AVERAGE': {
      if (!nums.length) throw new FormulaError('#DIV/0!')
      return nums.reduce((sum, value) => sum + value, 0) / nums.length
    }
    case 'MIN':
      return nums.length ? Math.min(...nums) : 0
    case 'MAX':
      return nums.length ? Math.max(...nums) : 0
    case 'COUNT':
      return nums.length
    case 'COUNTA':
      return values.filter((value) => value !== null && value !== '').length
    case 'COUNTBLANK':
      return values.filter((value) => value === null || value === '').length
    case 'MEDIAN': {
      if (!nums.length) throw new FormulaError('#NUM!')
      const sorted = [...nums].sort((a, b) => a - b)
      const middle = Math.floor(sorted.length / 2)
      return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
    }
    case 'PRODUCT':
      return nums.length ? nums.reduce((product, value) => product * value, 1) : 0
    case 'SUMSQ':
      return nums.reduce((sum, value) => sum + value * value, 0)
    case 'STDEV':
    case 'STDEVP': {
      if (nums.length < (name === 'STDEV' ? 2 : 1)) throw new FormulaError('#DIV/0!')
      const mean = nums.reduce((sum, value) => sum + value, 0) / nums.length
      const variance =
        nums.reduce((sum, value) => sum + (value - mean) ** 2, 0) /
        (name === 'STDEV' ? nums.length - 1 : nums.length)
      return Math.sqrt(variance)
    }
    case 'SUMPRODUCT': {
      const arrays = args.map((arg) => (isRangeValue(arg) ? flatten([arg]) : [scalar(arg)]))
      const length = Math.max(...arrays.map((array) => array.length))
      let total = 0
      for (let index = 0; index < length; index += 1) {
        total += arrays.reduce(
          (product, array) => product * toNumber(array[index] ?? null),
          1,
        )
      }
      return total
    }
    case 'ABS':
      return Math.abs(numericArg(args[0] ?? null))
    case 'SQRT': {
      const value = numericArg(args[0] ?? null)
      if (value < 0) throw new FormulaError('#NUM!')
      return Math.sqrt(value)
    }
    case 'POWER':
      return numericArg(args[0] ?? null) ** numericArg(args[1] ?? null)
    case 'MOD': {
      const divisor = numericArg(args[1] ?? null)
      if (divisor === 0) throw new FormulaError('#DIV/0!')
      return numericArg(args[0] ?? null) % divisor
    }
    case 'INT':
      return Math.floor(numericArg(args[0] ?? null))
    case 'TRUNC': {
      const digits = Math.trunc(numericArg(args[1] ?? 0))
      const factor = 10 ** digits
      return Math.trunc(numericArg(args[0] ?? null) * factor) / factor
    }
    case 'ROUND': {
      const digits = Math.trunc(numericArg(args[1] ?? 0))
      const factor = 10 ** digits
      return Math.round(numericArg(args[0] ?? null) * factor) / factor
    }
    case 'ROUNDUP': {
      const digits = Math.trunc(numericArg(args[1] ?? 0))
      const factor = 10 ** digits
      const value = numericArg(args[0] ?? null)
      return (value >= 0 ? Math.ceil(value * factor) : Math.floor(value * factor)) / factor
    }
    case 'ROUNDDOWN': {
      const digits = Math.trunc(numericArg(args[1] ?? 0))
      const factor = 10 ** digits
      const value = numericArg(args[0] ?? null)
      return (value >= 0 ? Math.floor(value * factor) : Math.ceil(value * factor)) / factor
    }
    case 'CEILING':
    case 'FLOOR': {
      const step = numericArg(args[1] ?? 1)
      if (step === 0) throw new FormulaError('#DIV/0!')
      const value = numericArg(args[0] ?? null)
      const quotient = value / step
      return (name === 'CEILING' ? Math.ceil(quotient) : Math.floor(quotient)) * step
    }
    case 'EXP':
      return Math.exp(numericArg(args[0] ?? null))
    case 'LN': {
      const value = numericArg(args[0] ?? null)
      if (value <= 0) throw new FormulaError('#NUM!')
      return Math.log(value)
    }
    case 'LOG10': {
      const value = numericArg(args[0] ?? null)
      if (value <= 0) throw new FormulaError('#NUM!')
      return Math.log10(value)
    }
    case 'LOG': {
      const value = numericArg(args[0] ?? null)
      const base = args.length > 1 ? numericArg(args[1]) : 10
      if (value <= 0 || base <= 0 || base === 1) throw new FormulaError('#NUM!')
      return Math.log(value) / Math.log(base)
    }
    case 'PI':
      return Math.PI
    case 'RAND':
      return Math.random()
    case 'RANDBETWEEN':
      return (
        Math.floor(Math.random() * (numericArg(args[1] ?? 1) - numericArg(args[0] ?? 0) + 1)) +
        numericArg(args[0] ?? 0)
      )
    case 'NOT':
      return !toBoolean(scalar(args[0] ?? null))
    case 'XOR':
      return values.reduce((result, value) => result !== toBoolean(value), false)
    case 'CONCAT':
    case 'CONCATENATE':
      return values.map((value) => toText(value)).join('')
    case 'LEN':
      return text.length
    case 'LEFT':
      return text.slice(0, Math.max(0, Math.trunc(numericArg(args[1] ?? 1))))
    case 'RIGHT': {
      const count = Math.max(0, Math.trunc(numericArg(args[1] ?? 1)))
      return count ? text.slice(-count) : ''
    }
    case 'MID': {
      const start = Math.max(1, Math.trunc(numericArg(args[1] ?? 1)))
      const count = Math.max(0, Math.trunc(numericArg(args[2] ?? 0)))
      return text.slice(start - 1, start - 1 + count)
    }
    case 'UPPER':
      return text.toUpperCase()
    case 'LOWER':
      return text.toLowerCase()
    case 'PROPER':
      return text.replace(/\b\w/g, (char) => char.toUpperCase())
    case 'TRIM':
      return text.replace(/\s+/g, ' ').trim()
    case 'SUBSTITUTE': {
      const oldText = textArg(args[1] ?? null)
      const newText = textArg(args[2] ?? null)
      if (!oldText) return text
      if (args.length > 3) {
        const occurrence = Math.max(1, Math.trunc(numericArg(args[3])))
        let seen = 0
        return text.replaceAll(oldText, (match) => {
          seen += 1
          return seen === occurrence ? newText : match
        })
      }
      return text.split(oldText).join(newText)
    }
    case 'TEXT': {
      const format = textArg(args[1] ?? null).toLowerCase()
      return formatSheetValue(scalar(args[0] ?? null), inferFormat(format))
    }
    case 'VALUE': {
      return toNumber(scalar(args[0] ?? null))
    }
    case 'TODAY':
      return isoDate(new Date())
    case 'NOW':
      return new Date().toLocaleString('zh-CN', { hour12: false })
    case 'DATE':
      return isoDate(
        new Date(
          Math.trunc(numericArg(args[0] ?? 1970)),
          Math.trunc(numericArg(args[1] ?? 1)) - 1,
          Math.trunc(numericArg(args[2] ?? 1)),
        ),
      )
    case 'YEAR':
      return dateFromValue(scalar(args[0] ?? null)).getFullYear()
    case 'MONTH':
      return dateFromValue(scalar(args[0] ?? null)).getMonth() + 1
    case 'DAY':
      return dateFromValue(scalar(args[0] ?? null)).getDate()
    case 'WEEKDAY':
      return dateFromValue(scalar(args[0] ?? null)).getDay() + 1
    case 'DAYS': {
      const end = dateFromValue(scalar(args[0] ?? null)).getTime()
      const start = dateFromValue(scalar(args[1] ?? null)).getTime()
      return Math.round((end - start) / 86400000)
    }
    case 'COUNTIF': {
      const range = args[0]
      if (!isRangeValue(range)) return 0
      const criteria = scalar(args[1] ?? null)
      return flatten([range]).filter((value) => matchCriteria(value, criteria)).length
    }
    case 'SUMIF':
    case 'AVERAGEIF': {
      const range = args[0]
      if (!isRangeValue(range)) {
        throw new FormulaError('#VALUE!')
      }
      const criteria = scalar(args[1] ?? null)
      const target = isRangeValue(args[2] ?? null) ? flatten([args[2] as RangeValue]) : flatten([range])
      const source = flatten([range])
      const matched = source
        .map((value, index) => (matchCriteria(value, criteria) ? target[index] : null))
        .filter((value): value is CellValue => value !== null)
        .map((value) => toNumber(value))
      if (name === 'SUMIF') return matched.reduce((sum, value) => sum + value, 0)
      if (!matched.length) throw new FormulaError('#DIV/0!')
      return matched.reduce((sum, value) => sum + value, 0) / matched.length
    }
    case 'VLOOKUP': {
      const lookup = scalar(args[0] ?? null)
      const table = args[1]
      if (!isRangeValue(table)) throw new FormulaError('#VALUE!')
      const column = Math.trunc(numericArg(args[2] ?? 1)) - 1
      if (column < 0) throw new FormulaError('#REF!')
      const exact = args.length > 3 ? !toBoolean(scalar(args[3])) : false
      let candidate: CellValue | undefined
      for (const row of table.values) {
        const key = row[0] ?? null
        if (compareValues(key, lookup) === 0) return row[column] ?? null
        if (!exact && compareValues(key, lookup) < 0) candidate = row[column]
      }
      if (!exact && candidate !== undefined) return candidate
      throw new FormulaError('#N/A')
    }
    case 'INDEX': {
      const table = args[0]
      if (!isRangeValue(table)) throw new FormulaError('#VALUE!')
      const row = Math.trunc(numericArg(args[1] ?? 1)) - 1
      const col = Math.trunc(numericArg(args[2] ?? 1)) - 1
      if (row < 0 || row >= table.values.length) throw new FormulaError('#REF!')
      if (col < 0 || col >= (table.values[row]?.length ?? 0)) throw new FormulaError('#REF!')
      return table.values[row][col] ?? null
    }
    case 'MATCH': {
      const lookup = scalar(args[0] ?? null)
      const range = args[1]
      if (!isRangeValue(range)) throw new FormulaError('#N/A')
      const values = flatten([range])
      const exact = args.length < 3 || numericArg(args[2]) === 0
      for (let index = 0; index < values.length; index += 1) {
        if (compareValues(values[index] ?? null, lookup) === 0) return index + 1
      }
      if (exact) throw new FormulaError('#N/A')
      let candidate = 0
      for (let index = 0; index < values.length; index += 1) {
        if (compareValues(values[index] ?? null, lookup) <= 0) candidate = index + 1
      }
      if (!candidate) throw new FormulaError('#N/A')
      return candidate
    }
    case 'ISBLANK':
      return scalar(args[0] ?? null) === null
    case 'ISNUMBER':
      return typeof scalar(args[0] ?? null) === 'number'
    case 'ISTEXT':
      return typeof scalar(args[0] ?? null) === 'string'
    case 'NA':
      throw new FormulaError('#N/A')
    default:
      throw new FormulaError('#NAME?')
  }
}

function inferFormat(format: string): SheetNumberFormat {
  if (!format) return 'general'
  if (format.includes('%')) return 'percent'
  if (format.includes('yy') || format.includes('mm') || format.includes('dd')) return 'date'
  if (/[¥￥$€£]/.test(format)) return 'currency'
  if (format.includes('@')) return 'text'
  if (/[0#]/.test(format)) return 'number'
  return 'general'
}

/** 计算整本工作簿；返回的 key 为 `sheetId!A1`。 */
export function evaluateWorkbook(workbook: SheetWorkbook): Map<string, FormulaResult> {
  const ctx: EvalContext = {
    workbook,
    sheetId: workbook.active,
    cache: new Map(),
    stack: new Set(),
  }
  for (const sheet of workbook.sheets) {
    for (const [address, cell] of Object.entries(sheet.cells)) {
      if (!cell.f) continue
      try {
        evalCell(ctx, sheet.id, address)
      } catch {
        // 错误已写入缓存，由 UI 展示
      }
    }
  }
  // 常量也写入缓存，方便统一读取
  for (const sheet of workbook.sheets) {
    for (const [address, cell] of Object.entries(sheet.cells)) {
      const key = `${sheet.id}!${address}`
      if (!ctx.cache.has(key)) ctx.cache.set(key, { value: cell.v ?? null })
    }
  }
  return ctx.cache
}

export function computedCell(
  results: Map<string, FormulaResult>,
  sheetId: string,
  address: string,
): FormulaResult {
  return results.get(`${sheetId}!${address}`) ?? { value: null }
}

// ---------- 显示格式 ----------

const NUMBER_FORMATTER = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 2,
})

export function formatGeneralNumber(value: number): string {
  if (!Number.isFinite(value)) return '#NUM!'
  if (Number.isInteger(value)) return String(value)
  const rounded = Math.round(value * 1e10) / 1e10
  return String(rounded)
}

export function formatSheetValue(value: CellValue, fmt?: SheetNumberFormat): string {
  if (value === null) return ''
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE'
  if (typeof value === 'string') {
    if (fmt === 'number' || fmt === 'percent' || fmt === 'currency') {
      const number = Number(value.replace(/[,%¥￥$€£\s]/g, ''))
      if (Number.isFinite(number) && value.trim() !== '') {
        return formatSheetValue(number, fmt)
      }
    }
    return value
  }
  if (!Number.isFinite(value)) return '#NUM!'
  if (fmt === 'percent') {
    return `${NUMBER_FORMATTER.format(value * 100)}%`
  }
  if (fmt === 'currency') {
    return `¥${NUMBER_FORMATTER.format(value)}`
  }
  if (fmt === 'date') {
    return isoDate(new Date(Date.UTC(1899, 11, 30) + Math.round(value * 86400000)))
  }
  if (fmt === 'number') {
    return NUMBER_FORMATTER.format(value)
  }
  return formatGeneralNumber(value)
}

export function cellDisplayText(
  results: Map<string, FormulaResult>,
  sheetId: string,
  address: string,
  style?: SheetCellStyle,
): string {
  const result = computedCell(results, sheetId, address)
  if (result.error) return result.error
  return formatSheetValue(result.value, style?.fmt)
}

// ---------- 插入 / 删除行列时调整公式引用 ----------

function shiftRefAddress(
  address: string,
  axis: 'row' | 'col',
  index: number,
  delta: number,
): string | null {
  const parsed = parseAddress(address)
  if (!parsed) return null
  const target = axis === 'row' ? parsed.row : parsed.col
  if (delta < 0) {
    if (target === index) return null
    if (target < index) return address
    if (axis === 'row') parsed.row += delta
    else parsed.col += delta
  } else if (delta > 0) {
    if (target >= index) {
      if (axis === 'row') parsed.row += delta
      else parsed.col += delta
    }
  }
  return cellAddress(parsed.row, parsed.col)
}

/**
 * 行列增删后调整公式中的引用。
 *
 * @param onlyQualified 为 true 时只调整显式引用该工作表的引用（用于其他工作表中的公式）。
 */
export function shiftFormula(
  formula: string,
  sheetName: string,
  axis: 'row' | 'col',
  index: number,
  delta: number,
  onlyQualified = false,
): string {
  const tokens = tokenize(formula)
  let replaced = ''
  let cursor = 0
  let changed = false
  let pendingSheet: string | null = null
  for (let position = 0; position < tokens.length; position += 1) {
    const token = tokens[position]
    if (token.type === 'op' && token.value === '!') {
      pendingSheet = tokens[position - 1]?.value ?? null
      continue
    }
    if (token.type !== 'ident' || !CELL_REF_RE.test(token.value)) {
      if (token.type === 'punct' && token.value === ',') pendingSheet = null
      continue
    }
    const next = tokens[position + 1]
    if (next?.type === 'punct' && next.value === '(') {
      pendingSheet = null
      continue
    }
    const qualifier = pendingSheet
    const qualified = !!qualifier && qualifier.toLowerCase() === sheetName.toLowerCase()
    const applies = qualified || (!onlyQualified && !qualifier)
    pendingSheet = null
    if (!applies) continue
    const original = token.value.replace(/\$/g, '').toUpperCase()
    const shiftedCell = shiftRefAddress(original, axis, index, delta)
    const replacement = shiftedCell
      ? token.value.includes('$')
        ? token.value.replace(/[A-Za-z]+\d+/, shiftedCell)
        : shiftedCell
      : '#REF!'
    if (replacement !== token.value) {
      replaced += formula.slice(cursor, token.start) + replacement
      cursor = token.end
      changed = true
    }
  }
  return changed ? replaced + formula.slice(cursor) : formula
}

function translateRef(token: string, deltaRow: number, deltaCol: number): string {
  const match = /^(\$?)([A-Za-z]{1,3})(\$?)(\d+)$/.exec(token)
  if (!match) return token
  let col = columnIndex(match[2])
  let row = Number(match[4]) - 1
  if (!match[1]) col += deltaCol
  if (!match[3]) row += deltaRow
  if (col < 0 || row < 0 || col >= MAX_COL_INDEX || row >= MAX_ROW_INDEX) return '#REF!'
  return `${match[1]}${columnLabel(col)}${match[3]}${row + 1}`
}

const MAX_COL_INDEX = 16384
const MAX_ROW_INDEX = 1048576

/**
 * 复制 / 粘贴时按相对偏移平移公式引用。
 * 含 `$` 的行 / 列保持绝对引用。
 */
export function translateFormula(formula: string, deltaRow: number, deltaCol: number): string {
  const prefix = formula.startsWith('=') ? '=' : ''
  const source = formula.startsWith('=') ? formula.slice(1) : formula
  if (!deltaRow && !deltaCol) return formula
  if (!source) return formula
  const tokens = tokenize(source)
  let replaced = ''
  let cursor = 0
  for (let position = 0; position < tokens.length; position += 1) {
    const token = tokens[position]
    if (token.type !== 'ident' || !CELL_REF_RE.test(token.value)) continue
    if (tokens[position + 1]?.type === 'op' && tokens[position + 1].value === '!') continue
    const translated = translateRef(token.value, deltaRow, deltaCol)
    if (translated === token.value) continue
    replaced += source.slice(cursor, token.start) + translated
    cursor = token.end
  }
  return prefix + (cursor ? replaced + source.slice(cursor) : source)
}

export { columnLabel }
