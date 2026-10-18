<script setup lang="ts">
/** 附件大屏预览：图片 / PDF / 音视频 / 文本在线查看，其余类型提供下载。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import OfficeFilePreview from '@/components/attachments/OfficeFilePreview.vue'
import type { DbAttachment } from '@/stores/noteDatabase'

const props = defineProps<{ open: boolean; file: DbAttachment | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const text = ref('')
const textLoading = ref(false)
const textError = ref('')
const textTruncated = ref(false)

const MAX_TEXT_BYTES = 512 * 1024

const ext = computed(() => {
  const name = props.file?.filename ?? ''
  return name.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase() ?? ''
})
const mime = computed(() => (props.file?.content_type ?? '').toLowerCase())
const kind = computed<
  'image' | 'pdf' | 'video' | 'audio' | 'text' | 'word' | 'excel' | 'ppt' | 'other'
>(() => {
  if (!props.file) return 'other'
  if (
    mime.value.startsWith('image/') ||
    ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif', 'svg'].includes(ext.value)
  ) {
    return 'image'
  }
  if (mime.value === 'application/pdf' || ext.value === 'pdf') return 'pdf'
  if (ext.value === 'docx' || mime.value.includes('wordprocessingml.document')) return 'word'
  if (
    ['xlsx', 'xlsm', 'xlsb', 'xls'].includes(ext.value) ||
    mime.value.includes('spreadsheetml.sheet') ||
    mime.value.includes('ms-excel')
  ) {
    return 'excel'
  }
  if (ext.value === 'pptx' || mime.value.includes('presentationml.presentation')) return 'ppt'
  if (
    mime.value.startsWith('video/') ||
    ['mp4', 'webm', 'mov', 'mkv', 'avi', 'm4v'].includes(ext.value)
  ) {
    return 'video'
  }
  if (mime.value.startsWith('audio/') || ['mp3', 'wav', 'ogg', 'flac', 'm4a'].includes(ext.value)) {
    return 'audio'
  }
  if (
    mime.value.startsWith('text/') ||
    mime.value.includes('json') ||
    mime.value.includes('xml') ||
    mime.value.includes('javascript') ||
    [
      'txt', 'md', 'markdown', 'csv', 'tsv', 'log', 'json', 'yaml', 'yml', 'xml',
      'js', 'mjs', 'ts', 'jsx', 'tsx', 'vue', 'py', 'sh', 'bash', 'zsh', 'sql',
      'css', 'scss', 'less', 'html', 'htm', 'ini', 'toml', 'conf', 'env', 'diff',
    ].includes(ext.value)
  ) {
    return 'text'
  }
  return 'other'
})

const sizeLabel = computed(() => {
  const size = props.file?.size ?? 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
})

async function loadText(url: string) {
  text.value = ''
  textError.value = ''
  textTruncated.value = false
  textLoading.value = true
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`读取失败（${res.status}）`)
    const blob = await res.blob()
    if (blob.size > MAX_TEXT_BYTES) {
      text.value = await blob.slice(0, MAX_TEXT_BYTES).text()
      textTruncated.value = true
    } else {
      text.value = await blob.text()
    }
  } catch (e: any) {
    textError.value = e?.message || '无法读取文件内容'
  } finally {
    textLoading.value = false
  }
}

watch(
  () => [props.open, props.file?.url] as const,
  ([open, url]) => {
    if (open && url && kind.value === 'text') void loadText(url)
  },
  { immediate: true },
)

function close() {
  emit('close')
}

function onKey(event: KeyboardEvent) {
  if (props.open && event.key === 'Escape') close()
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="html">
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-active-class="transition-opacity duration-150"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open && file"
        class="attachment-preview-overlay fixed inset-0 z-[300] flex flex-col bg-slate-950/85 backdrop-blur-sm"
        @click.self="close"
      >
        <header class="shrink-0 flex items-center gap-3 px-5 py-3 text-white/90">
          <KiwiIcon name="paperclip" :size="15" class="text-white/50" />
          <span class="min-w-0 truncate text-[13px] font-medium">{{ file.filename }}</span>
          <span class="shrink-0 text-[11px] text-white/40 tabular-nums">{{ sizeLabel }}</span>
          <div class="flex-1" />
          <a
            :href="file.url"
            :download="file.filename"
            class="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/10 px-2.5 py-1.5 text-[11.5px] text-white/80 transition-colors hover:bg-white/20 hover:text-white"
            @click.stop
          >
            <KiwiIcon name="download" :size="12" />
            下载
          </a>
          <button
            type="button"
            class="w-8 h-8 grid place-items-center rounded-lg text-white/60 transition-colors hover:bg-white/15 hover:text-white"
            title="关闭（Esc）"
            @click.stop="close"
          >
            <KiwiIcon name="close" :size="16" />
          </button>
        </header>

        <div class="flex-1 min-h-0 mx-4 mb-4 rounded-2xl bg-white shadow-2xl overflow-hidden">
          <div v-if="kind === 'image'" class="w-full h-full grid place-items-center bg-slate-100 p-2">
            <img :src="file.url" :alt="file.filename" class="max-w-full max-h-full object-contain" />
          </div>

          <iframe
            v-else-if="kind === 'pdf'"
            :src="file.url"
            class="w-full h-full border-0"
            :title="file.filename"
          />

          <OfficeFilePreview
            v-else-if="kind === 'word' || kind === 'excel' || kind === 'ppt'"
            :url="file.url"
            :filename="file.filename"
            :content-type="file.content_type"
            large
          />

          <div v-else-if="kind === 'video'" class="w-full h-full grid place-items-center bg-black">
            <video :src="file.url" controls class="max-w-full max-h-full" />
          </div>

          <div v-else-if="kind === 'audio'" class="w-full h-full grid place-items-center bg-slate-50">
            <audio :src="file.url" controls class="w-[min(560px,86%)]" />
          </div>

          <div v-else-if="kind === 'text'" class="w-full h-full flex flex-col bg-slate-950">
            <div class="flex-1 min-h-0 overflow-auto">
              <pre class="m-0 p-5 text-[12px] leading-relaxed text-slate-200 whitespace-pre-wrap break-words">{{
                textLoading ? '载入中…' : textError || text
              }}</pre>
            </div>
            <p
              v-if="textTruncated"
              class="shrink-0 border-t border-white/10 px-5 py-1.5 text-[10.5px] text-amber-300/80"
            >
              文件较大，仅显示前 512 KB，可下载后查看完整内容。
            </p>
          </div>

          <div v-else class="w-full h-full grid place-items-center bg-slate-50">
            <div class="text-center px-6">
              <KiwiIcon name="file" :size="40" class="mx-auto text-slate-300" />
              <p class="mt-3 text-[13px] font-medium text-slate-600">{{ file.filename }}</p>
              <p class="mt-1 text-[11.5px] text-slate-400">
                {{
                  ['doc', 'ppt'].includes(ext)
                    ? '旧版 Office 格式（.doc / .ppt）暂不支持在线预览，请下载后使用本地应用打开。'
                    : '该文件类型暂不支持在线预览，可下载后使用本地应用打开。'
                }}
              </p>
              <a
                :href="file.url"
                :download="file.filename"
                class="kiwi-btn-primary mt-4 !py-1.5 !text-xs"
              >
                <KiwiIcon name="download" :size="13" />
                下载文件
              </a>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
