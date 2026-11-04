<script setup lang="ts">
/** 附件正文预览：图片 / PDF / Office / 音视频 / 文本，其他类型提供下载。 */
import { computed, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import OfficeFilePreview from '@/components/attachments/OfficeFilePreview.vue'

const props = defineProps<{
  url: string
  filename: string
  contentType?: string
  size?: number
}>()

const text = ref('')
const textLoading = ref(false)
const textError = ref('')
const textTruncated = ref(false)

const MAX_TEXT_BYTES = 512 * 1024

const ext = computed(() => props.filename.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase() ?? '')
const mime = computed(() => (props.contentType ?? '').toLowerCase())
const kind = computed<
  'image' | 'pdf' | 'video' | 'audio' | 'text' | 'word' | 'excel' | 'ppt' | 'other'
>(() => {
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
  () => [props.url, kind.value] as const,
  ([url, current]) => {
    if (url && current === 'text') void loadText(url)
  },
  { immediate: true },
)
</script>

<template>
  <div class="w-full h-full min-h-0">
    <div v-if="kind === 'image'" class="w-full h-full grid place-items-center bg-slate-100 p-2">
      <img :src="url" :alt="filename" class="max-w-full max-h-full object-contain" />
    </div>

    <iframe
      v-else-if="kind === 'pdf'"
      :src="url"
      class="w-full h-full border-0"
      :title="filename"
    />

    <OfficeFilePreview
      v-else-if="kind === 'word' || kind === 'excel' || kind === 'ppt'"
      :url="url"
      :filename="filename"
      :content-type="contentType || ''"
      large
    />

    <div v-else-if="kind === 'video'" class="w-full h-full grid place-items-center bg-black">
      <video :src="url" controls class="max-w-full max-h-full" />
    </div>

    <div v-else-if="kind === 'audio'" class="w-full h-full grid place-items-center bg-slate-50">
      <audio :src="url" controls class="w-[min(560px,86%)]" />
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
        <p class="mt-3 text-[13px] font-medium text-slate-600">{{ filename }}</p>
        <p class="mt-1 text-[11.5px] text-slate-400">
          {{
            ['doc', 'ppt'].includes(ext)
              ? '旧版 Office 格式（.doc / .ppt）暂不支持在线预览，请下载后使用本地应用打开。'
              : '该文件类型暂不支持在线预览，可下载后使用本地应用打开。'
          }}
        </p>
        <a
          :href="url"
          :download="filename"
          class="kiwi-btn-primary mt-4 !py-1.5 !text-xs"
        >
          <KiwiIcon name="download" :size="13" />
          下载文件
        </a>
      </div>
    </div>
  </div>
</template>
