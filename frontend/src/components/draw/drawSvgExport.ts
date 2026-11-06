/**
 * jvs-draw 文档 → 静态 SVG。
 *
 * 阅读态、分享页、便签预览与图片导出都不加载 20MB 级白板运行时，
 * 只读取元素数据直接绘制。这里覆盖常用图形、文本、图片与箭头，
 * 不追求与交互式画布逐像素一致，但保证布局、文字与配色正确。
 */
import {
  drawDocUsesHandFont,
  embedHandFontInSvg,
  HAND_FONT_STACK,
  isHandFont,
} from './handFont'
import {
  drawDocBackground,
  type DrawElement,
  type JvsDrawDoc,
} from './types'

const FONT_FAMILY =
  "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
const MONO_FAMILY = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
const CONNECTOR_TYPES = new Set(['arrow', 'line', 'freedraw'])
const PADDING = 32
const MIN_WIDTH = 320
const MIN_HEIGHT = 180

interface Bounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

interface RenderContext {
  elements: DrawElement[]
  files: Record<string, string>
  defs: string[]
  gradients: Map<string, string>
  patterns: Map<string, string>
  prefix: string
  /** 元素未显式设置字体时，沿用画布当前的字体偏好。 */
  defaultFontFamily?: unknown
}

let svgSeq = 0

function num(value: unknown, fallback = 0): number {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : fallback
}

function esc(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function attr(value: unknown): string {
  return esc(value).replace(/"/g, '&quot;')
}

function color(value: unknown, fallback = 'transparent'): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

function isTransparent(value: unknown): boolean {
  const text = color(value)
  return text === 'transparent' || text === 'none'
}

function opacity(value: unknown): number {
  return Math.min(1, Math.max(0, num(value, 100) / 100))
}

function pointsOf(element: DrawElement): Array<[number, number]> {
  if (!Array.isArray(element.points)) return []
  return element.points
    .filter((point): point is [number, number] => Array.isArray(point) && point.length >= 2)
    .map((point) => [num(point[0]), num(point[1])])
}

function rawBounds(element: DrawElement): Bounds {
  if (CONNECTOR_TYPES.has(element.type)) {
    const points = pointsOf(element)
    if (points.length) {
      const xs = points.map(([x]) => element.x + x)
      const ys = points.map(([, y]) => element.y + y)
      // 预留箭头头部的长度，避免端点贴边时被 viewBox 裁掉。
      return {
        minX: Math.min(...xs) - 18,
        minY: Math.min(...ys) - 18,
        maxX: Math.max(...xs) + 18,
        maxY: Math.max(...ys) + 18,
      }
    }
  }
  return {
    minX: element.x,
    minY: element.y,
    maxX: element.x + element.width,
    maxY: element.y + element.height,
  }
}

function rotatePoint(
  x: number,
  y: number,
  centerX: number,
  centerY: number,
  angle: number,
): { x: number; y: number } {
  const radians = (angle * Math.PI) / 180
  const cos = Math.cos(radians)
  const sin = Math.sin(radians)
  const dx = x - centerX
  const dy = y - centerY
  return {
    x: centerX + dx * cos - dy * sin,
    y: centerY + dx * sin + dy * cos,
  }
}

function rotatedBounds(element: DrawElement): Bounds {
  const box = rawBounds(element)
  const angle = num(element.angle)
  if (!angle) return box
  const centerX = (box.minX + box.maxX) / 2
  const centerY = (box.minY + box.maxY) / 2
  const corners = [
    { x: box.minX, y: box.minY },
    { x: box.maxX, y: box.minY },
    { x: box.maxX, y: box.maxY },
    { x: box.minX, y: box.maxY },
  ].map((point) => rotatePoint(point.x, point.y, centerX, centerY, angle))
  return {
    minX: Math.min(...corners.map((point) => point.x)),
    minY: Math.min(...corners.map((point) => point.y)),
    maxX: Math.max(...corners.map((point) => point.x)),
    maxY: Math.max(...corners.map((point) => point.y)),
  }
}

function containerOf(element: DrawElement, elements: DrawElement[]): DrawElement | null {
  const containerId = typeof element.containerId === 'string' ? element.containerId : ''
  if (!containerId) return null
  return elements.find((item) => item.id === containerId) || null
}

function textBox(element: DrawElement, elements: DrawElement[]): Bounds {
  const container = containerOf(element, elements)
  if (container) {
    return {
      minX: container.x,
      minY: container.y,
      maxX: container.x + container.width,
      maxY: container.y + container.height,
    }
  }
  return {
    minX: element.x,
    minY: element.y,
    maxX: element.x + element.width,
    maxY: element.y + element.height,
  }
}

function charWidth(char: string, fontSize: number): number {
  if (/\s/.test(char)) return fontSize * 0.3
  if (/[⺀-￯]/.test(char)) return fontSize
  if (/[ilI.,'!|]/.test(char)) return fontSize * 0.3
  if (/[MW@#%&]/.test(char)) return fontSize * 0.82
  return fontSize * 0.58
}

function measure(text: string, fontSize: number, letterSpacing = 0): number {
  let width = 0
  for (const char of text) width += charWidth(char, fontSize) + letterSpacing
  return width
}

function wrapText(
  text: string,
  maxWidth: number,
  fontSize: number,
  letterSpacing = 0,
): string[] {
  const result: string[] = []
  for (const rawLine of String(text || '').replace(/\r\n?/g, '\n').split('\n')) {
    if (!rawLine) {
      result.push('')
      continue
    }
    if (maxWidth <= 0) {
      result.push(rawLine)
      continue
    }
    let line = ''
    let width = 0
    for (const char of rawLine) {
      const next = charWidth(char, fontSize) + letterSpacing
      if (line && width + next > maxWidth) {
        result.push(line)
        line = char
        width = next
      } else {
        line += char
        width += next
      }
    }
    if (line) result.push(line)
  }
  return result.length ? result : ['']
}

function roundRadius(element: DrawElement): number {
  const roundness = element.roundness
  const max = Math.min(element.width, element.height) / 2
  if (typeof roundness === 'number') {
    return roundness > 0 ? Math.min(24, max) : 0
  }
  if (roundness && typeof roundness === 'object') {
    return Math.min(24, max)
  }
  return 0
}

function dashArray(element: DrawElement): string {
  // 与画布渲染器的虚线间距保持一致。
  if (element.strokeStyle === 'dashed') return ' stroke-dasharray="8 8"'
  if (element.strokeStyle === 'dotted') return ' stroke-dasharray="3 6" stroke-linecap="round"'
  return ''
}

type ConnectorSide = 'left' | 'right' | 'top' | 'bottom'

function boundElement(
  element: DrawElement,
  key: 'startBinding' | 'endBinding',
  elements: DrawElement[],
): DrawElement | null {
  const binding = (element as Record<string, any>)[key]
  const id = typeof binding?.elementId === 'string' ? binding.elementId : ''
  if (!id) return null
  return elements.find((item) => item.id === id) ?? null
}

/** 连接点靠近绑定元素的哪条边，用于决定折线箭头的走向。 */
function nearestSide(target: DrawElement, point: [number, number]): ConnectorSide {
  const distances: Array<[ConnectorSide, number]> = [
    ['left', Math.abs(point[0] - target.x)],
    ['right', Math.abs(point[0] - (target.x + target.width))],
    ['top', Math.abs(point[1] - target.y)],
    ['bottom', Math.abs(point[1] - (target.y + target.height))],
  ]
  let best = distances[0]
  for (const item of distances) if (item[1] < best[1]) best = item
  return best[0]
}

function isHorizontalSide(side: ConnectorSide | null): boolean {
  return side === 'left' || side === 'right'
}

function isVerticalSide(side: ConnectorSide | null): boolean {
  return side === 'top' || side === 'bottom'
}

/** 去掉重复点与共线中间点，和画布的折线路径保持一致。 */
function cleanRoute(points: Array<[number, number]>): Array<[number, number]> {
  const result: Array<[number, number]> = []
  for (const point of points) {
    const last = result[result.length - 1]
    const previous = result.length > 1 ? result[result.length - 2] : undefined
    if (last && previous) {
      const sameY =
        Math.abs(previous[1] - last[1]) < 0.1 && Math.abs(last[1] - point[1]) < 0.1
      const sameX =
        Math.abs(previous[0] - last[0]) < 0.1 && Math.abs(last[0] - point[0]) < 0.1
      if (sameY || sameX) {
        result[result.length - 1] = point
        continue
      }
    }
    if (last && Math.abs(last[0] - point[0]) < 0.1 && Math.abs(last[1] - point[1]) < 0.1) {
      continue
    }
    result.push(point)
  }
  return result
}

/**
 * 折线箭头路由：两点折线按绑定元素所在边补出直角拐点。
 * 规则与 jvs-draw 的 getElbowPath 一致，避免预览把直角连线画成斜线。
 */
function elbowRoute(
  element: DrawElement,
  absolute: Array<[number, number]>,
  elements: DrawElement[],
): Array<[number, number]> {
  if (element.arrowType !== 'elbow' || absolute.length !== 2) return absolute
  const [start, end] = absolute
  const startTarget = boundElement(element, 'startBinding', elements)
  const endTarget = boundElement(element, 'endBinding', elements)
  const startSide = startTarget ? nearestSide(startTarget, start) : null
  const endSide = endTarget ? nearestSide(endTarget, end) : null
  let route: Array<[number, number]>
  if (isHorizontalSide(startSide) && isHorizontalSide(endSide)) {
    const x =
      startSide === endSide
        ? startSide === 'left'
          ? Math.min(start[0], end[0])
          : Math.max(start[0], end[0])
        : (start[0] + end[0]) / 2
    route = [start, [x, start[1]], [x, end[1]], end]
  } else if (isVerticalSide(startSide) && isVerticalSide(endSide)) {
    const y =
      startSide === endSide
        ? startSide === 'top'
          ? Math.min(start[1], end[1])
          : Math.max(start[1], end[1])
        : (start[1] + end[1]) / 2
    route = [start, [start[0], y], [end[0], y], end]
  } else if (isVerticalSide(startSide)) {
    route = [start, [start[0], end[1]], end]
  } else {
    // 起点是水平方向或未绑定时，与画布一致：先横后竖。
    route = [start, [end[0], start[1]], end]
  }
  return cleanRoute(route)
}

function linePath(points: Array<[number, number]>): string {
  return points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
}

/** 折线圆角路径，半径与画布的 pointsToRoundedPath(path, 8) 一致。 */
function roundedPath(points: Array<[number, number]>, radius = 8): string {
  if (points.length < 3) return linePath(points)
  const corner = (index: number) => {
    const previous = points[index - 1]
    const current = points[index]
    const next = points[index + 1]
    const inLength = Math.hypot(current[0] - previous[0], current[1] - previous[1])
    const outLength = Math.hypot(next[0] - current[0], next[1] - current[1])
    if (inLength < 0.01 || outLength < 0.01) return null
    const limit = Math.min(radius, inLength / 2, outLength / 2)
    return {
      from: [
        current[0] - ((current[0] - previous[0]) / inLength) * limit,
        current[1] - ((current[1] - previous[1]) / inLength) * limit,
      ] as [number, number],
      to: [
        current[0] + ((next[0] - current[0]) / outLength) * limit,
        current[1] + ((next[1] - current[1]) / outLength) * limit,
      ] as [number, number],
    }
  }
  let path = `M ${points[0][0]} ${points[0][1]}`
  for (let index = 1; index < points.length - 1; index += 1) {
    const arc = corner(index)
    if (!arc) {
      path += ` L ${points[index][0]} ${points[index][1]}`
      continue
    }
    path += ` L ${arc.from[0]} ${arc.from[1]}`
    path += ` Q ${points[index][0]} ${points[index][1]} ${arc.to[0]} ${arc.to[1]}`
  }
  const last = points[points.length - 1]
  return `${path} L ${last[0]} ${last[1]}`
}

function backPoint(
  point: [number, number],
  angle: number,
  distance: number,
): [number, number] {
  return [point[0] - distance * Math.cos(angle), point[1] - distance * Math.sin(angle)]
}

function polylineMarkup(
  points: Array<[number, number]>,
  attributes: string,
): string {
  return (
    `<path d="${points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'}${x},${y}`).join(' ')}" ` +
    `fill="none" ${attributes}/>`
  )
}

/**
 * 箭头头部按画布渲染器的类型与尺寸绘制。
 * SVG 导出的 marker 只有一种实心三角，和画布上的 V 形箭头 / 圆点差异明显。
 */
function arrowheadMarkup(
  type: unknown,
  point: [number, number],
  angle: number,
  element: DrawElement,
): string {
  const kind = typeof type === 'string' ? type : ''
  if (!kind || kind === 'none' || kind === 'line') return ''
  const stroke = attr(color(element.strokeColor, '#475569'))
  const width = Math.max(0.5, num(element.strokeWidth, 2))
  const lineStyle =
    `stroke="${stroke}" stroke-width="${width}" ` +
    `stroke-linejoin="round" stroke-linecap="round"`
  const filled = `fill="${stroke}" stroke="${stroke}" stroke-width="${width}"`
  const outline = `fill="#ffffff" stroke="${stroke}" stroke-width="${width}"`
  const half = Math.PI / 6
  const top = backPoint(point, angle + half, 15)
  const bottom = backPoint(point, angle - half, 15)
  switch (kind) {
    case 'arrow':
      return polylineMarkup([top, point, bottom], lineStyle)
    case 'half_arrow_top':
      return polylineMarkup([backPoint(point, angle - half, 15), point], lineStyle)
    case 'half_arrow_bottom':
      return polylineMarkup([backPoint(point, angle + half, 15), point], lineStyle)
    case 'triangle':
    case 'triangle_outline': {
      const left = backPoint(point, angle + half, 12)
      const right = backPoint(point, angle - half, 12)
      return (
        `<polygon points="${point[0]},${point[1]} ${left[0]},${left[1]} ${right[0]},${right[1]}" ` +
        `${kind === 'triangle' ? filled : outline}/>`
      )
    }
    case 'dot':
    case 'circle_outline': {
      const center = backPoint(point, angle, 5)
      return (
        `<circle cx="${center[0]}" cy="${center[1]}" r="5" ` +
        `${kind === 'dot' ? filled : outline}/>`
      )
    }
    case 'diamond':
    case 'diamond_outline': {
      const near = backPoint(point, angle, 8)
      const far = backPoint(point, angle, 16)
      const dx = Math.cos(angle + Math.PI / 2) * 6
      const dy = Math.sin(angle + Math.PI / 2) * 6
      const points = [
        point,
        [near[0] + dx, near[1] + dy],
        far,
        [near[0] - dx, near[1] - dy],
      ]
      return (
        `<polygon points="${points.map(([x, y]) => `${x},${y}`).join(' ')}" ` +
        `${kind === 'diamond' ? filled : outline}/>`
      )
    }
    case 'bar': {
      const dx = Math.cos(angle + Math.PI / 2) * 10
      const dy = Math.sin(angle + Math.PI / 2) * 10
      return polylineMarkup(
        [
          [point[0] + dx, point[1] + dy],
          [point[0] - dx, point[1] - dy],
        ],
        lineStyle,
      )
    }
    case 'crowfoot_one': {
      const neck = backPoint(point, angle, 15)
      const dx = Math.cos(angle + Math.PI / 2) * 10
      const dy = Math.sin(angle + Math.PI / 2) * 10
      return (
        polylineMarkup([top, point, bottom], lineStyle) +
        polylineMarkup(
          [
            [neck[0] + dx, neck[1] + dy],
            [neck[0] - dx, neck[1] - dy],
          ],
          lineStyle,
        )
      )
    }
    default:
      return ''
  }
}

function gradientFill(
  context: RenderContext,
  element: DrawElement,
  gradient: Record<string, any>,
): string {
  const key = JSON.stringify(gradient)
  const existing = context.gradients.get(key)
  if (existing) return `url(#${existing})`
  const id = `${context.prefix}-grad-${context.gradients.size}`
  context.gradients.set(key, id)
  const stops = (Array.isArray(gradient.stops) ? gradient.stops : [])
    .map((stop: any) => {
      const offset = Math.min(1, Math.max(0, num(stop?.offset)))
      const stopColor = color(stop?.color, '#cbd5e1')
      const stopOpacity = stop?.opacity === undefined ? '' : ` stop-opacity="${opacity(stop.opacity * 100)}"`
      return `<stop offset="${offset}" stop-color="${attr(stopColor)}"${stopOpacity}/>`
    })
    .join('')
  if (gradient.type === 'radial') {
    context.defs.push(`<radialGradient id="${id}">${stops}</radialGradient>`)
  } else {
    const direction = gradient.direction
    let x1 = 0
    let y1 = 0
    let x2 = 1
    let y2 = 0
    if (direction === 'vertical') {
      y2 = 1
    } else if (direction === 'diagonal') {
      y2 = 1
    } else if (typeof direction === 'number') {
      const radians = (direction * Math.PI) / 180
      x2 = Math.cos(radians)
      y2 = Math.sin(radians)
    }
    context.defs.push(
      `<linearGradient id="${id}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">${stops}</linearGradient>`,
    )
  }
  return `url(#${id})`
}

function fillOf(context: RenderContext, element: DrawElement): string {
  const background = color(element.backgroundColor)
  if (element.fillGradient && typeof element.fillGradient === 'object') {
    return gradientFill(context, element, element.fillGradient)
  }
  if (element.fillStyle && element.fillStyle !== 'solid' && !isTransparent(background)) {
    const key = `${element.fillStyle}:${background}:${color(element.strokeColor)}`
    const existing = context.patterns.get(key)
    if (existing) return `url(#${existing})`
    const id = `${context.prefix}-pattern-${context.patterns.size}`
    context.patterns.set(key, id)
    const stroke = attr(color(element.strokeColor, '#94a3b8'))
    let lines = '<path d="M0,8 L8,0" stroke="' + stroke + '" stroke-width="1"/>'
    if (element.fillStyle === 'cross-hatch') {
      lines += '<path d="M0,0 L8,8" stroke="' + stroke + '" stroke-width="1"/>'
    } else if (element.fillStyle === 'zigzag') {
      lines = '<path d="M0,6 L2,3 L4,6 L6,3 L8,6" fill="none" stroke="' + stroke + '" stroke-width="1"/>'
    }
    context.defs.push(
      `<pattern id="${id}" width="8" height="8" patternUnits="userSpaceOnUse">` +
        `<rect width="8" height="8" fill="${attr(background)}"/>${lines}</pattern>`,
    )
    return `url(#${id})`
  }
  return isTransparent(background) ? 'none' : attr(background)
}

function groupAttributes(element: DrawElement, center?: { x: number; y: number }): string {
  const parts: string[] = []
  const alpha = opacity(element.opacity)
  if (alpha < 1) parts.push(`opacity="${alpha}"`)
  const angle = num(element.angle)
  if (angle) {
    const cx = center?.x ?? element.x + element.width / 2
    const cy = center?.y ?? element.y + element.height / 2
    parts.push(`transform="rotate(${angle} ${cx} ${cy})"`)
  }
  return parts.length ? ` ${parts.join(' ')}` : ''
}

function renderText(element: DrawElement, context: RenderContext): string {
  const text = typeof element.text === 'string' ? element.text : ''
  if (!text) return ''
  const container = containerOf(element, context.elements)
  const box = textBox(element, context.elements)
  const fontSize = Math.max(1, num(element.fontSize, 20))
  const lineHeight = fontSize * Math.max(0.8, num(element.lineHeight, 1.25))
  const letterSpacing = num(element.letterSpacing)
  const paddingX = container ? 8 : 2
  const paddingY = container ? 4 : 0
  const maxWidth = Math.max(1, box.maxX - box.minX - paddingX * 2)
  const lines = wrapText(text, maxWidth, fontSize, letterSpacing)
  const totalHeight = lines.length * lineHeight
  const align =
    element.textAlign === 'left' || element.textAlign === 'right'
      ? element.textAlign
      : container?.textAlign === 'left'
        ? 'left'
        : 'center'
  const verticalAlign =
    element.verticalAlign === 'top' || element.verticalAlign === 'bottom'
      ? element.verticalAlign
      : container?.verticalAlign === 'top'
        ? 'top'
        : 'middle'
  let top = box.minY + paddingY
  if (verticalAlign === 'middle') {
    top = box.minY + (box.maxY - box.minY - totalHeight) / 2
  } else if (verticalAlign === 'bottom') {
    top = box.maxY - paddingY - totalHeight
  }
  const centerX = (box.minX + box.maxX) / 2
  const x =
    align === 'left'
      ? box.minX + paddingX
      : align === 'right'
        ? box.maxX - paddingX
        : centerX
  const anchor = align === 'left' ? 'start' : align === 'right' ? 'end' : 'middle'

  const fontColor = attr(color(element.fontColor, '#1e293b'))
  const family =
    element.fontFamily === undefined || element.fontFamily === null || element.fontFamily === ''
      ? context.defaultFontFamily
      : element.fontFamily
  const fontFamily =
    family === 'monospace' || family === 2
      ? MONO_FAMILY
      : isHandFont(family)
        ? HAND_FONT_STACK
        : FONT_FAMILY
  const weight = element.isBold
    ? '600'
    : /^(bold|semi.?bold|600|700|800|900)$/i.test(String(element.fontWeight || ''))
      ? '600'
      : '400'
  const style = element.isItalic ? ' font-style="italic"' : ''
  const decoration =
    element.isUnderline || element.isStrikethrough
      ? ` text-decoration="${[
          element.isUnderline ? 'underline' : '',
          element.isStrikethrough ? 'line-through' : '',
        ]
          .filter(Boolean)
          .join(' ')}"`
      : ''

  const background = color(element.fontBgColor)
  let back = ''
  if (!isTransparent(background)) {
    const lineWidths = lines.map((line) => measure(line, fontSize, letterSpacing))
    const width = Math.max(0, ...lineWidths) + 8
    const left =
      align === 'left'
        ? x - 4
        : align === 'right'
          ? x - width + 4
          : centerX - width / 2
    back = `<rect x="${left}" y="${top}" width="${width}" height="${totalHeight}" rx="4" fill="${attr(background)}"/>`
  }

  const tspans = lines
    .map(
      (line, index) =>
        `<tspan x="${x}" y="${top + lineHeight * (index + 0.78)}">${esc(line)}</tspan>`,
    )
    .join('')
  const textElement =
    `<text xml:space="preserve" text-anchor="${anchor}" font-family="${attr(fontFamily)}" ` +
    `font-size="${fontSize}" font-weight="${weight}"${style}${decoration} ` +
    `fill="${fontColor}"${letterSpacing ? ` letter-spacing="${letterSpacing}"` : ''}>${tspans}</text>`
  const center = {
    x: container ? container.x + container.width / 2 : element.x + element.width / 2,
    y: container ? container.y + container.height / 2 : element.y + element.height / 2,
  }
  const angle = container ? num(container.angle) : num(element.angle)
  const transform = angle ? ` transform="rotate(${angle} ${center.x} ${center.y})"` : ''
  const alpha = opacity(element.opacity)
  const alphaAttr = alpha < 1 ? ` opacity="${alpha}"` : ''
  return `<g${alphaAttr}${transform}>${back}${textElement}</g>`
}

function shapePath(element: DrawElement): string {
  const x = element.x
  const y = element.y
  const w = element.width
  const h = element.height
  const type = element.type
  if (type === 'ellipse' || type === 'circle') {
    return `<ellipse cx="${x + w / 2}" cy="${y + h / 2}" rx="${w / 2}" ry="${h / 2}"`
  }
  if (type === 'diamond') {
    const points = `${x + w / 2},${y} ${x + w},${y + h / 2} ${x + w / 2},${y + h} ${x},${y + h / 2}`
    return `<polygon points="${points}"`
  }
  if (type === 'triangle') {
    return `<polygon points="${x + w / 2},${y} ${x + w},${y + h} ${x},${y + h}"`
  }
  if (type === 'parallelogram') {
    const offset = Math.min(w * 0.22, 40)
    return `<polygon points="${x + offset},${y} ${x + w},${y} ${x + w - offset},${y + h} ${x},${y + h}"`
  }
  if (type === 'trapezoid') {
    const offset = Math.min(w * 0.18, 36)
    return `<polygon points="${x + offset},${y} ${x + w - offset},${y} ${x + w},${y + h} ${x},${y + h}"`
  }
  if (type === 'hexagon' || type === 'preparation') {
    const offset = Math.min(w * 0.18, 34)
    const points = `${x + offset},${y} ${x + w - offset},${y} ${x + w},${y + h / 2} ${x + w - offset},${y + h} ${x + offset},${y + h} ${x},${y + h / 2}`
    return `<polygon points="${points}"`
  }
  if (type === 'pentagon') {
    const cx = x + w / 2
    const cy = y + h / 2
    const points = Array.from({ length: 5 }, (_, index) => {
      const angle = -Math.PI / 2 + (index * Math.PI * 2) / 5
      return `${cx + (w / 2) * Math.cos(angle)},${cy + (h / 2) * Math.sin(angle)}`
    }).join(' ')
    return `<polygon points="${points}"`
  }
  if (type === 'star') {
    const cx = x + w / 2
    const cy = y + h / 2
    const points = Array.from({ length: 10 }, (_, index) => {
      const radius = index % 2 === 0 ? 1 : 0.45
      const angle = -Math.PI / 2 + (index * Math.PI) / 5
      return `${cx + (w / 2) * radius * Math.cos(angle)},${cy + (h / 2) * radius * Math.sin(angle)}`
    }).join(' ')
    return `<polygon points="${points}"`
  }
  if (type === 'cloud') {
    const path =
      `M ${x + w * 0.25} ${y + h * 0.9} ` +
      `C ${x + w * 0.04} ${y + h * 0.9}, ${x - w * 0.01} ${y + h * 0.63}, ${x + w * 0.14} ${y + h * 0.53} ` +
      `C ${x + w * 0.08} ${y + h * 0.28}, ${x + w * 0.33} ${y + h * 0.16}, ${x + w * 0.44} ${y + h * 0.34} ` +
      `C ${x + w * 0.55} ${y + h * 0.08}, ${x + w * 0.86} ${y + h * 0.13}, ${x + w * 0.86} ${y + h * 0.4} ` +
      `C ${x + w * 1.02} ${y + h * 0.45}, ${x + w * 1.02} ${y + h * 0.76}, ${x + w * 0.86} ${y + h * 0.81} ` +
      `C ${x + w * 0.8} ${y + h * 0.97}, ${x + w * 0.4} ${y + h * 0.99}, ${x + w * 0.25} ${y + h * 0.9} Z`
    return `<path d="${path}"`
  }
  if (type === 'cylinder') {
    const ry = Math.min(h * 0.16, 18)
    const path =
      `M ${x} ${y + ry} A ${w / 2} ${ry} 0 0 1 ${x + w} ${y + ry} ` +
      `L ${x + w} ${y + h - ry} A ${w / 2} ${ry} 0 0 1 ${x} ${y + h - ry} Z`
    return `<path d="${path}"`
  }
  if (type === 'note' || type === 'card') {
    const fold = Math.min(w, h) * 0.22
    const path =
      `M ${x} ${y} L ${x + w - fold} ${y} L ${x + w} ${y + fold} ` +
      `L ${x + w} ${y + h} L ${x} ${y + h} Z`
    return `<path d="${path}"`
  }
  if (type === 'manualInput') {
    return `<polygon points="${x},${y + h * 0.18} ${x + w},${y} ${x + w},${y + h} ${x},${y + h}"`
  }
  const radius = roundRadius(element)
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}"`
}

function renderShape(element: DrawElement, context: RenderContext): string {
  const fill = fillOf(context, element)
  const stroke = color(element.strokeColor)
  const strokeWidth = Math.max(0, num(element.strokeWidth, 2))
  const strokeAttr = isTransparent(stroke) || strokeWidth === 0 ? 'none' : attr(stroke)
  const strokeOpacity = opacity(element.strokeOpacity)
  const shape = shapePath(element)
  const isPathLike = /^(ellipse|polygon|path|rect)$/.test(shape.replace(/^<(\w+).*/, '$1'))
  const close = isPathLike ? shape : `${shape}`
  if (element.type === 'frame') {
    return `<g${groupAttributes(element)}><rect x="${element.x}" y="${element.y}" width="${element.width}" height="${element.height}" rx="8" fill="none" stroke="${strokeAttr}" stroke-width="${strokeWidth}" stroke-dasharray="6 5"/></g>`
  }
  return (
    `<g${groupAttributes(element)}>` +
    `<${close.slice(1)} fill="${fill}" stroke="${strokeAttr}" stroke-width="${strokeWidth}" ` +
    `stroke-opacity="${strokeOpacity}" stroke-linejoin="round"${dashArray(element)}/>` +
    `</g>`
  )
}

function renderConnector(element: DrawElement, context: RenderContext): string {
  const points = pointsOf(element)
  if (points.length < 2) return ''
  const absolute = points.map(
    ([x, y]) => [element.x + x, element.y + y] as [number, number],
  )
  const isElbow = element.arrowType === 'elbow'
  const route = isElbow ? elbowRoute(element, absolute, context.elements) : absolute
  if (route.length < 2) return ''
  const path = isElbow && route.length > 2 ? roundedPath(route, 8) : linePath(route)
  const stroke = color(element.strokeColor, '#475569')
  const strokeWidth = Math.max(0.5, num(element.strokeWidth, 2))
  const startAngle =
    Math.atan2(route[0][1] - route[1][1], route[0][0] - route[1][0])
  const last = route[route.length - 1]
  const previous = route[route.length - 2]
  const endAngle = Math.atan2(last[1] - previous[1], last[0] - previous[0])
  const heads =
    arrowheadMarkup(element.startArrowhead, route[0], startAngle, element) +
    arrowheadMarkup(element.endArrowhead, last, endAngle, element)
  return (
    `<g${groupAttributes(element)}>` +
    `<path d="${path}" fill="none" stroke="${attr(stroke)}" stroke-width="${strokeWidth}" ` +
    `stroke-opacity="${opacity(element.strokeOpacity)}" stroke-linecap="round" stroke-linejoin="round"` +
    `${dashArray(element)}/>${heads}</g>`
  )
}

function renderImage(element: DrawElement, context: RenderContext): string {
  const fileId = typeof element.fileId === 'string' ? element.fileId : ''
  const href =
    (typeof element.url === 'string' && element.url) ||
    (fileId ? context.files[fileId] : '') ||
    (typeof element.dataURL === 'string' ? element.dataURL : '')
  const url = typeof href === 'string' && href ? attr(href) : ''
  if (!url) {
    return (
      `<g${groupAttributes(element)}>` +
      `<rect x="${element.x}" y="${element.y}" width="${element.width}" height="${element.height}" ` +
      `rx="8" fill="#f8fafc" stroke="#cbd5e1" stroke-dasharray="5 4"/>` +
      `<text x="${element.x + element.width / 2}" y="${element.y + element.height / 2}" ` +
      `text-anchor="middle" font-family="${attr(FONT_FAMILY)}" font-size="13" fill="#94a3b8">图片</text>` +
      `</g>`
    )
  }
  return (
    `<g${groupAttributes(element)}>` +
    `<image x="${element.x}" y="${element.y}" width="${element.width}" height="${element.height}" ` +
    `href="${url}" preserveAspectRatio="none"/></g>`
  )
}

function renderElement(element: DrawElement, context: RenderContext): string {
  if (element.isDeleted) return ''
  if (element.type === 'text') return renderText(element, context)
  if (CONNECTOR_TYPES.has(element.type)) return renderConnector(element, context)
  if (element.type === 'image') return renderImage(element, context)
  return renderShape(element, context)
}

/** 生成完整、可独立打开的 SVG 文本；空白画布也返回带底色的占位图。 */
export function drawDocToSvg(doc: JvsDrawDoc): string {
  svgSeq += 1
  const prefix = `kiwi-draw-${svgSeq}`
  const context: RenderContext = {
    elements: doc.elements,
    files: doc.files || {},
    defs: [],
    gradients: new Map(),
    patterns: new Map(),
    prefix,
    defaultFontFamily: (doc.appState as Record<string, unknown> | undefined)
      ?.currentItemFontFamily,
  }
  const visible = doc.elements.filter((element) => !element.isDeleted)
  const boxes = visible.map((element) => rotatedBounds(element))
  let minX = 0
  let minY = 0
  let maxX = MIN_WIDTH
  let maxY = MIN_HEIGHT
  if (boxes.length) {
    minX = Math.min(...boxes.map((box) => box.minX)) - PADDING
    minY = Math.min(...boxes.map((box) => box.minY)) - PADDING
    maxX = Math.max(...boxes.map((box) => box.maxX)) + PADDING
    maxY = Math.max(...boxes.map((box) => box.maxY)) + PADDING
    if (maxX - minX < MIN_WIDTH) maxX = minX + MIN_WIDTH
    if (maxY - minY < MIN_HEIGHT) maxY = minY + MIN_HEIGHT
  }
  const width = maxX - minX
  const height = maxY - minY
  const background = color(drawDocBackground(doc), '#ffffff')
  const backgroundRect = isTransparent(background)
    ? ''
    : `<rect x="${minX}" y="${minY}" width="${width}" height="${height}" fill="${attr(background)}"/>`
  const body = visible.map((element) => renderElement(element, context)).join('')
  const defs = context.defs.length ? `<defs>${context.defs.join('')}</defs>` : ''
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${minX} ${minY} ${width} ${height}" ` +
    `width="${width}" height="${height}" role="img" aria-label="画布">` +
    `${defs}${backgroundRect}${body}</svg>`
  )
}

/**
 * 导出用 SVG：文档使用手绘主题时把内置字体数据一并嵌入。
 * PNG / PDF 通过 <img> 栅格化、下载后的 SVG 脱离应用打开时，
 * 都拿不到页面里的 @font-face，必须随文件携带字体。
 */
export async function drawDocToSvgForExport(doc: JvsDrawDoc): Promise<string> {
  const svg = drawDocToSvg(doc)
  if (!drawDocUsesHandFont(doc)) return svg
  return embedHandFontInSvg(svg)
}
