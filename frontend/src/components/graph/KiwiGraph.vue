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
    /** 常驻标签上限；0 = 按节点数自动计算 */
    labelLimit?: number
  }>(),
  {
    nodes: () => [],
    edges: () => [],
    mode: 'wiki',
    storageKey: '',
    readonly: false,
    labelLimit: 0,
  },
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
  entity: { fill: '#818cf8', light: '#c7d2fe', glow: 'rgba(129,140,248,0.55)' },
  concept: { fill: '#38bdf8', light: '#bae6fd', glow: 'rgba(56,189,248,0.5)' },
  summary: { fill: '#34d399', light: '#a7f3d0', glow: 'rgba(52,211,153,0.5)' },
  synthesis: { fill: '#fbbf24', light: '#fde68a', glow: 'rgba(251,191,36,0.5)' },
  note: { fill: '#a5b4cf', light: '#e2e8f0', glow: 'rgba(165,180,207,0.45)' },
  wiki: { fill: '#f472b6', light: '#fbcfe8', glow: 'rgba(244,114,182,0.5)' },
}
const NODE_STROKE = 'rgba(255,255,255,0.72)' // 星点边缘的冷白描边
const EDGE_HOVER = '#dbeafe'
const LABEL_COLOR = '#e6ecff' // 星空画布使用浅色标签
const MAX_COUNT = 8

/** 边类型 → 线型 / 颜色（README 10.2：引用、相关、矛盾用线型和颜色区分） */
const EDGE_STYLES: Record<
  string,
  { stroke: string; width: number; dash?: number[]; label: string; opacity: number }
> = {
  reference: { stroke: '#93a7ff', width: 0.9, label: '引用', opacity: 0.42 },
  note_link: { stroke: '#5eead4', width: 1, dash: [3, 3], label: '笔记双向链接', opacity: 0.42 },
  note_wiki: { stroke: '#d8b4fe', width: 1, dash: [2, 3], label: '笔记关联 Wiki', opacity: 0.42 },
  related: { stroke: '#fcd34d', width: 1, dash: [5, 4], label: '相关', opacity: 0.32 },
  contradiction: { stroke: '#fb7185', width: 1.4, dash: [4, 2], label: '矛盾标记', opacity: 0.75 },
}
const EDGE_FALLBACK = EDGE_STYLES.reference

/** 页面类型中文名：tooltip 只展示人能读懂的信息，不回退到内部 id。 */
const PAGE_TYPE_LABEL: Record<string, string> = {
  entity: '实体',
  concept: '概念',
  summary: '摘要',
  synthesis: '综述',
  note: '笔记',
  wiki: 'Wiki',
}

function edgeStyleOf(type: string) {
  return EDGE_STYLES[type] ?? EDGE_FALLBACK
}

/** tooltip 内容来自用户数据，注入 HTML 前必须转义。 */
function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
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

/** 掌握度色阶：星空画布上以「亮度」表达掌握度——未掌握是暗淡星点，
 *  越掌握越亮，形成「学习即点亮星空」的直观隐喻。 */
const MASTERY_STEPS = ['#58678a', '#6f80a8', '#8fa4d0', '#b6cbf5', '#e8f2ff']
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
    light: MASTERY_STEPS[Math.min(MASTERY_STEPS.length - 1, idx + 1)],
    glow: weak ? 'rgba(251,113,133,0.5)' : `rgba(147,197,253,${0.2 + value * 0.36})`,
  }
}

let g: any = null
let GraphCtor: any = null
let fitTimer: number | null = null

/** 力导向布局收敛后再做一次适配：首帧 fit 可能发生在节点仍在扩散时，
 *  会导致整图缩得过小（学习图谱尤其明显）。 */
function scheduleFit() {
  if (fitTimer) window.clearTimeout(fitTimer)
  fitTimer = window.setTimeout(() => {
    fitTimer = null
    fitGraph()
  }, 2800)
}

/** 鼠标直接移出画布/窗口时，浏览器不一定补发 node:pointerleave，
 *  hover-activate 的 inactive 状态会残留。这里兜底清空 hover 态并收起 tooltip。 */
function clearHover() {
  if (!g) return
  try {
    const ids: string[] = [
      ...(g.getNodeData?.() ?? []).map((d: any) => d.id),
      ...(g.getEdgeData?.() ?? []).map((d: any) => d.id),
    ]
    const states: Record<string, string[]> = {}
    for (const id of ids) {
      const current: string[] = g.getElementState?.(id) ?? []
      states[id] = current.filter((s) => s !== 'hover' && s !== 'inactive')
    }
    if (ids.length) g.setElementState(states, false)
  } catch {
    /* 版本差异容忍 */
  }
  try {
    g.getPluginInstance?.('tooltip')?.hide?.()
  } catch {
    /* 版本差异容忍 */
  }
}

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
    if (fitTimer) {
      window.clearTimeout(fitTimer)
      fitTimer = null
    }
    g?.destroy()
    const validIds = new Set(props.nodes.map((n) => n.id))
    const edges = props.edges.filter((e) => validIds.has(e.source) && validIds.has(e.target))
    // 大图只保留高关联节点的常驻标签，其余靠悬停提示，避免标签糊成一片
    const autoLimit =
      props.nodes.length <= 20
        ? props.nodes.length
        : props.nodes.length <= 48
          ? 18
          : props.nodes.length <= 80
            ? 22
            : 26
    const labelLimit =
      props.labelLimit > 0 ? Math.min(props.labelLimit, props.nodes.length) : autoLimit
    const labelIds = new Set(
      [...props.nodes]
        .sort((a, b) => b.link_count - a.link_count)
        .slice(0, labelLimit)
        .map((n) => n.id),
    )
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
        show_label: labelIds.has(n.id),
      },
    }))
    const g6Edges = edges.map((e) => ({
      source: e.source,
      target: e.target,
      data: { type: e.type },
    }))
    // tooltip 用 id → 节点映射还原可读标题，避免把内部 id 展示给用户。
    const nodeById = new Map(props.nodes.map((n) => [n.id, n]))

    g = new GraphCtor({
      container: container.value,
      // 不在每次渲染时自动 fit：与手动 fit 叠加会把「相对缩放」重复应用，
      // 连点重新布局时视图会越放越大。由 fitGraph() 串行、幂等地统一处理。
      autoFit: false,
      padding: 24,
      layout: {
        type: 'd3-force',
        // 星图布局：更长的关系线 + 更大的节点间距，保证稀疏、不堆叠；
        // 斥力设有距离上限，避免孤立节点被甩出视野导致整体缩放过度。
        link: { distance: 170, strength: 0.38 },
        collide: { radius: 54, strength: 1 },
        manyBody: { strength: -150, distanceMax: 520 },
        centerStrength: 0.065,
        alphaDecay: 0.045,
        velocityDecay: 0.35,
      },
      node: {
        style: (d: any) => {
          const meta = d.data ?? {}
          const ratio = Math.min(meta.link_count ?? 0, MAX_COUNT) / MAX_COUNT
          const isMastery = props.mode === 'mastery'
          const size = isMastery ? 24 + ratio * 14 : 22 + ratio * 20 // 22..42
          const pal = isMastery
            ? masteryPalette(meta.mastery ?? 0, !!meta.weak)
            : (NODE_PALETTE[meta.page_type] ?? NODE_PALETTE.wiki)
          return {
            size,
            // 显式写 opacity：G6 在移除 inactive 态时依赖基础样式来复位，
            // 基础里没有该字段会导致压暗后无法恢复亮度。
            opacity: 1,
            // 节点始终绘制在关系边之上：悬停、选中和常态都不被线条盖住。
            zIndex: 100,
            // 线性渐变：左上亮 → 右下主色，像恒星的明暗面。
            fill: `linear-gradient(135deg, ${pal.light} 0%, ${pal.fill} 100%)`,
            stroke: isMastery && meta.weak
              ? WEAK_STROKE
              : isMastery && meta.due
                ? DUE_STROKE
                : isMastery
                  ? 'rgba(224,237,255,0.85)'
                  : NODE_STROKE,
            lineWidth: isMastery && meta.weak ? 2.5 : isMastery && meta.due ? 2 : isMastery ? 1.4 : 1.6,
            lineDash: isMastery && meta.due && !meta.weak ? [4, 3] : undefined,
            // 多层光晕：靠近节点亮、向外扩散，模拟星光。
            shadowColor: pal.glow,
            shadowBlur: isMastery ? 20 + (meta.mastery ?? 0) * 12 : 24,
            shadowOffsetX: 0,
            shadowOffsetY: 0,
            cursor: 'pointer',
            labelText: meta.show_label ? (meta.title ?? '') : '',
            labelFill: LABEL_COLOR,
            labelFontSize: 11,
            labelPlacement: 'bottom',
            labelFontWeight: 500,
            labelMaxWidth: 118,
            labelMaxLines: 1,
            labelBackground: true,
            labelBackgroundFill: 'rgba(8,13,30,0.66)',
            labelBackgroundRadius: 5,
            labelPadding: [2, 6, 2, 6],
            labelBackgroundStroke: 'rgba(148,163,184,0.16)',
            labelBackgroundLineWidth: 1,
          }
        },
        state: {
          hover: {
            lineWidth: 3,
            shadowBlur: 34,
            labelFill: '#ffffff',
            labelBackgroundFill: 'rgba(15,23,42,0.9)',
          },
          selected: { lineWidth: 3.5, shadowBlur: 38 },
          // 悬停时其余星点压暗但仍可辨认，避免整片消失成「鬼影」。
          inactive: { opacity: 0.32, shadowColor: 'transparent', shadowBlur: 0 },
        },
      },
      edge: {
        style: (d: any) => {
          const style = edgeStyleOf(String(d.data?.type ?? 'reference'))
          return {
            stroke: style.stroke,
            zIndex: 1,
            lineWidth: style.width,
            lineDash: style.dash,
            // 星图用「星座连线」而非流程箭头：去掉箭头后线条更轻、更稀疏。
            endArrow: false,
            startArrow: false,
            lineAppendWidth: 10, // 更易点击
            strokeOpacity: style.opacity,
            // 极淡的同色辉光，让连线像星光而不是表格边框。
            shadowColor: style.stroke,
            shadowBlur: 4,
            shadowOffsetX: 0,
            shadowOffsetY: 0,
            labelText: '',
          }
        },
        state: {
          hover: {
            stroke: EDGE_HOVER,
            lineWidth: 1.8,
            strokeOpacity: 1,
            shadowBlur: 8,
            labelText: '',
          },
          inactive: { strokeOpacity: 0.14 },
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
        {
          type: 'hover-activate',
          degree: 1,
          state: 'hover',
          inactiveState: 'inactive',
          // 悬停节点时显式置顶，避免高亮关系边压住节点与标签。
          onHover: (evt: any) => {
            if (evt?.targetType !== 'node') return
            const id = evt?.target?.id
            if (id) {
              g?.frontElement?.(id)?.catch?.(() => {})
            }
          },
        },
      ],
      plugins: [
        {
          type: 'tooltip',
          // 右侧垂直居中：不会像 top-right 那样整块悬在指针上方，
          // 节点靠近画布上沿时也不会被 overflow-hidden 裁掉。
          position: 'right',
          offset: [16, 0],
          style: {
            '.tooltip': {
              'background-color': 'rgba(9, 14, 32, 0.96)',
              'box-shadow': '0 14px 38px rgba(2, 6, 23, 0.55)',
              'border-radius': '12px',
              color: '#cbd5e1',
              border: '1px solid rgba(148, 163, 184, 0.22)',
              'backdrop-filter': 'blur(12px)',
              padding: '10px 12px',
              // 去掉组件默认的 left/top 0.4s 缓动，避免弹窗「追不上」鼠标。
              transition: 'visibility 0.15s ease',
            },
            '.tooltip-title': { color: '#f1f5f9' },
            '.tooltip-list-item-marker': { display: 'none' },
          },
          // 注意：G6 v5 的第二个参数才是元素数据；event.target 只有 id。
          // 之前从 event.target.data 取标题，取不到就回退成内部 UUID，才出现「一堆 id」。
          getContent: (_evt: any, items: any[]) => {
            const item = items?.[0]
            if (!item) return ''
            const isEdge = item.source != null && item.target != null
            const meta = item.data ?? {}
            if (isEdge) {
              const linkType = String(meta.type ?? 'reference')
              const sourceId = typeof item.source === 'object' ? item.source?.id : item.source
              const targetId = typeof item.target === 'object' ? item.target?.id : item.target
              const sourceTitle = nodeById.get(String(sourceId))?.title
              const targetTitle = nodeById.get(String(targetId))?.title
              const ends =
                sourceTitle && targetTitle
                  ? `<div style="color:#94a3b8;margin-top:4px;font-size:10.5px;max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(sourceTitle)} → ${escapeHtml(targetTitle)}</div>`
                  : ''
              return `<div style="min-width:96px">
  <div style="font-size:11.5px;font-weight:600;color:#f1f5f9">${escapeHtml(edgeStyleOf(linkType).label)}</div>
  ${ends}
</div>`
            }
            const title = meta.title ?? nodeById.get(String(item.id))?.title ?? '未命名节点'
            const count = meta.link_count ?? 0
            const typeLabel = PAGE_TYPE_LABEL[meta.page_type] ?? meta.page_type ?? ''
            let detail = ''
            if (props.mode === 'mastery') {
              const mastery = Math.round((meta.mastery ?? 0) * 100)
              const flags = `${meta.weak ? ' · 薄弱' : ''}${meta.due ? ' · 待复习' : ''}${meta.content_updated ? ' · 内容已更新' : ''}`
              detail = `<div style="color:#94a3b8;margin-top:3px;font-size:10.5px">掌握度 ${mastery}%${flags}</div>
  <div style="margin-top:6px;height:3px;border-radius:999px;background:rgba(148,163,184,0.22);overflow:hidden">
    <div style="height:100%;width:${mastery}%;border-radius:999px;background:linear-gradient(90deg,#60a5fa,#e0edff)"></div>
  </div>`
            } else {
              detail = `<div style="color:#94a3b8;margin-top:3px;font-size:10.5px">${escapeHtml(typeLabel)} · 关联 ${count} 条</div>`
            }
            return `<div style="max-width:230px">
  <div style="font-size:12.5px;font-weight:600;color:#f8fafc;line-height:1.4">${escapeHtml(title)}</div>
  ${detail}
  <div style="color:#64748b;margin-top:5px;font-size:9.5px">点击查看</div>
</div>`
          },
        },
      ],
      animation: false,
    })

    // 力导向布局收敛后再应用手动拖拽位置，并让整张图回到视野内
    g.on('afterlayout', () => {
      void applySavedPositions().then(() => fitGraph())
    })
    g.setData({ nodes: g6Nodes, edges: g6Edges })
    await g.render()
    await applySavedPositions()
    fitGraph()
    scheduleFit()
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

/** 适配视野：使用「绝对缩放 + 居中」而不是 G6 的相对 fitView。
 *  fitView 按当前变换计算相对比例，连点重新布局会不断叠乘、越放越大；
 *  zoomTo 直接设定绝对比例，重复调用结果稳定。
 *  同时合并并发请求，保证最后一次布局收敛后的尺寸生效。 */
let fitQueued = false
let fitChain: Promise<void> = Promise.resolve()
function fitGraph() {
  if (!g?.zoomTo || fitQueued) return
  fitQueued = true
  fitChain = fitChain
    .then(async () => {
      fitQueued = false
      if (!g?.getCanvas) return
      const canvas = g.getCanvas()
      const [width, height] = canvas.getSize()
      const bounds = canvas.getBounds()
      if (!bounds?.max || !bounds?.min) return
      const bw = Number(bounds.max[0]) - Number(bounds.min[0])
      const bh = Number(bounds.max[1]) - Number(bounds.min[1])
      if (!(bw > 0) || !(bh > 0) || !width || !height) return
      const pad = 40
      const scale = Math.min((width - pad * 2) / bw, (height - pad * 2) / bh)
      if (!Number.isFinite(scale) || scale <= 0) return
      const [minZoom, maxZoom] = (g.getZoomRange?.() as [number, number]) ?? [0.01, 10]
      const zoom = Math.max(minZoom, Math.min(maxZoom, scale))
      await g.zoomTo(zoom)
      await g.fitCenter?.()
    })
    .catch(() => {
      fitQueued = false
    })
}

function zoomBy(ratio: number) {
  try { g?.zoomBy?.(ratio) } catch { /* 版本差异容忍 */ }
}

/** 重新布局：清除手动位置并整图重建。
 *  不直接 g.layout() 反复加热 d3-force——孤立节点会在每次加热后被斥力
 *  推得更远，连点几次后布局范围越来越大、视图越缩越小。
 *  重建则从同一初始状态开始，多次点击得到稳定结果。 */
function layout() {
  const key = positionsKey()
  if (key) {
    try {
      localStorage.removeItem(key)
    } catch {
      /* 忽略 */
    }
  }
  void createGraph()
}

let ro: ResizeObserver | null = null

onMounted(async () => {
  await loadG6()
  await nextTick()
  await createGraph()
  if (container.value) {
    container.value.addEventListener('pointerleave', clearHover)
    window.addEventListener('blur', clearHover)
  }
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
  container.value?.removeEventListener('pointerleave', clearHover)
  window.removeEventListener('blur', clearHover)
  if (fitTimer) {
    window.clearTimeout(fitTimer)
    fitTimer = null
  }
  try { g?.destroy() } catch { /* noop */ }
  g = null
})

defineExpose({ layout, fit: fitGraph, zoomBy })
</script>

<template>
  <div ref="container" class="w-full h-full min-h-0" />
</template>