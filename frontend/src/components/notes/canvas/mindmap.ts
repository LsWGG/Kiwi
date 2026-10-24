/**
 * 大纲 → 思维导图：把文档 Markdown 标题层级转成从左到右的树状画布。
 * 只读取标题行，正文段落与代码块不参与，保证生成的图结构清晰。
 */
import type { CanvasDoc, CanvasEdge, CanvasNode, CanvasTone } from './types'

const NODE_W = 190
const NODE_H = 46
const COL_GAP = 84
const ROW_GAP = 16
const ORIGIN = 64
const MAX_NODES = 120
const DEPTH_TONES: CanvasTone[] = ['accent', 'violet', 'green', 'amber', 'rose', 'neutral']
/** 根节点的直接分支分别着色，其余层级按深度递进，避免整棵树同色。 */
const BRANCH_TONES: CanvasTone[] = ['violet', 'green', 'amber', 'rose', 'accent', 'neutral']

interface OutlineNode {
  title: string
  level: number
  children: OutlineNode[]
}

let idSeq = 0
function nodeId(): string {
  idSeq += 1
  return `mind-${Date.now().toString(36)}-${idSeq}`
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

/** 从左到右布局：父节点在子节点纵向区间的中点，连线走贝塞尔曲线。 */
export function outlineToCanvasDoc(
  markdown: string,
  title: string,
): CanvasDoc | null {
  const tree = parseOutline(markdown, title)
  if (!tree) return null

  const nodes: CanvasNode[] = []
  const edges: CanvasEdge[] = []

  const place = (node: OutlineNode, depth: number, top: number, tone?: CanvasTone): string => {
    const height = subtreeHeight(node)
    const centerY = top + height / 2
    const id = nodeId()
    const nodeTone =
      tone ?? DEPTH_TONES[Math.min(depth, DEPTH_TONES.length - 1)]
    nodes.push({
      id,
      shape: depth === 0 ? 'round' : 'rect',
      x: ORIGIN + depth * (NODE_W + COL_GAP),
      y: Math.round(centerY - NODE_H / 2),
      w: NODE_W,
      h: NODE_H,
      text: node.title,
      tone: nodeTone,
      fontSize: depth === 0 ? 16 : 14,
      bold: depth === 0,
      align: 'left',
    })

    let cursor = top
    node.children.forEach((child, index) => {
      const childHeight = subtreeHeight(child)
      const childTone =
        depth === 0 ? BRANCH_TONES[index % BRANCH_TONES.length] : undefined
      const childId = place(child, depth + 1, cursor, childTone)
      edges.push({
        id: nodeId(),
        from: { nodeId: id, side: 'right', x: 0, y: 0 },
        to: { nodeId: childId, side: 'left', x: 0, y: 0 },
        curve: 'bezier',
        arrow: 'end',
      })
      cursor += childHeight + ROW_GAP
    })
    return id
  }

  place(tree, 0, ORIGIN)

  return {
    version: 1,
    theme: 'engineering',
    grid: true,
    snap: true,
    nodes,
    edges,
    viewport: { x: 0, y: 0, zoom: 0.8 },
  }
}
