<script setup lang="ts">
/** 笔记工作区：左侧多级目录 + 右侧正文 / 数据表 / 链接面板 + 笔记信息面板。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import NotesTreePanel from '@/components/notes/NotesTreePanel.vue'
import NoteInfoPanel from '@/components/notes/NoteInfoPanel.vue'
import NoteSearchDialog from '@/components/notes/NoteSearchDialog.vue'
import NoteLockGate from '@/components/notes/NoteLockGate.vue'
import NoteDocPane from '@/components/notes/panes/NoteDocPane.vue'
import NoteLinkPane from '@/components/notes/panes/NoteLinkPane.vue'
import NoteDatabasePane from '@/components/notes/panes/NoteDatabasePane.vue'
import NoteCanvasPane from '@/components/notes/panes/NoteCanvasPane.vue'
import NoteNotebookPane from '@/components/notes/panes/NoteNotebookPane.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

const route = useRoute()
const router = useRouter()
const kbs = useKbsStore()
const notes = useNotesStore()

const activeId = computed(() =>
  typeof route.params.id === 'string' && route.params.id ? route.params.id : null,
)
/** 上锁且本次会话未解锁：不挂载编辑器 / 阅读组件，也不展示信息面板。 */
const contentLocked = computed(() => {
  const note = notes.currentNote
  return !!note && !!note.is_locked && !note.unlocked
})
const loading = ref(false)
const creating = ref(false)
const infoOpen = ref(false)
const searchOpen = ref(false)

let seq = 0

function onGlobalKey(event: KeyboardEvent) {
  // 正文编辑器已处理的组合键（如 Ctrl+I 斜体）不再触发工作区面板切换。
  if (event.defaultPrevented) return
  const mod = event.ctrlKey || event.metaKey
  if (!mod) return
  const key = event.key.toLowerCase()
  if (key === 'k') {
    event.preventDefault()
    if (kbs.currentKbId) searchOpen.value = true
  } else if (key === 'i' && notes.currentNote && !contentLocked.value) {
    event.preventDefault()
    infoOpen.value = !infoOpen.value
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKey))

async function sync() {
  seq += 1
  const mySeq = seq
  if (!kbs.currentKbId) {
    notes.currentNote = null
    return
  }
  loading.value = true
  try {
    await notes.fetchTree()
    if (mySeq !== seq) return
    const id = activeId.value
    if (!id) {
      notes.stopImportPolling()
      notes.currentNote = null
      return
    }
    const cached = notes.currentNote
    if (!cached || cached.id !== id || cached.kb_id !== kbs.currentKbId) {
      notes.stopImportPolling()
      const note = await notes.getNote(id)
      if (mySeq !== seq) return
      if (note.kb_id !== kbs.currentKbId) {
        void router.replace({ name: 'notes' })
      }
    }
  } catch {
    if (mySeq !== seq) return
    notes.currentNote = null
    toast.error('笔记不存在或已删除')
    void router.replace({ name: 'notes' })
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

watch([() => kbs.currentKbId, activeId], sync, { immediate: true })

// 归档 / 移入回收站后 currentNote 会被清空，此时同步关闭路由，避免地址残留。
watch(
  () => notes.currentNote,
  (note, previous) => {
    if (!note && previous && activeId.value) {
      void router.replace({ name: 'notes' })
    }
  },
)

watch(
  () => kbs.currentKbId,
  () => {
    searchOpen.value = false
    infoOpen.value = false
  },
)

function openNote(note: NoteOut | string, kbId?: string, rowId?: string) {
  const id = typeof note === 'string' ? note : note.id
  if (kbId && kbId !== kbs.currentKbId) {
    kbs.currentKbId = kbId
  }
  // 从集合记录笔记跳回数据表时，带上行 id 以便定位并预览该记录
  const query = rowId ? { row: rowId } : {}
  if (activeId.value === id) {
    if (rowId) void router.replace({ name: 'notes', params: { id }, query })
    return
  }
  void router.push({ name: 'notes', params: { id }, query })
}

/** 反向链接：打开来源笔记，并带上被引用笔记的 id 以定位到引用处。 */
function openBacklink(noteId: string, mentionId?: string) {
  if (!mentionId) {
    openNote(noteId)
    return
  }
  infoOpen.value = false
  const query = { mention: mentionId, t: String(Date.now()) }
  if (activeId.value === noteId) {
    void router.replace({ name: 'notes', params: { id: noteId }, query })
  } else {
    void router.push({ name: 'notes', params: { id: noteId }, query })
  }
}

function openCollectionRow(databaseId: string, rowId: string) {
  openNote(databaseId, undefined, rowId)
}

function closeNote() {
  void router.replace({ name: 'notes' })
}

const CREATE_TITLES: Record<'doc' | 'canvas' | 'database' | 'notebook', string> = {
  doc: '无标题文档',
  canvas: '无标题画布',
  database: '无标题数据表',
  notebook: '无标题 Notebook',
}

async function create(kind: 'doc' | 'canvas' | 'database' | 'notebook') {
  creating.value = true
  try {
    const note = await notes.createNote({
      title: CREATE_TITLES[kind],
      kind,
    })
    openNote(note)
  } catch (e: any) {
    toast.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div class="h-full flex">
    <NotesTreePanel
      :active-id="activeId"
      @open-note="openNote"
      @close-note="closeNote"
      @open-search="searchOpen = true"
    />

    <div class="flex-1 min-w-0 relative flex overflow-hidden">
    <!-- 信息面板折叠时预留右侧槽位，避免悬浮入口遮挡数据表行操作等右侧交互 -->
    <section
      class="flex-1 min-w-0 flex flex-col overflow-hidden transition-[padding] duration-200"
      :class="notes.currentNote && !contentLocked && !infoOpen ? 'pr-7' : ''"
    >
      <div v-if="!kbs.currentKbId" class="flex-1 grid place-items-center">
        <KiwiEmpty icon="database" title="请先选择知识库" desc="工作区条目按知识库隔离" />
      </div>

      <div v-else-if="loading && !notes.currentNote" class="flex-1 grid place-items-center">
        <div class="flex items-center gap-2 text-sm text-slate-400">
          <KiwiIcon name="loader" :size="16" spin />
          加载中…
        </div>
      </div>

      <template v-else-if="notes.currentNote">
        <NoteLockGate
          v-if="contentLocked"
          :key="`lock-${notes.currentNote.id}`"
          :note="notes.currentNote"
        />
        <NoteDocPane
          v-else-if="notes.currentNote.kind === 'doc' || notes.currentNote.kind === 'import'"
          :key="notes.currentNote.id"
          :note="notes.currentNote"
          @open-info="infoOpen = true"
          @open-backlink="openBacklink"
        />
        <NoteLinkPane
          v-else-if="notes.currentNote.kind === 'link'"
          :key="notes.currentNote.id"
          :note="notes.currentNote"
        />
        <NoteDatabasePane
          v-else-if="notes.currentNote.kind === 'database'"
          :key="notes.currentNote.id"
          :note="notes.currentNote"
          @open-note="openNote"
        />
        <NoteCanvasPane
          v-else-if="notes.currentNote.kind === 'canvas'"
          :key="notes.currentNote.id"
          :note="notes.currentNote"
        />
        <NoteNotebookPane
          v-else-if="notes.currentNote.kind === 'notebook'"
          :key="notes.currentNote.id"
          :note="notes.currentNote"
        />
      </template>

      <div v-else class="flex-1 grid place-items-center px-6">
        <KiwiEmpty
          icon="note"
          title="开始记录"
          desc="从左侧选择条目，或创建一篇新文档。支持 Markdown、表格、任务列表、图片与附件。"
        >
          <button class="kiwi-btn-primary" :disabled="creating" @click="create('doc')">
            <KiwiIcon name="plus" :size="14" />
            新建文档
          </button>
          <button class="kiwi-btn-secondary" :disabled="creating" @click="create('canvas')">
            <KiwiIcon name="pen" :size="14" />
            新建画布
          </button>
          <button class="kiwi-btn-secondary" :disabled="creating" @click="create('database')">
            <KiwiIcon name="database" :size="14" />
            新建数据表
          </button>
          <button class="kiwi-btn-secondary" :disabled="creating" @click="create('notebook')">
            <KiwiIcon name="notebook" :size="14" />
            新建 Notebook
          </button>
        </KiwiEmpty>
      </div>
    </section>

    <!-- 信息面板折叠态入口 -->
    <button
      v-if="notes.currentNote && !contentLocked && !infoOpen"
      type="button"
      class="absolute right-0 top-1/2 -translate-y-1/2 z-30 flex flex-col items-center gap-1 rounded-l-xl border border-r-0 border-slate-200/70 bg-white/85 backdrop-blur px-1 py-2.5 text-slate-400 shadow-soft transition-colors hover:text-kiwi-600"
      title="笔记信息（Ctrl/⌘ + I）"
      @click="infoOpen = true"
    >
      <KiwiIcon name="chevronLeft" :size="12" />
      <span class="text-[9px] leading-none [writing-mode:vertical-rl]">信息</span>
    </button>

    <NoteInfoPanel
      v-if="notes.currentNote && !contentLocked"
      :note="notes.currentNote"
      :open="infoOpen"
      @close="infoOpen = false"
      @open-note="openBacklink"
      @open-collection-row="openCollectionRow"
    />
    </div>

    <NoteSearchDialog
      :open="searchOpen"
      @close="searchOpen = false"
      @open-note="openNote"
    />
  </div>
</template>
