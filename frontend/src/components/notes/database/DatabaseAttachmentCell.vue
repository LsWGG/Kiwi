<script setup lang="ts">
/** 数据表附件单元格：多文件上传（不限类型）、附件芯片与大屏预览。 */
import { computed, ref, watch } from 'vue'
import { toast } from '@/components/ui/toast'
import { uploadAttachment } from '@/api/attachments'
import { useKbsStore } from '@/stores/kbs'
import { useNoteDatabaseStore } from '@/stores/noteDatabase'
import type { DbAttachment } from '@/stores/noteDatabase'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import AttachmentPreview from './AttachmentPreview.vue'

const props = defineProps<{ value: any }>()
const emit = defineEmits<{ (e: 'update', value: DbAttachment[] | null): void }>()

const kbs = useKbsStore()
const database = useNoteDatabaseStore()

const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(0)
const previewFile = ref<DbAttachment | null>(null)
const previewOpen = ref(false)
const list = ref<DbAttachment[]>([])

watch(
  () => props.value,
  (value) => {
    list.value = Array.isArray(value)
      ? value.filter((item) => item && typeof item.url === 'string')
      : []
  },
  { immediate: true },
)

const uploadingLabel = computed(() =>
  uploading.value > 0 ? `上传中 ${uploading.value}…` : '',
)

function pickFiles() {
  fileInput.value?.click()
}

function sizeLabel(size: number) {
  if (!Number.isFinite(size) || size < 1024) return `${size || 0} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function commit(next: DbAttachment[]) {
  list.value = next
  emit('update', next.length ? next : null)
}

async function onFilesPicked(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return

  for (const file of files) {
    if (file.size > 20 * 1024 * 1024) {
      toast.error(`${file.name} 超过 20MB 上限`)
      continue
    }
    uploading.value += 1
    try {
      const uploaded = await uploadAttachment(file, database.noteId, kbs.currentKbId)
      const item: DbAttachment = {
        id: uploaded.id,
        filename: uploaded.filename,
        url: uploaded.url,
        content_type: uploaded.content_type,
        size: uploaded.size,
      }
      // 用函数式合并，避免连续上传时基于旧快照覆盖
      list.value = [...list.value, item]
      emit('update', list.value)
    } catch (e: any) {
      toast.error(e?.message || `${file.name} 上传失败`)
    } finally {
      uploading.value -= 1
    }
  }
}

function removeAttachment(index: number) {
  const next = list.value.filter((_, i) => i !== index)
  commit(next)
}

function openPreview(file: DbAttachment) {
  previewFile.value = file
  previewOpen.value = true
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-1 min-w-0 py-0.5">
    <button
      v-for="(file, index) in list"
      :key="file.id || `${file.url}-${index}`"
      type="button"
      class="db-attach-chip group/chip"
      :title="`${file.filename}（${sizeLabel(file.size)}）点击大屏预览`"
      @click.stop="openPreview(file)"
    >
      <KiwiIcon name="paperclip" :size="10" class="shrink-0 opacity-60" />
      <span class="truncate max-w-[150px]">{{ file.filename }}</span>
      <span
        class="db-attach-remove shrink-0 rounded-full p-px opacity-50 hover:bg-slate-200 hover:opacity-100"
        title="移除附件"
        @click.stop="removeAttachment(index)"
      >
        <KiwiIcon name="close" :size="9" />
      </span>
    </button>

    <span v-if="uploadingLabel" class="text-[10.5px] text-slate-400">{{ uploadingLabel }}</span>

    <button
      type="button"
      class="db-attach-add"
      :title="list.length ? '继续上传附件' : '上传附件（可多选，不限类型）'"
      @click.stop="pickFiles"
    >
      <KiwiIcon :name="list.length ? 'upload' : 'paperclip'" :size="11" />
      <span v-if="!list.length">上传附件</span>
    </button>

    <input
      ref="fileInput"
      type="file"
      multiple
      class="hidden"
      @change="onFilesPicked"
    />

    <AttachmentPreview :open="previewOpen" :file="previewFile" @close="previewOpen = false" />
  </div>
</template>

<style scoped>
.db-attach-chip {
  @apply inline-flex items-center gap-1 max-w-full rounded-md border border-slate-200/80 bg-white/80 px-1.5 py-0.5 text-[10.5px] leading-4 text-slate-600 transition-colors hover:border-kiwi-300 hover:bg-kiwi-50/60 hover:text-kiwi-700;
}
.db-attach-add {
  @apply inline-flex items-center gap-1 rounded-md border border-dashed border-slate-300 px-1.5 py-0.5 text-[10.5px] leading-4 text-slate-400 transition-colors hover:border-kiwi-400 hover:text-kiwi-600;
}
</style>
