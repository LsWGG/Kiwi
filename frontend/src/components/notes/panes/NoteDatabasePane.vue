<script setup lang="ts">
/** 数据表笔记：多视图切换、字段管理、行编辑。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { request } from '@/api/client'
import { useNotesStore, type NoteOut } from '@/stores/notes'
import {
  newViewId,
  useNoteDatabaseStore,
  type DbField,
  type DbFilter,
  type DbRow,
  type DbSort,
  type DbView,
  type ViewType,
} from '@/stores/noteDatabase'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import NoteTitleBreadcrumb from '@/components/notes/NoteTitleBreadcrumb.vue'
import NoteTagButton from '@/components/notes/NoteTagButton.vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import DatabaseTableView from '@/components/notes/database/DatabaseTableView.vue'
import DatabaseKanbanView from '@/components/notes/database/DatabaseKanbanView.vue'
import DatabaseGalleryView from '@/components/notes/database/DatabaseGalleryView.vue'
import DatabaseCalendarView from '@/components/notes/database/DatabaseCalendarView.vue'
import DatabaseFieldManager from '@/components/notes/database/DatabaseFieldManager.vue'
import DatabaseViewSettings from '@/components/notes/database/DatabaseViewSettings.vue'
import DatabaseRowModal from '@/components/notes/database/DatabaseRowModal.vue'
import { useAutosave } from '@/composables/useAutosave'
import { toast } from '@/components/ui/toast'

const props = defineProps<{ note: NoteOut }>()
const emit = defineEmits<{ (e: 'open-note', noteId: string): void }>()
const notes = useNotesStore()
const db = useNoteDatabaseStore()
const route = useRoute()
const router = useRouter()

const title = ref(props.note.title)
const activeViewId = ref<string | null>(null)
const loading = ref(true)
const loadError = ref('')

const fieldManagerOpen = ref(false)
const viewSettingsOpen = ref(false)
const rowModalOpen = ref(false)
const rowMode = ref<'create' | 'edit'>('create')
const editingRow = ref<DbRow | null>(null)
const rowPreset = ref<Record<string, any> | null>(null)
const deletingView = ref<DbView | null>(null)
const viewDeleteOpen = computed({
  get: () => deletingView.value !== null,
  set: (v: boolean) => {
    if (!v) deletingView.value = null
  },
})

const autosave = useAutosave(async () => {
  await notes.updateNote(props.note.id, { title: title.value.trim() || '无标题数据表' })
})

watch(
  () => props.note.title,
  (value) => {
    if (value !== title.value && !autosave.saving.value) title.value = value
  },
)

const activeView = computed(() => {
  const list = db.views
  return list.find((v) => v.id === activeViewId.value) ?? list[0] ?? null
})

watch(
  () => db.views,
  (views) => {
    if (!views.length) {
      activeViewId.value = null
      return
    }
    if (!views.some((v) => v.id === activeViewId.value)) {
      activeViewId.value = views[0].id
    }
  },
  { immediate: true },
)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    await db.load(props.note.id)
  } catch (e: any) {
    loadError.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  await revealRouteRow()
})

watch(
  () => route.query.row,
  () => void revealRouteRow(),
)

// ---------- 视图 ----------
const VIEW_META: Record<ViewType, { label: string; icon: string }> = {
  table: { label: '表格', icon: 'table' },
  kanban: { label: '看板', icon: 'kanban' },
  gallery: { label: '画册', icon: 'gallery' },
  calendar: { label: '日历', icon: 'calendar' },
}
const VIEW_TYPES: ViewType[] = ['table', 'kanban', 'gallery', 'calendar']

function uniqueViewName(type: ViewType): string {
  const base = VIEW_META[type].label
  const names = new Set(db.views.map((v) => v.name))
  if (!names.has(base)) return base
  let i = 2
  while (names.has(`${base} ${i}`)) i += 1
  return `${base} ${i}`
}

function buildView(type: ViewType): DbView | null {
  const text = db.fields.find((f) => f.type === 'text' || f.type === 'url')?.id ?? null
  const select = db.fields.find((f) => f.type === 'select')?.id ?? null
  const date = db.fields.find((f) => f.type === 'date')?.id ?? null
  if (type === 'kanban' && !select) {
    toast.info('看板需要一个单选字段，请先在字段管理中添加')
    return null
  }
  if (type === 'calendar' && !date) {
    toast.info('日历需要一个日期字段，请先在字段管理中添加')
    return null
  }
  const view: DbView = { id: newViewId(), name: uniqueViewName(type), type }
  if (type === 'table') view.hidden_fields = []
  if (type === 'kanban') view.group_field = select
  if (type === 'gallery') {
    view.cover_field = null
    view.title_field = text
  }
  if (type === 'calendar') {
    view.date_field = date
    view.title_field = text
  }
  return view
}

async function addView(type: ViewType) {
  const view = buildView(type)
  if (!view) return
  try {
    await db.saveSchema({ views: [...db.views, view] })
    activeViewId.value = view.id
    toast.success(`已添加${VIEW_META[type].label}视图`)
  } catch (e: any) {
    toast.error(e.message || '添加视图失败')
  }
}

async function updateView(view: DbView) {
  try {
    await db.saveSchema({
      views: db.views.map((v) => (v.id === view.id ? view : v)),
    })
    viewSettingsOpen.value = false
    toast.success('视图已更新')
  } catch (e: any) {
    toast.error(e.message || '保存视图失败')
  }
}

/** 表格列宽 / 行高 / 筛选 / 排序变更后持久化（合并短时间内多次变更）。 */
type TableViewPatch = {
  column_widths?: Record<string, number>
  row_heights?: Record<string, number>
  filters?: DbFilter[]
  sorts?: DbSort[]
}

let tableViewTimer: number | undefined

async function persistTableView() {
  window.clearTimeout(tableViewTimer)
  tableViewTimer = undefined
  try {
    await db.saveSchema({ views: [...db.views] })
  } catch (e: any) {
    toast.error(e.message || '保存表格视图失败')
  }
}

function onTableViewPatch(patch: TableViewPatch) {
  const view = activeView.value
  if (!view) return
  const index = db.views.findIndex((v) => v.id === view.id)
  if (index < 0) return
  db.views[index] = { ...view, ...patch }
  window.clearTimeout(tableViewTimer)
  tableViewTimer = window.setTimeout(() => void persistTableView(), 350)
}

onBeforeUnmount(() => {
  if (tableViewTimer) void persistTableView()
})

async function confirmDeleteView() {
  const view = deletingView.value
  deletingView.value = null
  if (!view || db.views.length <= 1) return
  try {
    const next = db.views.filter((v) => v.id !== view.id)
    await db.saveSchema({ views: next })
    activeViewId.value = next[0]?.id ?? null
    toast.success('视图已删除')
  } catch (e: any) {
    toast.error(e.message || '删除视图失败')
  }
}

// ---------- 字段 ----------
async function saveFields(fields: DbField[]) {
  if (!fields.length) return
  try {
    await db.saveSchema({ fields })
    fieldManagerOpen.value = false
    toast.success('字段已保存')
  } catch (e: any) {
    toast.error(e.message || '保存字段失败')
  }
}

// ---------- 行 ----------
function openCreateRow(preset?: Record<string, any>) {
  rowMode.value = 'create'
  editingRow.value = null
  rowPreset.value = preset ?? null
  rowModalOpen.value = true
}

function openRow(row: DbRow) {
  rowMode.value = 'edit'
  editingRow.value = row
  rowPreset.value = null
  rowModalOpen.value = true
  void loadRowNote(row)
}

// ---------- 记录笔记：按需生成 / 预览 / 溯源 ----------
const generatingNotes = ref(false)
const rowNote = ref<NoteOut | null>(null)
const rowNoteLoading = ref(false)
const rowNoteError = ref('')
let rowNoteSeq = 0

async function loadRowNote(row: DbRow | null) {
  const seq = ++rowNoteSeq
  rowNote.value = null
  rowNoteError.value = ''
  if (!row?.note_id) {
    rowNoteLoading.value = false
    return
  }
  rowNoteLoading.value = true
  try {
    const note = await request<NoteOut>(`/notes/${row.note_id}`, {
      kbId: props.note.kb_id,
    })
    if (seq === rowNoteSeq) rowNote.value = note
  } catch (e: any) {
    if (seq === rowNoteSeq) rowNoteError.value = e?.message || '读取记录笔记失败'
  } finally {
    if (seq === rowNoteSeq) rowNoteLoading.value = false
  }
}

function reportGenerated(
  result: { note_id: string; created: boolean }[],
  openSingle: boolean,
) {
  if (!result.length) return
  const created = result.filter((item) => item.created).length
  const reused = result.length - created
  if (created && reused) {
    toast.success(`已生成 ${created} 篇笔记，复用 ${reused} 篇已有笔记`)
  } else if (created) {
    toast.success(`已生成 ${created} 篇可编辑笔记`)
  } else {
    toast.success(`已复用 ${reused} 篇已有笔记`)
  }
  void notes.fetchTree().catch(() => {})
  if (openSingle && result.length === 1) {
    rowModalOpen.value = false
    emit('open-note', result[0].note_id)
  }
}

async function generateForRows(rows: DbRow[], openSingle = true) {
  if (!rows.length || generatingNotes.value) return []
  generatingNotes.value = true
  try {
    const result = await db.generateRowNotes(rows.map((row) => row.id))
    reportGenerated(result, openSingle)
    return result
  } catch (e: any) {
    toast.error(e?.message || '生成记录笔记失败')
    return []
  } finally {
    generatingNotes.value = false
  }
}

function generateSelectedNotes() {
  const rows = db.rows.filter((row) => selectedRowIds.value.has(row.id))
  void generateForRows(rows, rows.length === 1)
}

function openRowNoteFromTable(row: DbRow) {
  if (row.note_id) {
    emit('open-note', row.note_id)
    return
  }
  void generateForRows([row], true)
}

/** 行详情弹窗中的「生成笔记」：生成后留在弹窗内展示内容。 */
async function generateForEditingRow() {
  const row = editingRow.value
  if (!row) return
  const result = await generateForRows([row], false)
  const first = result[0]
  if (!first) return
  row.note_id = first.note_id
  await loadRowNote(row)
  void notes.fetchTree().catch(() => {})
}

/** 从记录笔记的信息面板跳回数据表，并定位到对应记录。 */
async function revealRouteRow() {
  const raw = route.query.row
  const rowId = typeof raw === 'string' ? raw : ''
  if (!rowId) return
  if (db.noteId !== props.note.id) return
  if (!db.rows.length) await load()
  const row = db.rows.find((item) => item.id === rowId)
  if (!row) return
  openRow(row)
  const query = { ...route.query }
  delete query.row
  void router.replace({ name: route.name || 'notes', params: route.params, query })
}

async function saveRow(data: Record<string, any>) {
  try {
    if (rowMode.value === 'create') await db.createRow(data)
    else if (editingRow.value) await db.updateRow(editingRow.value.id, data)
    rowModalOpen.value = false
    // 行同时是笔记：同步目录树中的标题与条目
    void notes.fetchTree().catch(() => {})
  } catch (e: any) {
    toast.error(e.message || '保存记录失败')
  }
}

async function deleteRow() {
  const row = editingRow.value
  if (!row) return
  try {
    await db.deleteRow(row.id)
    toast.success('记录已删除')
    void notes.fetchTree().catch(() => {})
  } catch (e: any) {
    toast.error(e.message || '删除记录失败')
  }
}

// ---------- 选择与批量删除 ----------
const selectionMode = ref(false)
const selectedRowIds = ref<Set<string>>(new Set())
const selectedIds = computed(() => [...selectedRowIds.value])
const selectedCount = computed(() => selectedRowIds.value.size)
const allSelected = computed(
  () => db.rows.length > 0 && db.rows.every((r) => selectedRowIds.value.has(r.id)),
)

function toggleSelect(id: string) {
  const next = new Set(selectedRowIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedRowIds.value = next
}

function selectRows(ids: string[], selected: boolean) {
  const next = new Set(selectedRowIds.value)
  for (const id of ids) {
    if (selected) next.add(id)
    else next.delete(id)
  }
  selectedRowIds.value = next
}

function toggleSelectAll() {
  selectRows(
    db.rows.map((r) => r.id),
    !allSelected.value,
  )
}

function clearSelection() {
  selectedRowIds.value = new Set()
}

function toggleSelectionMode() {
  selectionMode.value = !selectionMode.value
  if (!selectionMode.value) clearSelection()
}

// 行被删除或重新加载后，清掉已不存在的选择
watch(
  () => db.rows,
  (rows) => {
    if (!selectedRowIds.value.size) return
    const alive = new Set(rows.map((r) => r.id))
    const next = new Set([...selectedRowIds.value].filter((id) => alive.has(id)))
    if (next.size !== selectedRowIds.value.size) selectedRowIds.value = next
  },
)

const deleteTarget = ref<DbRow | null>(null)
const deleteOpen = computed({
  get: () => deleteTarget.value !== null,
  set: (v: boolean) => {
    if (!v) deleteTarget.value = null
  },
})
const deleteMessage = computed(() =>
  deleteTarget.value
    ? `删除「${rowTitle(deleteTarget.value)}」？若已生成记录笔记也会一并删除。`
    : '',
)

function askDeleteRow(row: DbRow) {
  deleteTarget.value = row
}

async function confirmDeleteRow() {
  const row = deleteTarget.value
  deleteTarget.value = null
  if (!row) return
  try {
    await db.deleteRow(row.id)
    toast.success('记录已删除')
    void notes.fetchTree().catch(() => {})
  } catch (e: any) {
    toast.error(e.message || '删除记录失败')
  }
}

const batchDeleteOpen = ref(false)

async function confirmDeleteSelected() {
  const ids = [...selectedRowIds.value]
  batchDeleteOpen.value = false
  if (!ids.length) return
  try {
    await db.deleteRows(ids)
    clearSelection()
    toast.success(`已删除 ${ids.length} 条记录`)
    void notes.fetchTree().catch(() => {})
  } catch (e: any) {
    toast.error(e.message || '批量删除失败')
  }
}

function openRowNote(noteId: string) {
  rowModalOpen.value = false
  emit('open-note', noteId)
}

function rowTitle(row: DbRow): string {
  for (const key of ['name', 'title']) {
    const value = row.data[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  const firstText = db.fields.find((f) =>
    ['text', 'long_text', 'url'].includes(f.type),
  )
  const value = firstText ? row.data[firstText.id] : ''
  return typeof value === 'string' && value.trim() ? value.trim() : '未命名记录'
}

async function saveRowAsTemplate() {
  const row = editingRow.value
  if (!row) return
  const name = rowTitle(row)
  try {
    await notes.createTemplate({
      name: `${name}（模板）`,
      description: `来自数据表「${props.note.title}」的记录模板，预填全部集合属性。`,
      icon: 'layoutTemplate',
      title_pattern: name,
      body_md: '',
      tags_json: [],
      props_json: {
        collection_note_id: props.note.id,
        collection_data: { ...row.data },
      },
    })
    toast.success(`已保存集合模板「${name}」`)
  } catch (e: any) {
    toast.error(e.message || '保存模板失败')
  }
}

async function updateCell(rowId: string, fieldId: string, value: any) {
  try {
    await db.updateRow(rowId, { [fieldId]: value })
    const field = db.fields.find((f) => f.id === fieldId)
    if (field && ['text', 'long_text', 'url'].includes(field.type)) {
      void notes.fetchTree().catch(() => {})
    }
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="shrink-0 flex items-center gap-2 px-4 pt-2.5">
      <NoteTitleBreadcrumb
        v-model:title="title"
        :note-id="note.id"
        :emoji="note.props_json?.emoji"
        kind="database"
        :folder-id="note.folder_id"
        placeholder="无标题数据表"
        @input="autosave.schedule()"
      />
      <div class="flex-1" />
      <span class="shrink-0 text-[10px] text-slate-400 tabular-nums">{{ db.rows.length }} 条记录</span>
      <NoteTagButton :note="note" />
      <button
        class="kiwi-btn-primary !py-1 !px-2.5 !text-[11px]"
        :disabled="!activeView"
        @click="openCreateRow()"
      >
        <KiwiIcon name="plus" :size="12" />
        新建记录
      </button>
      <span class="shrink-0 text-[10px] text-slate-400">
        <template v-if="autosave.saving.value">保存中…</template>
        <template v-else-if="autosave.savedAt.value">已保存 {{ autosave.savedAt.value }}</template>
      </span>
      <button
        class="kiwi-btn-ghost !py-1 !px-2 !text-[11px]"
        :class="selectionMode ? '!text-kiwi-600 !bg-kiwi-50' : ''"
        @click="toggleSelectionMode"
      >
        <KiwiIcon name="check" :size="12" />
        {{ selectionMode ? '退出选择' : '选择' }}
      </button>
      <button class="kiwi-btn-ghost !py-1 !px-2 !text-[11px]" @click="fieldManagerOpen = true">
        <KiwiIcon name="columns" :size="12" />
        字段
      </button>
      <button
        class="kiwi-btn-ghost !py-1 !px-2 !text-[11px]"
        :disabled="!activeView"
        @click="viewSettingsOpen = true"
      >
        <KiwiIcon name="settings" :size="12" />
        视图设置
      </button>
    </header>

    <!-- 视图页签：允许换行，避免 overflow 裁剪「添加视图」下拉框 -->
    <div class="shrink-0 flex flex-wrap items-center gap-1 px-3 pt-2 pb-1.5">
      <div
        v-for="view in db.views"
        :key="view.id"
        class="group shrink-0 flex items-center rounded-lg transition-colors"
        :class="activeView?.id === view.id ? 'bg-kiwi-100/80 text-kiwi-700' : 'text-slate-500 hover:bg-white/70'"
      >
        <button
          type="button"
          class="flex items-center gap-1.5 h-7 pl-2 pr-1 text-[11.5px]"
          @click="activeViewId = view.id"
        >
          <KiwiIcon :name="VIEW_META[view.type].icon" :size="12" />
          {{ view.name }}
        </button>
        <button
          v-if="db.views.length > 1"
          type="button"
          class="w-4 h-4 mr-1 grid place-items-center rounded text-slate-300 opacity-0 group-hover:opacity-100 hover:text-rose-500 hover:bg-white"
          title="删除视图"
          @click.stop="deletingView = view"
        >
          <KiwiIcon name="close" :size="9" />
        </button>
      </div>

      <KiwiDropdown width="w-40">
        <template #trigger="{ open }">
          <button
            type="button"
            class="w-6 h-6 grid place-items-center rounded-md text-slate-400 hover:bg-white/80 hover:text-kiwi-600"
            :class="open ? 'bg-white/80 text-kiwi-600' : ''"
            title="添加视图"
          >
            <KiwiIcon name="plus" :size="13" />
          </button>
        </template>
        <template #default="{ close }">
          <button
            v-for="type in VIEW_TYPES"
            :key="type"
            type="button"
            class="w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[12px] text-slate-600 hover:bg-kiwi-50"
            @click="close(); addView(type)"
          >
            <KiwiIcon :name="VIEW_META[type].icon" :size="13" class="text-slate-400" />
            {{ VIEW_META[type].label }}视图
          </button>
        </template>
      </KiwiDropdown>
    </div>

    <div class="shrink-0 h-px bg-slate-200/60 mx-3" />

    <!-- 批量选择工具条 -->
    <div
      v-if="selectionMode"
      class="shrink-0 flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1.5 text-[11px]"
    >
      <button class="text-slate-500 hover:text-kiwi-600" @click="toggleSelectAll">
        {{ allSelected ? '取消全选' : '全选' }}
      </button>
      <span class="text-slate-400 tabular-nums">已选 {{ selectedCount }} 条</span>
      <button
        class="flex items-center gap-1 text-kiwi-600 hover:text-kiwi-700 disabled:text-slate-300"
        :disabled="!selectedCount || generatingNotes"
        title="为选中的记录生成可编辑笔记；已有笔记的记录会直接复用"
        @click="generateSelectedNotes"
      >
        <KiwiIcon :name="generatingNotes ? 'loader' : 'bookOpen'" :size="11" :spin="generatingNotes" />
        生成笔记
      </button>
      <button
        class="flex items-center gap-1 text-rose-500 hover:text-rose-600 disabled:text-slate-300"
        :disabled="!selectedCount"
        @click="batchDeleteOpen = true"
      >
        <KiwiIcon name="trash" :size="11" />
        删除所选
      </button>
      <button class="ml-auto text-slate-400 hover:text-slate-600" @click="clearSelection">
        取消选择
      </button>
    </div>

    <!-- 内容 -->
    <div v-if="loading" class="flex-1 grid place-items-center">
      <div class="flex items-center gap-2 text-sm text-slate-400">
        <KiwiIcon name="loader" :size="16" spin />
        加载数据表…
      </div>
    </div>

    <div v-else-if="loadError" class="flex-1 grid place-items-center">
      <div class="text-center">
        <KiwiIcon name="alert" :size="24" class="mx-auto text-rose-400" />
        <p class="mt-2 text-[12px] text-slate-500">{{ loadError }}</p>
        <button class="kiwi-btn-secondary mt-3 !py-1.5 !text-xs" @click="load">重试</button>
      </div>
    </div>

    <template v-else-if="activeView">
      <DatabaseTableView
        v-if="activeView.type === 'table'"
        :fields="db.fields"
        :rows="db.rows"
        :view="activeView"
        :selection-mode="selectionMode"
        :selected-ids="selectedIds"
        @update-cell="updateCell"
        @create-row="openCreateRow()"
        @open-row="openRow"
        @patch-view="onTableViewPatch"
        @toggle-select="toggleSelect"
        @select-many="selectRows"
        @delete-row="askDeleteRow"
        @open-row-note="openRowNoteFromTable"
      />
      <DatabaseKanbanView
        v-else-if="activeView.type === 'kanban'"
        :fields="db.fields"
        :rows="db.rows"
        :view="activeView"
        :selection-mode="selectionMode"
        :selected-ids="selectedIds"
        @update-cell="updateCell"
        @create-row="openCreateRow"
        @open-row="openRow"
        @toggle-select="toggleSelect"
        @delete-row="askDeleteRow"
      />
      <DatabaseGalleryView
        v-else-if="activeView.type === 'gallery'"
        :fields="db.fields"
        :rows="db.rows"
        :view="activeView"
        :selection-mode="selectionMode"
        :selected-ids="selectedIds"
        @create-row="openCreateRow()"
        @open-row="openRow"
        @toggle-select="toggleSelect"
        @delete-row="askDeleteRow"
      />
      <DatabaseCalendarView
        v-else
        :fields="db.fields"
        :rows="db.rows"
        :view="activeView"
        :selection-mode="selectionMode"
        :selected-ids="selectedIds"
        @create-row="openCreateRow"
        @open-row="openRow"
        @toggle-select="toggleSelect"
        @delete-row="askDeleteRow"
      />
    </template>

    <div v-else class="flex-1 grid place-items-center">
      <div class="text-center">
        <KiwiIcon name="table" :size="24" class="mx-auto text-slate-300" />
        <p class="mt-2 text-[12px] text-slate-400">还没有视图</p>
        <button class="kiwi-btn-secondary mt-3 !py-1.5 !text-xs" @click="addView('table')">
          创建表格视图
        </button>
      </div>
    </div>

    <DatabaseFieldManager
      :open="fieldManagerOpen"
      :fields="db.fields"
      @close="fieldManagerOpen = false"
      @save="saveFields"
    />

    <DatabaseViewSettings
      :open="viewSettingsOpen"
      :fields="db.fields"
      :view="activeView"
      @close="viewSettingsOpen = false"
      @save="updateView"
    />

    <DatabaseRowModal
      :open="rowModalOpen"
      :mode="rowMode"
      :fields="db.fields"
      :row="editingRow"
      :preset="rowPreset"
      :note="rowNote"
      :note-loading="rowNoteLoading"
      :note-error="rowNoteError"
      :generating="generatingNotes"
      @close="rowModalOpen = false"
      @save="saveRow"
      @delete="deleteRow"
      @open-note="openRowNote"
      @generate-note="generateForEditingRow"
      @save-template="saveRowAsTemplate"
    />

    <KiwiConfirm
      v-model="viewDeleteOpen"
      danger
      title="删除视图"
      message="只会删除视图配置，记录不会丢失。"
      confirm-text="删除"
      @confirm="confirmDeleteView"
    />

    <KiwiConfirm
      v-model="deleteOpen"
      danger
      title="删除记录"
      :message="deleteMessage"
      confirm-text="删除"
      @confirm="confirmDeleteRow"
    />

    <KiwiConfirm
      v-model="batchDeleteOpen"
      danger
      title="批量删除记录"
      :message="`将删除选中的 ${selectedCount} 条记录；已生成的记录笔记也会一并删除，此操作不可撤销。`"
      confirm-text="删除"
      @confirm="confirmDeleteSelected"
    />
  </div>
</template>
