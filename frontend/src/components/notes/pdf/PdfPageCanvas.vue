<script setup lang="ts">
/**
 * 单页 PDF 画布：进入视口附近才渲染，离开后释放位图。
 * 这样既能保证批注层拿到真实 DOM 页面（而不是 iframe），
 * 又不会把一百多页一次性画进显存。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist'

const props = defineProps<{
  pdf: PDFDocumentProxy
  pageNumber: number
  /** 页面 CSS 缩放（1 = PDF 原始 72dpi 尺寸）。 */
  scale: number
  /** canvas 位图倍率，保证高分屏清晰。 */
  pixelRatio: number
  /** 首屏占位尺寸（PDF 点），页数据到达前先按它撑开高度。 */
  baseWidth: number
  baseHeight: number
}>()

const root = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const size = ref({ width: props.baseWidth * props.scale, height: props.baseHeight * props.scale })
const visible = ref(false)
const rendered = ref(false)
const failed = ref(false)

let page: PDFPageProxy | null = null
let observer: IntersectionObserver | null = null
let renderTask: RenderTask | null = null
let token = 0
let destroyed = false

const style = computed(() => ({
  width: `${Math.max(1, Math.round(size.value.width))}px`,
  height: `${Math.max(1, Math.round(size.value.height))}px`,
}))

function cancelTask() {
  if (!renderTask) return
  try {
    renderTask.cancel()
  } catch {
    /* 已结束的渲染任务取消时报错可忽略 */
  }
  renderTask = null
}

function cancelRender() {
  token += 1
  cancelTask()
}

async function render() {
  if (!visible.value || destroyed) return
  const current = ++token
  failed.value = false
  try {
    if (!page) page = await props.pdf.getPage(props.pageNumber)
    if (current !== token || destroyed) return

    const cssViewport = page.getViewport({ scale: props.scale })
    size.value = { width: cssViewport.width, height: cssViewport.height }
    await nextTick()

    const el = canvas.value
    if (!el || current !== token) return
    // 限制单页位图边长，避免 200% 缩放 + 高分屏时一张页面就吃掉上百 MB。
    const ratio = Math.max(
      1,
      Math.min(
        3,
        props.pixelRatio || 1,
        4096 / Math.max(1, cssViewport.width),
        4096 / Math.max(1, cssViewport.height),
      ),
    )
    const bitmap = page.getViewport({ scale: props.scale * ratio })
    el.width = Math.max(1, Math.floor(bitmap.width))
    el.height = Math.max(1, Math.floor(bitmap.height))
    el.style.width = `${cssViewport.width}px`
    el.style.height = `${cssViewport.height}px`

    cancelTask()
    const task = page.render({ canvas: el, viewport: bitmap, background: '#ffffff' })
    renderTask = task
    await task.promise
    if (current !== token || destroyed) return
    rendered.value = true
  } catch (e: any) {
    if (e?.name === 'RenderingCancelledException') return
    if (current === token) failed.value = true
  } finally {
    if (current === token) renderTask = null
  }
}

function releaseBitmap() {
  cancelRender()
  rendered.value = false
  const el = canvas.value
  if (el) {
    // 置零尺寸让浏览器立刻回收位图内存。
    el.width = 0
    el.height = 0
  }
  try {
    page?.cleanup()
  } catch {
    /* 渲染任务尚未完全取消时清理会抛错，下一轮渲染会重新初始化 */
  }
}

function onIntersect(entries: IntersectionObserverEntry[]) {
  const entry = entries[0]
  visible.value = entry.isIntersecting
  if (entry.isIntersecting) void render()
  else if (rendered.value) releaseBitmap()
}

watch(
  () => [props.scale, props.pixelRatio, props.baseWidth, props.baseHeight],
  () => {
    if (!page) {
      size.value = {
        width: props.baseWidth * props.scale,
        height: props.baseHeight * props.scale,
      }
    }
    if (visible.value) void render()
  },
)

onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') {
    visible.value = true
    void render()
    return
  }
  observer = new IntersectionObserver(onIntersect, { root: null, rootMargin: '900px 0px' })
  if (root.value) observer.observe(root.value)
})

onBeforeUnmount(() => {
  destroyed = true
  observer?.disconnect()
  observer = null
  cancelRender()
  page?.cleanup()
  page = null
})
</script>

<template>
  <div
    ref="root"
    class="pdf-page group relative shrink-0 overflow-hidden rounded-[3px] bg-white shadow-[0_1px_3px_rgba(15,23,42,0.16),0_10px_28px_-12px_rgba(15,23,42,0.25)]"
    :style="style"
    :data-page="pageNumber"
  >
    <canvas
      ref="canvas"
      v-show="rendered"
      class="block bg-white"
      :aria-label="`第 ${pageNumber} 页`"
    />
    <div
      v-if="!rendered"
      class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-white text-slate-300"
    >
      <template v-if="failed">
        <span class="text-[11px] text-rose-400">第 {{ pageNumber }} 页渲染失败</span>
      </template>
      <template v-else>
        <span
          class="pdf-page-skeleton absolute inset-0 animate-pulse bg-gradient-to-br from-slate-50 via-white to-slate-100"
        />
        <span class="relative text-[11px] tabular-nums text-slate-300">{{ pageNumber }}</span>
      </template>
    </div>
    <span
      v-else
      class="pointer-events-none absolute bottom-1.5 right-2 rounded bg-slate-900/35 px-1.5 py-0.5 text-[10px] tabular-nums text-white/90 opacity-0 transition-opacity duration-200 group-hover:opacity-100"
    >
      {{ pageNumber }}
    </span>
  </div>
</template>
