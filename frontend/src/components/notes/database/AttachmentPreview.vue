<script setup lang="ts">
/** 附件大屏预览：正文复用 AttachmentFileBody，外层负责遮罩 / 下载 / 关闭。 */
import { computed, onBeforeUnmount, onMounted } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import AttachmentFileBody from '@/components/attachments/AttachmentFileBody.vue'
import type { DbAttachment } from '@/stores/noteDatabase'

const props = defineProps<{ open: boolean; file: DbAttachment | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const sizeLabel = computed(() => {
  const size = props.file?.size ?? 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
})

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
          <AttachmentFileBody
            :url="file.url"
            :filename="file.filename"
            :content-type="file.content_type"
            :size="file.size"
          />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
