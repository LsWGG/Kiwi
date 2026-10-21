<script setup lang="ts">
/** 选择当前知识库中的一篇笔记，作为内容卡片插入正文。 */
import { computed, nextTick, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { useNotesStore, type NoteSummary } from '@/stores/notes'

const props = defineProps<{
  open: boolean
  /** 当前笔记 ID，避免嵌入自身 */
  currentNoteId?: string | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'select', note: NoteSummary): void
}>()

const notes = useNotesStore()
const query = ref('')
const input = ref<HTMLInputElement | null>(null)
const activeKind = ref('all')

const KINDS: Array<{ id: string; label: string; icon: string }> = [
  { id: 'all', label: '全部', icon: 'layers' },
  { id: 'doc', label: '文档', icon: 'file' },
  { id: 'database', label: '数据表', icon: 'table' },
  { id: 'sheet', label: '表格', icon: 'table' },
  { id: 'canvas', label: '画布', icon: 'pen' },
  { id: 'notebook', label: 'Notebook', icon: 'notebook' },
  { id: 'import', label: '导入', icon: 'fileImport' },
  { id: 'link', label: '链接', icon: 'link2' },
]

const KIND_META: Record<string, { label: string; icon: string; cls: string }> = {
  doc: { label: '文档', icon: 'file', cls: 'bg-kiwi-100 text-kiwi-600' },
  import: { label: '导入', icon: 'fileImport', cls: 'bg-orange-50 text-orange-500' },
  database: { label: '数据表', icon: 'table', cls: 'bg-sky-50 text-sky-600' },
  sheet: { label: '表格', icon: 'table', cls: 'bg-emerald-50 text-emerald-600' },
  canvas: { label: '画布', icon: 'pen', cls: 'bg-violet-50 text-violet-600' },
  notebook: { label: 'Notebook', icon: 'notebook', cls: 'bg-emerald-50 text-emerald-600' },
  link: { label: '链接', icon: 'link2', cls: 'bg-cyan-50 text-cyan-600' },
}

function metaOf(kind: string) {
  return KIND_META[kind] ?? KIND_META.doc
}

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return notes.notes
    .filter((note) => note.id !== props.currentNoteId)
    .filter((note) => activeKind.value === 'all' || note.kind === activeKind.value)
    .filter((note) => {
      if (!keyword) return true
      return (
        note.title.toLowerCase().includes(keyword) ||
        note.tags.some((tag) => tag.toLowerCase().includes(keyword))
      )
    })
    .slice(0, 60)
})

watch(
  () => props.open,
  (open) => {
    if (!open) return
    query.value = ''
    activeKind.value = 'all'
    void nextTick(() => input.value?.focus())
  },
)

function pick(note: NoteSummary) {
  emit('select', note)
  emit('close')
}
</script>

<template>
  <KiwiModal :open="open" title="插入笔记内容" @close="emit('close')">
    <div class="space-y-3">
      <div class="relative">
        <span class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-300">
          <KiwiIcon name="search" :size="14" />
        </span>
        <input
          ref="input"
          v-model="query"
          class="kiwi-input !pl-9"
          placeholder="搜索标题或标签…"
          @keydown.enter="filtered[0] && pick(filtered[0])"
        />
      </div>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="kind in KINDS"
          :key="kind.id"
          type="button"
          class="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition-colors"
          :class="
            activeKind === kind.id
              ? 'border-kiwi-200 bg-kiwi-50 text-kiwi-700'
              : 'border-slate-200 bg-white text-slate-500 hover:border-kiwi-200'
          "
          @click="activeKind = kind.id"
        >
          <KiwiIcon :name="kind.icon" :size="11" />
          {{ kind.label }}
        </button>
      </div>

      <div class="max-h-[52vh] min-h-[180px] overflow-y-auto rounded-xl border border-slate-100">
        <button
          v-for="note in filtered"
          :key="note.id"
          type="button"
          class="flex w-full items-center gap-3 border-b border-slate-100/80 px-3 py-2.5 text-left transition-colors last:border-0 hover:bg-kiwi-50/60"
          @click="pick(note)"
        >
          <span
            class="grid h-8 w-8 shrink-0 place-items-center rounded-lg"
            :class="metaOf(note.kind).cls"
          >
            <KiwiIcon :name="metaOf(note.kind).icon" :size="14" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[13px] font-medium text-slate-700">
              {{ note.title || '未命名' }}
            </span>
            <span class="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-slate-400">
              <span>{{ metaOf(note.kind).label }}</span>
              <span v-if="note.tags.length" class="truncate">
                · {{ note.tags.slice(0, 3).map((tag) => `#${tag}`).join(' ') }}
              </span>
            </span>
          </span>
          <KiwiIcon name="arrowRight" :size="13" class="shrink-0 text-slate-300" />
        </button>
        <div v-if="!filtered.length" class="grid min-h-[180px] place-content-center gap-1 text-center">
          <p class="text-sm text-slate-400">没有匹配的笔记</p>
          <p class="text-[11px] text-slate-300">可先在左侧目录创建文档、数据表或画布</p>
        </div>
      </div>
      <p class="text-[11px] text-slate-400">
        插入的是引用卡片：原笔记修改后，卡片始终指向最新内容。
      </p>
    </div>
  </KiwiModal>
</template>
