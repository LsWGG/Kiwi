<script setup lang="ts">
/** 分栏中的文件窗口：正文复用附件预览，顶部保留下载 / 新窗口打开。 */
import { computed } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import AttachmentFileBody from '@/components/attachments/AttachmentFileBody.vue'

const props = defineProps<{
  url: string
  filename: string
  contentType: string
  size?: number
}>()

const sizeLabel = computed(() => {
  const size = props.size ?? 0
  if (!size) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
})
</script>

<template>
  <div class="h-full min-h-0 flex flex-col bg-white">
    <div class="shrink-0 flex items-center gap-2 border-b border-slate-200/70 bg-slate-50/70 px-2 py-1">
      <span class="min-w-0 flex-1 truncate text-[10.5px] text-slate-400" :title="filename">
        {{ filename }}
        <span v-if="sizeLabel" class="ml-1 tabular-nums text-slate-300">{{ sizeLabel }}</span>
      </span>
      <a
        :href="url"
        :download="filename"
        class="grid h-6 w-6 place-items-center rounded text-slate-400 transition-colors hover:bg-white hover:text-kiwi-600"
        title="下载文件"
        @click.stop
      >
        <KiwiIcon name="download" :size="12" />
      </a>
      <a
        :href="url"
        target="_blank"
        rel="noopener noreferrer"
        class="grid h-6 w-6 place-items-center rounded text-slate-400 transition-colors hover:bg-white hover:text-kiwi-600"
        title="在新窗口打开"
        @click.stop
      >
        <KiwiIcon name="external" :size="12" />
      </a>
    </div>

    <div class="flex-1 min-h-0 overflow-hidden">
      <AttachmentFileBody
        :url="url"
        :filename="filename"
        :content-type="contentType"
        :size="size"
      />
    </div>
  </div>
</template>
