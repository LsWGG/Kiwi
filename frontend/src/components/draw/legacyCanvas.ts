/**
 * 旧版 canvas_doc 兼容转换。
 *
 * 旧画布把节点 / 连线保存在 note.props_json.canvas_doc；新版画布改用
 * jvs-draw 的 draw_doc。这里把旧结构尽量无损地转成 draw 元素，保证升级后
 * 已有笔记仍可打开、编辑，并在下一次保存时自然写回 draw_doc。
 */
import type { DrawElement, JvsDrawDoc } from './types'

interface LegacyNode {
  id?: unknown
  shape?: unknown
  x?: unknown
  y?: unknown
  w?: unknown
  h?: unknown
  text?: unknown
  variant?: unknown
  container?: unknown
  tone?: unknown
  fontSize?: unknown
  bold?: unknown
  align?: unknown
}

interface LegacyAnchor {
  nodeId?: unknown
  side?: unknown
  x?: unknown
  y?: unknown
}

interface LegacyEdge {
  id?: unknown
  from?: LegacyAnchor
  to?: LegacyAnchor
  curve?: unknown
  arrow?: unknown
  dashed?: unknown
  label?: unknown
  tone?: unknown
}

interface LegacyDoc {
  theme?: unknown
  grid?: unknown
  nodes?: unknown
  edges?: unknown
}

interface ToneStyle {
  fill: string
  stroke: string
  text: string
}

interface ThemeStyle {
  bg: string
  edge: string
  tones: Record<string, ToneStyle>
}

const THEME_STYLES: Record<string, ThemeStyle> = {
  engineering: {
    bg: '#f8fafc',
    edge: '#64748b',
    tones: {
      neutral: { fill: '#ffffff', stroke: '#cbd5e1', text: '#1e293b' },
      accent: { fill: '#e0f2fe', stroke: '#38bdf8', text: '#075985' },
      green: { fill: '#dcfce7', stroke: '#4ade80', text: '#166534' },
      amber: { fill: '#fef3c7', stroke: '#fbbf24', text: '#92400e' },
      rose: { fill: '#ffe4e6', stroke: '#fb7185', text: '#9f1239' },
      violet: { fill: '#ede9fe', stroke: '#a78bfa', text: '#5b21b6' },
    },
  },
  blueprint: {
    bg: '#0b1f3a',
    edge: '#60a5fa',
    tones: {
      neutral: { fill: '#102a4c', stroke: '#3b82f6', text: '#dbeafe' },
      accent: { fill: '#0c4a6e', stroke: '#38bdf8', text: '#e0f2fe' },
      green: { fill: '#064e3b', stroke: '#34d399', text: '#d1fae5' },
      amber: { fill: '#451a03', stroke: '#fbbf24', text: '#fef3c7' },
      rose: { fill: '#4c0519', stroke: '#fb7185', text: '#ffe4e6' },
      violet: { fill: '#2e1065', stroke: '#a78bfa', text: '#ede9fe' },
    },
  },
  paper: {
    bg: '#fbf7ef',
    edge: '#78716c',
    tones: {
      neutral: { fill: '#fffdf7', stroke: '#d6d3d1', text: '#44403c' },
      accent: { fill: '#ffedd5', stroke: '#fb923c', text: '#9a3412' },
      green: { fill: '#ecfccb', stroke: '#a3e635', text: '#3f6212' },
      amber: { fill: '#fef9c3', stroke: '#facc15', text: '#854d0e' },
      rose: { fill: '#ffe4e6', stroke: '#fb7185', text: '#9f1239' },
      violet: { fill: '#f3e8ff', stroke: '#c084fc', text: '#6b21a8' },
    },
  },
  midnight: {
    bg: '#0f172a',
    edge: '#94a3b8',
    tones: {
      neutral: { fill: '#1e293b', stroke: '#475569', text: '#e2e8f0' },
      accent: { fill: '#164e63', stroke: '#22d3ee', text: '#cffafe' },
      green: { fill: '#064e3b', stroke: '#34d399', text: '#d1fae5' },
      amber: { fill: '#451a03', stroke: '#fbbf24', text: '#fef3c7' },
      rose: { fill: '#4c0519', stroke: '#fb7185', text: '#ffe4e6' },
      violet: { fill: '#2e1065', stroke: '#c4b5fd', text: '#ede9fe' },
    },
  },
}

const DEFAULT_THEME = THEME_STYLES.engineering

function isRecord(value: unknown): value is Record<string, any> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function num(value: unknown, fallback = 0): number {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : fallback
}

function textOf(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function themeOf(id: unknown): ThemeStyle {
  return (typeof id === 'string' && THEME_STYLES[id]) || DEFAULT_THEME
}

function toneOf(theme: ThemeStyle, tone: unknown): ToneStyle {
  const key = typeof tone === 'string' ? tone : 'neutral'
  return theme.tones[key] ?? theme.tones.neutral
}

function baseElement(
  id: string,
  type: string,
  x: number,
  y: number,
  width: number,
  height: number,
  extra: Record<string, unknown>,
): DrawElement {
  return {
    id,
    type,
    x,
    y,
    width,
    height,
    angle: 0,
    strokeColor: '#94a3b8',
    backgroundColor: 'transparent',
    fillStyle: 'solid',
    strokeWidth: 2,
    strokeStyle: 'solid',
    roughness: 1,
    opacity: 100,
    strokeOpacity: 100,
    roundness: null,
    fontSize: 15,
    fontFamily: 'sans-serif',
    fontColor: '#1e293b',
    fontBgColor: 'transparent',
    textAlign: 'center',
    verticalAlign: 'middle',
    isDeleted: false,
    groupIds: [],
    boundElements: [],
    lineHeight: 1.25,
    letterSpacing: 0,
    ...extra,
  }
}

function textElement(
  id: string,
  text: string,
  x: number,
  y: number,
  width: number,
  height: number,
  extra: Record<string, unknown>,
): DrawElement {
  return baseElement(id, 'text', x, y, width, height, {
    text,
    originalText: text,
    strokeColor: 'transparent',
    backgroundColor: 'transparent',
    strokeWidth: 1,
    roundness: null,
    autoResize: false,
    ...extra,
  })
}

function shapeOf(node: LegacyNode): { type: string; roundness: unknown } {
  const shape = textOf(node.shape) || 'rect'
  if (node.container === true) return { type: 'rectangle', roundness: null }
  switch (shape) {
    case 'round':
    case 'sticky':
      return { type: 'rectangle', roundness: { type: 3 } }
    case 'ellipse':
      return { type: 'ellipse', roundness: null }
    case 'diamond':
      return { type: 'diamond', roundness: null }
    case 'network':
      if (node.variant === 'database') return { type: 'cylinder', roundness: null }
      if (node.variant === 'cloud') return { type: 'ellipse', roundness: null }
      return { type: 'rectangle', roundness: { type: 3 } }
    case 'uml':
    case 'table':
      return { type: 'rectangle', roundness: null }
    default:
      return { type: 'rectangle', roundness: { type: 3 } }
  }
}

function anchorPoint(
  node: LegacyNode | undefined,
  side: unknown,
  fallbackX: number,
  fallbackY: number,
): { x: number; y: number } {
  if (!node) return { x: fallbackX, y: fallbackY }
  const x = num(node.x)
  const y = num(node.y)
  const w = num(node.w)
  const h = num(node.h)
  switch (side) {
    case 'top':
      return { x: x + w / 2, y }
    case 'right':
      return { x: x + w, y: y + h / 2 }
    case 'bottom':
      return { x: x + w / 2, y: y + h }
    case 'left':
      return { x, y: y + h / 2 }
    default:
      return { x: x + w / 2, y: y + h / 2 }
  }
}

export function legacyCanvasToDraw(raw: unknown): JvsDrawDoc | null {
  if (!isRecord(raw) || !Array.isArray(raw.nodes)) return null
  const doc = raw as LegacyDoc
  const rawNodes: unknown[] = raw.nodes
  const theme = themeOf(doc.theme)
  const elements: DrawElement[] = []
  const nodes = new Map<string, LegacyNode>()

  for (const item of rawNodes) {
    if (!isRecord(item)) continue
    const node = item as LegacyNode
    const id = textOf(node.id)
    if (!id) continue
    nodes.set(id, node)
    const x = num(node.x)
    const y = num(node.y)
    const w = Math.max(0, num(node.w))
    const h = Math.max(0, num(node.h))
    const text = textOf(node.text)
    const align = node.align === 'left' ? 'left' : 'center'
    const fontSize = Math.max(8, num(node.fontSize, 15))
    const tone = toneOf(theme, node.shape === 'sticky' && !node.tone ? 'amber' : node.tone)
    const bold = node.bold === true

    if (textOf(node.shape) === 'text') {
      const lines = Math.max(1, text.split('\n').length)
      elements.push(
        textElement(id, text, x, y, w || 200, Math.max(20, lines * fontSize * 1.25), {
          fontSize,
          fontColor: tone.text,
          textAlign: align,
          verticalAlign: 'top',
          fontWeight: bold ? 'bold' : 'normal',
          isBold: bold,
        }),
      )
      continue
    }

    const shape = shapeOf(node)
    const isContainer = node.container === true
    const shapeId = id
    const textId = `${id}-text`
    const hasText = !!text.trim()
    elements.push(
      baseElement(shapeId, shape.type, x, y, w, h, {
        roundness: shape.roundness,
        strokeColor: isContainer ? theme.edge : tone.stroke,
        backgroundColor: isContainer ? 'transparent' : tone.fill,
        strokeStyle: isContainer ? 'dashed' : 'solid',
        boundElements: hasText ? [{ type: 'text', id: textId }] : [],
      }),
    )
    if (!hasText) continue
    const lines = Math.max(1, text.split('\n').length)
    const textHeight = Math.max(fontSize * 1.25, lines * fontSize * 1.25)
    const top = isContainer ? y + 6 : y + Math.max(4, (h - textHeight) / 2)
    elements.push(
      textElement(textId, text, x + 8, top, Math.max(20, w - 16), textHeight, {
        containerId: shapeId,
        fontSize,
        fontColor: tone.text,
        textAlign: isContainer ? 'left' : align,
        verticalAlign: isContainer ? 'top' : 'middle',
        fontWeight: bold ? 'bold' : 'normal',
        isBold: bold,
      }),
    )
  }

  if (Array.isArray(doc.edges)) {
    for (const item of doc.edges) {
      if (!isRecord(item)) continue
      const edge = item as LegacyEdge
      const id = textOf(edge.id) || `legacy-edge-${elements.length}`
      const from = isRecord(edge.from) ? (edge.from as LegacyAnchor) : {}
      const to = isRecord(edge.to) ? (edge.to as LegacyAnchor) : {}
      const fromId = textOf(from.nodeId)
      const toId = textOf(to.nodeId)
      const start = anchorPoint(nodes.get(fromId), from.side, num(from.x), num(from.y))
      const end = anchorPoint(nodes.get(toId), to.side, num(to.x), num(to.y))
      const dx = end.x - start.x
      const dy = end.y - start.y
      const label = textOf(edge.label).trim()
      const labelId = `${id}-label`
      const curve = textOf(edge.curve)
      const arrow = textOf(edge.arrow) || 'end'
      const tone = toneOf(theme, edge.tone)
      elements.push(
        baseElement(id, 'arrow', start.x, start.y, Math.abs(dx), Math.abs(dy), {
          points: [
            [0, 0],
            [dx, dy],
          ],
          startBinding: fromId ? { elementId: fromId, focus: 0, gap: 4, isBorder: false } : null,
          endBinding: toId ? { elementId: toId, focus: 0, gap: 4, isBorder: false } : null,
          startArrowhead: arrow === 'both' ? 'arrow' : null,
          endArrowhead: arrow === 'none' ? null : 'arrow',
          arrowType: curve === 'orthogonal' ? 'elbow' : curve === 'bezier' ? 'curve' : 'sharp',
          strokeColor: tone.stroke,
          strokeStyle: edge.dashed === true ? 'dashed' : 'solid',
          roundness: null,
          boundElements: label ? [{ type: 'text', id: labelId }] : [],
        }),
      )
      if (label) {
        elements.push(
          textElement(
            labelId,
            label,
            (start.x + end.x) / 2 - 40,
            (start.y + end.y) / 2 - 10,
            80,
            20,
            {
              containerId: id,
              fontSize: 12,
              fontColor: tone.text,
              textAlign: 'center',
              verticalAlign: 'middle',
            },
          ),
        )
      }
    }
  }

  return {
    type: 'jvs-draw',
    version: 1,
    elements,
    appState: {
      viewBackgroundColor: theme.bg,
      ...(doc.grid === true ? { gridType: 'dot' as const } : {}),
    },
    files: {},
    updatedAt: 0,
  }
}
