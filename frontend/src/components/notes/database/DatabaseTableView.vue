<script setup lang="ts">
/** 表格视图：粘性表头、内联编辑、拖拽调整列宽 / 行高、行详情。 */
import { computed, onBeforeUnmount, ref, watch, watchEffect } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import DatabaseCell from './DatabaseCell.vue'
import DatabaseTableControls from './DatabaseTableControls.vue'
import { fieldTypeMeta } from './meta'
import { applyTableQuery } from './tableQuery'
import type { DbField, DbFilter, DbRow, DbSort, DbView } from '@/stores/noteDatabase'

type ViewPatch = {
  column_widths?: Record<string, number>
  row_heights?: Record<string, number>
  filters?: DbFilter[]
  sorts?: DbSort[]
}

const props = withDefaults(
  defineProps<{
    fields: DbField[]
    rows: DbRow[]
    view: DbView
    selectionMode?: boolean
    selectedIds?: string[]
    /** 内嵌数据表在笔记阅读模式下只呈现内容 */
    editable?: boolean
    /** 内嵌数据表的记录不是独立笔记 */
    allowRowNotes?: boolean
  }>(),
  { selectionMode: false, selectedIds: () => [], editable: true, allowRowNotes: true },
)

const emit = defineEmits<{
  (e: 'update-cell', rowId: string, fieldId: string, value: any): void
  (e: 'create-row'): void
  (e: 'open-row', row: DbRow): void
  (e: 'patch-view', patch: ViewPatch): void
  (e: 'toggle-select', rowId: string): void
  (e: 'select-many', ids: string[], selected: boolean): void
  (e: 'delete-row', row: DbRow): void
  (e: 'open-row-note', row: DbRow): void
}>()

const INDEX_WIDTH = 36
const ACTION_WIDTH = 88
const DEFAULT_COL_WIDTH = 180
const MIN_COL_WIDTH = 60
const MAX_COL_WIDTH = 600
const MIN_ROW_HEIGHT = 36
const MAX_ROW_HEIGHT = 400

const tableRef = ref<HTMLTableElement | null>(null)
const widths = ref<Record<string, number>>({ ...(props.view.column_widths ?? {}) })
const heights = ref<Record<string, number>>({ ...(props.view.row_heights ?? {}) })

watch(
  () => props.view.column_widths,
  (value) => {
    widths.value = { ...(value ?? {}) }
  },
)
watch(
  () => props.view.row_heights,
  (value) => {
    heights.value = { ...(value ?? {}) }
  },
)

const visibleFields = computed(() => {
  const hidden = new Set(props.view.hidden_fields ?? [])
  return props.fields.filter((f) => !hidden.has(f.id))
})

/** 应用筛选与排序后的展示行；原始行数据保持不变。 */
const displayRows = computed(() =>
  applyTableQuery(props.rows, props.fields, props.view.filters, props.view.sorts),
)

const hasQuery = computed(
  () => (props.view.filters?.length ?? 0) > 0 || (props.view.sorts?.length ?? 0) > 0,
)

const selectedSet = computed(() => new Set(props.selectedIds))
const allDisplaySelected = computed(
  () => displayRows.value.length > 0 && displayRows.value.every((r) => selectedSet.value.has(r.id)),
)
const someDisplaySelected = computed(
  () => !allDisplaySelected.value && displayRows.value.some((r) => selectedSet.value.has(r.id)),
)
const headCheckbox = ref<HTMLInputElement | null>(null)

watchEffect(() => {
  if (headCheckbox.value) headCheckbox.value.indeterminate = someDisplaySelected.value
})

function toggleSelectAll() {
  emit(
    'select-many',
    displayRows.value.map((r) => r.id),
    !allDisplaySelected.value,
  )
}

function sortFor(fieldId: string): DbSort | undefined {
  return (props.view.sorts ?? []).find((s) => s.field === fieldId)
}

function sortIndex(fieldId: string): number {
  return (props.view.sorts ?? []).findIndex((s) => s.field === fieldId)
}

/** 点击表头循环：升序 → 降序 → 取消；保留其他字段的多重排序。 */
function toggleSort(field: DbField) {
  if (!props.editable) return
  const current = (props.view.sorts ?? []).map((s) => ({ ...s }))
  const index = current.findIndex((s) => s.field === field.id)
  let next: DbSort[]
  if (index < 0) {
    next = [...current, { field: field.id, direction: 'asc' }]
  } else if (current[index].direction === 'asc') {
    next = current.map((s) => (s.field === field.id ? { ...s, direction: 'desc' as const } : s))
  } else {
    next = current.filter((s) => s.field !== field.id)
  }
  emit('patch-view', { sorts: next })
}

function columnWidth(field: DbField): number {
  return widths.value[field.id] ?? DEFAULT_COL_WIDTH
}

const tableMinWidth = computed(
  () =>
    INDEX_WIDTH +
    (props.editable ? ACTION_WIDTH : 0) +
    visibleFields.value.reduce((sum, field) => sum + columnWidth(field), 0),
)

function rowStyle(row: DbRow) {
  const height = heights.value[row.id]
  return height ? { height: `${height}px` } : {}
}

/** 行高固定时同步约束单元格内容，附件再多也只会被裁切，不会撑高行。 */
function cellStyle(row: DbRow) {
  const height = heights.value[row.id]
  if (!height) return undefined
  const inner = Math.max(8, height - 1)
  return { height: `${inner}px`, maxHeight: `${inner}px` }
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

// ---------- 拖拽调整列宽 / 行高 ----------
type DragState =
  | { type: 'column'; fieldId: string; startX: number; startWidth: number }
  | { type: 'row'; rowId: string; startY: number; startHeight: number }

let drag: DragState | null = null

/** 4K 下 body 带 CSS zoom：getBoundingClientRect / clientX 都是放大后的视口像素，
 *  而列宽行高写的是未放大的 CSS 像素，必须先除掉缩放系数，否则拖拽会飞。 */
function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function startColumnResize(event: MouseEvent, field: DbField) {
  event.preventDefault()
  event.stopPropagation()
  const th = (event.currentTarget as HTMLElement | null)?.closest('th')
  const startWidth = (th?.getBoundingClientRect().width ?? columnWidth(field) * uiScale()) / uiScale()
  drag = { type: 'column', fieldId: field.id, startX: event.clientX, startWidth }
  beginDrag('col-resize')
}

function startRowResize(event: MouseEvent, row: DbRow) {
  event.preventDefault()
  event.stopPropagation()
  const tr = (event.currentTarget as HTMLElement | null)?.closest('tr')
  const startHeight = (tr?.getBoundingClientRect().height ?? 40 * uiScale()) / uiScale()
  drag = { type: 'row', rowId: row.id, startY: event.clientY, startHeight }
  beginDrag('row-resize')
}

function beginDrag(cursor: string) {
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)
  document.body.style.cursor = cursor
  document.body.style.userSelect = 'none'
}

function onDragMove(event: MouseEvent) {
  if (!drag) return
  const scale = uiScale()
  if (drag.type === 'column') {
    const next = Math.round(
      clamp(
        drag.startWidth + (event.clientX - drag.startX) / scale,
        MIN_COL_WIDTH,
        MAX_COL_WIDTH,
      ),
    )
    widths.value = { ...widths.value, [drag.fieldId]: next }
  } else {
    const next = Math.round(
      clamp(
        drag.startHeight + (event.clientY - drag.startY) / scale,
        MIN_ROW_HEIGHT,
        MAX_ROW_HEIGHT,
      ),
    )
    heights.value = { ...heights.value, [drag.rowId]: next }
  }
}

function onDragEnd() {
  if (!drag) return
  const type = drag.type
  drag = null
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  if (type === 'column') {
    emit('patch-view', { column_widths: { ...widths.value } })
  } else {
    emit('patch-view', { row_heights: { ...heights.value } })
  }
}

/** 双击列控件恢复自动列宽；双击行控件恢复自动行高。 */
function resetColumnWidth(field: DbField) {
  const next = { ...widths.value }
  delete next[field.id]
  widths.value = next
  emit('patch-view', { column_widths: next })
}

function resetRowHeight(row: DbRow) {
  const next = { ...heights.value }
  delete next[row.id]
  heights.value = next
  emit('patch-view', { row_heights: next })
}

onBeforeUnmount(() => {
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
})
</script>

<template>
  <div class="flex-1 min-h-0 flex flex-col" :class="{ 'is-readonly': !editable }">
    <!-- 筛选 / 排序工具栏（阅读模式不展示操作栏） -->
    <div v-if="editable" class="shrink-0 flex items-center gap-1 border-b border-slate-200/60 px-2.5 py-1.5">
      <DatabaseTableControls
        :fields="fields"
        :filters="view.filters ?? []"
        :sorts="view.sorts ?? []"
        @change="emit('patch-view', $event)"
      />
      <span v-if="hasQuery" class="ml-auto text-[10px] text-slate-400 tabular-nums">
        {{ displayRows.length }} / {{ rows.length }} 条
      </span>
    </div>

    <div class="flex-1 min-h-0 overflow-auto">
      <table
        ref="tableRef"
        class="w-full table-fixed border-collapse text-left"
        :style="{ minWidth: `${tableMinWidth}px` }"
      >
        <colgroup>
          <col :style="{ width: `${INDEX_WIDTH}px` }" />
          <col
            v-for="field in visibleFields"
            :key="field.id"
            :style="{ width: `${columnWidth(field)}px` }"
          />
          <col v-if="editable" :style="{ width: `${ACTION_WIDTH}px` }" />
        </colgroup>
        <thead>
          <tr class="sticky top-0 z-10 bg-white/90 backdrop-blur-xl">
            <th class="sticky left-0 z-20 border-b border-slate-200/70 bg-white/90 text-center text-[10px] font-normal text-slate-300">
              <input
                v-if="selectionMode"
                ref="headCheckbox"
                type="checkbox"
                class="align-middle rounded border-slate-300 text-kiwi-600 focus:ring-kiwi-300"
                title="全选当前视图"
                :checked="allDisplaySelected"
                :disabled="!displayRows.length"
                @change="toggleSelectAll"
              />
              <template v-else>#</template>
            </th>
            <th
              v-for="field in visibleFields"
              :key="field.id"
              class="relative border-b border-l border-slate-200/60 px-2.5 py-2 text-[11px] font-medium text-slate-500 whitespace-nowrap select-none"
              :class="editable ? 'cursor-pointer hover:bg-kiwi-50/40' : ''"
              :title="editable ? '点击排序：升序 → 降序 → 取消' : undefined"
              @click="toggleSort(field)"
            >
              <span class="flex min-w-0 items-center gap-1.5">
                <KiwiIcon :name="fieldTypeMeta(field.type).icon" :size="11" class="shrink-0 text-slate-300" />
                <span class="truncate">{{ field.name }}</span>
                <span
                  v-if="sortFor(field.id)"
                  class="ml-auto flex shrink-0 items-center gap-0.5 text-kiwi-500"
                >
                  <KiwiIcon
                    :name="sortFor(field.id)?.direction === 'asc' ? 'arrowUp' : 'arrowDown'"
                    :size="10"
                  />
                  <span
                    v-if="(view.sorts?.length ?? 0) > 1"
                    class="text-[9px] tabular-nums"
                  >
                    {{ sortIndex(field.id) + 1 }}
                  </span>
                </span>
              </span>
              <span
                v-if="editable"
                class="db-col-resizer"
                title="拖动调整列宽，双击恢复自动"
                @mousedown="startColumnResize($event, field)"
                @click.stop
                @dblclick.stop.prevent="resetColumnWidth(field)"
              />
            </th>
            <th v-if="editable" class="border-b border-l border-slate-200/60" />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, index) in displayRows"
            :key="row.id"
            class="group border-b border-slate-100 transition-colors hover:bg-kiwi-50/30"
            :style="rowStyle(row)"
          >
            <td class="relative sticky left-0 z-[1] bg-white text-center text-[10px] text-slate-300 tabular-nums select-none group-hover:bg-kiwi-50">
              <input
                v-if="selectionMode"
                type="checkbox"
                class="align-middle rounded border-slate-300 text-kiwi-600 focus:ring-kiwi-300"
                :checked="selectedSet.has(row.id)"
                @click.stop
                @change="emit('toggle-select', row.id)"
              />
              <template v-else>{{ index + 1 }}</template>
              <span
                v-if="editable"
                class="db-row-resizer"
                title="拖动调整行高，双击恢复自动"
                @mousedown="startRowResize($event, row)"
                @dblclick.stop.prevent="resetRowHeight(row)"
              />
            </td>
            <td
              v-for="field in visibleFields"
              :key="field.id"
              class="border-l border-slate-100 align-middle"
              :data-row-id="row.id"
              :data-field-id="field.id"
            >
              <div class="db-cell-clip" :style="cellStyle(row)">
                <DatabaseCell
                  :field="field"
                  :value="row.data[field.id]"
                  :readonly="!editable"
                  @update="emit('update-cell', row.id, field.id, $event)"
                />
              </div>
            </td>
            <td v-if="editable" class="border-l border-slate-100 text-center">
              <div class="flex items-center justify-center gap-0.5">
                <button
                  v-if="allowRowNotes"
                  type="button"
                  class="w-6 h-6 grid place-items-center rounded-md text-slate-300 opacity-0 transition-all group-hover:opacity-100 hover:text-kiwi-600 hover:bg-kiwi-50"
                  :class="row.note_id ? 'text-kiwi-500' : ''"
                  :title="row.note_id ? '打开记录笔记' : '为这条记录生成可编辑笔记'"
                  @click.stop="emit('open-row-note', row)"
                >
                  <KiwiIcon :name="row.note_id ? 'bookOpen' : 'notebook'" :size="12" />
                </button>
                <button
                  type="button"
                  class="w-6 h-6 grid place-items-center rounded-md text-slate-300 opacity-0 transition-all group-hover:opacity-100 hover:text-kiwi-600 hover:bg-kiwi-50"
                  title="展开记录"
                  @click="emit('open-row', row)"
                >
                  <KiwiIcon name="expand" :size="12" />
                </button>
                <button
                  type="button"
                  class="w-6 h-6 grid place-items-center rounded-md text-slate-300 opacity-0 transition-all group-hover:opacity-100 hover:text-rose-500 hover:bg-rose-50"
                  title="删除记录"
                  @click.stop="emit('delete-row', row)"
                >
                  <KiwiIcon name="trash" :size="12" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="!displayRows.length" class="px-4 py-14 text-center">
        <KiwiIcon
          :name="rows.length ? 'filter' : 'table'"
          :size="22"
          class="mx-auto text-slate-300"
        />
        <p class="mt-2 text-[12px] text-slate-400">
          {{ rows.length ? '没有符合筛选条件的记录' : '还没有记录' }}
        </p>
        <button
          v-if="editable && rows.length && (view.filters?.length ?? 0) > 0"
          type="button"
          class="mt-2 text-[11px] text-kiwi-500 hover:text-kiwi-700"
          @click="emit('patch-view', { filters: [] })"
        >
          清除筛选条件
        </button>
      </div>

      <button
        v-if="editable"
        type="button"
        class="sticky left-0 flex items-center gap-1.5 px-3 py-2 text-[11.5px] text-slate-400 transition-colors hover:text-kiwi-600"
        @click="emit('create-row')"
      >
        <KiwiIcon name="plus" :size="13" />
        新建记录
      </button>
    </div>
  </div>
</template>

<style scoped>
.is-readonly .db-cell-clip {
  min-height: 30px;
}
.db-col-resizer {
  position: absolute;
  top: 0;
  right: -3px;
  z-index: 2;
  width: 7px;
  height: 100%;
  cursor: col-resize;
}
.db-col-resizer::after {
  content: '';
  position: absolute;
  top: 24%;
  bottom: 24%;
  left: 3px;
  width: 1px;
  background: #cbd5e1;
  opacity: 0;
  transition:
    opacity 0.12s ease,
    background-color 0.12s ease;
}
th:hover .db-col-resizer::after {
  opacity: 0.8;
}
.db-col-resizer:hover::after,
.db-col-resizer:active::after {
  width: 2px;
  left: 2.5px;
  background: #818cf8;
  opacity: 1;
}
.db-row-resizer {
  position: absolute;
  left: 3px;
  right: 3px;
  bottom: -2px;
  z-index: 2;
  height: 6px;
  cursor: row-resize;
}
.db-row-resizer::after {
  content: '';
  position: absolute;
  left: 20%;
  right: 20%;
  bottom: 2px;
  height: 2px;
  border-radius: 2px;
  background: #a5b4fc;
  opacity: 0;
  transition: opacity 0.12s ease;
}
tr:hover .db-row-resizer::after {
  opacity: 0.55;
}
.db-row-resizer:hover::after,
.db-row-resizer:active::after {
  opacity: 1;
}
/* 列宽 / 行高变化时裁切超出单元格的内容（附件芯片、长文本等） */
.db-cell-clip {
  display: flex;
  align-items: center;
  min-width: 0;
  overflow: hidden;
}
.db-cell-clip > * {
  width: 100%;
  min-width: 0;
  max-height: 100%;
  overflow: hidden;
}
</style>
