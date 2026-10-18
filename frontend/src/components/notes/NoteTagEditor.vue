<script setup lang="ts">
/** 标签编辑器：笔记页头弹出层与目录右键菜单共用。 */
import { computed, ref, watch } from 'vue'
import { useNotesStore } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'
import { tagChipClass } from './tagPalette'

const props = defineProps<{
  noteId: string
  tags: string[]
}>()

const emit = defineEmits<{ (e: 'updated', tags: string[]): void }>()

const notes = useNotesStore()
const localTags = ref<string[]>([])
const tagInput = ref('')
const saving = ref(false)

watch(
  () => props.tags,
  (value) => {
    localTags.value = [...(value || [])]
  },
  { immediate: true, deep: true },
)

watch(
  () => props.noteId,
  () => {
    tagInput.value = ''
  },
)

const suggestions = computed(() => {
  const keyword = tagInput.value.trim().replace(/^#/, '').toLowerCase()
  return notes.tags
    .filter((tag) => !localTags.value.includes(tag.name))
    .filter((tag) => !keyword || tag.name.toLowerCase().includes(keyword))
    .slice(0, 8)
})

async function persist() {
  saving.value = true
  try {
    const note = await notes.setNoteTags(props.noteId, localTags.value)
    emit('updated', note.tags || [])
    toast.success('标签已更新')
  } catch (e: any) {
    toast.error(e.message || '保存标签失败')
    localTags.value = [...(props.tags || [])]
  } finally {
    saving.value = false
  }
}

async function addTag(name?: string) {
  const value = (name ?? tagInput.value).trim().replace(/^#/, '')
  if (!value || localTags.value.includes(value)) {
    tagInput.value = ''
    return
  }
  localTags.value = [...localTags.value, value]
  tagInput.value = ''
  await persist()
}

async function pickSuggestion(name: string) {
  await addTag(name)
}

async function removeTag(name: string) {
  localTags.value = localTags.value.filter((tag) => tag !== name)
  await persist()
}
</script>

<template>
  <div class="space-y-2">
    <div class="flex flex-wrap gap-1 min-h-5">
      <span
        v-for="(tag, index) in localTags"
        :key="tag"
        class="gap-1 py-0.5 text-[10.5px]"
        :class="tagChipClass(index)"
      >
        {{ tag }}
        <button
          type="button"
          class="opacity-50 transition-opacity hover:opacity-100 hover:text-rose-500"
          :disabled="saving"
          @click="removeTag(tag)"
        >
          <KiwiIcon name="close" :size="9" />
        </button>
      </span>
      <span v-if="!localTags.length" class="text-[10.5px] text-slate-300">
        暂无标签
      </span>
    </div>

    <input
      v-model="tagInput"
      class="kiwi-input !py-1 !text-[11.5px]"
      placeholder="输入标签后回车，如 项目/前端"
      @keydown.enter.prevent="addTag()"
    />

    <div v-if="suggestions.length" class="flex flex-wrap gap-1">
      <button
        v-for="(tag, index) in suggestions"
        :key="tag.id"
        type="button"
        class="py-0.5 text-[10px] transition-shadow hover:shadow-soft"
        :class="tagChipClass(index)"
        @click="pickSuggestion(tag.name)"
      >
        {{ tag.name }}
        <span class="text-slate-300">{{ tag.usage_count }}</span>
      </button>
    </div>

    <p v-if="saving" class="flex items-center gap-1 text-[10px] text-slate-400">
      <KiwiIcon name="loader" :size="10" spin />
      保存中…
    </p>
  </div>
</template>
