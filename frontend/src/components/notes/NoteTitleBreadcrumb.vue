<script setup lang="ts">
/**
 * 工作区面包屑：分组 / 表情 + 可改名标题。
 * 文档、数据表、链接统一使用；输入框宽度随标题长度自动伸缩。
 */
import { computed, nextTick, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import NoteEmojiButton from './NoteEmojiButton.vue'
import { useNotesStore, type NoteKind } from '@/stores/notes'

const props = withDefaults(
  defineProps<{
    noteId: string
    title: string
    emoji?: string
    kind?: NoteKind
    folderId?: string | null
    readonly?: boolean
    placeholder?: string
  }>(),
  {
    emoji: '',
    kind: 'doc',
    folderId: null,
    readonly: false,
    placeholder: '无标题',
  },
)

const emit = defineEmits<{
  (e: 'update:title', value: string): void
  (e: 'input'): void
}>()

const notes = useNotesStore()
const folderName = computed(
  () => notes.folders.find((f) => f.id === props.folderId)?.name ?? '工作区',
)

const readonlyEmoji = computed(() => (props.emoji || '').trim())
const readonlyIcon = computed(() => {
  switch (props.kind) {
    case 'database':
      return 'database'
    case 'canvas':
      return 'pen'
    case 'link':
      return 'link2'
    case 'import':
      return 'fileImport'
    case 'notebook':
      return 'notebook'
    default:
      return 'fileText'
  }
})
const readonlyIconClass = computed(() => {
  switch (props.kind) {
    case 'database':
      return 'text-kiwi-500'
    case 'canvas':
      return 'text-violet-500'
    case 'link':
      return 'text-sky-500'
    case 'import':
      return 'text-emerald-500/90'
    case 'notebook':
      return 'text-indigo-500'
    default:
      return 'text-blue-500'
  }
})

// 用隐藏镜像测量文本宽度，输入框随标题伸缩（最小 44px，最大 260px）
const mirror = ref<HTMLElement | null>(null)
const inputWidth = ref(72)
const displayText = computed(() => props.title || props.placeholder)

async function measure() {
  await nextTick()
  const width = mirror.value?.offsetWidth ?? 48
  inputWidth.value = Math.min(260, Math.max(44, width + 16))
}

watch(() => props.title, measure, { immediate: true })

function onInput(event: Event) {
  emit('update:title', (event.target as HTMLInputElement).value)
  emit('input')
}

function blurTarget(event: KeyboardEvent) {
  ;(event.target as HTMLInputElement).blur()
}
</script>

<template>
  <span class="flex items-center gap-1.5 text-[11px] text-slate-400 min-w-0">
    <KiwiIcon name="folder" :size="12" class="text-amber-400/80 shrink-0" />
    <span class="truncate max-w-[140px]">{{ folderName }}</span>
    <span class="text-slate-300">/</span>

    <template v-if="readonly">
      <span v-if="readonlyEmoji" class="shrink-0 text-[13px] leading-none">{{ readonlyEmoji }}</span>
      <KiwiIcon
        v-else
        :name="readonlyIcon"
        :size="12"
        class="shrink-0"
        :class="readonlyIconClass"
      />
      <span class="truncate max-w-[260px] text-slate-500">{{ displayText }}</span>
    </template>

    <template v-else>
      <NoteEmojiButton
        :note-id="noteId"
        :emoji="emoji"
        :kind="kind"
        :size="14"
      />
      <span class="relative inline-flex min-w-0 items-center">
        <span
          ref="mirror"
          class="pointer-events-none invisible absolute left-0 top-0 whitespace-pre text-[11px]"
          aria-hidden="true"
        >{{ displayText }}</span>
        <input
          :value="title"
          :style="{ width: `${inputWidth}px` }"
          class="h-6 min-w-0 max-w-[260px] truncate rounded-md border border-transparent bg-transparent px-1.5 py-0.5 text-[11px] text-slate-500 outline-none transition-colors hover:border-slate-200 focus:border-kiwi-300 focus:bg-white focus:text-slate-700"
          maxlength="300"
          :placeholder="placeholder"
          :title="displayText"
          @input="onInput"
          @keydown.enter.prevent="blurTarget"
        />
      </span>
    </template>
  </span>
</template>
