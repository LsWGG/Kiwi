<script setup lang="ts">
/** 标题旁的表情按钮：有自定义表情时替换默认类型图标。 */
import { computed, ref } from 'vue'
import { useNotesStore, type NoteKind } from '@/stores/notes'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'
import { NOTE_EMOJIS } from './emojis'

const props = withDefaults(
  defineProps<{
    noteId: string
    emoji?: string
    kind?: NoteKind
    size?: number
  }>(),
  { emoji: '', kind: 'doc', size: 20 },
)

const notes = useNotesStore()
const current = computed(() => (props.emoji || '').trim())
const custom = ref('')

const iconName = computed(() => {
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
const iconClass = computed(() => {
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

async function apply(emoji: string, close: () => void) {
  const value = emoji.trim()
  close()
  custom.value = ''
  if (!value && !current.value) return
  try {
    await notes.updateNote(props.noteId, { props_json: { emoji: value } })
  } catch (e: any) {
    toast.error(e.message || '设置表情失败')
  }
}
</script>

<template>
  <KiwiDropdown width="w-72">
    <template #trigger>
      <button
        type="button"
        class="w-7 h-7 shrink-0 grid place-items-center rounded-lg transition-colors hover:bg-slate-100"
        :title="current ? '更换文档表情' : '设置文档表情'"
      >
        <span v-if="current" class="leading-none" :style="{ fontSize: `${size}px` }">
          {{ current }}
        </span>
        <KiwiIcon v-else :name="iconName" :size="size" :class="iconClass" />
      </button>
    </template>
    <template #default="{ close }">
      <div class="px-1 pb-1.5 text-[10.5px] text-slate-400">选择文档表情</div>
      <div class="grid grid-cols-8 gap-0.5 max-h-56 overflow-y-auto pr-0.5">
        <button
          v-for="emoji in NOTE_EMOJIS"
          :key="emoji"
          type="button"
          class="h-8 grid place-items-center rounded-lg text-[17px] leading-none transition-colors hover:bg-kiwi-50"
          :class="emoji === current ? 'bg-kiwi-100/80' : ''"
          @click="apply(emoji, close)"
        >
          {{ emoji }}
        </button>
      </div>
      <div class="mt-1.5 flex items-center gap-1.5 border-t border-slate-100 pt-1.5">
        <input
          v-model="custom"
          class="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11.5px] text-slate-600 outline-none focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-100"
          placeholder="自定义表情 / 文字，如 🦄"
          maxlength="8"
          @keydown.enter.prevent="apply(custom, close)"
        />
        <button
          type="button"
          class="shrink-0 rounded-lg bg-kiwi-500 px-2 py-1 text-[11px] text-white transition-colors hover:bg-kiwi-600 disabled:opacity-50"
          :disabled="!custom.trim()"
          @click="apply(custom, close)"
        >
          使用
        </button>
      </div>
      <button
        v-if="current"
        type="button"
        class="mt-1 w-full flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11.5px] text-slate-500 transition-colors hover:bg-slate-100"
        @click="apply('', close)"
      >
        <KiwiIcon name="close" :size="12" />
        恢复默认图标
      </button>
    </template>
  </KiwiDropdown>
</template>
