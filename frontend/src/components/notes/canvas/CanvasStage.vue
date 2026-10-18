<script setup lang="ts">
/**
 * 画布编辑舞台：
 * - SVG 世界坐标渲染，支持平移 / 缩放 / 框选 / 多选拖动 / 缩放节点；
 * - 箭头连线吸附到节点四边（智能粘连），节点移动时连线跟随；
 * - 拖动时与其它节点做边缘/中心对齐吸附并显示辅助线；
 * - 主题、内置模板、文本双击编辑、撤销重做。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import {
  DEFAULT_FONT_SIZE,
  GRID_SIZE,
  NETWORK_KINDS,
  TONES,
  anchorPoint,
  boundsOf,
  facingSide,
  makeEdge,
  makeNode,
  newId,
  nodeCenter,
  type CanvasDoc,
  type CanvasEdge,
  type CanvasNetworkKind,
  type CanvasNode,
  type CanvasShape,
  type CanvasSide,
  type CanvasThemeId,
  type CanvasTool,
  type CanvasTone,
} from './types'
import { THEMES, isDark, themeOf, toneStyle } from './themes'
import { CANVAS_TEMPLATES, applyTemplate, type CanvasTemplate } from './templates'

const props = defineProps<{ modelValue: CanvasDoc }>()
const emit = defineEmits<{
  (e: 'update:modelValue', doc: CanvasDoc): void
  (e: 'change'): void
}>()

const doc = computed(() => props.modelValue)
const theme = computed(() => themeOf(doc.value.theme))
const dark = computed(() => isDark(theme.value))
const vp = computed(() => doc.value.viewport)
const nodeMap = computed(() => new Map(doc.value.nodes.map((node) => [node.id, node])))

const host = ref<HTMLElement | null>(null)
const size = ref({ w: 800, h: 600 })
const tool = ref<CanvasTool>('select')
const selectedNodes = ref<string[]>([])
const selectedEdge = ref<string | null>(null)
const hoverNode = ref<string | null>(null)
/**
 * 指针捕获后，click / dblclick 的 target 会被重定向到舞台容器，
 * 节点 <g> 上收不到双击；这里记录按下时命中的节点，供舞台双击处理。
 */
const lastPointerNodeId = ref<string | null>(null)
const spaceDown = ref(false)
const guideLines = ref<Array<{ x1: number; y1: number; x2: number; y2: number }>>([])
const marquee = ref<{ x: number; y: number; w: number; h: number } | null>(null)
const connectPreview = ref<{
  x1: number
  y1: number
  x2: number
  y2: number
  targetId: string | null
  targetSide: CanvasSide | null
} | null>(null)
const templateOpen = ref(false)
const pendingTemplate = ref<CanvasTemplate | null>(null)
const templateConfirmOpen = ref(false)

// ---------- 文本编辑 ----------
const editingId = ref<string | null>(null)
const editingText = ref('')
const editEl = ref<HTMLTextAreaElement | null>(null)

const editingNode = computed(() =>
  editingId.value ? nodeMap.value.get(editingId.value) ?? null : null,
)
const editStyle = computed(() => {
  const node = editingNode.value
  if (!node) return {}
  const tone = toneStyle(theme.value, node.tone)
  const engineering = node.shape === 'uml' || node.shape === 'table'
  const header = node.shape === 'uml' ? 34 : node.shape === 'table' ? 32 : 0
  return {
    left: `${vp.value.x + node.x * vp.value.zoom}px`,
    top: `${vp.value.y + node.y * vp.value.zoom}px`,
    width: `${node.w * vp.value.zoom}px`,
    height: `${node.h * vp.value.zoom}px`,
    padding: `${(engineering ? header + 6 : 8) * vp.value.zoom}px ${12 * vp.value.zoom}px`,
    fontSize: `${(engineering ? (node.fontSize ?? DEFAULT_FONT_SIZE) - 2 : (node.fontSize ?? DEFAULT_FONT_SIZE)) * vp.value.zoom}px`,
    lineHeight: '1.45',
    fontWeight: node.bold ? '600' : '400',
    textAlign: engineering ? 'left' : node.align === 'left' ? 'left' : 'center',
    color: tone.text,
    background: tone.fill,
    borderColor: theme.value.selection,
    borderRadius:
      node.shape === 'round' ? `${999 * vp.value.zoom}px` : `${12 * vp.value.zoom}px`,
  } as Record<string, string>
})

async function beginEdit(node: CanvasNode, selectAll = false) {
  selectedNodes.value = [node.id]
  selectedEdge.value = null
  editingId.value = node.id
  editingText.value = node.text
  await nextTick()
  const el = editEl.value
  if (!el) return
  el.focus()
  if (selectAll) el.select()
  else el.setSelectionRange(el.value.length, el.value.length)
}

function commitEdit() {
  const id = editingId.value
  if (!id) return
  editingId.value = null
  const node = nodeMap.value.get(id)
  if (!node) return
  const text = editingText.value
  if (node.text === text) return
  pushHistory()
  node.text = text
  changed()
}

function cancelEdit() {
  editingId.value = null
}

function onDblClick() {
  if (editingId.value || tool.value !== 'select') return
  const id = lastPointerNodeId.value
  if (!id) return
  const node = nodeMap.value.get(id)
  if (node) void beginEdit(node)
}

// ---------- 历史 ----------
const history = ref<string[]>([])
const future = ref<string[]>([])
const canUndo = computed(() => history.value.length > 0)
const canRedo = computed(() => future.value.length > 0)

function snapshot() {
  return JSON.stringify({
    theme: doc.value.theme,
    grid: doc.value.grid,
    snap: doc.value.snap,
    nodes: doc.value.nodes,
    edges: doc.value.edges,
  })
}

function pushHistory() {
  history.value.push(snapshot())
  if (history.value.length > 80) history.value.shift()
  future.value = []
}

function restore(json: string) {
  try {
    const data = JSON.parse(json)
    doc.value.theme = data.theme ?? doc.value.theme
    doc.value.grid = data.grid !== false
    doc.value.snap = data.snap === true
    doc.value.nodes = Array.isArray(data.nodes) ? data.nodes : []
    doc.value.edges = Array.isArray(data.edges) ? data.edges : []
  } catch {
    return
  }
  selectedNodes.value = selectedNodes.value.filter((id) => nodeMap.value.has(id))
  if (selectedEdge.value && !doc.value.edges.some((e) => e.id === selectedEdge.value)) {
    selectedEdge.value = null
  }
  changed()
}

function undo() {
  const last = history.value.pop()
  if (!last) return
  future.value.push(snapshot())
  restore(last)
}

function redo() {
  const next = future.value.pop()
  if (!next) return
  history.value.push(snapshot())
  restore(next)
}

function changed() {
  emit('update:modelValue', props.modelValue)
  emit('change')
}

// ---------- 坐标 ----------
function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function localPoint(event: { clientX: number; clientY: number }) {
  const el = host.value
  if (!el) return { x: 0, y: 0 }
  const rect = el.getBoundingClientRect()
  const scale = uiScale()
  return { x: (event.clientX - rect.left) / scale, y: (event.clientY - rect.top) / scale }
}

function toWorld(event: { clientX: number; clientY: number }) {
  const local = localPoint(event)
  return { x: (local.x - vp.value.x) / vp.value.zoom, y: (local.y - vp.value.y) / vp.value.zoom }
}

const transform = computed(
  () => `translate(${vp.value.x} ${vp.value.y}) scale(${vp.value.zoom})`,
)

// ---------- 选择 ----------
const selectedNodeObjs = computed(() =>
  selectedNodes.value.map((id) => nodeMap.value.get(id)).filter((n): n is CanvasNode => !!n),
)
const singleSelectedNode = computed(() =>
  selectedNodeObjs.value.length === 1 ? selectedNodeObjs.value[0] : null,
)
const selectedEdgeObj = computed(
  () => (selectedEdge.value ? doc.value.edges.find((e) => e.id === selectedEdge.value) ?? null : null),
)
const hasSelection = computed(() => selectedNodes.value.length > 0 || !!selectedEdge.value)

function isSelected(id: string) {
  return selectedNodes.value.includes(id)
}

function selectNode(id: string, additive = false) {
  if (additive) {
    selectedNodes.value = selectedNodes.value.includes(id)
      ? selectedNodes.value.filter((x) => x !== id)
      : [...selectedNodes.value, id]
  } else {
    selectedNodes.value = [id]
  }
  selectedEdge.value = null
}

function selectAllNodes() {
  selectedNodes.value = doc.value.nodes.map((n) => n.id)
  selectedEdge.value = null
}

function clearSelection() {
  selectedNodes.value = []
  selectedEdge.value = null
}

// ---------- 命中测试 ----------
function hitNode(point: { x: number; y: number }, exclude?: string | null): CanvasNode | null {
  for (let i = doc.value.nodes.length - 1; i >= 0; i -= 1) {
    const node = doc.value.nodes[i]
    if (exclude && node.id === exclude) continue
    if (
      point.x >= node.x - 4 &&
      point.x <= node.x + node.w + 4 &&
      point.y >= node.y - 4 &&
      point.y <= node.y + node.h + 4
    ) {
      return node
    }
  }
  return null
}

function nearestSide(node: CanvasNode, point: { x: number; y: number }): CanvasSide {
  const sides: CanvasSide[] = ['top', 'right', 'bottom', 'left']
  let best: CanvasSide = 'right'
  let bestDist = Infinity
  for (const side of sides) {
    const p = anchorPoint(node, side)
    const dist = (p.x - point.x) ** 2 + (p.y - point.y) ** 2
    if (dist < bestDist) {
      bestDist = dist
      best = side
    }
  }
  return best
}

// ---------- 指针交互 ----------
type Interaction =
  | { mode: 'pan'; start: { x: number; y: number }; vp: { x: number; y: number }; moved: boolean }
  | { mode: 'marquee'; start: { x: number; y: number }; additive: boolean }
  | {
      mode: 'move'
      start: { x: number; y: number }
      origins: Map<string, { x: number; y: number }>
      pushed: boolean
      moved: boolean
    }
  | {
      mode: 'resize'
      start: { x: number; y: number }
      handle: string
      nodeId: string
      origin: { x: number; y: number; w: number; h: number }
      pushed: boolean
    }
  | {
      mode: 'connect'
      start: { x: number; y: number }
      fromId: string
      fromSide: CanvasSide
    }
  | {
      mode: 'edge-end'
      edgeId: string
      end: 'from' | 'to'
      start: { x: number; y: number }
      pushed: boolean
      moved: boolean
    }

const interaction = ref<Interaction | null>(null)

const cursor = computed(() => {
  if (interaction.value?.mode === 'pan') return 'grabbing'
  if (spaceDown.value || tool.value === 'hand') return 'grab'
  if (tool.value === 'select') return 'default'
  if (tool.value === 'arrow') return 'crosshair'
  return 'copy'
})

const CURVE_OPTIONS = [
  { value: 'straight', label: '直线' },
  { value: 'orthogonal', label: '折线' },
  { value: 'bezier', label: '曲线' },
] as const
const ARROW_OPTIONS = [
  { value: 'none', label: '无箭头' },
  { value: 'end', label: '单箭头' },
  { value: 'both', label: '双箭头' },
] as const

function blurTarget(event: KeyboardEvent) {
  ;(event.target as HTMLInputElement | null)?.blur()
}

const TOOLS: Array<{ key: CanvasTool; icon: string; label: string; keyHint: string }> = [
  { key: 'select', icon: 'cursor', label: '选择', keyHint: 'V' },
  { key: 'hand', icon: 'hand', label: '平移', keyHint: 'H' },
  { key: 'rect', icon: 'square', label: '矩形', keyHint: 'R' },
  { key: 'ellipse', icon: 'circle', label: '椭圆', keyHint: 'O' },
  { key: 'diamond', icon: 'diamond', label: '判断', keyHint: 'D' },
  { key: 'text', icon: 'type', label: '文本', keyHint: 'T' },
  { key: 'sticky', icon: 'note', label: '便签', keyHint: 'S' },
  { key: 'uml', icon: 'code', label: 'UML 类', keyHint: 'C' },
  { key: 'table', icon: 'table', label: '库表', keyHint: 'B' },
  { key: 'arrow', icon: 'arrowUpRight', label: '连线', keyHint: 'A' },
]

const NETWORK_ITEMS: Array<{
  kind: CanvasNetworkKind
  icon: string
  label: string
  desc: string
  text: string
  tone: CanvasTone
}> = [
  { kind: 'cloud', icon: 'cloud', label: '云 / 互联网', desc: '公网入口', text: '互联网\nInternet', tone: 'accent' },
  { kind: 'server', icon: 'server', label: '服务器', desc: '计算节点', text: '应用服务器', tone: 'green' },
  { kind: 'database', icon: 'database', label: '数据库', desc: '关系型数据库', text: '数据库\nPostgreSQL', tone: 'green' },
  { kind: 'router', icon: 'router', label: '路由器 / 负载均衡', desc: '流量分发', text: '负载均衡\nNginx', tone: 'violet' },
  { kind: 'firewall', icon: 'firewall', label: '防火墙', desc: '安全边界', text: '防火墙\nWAF', tone: 'rose' },
  { kind: 'client', icon: 'monitor', label: '客户端', desc: '浏览器 / 终端', text: '客户端\nBrowser', tone: 'neutral' },
  { kind: 'switch', icon: 'switch', label: '交换机', desc: '二层网络', text: '交换机\nL2 Switch', tone: 'neutral' },
  { kind: 'storage', icon: 'storage', label: '对象存储', desc: '文件与备份', text: '对象存储\nMinIO', tone: 'amber' },
]
const NETWORK_KIND_SET = new Set<CanvasNetworkKind>(NETWORK_KINDS)

const SHAPE_LABELS: Record<CanvasShape, string> = {
  rect: '矩形',
  round: '圆角矩形',
  ellipse: '椭圆',
  diamond: '判断',
  text: '文本',
  sticky: '便签',
  uml: 'UML 类',
  table: '数据表',
  network: '网络图元',
}

function nodeLabel(node: CanvasNode): string {
  const first = node.text.split('\n').map((s) => s.trim()).find(Boolean)
  if (first) return first
  if (node.shape === 'network') {
    return NETWORK_ITEMS.find((item) => item.kind === node.variant)?.label ?? SHAPE_LABELS.network
  }
  return SHAPE_LABELS[node.shape]
}

function setTool(next: CanvasTool) {
  tool.value = next
  connectPreview.value = null
  if (next !== 'select') guideLines.value = []
  if (editingId.value) commitEdit()
}

function createShape(shape: CanvasShape, point: { x: number; y: number }) {
  const tone: CanvasTone | undefined =
    shape === 'sticky' ? 'amber' : shape === 'text' ? 'neutral' : 'neutral'
  const text =
    shape === 'sticky'
      ? '双击输入'
      : shape === 'text'
        ? '文本'
        : shape === 'uml'
          ? 'ClassName\n- field: type\n+ method(): return'
          : shape === 'table'
            ? 'table_name\nPK id BIGINT\nname VARCHAR(100)\ncreated_at TIMESTAMPTZ'
            : ''
  const node = makeNode(shape, point.x, point.y, text, { tone })
  node.x -= node.w / 2
  node.y -= node.h / 2
  if (doc.value.snap) {
    node.x = Math.round(node.x / GRID_SIZE) * GRID_SIZE
    node.y = Math.round(node.y / GRID_SIZE) * GRID_SIZE
  }
  pushHistory()
  doc.value.nodes.push(node)
  selectNode(node.id)
  setTool('select')
  changed()
  if (shape === 'text' || shape === 'sticky' || shape === 'uml' || shape === 'table') {
    void beginEdit(node, shape !== 'sticky')
  }
}

/** 从工具条下拉放置一个网络图元（落在当前视口中心）。 */
function addNetworkNode(kind: CanvasNetworkKind) {
  if (!NETWORK_KIND_SET.has(kind)) return
  const item = NETWORK_ITEMS.find((entry) => entry.kind === kind)
  const center = {
    x: (size.value.w / 2 - vp.value.x) / vp.value.zoom,
    y: (size.value.h / 2 - vp.value.y) / vp.value.zoom,
  }
  const node = makeNode('network', center.x, center.y, item?.text ?? '', {
    variant: kind,
    tone: item?.tone ?? 'neutral',
  })
  node.x -= node.w / 2
  node.y -= node.h / 2
  if (doc.value.snap) {
    node.x = Math.round(node.x / GRID_SIZE) * GRID_SIZE
    node.y = Math.round(node.y / GRID_SIZE) * GRID_SIZE
  }
  pushHistory()
  doc.value.nodes.push(node)
  selectNode(node.id)
  changed()
}

function onPointerDown(event: PointerEvent) {
  const target = event.target as Element | null
  if (target?.closest?.('.canvas-ui')) return
  if (event.button !== 0 && event.button !== 1) return

  const point = toWorld(event)
  const local = localPoint(event)
  const nodeEl = target?.closest?.('[data-node-id]') as Element | null
  const edgeEl = target?.closest?.('[data-edge-id]') as Element | null
  const edgeEndEl = target?.closest?.('[data-edge-end]') as Element | null
  const handleEl = target?.closest?.('[data-handle]') as Element | null

  lastPointerNodeId.value = nodeEl?.getAttribute('data-node-id') ?? null
  host.value?.setPointerCapture?.(event.pointerId)
  event.preventDefault()
  if (editingId.value) commitEdit()

  const startPan = () => {
    interaction.value = {
      mode: 'pan',
      start: local,
      vp: { x: vp.value.x, y: vp.value.y },
      moved: false,
    }
  }

  if (event.button === 1 || tool.value === 'hand' || spaceDown.value) {
    startPan()
    return
  }

  const nodeId = nodeEl?.getAttribute('data-node-id') ?? null

  if (handleEl && nodeId) {
    const node = nodeMap.value.get(nodeId)
    if (!node) return
    interaction.value = {
      mode: 'resize',
      start: point,
      handle: handleEl.getAttribute('data-handle') ?? 'se',
      nodeId,
      origin: { x: node.x, y: node.y, w: node.w, h: node.h },
      pushed: false,
    }
    return
  }

  if (tool.value === 'arrow') {
    if (!nodeId) return
    const node = nodeMap.value.get(nodeId)
    if (!node) return
    const side = nearestSide(node, point)
    const anchor = anchorPoint(node, side)
    interaction.value = { mode: 'connect', start: point, fromId: nodeId, fromSide: side }
    connectPreview.value = {
      x1: anchor.x,
      y1: anchor.y,
      x2: point.x,
      y2: point.y,
      targetId: null,
      targetSide: null,
    }
    return
  }

  if (tool.value !== 'select') {
    createShape(tool.value as CanvasShape, point)
    return
  }

  if (edgeEndEl) {
    const edgeId = edgeEndEl.getAttribute('data-edge-id') ?? ''
    const end = edgeEndEl.getAttribute('data-edge-end')
    if ((end === 'from' || end === 'to') && doc.value.edges.some((edge) => edge.id === edgeId)) {
      selectedEdge.value = edgeId
      selectedNodes.value = []
      interaction.value = {
        mode: 'edge-end',
        edgeId,
        end,
        start: point,
        pushed: false,
        moved: false,
      }
      return
    }
  }

  if (edgeEl) {
    selectedEdge.value = edgeEl.getAttribute('data-edge-id')
    selectedNodes.value = []
    return
  }

  if (nodeId) {
    const clicked = nodeMap.value.get(nodeId)
    if (!clicked) return
    const additive = event.shiftKey
    if (additive) {
      selectNode(nodeId, true)
      return
    }
    if (!isSelected(nodeId)) selectNode(nodeId)
    const origins = new Map<string, { x: number; y: number }>()
    for (const id of selectedNodes.value) {
      const node = nodeMap.value.get(id)
      if (node) origins.set(id, { x: node.x, y: node.y })
    }
    interaction.value = { mode: 'move', start: point, origins, pushed: false, moved: false }
    return
  }

  if (!event.shiftKey) clearSelection()
  interaction.value = { mode: 'marquee', start: point, additive: event.shiftKey }
  marquee.value = { x: point.x, y: point.y, w: 0, h: 0 }
}

function onPointerMove(event: PointerEvent) {
  const point = toWorld(event)
  const it = interaction.value
  if (!it) {
    const node = hitNode(point)
    const next = node?.id ?? null
    if (next !== hoverNode.value) hoverNode.value = next
    return
  }

  if (it.mode === 'pan') {
    const local = localPoint(event)
    it.moved = it.moved || Math.abs(local.x - it.start.x) + Math.abs(local.y - it.start.y) > 0.5
    vp.value.x = it.vp.x + (local.x - it.start.x)
    vp.value.y = it.vp.y + (local.y - it.start.y)
    return
  }

  if (it.mode === 'marquee') {
    const x = Math.min(it.start.x, point.x)
    const y = Math.min(it.start.y, point.y)
    marquee.value = { x, y, w: Math.abs(point.x - it.start.x), h: Math.abs(point.y - it.start.y) }
    return
  }

  if (it.mode === 'move') {
    const dx = point.x - it.start.x
    const dy = point.y - it.start.y
    if (!it.moved && Math.abs(dx) + Math.abs(dy) < 0.8) return
    it.moved = true
    if (!it.pushed) {
      pushHistory()
      it.pushed = true
    }
    const proposed = new Map<string, { x: number; y: number }>()
    for (const [id, origin] of it.origins) {
      let x = origin.x + dx
      let y = origin.y + dy
      if (doc.value.snap) {
        x = Math.round(x / GRID_SIZE) * GRID_SIZE
        y = Math.round(y / GRID_SIZE) * GRID_SIZE
      }
      proposed.set(id, { x, y })
    }
    const aligned = computeAlignment(new Set(it.origins.keys()), proposed)
    guideLines.value = aligned.lines
    for (const [id, p] of proposed) {
      const node = nodeMap.value.get(id)
      if (!node) continue
      node.x = p.x + aligned.dx
      node.y = p.y + aligned.dy
    }
    return
  }

  if (it.mode === 'resize') {
    if (!it.pushed) {
      pushHistory()
      it.pushed = true
    }
    const node = nodeMap.value.get(it.nodeId)
    if (!node) return
    const dx = point.x - it.start.x
    const dy = point.y - it.start.y
    let { x, y, w, h } = it.origin
    switch (it.handle) {
      case 'nw':
        x = it.origin.x + dx
        y = it.origin.y + dy
        w = it.origin.w - dx
        h = it.origin.h - dy
        break
      case 'ne':
        y = it.origin.y + dy
        w = it.origin.w + dx
        h = it.origin.h - dy
        break
      case 'sw':
        x = it.origin.x + dx
        w = it.origin.w - dx
        h = it.origin.h + dy
        break
      default:
        w = it.origin.w + dx
        h = it.origin.h + dy
    }
    if (w < 40) {
      if (it.handle.includes('w')) x = it.origin.x + it.origin.w - 40
      w = 40
    }
    if (h < 32) {
      if (it.handle.includes('n')) y = it.origin.y + it.origin.h - 32
      h = 32
    }
    if (doc.value.snap) {
      x = Math.round(x / GRID_SIZE) * GRID_SIZE
      y = Math.round(y / GRID_SIZE) * GRID_SIZE
      w = Math.round(w / GRID_SIZE) * GRID_SIZE
      h = Math.round(h / GRID_SIZE) * GRID_SIZE
    }
    node.x = x
    node.y = y
    node.w = w
    node.h = h
    return
  }

  if (it.mode === 'edge-end') {
    const edge = doc.value.edges.find((item) => item.id === it.edgeId)
    if (!edge) return
    if (
      !it.moved &&
      Math.abs(point.x - it.start.x) + Math.abs(point.y - it.start.y) < 0.8
    ) {
      return
    }
    it.moved = true
    if (!it.pushed) {
      pushHistory()
      it.pushed = true
    }
    const anchor = it.end === 'from' ? edge.from : edge.to
    const target = hitNode(point)
    if (target) {
      anchor.nodeId = target.id
      anchor.side = nearestSide(target, point)
      anchor.x = 0
      anchor.y = 0
    } else {
      const other = it.end === 'from' ? edge.to : edge.from
      const otherNode = other.nodeId ? nodeMap.value.get(other.nodeId) : null
      const otherPoint = otherNode
        ? nodeCenter(otherNode)
        : { x: other.x, y: other.y }
      anchor.nodeId = null
      anchor.x = point.x
      anchor.y = point.y
      anchor.side =
        Math.abs(point.x - otherPoint.x) >= Math.abs(point.y - otherPoint.y)
          ? otherPoint.x >= point.x
            ? 'right'
            : 'left'
          : otherPoint.y >= point.y
            ? 'bottom'
            : 'top'
    }
    return
  }

  if (it.mode === 'connect') {
    const target = hitNode(point, it.fromId)
    const targetSide = target ? nearestSide(target, point) : null
    let x2 = point.x
    let y2 = point.y
    if (target && targetSide) {
      const anchor = anchorPoint(target, targetSide)
      x2 = anchor.x
      y2 = anchor.y
    }
    connectPreview.value = {
      x1: connectPreview.value?.x1 ?? point.x,
      y1: connectPreview.value?.y1 ?? point.y,
      x2,
      y2,
      targetId: target?.id ?? null,
      targetSide,
    }
    if (target && target.id !== hoverNode.value) hoverNode.value = target.id
  }
}

function onPointerUp(event: PointerEvent) {
  const it = interaction.value
  if (!it) return
  interaction.value = null
  host.value?.releasePointerCapture?.(event.pointerId)

  if (it.mode === 'pan') {
    if (it.moved) changed()
    return
  }

  if (it.mode === 'marquee') {
    const box = marquee.value
    marquee.value = null
    if (!box) return
    const hits = doc.value.nodes.filter((node) => {
      return (
        node.x < box.x + box.w &&
        node.x + node.w > box.x &&
        node.y < box.y + box.h &&
        node.y + node.h > box.y
      )
    })
    const ids = hits.map((n) => n.id)
    selectedNodes.value = it.additive
      ? Array.from(new Set([...selectedNodes.value, ...ids]))
      : ids
    selectedEdge.value = null
    return
  }

  if (it.mode === 'move') {
    guideLines.value = []
    if (it.pushed) changed()
    return
  }

  if (it.mode === 'resize') {
    if (it.pushed) changed()
    return
  }

  if (it.mode === 'edge-end') {
    if (it.moved) changed()
    return
  }

  if (it.mode === 'connect') {
    const preview = connectPreview.value
    connectPreview.value = null
    const target = preview?.targetId ? nodeMap.value.get(preview.targetId) : null
    if (!target || target.id === it.fromId) return
    const from = nodeMap.value.get(it.fromId)
    if (!from) return
    const side = preview?.targetSide ?? nearestSide(target, nodeCenter(from))
    pushHistory()
    const edge = makeEdge(
      { nodeId: from.id, side: it.fromSide },
      { nodeId: target.id, side },
      { curve: 'orthogonal', arrow: 'end' },
    )
    doc.value.edges.push(edge)
    selectedEdge.value = edge.id
    selectedNodes.value = []
    tool.value = 'select'
    changed()
  }
}

function onWheel(event: WheelEvent) {
  const target = event.target as Element | null
  if (target?.closest?.('.canvas-ui')) return
  event.preventDefault()
  const local = localPoint(event)
  if (event.ctrlKey || event.metaKey) {
    zoomAt(local, Math.exp(-event.deltaY * 0.002))
  } else {
    const scale = uiScale()
    vp.value.x -= event.deltaX / scale
    vp.value.y -= event.deltaY / scale
    changed()
  }
}

// ---------- 对齐辅助 ----------
function computeAlignment(
  movingIds: Set<string>,
  proposed: Map<string, { x: number; y: number }>,
): { dx: number; dy: number; lines: Array<{ x1: number; y1: number; x2: number; y2: number }> } {
  const stationary = doc.value.nodes.filter((n) => !movingIds.has(n.id))
  if (!stationary.length) return { dx: 0, dy: 0, lines: [] }
  const originals = nodeMap.value
  const boxes = [...movingIds]
    .map((id) => {
      const node = originals.get(id)
      const p = proposed.get(id)
      return node && p ? { x: p.x, y: p.y, w: node.w, h: node.h } : null
    })
    .filter((b): b is { x: number; y: number; w: number; h: number } => !!b)
  if (!boxes.length) return { dx: 0, dy: 0, lines: [] }

  const threshold = 7 / vp.value.zoom
  const edgesX = (b: { x: number; w: number }) => [b.x, b.x + b.w / 2, b.x + b.w]
  const edgesY = (b: { y: number; h: number }) => [b.y, b.y + b.h / 2, b.y + b.h]

  let dx = 0
  let bestX = threshold + 1
  let guideX: number | null = null
  for (const m of boxes) {
    for (const me of edgesX(m)) {
      for (const s of stationary) {
        for (const se of edgesX(s)) {
          const delta = se - me
          if (Math.abs(delta) <= threshold && Math.abs(delta) < bestX) {
            bestX = Math.abs(delta)
            dx = delta
            guideX = se
          }
        }
      }
    }
  }

  const boxesX = boxes.map((b) => ({ ...b, x: b.x + dx }))
  let dy = 0
  let bestY = threshold + 1
  let guideY: number | null = null
  for (const m of boxesX) {
    for (const me of edgesY(m)) {
      for (const s of stationary) {
        for (const se of edgesY(s)) {
          const delta = se - me
          if (Math.abs(delta) <= threshold && Math.abs(delta) < bestY) {
            bestY = Math.abs(delta)
            dy = delta
            guideY = se
          }
        }
      }
    }
  }

  const lines: Array<{ x1: number; y1: number; x2: number; y2: number }> = []
  const boxesY = boxesX.map((b) => ({ ...b, y: b.y + dy }))
  if (guideX !== null) {
    const spans: Array<[number, number]> = [
      ...boxesY.map((b) => [b.y, b.y + b.h] as [number, number]),
      ...stationary
        .filter((s) => edgesX(s).some((v) => Math.abs(v - guideX!) < 0.5))
        .map((s) => [s.y, s.y + s.h] as [number, number]),
    ]
    lines.push({
      x1: guideX,
      y1: Math.min(...spans.map((s) => s[0])) - 28,
      x2: guideX,
      y2: Math.max(...spans.map((s) => s[1])) + 28,
    })
  }
  if (guideY !== null) {
    const spans: Array<[number, number]> = [
      ...boxesY.map((b) => [b.x, b.x + b.w] as [number, number]),
      ...stationary
        .filter((s) => edgesY(s).some((v) => Math.abs(v - guideY!) < 0.5))
        .map((s) => [s.x, s.x + s.w] as [number, number]),
    ]
    lines.push({
      x1: Math.min(...spans.map((s) => s[0])) - 28,
      y1: guideY,
      x2: Math.max(...spans.map((s) => s[1])) + 28,
      y2: guideY,
    })
  }
  return { dx, dy, lines }
}

// ---------- 渲染计算 ----------
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

interface NodeView {
  node: CanvasNode
  tone: ReturnType<typeof toneStyle>
  rx: number
  lines: string[]
  baselines: number[]
  textX: number
  anchor: 'middle' | 'start'
  isText: boolean
  engineering: boolean
  headerH: number
  title: string
  titleX: number
  titleBaseline: number
  titleAnchor: 'middle' | 'start'
  bodyFontSize: number
  bodyX: number
  bodyLines: string[]
  bodyBaselines: number[]
  rowLines: number[]
  tableRows: Array<{ key: string; text: string; textX: number }>
  centerX: number
  networkLines: string[]
  networkBaselines: number[]
  iconY: number
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

const nodeViews = computed<NodeView[]>(() =>
  doc.value.nodes.map((node) => {
    const tone = toneStyle(theme.value, node.tone)
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

    const engineering = node.shape === 'uml' || node.shape === 'table'
    const isTable = node.shape === 'table'
    const isUml = node.shape === 'uml'
    const headerH = isUml ? 34 : isTable ? 32 : 0
    const raw = (node.text || '').split('\n')
    const title = raw[0]?.trim() || (isUml ? 'ClassName' : 'table_name')
    const rawBody = raw.slice(1)
    while (rawBody.length && !rawBody[rawBody.length - 1].trim()) rawBody.pop()

    const bodyFontSize = Math.max(10, Math.min(14, fontSize - 3))
    const bodyX = node.x + 12
    let bodyLines: string[] = []
    let bodyBaselines: number[] = []
    let rowLines: number[] = []
    let tableRows: Array<{ key: string; text: string; textX: number }> = []

    if (isUml) {
      const rowH = bodyFontSize * 1.55
      const available = Math.max(0, node.h - headerH - 10)
      const maxRows = Math.max(1, Math.floor(available / rowH))
      // 支持 “- PK id: UUID” / “PK id: UUID” 两种写法，保留 UML 可见性符号。
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
      bodyLines = tableRows.map((row) => row.text)
      bodyBaselines = tableRows.map(
        (_, i) => node.y + headerH + 15 + i * rowH,
      )
    } else if (isTable) {
      const rowH = 20
      const available = Math.max(0, node.h - headerH - 6)
      const maxRows = Math.max(1, Math.floor(available / rowH))
      tableRows = rawBody.slice(0, maxRows).map((line) => {
        const match = line.match(/^\s*(PK|FK|UQ|IDX)\b[\s:：-]*(.*)$/i)
        if (match) {
          const key = match[1].toUpperCase()
          return {
            key,
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
        tableRows[tableRows.length - 1] = {
          key: '',
          text: '…',
          textX: node.x + 12,
        }
      }
      tableRows.forEach((_, i) => {
        bodyBaselines.push(node.y + headerH + rowH * i + rowH * 0.68)
        if (i > 0) rowLines.push(node.y + headerH + rowH * i)
      })
      bodyLines = tableRows.map((row) => row.text)
    }

    const networkLines = node.shape === 'network'
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
      node,
      tone,
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
      lines,
      baselines,
      textX: alignLeft ? node.x + 14 : node.x + node.w / 2,
      anchor: alignLeft ? 'start' : 'middle',
      isText: node.shape === 'text',
      engineering,
      headerH,
      title,
      titleX: isUml ? node.x + node.w / 2 : node.x + 12,
      titleBaseline: node.y + (isUml ? 22 : 21),
      titleAnchor: isUml ? 'middle' : 'start',
      bodyFontSize,
      bodyX,
      bodyLines,
      bodyBaselines,
      rowLines,
      tableRows,
      centerX: node.x + node.w / 2,
      networkLines,
      networkBaselines,
      iconY: node.y + 32,
    }
  }),
)

function diamondPoints(node: CanvasNode): string {
  const cx = node.x + node.w / 2
  const cy = node.y + node.h / 2
  return `${cx},${node.y} ${node.x + node.w},${cy} ${cx},${node.y + node.h} ${node.x},${cy}`
}

/** UML / 数据表的表头路径：仅上方两角圆角。 */
function headerPath(node: CanvasNode, rx: number, height: number): string {
  const x = node.x
  const y = node.y
  const w = node.w
  const r = Math.min(rx, height / 2, w / 2)
  return `M ${x + r} ${y} H ${x + w - r} Q ${x + w} ${y} ${x + w} ${y + r} V ${y + height} H ${x} V ${y + r} Q ${x} ${y} ${x + r} ${y} Z`
}

interface EdgeView {
  edge: CanvasEdge
  d: string
  color: string
  marker: string
  mid: { x: number; y: number }
  from: { x: number; y: number }
  to: { x: number; y: number }
  label: string
  labelW: number
  selected: boolean
}

function sideDir(side: CanvasSide) {
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

function polylineMid(points: Array<{ x: number; y: number }>) {
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

interface EdgeSides {
  fromSide: CanvasSide
  toSide: CanvasSide
}

/**
 * 解析每条连线实际使用的节点边。
 * auto 模式根据两节点中心的相对位置选择更自然的一侧。
 */
const edgeSideMap = computed<Map<string, EdgeSides>>(() => {
  const result = new Map<string, EdgeSides>()
  for (const edge of doc.value.edges) {
    const fromNode = edge.from.nodeId ? nodeMap.value.get(edge.from.nodeId) : null
    const toNode = edge.to.nodeId ? nodeMap.value.get(edge.to.nodeId) : null
    const fromBase = fromNode ? nodeCenter(fromNode) : { x: edge.from.x, y: edge.from.y }
    const toBase = toNode ? nodeCenter(toNode) : { x: edge.to.x, y: edge.to.y }
    const fromSide: CanvasSide = fromNode
      ? edge.from.side === 'auto'
        ? facingSide(fromNode, toBase)
        : edge.from.side
      : edge.from.side === 'auto'
        ? toBase.x >= fromBase.x
          ? 'right'
          : 'left'
        : edge.from.side
    const toSide: CanvasSide = toNode
      ? edge.to.side === 'auto'
        ? facingSide(toNode, fromBase)
        : edge.to.side
      : edge.to.side === 'auto'
        ? fromBase.x >= toBase.x
          ? 'right'
          : 'left'
        : edge.to.side
    result.set(edge.id, { fromSide, toSide })
  }
  return result
})

/**
 * 自适应端口：同一节点同一边上的多条连线沿边均分，避免全部挤在中点。
 * key = `${edgeId}:from|to`。
 */
const edgePorts = computed<Map<string, { index: number; count: number }>>(() => {
  const groups = new Map<string, string[]>()
  for (const edge of doc.value.edges) {
    const sides = edgeSideMap.value.get(edge.id)
    if (!sides) continue
    if (edge.from.nodeId) {
      const key = `${edge.from.nodeId}:${sides.fromSide}`
      groups.set(key, [...(groups.get(key) ?? []), `${edge.id}:from`])
    }
    if (edge.to.nodeId) {
      const key = `${edge.to.nodeId}:${sides.toSide}`
      groups.set(key, [...(groups.get(key) ?? []), `${edge.id}:to`])
    }
  }
  const result = new Map<string, { index: number; count: number }>()
  for (const entries of groups.values()) {
    entries.forEach((entry, index) => {
      result.set(entry, { index, count: entries.length })
    })
  }
  return result
})

function portPoint(
  node: CanvasNode,
  side: CanvasSide,
  edgeId: string,
  end: 'from' | 'to',
): { x: number; y: number } {
  // 菱形 / 椭圆的四条“边”其实是顶点或弧顶，沿包围盒均分会把锚点落到图形外。
  if (node.shape === 'diamond' || node.shape === 'ellipse') return anchorPoint(node, side)
  const port = edgePorts.value.get(`${edgeId}:${end}`)
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

function dedupePoints(points: Array<{ x: number; y: number }>) {
  return points.filter((point, index) => {
    if (!index) return true
    const prev = points[index - 1]
    return Math.abs(point.x - prev.x) > 0.5 || Math.abs(point.y - prev.y) > 0.5
  })
}

/** 折线圆角路径：直角转折改为二次贝塞尔，视觉更柔和。 */
function roundedPath(points: Array<{ x: number; y: number }>, radius = 12): string {
  const pts = dedupePoints(points)
  if (pts.length < 2) {
    return pts.length ? `M ${pts[0].x} ${pts[0].y}` : ''
  }
  let d = `M ${pts[0].x} ${pts[0].y}`
  for (let i = 1; i < pts.length - 1; i += 1) {
    const prev = pts[i - 1]
    const cur = pts[i]
    const next = pts[i + 1]
    const d1 = Math.hypot(cur.x - prev.x, cur.y - prev.y)
    const d2 = Math.hypot(next.x - cur.x, next.y - cur.y)
    const r = Math.min(radius, d1 / 2, d2 / 2)
    if (r < 1.5) {
      d += ` L ${cur.x} ${cur.y}`
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
    d += ` L ${before.x} ${before.y} Q ${cur.x} ${cur.y} ${after.x} ${after.y}`
  }
  const last = pts[pts.length - 1]
  d += ` L ${last.x} ${last.y}`
  return d
}

function edgeGeometry(edge: CanvasEdge): {
  d: string
  mid: { x: number; y: number }
  from: { x: number; y: number }
  to: { x: number; y: number }
} {
  const fromNode = edge.from.nodeId ? nodeMap.value.get(edge.from.nodeId) : null
  const toNode = edge.to.nodeId ? nodeMap.value.get(edge.to.nodeId) : null
  const sides = edgeSideMap.value.get(edge.id)
  const fromSide: CanvasSide = sides?.fromSide ?? 'right'
  const toSide: CanvasSide = sides?.toSide ?? 'left'
  const fromBase = fromNode ? nodeCenter(fromNode) : { x: edge.from.x, y: edge.from.y }
  const toBase = toNode ? nodeCenter(toNode) : { x: edge.to.x, y: edge.to.y }
  const p1 = fromNode ? portPoint(fromNode, fromSide, edge.id, 'from') : fromBase
  const p2 = toNode ? portPoint(toNode, toSide, edge.id, 'to') : toBase

  if (edge.curve === 'bezier') {
    const dx = Math.abs(p2.x - p1.x)
    const dy = Math.abs(p2.y - p1.y)
    const k = Math.max(36, Math.min(180, dx * 0.5 + dy * 0.15))
    const d1 = sideDir(fromSide)
    const d2 = sideDir(toSide)
    const c1 = { x: p1.x + d1.x * k, y: p1.y + d1.y * k }
    const c2 = { x: p2.x + d2.x * k, y: p2.y + d2.y * k }
    const mid = {
      x: (p1.x + 3 * c1.x + 3 * c2.x + p2.x) / 8,
      y: (p1.y + 3 * c1.y + 3 * c2.y + p2.y) / 8,
    }
    return {
      d: `M ${p1.x} ${p1.y} C ${c1.x} ${c1.y} ${c2.x} ${c2.y} ${p2.x} ${p2.y}`,
      mid,
      from: p1,
      to: p2,
    }
  }

  if (edge.curve === 'straight') {
    return {
      d: `M ${p1.x} ${p1.y} L ${p2.x} ${p2.y}`,
      mid: { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 },
      from: p1,
      to: p2,
    }
  }

  const off = 22
  const d1 = sideDir(fromSide)
  const d2 = sideDir(toSide)
  const a = { x: p1.x + d1.x * off, y: p1.y + d1.y * off }
  const b = { x: p2.x + d2.x * off, y: p2.y + d2.y * off }
  const points: Array<{ x: number; y: number }> = [p1, a]
  const horizontal1 = fromSide === 'left' || fromSide === 'right'
  const horizontal2 = toSide === 'left' || toSide === 'right'
  if (horizontal1 && horizontal2) {
    const dir1 = fromSide === 'right' ? 1 : -1
    const dir2 = toSide === 'right' ? 1 : -1
    if (dir1 === dir2) {
      // 两侧同向（例如都在节点右侧）：从外侧绕行，避免线穿过节点
      const outerX = dir1 > 0 ? Math.max(a.x, b.x) + 26 : Math.min(a.x, b.x) - 26
      points.push({ x: outerX, y: a.y }, { x: outerX, y: b.y })
    } else {
      const mx = (a.x + b.x) / 2
      points.push({ x: mx, y: a.y }, { x: mx, y: b.y })
    }
  } else if (!horizontal1 && !horizontal2) {
    const dir1 = fromSide === 'bottom' ? 1 : -1
    const dir2 = toSide === 'bottom' ? 1 : -1
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

const markerDefs = computed(() => {
  const defs: Array<{ id: string; fill: string }> = [
    { id: 'kiwi-arrow-default', fill: theme.value.edge },
  ]
  for (const tone of TONES) {
    defs.push({ id: `kiwi-arrow-${tone}`, fill: theme.value.tones[tone].stroke })
  }
  return defs
})

function markerUrl(edge: CanvasEdge): string {
  return `url(#kiwi-arrow-${edge.tone ?? 'default'})`
}

const edgeViews = computed<EdgeView[]>(() =>
  doc.value.edges.map((edge) => {
    const geo = edgeGeometry(edge)
    const label = (edge.label ?? '').trim()
    return {
      edge,
      d: geo.d,
      color:
        selectedEdge.value === edge.id
          ? theme.value.selection
          : edge.tone
            ? toneStyle(theme.value, edge.tone).stroke
            : theme.value.edge,
      marker: markerUrl(edge),
      mid: geo.mid,
      from: geo.from,
      to: geo.to,
      label,
      labelW: Math.max(28, Array.from(label).reduce((sum, ch) => sum + charWidth(ch, 11), 0) + 14),
      selected: selectedEdge.value === edge.id,
    }
  }),
)

const selectedEdgeView = computed(
  () => edgeViews.value.find((view) => view.selected) ?? null,
)

const anchorNodeId = computed(
  () => connectPreview.value?.targetId ?? hoverNode.value ?? singleSelectedNode.value?.id ?? null,
)
const ANCHOR_SIDES: CanvasSide[] = ['top', 'right', 'bottom', 'left']
const EDGE_ENDS = ['from', 'to'] as const

const HANDLE_CURSORS: Record<string, string> = {
  nw: 'nwse-resize',
  ne: 'nesw-resize',
  sw: 'nesw-resize',
  se: 'nwse-resize',
}

function handlesOf(node: CanvasNode) {
  const s = 9 / vp.value.zoom
  const half = s / 2
  return [
    { key: 'nw', x: node.x - half, y: node.y - half },
    { key: 'ne', x: node.x + node.w - half, y: node.y - half },
    { key: 'sw', x: node.x - half, y: node.y + node.h - half },
    { key: 'se', x: node.x + node.w - half, y: node.y + node.h - half },
  ].map((h) => ({ ...h, size: s, cursor: HANDLE_CURSORS[h.key] }))
}

// ---------- 缩放 / 视图 ----------
function clampZoom(value: number) {
  return Math.min(4, Math.max(0.2, value))
}

function zoomAt(local: { x: number; y: number }, factor: number) {
  const oldZoom = vp.value.zoom
  const next = clampZoom(oldZoom * factor)
  if (next === oldZoom) return
  vp.value.x = local.x - (local.x - vp.value.x) * (next / oldZoom)
  vp.value.y = local.y - (local.y - vp.value.y) * (next / oldZoom)
  vp.value.zoom = next
  changed()
}

function zoomBy(factor: number) {
  zoomAt({ x: size.value.w / 2, y: size.value.h / 2 }, factor)
}

function fit() {
  const nodes = doc.value.nodes
  if (!nodes.length) {
    vp.value.x = 96
    vp.value.y = 80
    vp.value.zoom = 1
    changed()
    return
  }
  const b = boundsOf(nodes)
  const padding = 90
  const zoom = clampZoom(
    Math.min(
      (size.value.w - padding * 2) / Math.max(1, b.w),
      (size.value.h - padding * 2) / Math.max(1, b.h),
      1.35,
    ),
  )
  vp.value.zoom = zoom
  vp.value.x = (size.value.w - b.w * zoom) / 2 - b.x * zoom
  vp.value.y = (size.value.h - b.h * zoom) / 2 - b.y * zoom
  changed()
}

// ---------- 编辑操作 ----------
function deleteSelection() {
  if (!hasSelection.value) return
  pushHistory()
  if (selectedNodes.value.length) {
    const ids = new Set(selectedNodes.value)
    doc.value.nodes = doc.value.nodes.filter((n) => !ids.has(n.id))
    doc.value.edges = doc.value.edges.filter(
      (e) => !(e.from.nodeId && ids.has(e.from.nodeId)) && !(e.to.nodeId && ids.has(e.to.nodeId)),
    )
  }
  if (selectedEdge.value) {
    doc.value.edges = doc.value.edges.filter((e) => e.id !== selectedEdge.value)
  }
  clearSelection()
  guideLines.value = []
  changed()
}

function duplicateSelection() {
  const nodes = selectedNodeObjs.value
  if (!nodes.length) return
  pushHistory()
  const idMap = new Map<string, string>()
  const clones = nodes.map((node) => {
    const clone: CanvasNode = { ...node, id: newId('n'), x: node.x + 28, y: node.y + 28 }
    idMap.set(node.id, clone.id)
    return clone
  })
  const ids = new Set(nodes.map((n) => n.id))
  const copiedEdges = doc.value.edges
    .filter(
      (e) =>
        e.from.nodeId &&
        e.to.nodeId &&
        ids.has(e.from.nodeId) &&
        ids.has(e.to.nodeId),
    )
    .map((e) => ({
      ...e,
      id: newId('e'),
      from: { ...e.from, nodeId: idMap.get(e.from.nodeId!) ?? null },
      to: { ...e.to, nodeId: idMap.get(e.to.nodeId!) ?? null },
    }))
  doc.value.nodes.push(...clones)
  doc.value.edges.push(...copiedEdges)
  selectedNodes.value = clones.map((n) => n.id)
  selectedEdge.value = null
  changed()
}

// ---------- 图层顺序 ----------
const layerNodes = computed(() => [...doc.value.nodes].reverse())

/** delta > 0 向顶层移动，delta < 0 向底层移动。 */
function moveLayer(id: string, delta: number) {
  const index = doc.value.nodes.findIndex((node) => node.id === id)
  const target = index + delta
  if (index < 0 || target < 0 || target >= doc.value.nodes.length) return
  pushHistory()
  const next = [...doc.value.nodes]
  ;[next[index], next[target]] = [next[target], next[index]]
  doc.value.nodes = next
  changed()
}

function bringForward() {
  const ids = new Set(selectedNodes.value)
  if (!ids.size) return
  const next = [...doc.value.nodes]
  for (let i = next.length - 2; i >= 0; i -= 1) {
    if (ids.has(next[i].id) && !ids.has(next[i + 1].id)) {
      ;[next[i], next[i + 1]] = [next[i + 1], next[i]]
    }
  }
  pushHistory()
  doc.value.nodes = next
  changed()
}

function sendBackward() {
  const ids = new Set(selectedNodes.value)
  if (!ids.size) return
  const next = [...doc.value.nodes]
  for (let i = 1; i < next.length; i += 1) {
    if (ids.has(next[i].id) && !ids.has(next[i - 1].id)) {
      ;[next[i], next[i - 1]] = [next[i - 1], next[i]]
    }
  }
  pushHistory()
  doc.value.nodes = next
  changed()
}

function bringToFront() {
  const ids = new Set(selectedNodes.value)
  if (!ids.size) return
  pushHistory()
  doc.value.nodes = [
    ...doc.value.nodes.filter((node) => !ids.has(node.id)),
    ...doc.value.nodes.filter((node) => ids.has(node.id)),
  ]
  changed()
}

function sendToBack() {
  const ids = new Set(selectedNodes.value)
  if (!ids.size) return
  pushHistory()
  doc.value.nodes = [
    ...doc.value.nodes.filter((node) => ids.has(node.id)),
    ...doc.value.nodes.filter((node) => !ids.has(node.id)),
  ]
  changed()
}

function setNodeTone(tone: CanvasTone) {
  const node = singleSelectedNode.value
  if (!node) return
  pushHistory()
  node.tone = tone
  changed()
}

function toggleBold() {
  const node = singleSelectedNode.value
  if (!node) return
  pushHistory()
  node.bold = !node.bold
  changed()
}

function bumpFont(delta: number) {
  const node = singleSelectedNode.value
  if (!node) return
  pushHistory()
  node.fontSize = Math.min(48, Math.max(9, (node.fontSize ?? DEFAULT_FONT_SIZE) + delta))
  changed()
}

function toggleAlign() {
  const node = singleSelectedNode.value
  if (!node) return
  pushHistory()
  node.align = node.align === 'left' ? 'center' : 'left'
  changed()
}

function setEdgeCurve(curve: CanvasEdge['curve']) {
  const edge = selectedEdgeObj.value
  if (!edge) return
  pushHistory()
  edge.curve = curve
  changed()
}

function setEdgeArrow(arrow: CanvasEdge['arrow']) {
  const edge = selectedEdgeObj.value
  if (!edge) return
  pushHistory()
  edge.arrow = arrow
  changed()
}

function toggleEdgeDashed() {
  const edge = selectedEdgeObj.value
  if (!edge) return
  pushHistory()
  edge.dashed = !edge.dashed
  changed()
}

function onEdgeLabelChange(event: Event) {
  const edge = selectedEdgeObj.value
  if (!edge) return
  const value = (event.target as HTMLInputElement).value
  if (value === (edge.label ?? '')) return
  pushHistory()
  edge.label = value
  changed()
}

function setTheme(id: CanvasThemeId) {
  if (doc.value.theme === id) return
  pushHistory()
  doc.value.theme = id
  changed()
}

function toggleGrid() {
  pushHistory()
  doc.value.grid = !doc.value.grid
  changed()
}

function toggleSnap() {
  pushHistory()
  doc.value.snap = !doc.value.snap
  changed()
}

/** 画布已有内容时先确认，避免误覆盖；空画布直接应用。 */
function requestTpl(template: CanvasTemplate) {
  if (doc.value.nodes.length || doc.value.edges.length) {
    pendingTemplate.value = template
    templateConfirmOpen.value = true
    return
  }
  applyTpl(template)
}

function confirmTplReplace() {
  const template = pendingTemplate.value
  pendingTemplate.value = null
  if (template) applyTpl(template)
}

function applyTpl(template: CanvasTemplate) {
  pushHistory()
  const next = applyTemplate(doc.value, template)
  doc.value.theme = next.theme
  doc.value.grid = next.grid
  doc.value.snap = next.snap
  doc.value.nodes = next.nodes
  doc.value.edges = next.edges
  clearSelection()
  templateOpen.value = false
  changed()
  void nextTick(() => fit())
}

function addEmptySticky() {
  const center = {
    x: (size.value.w / 2 - vp.value.x) / vp.value.zoom,
    y: (size.value.h / 2 - vp.value.y) / vp.value.zoom,
  }
  createShape('sticky', center)
}

/** 思维导图快捷操作：Tab 为选中节点创建子节点。 */
function addChildNode() {
  const parent = singleSelectedNode.value
  if (!parent) return
  const outgoing = doc.value.edges.filter((e) => e.from.nodeId === parent.id).length
  const node = makeNode(
    'round',
    parent.x + parent.w + 90,
    parent.y + outgoing * 96 - 16,
    '分支主题',
    { tone: 'neutral' },
  )
  pushHistory()
  doc.value.nodes.push(node)
  doc.value.edges.push(
    makeEdge(
      { nodeId: parent.id, side: 'right' },
      { nodeId: node.id, side: 'left' },
      { curve: 'bezier', arrow: 'none' },
    ),
  )
  selectNode(node.id)
  changed()
  void beginEdit(node, true)
}

// ---------- 键盘 ----------
function isTyping(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  if (!target) return false
  const tag = target.tagName
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    target.isContentEditable === true
  )
}

function onKeyDown(event: KeyboardEvent) {
  if (isTyping(event)) return
  const mod = event.ctrlKey || event.metaKey
  const key = event.key
  const lower = key.toLowerCase()

  if (key === ' ' || event.code === 'Space') {
    if (!event.repeat) spaceDown.value = true
    event.preventDefault()
    return
  }

  if (mod) {
    if (lower === 'z') {
      event.preventDefault()
      if (event.shiftKey) redo()
      else undo()
      return
    }
    if (lower === 'y') {
      event.preventDefault()
      redo()
      return
    }
    if (lower === 'd') {
      event.preventDefault()
      duplicateSelection()
      return
    }
    if (lower === 'a') {
      event.preventDefault()
      selectAllNodes()
      return
    }
    if (lower === 's') return
    if (key === '0') {
      event.preventDefault()
      fit()
      return
    }
    if (key === '=' || key === '+') {
      event.preventDefault()
      zoomBy(1.2)
      return
    }
    if (key === '-') {
      event.preventDefault()
      zoomBy(1 / 1.2)
      return
    }
    return
  }

  if (event.code === 'BracketRight') {
    event.preventDefault()
    if (event.shiftKey) bringToFront()
    else bringForward()
    return
  }
  if (event.code === 'BracketLeft') {
    event.preventDefault()
    if (event.shiftKey) sendToBack()
    else sendBackward()
    return
  }

  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault()
    deleteSelection()
    return
  }
  if (key === 'Escape') {
    connectPreview.value = null
    guideLines.value = []
    clearSelection()
    setTool('select')
    return
  }
  if (key === 'Enter') {
    if (singleSelectedNode.value) {
      event.preventDefault()
      void beginEdit(singleSelectedNode.value)
    }
    return
  }
  if (key === 'Tab') {
    if (singleSelectedNode.value) {
      event.preventDefault()
      addChildNode()
    }
    return
  }
  if (key.startsWith('Arrow')) {
    if (!selectedNodeObjs.value.length) return
    event.preventDefault()
    const step = event.shiftKey ? 10 : 1
    const dx = key === 'ArrowLeft' ? -step : key === 'ArrowRight' ? step : 0
    const dy = key === 'ArrowUp' ? -step : key === 'ArrowDown' ? step : 0
    pushHistory()
    for (const node of selectedNodeObjs.value) {
      node.x += dx
      node.y += dy
    }
    changed()
    return
  }

  const toolKeys: Record<string, CanvasTool> = {
    v: 'select',
    h: 'hand',
    r: 'rect',
    o: 'ellipse',
    d: 'diamond',
    t: 'text',
    s: 'sticky',
    c: 'uml',
    b: 'table',
    a: 'arrow',
  }
  if (toolKeys[lower]) {
    event.preventDefault()
    setTool(toolKeys[lower])
  }
}

function onKeyUp(event: KeyboardEvent) {
  if (event.key === ' ' || event.code === 'Space') spaceDown.value = false
}

function onBlurWindow() {
  spaceDown.value = false
}

// ---------- 生命周期 ----------
let observer: ResizeObserver | null = null

onMounted(() => {
  const el = host.value
  if (el) {
    size.value = { w: el.clientWidth || 800, h: el.clientHeight || 600 }
    observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (!rect) return
      size.value = { w: Math.max(1, rect.width), h: Math.max(1, rect.height) }
    })
    observer.observe(el)
    el.addEventListener('wheel', onWheel, { passive: false })
  }
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
  window.addEventListener('blur', onBlurWindow)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  host.value?.removeEventListener('wheel', onWheel)
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('keyup', onKeyUp)
  window.removeEventListener('blur', onBlurWindow)
})

defineExpose({ fit, undo, redo, zoomBy, addEmptySticky })
</script>

<template>
  <div
    ref="host"
    class="canvas-stage relative h-full w-full overflow-hidden select-none"
    :style="{ background: theme.bg, cursor }"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
    @dblclick="onDblClick"
    @contextmenu.prevent
  >
    <svg class="absolute inset-0 h-full w-full" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <pattern
          id="kiwi-canvas-grid"
          :width="GRID_SIZE"
          :height="GRID_SIZE"
          patternUnits="userSpaceOnUse"
        >
          <circle :cx="1.2" :cy="1.2" r="1.1" :fill="theme.gridStrong" />
        </pattern>
        <marker
          v-for="def in markerDefs"
          :id="def.id"
          :key="def.id"
          markerWidth="6"
          markerHeight="6"
          refX="5"
          refY="3"
          orient="auto-start-reverse"
          markerUnits="strokeWidth"
        >
          <path d="M0 0 L6 3 L0 6 Z" :fill="def.fill" />
        </marker>
      </defs>

      <g :transform="transform">
        <!-- 网格 -->
        <rect
          v-if="doc.grid"
          :x="-vp.x / vp.zoom"
          :y="-vp.y / vp.zoom"
          :width="size.w / vp.zoom"
          :height="size.h / vp.zoom"
          fill="url(#kiwi-canvas-grid)"
        />

        <!-- 连线 -->
        <g
          v-for="view in edgeViews"
          :key="view.edge.id"
          :data-edge-id="view.edge.id"
          class="canvas-edge"
        >
          <path
            :d="view.d"
            fill="none"
            :stroke="view.color"
            :stroke-width="view.selected ? 2.6 / vp.zoom : 1.6 / vp.zoom"
            :stroke-dasharray="view.edge.dashed ? `${7 / vp.zoom} ${6 / vp.zoom}` : undefined"
            :marker-end="view.edge.arrow !== 'none' ? view.marker : undefined"
            :marker-start="view.edge.arrow === 'both' ? view.marker : undefined"
            stroke-linejoin="round"
            stroke-linecap="round"
          />
          <path
            :d="view.d"
            fill="none"
            stroke="transparent"
            :stroke-width="Math.max(14 / vp.zoom, 10)"
            pointer-events="stroke"
            class="cursor-pointer"
          />
          <g v-if="view.label" pointer-events="none">
            <rect
              :x="view.mid.x - view.labelW / 2"
              :y="view.mid.y - 10 / vp.zoom"
              :width="view.labelW"
              :height="20 / vp.zoom"
              :rx="6 / vp.zoom"
              :fill="theme.edgeLabelBg"
              :stroke="theme.grid"
              :stroke-width="1 / vp.zoom"
            />
            <text
              :x="view.mid.x"
              :y="view.mid.y + 4 / vp.zoom"
              text-anchor="middle"
              :font-size="11 / vp.zoom"
              :fill="theme.edge"
              font-family="'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
            >
              {{ view.label }}
            </text>
          </g>
        </g>

        <!-- 节点 -->
        <g
          v-for="view in nodeViews"
          :key="view.node.id"
          :data-node-id="view.node.id"
          class="canvas-node"
        >
          <rect
            v-if="view.node.shape === 'text' && (hoverNode === view.node.id || isSelected(view.node.id))"
            :x="view.node.x"
            :y="view.node.y"
            :width="view.node.w"
            :height="view.node.h"
            :rx="8"
            fill="none"
            :stroke="theme.edge"
            :stroke-dasharray="`${4 / vp.zoom} ${4 / vp.zoom}`"
            :stroke-width="1 / vp.zoom"
            pointer-events="none"
          />

          <!-- UML 类 / 数据表 -->
          <template v-if="view.engineering">
            <rect
              :x="view.node.x"
              :y="view.node.y"
              :width="view.node.w"
              :height="view.node.h"
              :rx="view.rx"
              :fill="view.tone.fill"
              :stroke="view.tone.stroke"
              :stroke-width="1.5 / vp.zoom"
            />
            <path
              :d="headerPath(view.node, view.rx, view.headerH)"
              :fill="view.tone.stroke"
              fill-opacity="0.18"
              :stroke="view.tone.stroke"
              :stroke-width="1.2 / vp.zoom"
            />
            <text
              :x="view.titleX"
              :y="view.titleBaseline"
              :text-anchor="view.titleAnchor"
              :font-size="view.node.shape === 'uml' ? 14 : 12.8"
              font-weight="600"
              :fill="view.tone.text"
              font-family="'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
              pointer-events="none"
            >{{ view.title }}</text>
            <g
              v-if="view.node.shape === 'table'"
              :transform="`translate(${view.node.x + view.node.w - 24} ${view.node.y + 10})`"
              :stroke="view.tone.stroke"
              fill="none"
              :stroke-width="1 / vp.zoom"
              opacity="0.75"
              pointer-events="none"
            >
              <rect x="0" y="0" width="13" height="11" rx="1.5" />
              <line x1="0" y1="4" x2="13" y2="4" />
              <line x1="6.5" y1="0" x2="6.5" y2="11" />
            </g>

            <g
              v-if="view.node.shape === 'uml' && view.tableRows.length"
              pointer-events="none"
            >
              <g v-for="(row, rowIndex) in view.tableRows" :key="`uml-${rowIndex}`">
                <text
                  v-if="row.key"
                  :x="view.node.x + 12"
                  :y="view.bodyBaselines[rowIndex]"
                  :font-size="8.8"
                  font-weight="700"
                  :fill="view.tone.stroke"
                  font-family="'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
                >{{ row.key }}</text>
                <text
                  :x="row.textX"
                  :y="view.bodyBaselines[rowIndex]"
                  :font-size="view.bodyFontSize"
                  :fill="view.tone.text"
                  font-family="'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
                >{{ row.text }}</text>
              </g>
            </g>

            <template v-if="view.node.shape === 'table'">
              <line
                v-for="y in view.rowLines"
                :key="`row-${y}`"
                :x1="view.node.x"
                :x2="view.node.x + view.node.w"
                :y1="y"
                :y2="y"
                :stroke="view.tone.stroke"
                :stroke-width="1 / vp.zoom"
                opacity="0.22"
                pointer-events="none"
              />
              <g
                v-for="(row, rowIndex) in view.tableRows"
                :key="`cell-${rowIndex}`"
                pointer-events="none"
              >
                <text
                  v-if="row.key"
                  :x="view.node.x + 12"
                  :y="view.bodyBaselines[rowIndex]"
                  :font-size="8.8"
                  font-weight="700"
                  :fill="view.tone.stroke"
                  font-family="'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
                >{{ row.key }}</text>
                <text
                  :x="row.textX"
                  :y="view.bodyBaselines[rowIndex]"
                  :font-size="view.bodyFontSize"
                  :fill="view.tone.text"
                  font-family="'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
                >{{ row.text }}</text>
              </g>
            </template>
          </template>

          <!-- 网络图元 -->
          <template v-else-if="view.node.shape === 'network'">
            <rect
              :x="view.node.x"
              :y="view.node.y"
              :width="view.node.w"
              :height="view.node.h"
              :rx="view.rx"
              :fill="view.tone.fill"
              :stroke="view.tone.stroke"
              :stroke-width="1.5 / vp.zoom"
            />
            <g
              :transform="`translate(${view.centerX} ${view.iconY})`"
              :stroke="view.tone.stroke"
              fill="none"
              :stroke-width="1.5 / vp.zoom"
              stroke-linecap="round"
              stroke-linejoin="round"
              pointer-events="none"
            >
              <template v-if="view.node.variant === 'cloud'">
                <path
                  d="M-17 6 C-25 6 -25 -5 -16 -7 C-15 -17 3 -21 8 -10 C20 -13 25 3 16 7 Z"
                  fill="none"
                />
              </template>
              <template v-else-if="view.node.variant === 'database'">
                <ellipse cx="0" cy="-10" rx="13" ry="4.5" />
                <path d="M-13 -10 V8 C-13 11.5 -7 14 0 14 C7 14 13 11.5 13 8 V-10" />
                <path d="M-13 0 C-13 3.5 -7 6 0 6 C7 6 13 3.5 13 0" />
              </template>
              <template v-else-if="view.node.variant === 'storage'">
                <ellipse cx="0" cy="-13" rx="13" ry="4.5" />
                <path d="M-13 -13 V12 C-13 15.5 -7 18 0 18 C7 18 13 15.5 13 12 V-13" />
                <path d="M-13 -1 C-13 2.5 -7 5 0 5 C7 5 13 2.5 13 -1" />
                <path d="M-13 9 C-13 12.5 -7 15 0 15 C7 15 13 12.5 13 9" />
              </template>
              <template v-else-if="view.node.variant === 'router'">
                <rect x="-16" y="3" width="32" height="12" rx="2.5" />
                <path d="M0 3 V-4" />
                <path d="m-4 -8 4 -4 4 4" />
                <circle cx="-10" cy="9" r="0.9" :fill="view.tone.stroke" stroke="none" />
                <circle cx="-5" cy="9" r="0.9" :fill="view.tone.stroke" stroke="none" />
              </template>
              <template v-else-if="view.node.variant === 'firewall'">
                <rect x="-15" y="-13" width="30" height="26" rx="2.5" />
                <path d="M-15 -4 H15 M-15 5 H15" />
                <path d="M-5 -13 V-4 M5 -4 V5 M-5 5 V13" />
              </template>
              <template v-else-if="view.node.variant === 'client'">
                <rect x="-15" y="-15" width="30" height="21" rx="2.5" />
                <path d="M0 6 V12 M-7 13 H7" />
              </template>
              <template v-else-if="view.node.variant === 'switch'">
                <rect x="-15" y="-8" width="30" height="16" rx="2.5" />
                <path d="m-8 -12 3 -3 3 3 M8 -12l-3 -3-3 3" />
                <circle cx="-10" cy="0" r="0.9" :fill="view.tone.stroke" stroke="none" />
                <circle cx="-4" cy="0" r="0.9" :fill="view.tone.stroke" stroke="none" />
                <circle cx="4" cy="0" r="0.9" :fill="view.tone.stroke" stroke="none" />
                <circle cx="10" cy="0" r="0.9" :fill="view.tone.stroke" stroke="none" />
              </template>
              <template v-else>
                <rect x="-15" y="-15" width="30" height="12" rx="2" />
                <rect x="-15" y="3" width="30" height="12" rx="2" />
                <path d="M-10 -9 H-4 M-10 9 H-4" />
              </template>
            </g>
            <text
              v-if="view.networkLines.length"
              :x="view.centerX"
              text-anchor="middle"
              :font-size="12.5"
              font-weight="500"
              :fill="view.tone.text"
              font-family="'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
              pointer-events="none"
            >
              <tspan
                v-for="(line, index) in view.networkLines"
                :key="index"
                :x="view.centerX"
                :y="view.networkBaselines[index]"
              >{{ line }}</tspan>
            </text>
          </template>

          <!-- 普通图形 -->
          <template v-else>
            <ellipse
              v-if="view.node.shape === 'ellipse'"
              :cx="view.node.x + view.node.w / 2"
              :cy="view.node.y + view.node.h / 2"
              :rx="view.node.w / 2"
              :ry="view.node.h / 2"
              :fill="view.isText || view.node.container ? 'transparent' : view.tone.fill"
              :stroke="view.isText ? 'transparent' : view.tone.stroke"
              :stroke-width="1.5 / vp.zoom"
            />
            <polygon
              v-else-if="view.node.shape === 'diamond'"
              :points="diamondPoints(view.node)"
              :fill="view.isText || view.node.container ? 'transparent' : view.tone.fill"
              :stroke="view.isText ? 'transparent' : view.tone.stroke"
              :stroke-width="1.5 / vp.zoom"
            />
            <rect
              v-else
              :x="view.node.x"
              :y="view.node.y"
              :width="view.node.w"
              :height="view.node.h"
              :rx="view.rx"
              :fill="view.isText || view.node.container ? 'transparent' : view.tone.fill"
              :stroke="view.isText ? 'transparent' : view.tone.stroke"
              :stroke-width="1.5 / vp.zoom"
              :style="view.node.shape === 'sticky' ? 'filter: drop-shadow(0 3px 6px rgba(15,23,42,.12))' : ''"
            />
            <text
              v-if="view.node.text"
              :x="view.textX"
              :y="view.baselines[0]"
              :text-anchor="view.anchor"
              :font-size="view.node.fontSize ?? DEFAULT_FONT_SIZE"
              :font-weight="view.node.bold ? 600 : 400"
              :fill="view.tone.text"
              font-family="'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
              pointer-events="none"
            >
              <tspan
                v-for="(line, index) in view.lines"
                :key="index"
                :x="view.textX"
                :y="view.baselines[index]"
              >{{ line }}</tspan>
            </text>
            <text
              v-else-if="view.isText"
              :x="view.textX"
              :y="view.node.y + view.node.h / 2 + 5"
              :text-anchor="view.anchor"
              :font-size="view.node.fontSize ?? DEFAULT_FONT_SIZE"
              :fill="theme.gridStrong"
              font-family="'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
              pointer-events="none"
            >
              双击输入
            </text>
          </template>

          <!-- 选中框 -->
          <rect
            v-if="isSelected(view.node.id)"
            :x="view.node.x - 3 / vp.zoom"
            :y="view.node.y - 3 / vp.zoom"
            :width="view.node.w + 6 / vp.zoom"
            :height="view.node.h + 6 / vp.zoom"
            :rx="view.rx + 2 / vp.zoom"
            fill="none"
            :stroke="theme.selection"
            :stroke-width="1.5 / vp.zoom"
            :stroke-dasharray="`${5 / vp.zoom} ${4 / vp.zoom}`"
            pointer-events="none"
          />

          <!-- 吸附端点 -->
          <g v-if="anchorNodeId === view.node.id" pointer-events="none">
            <circle
              v-for="side in ANCHOR_SIDES"
              :key="side"
              :cx="anchorPoint(view.node, side).x"
              :cy="anchorPoint(view.node, side).y"
              :r="4.2 / vp.zoom"
              :fill="theme.bg"
              :stroke="theme.accent"
              :stroke-width="1.6 / vp.zoom"
            />
          </g>

          <!-- 连线目标高亮 -->
          <rect
            v-if="connectPreview?.targetId === view.node.id"
            :x="view.node.x - 5 / vp.zoom"
            :y="view.node.y - 5 / vp.zoom"
            :width="view.node.w + 10 / vp.zoom"
            :height="view.node.h + 10 / vp.zoom"
            :rx="view.rx + 3 / vp.zoom"
            fill="none"
            :stroke="theme.accent"
            :stroke-width="2 / vp.zoom"
            pointer-events="none"
          />

          <!-- 缩放手柄 -->
          <template v-if="singleSelectedNode?.id === view.node.id && editingId !== view.node.id">
            <rect
              v-for="handle in handlesOf(view.node)"
              :key="handle.key"
              :data-handle="handle.key"
              :x="handle.x"
              :y="handle.y"
              :width="handle.size"
              :height="handle.size"
              :rx="1.5 / vp.zoom"
              :fill="theme.handleFill"
              :stroke="theme.selection"
              :stroke-width="1.4 / vp.zoom"
              :style="{ cursor: handle.cursor }"
            />
          </template>
        </g>

        <!-- 选中连线的端点：拖动可重新吸附节点或落到空白处 -->
        <g v-if="selectedEdgeView" pointer-events="all">
          <circle
            v-for="end in EDGE_ENDS"
            :key="end"
            :data-edge-id="selectedEdgeView.edge.id"
            :data-edge-end="end"
            :cx="end === 'from' ? selectedEdgeView.from.x : selectedEdgeView.to.x"
            :cy="end === 'from' ? selectedEdgeView.from.y : selectedEdgeView.to.y"
            :r="7 / vp.zoom"
            :fill="theme.bg"
            :stroke="theme.selection"
            :stroke-width="2 / vp.zoom"
            class="cursor-crosshair"
          />
        </g>

        <!-- 连线预览 -->
        <g v-if="connectPreview" pointer-events="none">
          <line
            :x1="connectPreview.x1"
            :y1="connectPreview.y1"
            :x2="connectPreview.x2"
            :y2="connectPreview.y2"
            :stroke="theme.accent"
            :stroke-width="1.6 / vp.zoom"
            :stroke-dasharray="`${6 / vp.zoom} ${5 / vp.zoom}`"
          />
          <circle
            :cx="connectPreview.x2"
            :cy="connectPreview.y2"
            :r="3.5 / vp.zoom"
            :fill="theme.accent"
          />
        </g>

        <!-- 对齐辅助线 -->
        <line
          v-for="(guide, index) in guideLines"
          :key="`g-${index}`"
          :x1="guide.x1"
          :y1="guide.y1"
          :x2="guide.x2"
          :y2="guide.y2"
          :stroke="theme.guide"
          :stroke-width="1 / vp.zoom"
          :stroke-dasharray="`${5 / vp.zoom} ${4 / vp.zoom}`"
          pointer-events="none"
        />

        <!-- 框选 -->
        <rect
          v-if="marquee"
          :x="marquee.x"
          :y="marquee.y"
          :width="marquee.w"
          :height="marquee.h"
          :rx="2 / vp.zoom"
          :fill="theme.accent"
          fill-opacity="0.08"
          :stroke="theme.accent"
          :stroke-width="1 / vp.zoom"
          :stroke-dasharray="`${4 / vp.zoom} ${3 / vp.zoom}`"
          pointer-events="none"
        />
      </g>
    </svg>

    <!-- 左上：工具条 + 属性检查器（同一列，避免换行时互相遮挡） -->
    <div class="canvas-ui absolute left-3 top-3 z-20 flex max-w-[min(96%,980px)] flex-col items-start gap-1.5">
      <div
        class="flex max-w-full flex-wrap items-center gap-0.5 rounded-xl border p-1 shadow-lg backdrop-blur-md"
        :class="dark ? 'border-white/10 bg-slate-900/80' : 'border-slate-200/80 bg-white/90'"
      >
      <button
        v-for="item in TOOLS"
        :key="item.key"
        type="button"
        class="grid h-8 w-8 place-items-center rounded-lg transition-colors"
        :class="
          tool === item.key
            ? 'bg-kiwi-500 text-white shadow-sm'
            : dark
              ? 'text-slate-300 hover:bg-white/10'
              : 'text-slate-500 hover:bg-slate-100'
        "
        :title="`${item.label}（${item.keyHint}）`"
        @click="setTool(item.key)"
      >
        <KiwiIcon :name="item.icon" :size="15" />
      </button>

      <KiwiDropdown width="w-64">
        <template #trigger="{ open }">
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg transition-colors"
            :class="
              open
                ? 'bg-kiwi-50 text-kiwi-600'
                : dark
                  ? 'text-slate-300 hover:bg-white/10'
                  : 'text-slate-500 hover:bg-slate-100'
            "
            title="网络图元"
          >
            <KiwiIcon name="cloud" :size="15" />
          </button>
        </template>
        <template #default="{ close }">
          <p class="px-2.5 pb-1 pt-1.5 text-[10px] font-medium text-slate-400">网络图元 · 点击放置到画布</p>
          <button
            v-for="item in NETWORK_ITEMS"
            :key="item.kind"
            type="button"
            class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-kiwi-50/80"
            @click="addNetworkNode(item.kind); close()"
          >
            <span class="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500">
              <KiwiIcon :name="item.icon" :size="14" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-[12px] font-medium text-slate-700">{{ item.label }}</span>
              <span class="block text-[10px] text-slate-400">{{ item.desc }}</span>
            </span>
          </button>
        </template>
      </KiwiDropdown>

      <span class="mx-0.5 h-5 w-px" :class="dark ? 'bg-white/10' : 'bg-slate-200'" />

      <button
        type="button"
        class="grid h-8 w-8 place-items-center rounded-lg transition-colors disabled:opacity-30"
        :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
        title="撤销（Ctrl/Cmd+Z）"
        :disabled="!canUndo"
        @click="undo"
      >
        <KiwiIcon name="undo" :size="15" />
      </button>
      <button
        type="button"
        class="grid h-8 w-8 place-items-center rounded-lg transition-colors disabled:opacity-30"
        :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
        title="重做（Ctrl/Cmd+Shift+Z）"
        :disabled="!canRedo"
        @click="redo"
      >
        <KiwiIcon name="redo" :size="15" />
      </button>
      <button
        type="button"
        class="grid h-8 w-8 place-items-center rounded-lg transition-colors disabled:opacity-30"
        :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
        title="复制选中（Ctrl/Cmd+D）"
        :disabled="!hasSelection"
        @click="duplicateSelection"
      >
        <KiwiIcon name="copy" :size="15" />
      </button>
      <button
        type="button"
        class="grid h-8 w-8 place-items-center rounded-lg text-rose-500 transition-colors hover:bg-rose-50 disabled:opacity-30"
        title="删除选中（Delete）"
        :disabled="!hasSelection"
        @click="deleteSelection"
      >
        <KiwiIcon name="trash" :size="15" />
      </button>

      <span class="mx-0.5 h-5 w-px" :class="dark ? 'bg-white/10' : 'bg-slate-200'" />

      <button
        type="button"
        class="flex h-8 items-center gap-1.5 rounded-lg px-2 text-[11.5px] font-medium transition-colors"
        :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-600 hover:bg-slate-100'"
        title="从模板开始"
        @click="templateOpen = true"
      >
        <KiwiIcon name="layoutTemplate" :size="15" />
        模板
      </button>

      <KiwiDropdown width="w-60">
        <template #trigger="{ open }">
          <button
            type="button"
            class="flex h-8 items-center gap-1.5 rounded-lg px-2 text-[11.5px] font-medium transition-colors"
            :class="
              open
                ? dark
                  ? 'bg-white/10 text-white'
                  : 'bg-slate-100 text-slate-700'
                : dark
                  ? 'text-slate-300 hover:bg-white/10'
                  : 'text-slate-600 hover:bg-slate-100'
            "
            title="切换主题"
          >
            <KiwiIcon name="palette" :size="15" />
            {{ theme.name }}
          </button>
        </template>
        <template #default="{ close }">
          <button
            v-for="item in Object.values(THEMES)"
            :key="item.id"
            type="button"
            class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-kiwi-50/80"
            @click="setTheme(item.id); close()"
          >
            <span class="flex h-7 w-7 shrink-0 items-center justify-center gap-0.5 rounded-lg border border-slate-200/80">
              <span
                v-for="color in item.swatches"
                :key="color"
                class="h-3.5 w-1.5 rounded-sm"
                :style="{ background: color }"
              />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-[12px] font-medium text-slate-700">{{ item.name }}</span>
              <span class="block truncate text-[10px] text-slate-400">{{ item.desc }}</span>
            </span>
            <KiwiIcon
              v-if="doc.theme === item.id"
              name="check"
              :size="13"
              class="shrink-0 text-kiwi-500"
            />
          </button>
        </template>
      </KiwiDropdown>

      <KiwiDropdown width="w-72">
        <template #trigger="{ open }">
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg transition-colors"
            :class="
              open
                ? 'bg-kiwi-50 text-kiwi-600'
                : dark
                  ? 'text-slate-300 hover:bg-white/10'
                  : 'text-slate-500 hover:bg-slate-100'
            "
            title="图层顺序"
          >
            <KiwiIcon name="layers" :size="15" />
          </button>
        </template>
        <template #default>
          <div class="flex items-center justify-between px-2.5 pb-1 pt-1.5">
            <span class="text-[10px] font-medium text-slate-400">图层（上 → 下）</span>
            <span class="text-[10px] tabular-nums text-slate-400">{{ doc.nodes.length }} 个节点</span>
          </div>
          <div v-if="!doc.nodes.length" class="px-2.5 py-3 text-[11px] text-slate-400">
            画布上还没有节点
          </div>
          <div v-else class="max-h-72 overflow-y-auto">
            <div
              v-for="node in layerNodes"
              :key="node.id"
              class="flex items-center gap-1 rounded-lg px-1.5 py-1"
              :class="isSelected(node.id) ? 'bg-kiwi-50' : 'hover:bg-slate-50'"
            >
              <button
                type="button"
                class="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                @click="selectNode(node.id)"
              >
                <span
                  class="h-2.5 w-2.5 shrink-0 rounded-sm border"
                  :style="{
                    background: theme.tones[node.tone ?? 'neutral'].fill,
                    borderColor: theme.tones[node.tone ?? 'neutral'].stroke,
                  }"
                />
                <KiwiIcon
                  :name="
                    node.shape === 'network'
                      ? NETWORK_ITEMS.find((item) => item.kind === node.variant)?.icon ?? 'cloud'
                      : node.shape === 'uml'
                        ? 'code'
                        : node.shape === 'table'
                          ? 'table'
                          : node.shape === 'sticky'
                            ? 'note'
                            : node.shape === 'text'
                              ? 'type'
                              : node.shape === 'diamond'
                                ? 'diamond'
                                : node.shape === 'ellipse'
                                  ? 'circle'
                                  : 'square'
                  "
                  :size="12"
                  class="shrink-0 text-slate-400"
                />
                <span class="truncate text-[11.5px] text-slate-600">
                  {{ nodeLabel(node) }}
                </span>
              </button>
              <button
                type="button"
                class="grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-white hover:text-slate-600 disabled:opacity-25"
                title="上移一层（更靠前）"
                :disabled="node.id === doc.nodes[doc.nodes.length - 1]?.id"
                @click="moveLayer(node.id, 1)"
              >
                <KiwiIcon name="arrowUp" :size="12" />
              </button>
              <button
                type="button"
                class="grid h-6 w-6 place-items-center rounded-md text-slate-400 transition-colors hover:bg-white hover:text-slate-600 disabled:opacity-25"
                title="下移一层（更靠后）"
                :disabled="node.id === doc.nodes[0]?.id"
                @click="moveLayer(node.id, -1)"
              >
                <KiwiIcon name="arrowDown" :size="12" />
              </button>
            </div>
          </div>
          <div class="mt-1 border-t border-slate-100 px-2.5 py-1.5 text-[10px] text-slate-400">
            列表越靠上越靠前 · 快捷键 [ / ]
          </div>
        </template>
      </KiwiDropdown>

      <button
        type="button"
        class="grid h-8 w-8 place-items-center rounded-lg transition-colors"
        :class="
          doc.grid
            ? 'bg-kiwi-50 text-kiwi-600'
            : dark
              ? 'text-slate-400 hover:bg-white/10'
              : 'text-slate-400 hover:bg-slate-100'
        "
        title="显示网格"
        @click="toggleGrid"
      >
        <KiwiIcon name="hash" :size="15" />
      </button>
      <button
        type="button"
        class="grid h-8 w-8 place-items-center rounded-lg transition-colors"
        :class="
          doc.snap
            ? 'bg-kiwi-50 text-kiwi-600'
            : dark
              ? 'text-slate-400 hover:bg-white/10'
              : 'text-slate-400 hover:bg-slate-100'
        "
        title="吸附到网格"
        @click="toggleSnap"
      >
        <KiwiIcon name="magnet" :size="15" />
      </button>
      </div>

      <!-- 属性检查器 -->
      <div
        v-if="singleSelectedNode || selectedEdgeObj"
        class="flex max-w-full flex-wrap items-center gap-1.5 rounded-xl border px-2 py-1.5 shadow-lg backdrop-blur-md"
        :class="dark ? 'border-white/10 bg-slate-900/80' : 'border-slate-200/80 bg-white/90'"
      >
      <template v-if="singleSelectedNode">
        <span class="mr-0.5 text-[10px] font-medium" :class="dark ? 'text-slate-400' : 'text-slate-400'">
          节点
        </span>
        <button
          v-for="tone in TONES"
          :key="tone"
          type="button"
          class="h-5 w-5 rounded-full border-2 transition-transform hover:scale-110"
          :class="singleSelectedNode.tone === tone ? 'ring-2 ring-kiwi-400 ring-offset-1' : ''"
          :style="{
            background: theme.tones[tone].fill,
            borderColor: theme.tones[tone].stroke,
          }"
          :title="tone"
          @click="setNodeTone(tone)"
        />
        <span class="mx-0.5 h-4 w-px" :class="dark ? 'bg-white/10' : 'bg-slate-200'" />
        <button
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md transition-colors"
          :class="
            singleSelectedNode.bold
              ? 'bg-kiwi-50 text-kiwi-600'
              : dark
                ? 'text-slate-300 hover:bg-white/10'
                : 'text-slate-500 hover:bg-slate-100'
          "
          title="加粗"
          @click="toggleBold"
        >
          <KiwiIcon name="bold" :size="13" />
        </button>
        <div class="flex items-center rounded-md border" :class="dark ? 'border-white/10' : 'border-slate-200'">
          <button
            type="button"
            class="grid h-6 w-6 place-items-center rounded-l-md transition-colors"
            :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
            title="减小字号"
            @click="bumpFont(-1)"
          >
            <KiwiIcon name="minus" :size="12" />
          </button>
          <span class="min-w-6 text-center text-[10.5px] tabular-nums" :class="dark ? 'text-slate-300' : 'text-slate-500'">
            {{ singleSelectedNode.fontSize ?? DEFAULT_FONT_SIZE }}
          </span>
          <button
            type="button"
            class="grid h-6 w-6 place-items-center rounded-r-md transition-colors"
            :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
            title="增大字号"
            @click="bumpFont(1)"
          >
            <KiwiIcon name="plus" :size="12" />
          </button>
        </div>
        <button
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md transition-colors"
          :class="
            singleSelectedNode.align === 'left'
              ? 'bg-kiwi-50 text-kiwi-600'
              : dark
                ? 'text-slate-300 hover:bg-white/10'
                : 'text-slate-500 hover:bg-slate-100'
          "
          title="切换对齐"
          @click="toggleAlign"
        >
          <KiwiIcon name="alignLeft" :size="13" />
        </button>
        <span class="mx-0.5 h-4 w-px" :class="dark ? 'bg-white/10' : 'bg-slate-200'" />
        <span class="text-[10px]" :class="dark ? 'text-slate-500' : 'text-slate-400'">图层</span>
        <div
          class="flex items-center rounded-md border"
          :class="dark ? 'border-white/10' : 'border-slate-200'"
        >
          <button
            v-for="action in [
              { key: 'top', label: '顶', title: '置于顶层（Shift+]）', handler: bringToFront },
              { key: 'up', label: '上', title: '上移一层（]）', handler: bringForward },
              { key: 'down', label: '下', title: '下移一层（[）', handler: sendBackward },
              { key: 'bottom', label: '底', title: '置于底层（Shift+[）', handler: sendToBack },
            ]"
            :key="action.key"
            type="button"
            class="h-6 min-w-6 px-1 text-[10.5px] transition-colors first:rounded-l-md last:rounded-r-md"
            :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
            :title="action.title"
            @click="action.handler"
          >
            {{ action.label }}
          </button>
        </div>
        <span class="mx-0.5 h-4 w-px" :class="dark ? 'bg-white/10' : 'bg-slate-200'" />
        <button
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md text-rose-500 transition-colors hover:bg-rose-50"
          title="删除"
          @click="deleteSelection"
        >
          <KiwiIcon name="trash" :size="13" />
        </button>
        <span class="ml-1 text-[10px]" :class="dark ? 'text-slate-500' : 'text-slate-400'">
          Tab 添加子节点 · 双击编辑
        </span>
      </template>

      <template v-else-if="selectedEdgeObj">
        <span class="mr-0.5 text-[10px] font-medium" :class="dark ? 'text-slate-400' : 'text-slate-400'">
          连线
        </span>
        <button
          v-for="option in CURVE_OPTIONS"
          :key="option.value"
          type="button"
          class="rounded-md px-2 py-1 text-[10.5px] font-medium transition-colors"
          :class="
            selectedEdgeObj.curve === option.value
              ? 'bg-kiwi-50 text-kiwi-600'
              : dark
                ? 'text-slate-300 hover:bg-white/10'
                : 'text-slate-500 hover:bg-slate-100'
          "
          @click="setEdgeCurve(option.value)"
        >
          {{ option.label }}
        </button>
        <span class="mx-0.5 h-4 w-px" :class="dark ? 'bg-white/10' : 'bg-slate-200'" />
        <button
          v-for="option in ARROW_OPTIONS"
          :key="option.value"
          type="button"
          class="rounded-md px-2 py-1 text-[10.5px] font-medium transition-colors"
          :class="
            selectedEdgeObj.arrow === option.value
              ? 'bg-kiwi-50 text-kiwi-600'
              : dark
                ? 'text-slate-300 hover:bg-white/10'
                : 'text-slate-500 hover:bg-slate-100'
          "
          @click="setEdgeArrow(option.value)"
        >
          {{ option.label }}
        </button>
        <button
          type="button"
          class="rounded-md px-2 py-1 text-[10.5px] font-medium transition-colors"
          :class="
            selectedEdgeObj.dashed
              ? 'bg-kiwi-50 text-kiwi-600'
              : dark
                ? 'text-slate-300 hover:bg-white/10'
                : 'text-slate-500 hover:bg-slate-100'
          "
          @click="toggleEdgeDashed"
        >
          虚线
        </button>
        <input
          :value="selectedEdgeObj.label ?? ''"
          type="text"
          placeholder="连线标签"
          class="h-6 w-28 rounded-md border px-2 text-[11px] outline-none focus:border-kiwi-400"
          :class="
            dark
              ? 'border-white/10 bg-white/5 text-slate-200 placeholder:text-slate-500'
              : 'border-slate-200 bg-white text-slate-600 placeholder:text-slate-300'
          "
          @change="onEdgeLabelChange"
          @keydown.enter="blurTarget"
        />
        <button
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md text-rose-500 transition-colors hover:bg-rose-50"
          title="删除连线"
          @click="deleteSelection"
        >
          <KiwiIcon name="trash" :size="13" />
        </button>
      </template>
      </div>
    </div>

    <!-- 空画布引导 -->
    <div v-if="!doc.nodes.length" class="pointer-events-none absolute inset-0 z-10 grid place-items-center">
      <div
        class="canvas-ui pointer-events-auto rounded-2xl border px-8 py-7 text-center shadow-xl backdrop-blur-md"
        :class="dark ? 'border-white/10 bg-slate-900/70' : 'border-slate-200/80 bg-white/80'"
      >
        <div
          class="mx-auto grid h-12 w-12 place-items-center rounded-2xl"
          :class="dark ? 'bg-white/5 text-kiwi-300' : 'bg-kiwi-50 text-kiwi-500'"
        >
          <KiwiIcon name="pen" :size="22" />
        </div>
        <p class="mt-3 text-[13px] font-semibold" :class="dark ? 'text-slate-100' : 'text-slate-700'">
          画布是空的
        </p>
        <p class="mt-1 text-[11.5px]" :class="dark ? 'text-slate-400' : 'text-slate-400'">
          选择上方图形工具绘制，或从内置模板开始
        </p>
        <div class="mt-4 flex items-center justify-center gap-2">
          <button type="button" class="kiwi-btn-primary !px-3 !py-1.5 !text-xs" @click="templateOpen = true">
            <KiwiIcon name="layoutTemplate" :size="13" />
            浏览模板
          </button>
          <button type="button" class="kiwi-btn-secondary !px-3 !py-1.5 !text-xs" @click="addEmptySticky">
            <KiwiIcon name="note" :size="13" />
            添加便签
          </button>
        </div>
      </div>
    </div>

    <!-- 右下：缩放 -->
    <div
      class="canvas-ui absolute bottom-3 right-3 z-20 flex items-center gap-0.5 rounded-lg border p-0.5 shadow-md backdrop-blur-md"
      :class="dark ? 'border-white/10 bg-slate-900/80' : 'border-slate-200/80 bg-white/90'"
    >
      <button
        type="button"
        class="grid h-7 w-7 place-items-center rounded-md transition-colors"
        :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
        title="缩小（Ctrl/Cmd+-）"
        @click="zoomBy(1 / 1.2)"
      >
        <KiwiIcon name="minus" :size="13" />
      </button>
      <button
        type="button"
        class="min-w-11 rounded-md px-1 text-center text-[10.5px] tabular-nums transition-colors"
        :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
        title="适应画布（Ctrl/Cmd+0）"
        @click="fit"
      >
        {{ Math.round(vp.zoom * 100) }}%
      </button>
      <button
        type="button"
        class="grid h-7 w-7 place-items-center rounded-md transition-colors"
        :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
        title="放大（Ctrl/Cmd++）"
        @click="zoomBy(1.2)"
      >
        <KiwiIcon name="plus" :size="13" />
      </button>
      <button
        type="button"
        class="grid h-7 w-7 place-items-center rounded-md transition-colors"
        :class="dark ? 'text-slate-300 hover:bg-white/10' : 'text-slate-500 hover:bg-slate-100'"
        title="适应画布"
        @click="fit"
      >
        <KiwiIcon name="maximize" :size="13" />
      </button>
    </div>

    <!-- 左下：操作提示 -->
    <div
      class="canvas-ui pointer-events-none absolute bottom-3 left-3 z-10 rounded-lg px-2 py-1 text-[10px] backdrop-blur-sm"
      :class="dark ? 'bg-slate-900/60 text-slate-400' : 'bg-white/70 text-slate-400'"
    >
      空格拖动平移 · Ctrl/⌘+滚轮缩放 · V 选择 · A 连线 · [ / ] 图层
    </div>

    <!-- 文本编辑 -->
    <textarea
      v-if="editingId"
      ref="editEl"
      v-model="editingText"
      class="canvas-ui canvas-text-edit absolute z-30 resize-none overflow-hidden outline-none"
      :style="editStyle"
      spellcheck="false"
      @blur="commitEdit"
      @pointerdown.stop
      @wheel.stop
      @keydown.esc.stop.prevent="cancelEdit"
      @keydown.enter.ctrl.stop.prevent="commitEdit"
      @keydown.enter.meta.stop.prevent="commitEdit"
    />

    <!-- 模板库 -->
    <KiwiModal :open="templateOpen" title="从模板开始" max-w="max-w-2xl" @close="templateOpen = false">
      <p class="-mt-2 mb-4 text-[11.5px] text-slate-400">
        应用模板会替换当前画布内容，可用撤销（Ctrl/Cmd+Z）恢复。
      </p>
      <div class="grid grid-cols-2 gap-3">
        <button
          v-for="item in CANVAS_TEMPLATES"
          :key="item.id"
          type="button"
          class="flex items-start gap-3 rounded-xl border border-slate-200/80 bg-white/70 p-3.5 text-left transition-all hover:-translate-y-0.5 hover:border-kiwi-300 hover:shadow-md"
          @click="requestTpl(item)"
        >
          <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-kiwi-50 text-kiwi-600">
            <KiwiIcon :name="item.icon" :size="18" />
          </span>
          <span class="min-w-0">
            <span class="block text-[13px] font-semibold text-slate-700">{{ item.name }}</span>
            <span class="mt-0.5 block text-[11px] leading-relaxed text-slate-400">{{ item.desc }}</span>
          </span>
        </button>
      </div>
    </KiwiModal>

    <KiwiConfirm
      v-model="templateConfirmOpen"
      title="替换当前画布？"
      :message="`画布中已有 ${doc.nodes.length} 个节点、${doc.edges.length} 条连线，应用模板会替换全部内容。替换后可用撤销（Ctrl/Cmd+Z）恢复。`"
      confirm-text="替换并应用"
      danger
      @confirm="confirmTplReplace"
    />
  </div>
</template>

<style scoped>
.canvas-stage {
  touch-action: none;
}
.canvas-text-edit {
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.35);
  border: 1px solid transparent;
}
.canvas-node {
  cursor: inherit;
}
</style>
