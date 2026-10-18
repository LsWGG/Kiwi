<script setup lang="ts">
/**
 * KiwiGraph：G6 v5 知识图谱封装组件（2D）。
 * 唯一引入 @antv/g6 的文件——未来换渲染器只需改这里。
 * - 动态 import @antv/g6；加载失败时父组件展示兜底列表。
 * - 节点按 page_type 配色（跨色系高区分度），link_count 映射节点尺寸，
 *   渐变 + 同色光晕 + 白色描边；曲率边带箭头；drag/zoom/hover tooltip。
 * - 外部交互：node:click 事件（抛完整 node id，如 "wiki:<uuid>"）。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

export interface GraphNodeData {
  id: string
  kind: string
  title: string
  page_type: string
  link_count: number
  /** 学习图谱：0-1 掌握度 */
  mastery?: number
  /** 学习图谱：薄弱标记 */
  weak?: boolean
  /** 学习图谱：复习到期 */
  due?: boolean
  /** 学习图谱：知识点内容已更新 */
  content_updated?: boolean
}
export interface GraphEdgeData {
  source: string
  target: string
  type: string
}

const props = withDefaults(
  defineProps<{
    nodes: GraphNodeData[]
    edges: GraphEdgeData[]
    /** wiki：按页面类型着色；mastery：按掌握度顺序色阶着色 */
    mode?: 'wiki' | 'mastery'
    /** 节点拖拽位置持久化的命名空间（通常传 kb id）；为空则不持久化 */
    storageKey?: string
    /** 只读图谱：禁用节点拖拽 */
    readonly?: boolean
  }>(),
  { nodes: () => [], edges: () => [], mode: 'wiki', storageKey: '', readonly: false },
)
const emit = defineEmits<{
  (e: 'node:click', nodeId: string): void
  /** G6 加载或渲染失败时上抛，父组件据此降级为列表（避免停在空白画布） */
  (e: 'unavailable'): void
  /** 画布渲染完成回调，父组件据此熄灭「布局计算中」遮罩 */
  (e: 'ready'): void
}>()

const container = ref<HTMLDivElement>()
const available = ref(false)

// ---------- 类型配色：柔和淡彩，符合「冷紫灰玻璃」主题 ----------
// 中低饱和跨色系色相（品牌紫 / 青 / 绿 / 琥珀 / 玫红），不刺眼；
// 用 OKLab 校验两两 ΔE 最低 12.8（青↔绿为相邻近色，天然靠拢），其余 15–28 可辨。
const NODE_PALETTE: Record<string, { fill: string; light: string; glow: string }> = {
  entity: { fill: '#6f72dc', light: '#aeb1f2', glow: 'rgba(111,114,220,0.22)' },
  concept: { fill: '#3fa0c9', light: '#8fd3eb', glow: 'rgba(63,160,201,0.22)' },
  summary: { fill: '#559d71', light: '#95cba4', glow: 'rgba(85,157,113,0.22)' },
  synthesis: { fill: '#c6944e', light: '#e2c78f', glow: 'rgba(198,148,78,0.24)' },
  note: { fill: '#7a8b9e', light: '#b7c3cf', glow: 'rgba(122,139,158,0.22)' },
  wiki: { fill: '#bd6f9e', light: '#ddb3cd', glow: 'rgba(189,111,158,0.22)' },
}
const NODE_STROKE = '#ffffff' // 白色描边提升对比
const EDGE_HOVER = '#b9c0ff'
const LABEL_COLOR = '#f8fafc' // 深色背景反白
const MAX_COUNT = 10

/** 边类型 → 线型 / 颜色（README 10.2：引用、相关、矛盾用线型和颜色区分） */
const EDGE_STYLES: Record<
  string,
  { stroke: string; width: number; dash?: number[]; label: string; opacity: number }
> = {
  reference: { stroke: '#7c86ee', width: 1.6, label: '引用', opacity: 0.85 },
  note_link: { stroke: '#4fb3a5', width: 1.5, dash: [5, 4], label: '笔记双向链接', opacity: 0.9 },
  note_wiki: { stroke: '#c58ad0', width: 1.5, dash: [2, 3], label: '笔记关联 Wiki', opacity: 0.9 },
  related: { stroke: '#d0a24a', width: 1.6, dash: [8, 4], label: '相关', opacity: 0.9 },
  contradiction: { stroke: '#ef6a6a', width: 2, dash: [4, 3], label: '矛盾标记', opacity: 0.95 },
}
const EDGE_FALLBACK = EDGE_STYLES.reference

function edgeStyleOf(type: string) {
  return EDGE_STYLES[type] ?? EDGE_FALLBACK
}

/** 节点拖拽位置持久化键；空字符串表示不持久化。 */
function positionsKey(): string {
  return props.storageKey ? `kiwi.graph.positions.${props.storageKey}` : ''
}

function readPositions(): Record<string, [number, number]> {
  const key = positionsKey()
  if (!key) return {}
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    const result: Record<string, [number, number]> = {}
    for (const [id, pos] of Object.entries(parsed)) {
      if (Array.isArray(pos) && pos.length === 2 && pos.every((v) => Number.isFinite(v))) {
        result[id] = [Number(pos[0]), Number(pos[1])]
      }
    }
    return result
  } catch {
    return {}
  }
}

function writePositions(ids: string[]) {
  const key = positionsKey()
  if (!key || !g) return
  try {
    const existing = readPositions()
    for (const id of ids) {
      try {
        const pos = g.getElementPosition(id)
        if (Array.isArray(pos) && pos.length === 2) {
          existing[id] = [Number(pos[0]), Number(pos[1])]
        }
      } catch {
        /* 节点已被过滤 */
      }
    }
    localStorage.setItem(key, JSON.stringify(existing))
  } catch {
    /* 配额 / 隐私模式忽略 */
  }
}

/** 布局收敛后应用手动拖拽过的节点位置。 */
async function applySavedPositions() {
  if (!g) return
  const saved = readPositions()
  const validIds = new Set(props.nodes.map((n) => n.id))
  const positions: Record<string, [number, number]> = {}
  for (const [id, pos] of Object.entries(saved)) {
    if (validIds.has(id)) positions[id] = pos
  }
  if (!Object.keys(positions).length) return
  try {
    await g.translateElementTo(positions, false)
  } catch {
    /* 版本差异容忍 */
  }
}

/** 掌握度顺序色阶：单一色相由浅到深（0 → 1），色盲友好 */
const MASTERY_STEPS = ['#e6e8fb', '#c9cdf7', '#a9aef0', '#878de6', '#666cdb', '#474dcb']
const WEAK_STROKE = '#fb7185'
const DUE_STROKE = '#fbbf24'

function masteryPalette(mastery: number, weak: boolean) {
  const value = Math.max(0, Math.min(1, mastery || 0))
  const idx = Math.min(
    MASTERY_STEPS.length - 1,
    Math.max(0, Math.round(value * (MASTERY_STEPS.length - 1))),
  )
  return {
    fill: MASTERY_STEPS[idx],
    light: MASTERY_STEPS[Math.max(0, idx - 1)],
    glow: weak ? 'rgba(251,113,133,0.28)' : 'rgba(99,102,241,0.24)',
  }
}

/** 稳定字符串散列（用于给边分配稳定曲率，相同 id 画同一弧度） */
function strHash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) >>> 0
  }
  return h
}

/** 节点浮动呼吸动画：Canvas 元素挂 Web Animations Y 轴微浮动，
 *  延迟按 id 散列错开，形成错落漂浮感。布局已收敛，不会与力导向冲突。 */
function startFloat() {
  try {
    const canvas = g?.getCanvas()
    // 首次挂动画后标记，避免 watch 重建重复挂同一批
    if (g.__floating) return
    for (const n of props.nodes) {
      const el = canvas?.getElementById?.(n.id)
      if (!el?.animate) continue
      const phase = (strHash(n.id) % 8) * 400 // 0..2800ms 错开
      el.animate(
        [{ y: 0 }, { y: -9 }, { y: 0 }],
        {
          duration: 3400,
          easing: 'ease-in-out',
          iterations: Infinity,
          delay: phase,
        },
      )
    }
    g.__floating = true
  } catch {
    /* 动画挂载失败不阻塞图谱 */
  }
}

let g: any = null
let GraphCtor: any = null

async function loadG6() {
  if (GraphCtor) return
  try {
    const mod = await import('@antv/g6')
    GraphCtor = mod.Graph
    available.value = true
  } catch {
    available.value = false
    emit('unavailable')
  }
}

async function createGraph() {
  if (!GraphCtor || !container.value) return
  try {
    g?.destroy()
    const validIds = new Set(props.nodes.map((n) => n.id))
    const edges = props.edges.filter((e) => validIds.has(e.source) && validIds.has(e.target))
    // 归一化为 G6 v5 约定：业务字段放 data（style 回调经 d.data 读取）
    const g6Nodes = props.nodes.map((n) => ({
      id: n.id,
      data: {
        title: n.title,
        page_type: n.page_type,
        link_count: n.link_count,
        kind: n.kind,
        mastery: n.mastery,
        weak: n.weak,
        due: n.due,
        content_updated: n.content_updated,
      },
    }))
    const g6Edges = edges.map((e) => ({
      source: e.source,
      target: e.target,
      data: { type: e.type },
    }))

    g = new GraphCtor({
      container: container.value,
      autoFit: { type: 'view', options: { when: 'always' }, animation: false },
      layout: {
        type: 'd3-force',
        linkDistance: 130,
        preventOverlap: true,
        collideStrength: 0.95,
        nodeStrength: -120,
        edgeStrength: 0.6,
      },
      node: {
        style: (d: any) => {
          const meta = d.data ?? {}
          const ratio = Math.min(meta.link_count ?? 0, MAX_COUNT) / MAX_COUNT
          const isMastery = props.mode === 'mastery'
          const size = isMastery ? 30 + ratio * 18 : 26 + ratio * 26 // 26..52
          const pal = isMastery
            ? masteryPalette(meta.mastery ?? 0, !!meta.weak)
            : (NODE_PALETTE[meta.page_type] ?? NODE_PALETTE.wiki)
          return {
            size,
            // 线性渐变：左上亮 → 右下主色，柔和光影（g-lite 用标准 CSS 渐变字符串）
            fill: `linear-gradient(135deg, ${pal.light} 0%, ${pal.fill} 100%)`,
            stroke: isMastery && meta.weak ? WEAK_STROKE : isMastery && meta.due ? DUE_STROKE : NODE_STROKE,
            lineWidth: isMastery && meta.weak ? 3 : isMastery && meta.due ? 2.5 : 2.5,
            lineDash: isMastery && meta.due && !meta.weak ? [5, 4] : undefined,
            shadowColor: pal.glow,
            shadowBlur: 14,
            shadowOffsetX: 0,
            shadowOffsetY: 2,
            labelText: meta.title ?? d.id,
            labelFill: LABEL_COLOR,
            labelFontSize: 12,
            labelPlacement: 'bottom',
            labelFontWeight: 600,
            labelMaxWidth: 150,
            labelBackground: true,
            labelBackgroundFill: 'rgba(10,14,34,0.72)',
            labelBackgroundRadius: 8,
            labelPadding: [2, 6, 2, 6],
          }
        },
        state: {
          hover: { lineWidth: 3, shadowBlur: 24 },
          selected: { lineWidth: 3.5, shadowBlur: 26 },
          inactive: { fill: '#1b2352', shadowColor: 'transparent', shadowBlur: 0 },
        },
      },
      edge: {
        style: (d: any) => {
          // 平行/密集边给不同曲率，避免重叠成直线
          const curve = (strHash(d.id ?? `${d.source}-${d.target}`) % 3 - 1) * 18
          const style = edgeStyleOf(String(d.data?.type ?? 'reference'))
          return {
            stroke: style.stroke,
            lineWidth: style.width,
            lineDash: style.dash,
            endArrow: true,
            startArrow: false,
            curveOffset: curve,
            curvePosition: 0.5,
            lineAppendWidth: 8, // 更易点击
            strokeOpacity: style.opacity,
            labelText: '',
          }
        },
        state: {
          hover: { stroke: EDGE_HOVER, lineWidth: 2.4, strokeOpacity: 1, labelText: '' },
          inactive: { stroke: '#232a4d', strokeOpacity: 0.6 },
        },
      },
      behaviors: [
        'drag-canvas',
        'zoom-canvas',
        // 学习图谱只读；编辑图谱允许拖拽并在结束后持久化位置
        ...(props.readonly || props.mode === 'mastery'
          ? []
          : [
              {
                type: 'drag-element',
                onFinish: (ids: string[]) => writePositions(ids),
              },
            ]),
        { type: 'hover-activate', degree: 1, activeState: 'hover', inactiveState: 'inactive' },
      ],
      plugins: [
        {
          type: 'tooltip',
          style: {
            '.tooltip': {
              'background-color': 'rgba(10, 14, 34, 0.9)',
              'box-shadow': '0 8px 20px rgba(0, 0, 0, 0.45)',
              'border-radius': '10px',
              color: '#cbd5e1',
              border: '1px solid rgba(139, 134, 230, 0.35)',
            },
            '.tooltip-title': { color: '#e2e8f0' },
            '.tooltip-list-item-marker': { display: 'none' },
          },
          getContent: (evt: any) => {
            const item = evt?.target?.id != null ? evt.target : null
            if (!item) return '<span style="font-size:11px;color:#cbd5e1">无信息</span>'
            const isEdge = evt.targetType === 'edge' || !!(item.source)
            if (isEdge) {
              const linkType = String(item.source?.data?.type ?? item.data?.type ?? 'reference')
              return `<span style="font-size:11px;color:#cbd5e1;white-space:nowrap">↔ ${edgeStyleOf(linkType).label}</span>`
            }
            const meta = item.data ?? {}
            const title = meta.title ?? item.id
            const count = meta.link_count ?? 0
            const masteryLine =
              props.mode === 'mastery'
                ? ` · 掌握度 ${Math.round((meta.mastery ?? 0) * 100)}%${meta.weak ? ' · 薄弱' : ''}${meta.due ? ' · 待复习' : ''}${meta.content_updated ? ' · 内容已更新' : ''}`
                : ` · ${meta.page_type ?? ''}`
            return `<div style="font-size:11px;color:#e2e8f0;white-space:nowrap">
  <b style="color:#c7ccff">${title}</b>
  <div style="color:#94a3b8;margin-top:2px">关联 ${count} 条${masteryLine}</div>
</div>`
          },
        },
      ],
      animation: false,
    })

    // 力导向布局收敛后再应用手动拖拽位置，避免被布局覆盖
    g.on('afterlayout', () => void applySavedPositions())
    g.setData({ nodes: g6Nodes, edges: g6Edges })
    await g.render()
    await applySavedPositions()
    startFloat()
    emit('ready')
    g.on('node:click', (e: any) => {
      const id = e?.target?.id ?? (typeof e?.targetId === 'string' ? e.targetId : undefined)
      if (id) emit('node:click', id)
    })
  } catch (err) {
    console.warn('[KiwiGraph] G6 渲染失败，降级为列表展示', err)
    available.value = false
    emit('unavailable')
    try { g?.destroy() } catch { /* noop */ }
    g = null
  }
}

function resize() {
  if (container.value && g?.resize) {
    try { g.resize() } catch { /* 版本差异容忍 */ }
  }
}

/** 重跑 d3-force 布局（供父组件「重新布局」按钮调用，无需重建图）。
 *  显式重新布局会清除本图谱已保存的手动位置，让节点回到自动布局。 */
function layout() {
  const key = positionsKey()
  if (key) {
    try {
      localStorage.removeItem(key)
    } catch {
      /* 忽略 */
    }
  }
  if (g?.layout) {
    try { g.layout() } catch { /* 版本差异容忍 */ }
  }
}

let ro: ResizeObserver | null = null

onMounted(async () => {
  await loadG6()
  await nextTick()
  await createGraph()
  if (available.value && container.value) {
    ro = new ResizeObserver(() => resize())
    ro.observe(container.value)
  }
})

watch(
  () => [props.nodes, props.edges, props.mode],
  async () => {
    if (!GraphCtor) return
    await createGraph()
  },
)

onBeforeUnmount(() => {
  ro?.disconnect()
  try { g?.destroy() } catch { /* noop */ }
  g = null
})

defineExpose({ layout })
</script>

<template>
  <div ref="container" class="w-full h-full min-h-0" />
</template>