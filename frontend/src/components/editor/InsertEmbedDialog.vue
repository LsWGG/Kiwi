<script setup lang="ts">
/**
 * 插入链接 / 附件的统一弹窗。
 * 展示方式不在这里选择：先以内容卡片 / 内联预览插入，
 * 之后可在正文的嵌入块上随时切换「内容 / 标题超链接 / 网页嵌入」。
 */
import { ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import { fetchLinkMeta, type LinkMeta } from '@/api/links'

export type EmbedTab = 'link' | 'file'

const props = defineProps<{
  open: boolean
  tab: EmbedTab
  initialUrl?: string
  initialFiles?: File[]
  selectionText?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (
    e: 'insert-link',
    payload: { url: string; title: string; meta: LinkMeta | null },
  ): void
  (e: 'insert-files', payload: { files: File[] }): void
}>()

const tab = ref<EmbedTab>('link')
const url = ref('')
const title = ref('')
const meta = ref<LinkMeta | null>(null)
const loading = ref(false)
const error = ref('')
const files = ref<File[]>([])
const dragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

function normalizeUrl(raw: string): string {
  let value = raw.trim()
  if (!value) return ''
  if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(value)) value = `https://${value}`
  return value
}

function reset() {
  tab.value = props.tab
  url.value = props.initialUrl ?? ''
  title.value = ''
  meta.value = null
  loading.value = false
  error.value = ''
  files.value = [...(props.initialFiles ?? [])]
  dragging.value = false
}

watch(
  () => props.open,
  (open) => {
    if (open) reset()
  },
  { immediate: true },
)

watch(
  () => props.tab,
  (value) => {
    if (props.open) tab.value = value
  },
)

watch(tab, () => {
  error.value = ''
})

async function loadMeta(force = false) {
  const target = normalizeUrl(url.value)
  if (!target || loading.value) return
  if (meta.value && !force) return
  url.value = target
  loading.value = true
  error.value = ''
  try {
    const result = await fetchLinkMeta(target)
    meta.value = result
    if (!title.value.trim()) title.value = result.title
    if (result.fetch_status === 'failed') {
      error.value = result.error
        ? `未能读取网页信息：${result.error}`
        : '未能读取网页信息，将使用链接地址作为标题'
    }
  } catch (e: any) {
    meta.value = null
    error.value = e?.message || '链接解析失败'
  } finally {
    loading.value = false
  }
}

function addFiles(list: FileList | File[] | null) {
  if (!list) return
  const incoming = Array.from(list)
  const map = new Map(files.value.map((f) => [`${f.name}:${f.size}:${f.lastModified}`, f]))
  for (const file of incoming) map.set(`${file.name}:${file.size}:${file.lastModified}`, file)
  files.value = [...map.values()]
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  addFiles(input.files)
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragging.value = false
  addFiles(event.dataTransfer?.files ?? null)
}

function removeFile(index: number) {
  files.value = files.value.filter((_, i) => i !== index)
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

async function submitLink() {
  const target = normalizeUrl(url.value)
  if (!target) {
    error.value = '请输入链接地址'
    return
  }
  if (!/^https?:\/\//i.test(target)) {
    error.value = '仅支持 http / https 链接'
    return
  }
  await loadMeta(true)
  emit('insert-link', {
    url: normalizeUrl(url.value),
    title: title.value.trim() || meta.value?.title || target,
    meta: meta.value,
  })
}

function submitFiles() {
  if (!files.value.length) {
    error.value = '请选择要插入的文件'
    return
  }
  emit('insert-files', { files: [...files.value] })
}
</script>

<template>
  <KiwiModal
    :open="open"
    :title="tab === 'link' ? '插入链接' : '插入附件'"
    max-w="max-w-xl"
    @close="emit('close')"
  >
    <div class="mb-4 flex gap-1 rounded-xl bg-slate-100/80 p-1">
      <button
        type="button"
        class="embed-tab"
        :class="tab === 'link' ? 'is-active' : ''"
        @click="tab = 'link'"
      >
        <KiwiIcon name="link2" :size="13" />
        链接
      </button>
      <button
        type="button"
        class="embed-tab"
        :class="tab === 'file' ? 'is-active' : ''"
        @click="tab = 'file'"
      >
        <KiwiIcon name="paperclip" :size="13" />
        附件
      </button>
    </div>

    <!-- 链接 -->
    <div v-if="tab === 'link'" class="space-y-3">
      <label class="embed-label">
        <span>链接地址</span>
        <div class="flex gap-2">
          <input
            v-model="url"
            class="embed-input"
            placeholder="https://example.com/article"
            @blur="loadMeta()"
            @keydown.enter.prevent="loadMeta(true)"
          />
          <button
            type="button"
            class="kiwi-btn-ghost shrink-0 !px-2.5"
            :disabled="loading || !url.trim()"
            title="读取网页标题与摘要"
            @click="loadMeta(true)"
          >
            <KiwiIcon :name="loading ? 'loader' : 'refresh'" :size="13" :spin="loading" />
          </button>
        </div>
      </label>

      <label class="embed-label">
        <span>标题 <em>（留空自动获取）</em></span>
        <input v-model="title" class="embed-input" placeholder="链接标题" />
      </label>

      <div v-if="meta?.excerpt" class="rounded-lg border border-slate-200/70 bg-slate-50/70 px-3 py-2 text-[11.5px] leading-relaxed text-slate-500">
        {{ meta.excerpt }}
      </div>

      <p class="rounded-lg border border-slate-200/70 bg-slate-50/60 px-3 py-2 text-[11px] leading-relaxed text-slate-400">
        插入后可在正文的卡片上切换展示方式：内容卡片、标题超链接或网页内容嵌入。
      </p>
    </div>

    <!-- 附件 -->
    <div v-else class="space-y-3">
      <div
        class="embed-drop"
        :class="dragging ? 'is-dragging' : ''"
        @click="fileInput?.click()"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <KiwiIcon name="upload" :size="22" class="text-slate-300" />
        <p class="mt-1.5 text-[12.5px] text-slate-600">
          {{ dragging ? '松开鼠标添加文件' : '点击选择文件，或拖拽到这里' }}
        </p>
        <p class="mt-0.5 text-[11px] text-slate-400">支持 Word / Excel / PPT / PDF / 图片 / 音视频等，单个不超过 20MB</p>
        <input ref="fileInput" type="file" multiple class="hidden" @change="onPick" />
      </div>

      <div v-if="files.length" class="space-y-1.5">
        <div v-for="(file, index) in files" :key="`${file.name}-${index}`" class="embed-file-row">
          <KiwiIcon name="file" :size="13" class="shrink-0 text-slate-400" />
          <span class="min-w-0 flex-1 truncate text-[12px] text-slate-600">{{ file.name }}</span>
          <span class="shrink-0 text-[10.5px] tabular-nums text-slate-400">{{ formatSize(file.size) }}</span>
          <button
            type="button"
            class="grid h-6 w-6 shrink-0 place-items-center rounded-md text-slate-400 hover:bg-white hover:text-rose-500"
            title="移除"
            @click.stop="removeFile(index)"
          >
            <KiwiIcon name="close" :size="11" />
          </button>
        </div>
      </div>

      <p class="rounded-lg border border-slate-200/70 bg-slate-50/60 px-3 py-2 text-[11px] leading-relaxed text-slate-400">
        插入后可在正文的文件卡片上切换为「内容预览」或「标题超链接」。
      </p>
    </div>

    <p v-if="error" class="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-[11.5px] text-rose-500">
      {{ error }}
    </p>

    <div class="mt-5 flex justify-end gap-2">
      <button type="button" class="kiwi-btn-ghost" @click="emit('close')">取消</button>
      <button
        type="button"
        class="kiwi-btn-primary"
        :disabled="loading || (tab === 'link' ? !url.trim() : !files.length)"
        @click="tab === 'link' ? submitLink() : submitFiles()"
      >
        <KiwiIcon name="plus" :size="13" />
        插入
      </button>
    </div>
  </KiwiModal>
</template>

<style scoped>
.embed-tab {
  @apply flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] text-slate-500 transition-colors hover:text-slate-700;
}
.embed-tab.is-active {
  @apply bg-white text-kiwi-700 shadow-sm;
}
.embed-label {
  @apply mb-1 block text-[11.5px] font-medium text-slate-500;
}
.embed-label em {
  @apply not-italic font-normal text-slate-400;
}
.embed-input {
  @apply h-9 w-full rounded-lg border border-slate-200 bg-white/80 px-2.5 text-[12.5px] text-slate-700 outline-none transition-colors placeholder:text-slate-300 focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-200/60;
}
.embed-drop {
  @apply flex cursor-pointer flex-col items-center rounded-xl border border-dashed border-slate-300 bg-slate-50/50 px-4 py-6 text-center transition-colors hover:border-kiwi-300 hover:bg-kiwi-50/40;
}
.embed-drop.is-dragging {
  @apply border-kiwi-400 bg-kiwi-50;
}
.embed-file-row {
  @apply flex items-center gap-2 rounded-lg border border-slate-200/70 bg-white/80 px-2.5 py-1.5;
}
</style>
