<script setup lang="ts">
/** 画册视图：卡片网格，支持封面与标题字段。 */
import { computed } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { chipClass } from './colors'
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
  (e: 'create-row'): void
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

const titleField = computed(
  () =>
    props.fields.find((f) => f.id === props.view.title_field) ??
    props.fields.find((f) => f.type === 'text') ??
    props.fields.find((f) => f.type === 'long_text') ??
    props.fields.find((f) => f.type === 'url') ??
    null,
)
const coverField = computed(
  () => props.fields.find((f) => f.id === props.view.cover_field) ?? null,
)

const COVERS = [
  'from-kiwi-200/70 via-kiwi-100/60 to-white',
  'from-sky-200/60 via-sky-100/50 to-white',
  'from-amber-200/60 via-amber-100/50 to-white',
  'from-emerald-200/60 via-emerald-100/50 to-white',
  'from-rose-200/60 via-rose-100/50 to-white',
]

function coverUrl(row: DbRow): string {
  if (!coverField.value) return ''
  const value = row.data[coverField.value.id]
  if (typeof value !== 'string') return ''
  return /^https?:\/\//i.test(value) ? value : ''
}

function cardTitle(row: DbRow): string {
  if (!titleField.value) return '未命名'
  const value = row.data[titleField.value.id]
  if (value === null || value === undefined || value === '') return '未命名'
  if (titleField.value.type === 'select') {
    return titleField.value.options?.find((o) => o.id === value)?.name ?? '未命名'
  }
  return String(value)
}

function chips(row: DbRow): { id: string; name: string; color?: string }[] {
  const skip = new Set([titleField.value?.id, coverField.value?.id])
  const out: { id: string; name: string; color?: string }[] = []
  for (const field of props.fields) {
    if (skip.has(field.id) || field.type !== 'select') continue
    const value = row.data[field.id]
    const option = field.options?.find((o) => o.id === value)
    if (option) out.push(option)
  }
  return out.slice(0, 2)
}

function dateText(row: DbRow): string {
  for (const field of props.fields) {
    if (field.type !== 'date') continue
    const value = row.data[field.id]
    if (value) return String(value)
  }
  return ''
}
</script>

<template>
  <div class="flex-1 min-h-0 overflow-y-auto p-3" :class="{ 'is-readonly': !editable }">
    <div v-if="rows.length" class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(200px, 1fr))">
      <div
        v-for="(row, index) in rows"
        :key="row.id"
        role="button"
        tabindex="0"
        class="group relative text-left rounded-xl border border-slate-200/70 bg-white/80 overflow-hidden transition-all"
        :class="[
          editable ? 'hover:border-kiwi-200 hover:shadow-lifted cursor-pointer' : 'cursor-default',
          selectedSet.has(row.id) ? 'border-kiwi-300 ring-2 ring-kiwi-200' : '',
        ]"
        @click="onCardClick(row)"
        @keydown.enter.prevent="onCardClick(row)"
      >
        <div v-if="editable" class="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
          <input
            v-if="selectionMode"
            type="checkbox"
            class="rounded border-slate-300 bg-white/90 text-kiwi-600 focus:ring-kiwi-300"
            :checked="selectedSet.has(row.id)"
            @click.stop
            @change="emit('toggle-select', row.id)"
          />
          <button
            type="button"
            class="grid h-6 w-6 place-items-center rounded-md bg-white/90 text-slate-400 opacity-0 shadow-sm transition-opacity hover:text-rose-500 group-hover:opacity-100"
            title="删除记录"
            @click.stop="emit('delete-row', row)"
          >
            <KiwiIcon name="trash" :size="12" />
          </button>
        </div>
        <div class="h-28 relative overflow-hidden">
          <img
            v-if="coverUrl(row)"
            :src="coverUrl(row)"
            class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
            alt=""
            loading="lazy"
          />
          <div
            v-else
            class="w-full h-full bg-gradient-to-br grid place-items-center"
            :class="COVERS[index % COVERS.length]"
          >
            <KiwiIcon name="image" :size="22" class="text-white/80 drop-shadow-sm" />
          </div>
        </div>
        <div class="p-2.5">
          <p class="text-[12.5px] font-medium text-slate-700 leading-snug truncate">
            {{ cardTitle(row) }}
          </p>
          <div v-if="chips(row).length || dateText(row)" class="mt-1.5 flex flex-wrap items-center gap-1">
            <span
              v-for="chip in chips(row)"
              :key="chip.id"
              class="rounded border px-1.5 py-px text-[10px]"
              :class="chipClass(chip.color)"
            >
              {{ chip.name }}
            </span>
            <span v-if="dateText(row)" class="inline-flex items-center gap-1 text-[10px] text-slate-400">
              <KiwiIcon name="calendar" :size="9" />
              {{ dateText(row) }}
            </span>
          </div>
        </div>
      </div>

      <button
        v-if="editable"
        type="button"
        class="rounded-xl border border-dashed border-slate-200/80 min-h-[168px] grid place-items-center text-slate-300 transition-colors hover:border-kiwi-300 hover:text-kiwi-500 hover:bg-kiwi-50/30"
        @click="emit('create-row')"
      >
        <span class="flex flex-col items-center gap-1 text-[11px]">
          <KiwiIcon name="plus" :size="16" />
          新建记录
        </span>
      </button>
    </div>

    <div v-else class="py-16 text-center">
      <KiwiIcon name="gallery" :size="26" class="mx-auto text-slate-300" />
      <p class="mt-2 text-[12px] text-slate-400">还没有画册卡片</p>
      <button
        v-if="editable"
        class="kiwi-btn-secondary mt-3 !py-1.5 !text-xs"
        @click="emit('create-row')"
      >
        <KiwiIcon name="plus" :size="13" />
        新建记录
      </button>
    </div>
  </div>
</template>
