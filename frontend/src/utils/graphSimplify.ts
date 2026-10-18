/**
 * 图谱精要视图：把「全量关系图」压缩成可读的骨架。
 *
 * 背景：Wiki 页面之间除了显式 `[[slug]]` 引用外，编译还会按共同引用 / 标签
 * 自动补「相关」边；业务库一多，边数会远大于节点数，直接绘制会出现线条和
 * 标签堆叠。这里做三件事（只在精要模式下生效）：
 *
 * 1. 去掉自动生成的 `related` 边（完整模式仍可查看）；
 * 2. 双向引用合并为一条视觉边，避免两条直线完全重叠；
 * 3. 按连接度保留前 N 个节点（聚焦筛选时不裁剪），其余边同步裁掉。
 *
 * 完整模式原样返回，保证任何关系都不会在系统中丢失。
 */

export interface SimplifyNode {
  id: string
  link_count: number
}

export interface SimplifyEdge {
  source: string
  target: string
  type: string
}

const EDGE_PRIORITY: Record<string, number> = {
  contradiction: 5,
  // 笔记关系优先于普通 Wiki 引用：勾选「包含笔记节点」时，
  // 这些边必须先占位，否则笔记会以孤立星点出现。
  note_link: 4.5,
  note_wiki: 4.5,
  reference: 4,
  related: 1,
}

export interface SimplifyOptions {
  compact: boolean
  /** 精要模式最多展示的节点数 */
  maxNodes?: number
  /** 聚焦邻域模式下不做节点裁剪，只做边合并 */
  focusActive?: boolean
  /** 额外保留的节点（例如当前选中的知识点） */
  keepIds?: string[]
  /** 精要模式下每个节点最多保留的关系数（控制线条密度） */
  maxEdgesPerNode?: number
}

export interface SimplifyResult<N extends SimplifyNode, E extends SimplifyEdge> {
  nodes: N[]
  edges: E[]
  hiddenNodes: number
  hiddenEdges: number
}

export function simplifyGraph<N extends SimplifyNode, E extends SimplifyEdge>(
  nodes: N[],
  edges: E[],
  options: SimplifyOptions,
): SimplifyResult<N, E> {
  if (!options.compact) {
    return { nodes, edges, hiddenNodes: 0, hiddenEdges: 0 }
  }

  // 1) 自动「相关」边在精要模式中隐藏；2) 同一对节点的多条边只保留最强的一条。
  const pairEdges = new Map<string, E>()
  for (const edge of edges) {
    if (edge.type === 'related') continue
    const key = [edge.source, edge.target].sort().join('|')
    const current = pairEdges.get(key)
    if (!current || (EDGE_PRIORITY[edge.type] ?? 0) > (EDGE_PRIORITY[current.type] ?? 0)) {
      pairEdges.set(key, edge)
    }
  }
  const dedupedEdges = [...pairEdges.values()]

  // 3) 按精要视图中的真实连接度排序，保留骨架节点。
  const degree = new Map<string, number>()
  for (const edge of dedupedEdges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
  }
  const maxNodes = Math.max(6, options.maxNodes ?? 18)
  const ranked = [...nodes].sort(
    (a, b) =>
      (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0) || b.link_count - a.link_count,
  )
  const base = options.focusActive ? nodes : ranked.slice(0, maxNodes)
  const keepIds = new Set(base.map((node) => node.id))
  for (const id of options.keepIds ?? []) {
    if (nodes.some((node) => node.id === id)) keepIds.add(id)
  }
  const visibleNodes = nodes.filter((node) => keepIds.has(node.id))

  // 4) 每个节点最多保留 N 条边：先保留跨模块/高连接度节点之间的边，
  //    避免中心节点被十几条线穿过，精要视图保持稀疏可读。
  const maxEdgesPerNode = Math.max(1, options.maxEdgesPerNode ?? 3)
  const candidates = dedupedEdges
    .filter((edge) => keepIds.has(edge.source) && keepIds.has(edge.target))
    .sort(
      (a, b) =>
        (EDGE_PRIORITY[b.type] ?? 0) - (EDGE_PRIORITY[a.type] ?? 0) ||
        (degree.get(b.source) ?? 0) + (degree.get(b.target) ?? 0) -
          ((degree.get(a.source) ?? 0) + (degree.get(a.target) ?? 0)),
    )
  const edgeDegree = new Map<string, number>()
  const visibleEdges: E[] = []
  for (const edge of candidates) {
    const sourceDegree = edgeDegree.get(edge.source) ?? 0
    const targetDegree = edgeDegree.get(edge.target) ?? 0
    if (sourceDegree >= maxEdgesPerNode || targetDegree >= maxEdgesPerNode) continue
    visibleEdges.push(edge)
    edgeDegree.set(edge.source, sourceDegree + 1)
    edgeDegree.set(edge.target, targetDegree + 1)
  }

  return {
    nodes: visibleNodes,
    edges: visibleEdges,
    hiddenNodes: nodes.length - visibleNodes.length,
    hiddenEdges: edges.length - visibleEdges.length,
  }
}
