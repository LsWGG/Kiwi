<script setup lang="ts">
/** 看板视图：按单选字段分列，拖拽卡片改变分组。 */
import { computed, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { chipClass, dotClass } from './colors'
import { fieldTypeMeta } from './meta'
import type { DbField, DbRow, DbView } from '@/stores/noteDatabase'

const props = withDefaults(
  defineProps<{
    fields: DbField[]
    rows: DbRow[]
    view: DbView
    selectionMode?: boolean
    selectedIds?: string[]
    /** 内嵌数据表在笔记阅读模式下只呈现内容 */
    editable?: boolean
  }>(),
  { selectionMode: false, selectedIds: () => [], editable: true },
)

const emit = defineEmits<{
  (e: 'update-cell', rowId: string, fieldId: string, value: any): void
  (e: 'create-row', preset?: Record<string, any>): void
  (e: 'open-row', row: DbRow): void
  (e: 'toggle-select', rowId: string): void
  (e: 'delete-row', row: DbRow): void
}>()

const selectedSet = computed(() => new Set(props.selectedIds))

function onCardClick(row: DbRow) {
  if (!props.editable) return
  if (props.selectionMode) emit('toggle-select', row.id)
  else emit('open-row', row)
}

const groupField = computed(
  () => props.fields.find((f) => f.id === props.view.group_field) ?? null,
)
const titleField = computed(
  () =>
    props.fields.find((f) => f.id === props.view.title_field) ??
    props.fields.find((f) => f.type === 'text') ??
    props.fields.find((f) => f.type === 'long_text') ??
    props.fields.find((f) => f.type === 'url') ??
    null,
)
const columns = computed(() => {
  const options = groupField.value?.options ?? []
  return [
    ...options.map((o) => ({ id: o.id as string | null, name: o.name, color: o.color })),
    { id: null as string | null, name: '未分组', color: 'slate' },
  ]
})

function rowsOf(colId: string | null): DbRow[] {
  if (!groupField.value) return props.rows
  return props.rows.filter((row) => {
    const value = row.data[groupField.value!.id]
    return colId === null ? !value : value === colId
  })
}

function cellText(row: DbRow, field: DbField): string {
  const value = row.data[field.id]
  if (value === null || value === undefined || value === '') return ''
  if (field.type === 'select') {
    return field.options?.find((o) => o.id === value)?.name ?? ''
  }
  if (field.type === 'multi_select') {
    return (Array.isArray(value) ? value : [])
      .map((id: string) => field.options?.find((o) => o.id === id)?.name)
      .filter(Boolean)
      .join('、')
  }
  if (field.type === 'checkbox') return value ? '是' : '否'
  if (field.type === 'progress') {
    const n = Number(value)
    return Number.isFinite(n) ? `${Math.round(n)}%` : ''
  }
  if (field.type === 'attachment') {
    const count = Array.isArray(value) ? value.length : 0
    return count ? `${count} 个附件` : ''
  }
  return String(value)
}

function cardTitle(row: DbRow): string {
  if (titleField.value) {
    const text = cellText(row, titleField.value)
    if (text) return text
  }
  return '未命名'
}

function previewFields(row: DbRow): { field: DbField; text: string }[] {
  const skip = new Set([groupField.value?.id, titleField.value?.id])
  const configured = props.view.display_fields
  if (Array.isArray(configured)) {
    return configured
      .map((id) => props.fields.find((f) => f.id === id))
      .filter((f): f is DbField => !!f && !skip.has(f.id))
      .map((f) => ({ field: f, text: cellText(row, f) }))
      .filter((x) => x.text)
      .slice(0, 8)
  }
  return props.fields
    .filter((f) => !skip.has(f.id) && f.type !== 'checkbox')
    .map((f) => ({ field: f, text: cellText(row, f) }))
    .filter((x) => x.text)
    .slice(0, 2)
}

// ---------- 拖拽 ----------
const dragId = ref<string | null>(null)
const dragOver = ref<string | null>(null)

function onDragStart(event: DragEvent, row: DbRow) {
  if (!props.editable) {
    event.preventDefault()
    return
  }
  dragId.value = row.id
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', row.id)
  }
}

function onDrop(colId: string | null) {
  if (!props.editable) return
  const id = dragId.value
  dragId.value = null
  dragOver.value = null
  if (!id || !groupField.value) return
  emit('update-cell', id, groupField.value.id, colId)
}

function onColLeave(event: DragEvent, key: string) {
  const el = event.currentTarget as HTMLElement
  if (event.relatedTarget && el.contains(event.relatedTarget as Node)) return
  if (dragOver.value === key) dragOver.value = null
}

function colKey(colId: string | null) {
  return colId ?? '__none__'
}
</script>

<template>
  <div v-if="!groupField" class="flex-1 grid place-items-center">
    <div class="text-center">
      <KiwiIcon name="kanban" :size="26" class="mx-auto text-slate-300" />
      <p class="mt-2 text-[12px] text-slate-400">看板需要一个单选字段作为分组依据</p>
      <p class="mt-0.5 text-[11px] text-slate-300">可在“视图设置”中选择分组字段</p>
    </div>
  </div>

  <div
    v-else
    class="flex-1 min-h-0 overflow-x-auto overflow-y-hidden px-3 py-3"
    :class="{ 'is-readonly': !editable }"
  >
    <div class="h-full flex gap-3 items-start">
      <div
        v-for="col in columns"
        :key="colKey(col.id)"
        class="w-[260px] shrink-0 flex flex-col max-h-full rounded-xl border transition-colors"
        :class="dragOver === colKey(col.id) ? 'border-kiwi-300 bg-kiwi-50/50' : 'border-slate-200/60 bg-white/40'"
        @dragover.prevent="dragOver = colKey(col.id)"
        @dragleave="onColLeave($event, colKey(col.id))"
        @drop.prevent="onDrop(col.id)"
      >
        <div class="shrink-0 flex items-center gap-1.5 px-2.5 py-2">
          <span class="w-2 h-2 rounded-full" :class="dotClass(col.color)" />
          <span class="text-[11.5px] font-medium text-slate-600 truncate">{{ col.name }}</span>
          <span class="text-[10px] text-slate-400 tabular-nums">{{ rowsOf(col.id).length }}</span>
          <div class="flex-1" />
          <button
            v-if="editable"
            class="w-5 h-5 grid place-items-center rounded text-slate-300 hover:text-kiwi-600 hover:bg-kiwi-50"
            title="在此列新建"
            @click="emit('create-row', col.id ? { [groupField.id]: col.id } : {})"
          >
            <KiwiIcon name="plus" :size="12" />
          </button>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto px-2 pb-2 space-y-2">
          <div
            v-for="row in rowsOf(col.id)"
            :key="row.id"
            role="button"
            tabindex="0"
            :draggable="editable"
            class="group relative w-full rounded-lg border border-slate-200/70 bg-white/90 px-2.5 py-2 text-left shadow-soft transition-all hover:border-kiwi-200 hover:shadow-lifted"
            :class="[
              editable ? 'cursor-grab active:cursor-grabbing' : 'cursor-default',
              dragId === row.id ? 'opacity-40' : '',
              selectedSet.has(row.id) ? 'border-kiwi-300 ring-2 ring-kiwi-200' : '',
            ]"
            @click="onCardClick(row)"
            @keydown.enter.prevent="onCardClick(row)"
            @dragstart="onDragStart($event, row)"
            @dragend="dragId = null"
          >
            <div v-if="editable" class="absolute right-1 top-1 z-10 flex items-center gap-0.5">
              <input
                v-if="selectionMode"
                type="checkbox"
                class="rounded border-slate-300 text-kiwi-600 focus:ring-kiwi-300"
                :checked="selectedSet.has(row.id)"
                @click.stop
                @change="emit('toggle-select', row.id)"
              />
              <button
                type="button"
                class="grid h-5 w-5 place-items-center rounded text-slate-300 opacity-0 transition-opacity hover:bg-rose-50 hover:text-rose-500 group-hover:opacity-100"
                title="删除记录"
                @click.stop="emit('delete-row', row)"
              >
                <KiwiIcon name="trash" :size="11" />
              </button>
            </div>
            <p class="pr-10 text-[12px] font-medium text-slate-700 leading-snug line-clamp-2">
              {{ cardTitle(row) }}
            </p>
            <div v-if="previewFields(row).length" class="mt-1.5 flex flex-wrap gap-1">
              <span
                v-for="item in previewFields(row)"
                :key="item.field.id"
                class="inline-flex items-center gap-1 rounded px-1.5 py-px text-[10px]"
                :class="item.field.type === 'select' || item.field.type === 'multi_select'
                  ? chipClass(item.field.options?.[0]?.color)
                  : 'bg-slate-50 text-slate-500 border border-slate-200/60'"
              >
                <KiwiIcon
                  v-if="item.field.type === 'date'"
                  :name="fieldTypeMeta(item.field.type).icon"
                  :size="9"
                />
                {{ item.text }}
              </span>
            </div>
          </div>

          <button
            v-if="editable"
            class="w-full rounded-lg border border-dashed border-slate-200/70 py-1.5 text-[10.5px] text-slate-300 transition-colors hover:border-kiwi-300 hover:text-kiwi-500"
            @click="emit('create-row', col.id ? { [groupField.id]: col.id } : {})"
          >
            + 新建
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
