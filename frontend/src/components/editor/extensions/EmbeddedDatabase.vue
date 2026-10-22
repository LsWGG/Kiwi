<script setup lang="ts">
/**
 * 内嵌数据表：与数据表笔记共用字段 / 视图 / 记录模型与四个视图组件。
 * 修改直接回写 Tiptap 节点属性，最终由 Markdown 围栏持久化。
 */
import { computed, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import { toast } from '@/components/ui/toast'
import DatabaseTableView from '@/components/notes/database/DatabaseTableView.vue'
import DatabaseKanbanView from '@/components/notes/database/DatabaseKanbanView.vue'
import DatabaseGalleryView from '@/components/notes/database/DatabaseGalleryView.vue'
import DatabaseCalendarView from '@/components/notes/database/DatabaseCalendarView.vue'
import DatabaseFieldManager from '@/components/notes/database/DatabaseFieldManager.vue'
import DatabaseViewSettings from '@/components/notes/database/DatabaseViewSettings.vue'
import DatabaseRowModal from '@/components/notes/database/DatabaseRowModal.vue'
import { applyTableQuery } from '@/components/notes/database/tableQuery'
import {
  DATATABLE_MAX_COLUMNS,
  DATATABLE_MAX_ROWS,
  inlineRowsForView,
  newInlineViewId,
  newRowId,
  sanitizeViews,
  type InlineDbRow,
} from './dataTableModel'
import { newFieldId, type DbField, type DbFilter, type DbRow, type DbSort, type DbView, type ViewType } from '@/stores/noteDatabase'

const props = defineProps<{
  fields: DbField[]
  views: DbView[]
  rows: InlineDbRow[]
  activeView: string
  editable: boolean
}>()

const emit = defineEmits<{
  (e: 'fields', fields: DbField[]): void
  (e: 'views', views: DbView[]): void
  (e: 'rows', rows: InlineDbRow[]): void
  (e: 'view', viewId: string): void
}>()

const VIEW_META: Record<ViewType, { label: string; icon: string }> = {
  table: { label: '表格', icon: 'table' },
  kanban: { label: '看板', icon: 'kanban' },
  gallery: { label: '画册', icon: 'gallery' },
  calendar: { label: '日历', icon: 'calendar' },
}
const VIEW_TYPES: ViewType[] = ['table', 'kanban', 'gallery', 'calendar']

const activeView = computed(
  () => props.views.find((view) => view.id === props.activeView) ?? props.views[0] ?? null,
)

const dbRows = computed<DbRow[]>(() =>
  inlineRowsForView({
    title: '',
    fields: props.fields,
    views: props.views,
    rows: props.rows,
    view: props.activeView,
  }),
)

// ---------------------------------------------------------------------------
// 视图
// ---------------------------------------------------------------------------

function uniqueViewName(type: ViewType): string {
  const base = VIEW_META[type].label
  const names = new Set(props.views.map((view) => view.name))
  if (!names.has(base)) return base
  let index = 2
  while (names.has(`${base} ${index}`)) index += 1
  return `${base} ${index}`
}

function buildView(type: ViewType): DbView | null {
  const text = props.fields.find((field) => field.type === 'text' || field.type === 'url')?.id ?? null
  const select = props.fields.find((field) => field.type === 'select')?.id ?? null
  const date = props.fields.find((field) => field.type === 'date')?.id ?? null
  if (type === 'kanban' && !select) {
    toast.info('看板需要一个单选字段，请先在字段管理中添加')
    return null
  }
  if (type === 'calendar' && !date) {
    toast.info('日历需要一个日期字段，请先在字段管理中添加')
    return null
  }
  const view: DbView = { id: newInlineViewId(), name: uniqueViewName(type), type }
  if (type === 'table') view.hidden_fields = []
  if (type === 'kanban') {
    view.group_field = select
    view.title_field = text
    view.display_fields = null
  }
  if (type === 'gallery') {
    view.cover_field = null
    view.title_field = text
  }
  if (type === 'calendar') {
    view.date_field = date
    view.end_field = null
    view.title_field = text
    view.bar_color = null
  }
  return view
}

function addView(type: ViewType) {
  const view = buildView(type)
  if (!view) return
  emit('views', [...props.views, view])
  emit('view', view.id)
  toast.success(`已添加${VIEW_META[type].label}视图`)
}

const deletingView = ref<DbView | null>(null)
const viewDeleteOpen = computed({
  get: () => deletingView.value !== null,
  set: (value: boolean) => {
    if (!value) deletingView.value = null
  },
})

function confirmDeleteView() {
  const view = deletingView.value
  deletingView.value = null
  if (!view || props.views.length <= 1) return
  const next = props.views.filter((item) => item.id !== view.id)
  emit('views', next)
  if (activeView.value?.id === view.id) emit('view', next[0].id)
  toast.success('视图已删除')
}

function saveView(view: DbView) {
  emit(
    'views',
    props.views.map((item) => (item.id === view.id ? view : item)),
  )
  viewSettingsOpen.value = false
  toast.success('视图已保存')
}

type TableViewPatch = {
  column_widths?: Record<string, number>
  row_heights?: Record<string, number>
  filters?: DbFilter[]
  sorts?: DbSort[]
}

function patchView(patch: TableViewPatch) {
  const view = activeView.value
  if (!view) return
  emit(
    'views',
    props.views.map((item) => (item.id === view.id ? { ...view, ...patch } : item)),
  )
}

// ---------------------------------------------------------------------------
// 字段
// ---------------------------------------------------------------------------

const fieldManagerOpen = ref(false)

function saveFields(fields: DbField[]) {
  if (!fields.length) return
  const allowed = new Set(fields.map((field) => field.id))
  const nextViews = sanitizeViews(props.views, fields)
  const nextRows = props.rows.map((row) => ({
    id: row.id,
    data: Object.fromEntries(
      Object.entries(row.data).filter(([fieldId]) => allowed.has(fieldId)),
    ),
  }))
  emit('fields', fields)
  emit('views', nextViews)
  emit('rows', nextRows)
  const active = activeView.value
  if (!active || !nextViews.some((view) => view.id === active.id)) {
    emit('view', nextViews[0]?.id ?? '')
  }
  fieldManagerOpen.value = false
  toast.success('字段已保存')
}

// ---------------------------------------------------------------------------
// 记录
// ---------------------------------------------------------------------------

const rowModalOpen = ref(false)
const rowMode = ref<'create' | 'edit'>('create')
const editingRowId = ref<string | null>(null)
const rowPreset = ref<Record<string, any> | null>(null)
const editingRow = computed(
  () => dbRows.value.find((row) => row.id === editingRowId.value) ?? null,
)

const viewSettingsOpen = ref(false)

function openCreateRow(preset?: Record<string, any>) {
  rowMode.value = 'create'
  editingRowId.value = null
  rowPreset.value = preset ?? null
  rowModalOpen.value = true
}

function openRow(row: DbRow) {
  rowMode.value = 'edit'
  editingRowId.value = row.id
  rowPreset.value = null
  rowModalOpen.value = true
}

function saveRow(data: Record<string, any>) {
  const clean: Record<string, any> = {}
  for (const field of props.fields) {
    if (field.id in data) clean[field.id] = data[field.id]
  }
  if (rowMode.value === 'create') {
    if (props.rows.length >= DATATABLE_MAX_ROWS) {
      toast.info(`最多 ${DATATABLE_MAX_ROWS} 条记录`)
      return
    }
    emit('rows', [...props.rows, { id: newRowId(), data: clean }])
  } else if (editingRowId.value) {
    emit(
      'rows',
      props.rows.map((row) =>
        row.id === editingRowId.value ? { id: row.id, data: { ...row.data, ...clean } } : row,
      ),
    )
  }
  rowModalOpen.value = false
}

function updateCell(rowId: string, fieldId: string, value: any) {
  emit(
    'rows',
    props.rows.map((row) =>
      row.id === rowId ? { id: row.id, data: { ...row.data, [fieldId]: value } } : row,
    ),
  )
}

const deleteTarget = ref<DbRow | null>(null)
const deleteOpen = computed({
  get: () => deleteTarget.value !== null,
  set: (value: boolean) => {
    if (!value) deleteTarget.value = null
  },
})
const deleteMessage = computed(() =>
  deleteTarget.value ? `删除「${rowTitle(deleteTarget.value)}」？删除后不可恢复。` : '',
)

function askDeleteRow(row: DbRow) {
  deleteTarget.value = row
}

function removeRowById(id: string) {
  emit('rows', props.rows.filter((row) => row.id !== id))
}

function confirmDeleteRow() {
  const row = deleteTarget.value
  deleteTarget.value = null
  if (!row) return
  removeRowById(row.id)
  toast.success('记录已删除')
}

function deleteFromModal() {
  if (!editingRowId.value) return
  removeRowById(editingRowId.value)
  rowModalOpen.value = false
  toast.success('记录已删除')
}

function rowTitle(row: DbRow): string {
  for (const field of props.fields) {
    if (!['text', 'long_text', 'url'].includes(field.type)) continue
    const value = row.data[field.id]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return '未命名记录'
}

// ---------------------------------------------------------------------------
// 批量选择
// ---------------------------------------------------------------------------

const selectionMode = ref(false)
const selectedRowIds = ref<Set<string>>(new Set())
const selectedIds = computed(() => [...selectedRowIds.value])
const selectedCount = computed(() => selectedRowIds.value.size)

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

function toggleSelectionMode() {
  selectionMode.value = !selectionMode.value
  if (!selectionMode.value) selectedRowIds.value = new Set()
}

const batchDeleteOpen = ref(false)

function confirmDeleteSelected() {
  const ids = selectedRowIds.value
  batchDeleteOpen.value = false
  if (!ids.size) return
  emit(
    'rows',
    props.rows.filter((row) => !ids.has(row.id)),
  )
  toast.success(`已删除 ${ids.size} 条记录`)
  selectedRowIds.value = new Set()
}

// ---------------------------------------------------------------------------
// 从 Excel / 表格批量粘贴（Tab 分隔）
// ---------------------------------------------------------------------------

function normalizePasteDate(value: string): string | null {
  const match = value.trim().match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function coercePasteValue(field: DbField, raw: string): any {
  const text = raw.trim()
  if (field.type === 'checkbox') {
    return ['1', 'true', '是', '✓', 'yes'].includes(text.toLowerCase())
  }
  if (!text) return null
  if (field.type === 'number') {
    const number = Number(text.replace(/,/g, ''))
    return Number.isFinite(number) ? number : null
  }
  if (field.type === 'rating') {
    const number = Number(text)
    return Number.isFinite(number) ? Math.max(0, Math.min(5, Math.round(number))) : null
  }
  if (field.type === 'progress') {
    const number = Number(text.replace(/%$/, ''))
    return Number.isFinite(number) ? Math.max(0, Math.min(100, Math.round(number))) : null
  }
  if (field.type === 'date') return normalizePasteDate(text)
  if (field.type === 'select') {
    const option = (field.options ?? []).find(
      (item) => item.name === text || item.id === text,
    )
    return option?.id ?? null
  }
  if (field.type === 'multi_select') {
    const names = text.split(/[,，、;；]/).map((item) => item.trim()).filter(Boolean)
    const ids = names
      .map((name) => (field.options ?? []).find((item) => item.name === name || item.id === name)?.id)
      .filter((id): id is string => !!id)
    return ids
  }
  if (field.type === 'attachment') return null
  return text.slice(0, field.type === 'long_text' ? 20000 : 5000)
}

function onPasteCapture(event: ClipboardEvent) {
  if (!props.editable || activeView.value?.type !== 'table') return
  const target = event.target as HTMLElement | null
  const cell = target?.closest?.('td[data-row-id][data-field-id]') as HTMLElement | null
  if (!cell) return
  const text = event.clipboardData?.getData('text/plain') ?? ''
  if (!text || (!text.includes('\t') && !text.includes('\n'))) return

  const rowId = cell.dataset.rowId ?? ''
  const fieldId = cell.dataset.fieldId ?? ''
  const view = activeView.value
  // 粘贴以「当前视图看到的行」为准：排序 / 筛选后仍写入用户眼前的记录
  const displayRows = applyTableQuery(dbRows.value, props.fields, view.filters, view.sorts)
  const startRow = displayRows.findIndex((row) => row.id === rowId)
  if (startRow < 0) return

  const hidden = new Set(view.hidden_fields ?? [])
  const visibleFields = props.fields.filter((field) => !hidden.has(field.id))
  const startColumn = visibleFields.findIndex((field) => field.id === fieldId)
  if (startColumn < 0) return

  const grid = text
    .replace(/\r/g, '')
    .replace(/\n$/, '')
    .split('\n')
    .map((line) => line.split('\t'))
  if (!grid.length) return
  event.preventDefault()

  const width = Math.max(...grid.map((line) => line.length))
  const additions: DbField[] = []
  while (
    visibleFields.length + additions.length < startColumn + width &&
    props.fields.length + additions.length < DATATABLE_MAX_COLUMNS
  ) {
    additions.push({
      id: newFieldId(),
      name: `列 ${props.fields.length + additions.length + 1}`,
      type: 'text',
    })
  }
  const nextFields = [...props.fields, ...additions]
  const targetFields = [...visibleFields, ...additions]

  const nextRows = props.rows.map((row) => ({ id: row.id, data: { ...row.data } }))
  const rawIndexById = new Map(nextRows.map((row, index) => [row.id, index]))
  grid.forEach((line, rowOffset) => {
    const displayRow = displayRows[startRow + rowOffset]
    let rawIndex = displayRow ? rawIndexById.get(displayRow.id) : undefined
    if (rawIndex === undefined) {
      if (nextRows.length >= DATATABLE_MAX_ROWS) return
      const created = { id: newRowId(), data: {} }
      nextRows.push(created)
      rawIndex = nextRows.length - 1
      rawIndexById.set(created.id, rawIndex)
    }
    const row = nextRows[rawIndex]
    if (!row) return
    line.forEach((raw, columnOffset) => {
      const field = targetFields[startColumn + columnOffset]
      if (!field) return
      row.data[field.id] = coercePasteValue(field, raw)
    })
  })

  if (additions.length) emit('fields', nextFields)
  emit('rows', nextRows)
  toast.success(`已粘贴 ${grid.length} 行 × ${width} 列`)
}
</script>

<template>
  <div class="kiwi-embedded-db" :class="{ 'is-readonly': !editable }">
    <!-- 编辑工具条 -->
    <div v-if="editable" class="kiwi-embedded-db-head">
      <span class="kiwi-embedded-db-count">{{ rows.length }} 条记录</span>
      <div class="flex-1" />
      <button
        type="button"
        class="kiwi-embedded-db-action is-primary"
        :disabled="!activeView"
        @mousedown.prevent
        @click="openCreateRow()"
      >
        <KiwiIcon name="plus" :size="11" />
        新建记录
      </button>
      <button
        type="button"
        class="kiwi-embedded-db-action"
        @mousedown.prevent
        @click="fieldManagerOpen = true"
      >
        <KiwiIcon name="columns" :size="11" />
        字段
      </button>
      <button
        type="button"
        class="kiwi-embedded-db-action"
        :disabled="!activeView"
        @mousedown.prevent
        @click="viewSettingsOpen = true"
      >
        <KiwiIcon name="settings" :size="11" />
        视图设置
      </button>
      <button
        type="button"
        class="kiwi-embedded-db-action"
        :class="selectionMode ? '!text-kiwi-600 !bg-kiwi-50' : ''"
        @mousedown.prevent
        @click="toggleSelectionMode"
      >
        <KiwiIcon name="check" :size="11" />
        {{ selectionMode ? '退出选择' : '选择' }}
      </button>
    </div>

    <!-- 视图页签 -->
    <div v-if="editable" class="kiwi-embedded-db-tabs">
      <div
        v-for="view in views"
        :key="view.id"
        class="group flex shrink-0 items-center rounded-md transition-colors"
        :class="
          activeView?.id === view.id
            ? 'bg-kiwi-100/80 text-kiwi-700'
            : 'text-slate-500 hover:bg-white/80'
        "
      >
        <button
          type="button"
          class="flex h-6 items-center gap-1 pl-1.5 pr-1 text-[11px]"
          @mousedown.prevent
          @click="emit('view', view.id)"
        >
          <KiwiIcon :name="VIEW_META[view.type].icon" :size="10" />
          {{ view.name }}
        </button>
        <button
          v-if="views.length > 1"
          type="button"
          class="mr-0.5 grid h-3.5 w-3.5 place-items-center rounded text-slate-300 opacity-0 hover:bg-white hover:text-rose-500 group-hover:opacity-100"
          title="删除视图"
          @mousedown.prevent
          @click.stop="deletingView = view"
        >
          <KiwiIcon name="close" :size="8" />
        </button>
      </div>

      <KiwiDropdown width="w-36">
        <template #trigger="{ open }">
          <button
            type="button"
            class="grid h-5 w-5 place-items-center rounded text-slate-400 hover:bg-white/80 hover:text-kiwi-600"
            :class="open ? 'bg-white/80 text-kiwi-600' : ''"
            title="添加视图"
            @mousedown.prevent
          >
            <KiwiIcon name="plus" :size="11" />
          </button>
        </template>
        <template #default="{ close }">
          <button
            v-for="type in VIEW_TYPES"
            :key="type"
            type="button"
            class="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-[11.5px] text-slate-600 hover:bg-kiwi-50"
            @click="close(); addView(type)"
          >
            <KiwiIcon :name="VIEW_META[type].icon" :size="12" class="text-slate-400" />
            {{ VIEW_META[type].label }}视图
          </button>
        </template>
      </KiwiDropdown>
    </div>

    <!-- 批量选择工具条 -->
    <div v-if="editable && selectionMode" class="kiwi-embedded-db-selection">
      <button type="button" @click="selectRows(dbRows.map((row) => row.id), selectedCount !== dbRows.length)">
        {{ selectedCount === dbRows.length && dbRows.length ? '取消全选' : '全选' }}
      </button>
      <span>已选 {{ selectedCount }} 条</span>
      <button
        type="button"
        class="is-danger"
        :disabled="!selectedCount"
        @click="batchDeleteOpen = true"
      >
        <KiwiIcon name="trash" :size="10" />
        删除所选
      </button>
      <button type="button" class="ml-auto" @click="selectedRowIds = new Set()">取消选择</button>
    </div>

    <!-- 四个视图共享同一批记录 -->
    <div class="kiwi-embedded-db-body" @paste.capture="onPasteCapture">
      <DatabaseTableView
        v-if="activeView?.type === 'table'"
        :fields="fields"
        :rows="dbRows"
        :view="activeView"
        :editable="editable"
        :selection-mode="editable && selectionMode"
        :selected-ids="selectedIds"
        :allow-row-notes="false"
        @update-cell="updateCell"
        @create-row="openCreateRow()"
        @open-row="openRow"
        @patch-view="patchView"
        @toggle-select="toggleSelect"
        @select-many="selectRows"
        @delete-row="askDeleteRow"
      />
      <DatabaseKanbanView
        v-else-if="activeView?.type === 'kanban'"
        :fields="fields"
        :rows="dbRows"
        :view="activeView"
        :editable="editable"
        :selection-mode="editable && selectionMode"
        :selected-ids="selectedIds"
        @update-cell="updateCell"
        @create-row="openCreateRow"
        @open-row="openRow"
        @toggle-select="toggleSelect"
        @delete-row="askDeleteRow"
      />
      <DatabaseGalleryView
        v-else-if="activeView?.type === 'gallery'"
        :fields="fields"
        :rows="dbRows"
        :view="activeView"
        :editable="editable"
        :selection-mode="editable && selectionMode"
        :selected-ids="selectedIds"
        @create-row="openCreateRow()"
        @open-row="openRow"
        @toggle-select="toggleSelect"
        @delete-row="askDeleteRow"
      />
      <DatabaseCalendarView
        v-else-if="activeView?.type === 'calendar'"
        :fields="fields"
        :rows="dbRows"
        :view="activeView"
        :editable="editable"
        :selection-mode="editable && selectionMode"
        :selected-ids="selectedIds"
        @create-row="openCreateRow"
        @open-row="openRow"
        @toggle-select="toggleSelect"
        @delete-row="askDeleteRow"
      />
    </div>

    <DatabaseFieldManager
      v-if="editable"
      :open="fieldManagerOpen"
      :fields="fields"
      @close="fieldManagerOpen = false"
      @save="saveFields"
    />
    <DatabaseViewSettings
      v-if="editable"
      :open="viewSettingsOpen"
      :fields="fields"
      :view="activeView"
      @close="viewSettingsOpen = false"
      @save="saveView"
    />
    <DatabaseRowModal
      v-if="editable"
      :open="rowModalOpen"
      :mode="rowMode"
      :fields="fields"
      :row="editingRow"
      :preset="rowPreset"
      :note-integration="false"
      @close="rowModalOpen = false"
      @save="saveRow"
      @delete="deleteFromModal"
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
      v-model="viewDeleteOpen"
      danger
      title="删除视图"
      :message="`删除视图「${deletingView?.name ?? ''}」？记录不会被删除。`"
      confirm-text="删除"
      @confirm="confirmDeleteView"
    />
    <KiwiConfirm
      v-model="batchDeleteOpen"
      danger
      title="批量删除记录"
      :message="`删除选中的 ${selectedCount} 条记录？删除后不可恢复。`"
      confirm-text="删除"
      @confirm="confirmDeleteSelected"
    />
  </div>
</template>

<style scoped>
.kiwi-embedded-db {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.kiwi-embedded-db-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 3px;
}
.kiwi-embedded-db-count {
  font-size: 10px;
  color: rgb(148 163 184);
  font-variant-numeric: tabular-nums;
}
.kiwi-embedded-db-action {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 22px;
  padding: 0 6px;
  border-radius: 6px;
  font-size: 10.5px;
  color: rgb(100 116 139);
  transition: background 0.15s ease, color 0.15s ease;
}
.kiwi-embedded-db-action:hover {
  background: rgb(var(--kiwi-50));
  color: rgb(var(--kiwi-700));
}
.kiwi-embedded-db-action:disabled {
  opacity: 0.4;
}
.kiwi-embedded-db-action.is-primary {
  background: rgb(var(--kiwi-600));
  color: white;
}
.kiwi-embedded-db-action.is-primary:hover {
  background: rgb(var(--kiwi-700));
  color: white;
}
.kiwi-embedded-db-tabs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px;
  padding: 2px 8px 4px;
  border-bottom: 1px solid rgb(241 245 249);
}
.kiwi-embedded-db-selection {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 3px 8px;
  font-size: 10.5px;
  color: rgb(100 116 139);
  border-bottom: 1px solid rgb(241 245 249);
}
.kiwi-embedded-db-selection button:hover {
  color: rgb(var(--kiwi-700));
}
.kiwi-embedded-db-selection button.is-danger {
  color: rgb(244 63 94);
}
.kiwi-embedded-db-selection button:disabled {
  color: rgb(203 213 225);
}
.kiwi-embedded-db-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  height: clamp(300px, 44vh, 480px);
}
.kiwi-embedded-db.is-readonly .kiwi-embedded-db-body {
  height: clamp(300px, 44vh, 480px);
}
</style>
