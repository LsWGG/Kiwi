/**
 * 大纲 → 思维导图（jvs-draw 文档）。
 * 只读取 Markdown 标题行，按层级从左到右排布，正文与代码块不参与。
 */
import type { DrawElement, JvsDrawDoc } from './types'

const NODE_W = 200
const NODE_H = 48
const COL_GAP = 88
const ROW_GAP = 16
const ORIGIN = 64
const MAX_NODES = 120

interface Tone {
  fill: string
  stroke: string
  text: string
}

const ROOT_TONE: Tone = { fill: '#4f46e5', stroke: '#4338ca', text: '#ffffff' }
const BRANCH_TONES: Tone[] = [
  { fill: '#ede9fe', stroke: '#8b5cf6', text: '#4c1d95' },
  { fill: '#ccfbf1', stroke: '#14b8a6', text: '#134e4a' },
  { fill: '#fef3c7', stroke: '#f59e0b', text: '#78350f' },
  { fill: '#ffe4e6', stroke: '#f43f5e', text: '#881337' },
  { fill: '#dbeafe', stroke: '#3b82f6', text: '#1e3a8a' },
  { fill: '#f1f5f9', stroke: '#94a3b8', text: '#334155' },
]
const DEPTH_TONES: Tone[] = [
  ROOT_TONE,
  BRANCH_TONES[0],
  BRANCH_TONES[2],
  BRANCH_TONES[4],
  BRANCH_TONES[5],
]

interface OutlineNode {
  title: string
  level: number
  children: OutlineNode[]
}

let idSeq = 0
function elementId(prefix: string): string {
  idSeq += 1
  return `${prefix}-${Date.now().toString(36)}-${idSeq}`
}

function cleanHeading(raw: string): string {
  return raw
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*_`~]/g, '')
    .replace(/<[^>]+>/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** 解析标题树；没有标题时返回 null。 */
export function parseOutline(markdown: string, fallbackTitle: string): OutlineNode | null {
  const root: OutlineNode = {
    title: fallbackTitle.trim() || '思维导图',
    level: 0,
    children: [],
  }
  const stack: OutlineNode[] = [root]
  let fence = false
  let count = 0

  for (const line of markdown.split(/\r?\n/)) {
    if (/^\s*(```|~~~)/.test(line)) {
      fence = !fence
      continue
    }
    if (fence) continue
    const match = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line)
    if (!match) continue
    const level = match[1].length
    const title = cleanHeading(match[2])
    if (!title) continue
    while (stack.length > 1 && stack[stack.length - 1].level >= level) {
      stack.pop()
    }
    const node: OutlineNode = { title, level, children: [] }
    stack[stack.length - 1].children.push(node)
    stack.push(node)
    count += 1
    if (count >= MAX_NODES) break
  }

  return root.children.length ? root : null
}

function subtreeHeight(node: OutlineNode): number {
  if (!node.children.length) return NODE_H
  const children = node.children.reduce(
    (sum, child, index) => sum + subtreeHeight(child) + (index ? ROW_GAP : 0),
    0,
  )
  return Math.max(NODE_H, children)
}

function baseElement(
  id: string,
  type: string,
  x: number,
  y: number,
  width: number,
  height: number,
): DrawElement {
  return {
    id,
    type,
    x,
    y,
    width,
    height,
    angle: 0,
    strokeColor: '#cbd5e1',
    backgroundColor: 'transparent',
    fillStyle: 'solid',
    strokeWidth: 2,
    strokeStyle: 'solid',
    roughness: 1,
    opacity: 100,
    strokeOpacity: 100,
    roundness: { type: 3 },
    fontSize: 14,
    fontFamily: 'sans-serif',
    fontColor: '#1e293b',
    fontBgColor: 'transparent',
    textAlign: 'left',
    verticalAlign: 'middle',
    isBold: false,
    fontWeight: 'normal',
    seed: idSeq + 1,
    version: 1,
    versionNonce: idSeq + 1,
    isDeleted: false,
    groupIds: [],
    boundElements: [],
    updated: Date.now(),
    link: null,
    locked: false,
    frameId: null,
    lineHeight: 1.25,
    letterSpacing: 0,
  }
}

function addNode(
  elements: DrawElement[],
  id: string,
  title: string,
  x: number,
  y: number,
  tone: Tone,
  isRoot: boolean,
): DrawElement {
  const shape = baseElement(id, isRoot ? 'rectangle' : 'rectangle', x, y, NODE_W, NODE_H)
  Object.assign(shape, {
    strokeColor: tone.stroke,
    backgroundColor: tone.fill,
    strokeWidth: isRoot ? 2 : 1.6,
    roundness: { type: 3 },
  })
  elements.push(shape)

  const textId = `${id}-text`
  const text = baseElement(textId, 'text', x + 12, y + 8, NODE_W - 24, NODE_H - 16)
  Object.assign(text, {
    text: title,
    originalText: title,
    containerId: id,
    autoResize: false,
    fontSize: isRoot ? 16 : 13.5,
    fontColor: tone.text,
    textAlign: 'left',
    verticalAlign: 'middle',
    isBold: isRoot,
    fontWeight: isRoot ? 'bold' : 'normal',
    roundness: null,
    backgroundColor: 'transparent',
  })
  shape.boundElements = [{ type: 'text', id: textId }]
  elements.push(text)
  return shape
}

function addEdge(elements: DrawElement[], from: DrawElement, to: DrawElement): void {
  const x1 = from.x + from.width
  const y1 = from.y + from.height / 2
  const x2 = to.x
  const y2 = to.y + to.height / 2
  const minX = Math.min(x1, x2)
  const minY = Math.min(y1, y2)
  const element = baseElement(
    elementId('edge'),
    'arrow',
    minX,
    minY,
    Math.max(1, Math.abs(x2 - x1)),
    Math.max(1, Math.abs(y2 - y1)),
  )
  Object.assign(element, {
    points: [
      [x1 - minX, y1 - minY],
      [x2 - minX, y2 - minY],
    ],
    lastCommittedPoint: null,
    startArrowhead: null,
    endArrowhead: 'arrow',
    arrowType: 'sharp',
    strokeColor: '#94a3b8',
    backgroundColor: 'transparent',
    strokeWidth: 1.6,
    roundness: null,
    startBinding: { elementId: from.id, focus: 0, gap: 4, isBorder: false },
    endBinding: { elementId: to.id, focus: 0, gap: 4, isBorder: false },
  })
  elements.push(element)
}

/** 从左到右布局：父节点位于子节点纵向区间的中点，箭头从右侧连到子节点左侧。 */
export function outlineToDrawDoc(markdown: string, title: string): JvsDrawDoc | null {
  const tree = parseOutline(markdown, title)
  if (!tree) return null

  const elements: DrawElement[] = []
  const shapes = new Map<string, DrawElement>()

  const place = (node: OutlineNode, depth: number, top: number, tone?: Tone): string => {
    const height = subtreeHeight(node)
    const centerY = top + height / 2
    const id = elementId('mind')
    const nodeTone = tone ?? DEPTH_TONES[Math.min(depth, DEPTH_TONES.length - 1)]
    const shape = addNode(
      elements,
      id,
      node.title,
      ORIGIN + depth * (NODE_W + COL_GAP),
      Math.round(centerY - NODE_H / 2),
      nodeTone,
      depth === 0,
    )
    shapes.set(id, shape)

    let cursor = top
    node.children.forEach((child, index) => {
      const childHeight = subtreeHeight(child)
      const childTone =
        depth === 0 ? BRANCH_TONES[index % BRANCH_TONES.length] : undefined
      const childId = place(child, depth + 1, cursor, childTone)
      const childShape = shapes.get(childId)
      if (childShape) addEdge(elements, shape, childShape)
      cursor += childHeight + ROW_GAP
    })
    return id
  }

  place(tree, 0, ORIGIN)

  return {
    type: 'jvs-draw',
    version: 1,
    elements,
    appState: { viewBackgroundColor: '#f8fafc' },
    files: {},
    updatedAt: Date.now(),
  }
}
