<script setup lang="ts">
/** 导入笔记的原始文件查看器：PDF / 图片内嵌预览，Markdown / 纯文本就地渲染，其余提供下载。 */
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

// PDF.js 体积较大，只有真的打开只读 PDF 时才加载对应分包。
const PdfViewer = defineAsyncComponent(() => import('@/components/notes/pdf/PdfViewer.vue'))

const props = withDefaults(
  defineProps<{
    noteId: string
    kbId: string | null
    filename?: string
    contentType?: string
    size?: number
    /**
     * 嵌入只读阅读区：不再自己滚动，页面按自然高度铺开，
     * 由外层阅读滚动容器统一滚动，批注层才能跟着内容走。
     */
    embedded?: boolean
    /** 阅读工具条的缩放倍数，PDF 页面直接按此比例渲染。 */
    zoom?: number
  }>(),
  { filename: '', contentType: '', size: 0, embedded: false, zoom: 1 },
)

const ext = computed(() => {
  const name = props.filename || ''
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : ''
})

const kind = computed<'pdf' | 'image' | 'text' | 'markdown' | 'other'>(() => {
  const ct = (props.contentType || '').toLowerCase()
  if (ct.includes('pdf') || ext.value === 'pdf') return 'pdf'
  if (
    ct.startsWith('image/') ||
    ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tif', 'tiff', 'svg'].includes(ext.value)
  ) {
    return 'image'
  }
  if (['md', 'markdown'].includes(ext.value)) return 'markdown'
  if (ct.startsWith('text/') || ['txt', 'text', 'csv', 'json', 'log', 'html', 'htm'].includes(ext.value)) {
    return 'text'
  }
  return 'other'
})

const fileUrl = computed(() => {
  const base = `/api/notes/${props.noteId}/source-file`
  return props.kbId ? `${base}?kb_id=${encodeURIComponent(props.kbId)}` : base
})

const filename = computed(() => props.filename || '原始文件')

const sizeText = computed(() => {
  const bytes = Number(props.size) || 0
  if (bytes <= 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
})

const pdfPages = ref(0)

const textContent = ref('')
const textLoading = ref(false)
const textError = ref('')

async function loadText() {
  if (kind.value !== 'text' && kind.value !== 'markdown') return
  textLoading.value = true
  textError.value = ''
  try {
    const res = await fetch(fileUrl.value)
    if (!res.ok) throw new Error(`读取失败（${res.status}）`)
    textContent.value = await res.text()
  } catch (e: any) {
    textError.value = e.message || '读取原始文件失败'
  } finally {
    textLoading.value = false
  }
}

watch(
  () => [fileUrl.value, kind.value],
  () => {
    textContent.value = ''
    void loadText()
  },
  { immediate: true },
)

function openInNewTab() {
  window.open(fileUrl.value, '_blank', 'noopener')
}

function download() {
  // 服务端以 inline 返回；用 download 属性在同一源下触发下载。
  const a = document.createElement('a')
  a.href = fileUrl.value
  a.download = filename.value
  document.body.appendChild(a)
  a.click()
  a.remove()
  toast.success('已开始下载原始文件')
}
</script>

<template>
  <div
    class="flex flex-col bg-slate-100/50"
    :class="embedded ? 'min-h-full' : 'h-full min-h-0'"
  >
    <div
      class="flex h-10 shrink-0 items-center gap-2 border-b border-slate-200/70 px-3"
      :class="embedded ? 'sticky top-0 z-20 bg-white/90 backdrop-blur-md' : 'bg-white/70'"
    >
      <KiwiIcon
        :name="kind === 'pdf' ? 'fileText' : kind === 'image' ? 'image' : 'fileImport'"
        :size="14"
        class="shrink-0 text-emerald-500"
      />
      <span class="min-w-0 truncate text-[12px] font-medium text-slate-600" :title="filename">
        {{ filename }}
      </span>
      <span v-if="sizeText" class="shrink-0 text-[10px] tabular-nums text-slate-400">
        {{ sizeText }}
      </span>
      <span v-if="kind === 'pdf' && pdfPages" class="shrink-0 text-[10px] tabular-nums text-slate-400">
        {{ pdfPages }} 页
      </span>
      <div class="flex-1" />
      <button
        type="button"
        class="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
        title="在新标签页打开"
        @click="openInNewTab"
      >
        <KiwiIcon name="arrowUpRight" :size="13" />
      </button>
      <button
        type="button"
        class="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
        title="下载原始文件"
        @click="download"
      >
        <KiwiIcon name="download" :size="13" />
      </button>
    </div>

    <div :class="embedded ? '' : 'min-h-0 flex-1 overflow-hidden'">
      <PdfViewer
        v-if="kind === 'pdf' && embedded"
        :url="fileUrl"
        :zoom="zoom"
        embedded
        @loaded="pdfPages = $event"
      />
      <iframe
        v-else-if="kind === 'pdf'"
        :src="fileUrl"
        :title="filename"
        class="h-full w-full border-0 bg-white"
      />
      <div
        v-else-if="kind === 'image'"
        :class="embedded ? 'px-5 py-5' : 'h-full overflow-auto p-5'"
      >
        <img
          :src="fileUrl"
          :alt="filename"
          class="mx-auto rounded-lg bg-white object-contain shadow-sm"
          :class="embedded ? 'max-w-full' : 'max-h-full max-w-full'"
        />
      </div>
      <div
        v-else-if="kind === 'markdown' || kind === 'text'"
        :class="embedded ? 'px-6 py-5' : 'h-full overflow-auto px-6 py-5'"
      >
        <div v-if="textLoading" class="py-12 text-center text-[11px] text-slate-400">
          <KiwiIcon name="loader" :size="16" spin class="mx-auto mb-1.5" />
          读取原始文件…
        </div>
        <p v-else-if="textError" class="py-12 text-center text-[11px] text-rose-500">
          {{ textError }}
        </p>
        <MarkdownView v-else-if="kind === 'markdown'" :content="textContent" />
        <pre
          v-else
          class="whitespace-pre-wrap break-words rounded-xl border border-slate-200/70 bg-white/80 p-4 text-[12px] leading-relaxed text-slate-600"
        >{{ textContent }}</pre>
      </div>
      <div
        v-else
        class="grid place-items-center px-6"
        :class="embedded ? 'min-h-[420px] py-16' : 'h-full'"
      >
        <div class="max-w-sm rounded-2xl border border-slate-200/70 bg-white/80 p-6 text-center shadow-sm">
          <KiwiIcon name="fileImport" :size="30" class="mx-auto text-slate-300" />
          <p class="mt-3 text-[13px] font-medium text-slate-600">{{ filename }}</p>
          <p class="mt-1 text-[11px] leading-relaxed text-slate-400">
            该格式无法在浏览器中内嵌预览。可以下载后用本地应用打开，或在新标签页尝试查看。
          </p>
          <div class="mt-4 flex justify-center gap-2">
            <button class="kiwi-btn-secondary !py-1.5 !px-3 !text-[11px]" @click="openInNewTab">
              新标签页打开
            </button>
            <button class="kiwi-btn-primary !py-1.5 !px-3 !text-[11px]" @click="download">
              <KiwiIcon name="download" :size="12" /> 下载
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
