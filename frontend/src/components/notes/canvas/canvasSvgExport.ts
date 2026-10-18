/**
 * 画布 → SVG 导出。
 * 与 CanvasStage 使用同一套几何 / 文本排版规则，把节点、连线、主题色
 * 序列化为独立 SVG 文件，便于分享、插入文档或继续用矢量工具编辑。
 */
import {
  anchorPoint,
  boundsOf,
  facingSide,
  nodeCenter,
  DEFAULT_FONT_SIZE,
  type CanvasDoc,
  type CanvasEdge,
  type CanvasNode,
  type CanvasSide,
} from './types'
import { themeOf, toneStyle } from './themes'

const PADDING = 40
const GRID = 16
const FONT_FAMILY =
  "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"

interface Point {
  x: number
  y: number
}

function num(value: number): number {
  return Number.isFinite(value) ? Math.round(value * 10) / 10 : 0
}

function esc(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function charWidth(ch: string, size: number): number {
  if (/[⺀-鿿豈-﫿＀-￯]/.test(ch)) return size
  if (/\s/.test(ch)) return size * 0.33
  if (/[A-Z0-9]/.test(ch)) return size * 0.64
  if (/[a-z]/.test(ch)) return size * 0.53
  return size * 0.5
}

function wrapText(text: string, maxWidth: number, fontSize: number): string[] {
  const lines: string[] = []
  for (const raw of text.split('\n')) {
    let line = ''
    let width = 0
    for (const ch of Array.from(raw)) {
      const w = charWidth(ch, fontSize)
      if (line && width + w > maxWidth) {
        lines.push(line.trimEnd())
        line = ch
        width = w
      } else {
        line += ch
        width += w
      }
    }
    lines.push(line.trimEnd())
  }
  return lines.length ? lines : ['']
}

function clipText(text: string, maxWidth: number, fontSize: number): string {
  if (maxWidth <= 0) return ''
  let out = ''
  let width = 0
  for (const ch of Array.from(text)) {
    const w = charWidth(ch, fontSize)
    if (width + w > maxWidth) {
      return `${out.slice(0, Math.max(0, out.length - 1))}…`
    }
    out += ch
    width += w
  }
  return out
}

function sideDir(side: CanvasSide): Point {
  switch (side) {
    case 'right':
      return { x: 1, y: 0 }
    case 'left':
      return { x: -1, y: 0 }
    case 'top':
      return { x: 0, y: -1 }
    default:
      return { x: 0, y: 1 }
  }
}

function dedupePoints(points: Point[]): Point[] {
  return points.filter((point, index) => {
    if (!index) return true
    const prev = points[index - 1]
    return Math.abs(point.x - prev.x) > 0.5 || Math.abs(point.y - prev.y) > 0.5
  })
}

function polylineMid(points: Point[]): Point {
  if (points.length === 1) return points[0]
  let total = 0
  const lengths: number[] = []
  for (let i = 1; i < points.length; i += 1) {
    const len = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y)
    lengths.push(len)
    total += len
  }
  let remain = total / 2
  for (let i = 0; i < lengths.length; i += 1) {
    if (remain <= lengths[i]) {
      const t = lengths[i] ? remain / lengths[i] : 0
      return {
        x: points[i].x + (points[i + 1].x - points[i].x) * t,
        y: points[i].y + (points[i + 1].y - points[i].y) * t,
      }
    }
    remain -= lengths[i]
  }
  return points[points.length - 1]
}

function roundedPath(points: Point[], radius = 12): string {
  const pts = dedupePoints(points)
  if (pts.length < 2) return pts.length ? `M ${num(pts[0].x)} ${num(pts[0].y)}` : ''
  let d = `M ${num(pts[0].x)} ${num(pts[0].y)}`
  for (let i = 1; i < pts.length - 1; i += 1) {
    const prev = pts[i - 1]
    const cur = pts[i]
    const next = pts[i + 1]
    const d1 = Math.hypot(cur.x - prev.x, cur.y - prev.y)
    const d2 = Math.hypot(next.x - cur.x, next.y - cur.y)
    const r = Math.min(radius, d1 / 2, d2 / 2)
    if (r < 1.5) {
      d += ` L ${num(cur.x)} ${num(cur.y)}`
      continue
    }
    const before = {
      x: cur.x + ((prev.x - cur.x) / d1) * r,
      y: cur.y + ((prev.y - cur.y) / d1) * r,
    }
    const after = {
      x: cur.x + ((next.x - cur.x) / d2) * r,
      y: cur.y + ((next.y - cur.y) / d2) * r,
    }
    d += ` L ${num(before.x)} ${num(before.y)} Q ${num(cur.x)} ${num(cur.y)} ${num(after.x)} ${num(after.y)}`
  }
  const last = pts[pts.length - 1]
  d += ` L ${num(last.x)} ${num(last.y)}`
  return d
}

function headerPath(node: CanvasNode, rx: number, height: number): string {
  const x = num(node.x)
  const y = num(node.y)
  const w = num(node.w)
  const r = num(Math.min(rx, height / 2, node.w / 2))
  return `M ${num(x + r)} ${y} H ${num(x + w - r)} Q ${num(x + w)} ${y} ${num(x + w)} ${num(y + r)} V ${num(y + height)} H ${x} V ${num(y + r)} Q ${x} ${y} ${num(x + r)} ${y} Z`
}

interface EdgeSides {
  fromSide: CanvasSide
  toSide: CanvasSide
}

interface EdgeGeometry {
  d: string
  mid: Point
  from: Point
  to: Point
}

interface NodeLayout {
  lines: string[]
  baselines: number[]
  textX: number
  anchor: 'middle' | 'start'
  title: string
  titleX: number
  titleBaseline: number
  titleAnchor: 'middle' | 'start'
  bodyFontSize: number
  tableRows: Array<{ key: string; text: string; textX: number }>
  bodyBaselines: number[]
  rowLines: number[]
  networkLines: string[]
  networkBaselines: number[]
  centerX: number
  iconY: number
  rx: number
}

function layoutNode(node: CanvasNode): NodeLayout {
  const fontSize = node.fontSize ?? DEFAULT_FONT_SIZE
  const lineHeight = fontSize * 1.45
  const padX = node.shape === 'diamond' ? node.w * 0.2 : 14
  const maxWidth = Math.max(20, node.w - padX * 2)
  const lines = wrapText(node.text || '', maxWidth, fontSize)
  const maxLines = Math.max(1, Math.floor((node.h - 12) / lineHeight))
  if (lines.length > maxLines) {
    lines.length = maxLines
    const last = lines[maxLines - 1] ?? ''
    lines[maxLines - 1] = `${last.slice(0, Math.max(0, last.length - 1))}…`
  }
  const totalHeight = lines.length * lineHeight
  const top = node.y + (node.h - totalHeight) / 2
  const baselines = lines.map((_, i) => top + fontSize * 0.86 + i * lineHeight)
  const alignLeft = node.align === 'left'

  const isUml = node.shape === 'uml'
  const isTable = node.shape === 'table'
  const headerH = isUml ? 34 : isTable ? 32 : 0
  const raw = (node.text || '').split('\n')
  const title = raw[0]?.trim() || (isUml ? 'ClassName' : 'table_name')
  const rawBody = raw.slice(1)
  while (rawBody.length && !rawBody[rawBody.length - 1].trim()) rawBody.pop()

  const bodyFontSize = Math.max(10, Math.min(14, fontSize - 3))
  let tableRows: Array<{ key: string; text: string; textX: number }> = []
  let bodyBaselines: number[] = []
  let rowLines: number[] = []

  if (isUml) {
    const rowH = bodyFontSize * 1.55
    const available = Math.max(0, node.h - headerH - 10)
    const maxRows = Math.max(1, Math.floor(available / rowH))
    tableRows = rawBody.slice(0, maxRows).map((line) => {
      const match = line.match(/^\s*([-+#~])?\s*(PK|FK|UQ|IDX)\b[\s:：-]*(.*)$/i)
      if (match) {
        const visibility = match[1] ? `${match[1]} ` : ''
        return {
          key: match[2].toUpperCase(),
          text: clipText(`${visibility}${match[3].trim()}`, node.w - 58, bodyFontSize),
          textX: node.x + 46,
        }
      }
      return {
        key: '',
        text: clipText(line, node.w - 24, bodyFontSize),
        textX: node.x + 12,
      }
    })
    if (rawBody.length > maxRows && tableRows.length) {
      tableRows[tableRows.length - 1] = { key: '', text: '…', textX: node.x + 12 }
    }
    bodyBaselines = tableRows.map((_, i) => node.y + headerH + 15 + i * rowH)
  } else if (isTable) {
    const rowH = 20
    const available = Math.max(0, node.h - headerH - 6)
    const maxRows = Math.max(1, Math.floor(available / rowH))
    tableRows = rawBody.slice(0, maxRows).map((line) => {
      const match = line.match(/^\s*(PK|FK|UQ|IDX)\b[\s:：-]*(.*)$/i)
      if (match) {
        return {
          key: match[1].toUpperCase(),
          text: clipText(match[2].trim(), node.w - 58, bodyFontSize),
          textX: node.x + 46,
        }
      }
      return {
        key: '',
        text: clipText(line.trim(), node.w - 24, bodyFontSize),
        textX: node.x + 12,
      }
    })
    if (rawBody.length > maxRows && tableRows.length) {
      tableRows[tableRows.length - 1] = { key: '', text: '…', textX: node.x + 12 }
    }
    tableRows.forEach((_, i) => {
      bodyBaselines.push(node.y + headerH + rowH * i + rowH * 0.68)
      if (i > 0) rowLines.push(node.y + headerH + rowH * i)
    })
  }

  const networkLines =
    node.shape === 'network'
      ? wrapText(node.text || '', Math.max(40, node.w - 24), 12.5)
      : []
  let networkBaselines: number[] = []
  if (node.shape === 'network') {
    const lineH = 17
    const maxLabelLines = Math.max(1, Math.floor((node.h - 58) / lineH))
    if (networkLines.length > maxLabelLines) networkLines.length = maxLabelLines
    const block = networkLines.length * lineH
    const labelTop = node.y + 56 + Math.max(0, (node.h - 56 - block) / 2)
    networkBaselines = networkLines.map((_, i) => labelTop + 12 + i * lineH)
  }

  return {
    lines,
    baselines,
    textX: alignLeft ? node.x + 14 : node.x + node.w / 2,
    anchor: alignLeft ? 'start' : 'middle',
    title,
    titleX: isUml ? node.x + node.w / 2 : node.x + 12,
    titleBaseline: node.y + (isUml ? 22 : 21),
    titleAnchor: isUml ? 'middle' : 'start',
    bodyFontSize,
    tableRows,
    bodyBaselines,
    rowLines,
    networkLines,
    networkBaselines,
    centerX: node.x + node.w / 2,
    iconY: node.y + 32,
    rx:
      node.shape === 'round'
        ? node.h / 2
        : node.shape === 'sticky'
          ? 4
          : node.shape === 'uml'
            ? 10
            : node.shape === 'network'
              ? 14
              : 12,
  }
}

function diamondPoints(node: CanvasNode): string {
  const cx = node.x + node.w / 2
  const cy = node.y + node.h / 2
  return `${num(cx)},${num(node.y)} ${num(node.x + node.w)},${num(cy)} ${num(cx)},${num(node.y + node.h)} ${num(node.x)},${num(cy)}`
}

function networkIcon(node: CanvasNode, stroke: string, iconY: number): string {
  const body: string[] = []
  const variant = node.variant ?? 'server'
  switch (variant) {
    case 'cloud':
      body.push('<path d="M-17 6 C-25 6 -25 -5 -16 -7 C-15 -17 3 -21 8 -10 C20 -13 25 3 16 7 Z"/>')
      break
    case 'database':
      body.push('<ellipse cx="0" cy="-10" rx="13" ry="4.5"/>')
      body.push('<path d="M-13 -10 V8 C-13 11.5 -7 14 0 14 C7 14 13 11.5 13 8 V-10"/>')
      body.push('<path d="M-13 0 C-13 3.5 -7 6 0 6 C7 6 13 3.5 13 0"/>')
      break
    case 'storage':
      body.push('<ellipse cx="0" cy="-13" rx="13" ry="4.5"/>')
      body.push('<path d="M-13 -13 V12 C-13 15.5 -7 18 0 18 C7 18 13 15.5 13 12 V-13"/>')
      body.push('<path d="M-13 -1 C-13 2.5 -7 5 0 5 C7 5 13 2.5 13 -1"/>')
      body.push('<path d="M-13 9 C-13 12.5 -7 15 0 15 C7 15 13 12.5 13 9"/>')
      break
    case 'router':
      body.push('<rect x="-16" y="3" width="32" height="12" rx="2.5"/>')
      body.push('<path d="M0 3 V-4"/><path d="m-4 -8 4 -4 4 4"/>')
      body.push(`<circle cx="-10" cy="9" r="0.9" fill="${stroke}" stroke="none"/>`)
      body.push(`<circle cx="-5" cy="9" r="0.9" fill="${stroke}" stroke="none"/>`)
      break
    case 'firewall':
      body.push('<rect x="-15" y="-13" width="30" height="26" rx="2.5"/>')
      body.push('<path d="M-15 -4 H15 M-15 5 H15"/>')
      body.push('<path d="M-5 -13 V-4 M5 -4 V5 M-5 5 V13"/>')
      break
    case 'client':
      body.push('<rect x="-15" y="-15" width="30" height="21" rx="2.5"/>')
      body.push('<path d="M0 6 V12 M-7 13 H7"/>')
      break
    case 'switch':
      body.push('<rect x="-15" y="-8" width="30" height="16" rx="2.5"/>')
      body.push('<path d="m-8 -12 3 -3 3 3 M8 -12l-3 -3-3 3"/>')
      for (const cx of [-10, -4, 4, 10]) {
        body.push(`<circle cx="${cx}" cy="0" r="0.9" fill="${stroke}" stroke="none"/>`)
      }
      break
    default:
      body.push('<rect x="-15" y="-15" width="30" height="12" rx="2"/>')
      body.push('<rect x="-15" y="3" width="30" height="12" rx="2"/>')
      body.push('<path d="M-10 -9 H-4 M-10 9 H-4"/>')
  }
  return `<g transform="translate(${num(node.x + node.w / 2)} ${num(iconY)})" fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${body.join('')}</g>`
}

function nodeSvg(node: CanvasNode, theme: ReturnType<typeof themeOf>): string {
  const tone = toneStyle(theme, node.tone)
  const layout = layoutNode(node)
  const parts: string[] = []
  const textFill = tone.text
  const isText = node.shape === 'text'
  const fill = isText || node.container ? 'transparent' : tone.fill
  const stroke = isText ? 'transparent' : tone.stroke
  const isEngineering = node.shape === 'uml' || node.shape === 'table'

  if (isEngineering) {
    parts.push(
      `<rect x="${num(node.x)}" y="${num(node.y)}" width="${num(node.w)}" height="${num(node.h)}" rx="${num(layout.rx)}" fill="${tone.fill}" stroke="${tone.stroke}" stroke-width="1.5"/>`,
    )
    parts.push(
      `<path d="${headerPath(node, layout.rx, node.shape === 'uml' ? 34 : 32)}" fill="${tone.stroke}" fill-opacity="0.18" stroke="${tone.stroke}" stroke-width="1.2"/>`,
    )
    parts.push(
      `<text x="${num(layout.titleX)}" y="${num(layout.titleBaseline)}" text-anchor="${layout.titleAnchor}" font-size="${node.shape === 'uml' ? 14 : 12.8}" font-weight="600" fill="${textFill}" font-family="${FONT_FAMILY}">${esc(layout.title)}</text>`,
    )
    for (const y of layout.rowLines) {
      parts.push(
        `<line x1="${num(node.x)}" x2="${num(node.x + node.w)}" y1="${num(y)}" y2="${num(y)}" stroke="${tone.stroke}" stroke-width="1" opacity="0.22"/>`,
      )
    }
    layout.tableRows.forEach((row, index) => {
      const baseline = layout.bodyBaselines[index]
      if (!Number.isFinite(baseline)) return
      if (row.key) {
        parts.push(
          `<text x="${num(node.x + 12)}" y="${num(baseline)}" font-size="8.8" font-weight="700" fill="${tone.stroke}" font-family="${FONT_FAMILY}">${esc(row.key)}</text>`,
        )
      }
      parts.push(
        `<text x="${num(row.textX)}" y="${num(baseline)}" font-size="${num(layout.bodyFontSize)}" fill="${textFill}" font-family="${FONT_FAMILY}">${esc(row.text)}</text>`,
      )
    })
    return parts.join('')
  }

  if (node.shape === 'network') {
    parts.push(
      `<rect x="${num(node.x)}" y="${num(node.y)}" width="${num(node.w)}" height="${num(node.h)}" rx="${num(layout.rx)}" fill="${tone.fill}" stroke="${tone.stroke}" stroke-width="1.5"/>`,
    )
    parts.push(networkIcon(node, tone.stroke, layout.iconY))
    if (layout.networkLines.length) {
      const tspans = layout.networkLines
        .map(
          (line, index) =>
            `<tspan x="${num(layout.centerX)}" y="${num(layout.networkBaselines[index])}">${esc(line)}</tspan>`,
        )
        .join('')
      parts.push(
        `<text text-anchor="middle" font-size="12.5" font-weight="500" fill="${textFill}" font-family="${FONT_FAMILY}">${tspans}</text>`,
      )
    }
    return parts.join('')
  }

  if (node.shape === 'ellipse') {
    parts.push(
      `<ellipse cx="${num(node.x + node.w / 2)}" cy="${num(node.y + node.h / 2)}" rx="${num(node.w / 2)}" ry="${num(node.h / 2)}" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>`,
    )
  } else if (node.shape === 'diamond') {
    parts.push(
      `<polygon points="${diamondPoints(node)}" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>`,
    )
  } else if (!isText) {
    parts.push(
      `<rect x="${num(node.x)}" y="${num(node.y)}" width="${num(node.w)}" height="${num(node.h)}" rx="${num(layout.rx)}" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>`,
    )
  }

  if (node.text) {
    const tspans = layout.lines
      .map(
        (line, index) =>
          `<tspan x="${num(layout.textX)}" y="${num(layout.baselines[index])}">${esc(line)}</tspan>`,
      )
      .join('')
    parts.push(
      `<text text-anchor="${layout.anchor}" font-size="${num(node.fontSize ?? DEFAULT_FONT_SIZE)}" font-weight="${node.bold ? 600 : 400}" fill="${textFill}" font-family="${FONT_FAMILY}">${tspans}</text>`,
    )
  }
  return parts.join('')
}

/** 生成完整、可独立打开的 SVG 文本。 */
export function canvasDocToSvg(doc: CanvasDoc): string {
  const theme = themeOf(doc.theme)
  const nodeMap = new Map(doc.nodes.map((node) => [node.id, node]))

  // 连线实际使用的节点边。
  const sides = new Map<string, EdgeSides>()
  for (const edge of doc.edges) {
    const fromNode = edge.from.nodeId ? nodeMap.get(edge.from.nodeId) : null
    const toNode = edge.to.nodeId ? nodeMap.get(edge.to.nodeId) : null
    const fromBase = fromNode ? nodeCenter(fromNode) : { x: edge.from.x, y: edge.from.y }
    const toBase = toNode ? nodeCenter(toNode) : { x: edge.to.x, y: edge.to.y }
    sides.set(edge.id, {
      fromSide: fromNode
        ? edge.from.side === 'auto'
          ? facingSide(fromNode, toBase)
          : edge.from.side
        : edge.from.side === 'auto'
          ? toBase.x >= fromBase.x
            ? 'right'
            : 'left'
          : edge.from.side,
      toSide: toNode
        ? edge.to.side === 'auto'
          ? facingSide(toNode, fromBase)
          : edge.to.side
        : edge.to.side === 'auto'
          ? fromBase.x >= toBase.x
            ? 'right'
            : 'left'
          : edge.to.side,
    })
  }

  // 同一条边上的多个连线端口均分。
  const groups = new Map<string, string[]>()
  for (const edge of doc.edges) {
    const side = sides.get(edge.id)
    if (!side) continue
    if (edge.from.nodeId) {
      const key = `${edge.from.nodeId}:${side.fromSide}`
      groups.set(key, [...(groups.get(key) ?? []), `${edge.id}:from`])
    }
    if (edge.to.nodeId) {
      const key = `${edge.to.nodeId}:${side.toSide}`
      groups.set(key, [...(groups.get(key) ?? []), `${edge.id}:to`])
    }
  }
  const ports = new Map<string, { index: number; count: number }>()
  for (const entries of groups.values()) {
    entries.forEach((entry, index) => ports.set(entry, { index, count: entries.length }))
  }

  const portPoint = (node: CanvasNode, side: CanvasSide, edgeId: string, end: 'from' | 'to'): Point => {
    if (node.shape === 'diamond' || node.shape === 'ellipse') return anchorPoint(node, side)
    const port = ports.get(`${edgeId}:${end}`)
    const t = port && port.count > 1 ? (port.index + 1) / (port.count + 1) : 0.5
    switch (side) {
      case 'top':
        return { x: node.x + node.w * t, y: node.y }
      case 'bottom':
        return { x: node.x + node.w * t, y: node.y + node.h }
      case 'left':
        return { x: node.x, y: node.y + node.h * t }
      default:
        return { x: node.x + node.w, y: node.y + node.h * t }
    }
  }

  const geometry = (edge: CanvasEdge): EdgeGeometry => {
    const fromNode = edge.from.nodeId ? nodeMap.get(edge.from.nodeId) : null
    const toNode = edge.to.nodeId ? nodeMap.get(edge.to.nodeId) : null
    const side = sides.get(edge.id) ?? { fromSide: 'right' as CanvasSide, toSide: 'left' as CanvasSide }
    const p1 = fromNode
      ? portPoint(fromNode, side.fromSide, edge.id, 'from')
      : { x: edge.from.x, y: edge.from.y }
    const p2 = toNode
      ? portPoint(toNode, side.toSide, edge.id, 'to')
      : { x: edge.to.x, y: edge.to.y }

    if (edge.curve === 'bezier') {
      const dx = Math.abs(p2.x - p1.x)
      const dy = Math.abs(p2.y - p1.y)
      const k = Math.max(36, Math.min(180, dx * 0.5 + dy * 0.15))
      const d1 = sideDir(side.fromSide)
      const d2 = sideDir(side.toSide)
      const c1 = { x: p1.x + d1.x * k, y: p1.y + d1.y * k }
      const c2 = { x: p2.x + d2.x * k, y: p2.y + d2.y * k }
      return {
        d: `M ${num(p1.x)} ${num(p1.y)} C ${num(c1.x)} ${num(c1.y)} ${num(c2.x)} ${num(c2.y)} ${num(p2.x)} ${num(p2.y)}`,
        mid: {
          x: (p1.x + 3 * c1.x + 3 * c2.x + p2.x) / 8,
          y: (p1.y + 3 * c1.y + 3 * c2.y + p2.y) / 8,
        },
        from: p1,
        to: p2,
      }
    }

    if (edge.curve === 'straight') {
      return {
        d: `M ${num(p1.x)} ${num(p1.y)} L ${num(p2.x)} ${num(p2.y)}`,
        mid: { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 },
        from: p1,
        to: p2,
      }
    }

    const off = 22
    const d1 = sideDir(side.fromSide)
    const d2 = sideDir(side.toSide)
    const a = { x: p1.x + d1.x * off, y: p1.y + d1.y * off }
    const b = { x: p2.x + d2.x * off, y: p2.y + d2.y * off }
    const points: Point[] = [p1, a]
    const horizontal1 = side.fromSide === 'left' || side.fromSide === 'right'
    const horizontal2 = side.toSide === 'left' || side.toSide === 'right'
    if (horizontal1 && horizontal2) {
      const dir1 = side.fromSide === 'right' ? 1 : -1
      const dir2 = side.toSide === 'right' ? 1 : -1
      if (dir1 === dir2) {
        const outerX = dir1 > 0 ? Math.max(a.x, b.x) + 26 : Math.min(a.x, b.x) - 26
        points.push({ x: outerX, y: a.y }, { x: outerX, y: b.y })
      } else {
        const mx = (a.x + b.x) / 2
        points.push({ x: mx, y: a.y }, { x: mx, y: b.y })
      }
    } else if (!horizontal1 && !horizontal2) {
      const dir1 = side.fromSide === 'bottom' ? 1 : -1
      const dir2 = side.toSide === 'bottom' ? 1 : -1
      if (dir1 === dir2) {
        const outerY = dir1 > 0 ? Math.max(a.y, b.y) + 26 : Math.min(a.y, b.y) - 26
        points.push({ x: a.x, y: outerY }, { x: b.x, y: outerY })
      } else {
        const my = (a.y + b.y) / 2
        points.push({ x: a.x, y: my }, { x: b.x, y: my })
      }
    } else if (horizontal1) {
      points.push({ x: b.x, y: a.y })
    } else {
      points.push({ x: a.x, y: b.y })
    }
    points.push(b, p2)
    return { d: roundedPath(points), mid: polylineMid(points), from: p1, to: p2 }
  }

  // 包围盒：节点 + 自由端点，并留出投影 / 标签余量。
  const bounds = boundsOf(doc.nodes)
  let minX = doc.nodes.length ? bounds.x : 0
  let minY = doc.nodes.length ? bounds.y : 0
  let maxX = doc.nodes.length ? bounds.x + bounds.w : 640
  let maxY = doc.nodes.length ? bounds.y + bounds.h : 400
  for (const edge of doc.edges) {
    if (!edge.from.nodeId) {
      minX = Math.min(minX, edge.from.x)
      maxX = Math.max(maxX, edge.from.x)
      minY = Math.min(minY, edge.from.y)
      maxY = Math.max(maxY, edge.from.y)
    }
    if (!edge.to.nodeId) {
      minX = Math.min(minX, edge.to.x)
      maxX = Math.max(maxX, edge.to.x)
      minY = Math.min(minY, edge.to.y)
      maxY = Math.max(maxY, edge.to.y)
    }
  }
  const offsetX = PADDING - minX
  const offsetY = PADDING - minY
  const width = Math.max(320, Math.ceil(maxX - minX + PADDING * 2))
  const height = Math.max(220, Math.ceil(maxY - minY + PADDING * 2))

  const defs: string[] = [
    `<pattern id="kiwi-export-grid" width="${GRID}" height="${GRID}" patternUnits="userSpaceOnUse"><circle cx="1.2" cy="1.2" r="1.1" fill="${theme.gridStrong}"/></pattern>`,
  ]
  const markerColors: Array<[string, string]> = [['default', theme.edge]]
  for (const [tone, style] of Object.entries(theme.tones)) {
    markerColors.push([tone, style.stroke])
  }
  for (const [tone, color] of markerColors) {
    defs.push(
      `<marker id="kiwi-export-arrow-${tone}" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto-start-reverse" markerUnits="strokeWidth"><path d="M0 0 L6 3 L0 6 Z" fill="${color}"/></marker>`,
    )
  }

  const edges: string[] = []
  for (const edge of doc.edges) {
    const geo = geometry(edge)
    const color = edge.tone ? toneStyle(theme, edge.tone).stroke : theme.edge
    const marker = `url(#kiwi-export-arrow-${edge.tone ?? 'default'})`
    const dash = edge.dashed ? ' stroke-dasharray="7 6"' : ''
    const markerEnd = edge.arrow !== 'none' ? ` marker-end="${marker}"` : ''
    const markerStart = edge.arrow === 'both' ? ` marker-start="${marker}"` : ''
    edges.push(
      `<path d="${geo.d}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"${dash}${markerEnd}${markerStart}/>`,
    )
    const label = (edge.label ?? '').trim()
    if (label) {
      const labelW = Math.max(
        28,
        Array.from(label).reduce((sum, ch) => sum + charWidth(ch, 11), 0) + 14,
      )
      edges.push(
        `<rect x="${num(geo.mid.x - labelW / 2)}" y="${num(geo.mid.y - 10)}" width="${num(labelW)}" height="20" rx="6" fill="${theme.edgeLabelBg}" stroke="${theme.grid}" stroke-width="1"/>`,
      )
      edges.push(
        `<text x="${num(geo.mid.x)}" y="${num(geo.mid.y + 4)}" text-anchor="middle" font-size="11" fill="${theme.edge}" font-family="${FONT_FAMILY}">${esc(label)}</text>`,
      )
    }
  }

  const nodes = doc.nodes.map((node) => `<g>${nodeSvg(node, theme)}</g>`)

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `<defs>${defs.join('')}</defs>`,
    `<rect width="${width}" height="${height}" fill="${theme.bg}"/>`,
    `<g transform="translate(${num(offsetX)} ${num(offsetY)})">`,
    doc.grid
      ? `<rect x="${num(bounds.x - 24)}" y="${num(bounds.y - 24)}" width="${num(bounds.w + 48)}" height="${num(bounds.h + 48)}" fill="url(#kiwi-export-grid)"/>`
      : '',
    edges.join(''),
    nodes.join(''),
    '</g>',
    '</svg>',
  ].join('\n')
}
