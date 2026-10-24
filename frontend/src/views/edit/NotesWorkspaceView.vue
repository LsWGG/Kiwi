<script setup lang="ts">
/** 笔记工作区：左侧多级目录 + 右侧正文 / 数据表 / 链接面板 + 笔记信息面板。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import NotesTreePanel from '@/components/notes/NotesTreePanel.vue'
import NoteInfoPanel from '@/components/notes/NoteInfoPanel.vue'
import NoteFindBar from '@/components/notes/NoteFindBar.vue'
import { useCommandPaletteStore } from '@/stores/commandPalette'
import { useNoteFindStore } from '@/stores/noteFind'
import { NOTE_CREATE_TITLES, type CreatableNoteKind } from '@/constants/noteKinds'
import NoteLockGate from '@/components/notes/NoteLockGate.vue'
import NoteDocPane from '@/components/notes/panes/NoteDocPane.vue'
import NoteLinkPane from '@/components/notes/panes/NoteLinkPane.vue'
import NoteDatabasePane from '@/components/notes/panes/NoteDatabasePane.vue'
import NoteCanvasPane from '@/components/notes/panes/NoteCanvasPane.vue'
import NoteNotebookPane from '@/components/notes/panes/NoteNotebookPane.vue'
import NoteSheetPane from '@/components/notes/panes/NoteSheetPane.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

const route = useRoute()
const router = useRouter()
const kbs = useKbsStore()
const notes = useNotesStore()
const commandPalette = useCommandPaletteStore()
const noteFind = useNoteFindStore()
/** 页内查找只扫描当前笔记面板，不含目录树与查找条自身。 */
const findScopeRef = ref<HTMLElement | null>(null)

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

// ---------- 窄屏：目录改为抽屉，避免挤压正文 ----------
const compact = ref(false)
const mobileTreeOpen = ref(false)
let compactQuery: MediaQueryList | null = null

function onCompactChange(event: MediaQueryListEvent) {
  compact.value = event.matches
}

let seq = 0

/** 打开页内查找：有选区时以选中文字作为初始关键词。 */
function showFind() {
  const note = notes.currentNote
  if (!note || contentLocked.value) return
  if (noteFind.open) {
    // 已在查找：再次按 Ctrl/⌘+F 只聚焦并全选关键词，不覆盖输入。
    noteFind.show('', note.id)
    return
  }
  let seed = ''
  const selection = window.getSelection()
  const scope = findScopeRef.value
  if (selection && !selection.isCollapsed && scope && selection.anchorNode) {
    if (scope.contains(selection.anchorNode)) {
      seed = selection.toString().replace(/\s+/g, ' ').trim().slice(0, 80)
    }
  }
  noteFind.show(seed, note.id)
}

function onGlobalKey(event: KeyboardEvent) {
  // 正文编辑器已处理的组合键（如 Ctrl+I 斜体）不再触发工作区面板切换。
  // Ctrl/⌘+K 由 App.vue 的命令面板统一处理，工作区不再单独监听。
  if (event.defaultPrevented) return
  const mod = event.ctrlKey || event.metaKey
  const key = event.key.toLowerCase()
  if (mod && key === 'f' && notes.currentNote && !contentLocked.value) {
    // 拦截浏览器原生查找，改用笔记内查找条（支持计数与上下项）。
    event.preventDefault()
    showFind()
    return
  }
  if (noteFind.open && event.key === 'F3') {
    event.preventDefault()
    noteFind.step(event.shiftKey ? -1 : 1)
    return
  }
  if (!mod) return
  if (key === 'i' && notes.currentNote && !contentLocked.value) {
    event.preventDefault()
    infoOpen.value = !infoOpen.value
  }
}

// ---------- 目录树后台增量同步 ----------
// 页面可见时每分钟拉取一次 `?since=` 增量，多端 / 后台写入无需手动刷新。
const TREE_POLL_MS = 60_000
let treePollTimer: number | null = null

function refreshTreeQuietly() {
  if (document.visibilityState !== 'visible') return
  if (!kbs.currentKbId || notes.treeLoading) return
  void notes.fetchTree().catch(() => {})
}

function onVisibilityChange() {
  if (document.visibilityState === 'visible') refreshTreeQuietly()
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKey)
  compactQuery = window.matchMedia('(max-width: 767px)')
  compact.value = compactQuery.matches
  compactQuery.addEventListener('change', onCompactChange)
  treePollTimer = window.setInterval(refreshTreeQuietly, TREE_POLL_MS)
  document.addEventListener('visibilitychange', onVisibilityChange)
})
onBeforeUnmount(() => {
  noteFind.close()
  window.removeEventListener('keydown', onGlobalKey)
  compactQuery?.removeEventListener('change', onCompactChange)
  if (treePollTimer !== null) window.clearInterval(treePollTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

watch(compact, (value) => {
  if (!value) mobileTreeOpen.value = false
})
watch(activeId, () => {
  mobileTreeOpen.value = false
  noteFind.close()
})
watch(contentLocked, (locked) => {
  if (locked) noteFind.close()
})
watch(
  () => commandPalette.open,
  (open) => {
    if (open) noteFind.close()
  },
)

async function sync() {
  seq += 1
  const mySeq = seq
  if (!kbs.currentKbId) {
    notes.currentNote = null
    return
  }
  // PDF 导出的离屏 iframe 通过 URL 带上解锁令牌；读取后立刻从地址栏移除，
  // 避免令牌留在历史记录里。
  const queryToken = route.query.note_token
  if (typeof queryToken === 'string' && queryToken && activeId.value) {
    notes.rememberUnlockToken(activeId.value, queryToken)
    const query = { ...route.query }
    delete query.note_token
    void router.replace({ name: 'notes', params: { id: activeId.value }, query })
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
    if (cached && cached.id === id && cached.kb_id !== kbs.currentKbId) {
      // 切换知识库后旧笔记不属于当前库：静默回到工作区空态，不当作「已删除」报错。
      notes.stopImportPolling()
      notes.currentNote = null
      void router.replace({ name: 'notes' })
      return
    }
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
    commandPalette.close()
    infoOpen.value = false
  },
)

function openNote(note: NoteOut | string, kbId?: string, rowId?: string) {
  const id = typeof note === 'string' ? note : note.id
  mobileTreeOpen.value = false
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

async function create(kind: CreatableNoteKind) {
  creating.value = true
  try {
    const note = await notes.createNote({
      title: NOTE_CREATE_TITLES[kind],
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
    <!-- 窄屏抽屉：目录浮在正文之上，点击遮罩或选中笔记后关闭 -->
    <div
      v-if="!compact || mobileTreeOpen"
      class="shrink-0 h-full flex"
      :class="compact ? 'fixed inset-y-0 left-0 z-50 shadow-2xl' : ''"
    >
      <NotesTreePanel
        :active-id="activeId"
        :drawer="compact"
        @open-note="openNote"
        @close-note="closeNote"
        @open-search="commandPalette.show()"
        @close="mobileTreeOpen = false"
      />
    </div>
    <div
      v-if="compact && mobileTreeOpen"
      class="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-[2px]"
      @click="mobileTreeOpen = false"
    />

    <div class="flex-1 min-w-0 relative flex overflow-hidden">
    <!-- 信息面板折叠时预留右侧槽位，避免悬浮入口遮挡数据表行操作等右侧交互 -->
    <section
      class="relative flex-1 min-w-0 flex flex-col overflow-hidden transition-[padding] duration-200"
      :class="notes.currentNote && !contentLocked && !infoOpen ? 'pr-7' : ''"
    >
      <!-- 窄屏顶栏：目录入口 + 当前条目标题 -->
      <div
        v-if="compact"
        class="shrink-0 h-11 flex items-center gap-1.5 border-b border-slate-200/60 bg-white/75 px-2 backdrop-blur"
      >
        <button
          type="button"
          class="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-[12px] text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
          title="打开目录"
          @click="mobileTreeOpen = true"
        >
          <KiwiIcon name="panelLeft" :size="15" />
          目录
        </button>
        <span class="min-w-0 flex-1 truncate text-[12.5px] font-medium text-slate-700">
          {{ notes.currentNote?.title || '工作区' }}
        </span>
        <button
          v-if="kbs.currentKbId"
          type="button"
          class="grid h-8 w-8 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
          title="搜索笔记（Ctrl/⌘ + K）"
          @click="commandPalette.show()"
        >
          <KiwiIcon name="search" :size="15" />
        </button>
      </div>

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
        <!-- display:contents 不参与布局，只作为页内查找的扫描范围。 -->
        <div v-else ref="findScopeRef" class="contents">
          <NoteDocPane
            v-if="notes.currentNote.kind === 'doc' || notes.currentNote.kind === 'import'"
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
          <NoteSheetPane
            v-else-if="notes.currentNote.kind === 'sheet'"
            :key="notes.currentNote.id"
            :note="notes.currentNote"
          />
        </div>
        <NoteFindBar :scope="findScopeRef" />
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
          <button class="kiwi-btn-secondary" :disabled="creating" @click="create('sheet')">
            <KiwiIcon name="table" :size="14" />
            新建表格
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

    <div
      v-if="compact && infoOpen && notes.currentNote && !contentLocked"
      class="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-[2px]"
      @click="infoOpen = false"
    />
    <NoteInfoPanel
      v-if="notes.currentNote && !contentLocked"
      :note="notes.currentNote"
      :open="infoOpen"
      @close="infoOpen = false"
      @open-note="openBacklink"
      @open-collection-row="openCollectionRow"
    />
    </div>
  </div>
</template>
