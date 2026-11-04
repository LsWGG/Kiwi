/**
 * 分栏布局树：纯函数，负责拆分 / 移除 / 换位 / 预设排列与持久化校验。
 *
 * 树只有两种节点：
 * - pane：一个展示窗口（笔记 / 网页 / 文件）
 * - split：按 row / column 平铺若干子节点，sizes 为百分比
 */
export type PaneTarget =
  | { kind: 'note'; noteId: string; kbId: string }
  | { kind: 'url'; url: string; title: string; site?: string }
  | { kind: 'file'; url: string; filename: string; contentType: string; size?: number }

export interface PaneLeaf {
  id: string
  type: 'pane'
  target: PaneTarget
}

export interface PaneSplit {
  id: string
  type: 'split'
  direction: 'row' | 'column'
  /** 与 children 一一对应的百分比，总和约等于 100。 */
  sizes: number[]
  children: PaneNode[]
}

export type PaneNode = PaneLeaf | PaneSplit
export type DockZone = 'left' | 'right' | 'top' | 'bottom' | 'center'
export type PanePreset = 'row' | 'column' | 'grid'

export const MAX_PANES = 6
/** 拖动分隔线时单栏的最小宽度（px）。 */
export const MIN_PANE_PX = 240

let uidSeq = 0
export function paneUid(prefix = 'pane'): string {
  uidSeq += 1
  return `${prefix}-${Date.now().toString(36)}-${uidSeq}`
}

export function createLeaf(target: PaneTarget): PaneLeaf {
  return { id: paneUid(), type: 'pane', target }
}

export function createSplit(
  direction: 'row' | 'column',
  children: PaneNode[],
  sizes?: number[],
): PaneSplit {
  return {
    id: paneUid('split'),
    type: 'split',
    direction,
    children,
    sizes: normalizeSizes(sizes ?? equalSizes(children.length), children.length),
  }
}

export function equalSizes(count: number): number[] {
  if (count <= 0) return []
  return Array.from({ length: count }, () => 100 / count)
}

export function normalizeSizes(sizes: number[], count: number): number[] {
  if (count <= 0) return []
  const raw = sizes.slice(0, count).map((value) => (Number.isFinite(value) ? value : 0))
  while (raw.length < count) raw.push(0)
  const positive = raw.map((value) => (value > 0 ? value : 0))
  const total = positive.reduce((sum, value) => sum + value, 0)
  if (total <= 0) return equalSizes(count)
  return positive.map((value) => (value / total) * 100)
}

export function flattenPanes(node: PaneNode | null | undefined): PaneLeaf[] {
  if (!node) return []
  if (node.type === 'pane') return [node]
  return node.children.flatMap((child) => flattenPanes(child))
}

export function findPane(node: PaneNode | null | undefined, id: string | null): PaneLeaf | null {
  if (!node || !id) return null
  if (node.type === 'pane') return node.id === id ? node : null
  for (const child of node.children) {
    const found = findPane(child, id)
    if (found) return found
  }
  return null
}

export function findSplit(node: PaneNode | null | undefined, id: string | null): PaneSplit | null {
  if (!node || !id) return null
  if (node.type === 'split') {
    if (node.id === id) return node
    for (const child of node.children) {
      const found = findSplit(child, id)
      if (found) return found
    }
  }
  return null
}

/** 单子节点的 split 没有意义，递归折叠掉（返回 null 表示整棵子树为空）。 */
export function collapseNode(node: PaneNode | null): PaneNode | null {
  if (!node) return null
  if (node.type === 'pane') return node
  const children = node.children
    .map((child) => collapseNode(child))
    .filter((child): child is PaneNode => !!child)
  if (!children.length) return null
  if (children.length === 1) return children[0]
  return {
    ...node,
    children,
    sizes: normalizeSizes(node.sizes, children.length),
  }
}

/** 移除某个 pane，父 split 随之折叠。 */
export function removePane(
  node: PaneNode | null,
  paneId: string,
): PaneNode | null {
  if (!node) return null
  if (node.type === 'pane') return node.id === paneId ? null : node
  const index = node.children.findIndex((child) => child.id === paneId)
  if (index >= 0) {
    const children = node.children.filter((_, i) => i !== index)
    const sizes = node.sizes.filter((_, i) => i !== index)
    return collapseNode({
      ...node,
      children,
      sizes: normalizeSizes(sizes, children.length),
    })
  }
  const children = node.children.map((child) => removePane(child, paneId))
  return collapseNode({
    ...node,
    children: children.filter((child): child is PaneNode => !!child),
    sizes: normalizeSizes(node.sizes, children.length),
  })
}

/** 把 targetId 对应的 pane 换成 split(target, newLeaf)；zone 决定方向与新栏位置。 */
export function splitPaneAt(
  node: PaneNode,
  targetId: string,
  newLeaf: PaneLeaf,
  zone: Exclude<DockZone, 'center'>,
): PaneNode {
  if (node.type === 'pane') {
    if (node.id !== targetId) return node
    const direction = zone === 'left' || zone === 'right' ? 'row' : 'column'
    const before = zone === 'left' || zone === 'top'
    const children = before ? [newLeaf, node] : [node, newLeaf]
    return createSplit(direction, children, [50, 50])
  }
  return {
    ...node,
    children: node.children.map((child) => splitPaneAt(child, targetId, newLeaf, zone)),
  }
}

/** 交换两个 pane 的 target（停靠到中心）。 */
export function swapPaneTargets(node: PaneNode, aId: string, bId: string): PaneNode {
  if (node.type === 'pane') {
    if (node.id !== aId && node.id !== bId) return node
    return node
  }
  const targets = new Map<string, PaneTarget>()
  for (const leaf of flattenPanes(node)) {
    if (leaf.id === aId || leaf.id === bId) targets.set(leaf.id, leaf.target)
  }
  const a = targets.get(aId)
  const b = targets.get(bId)
  if (!a || !b) return node
  const replace = (n: PaneNode): PaneNode => {
    if (n.type === 'pane') {
      if (n.id === aId) return { ...n, target: b }
      if (n.id === bId) return { ...n, target: a }
      return n
    }
    return { ...n, children: n.children.map(replace) }
  }
  return replace(node)
}

/** 替换某个 pane 的 target，保留位置与 pane id（LRU 替换时使用）。 */
export function replacePaneTarget(
  node: PaneNode,
  paneId: string,
  target: PaneTarget,
): PaneNode {
  if (node.type === 'pane') {
    return node.id === paneId ? { ...node, target } : node
  }
  return {
    ...node,
    children: node.children.map((child) => replacePaneTarget(child, paneId, target)),
  }
}

/** 更新某个 split 的 sizes；其他节点原样返回。 */
export function updateSplitSizes(
  node: PaneNode,
  splitId: string,
  sizes: number[],
): PaneNode {
  if (node.type === 'pane') return node
  if (node.id === splitId) {
    return { ...node, sizes: normalizeSizes(sizes, node.children.length) }
  }
  return {
    ...node,
    children: node.children.map((child) => updateSplitSizes(child, splitId, sizes)),
  }
}

/**
 * 按当前叶子顺序重建布局：
 * - row：全部左右排列
 * - column：全部上下排列
 * - grid：每行最多 2 栏，行间上下排列
 */
export function buildPreset(
  leaves: PaneLeaf[],
  preset: PanePreset,
): PaneNode | null {
  if (!leaves.length) return null
  if (leaves.length === 1) return leaves[0]
  if (preset === 'row') return createSplit('row', leaves)
  if (preset === 'column') return createSplit('column', leaves)
  const rows: PaneNode[] = []
  for (let i = 0; i < leaves.length; i += 2) {
    const pair = leaves.slice(i, i + 2)
    rows.push(pair.length === 1 ? pair[0] : createSplit('row', pair, [50, 50]))
  }
  if (rows.length === 1) return rows[0]
  return createSplit('column', rows)
}

/** 最久未使用的 pane；活跃 pane 不参与，避免替换掉用户正在看的窗口。 */
export function leastRecentlyUsed(
  leaves: PaneLeaf[],
  lastUsed: Record<string, number>,
  activePaneId: string | null,
): PaneLeaf | null {
  const candidates = leaves.filter((leaf) => leaf.id !== activePaneId)
  const pool = candidates.length ? candidates : leaves
  let victim: PaneLeaf | null = null
  let least = Number.POSITIVE_INFINITY
  for (const leaf of pool) {
    const used = lastUsed[leaf.id] ?? 0
    if (used < least) {
      least = used
      victim = leaf
    }
  }
  return victim
}

export function sameTarget(a: PaneTarget, b: PaneTarget): boolean {
  if (a.kind === 'note') return b.kind === 'note' && a.noteId === b.noteId
  if (b.kind === 'note') return false
  return a.url === b.url
}

function isTarget(value: unknown): value is PaneTarget {
  if (!value || typeof value !== 'object') return false
  const target = value as Record<string, unknown>
  if (target.kind === 'note') {
    return (
      typeof target.noteId === 'string' &&
      target.noteId.length > 0 &&
      typeof target.kbId === 'string'
    )
  }
  if (target.kind === 'url') {
    return typeof target.url === 'string' && target.url.length > 0
  }
  if (target.kind === 'file') {
    return (
      typeof target.url === 'string' &&
      target.url.length > 0 &&
      typeof target.filename === 'string'
    )
  }
  return false
}

function parseNode(raw: unknown): PaneNode | null {
  if (!raw || typeof raw !== 'object') return null
  const node = raw as Record<string, any>
  if (node.type === 'pane') {
    if (typeof node.id !== 'string' || !isTarget(node.target)) return null
    return { id: node.id, type: 'pane', target: node.target }
  }
  if (node.type === 'split') {
    if (
      typeof node.id !== 'string' ||
      (node.direction !== 'row' && node.direction !== 'column') ||
      !Array.isArray(node.children)
    ) {
      return null
    }
    const children = node.children
      .map((child: unknown) => parseNode(child))
      .filter((child: PaneNode | null): child is PaneNode => !!child)
    if (!children.length) return null
    if (children.length === 1) return children[0]
    return {
      id: node.id,
      type: 'split',
      direction: node.direction,
      children,
      sizes: normalizeSizes(Array.isArray(node.sizes) ? node.sizes : [], children.length),
    }
  }
  return null
}

export interface StoredLayout {
  version: 1
  enabled: boolean
  root: PaneNode
  activePaneId: string | null
  lastUsed: Record<string, number>
}

/** 从 localStorage 读取的原始对象中校验出可用布局；无效返回 null。 */
export function parseStoredLayout(raw: unknown): StoredLayout | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, any>
  if (data.version !== 1) return null
  const root = parseNode(data.root)
  if (!root) return null
  if (flattenPanes(root).length > MAX_PANES) return null
  const lastUsed: Record<string, number> = {}
  if (data.lastUsed && typeof data.lastUsed === 'object') {
    for (const [key, value] of Object.entries(data.lastUsed)) {
      if (typeof value === 'number' && Number.isFinite(value)) lastUsed[key] = value
    }
  }
  const activePaneId =
    typeof data.activePaneId === 'string' && findPane(root, data.activePaneId)
      ? data.activePaneId
      : flattenPanes(root)[0]?.id ?? null
  return {
    version: 1,
    enabled: data.enabled === true,
    root,
    activePaneId,
    lastUsed,
  }
}
