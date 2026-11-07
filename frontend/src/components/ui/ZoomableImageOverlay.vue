<script setup lang="ts">
/**
 * 全屏图片查看器：滚轮 / 按钮缩放，拖拽平移，双击复位，点击图片外区域关闭。
 * 图片与笔记正文中的灯箱、Markdown 阅读态灯箱共用，保证交互一致。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import KiwiIcon from './KiwiIcon.vue'
import { toast } from './toast'

const props = withDefaults(
  defineProps<{
    open: boolean
    src: string
    alt?: string
    caption?: string
    /** 下载失败时是否允许退回到新窗口打开。 */
    fallbackOpen?: boolean
  }>(),
  { alt: '', caption: '', fallbackOpen: true },
)

const emit = defineEmits<{ (e: 'close'): void }>()

const stage = ref<HTMLElement | null>(null)
const image = ref<HTMLImageElement | null>(null)
const scale = ref(1)
const offset = ref({ x: 0, y: 0 })
const dragging = ref(false)
const loaded = ref(false)

const MIN_SCALE = 0.2
const MAX_SCALE = 8
const STEP = 0.2

const percent = computed(() => Math.round(scale.value * 100))
const zoomed = computed(() => Math.abs(scale.value - 1) > 0.001 || offset.value.x !== 0 || offset.value.y !== 0)

const imageStyle = computed(() => ({
  transform: `translate3d(${offset.value.x}px, ${offset.value.y}px, 0) scale(${scale.value})`,
  cursor: dragging.value ? 'grabbing' : zoomed.value ? 'grab' : 'zoom-in',
}))

function clampScale(value: number) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value))
}

function reset() {
  scale.value = 1
  offset.value = { x: 0, y: 0 }
  dragging.value = false
}

function zoomAt(nextScale: number, clientX?: number, clientY?: number) {
  const target = clampScale(nextScale)
  if (Math.abs(target - scale.value) < 0.001) return
  const stageRect = stage.value?.getBoundingClientRect()
  if (stageRect && typeof clientX === 'number' && typeof clientY === 'number') {
    // 以指针所在位置为缩放中心：先记录指针相对图片中心的坐标，再按比例修正平移。
    const centerX = stageRect.left + stageRect.width / 2
    const centerY = stageRect.top + stageRect.height / 2
    const ratio = target / scale.value
    offset.value = {
      x: (offset.value.x + clientX - centerX) * ratio - (clientX - centerX),
      y: (offset.value.y + clientY - centerY) * ratio - (clientY - centerY),
    }
  }
  scale.value = target
}

function zoomBy(direction: -1 | 1) {
  zoomAt(scale.value + direction * STEP)
}

function onWheel(event: WheelEvent) {
  event.preventDefault()
  const delta = event.deltaY > 0 ? -STEP : STEP
  zoomAt(scale.value + delta, event.clientX, event.clientY)
}

function onDoubleClick() {
  if (zoomed.value) reset()
  else zoomAt(2)
}

let dragStart: { x: number; y: number; ox: number; oy: number } | null = null

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  dragging.value = true
  dragStart = {
    x: event.clientX,
    y: event.clientY,
    ox: offset.value.x,
    oy: offset.value.y,
  }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function onPointerMove(event: PointerEvent) {
  if (!dragStart) return
  offset.value = {
    x: dragStart.ox + event.clientX - dragStart.x,
    y: dragStart.oy + event.clientY - dragStart.y,
  }
}

function onPointerUp() {
  dragging.value = false
  dragStart = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
}

function onImageLoad() {
  loaded.value = true
}

function close() {
  emit('close')
}

function onKeydown(event: KeyboardEvent) {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key === '+' || event.key === '=') {
    event.preventDefault()
    zoomBy(1)
    return
  }
  if (event.key === '-' || event.key === '_') {
    event.preventDefault()
    zoomBy(-1)
    return
  }
  if (event.key === '0') {
    event.preventDefault()
    reset()
  }
}

function onBackdropClick(event: MouseEvent) {
  // 仅点击图片外的空白区域关闭；图片与工具栏自身的点击不冒泡到这里。
  if (event.target === event.currentTarget) close()
}

async function download() {
  if (!props.src) return
  try {
    const res = await fetch(props.src)
    if (!res.ok) throw new Error()
    const blob = await res.blob()
    const objectUrl = URL.createObjectURL(blob)
    const path = props.src.split('?')[0]
    const name = path.slice(path.lastIndexOf('/') + 1) || 'image.png'
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    toast.success('已开始下载图片')
  } catch {
    if (props.fallbackOpen) window.open(props.src, '_blank', 'noopener')
    else toast.error('下载图片失败')
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      reset()
      loaded.value = false
      document.addEventListener('keydown', onKeydown)
      document.body.style.overflow = 'hidden'
    } else {
      document.removeEventListener('keydown', onKeydown)
      document.body.style.overflow = ''
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      dragging.value = false
      dragStart = null
    }
  },
)

onMounted(() => {
  if (props.open) {
    document.addEventListener('keydown', onKeydown)
    document.body.style.overflow = 'hidden'
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  if (props.open) document.body.style.overflow = ''
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[130] flex flex-col bg-slate-950/90 backdrop-blur-sm"
      @click="onBackdropClick"
    >
      <div class="flex shrink-0 items-center justify-between gap-2 px-4 py-3">
        <div class="flex items-center gap-1 rounded-xl bg-white/10 p-0.5 text-white/80">
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg transition-colors hover:bg-white/15 hover:text-white disabled:opacity-40"
            title="缩小（-）"
            :disabled="scale <= MIN_SCALE"
            @click.stop="zoomBy(-1)"
          >
            <KiwiIcon name="minus" :size="15" />
          </button>
          <button
            type="button"
            class="h-8 min-w-[58px] rounded-lg px-1 text-[11px] font-medium tabular-nums transition-colors hover:bg-white/15"
            title="点击恢复 100%"
            @click.stop="reset"
          >
            {{ percent }}%
          </button>
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg transition-colors hover:bg-white/15 hover:text-white disabled:opacity-40"
            title="放大（+）"
            :disabled="scale >= MAX_SCALE"
            @click.stop="zoomBy(1)"
          >
            <KiwiIcon name="plus" :size="15" />
          </button>
          <span class="mx-0.5 h-4 w-px bg-white/15" />
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg transition-colors hover:bg-white/15 hover:text-white disabled:opacity-40"
            title="适应窗口（0）"
            :disabled="!zoomed"
            @click.stop="reset"
          >
            <KiwiIcon name="maximize" :size="14" />
          </button>
        </div>
        <div class="flex items-center gap-2">
          <span class="hidden text-[10.5px] text-white/45 sm:inline">滚轮缩放 · 拖动平移 · 双击复位</span>
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-white/80 transition-colors hover:bg-white/20 hover:text-white"
            title="下载原图"
            @click.stop="download"
          >
            <KiwiIcon name="download" :size="15" />
          </button>
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg bg-white/10 text-white/80 transition-colors hover:bg-white/20 hover:text-white"
            title="关闭（Esc）"
            @click.stop="close"
          >
            <KiwiIcon name="close" :size="15" />
          </button>
        </div>
      </div>

      <div
        ref="stage"
        class="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden"
        @click="onBackdropClick"
        @wheel="onWheel"
      >
        <img
          ref="image"
          :src="src"
          :alt="alt"
          class="max-h-full max-w-full select-none rounded-lg object-contain shadow-2xl transition-opacity duration-150"
          :class="loaded ? 'opacity-100' : 'opacity-0'"
          :style="imageStyle"
          draggable="false"
          @load="onImageLoad"
          @pointerdown="onPointerDown"
          @dblclick.stop="onDoubleClick"
          @click.stop
        />
        <span
          v-if="!loaded"
          class="pointer-events-none absolute inset-0 grid place-items-center text-[12px] text-white/60"
        >
          <KiwiIcon name="loader" :size="20" :spin="true" />
        </span>
      </div>

      <p v-if="caption" class="shrink-0 px-6 pb-4 text-center text-[12px] leading-relaxed text-white/60">
        {{ caption }}
      </p>
    </div>
  </Teleport>
</template>
