/**
 * 画布笔记数据模型。
 * 文档整体保存在 note.props_json.canvas_doc，节点 / 连线均为纯数据，便于撤销与持久化。
 */

export type CanvasShape =
  | 'rect'
  | 'round'
  | 'ellipse'
  | 'diamond'
  | 'text'
  | 'sticky'
  | 'uml'
  | 'table'
  | 'network'
export type CanvasTool =
  | 'select'
  | 'hand'
  | 'rect'
  | 'ellipse'
  | 'diamond'
  | 'text'
  | 'sticky'
  | 'uml'
  | 'table'
  | 'arrow'
export type CanvasNetworkKind =
  | 'cloud'
  | 'server'
  | 'database'
  | 'router'
  | 'firewall'
  | 'client'
  | 'switch'
  | 'storage'
export type CanvasTone = 'neutral' | 'accent' | 'green' | 'amber' | 'rose' | 'violet'
export type CanvasSide = 'top' | 'right' | 'bottom' | 'left'
export type CanvasAnchorSide = CanvasSide | 'auto'
export type EdgeCurve = 'straight' | 'orthogonal' | 'bezier'
export type EdgeArrow = 'end' | 'both' | 'none'
export type CanvasThemeId = 'engineering' | 'blueprint' | 'paper' | 'midnight'

export interface CanvasNode {
  id: string
  shape: CanvasShape
  x: number
  y: number
  w: number
  h: number
  text: string
  /** 网络图元的具体类型（server / database / firewall…） */
  variant?: CanvasNetworkKind
  /** 容器节点（分区 / 泳道）：填充透明，让连线和标签透出 */
  container?: boolean
  tone?: CanvasTone
  fontSize?: number
  bold?: boolean
  align?: 'left' | 'center'
}

export interface CanvasAnchor {
  nodeId: string | null
  side: CanvasAnchorSide
  /** nodeId 为空时作为自由端点使用 */
  x: number
  y: number
}

export interface CanvasEdge {
  id: string
  from: CanvasAnchor
  to: CanvasAnchor
  curve: EdgeCurve
  arrow: EdgeArrow
  dashed?: boolean
  label?: string
  tone?: CanvasTone
}

export interface CanvasViewport {
  x: number
  y: number
  zoom: number
}

export interface CanvasDoc {
  version: 1
  theme: CanvasThemeId
  grid: boolean
  snap: boolean
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  viewport: CanvasViewport
}

export const THEME_IDS: CanvasThemeId[] = ['engineering', 'blueprint', 'paper', 'midnight']
export const TONES: CanvasTone[] = ['neutral', 'accent', 'green', 'amber', 'rose', 'violet']
export const NETWORK_KINDS: CanvasNetworkKind[] = [
  'cloud',
  'server',
  'database',
  'router',
  'firewall',
  'client',
  'switch',
  'storage',
]

export const NODE_SIZES: Record<CanvasShape, { w: number; h: number }> = {
  rect: { w: 184, h: 72 },
  round: { w: 184, h: 64 },
  ellipse: { w: 184, h: 92 },
  diamond: { w: 196, h: 112 },
  text: { w: 200, h: 44 },
  sticky: { w: 184, h: 150 },
  uml: { w: 258, h: 176 },
  table: { w: 272, h: 180 },
  network: { w: 172, h: 112 },
}

export const DEFAULT_FONT_SIZE = 15
export const GRID_SIZE = 16

let idSeq = 0

export function newId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.()
  if (uuid) return `${prefix}-${uuid.slice(0, 8)}`
  idSeq += 1
  return `${prefix}-${Date.now().toString(36)}-${idSeq}`
}

export function makeNode(
  shape: CanvasShape,
  x: number,
  y: number,
  text = '',
  patch: Partial<CanvasNode> = {},
): CanvasNode {
  const size = NODE_SIZES[shape]
  return {
    id: newId('n'),
    shape,
    x,
    y,
    w: size.w,
    h: size.h,
    text,
    ...patch,
  }
}

export function makeEdge(
  from: Pick<CanvasAnchor, 'nodeId' | 'side'>,
  to: Pick<CanvasAnchor, 'nodeId' | 'side'>,
  patch: Partial<CanvasEdge> = {},
): CanvasEdge {
  return {
    id: newId('e'),
    from: { nodeId: from.nodeId, side: from.side, x: 0, y: 0 },
    to: { nodeId: to.nodeId, side: to.side, x: 0, y: 0 },
    curve: 'orthogonal',
    arrow: 'end',
    ...patch,
  }
}

export function emptyDoc(): CanvasDoc {
  return {
    version: 1,
    theme: 'engineering',
    grid: true,
    snap: false,
    nodes: [],
    edges: [],
    viewport: { x: 96, y: 80, zoom: 1 },
  }
}

const SHAPES: CanvasShape[] = [
  'rect',
  'round',
  'ellipse',
  'diamond',
  'text',
  'sticky',
  'uml',
  'table',
  'network',
]
const CURVES: EdgeCurve[] = ['straight', 'orthogonal', 'bezier']
const ARROWS: EdgeArrow[] = ['end', 'both', 'none']
const SIDES: CanvasAnchor['side'][] = ['auto', 'top', 'right', 'bottom', 'left']

function num(value: unknown, fallback: number): number {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : fallback
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/**
 * 容错读取持久化文档：旧数据 / 手工修改缺字段时回退到默认值，
 * 避免一次坏数据让整张画布打不开。
 */
export function normalizeDoc(raw: unknown): CanvasDoc {
  const base = emptyDoc()
  if (!raw || typeof raw !== 'object') return base
  const data = raw as Record<string, any>
  const theme = THEME_IDS.includes(data.theme) ? (data.theme as CanvasThemeId) : base.theme
  const nodes: CanvasNode[] = Array.isArray(data.nodes)
    ? data.nodes
        .filter((n: any) => n && typeof n === 'object')
        .map((n: any) => {
          const shape: CanvasShape = SHAPES.includes(n.shape) ? n.shape : 'rect'
          const size = NODE_SIZES[shape]
          return {
            id: str(n.id) || newId('n'),
            shape,
            x: num(n.x, 0),
            y: num(n.y, 0),
            w: Math.max(24, num(n.w, size.w)),
            h: Math.max(24, num(n.h, size.h)),
            text: str(n.text),
            variant:
              shape === 'network' && NETWORK_KINDS.includes(n.variant)
                ? (n.variant as CanvasNetworkKind)
                : shape === 'network'
                  ? 'server'
                  : undefined,
            container: n.container === true,
            tone: TONES.includes(n.tone) ? (n.tone as CanvasTone) : undefined,
            fontSize: Math.min(72, Math.max(8, num(n.fontSize, DEFAULT_FONT_SIZE))),
            bold: n.bold === true,
            align: n.align === 'left' ? 'left' : 'center',
          }
        })
    : []
  const ids = new Set(nodes.map((n) => n.id))
  const edges: CanvasEdge[] = Array.isArray(data.edges)
    ? data.edges
        .filter((e: any) => e && typeof e === 'object')
        .map((e: any) => {
          const from = normalizeAnchor(e.from, ids)
          const to = normalizeAnchor(e.to, ids)
          return {
            id: str(e.id) || newId('e'),
            from,
            to,
            curve: CURVES.includes(e.curve) ? (e.curve as EdgeCurve) : 'orthogonal',
            arrow: ARROWS.includes(e.arrow) ? (e.arrow as EdgeArrow) : 'end',
            dashed: e.dashed === true,
            label: str(e.label),
            tone: TONES.includes(e.tone) ? (e.tone as CanvasTone) : undefined,
          }
        })
        .filter((e: CanvasEdge) => e.from.nodeId || e.to.nodeId || e.from.x || e.from.y)
    : []
  const viewport = data.viewport && typeof data.viewport === 'object' ? data.viewport : {}
  return {
    version: 1,
    theme,
    grid: data.grid !== false,
    snap: data.snap === true,
    nodes,
    edges,
    viewport: {
      x: num(viewport.x, base.viewport.x),
      y: num(viewport.y, base.viewport.y),
      zoom: Math.min(4, Math.max(0.2, num(viewport.zoom, 1))),
    },
  }
}

function normalizeAnchor(raw: any, nodeIds: Set<string>): CanvasAnchor {
  const data = raw && typeof raw === 'object' ? raw : {}
  const nodeId = typeof data.nodeId === 'string' && nodeIds.has(data.nodeId) ? data.nodeId : null
  return {
    nodeId,
    side: SIDES.includes(data.side) ? data.side : 'auto',
    x: num(data.x, 0),
    y: num(data.y, 0),
  }
}

export function nodeCenter(node: CanvasNode): { x: number; y: number } {
  return { x: node.x + node.w / 2, y: node.y + node.h / 2 }
}

/** 节点某条边的中点（连线吸附点）。 */
export function anchorPoint(node: CanvasNode, side: CanvasSide): { x: number; y: number } {
  switch (side) {
    case 'top':
      return { x: node.x + node.w / 2, y: node.y }
    case 'bottom':
      return { x: node.x + node.w / 2, y: node.y + node.h }
    case 'left':
      return { x: node.x, y: node.y + node.h / 2 }
    default:
      return { x: node.x + node.w, y: node.y + node.h / 2 }
  }
}

/** 根据目标点方向选择最合适的吸附边。 */
export function facingSide(node: CanvasNode, point: { x: number; y: number }): CanvasSide {
  const center = nodeCenter(node)
  const dx = point.x - center.x
  const dy = point.y - center.y
  if (Math.abs(dx) * node.h >= Math.abs(dy) * node.w) {
    return dx >= 0 ? 'right' : 'left'
  }
  return dy >= 0 ? 'bottom' : 'top'
}

/** 所有节点（含线宽余量）的包围盒。 */
export function boundsOf(nodes: CanvasNode[]) {
  if (!nodes.length) return { x: 0, y: 0, w: 0, h: 0 }
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const node of nodes) {
    minX = Math.min(minX, node.x)
    minY = Math.min(minY, node.y)
    maxX = Math.max(maxX, node.x + node.w)
    maxY = Math.max(maxY, node.y + node.h)
  }
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
}
