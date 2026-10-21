<script setup lang="ts">
/**
 * 只读导入用的 PDF 预览器：用 PDF.js 把页面画进当前文档的 canvas，
 * 而不是 iframe 内嵌浏览器阅读器。
 *
 * 这样阅读模式的激光点、演示笔画布能真正覆盖 PDF，滚轮与滚动也由
 * 外层的阅读滚动容器统一处理，批注会随内容一起滚动。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
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
/** 加密 PDF：等待用户输入密码。 */
const needPassword = ref(false)
const password = ref('')
const passwordError = ref('')
/** PDF.js 解析失败时，可退回浏览器内置阅读器。 */
const native = ref(false)
const passwordEl = ref<HTMLInputElement | null>(null)

let task: PDFDocumentLoadingTask | null = null
let observer: ResizeObserver | null = null
let generation = 0
let passwordUpdate: ((value: string) => void) | null = null
let watchdog: ReturnType<typeof setTimeout> | null = null

/** 超过这个时间没有下载进度就认定卡死，避免一直转圈。 */
const LOAD_TIMEOUT_MS = 30_000

function clearWatchdog() {
  if (watchdog) {
    clearTimeout(watchdog)
    watchdog = null
  }
}

function armWatchdog(run: number) {
  clearWatchdog()
  watchdog = setTimeout(() => {
    if (run !== generation || !loading.value) return
    fail('加载超时：文件过大、网络中断或 PDF 格式不受支持')
  }, LOAD_TIMEOUT_MS)
}

function fail(message: string) {
  // 让仍在等待的 task.promise 回归时不再覆盖当前状态。
  generation += 1
  clearWatchdog()
  passwordUpdate = null
  needPassword.value = false
  if (task) {
    void task.destroy().catch(() => undefined)
    task = null
  }
  doc.value = null
  loading.value = false
  error.value = message
  emit('error', message)
}

function submitPassword() {
  const update = passwordUpdate
  if (!update) return
  passwordUpdate = null
  needPassword.value = false
  passwordError.value = ''
  loading.value = true
  armWatchdog(generation)
  update(password.value)
  password.value = ''
}

function cancelPassword() {
  passwordUpdate = null
  needPassword.value = false
  password.value = ''
  fail('已取消输入密码')
}

/** 浏览器内置阅读器：某些 PDF.js 不支持的格式（如 XFA 表单）由浏览器处理。 */
function openNative() {
  generation += 1
  clearWatchdog()
  passwordUpdate = null
  needPassword.value = false
  if (task) {
    void task.destroy().catch(() => undefined)
    task = null
  }
  doc.value = null
  loading.value = false
  error.value = ''
  native.value = true
}

function retry() {
  native.value = false
  void load()
}

function openInNewTab() {
  window.open(props.url, '_blank', 'noopener')
}

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
  needPassword.value = false
  password.value = ''
  passwordError.value = ''
  passwordUpdate = null
  native.value = false
  clearWatchdog()
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
      if (run !== generation) return
      armWatchdog(run)
      if (total > 0) progress.value = Math.min(99, Math.round((loaded / total) * 100))
    }
    // 加密 PDF：没有这个回调时 task.promise 会直接拒绝，界面只剩错误提示。
    task.onPassword = (updatePassword: (value: string) => void, reason: number) => {
      if (run !== generation) return
      clearWatchdog()
      passwordUpdate = updatePassword
      passwordError.value = reason === 2 ? '密码不正确，请重试' : ''
      loading.value = false
      needPassword.value = true
      void nextTick(() => passwordEl.value?.focus())
    }
    armWatchdog(run)
    const pdf = await task.promise
    if (run !== generation) {
      void pdf.loadingTask.destroy().catch(() => undefined)
      return
    }
    // 用首页尺寸做所有页的占位；同一份 PDF 绝大多数页面尺寸一致。
    const first = await pdf.getPage(1)
    if (run !== generation) return
    const view = first.getViewport({ scale: 1 })
    firstPageSize.value = { width: view.width, height: view.height }
    pageCount.value = pdf.numPages
    doc.value = pdf
    loading.value = false
    clearWatchdog()
    emit('loaded', pdf.numPages)
    emit('error', '')
  } catch (e: any) {
    if (run !== generation) return
    if (needPassword.value) return
    fail(e?.message || 'PDF 加载失败')
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
    <div v-if="needPassword" class="grid min-h-[420px] place-items-center px-6 py-16">
      <form
        class="w-full max-w-sm rounded-2xl border border-slate-200/80 bg-white/90 p-6 text-center shadow-sm"
        @submit.prevent="submitPassword"
      >
        <KiwiIcon name="lock" :size="24" class="mx-auto text-kiwi-400" />
        <p class="mt-3 text-[13px] font-medium text-slate-600">该 PDF 已加密</p>
        <p class="mt-1 text-[11px] text-slate-400">输入打开密码后即可在页面内阅读</p>
        <input
          ref="passwordEl"
          v-model="password"
          type="password"
          autocomplete="off"
          class="kiwi-input mt-3 w-full text-center"
          placeholder="PDF 密码"
        />
        <p v-if="passwordError" class="mt-1.5 text-[11px] text-rose-500">{{ passwordError }}</p>
        <div class="mt-4 flex justify-center gap-2">
          <button type="button" class="kiwi-btn-secondary !px-3 !py-1.5 !text-[11px]" @click="cancelPassword">
            取消
          </button>
          <button type="submit" class="kiwi-btn-primary !px-3 !py-1.5 !text-[11px]">解锁并加载</button>
        </div>
      </form>
    </div>

    <div v-else-if="loading" class="grid min-h-[420px] place-items-center px-6 py-16">
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
        <p class="mt-1 text-[11px] text-slate-400">
          可重试，或改用浏览器内置阅读器 / 新标签页打开。
        </p>
        <div class="mt-4 flex flex-wrap justify-center gap-2">
          <button class="kiwi-btn-secondary !px-3 !py-1.5 !text-[11px]" @click="retry">重试</button>
          <button class="kiwi-btn-secondary !px-3 !py-1.5 !text-[11px]" @click="openNative">
            内置阅读器
          </button>
          <button class="kiwi-btn-primary !px-3 !py-1.5 !text-[11px]" @click="openInNewTab">
            新标签页打开
          </button>
        </div>
      </div>
    </div>

    <iframe
      v-else-if="native"
      :src="url"
      title="PDF 预览"
      class="w-full border-0 bg-white"
      :class="embedded ? 'h-[70vh] min-h-[480px]' : 'h-full'"
    />

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
