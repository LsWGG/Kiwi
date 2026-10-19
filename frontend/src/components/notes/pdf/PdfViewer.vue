<script setup lang="ts">
/**
 * 只读导入用的 PDF 预览器：用 PDF.js 把页面画进当前文档的 canvas，
 * 而不是 iframe 内嵌浏览器阅读器。
 *
 * 这样阅读模式的激光点、演示笔画布能真正覆盖 PDF，滚轮与滚动也由
 * 外层的阅读滚动容器统一处理，批注会随内容一起滚动。
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import PdfPageCanvas from './PdfPageCanvas.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

GlobalWorkerOptions.workerSrc = workerUrl

const props = withDefaults(
  defineProps<{
    url: string
    /** 阅读工具条的缩放倍数（1 = 适应宽度）。 */
    zoom?: number
    /** 嵌在外层滚动容器里：自身不滚动，页面按自然高度铺开。 */
    embedded?: boolean
  }>(),
  { zoom: 1, embedded: false },
)

const emit = defineEmits<{
  (e: 'loaded', pages: number): void
  (e: 'error', message: string): void
}>()

const viewerEl = ref<HTMLElement | null>(null)
const doc = shallowRef<PDFDocumentProxy | null>(null)
const loading = ref(true)
const error = ref('')
const pageCount = ref(0)
const firstPageSize = ref({ width: 595, height: 842 })
const containerWidth = ref(0)
const progress = ref(0)

let task: PDFDocumentLoadingTask | null = null
let observer: ResizeObserver | null = null
let generation = 0

/** 页面在容器里留 24px 左右边距，保持纸张居中的呼吸感。 */
const H_PADDING = 48

/** 适应容器宽度后的基础缩放；用户缩放再乘在其上。 */
const baseScale = computed(() => {
  const width = containerWidth.value - H_PADDING
  if (width <= 0 || !firstPageSize.value.width) return 1
  return Math.min(2.5, Math.max(0.18, width / firstPageSize.value.width))
})

const scale = computed(() => baseScale.value * (props.zoom || 1))
const pixelRatio = computed(() =>
  typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1,
)

const pages = computed(() => Array.from({ length: pageCount.value }, (_, i) => i + 1))

async function load() {
  const run = ++generation
  loading.value = true
  error.value = ''
  pageCount.value = 0
  progress.value = 0
  const previous = doc.value
  doc.value = null
  if (task) {
    void task.destroy().catch(() => undefined)
    task = null
  }
  if (previous) void previous.loadingTask.destroy().catch(() => undefined)

  try {
    task = getDocument({
      url: props.url,
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/',
      wasmUrl: '/pdfjs/wasm/',
      iccUrl: '/pdfjs/iccs/',
      useWasm: true,
    })
    task.onProgress = ({ loaded, total }: { loaded: number; total: number }) => {
      if (run === generation && total > 0) progress.value = Math.min(99, Math.round((loaded / total) * 100))
    }
    const pdf = await task.promise
    if (run !== generation) {
      void pdf.loadingTask.destroy().catch(() => undefined)
      return
    }
    // 用首页尺寸做所有页的占位；同一份 PDF 绝大多数页面尺寸一致。
    const first = await pdf.getPage(1)
    const view = first.getViewport({ scale: 1 })
    firstPageSize.value = { width: view.width, height: view.height }
    pageCount.value = pdf.numPages
    doc.value = pdf
    loading.value = false
    emit('loaded', pdf.numPages)
    emit('error', '')
  } catch (e: any) {
    if (run !== generation) return
    loading.value = false
    error.value = e?.message || 'PDF 加载失败'
    emit('error', error.value)
  }
}

function observeWidth() {
  observer?.disconnect()
  observer = null
  const el = viewerEl.value
  if (!el) return
  containerWidth.value = el.clientWidth
  observer = new ResizeObserver(() => {
    containerWidth.value = viewerEl.value?.clientWidth ?? 0
  })
  observer.observe(el)
}

watch(
  () => props.url,
  () => {
    observeWidth()
    void load()
  },
)

onMounted(() => {
  observeWidth()
  void load()
})

onBeforeUnmount(() => {
  generation += 1
  observer?.disconnect()
  observer = null
  if (task) void task.destroy().catch(() => undefined)
  task = null
  if (doc.value) void doc.value.loadingTask.destroy().catch(() => undefined)
  doc.value = null
})
</script>

<template>
  <div
    ref="viewerEl"
    class="pdf-viewer relative w-full"
    :class="embedded ? '' : 'h-full overflow-auto'"
  >
    <div v-if="loading" class="grid min-h-[420px] place-items-center px-6 py-16">
      <div class="text-center">
        <KiwiIcon name="loader" :size="22" spin class="mx-auto mb-3 text-kiwi-400" />
        <p class="text-[12px] text-slate-500">正在加载 PDF…</p>
        <div class="mx-auto mt-3 h-1 w-40 overflow-hidden rounded-full bg-slate-200">
          <div
            class="h-full rounded-full bg-kiwi-400 transition-[width] duration-200"
            :style="{ width: `${progress}%` }"
          />
        </div>
      </div>
    </div>

    <div v-else-if="error" class="grid min-h-[420px] place-items-center px-6 py-16">
      <div class="max-w-sm rounded-2xl border border-rose-100 bg-white/90 p-6 text-center shadow-sm">
        <KiwiIcon name="alert" :size="26" class="mx-auto text-rose-300" />
        <p class="mt-3 text-[13px] font-medium text-slate-600">PDF 无法在页面内渲染</p>
        <p class="mt-1 break-words text-[11px] leading-relaxed text-slate-400">{{ error }}</p>
        <p class="mt-1 text-[11px] text-slate-400">可点击右上角在新标签页打开原始文件。</p>
      </div>
    </div>

    <div v-else-if="doc" class="pdf-pages">
      <PdfPageCanvas
        v-for="page in pages"
        :key="page"
        :pdf="doc!"
        :page-number="page"
        :scale="scale"
        :pixel-ratio="pixelRatio"
        :base-width="firstPageSize.width"
        :base-height="firstPageSize.height"
      />
    </div>
  </div>
</template>

<style scoped>
.pdf-viewer {
  background:
    radial-gradient(1200px 500px at 50% -10%, rgba(148, 163, 184, 0.13), transparent 70%),
    #eef1f5;
}
.pdf-pages {
  display: flex;
  width: max-content;
  min-width: 100%;
  box-sizing: border-box;
  flex-direction: column;
  align-items: center;
  gap: 18px;
  padding: 20px 24px 44px;
}
</style>
