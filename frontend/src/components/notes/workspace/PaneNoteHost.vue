<script setup lang="ts">
/** 分栏中的笔记窗口：独立加载正文，不抢占全局 currentNote。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import NotePaneContent from '@/components/notes/NotePaneContent.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const props = defineProps<{
  noteId: string
  kbId: string
  active: boolean
}>()

const emit = defineEmits<{
  (e: 'open-info'): void
  (e: 'open-backlink', noteId: string, mentionId?: string): void
  (e: 'open-note', noteId: string): void
}>()

const notes = useNotesStore()
/** 直接读缓存：解锁 / 标题变化 / 信息面板刷新都会就地更新所有窗口。 */
const note = computed<NoteOut | null>(() => notes.noteCache[props.noteId] ?? null)
const loading = ref(false)
const error = ref('')
let loadSeq = 0

async function load(force = false) {
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    await notes.fetchNote(props.noteId, { force })
  } catch (e: any) {
    if (seq === loadSeq) error.value = e?.message || '笔记不存在或已删除'
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

onMounted(() => void load(false))
watch(
  () => props.noteId,
  () => void load(false),
)
</script>

<template>
  <div class="h-full min-h-0">
    <div v-if="loading && !note" class="h-full grid place-items-center">
      <div class="flex items-center gap-2 text-sm text-slate-400">
        <KiwiIcon name="loader" :size="16" spin />
        加载中…
      </div>
    </div>

    <div v-else-if="error" class="h-full grid place-items-center px-6">
      <div class="text-center">
        <KiwiIcon name="alert" :size="32" class="mx-auto text-slate-300" />
        <p class="mt-3 text-[13px] font-medium text-slate-600">无法打开这篇笔记</p>
        <p class="mt-1 text-[11.5px] text-slate-400">{{ error }}</p>
        <button type="button" class="kiwi-btn-secondary mt-4 !py-1.5 !text-xs" @click="load(true)">
          重试
        </button>
      </div>
    </div>

    <NotePaneContent
      v-else-if="note"
      :note="note"
      :active="active"
      in-pane
      @open-info="emit('open-info')"
      @open-backlink="(id, mentionId) => emit('open-backlink', id, mentionId)"
      @open-note="(id) => emit('open-note', id)"
      @unlocked="load(true)"
    />
  </div>
</template>
