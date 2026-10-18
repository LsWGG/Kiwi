<script setup lang="ts">
/** 快速捕获：把一闪而过的想法直接收进「收件箱」分组。 */
import { nextTick, ref, watch } from 'vue'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import { toast } from '@/components/ui/toast'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', note: NoteOut): void
}>()

const notes = useNotesStore()
const text = ref('')
const title = ref('')
const saving = ref(false)
const textarea = ref<HTMLTextAreaElement | null>(null)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    text.value = ''
    title.value = ''
    await nextTick()
    textarea.value?.focus()
  },
)

async function submit() {
  const value = text.value.trim()
  if (!value || saving.value) return
  saving.value = true
  try {
    const note = await notes.quickCapture(value, title.value.trim() || undefined)
    toast.success('已收入收件箱')
    emit('created', note)
    emit('close')
  } catch (e: any) {
    toast.error(e.message || '快速捕获失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <KiwiModal :open="open" title="快速捕获" max-w="max-w-lg" @close="emit('close')">
    <div class="space-y-3">
      <div class="flex items-center gap-2 rounded-lg bg-kiwi-50/70 border border-kiwi-100 px-3 py-2">
        <KiwiIcon name="sparkle" :size="14" class="text-kiwi-500 shrink-0" />
        <p class="text-[11px] text-kiwi-700 leading-relaxed">
          内容会自动保存到「收件箱」分组，之后可补充标签、关联 Wiki 页面或整理到其他分组。
        </p>
      </div>
      <input
        v-model="title"
        class="kiwi-input"
        placeholder="标题（可选，默认取正文首行）"
        @keydown.enter.prevent="submit"
      />
      <textarea
        ref="textarea"
        v-model="text"
        class="kiwi-input h-44 resize-none text-[13px] leading-relaxed"
        placeholder="记下此刻的想法、待办或摘录…&#10;&#10;支持 Markdown。Ctrl/⌘ + Enter 保存"
        @keydown.meta.enter.prevent="submit"
        @keydown.ctrl.enter.prevent="submit"
      />
      <div class="flex items-center justify-between">
        <span class="text-[10px] text-slate-400">
          {{ text.trim().length }} 字
          <span class="mx-1 text-slate-200">·</span>
          保存为文档
        </span>
        <div class="flex gap-2">
          <button class="kiwi-btn-secondary" @click="emit('close')">取消</button>
          <button class="kiwi-btn-primary" :disabled="!text.trim() || saving" @click="submit">
            <KiwiIcon name="send" :size="12" />
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </KiwiModal>
</template>
