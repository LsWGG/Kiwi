<script setup lang="ts">
/**
 * 阅读模式演示层：
 * - 红色激光点跟随鼠标
 * - 底部浮动栏：目录 / 全屏 / 页面缩放 / 演示笔（画笔、箭头、矩形、椭圆、颜色）/ 橡皮擦 / 清空
 * 批注画布只覆盖当前可视区域，不修改笔记内容。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

type DrawTool = 'pen' | 'arrow' | 'rect' | 'ellipse'
type Tool = DrawTool | 'eraser'

interface Point {
  x: number
  y: number
}

interface Stroke {
  tool: DrawTool
  color: string
  width: number
  points: Point[]
}

const props = withDefaults(
  defineProps<{
    areaEl: HTMLElement | null
    scrollerEl: HTMLElement | null
    zoom: number
    zen: boolean
    /** 阅读模式下目录侧栏是否展开 */
    outlineOpen?: boolean
    /** 当前页面是否有目录可显示（链接 / 手账等没有大纲的页面不显示按钮） */
    outlineAvailable?: boolean
  }>(),
  { outlineOpen: false, outlineAvailable: false },
)

const emit = defineEmits<{
  (e: 'update:zoom', value: number): void
  (e: 'update:zen', value: boolean): void
  (e: 'toggle-outline'): void
}>()

const COLORS = ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#8b5cf6', '#0f172a']
const COLOR_NAMES: Record<string, string> = {
  '#ef4444': '红色',
  '#f59e0b': '橙色',
  '#22c55e': '绿色',
  '#3b82f6': '蓝色',
  '#8b5cf6': '紫色',
  '#0f172a': '黑色',
}
const TOOLS: { tool: Tool; icon: string; label: string }[] = [
  { tool: 'pen', icon: 'pen', label: '画笔' },
  { tool: 'arrow', icon: 'arrowUpRight', label: '箭头' },
  { tool: 'rect', icon: 'square', label: '矩形' },
  { tool: 'ellipse', icon: 'circle', label: '椭圆' },
  { tool: 'eraser', icon: 'eraser', label: '橡皮擦' },
]

const ZOOM_MIN = 50
const ZOOM_MAX = 200
const ZOOM_STEP = 10

const canvas = ref<HTMLCanvasElement | null>(null)
const active = ref(false)
const tool = ref<Tool>('pen')
const color = ref(COLORS[0])
const strokes = ref<Stroke[]>([])
const dotVisible = ref(false)
const dot = ref<Point>({ x: 0, y: 0 })
const zoomPct = computed(() => Math.round(props.zoom * 100))

let drawing: Stroke | null = null
let erasing = false
let dpr = 1
let observer: ResizeObserver | null = null
let scrollEl: HTMLElement | null = null

/** 4K 下 body 带 CSS zoom，滚动容器的 scrollTop 需要乘上缩放才是屏幕位移。 */
function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

/** 当前滚动位移（画布/视口像素）。 */
function scrollOffset(): Point {
  const el = props.scrollerEl
  const scale = uiScale()
  return { x: (el?.scrollLeft ?? 0) * scale, y: (el?.scrollTop ?? 0) * scale }
}

/**
 * 批注点存到「正文内容坐标系」：记录时加上当前滚动位移，绘制时整体反向平移，
 * 这样正文上下滚动时标记会跟着内容走，而不是钉在屏幕上。
 */
function bindScroller(el: HTMLElement | null) {
  if (scrollEl === el) return
  scrollEl?.removeEventListener('scroll', redraw)
  scrollEl = el
  scrollEl?.addEventListener('scroll', redraw, { passive: true })
}

watch(() => props.scrollerEl, bindScroller, { immediate: true })

// ---------- 缩放 ----------
/** zoom 以倍数传递（1 = 100%），这里统一按百分比做范围约束。 */
function setZoomPct(pct: number) {
  emit('update:zoom', Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, pct)) / 100)
}

function resetZoom() {
  setZoomPct(100)
}

// ---------- 全屏 ----------
function toggleZen() {
  emit('update:zen', !props.zen)
}

// ---------- 红点 ----------
function onWindowPointerMove(event: PointerEvent) {
  const area = props.areaEl
  if (!area) {
    dotVisible.value = false
    return
  }
  const rect = area.getBoundingClientRect()
  const inside =
    event.clientX >= rect.left &&
    event.clientX <= rect.right &&
    event.clientY >= rect.top &&
    event.clientY <= rect.bottom
  const target = event.target as Element | null
  const overToolbar = !!target?.closest?.('.reading-toolbar')
  dotVisible.value = inside && !overToolbar
  if (inside) {
    // 用百分比定位：body 在 4K 下带 CSS zoom，像素坐标会被二次缩放而与鼠标错位。
    dot.value = {
      x: rect.width ? ((event.clientX - rect.left) / rect.width) * 100 : 0,
      y: rect.height ? ((event.clientY - rect.top) / rect.height) * 100 : 0,
    }
  }
}

// ---------- 滚轮 ----------
/**
 * 演示层盖在滚动容器上方，滚轮事件不会落到下面的滚动容器；
 * 这里手动转发给 scroller，保证开启演示笔后仍能滚动页面。
 */
function onWheel(event: WheelEvent) {
  const scroller = props.scrollerEl
  if (!scroller) return
  event.preventDefault()
  const unit =
    event.deltaMode === WheelEvent.DOM_DELTA_LINE
      ? 16
      : event.deltaMode === WheelEvent.DOM_DELTA_PAGE
        ? scroller.clientHeight
        : 1
  scroller.scrollTop += event.deltaY * unit
  scroller.scrollLeft += event.deltaX * unit
}

// ---------- 画布 ----------
function resizeCanvas() {
  const el = canvas.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  dpr = window.devicePixelRatio || 1
  el.width = Math.max(1, Math.round(rect.width * dpr))
  el.height = Math.max(1, Math.round(rect.height * dpr))
  const ctx = el.getContext('2d')
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  redraw()
}

function bindArea(el: HTMLElement | null) {
  observer?.disconnect()
  observer = null
  if (!el) return
  observer = new ResizeObserver(() => resizeCanvas())
  observer.observe(el)
  resizeCanvas()
}

watch(
  () => props.areaEl,
  (el) => bindArea(el),
  { immediate: true },
)

watch(active, (on) => {
  if (!on) {
    drawing = null
    erasing = false
  }
  requestAnimationFrame(resizeCanvas)
})

watch(tool, (value) => {
  if (value !== 'eraser') erasing = false
})

function context(): CanvasRenderingContext2D | null {
  return canvas.value?.getContext('2d') ?? null
}

function drawStroke(ctx: CanvasRenderingContext2D, stroke: Stroke) {
  const points = stroke.points
  if (!points.length) return
  ctx.save()
  ctx.strokeStyle = stroke.color
  ctx.fillStyle = stroke.color
  ctx.lineWidth = stroke.width
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  if (stroke.tool === 'pen') {
    ctx.beginPath()
    if (points.length === 1) {
      ctx.arc(points[0].x, points[0].y, stroke.width / 2, 0, Math.PI * 2)
      ctx.fill()
    } else {
      ctx.moveTo(points[0].x, points[0].y)
      for (let i = 1; i < points.length; i += 1) ctx.lineTo(points[i].x, points[i].y)
      ctx.stroke()
    }
    ctx.restore()
    return
  }

  const start = points[0]
  const end = points[points.length - 1] ?? start

  if (stroke.tool === 'arrow') {
    ctx.beginPath()
    ctx.moveTo(start.x, start.y)
    ctx.lineTo(end.x, end.y)
    ctx.stroke()
    const angle = Math.atan2(end.y - start.y, end.x - start.x)
    const head = 12 + stroke.width * 2
    ctx.beginPath()
    ctx.moveTo(end.x, end.y)
    ctx.lineTo(
      end.x - head * Math.cos(angle - Math.PI / 7),
      end.y - head * Math.sin(angle - Math.PI / 7),
    )
    ctx.lineTo(
      end.x - head * Math.cos(angle + Math.PI / 7),
      end.y - head * Math.sin(angle + Math.PI / 7),
    )
    ctx.closePath()
    ctx.fill()
  } else if (stroke.tool === 'rect') {
    ctx.strokeRect(
      Math.min(start.x, end.x),
      Math.min(start.y, end.y),
      Math.abs(end.x - start.x),
      Math.abs(end.y - start.y),
    )
  } else {
    const rx = Math.abs(end.x - start.x) / 2
    const ry = Math.abs(end.y - start.y) / 2
    ctx.beginPath()
    ctx.ellipse(
      (start.x + end.x) / 2,
      (start.y + end.y) / 2,
      Math.max(rx, 0.5),
      Math.max(ry, 0.5),
      0,
      0,
      Math.PI * 2,
    )
    ctx.stroke()
  }
  ctx.restore()
}

function redraw() {
  const el = canvas.value
  const ctx = context()
  if (!el || !ctx) return
  ctx.clearRect(0, 0, el.width / dpr, el.height / dpr)
  const offset = scrollOffset()
  ctx.save()
  ctx.translate(-offset.x, -offset.y)
  for (const stroke of strokes.value) drawStroke(ctx, stroke)
  if (drawing) drawStroke(ctx, drawing)
  ctx.restore()
}

function localPoint(event: PointerEvent): Point {
  const rect = canvas.value?.getBoundingClientRect()
  if (!rect) return { x: 0, y: 0 }
  const offset = scrollOffset()
  return {
    x: event.clientX - rect.left + offset.x,
    y: event.clientY - rect.top + offset.y,
  }
}

function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const length = dx * dx + dy * dy
  const t = length ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length)) : 0
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
}

function strokeHit(stroke: Stroke, point: Point): boolean {
  const threshold = 12 + stroke.width / 2
  const pts = stroke.points
  if (!pts.length) return false
  if (stroke.tool === 'pen') {
    if (pts.length === 1) return Math.hypot(point.x - pts[0].x, point.y - pts[0].y) <= threshold
    return pts.some(
      (p, i) => i > 0 && distanceToSegment(point, pts[i - 1], p) <= threshold,
    )
  }
  const start = pts[0]
  const end = pts[pts.length - 1] ?? start
  if (stroke.tool === 'arrow') {
    return distanceToSegment(point, start, end) <= threshold
  }
  if (stroke.tool === 'rect') {
    const a = { x: Math.min(start.x, end.x), y: Math.min(start.y, end.y) }
    const b = { x: Math.max(start.x, end.x), y: Math.max(start.y, end.y) }
    return (
      distanceToSegment(point, a, { x: b.x, y: a.y }) <= threshold ||
      distanceToSegment(point, { x: b.x, y: a.y }, b) <= threshold ||
      distanceToSegment(point, b, { x: a.x, y: b.y }) <= threshold ||
      distanceToSegment(point, { x: a.x, y: b.y }, a) <= threshold
    )
  }
  // 椭圆：采样轮廓近似命中
  const cx = (start.x + end.x) / 2
  const cy = (start.y + end.y) / 2
  const rx = Math.abs(end.x - start.x) / 2
  const ry = Math.abs(end.y - start.y) / 2
  let prev = { x: cx + rx, y: cy }
  for (let i = 1; i <= 72; i += 1) {
    const angle = (i / 72) * Math.PI * 2
    const next = { x: cx + rx * Math.cos(angle), y: cy + ry * Math.sin(angle) }
    if (distanceToSegment(point, prev, next) <= threshold) return true
    prev = next
  }
  return false
}

function eraseAt(point: Point): boolean {
  const before = strokes.value.length
  strokes.value = strokes.value.filter((stroke) => !strokeHit(stroke, point))
  return strokes.value.length !== before
}

function onCanvasPointerDown(event: PointerEvent) {
  if (!active.value) return
  event.preventDefault()
  canvas.value?.setPointerCapture(event.pointerId)
  const point = localPoint(event)
  if (tool.value === 'eraser') {
    erasing = true
    if (eraseAt(point)) redraw()
    return
  }
  drawing = {
    tool: tool.value,
    color: color.value,
    width: tool.value === 'pen' ? 3 : 2.6,
    points: tool.value === 'pen' ? [point] : [point, { ...point }],
  }
  redraw()
}

function onCanvasPointerMove(event: PointerEvent) {
  if (!active.value) return
  const point = localPoint(event)
  if (tool.value === 'eraser') {
    if (!erasing) return
    if (eraseAt(point)) redraw()
    return
  }
  if (!drawing) return
  if (drawing.tool === 'pen') drawing.points.push(point)
  else drawing.points[1] = point
  redraw()
}

function onCanvasPointerUp(event: PointerEvent) {
  if (tool.value === 'eraser') {
    erasing = false
    return
  }
  if (!drawing) return
  const point = localPoint(event)
  if (drawing.tool === 'pen') drawing.points.push(point)
  else drawing.points[1] = point
  const start = drawing.points[0]
  const end = drawing.points[drawing.points.length - 1]
  const moved = Math.hypot(end.x - start.x, end.y - start.y)
  if (drawing.tool === 'pen' ? drawing.points.length > 1 : moved > 3) {
    strokes.value.push(drawing)
  }
  drawing = null
  redraw()
}

function startAnnotating() {
  active.value = true
  tool.value = 'pen'
}

function stopAnnotating() {
  active.value = false
}

function clearStrokes() {
  strokes.value = []
  drawing = null
  redraw()
}

function reset() {
  active.value = false
  drawing = null
  erasing = false
  strokes.value = []
  tool.value = 'pen'
  color.value = COLORS[0]
  redraw()
}

// ---------- 快捷键 ----------
function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (props.zen) {
    emit('update:zen', false)
    return
  }
  if (active.value) {
    event.preventDefault()
    stopAnnotating()
  }
}

onMounted(() => {
  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('keydown', onKeydown)
  requestAnimationFrame(resizeCanvas)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  scrollEl?.removeEventListener('scroll', redraw)
  scrollEl = null
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('keydown', onKeydown)
})

defineExpose({ reset })
</script>

<template>
  <div
    class="reading-layer pointer-events-none absolute inset-0 z-40 overflow-hidden"
    @wheel="onWheel"
  >
    <canvas
      ref="canvas"
      class="reading-canvas absolute inset-0 z-30 h-full w-full"
      :class="active ? 'pointer-events-auto cursor-none' : 'pointer-events-none'"
      :data-strokes="strokes.length"
      :data-tool="active ? tool : 'off'"
      :data-color="color"
      @pointerdown="onCanvasPointerDown"
      @pointermove="onCanvasPointerMove"
      @pointerup="onCanvasPointerUp"
      @pointercancel="onCanvasPointerUp"
    />

    <!-- 红色激光点 -->
    <div
      v-show="dotVisible"
      class="reading-laser"
      :style="{ left: `${dot.x}%`, top: `${dot.y}%` }"
    >
      <span class="reading-laser-halo" />
      <span class="reading-laser-dot" />
    </div>

    <!-- 底部浮动操作栏 -->
    <div
      class="reading-toolbar pointer-events-auto absolute bottom-5 left-1/2 z-50 flex -translate-x-1/2 items-center gap-0.5 rounded-2xl border border-white/10 bg-slate-900/70 px-2 py-1.5 text-white shadow-2xl backdrop-blur-xl opacity-25 transition-opacity duration-300 hover:opacity-100 focus-within:opacity-100"
    >
      <button
        v-if="outlineAvailable"
        type="button"
        class="rt-btn"
        :class="{ 'is-active': outlineOpen }"
        :title="outlineOpen ? '隐藏目录' : '显示目录'"
        :aria-pressed="outlineOpen"
        @click="emit('toggle-outline')"
      >
        <KiwiIcon name="listTree" :size="15" />
      </button>

      <button
        type="button"
        class="rt-btn"
        :title="zen ? '退出全屏' : '全屏阅读'"
        @click="toggleZen"
      >
        <KiwiIcon :name="zen ? 'minimize' : 'maximize'" :size="15" />
      </button>

      <span class="rt-divider" />

      <button
        type="button"
        class="rt-btn"
        title="缩小页面"
        :disabled="zoomPct <= 50"
        @click="setZoomPct(zoomPct - ZOOM_STEP)"
      >
        <KiwiIcon name="minus" :size="14" />
      </button>
      <button
        type="button"
        class="rt-zoom"
        :title="zoomPct === 100 ? '当前为原始比例' : '点击恢复 100%'"
        @click="resetZoom"
      >
        {{ zoomPct }}%
      </button>
      <button
        type="button"
        class="rt-btn"
        title="放大页面"
        :disabled="zoomPct >= 200"
        @click="setZoomPct(zoomPct + ZOOM_STEP)"
      >
        <KiwiIcon name="plus" :size="14" />
      </button>

      <span class="rt-divider" />

      <button
        v-if="!active"
        type="button"
        class="rt-pen-toggle"
        title="开启演示笔，在页面上批注"
        @click="startAnnotating"
      >
        <KiwiIcon name="pen" :size="14" />
        演示笔
      </button>

      <template v-else>
        <button
          v-for="item in TOOLS"
          :key="item.tool"
          type="button"
          class="rt-btn"
          :class="{ 'is-active': tool === item.tool }"
          :title="item.label"
          @click="tool = item.tool"
        >
          <KiwiIcon :name="item.icon" :size="14" />
        </button>

        <span class="rt-divider" />

        <button
          v-for="item in COLORS"
          :key="item"
          type="button"
          class="rt-swatch"
          :class="color === item ? 'is-active' : ''"
          :style="{ backgroundColor: item }"
          :title="`${COLOR_NAMES[item]}笔`"
          @click="color = item"
        />

        <span class="rt-divider" />

        <button
          type="button"
          class="rt-btn"
          title="清空所有批注"
          :disabled="!strokes.length"
          @click="clearStrokes"
        >
          <KiwiIcon name="trash" :size="14" />
        </button>
        <button type="button" class="rt-btn" title="退出演示笔" @click="stopAnnotating">
          <KiwiIcon name="close" :size="14" />
        </button>
      </template>

      <button
        v-if="!active && strokes.length"
        type="button"
        class="rt-btn"
        title="清空所有批注"
        @click="clearStrokes"
      >
        <KiwiIcon name="trash" :size="14" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.rt-btn {
  @apply grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-200 transition-colors hover:bg-white/15 hover:text-white disabled:opacity-30 disabled:hover:bg-transparent;
}
.rt-btn.is-active {
  @apply bg-white text-slate-900 shadow-sm hover:bg-white hover:text-slate-900;
}
.rt-divider {
  @apply mx-0.5 h-5 w-px shrink-0 bg-white/15;
}
.rt-zoom {
  @apply h-8 min-w-[48px] shrink-0 rounded-lg px-1 text-[11px] tabular-nums text-slate-200 transition-colors hover:bg-white/15 hover:text-white;
}
.rt-pen-toggle {
  @apply flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[11.5px] text-slate-200 transition-colors hover:bg-white/15 hover:text-white;
}
.rt-swatch {
  @apply h-4 w-4 shrink-0 rounded-full ring-2 ring-transparent ring-offset-2 ring-offset-slate-900 transition-transform hover:scale-110;
}
.rt-swatch.is-active {
  @apply ring-white;
}
.reading-toolbar {
  cursor: auto;
}
.reading-toolbar button {
  cursor: pointer;
}
.reading-laser {
  position: absolute;
  z-index: 60;
  pointer-events: none;
  transform: translate(-50%, -50%);
}
.reading-laser-halo {
  position: absolute;
  left: -18px;
  top: -18px;
  width: 36px;
  height: 36px;
  border-radius: 9999px;
  background: radial-gradient(circle, rgba(239, 68, 68, 0.3), rgba(239, 68, 68, 0) 70%);
  animation: reading-laser-pulse 2s ease-out infinite;
}
.reading-laser-dot {
  position: absolute;
  left: -5px;
  top: -5px;
  width: 10px;
  height: 10px;
  border-radius: 9999px;
  background: radial-gradient(circle at 35% 30%, #ffffff, #fca5a5 28%, #ef4444 72%);
  box-shadow:
    0 0 0 2px rgba(255, 255, 255, 0.8),
    0 0 16px 4px rgba(239, 68, 68, 0.55);
}
@keyframes reading-laser-pulse {
  0% {
    transform: scale(0.7);
    opacity: 0.9;
  }
  70% {
    transform: scale(1.35);
    opacity: 0;
  }
  100% {
    transform: scale(1.35);
    opacity: 0;
  }
}
</style>
