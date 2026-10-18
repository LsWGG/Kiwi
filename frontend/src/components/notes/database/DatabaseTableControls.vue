<script setup lang="ts">
/** 表格工具栏：字段筛选与多字段排序。 */
import { computed } from 'vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import type { DbField, DbFilter, DbSort } from '@/stores/noteDatabase'

type Op = DbFilter['op']
type Patch = { filters?: DbFilter[]; sorts?: DbSort[] }

const props = defineProps<{
  fields: DbField[]
  filters: DbFilter[]
  sorts: DbSort[]
}>()

const emit = defineEmits<{
  (e: 'change', patch: Patch): void
}>()

const OP_LABEL: Record<Op, string> = {
  contains: '包含',
  not_contains: '不包含',
  is: '是',
  is_not: '不是',
  is_empty: '为空',
  is_not_empty: '不为空',
  gt: '大于',
  gte: '大于等于',
  lt: '小于',
  lte: '小于等于',
}

function opsFor(field: DbField): Op[] {
  switch (field.type) {
    case 'number':
    case 'rating':
    case 'progress':
    case 'date':
      return ['is', 'is_not', 'gt', 'gte', 'lt', 'lte', 'is_empty', 'is_not_empty']
    case 'select':
      return ['is', 'is_not', 'is_empty', 'is_not_empty']
    case 'multi_select':
      return ['contains', 'not_contains', 'is_empty', 'is_not_empty']
    case 'checkbox':
      return ['is', 'is_not']
    case 'attachment':
      return ['is_empty', 'is_not_empty']
    default:
      return ['contains', 'not_contains', 'is', 'is_not', 'is_empty', 'is_not_empty']
  }
}

function needsValue(op: Op): boolean {
  return op !== 'is_empty' && op !== 'is_not_empty'
}

const filters = computed(() => props.filters ?? [])
const sorts = computed(() => props.sorts ?? [])

const filterRows = computed(() =>
  filters.value.flatMap((filter) => {
    const field = props.fields.find((f) => f.id === filter.field)
    return field ? [{ filter, field }] : []
  }),
)

const sortRows = computed(() =>
  sorts.value.flatMap((sort, index) => {
    const field = props.fields.find((f) => f.id === sort.field)
    return field ? [{ sort, field, index }] : []
  }),
)

function emitFilters(next: DbFilter[]) {
  emit('change', { filters: next })
}

function emitSorts(next: DbSort[]) {
  emit('change', { sorts: next })
}

let seq = 0
function newFilterId(): string {
  seq += 1
  return `flt_${Date.now().toString(36)}_${seq}`
}

function defaultValue(field: DbField, op: Op): DbFilter['value'] {
  if (!needsValue(op)) return null
  if (field.type === 'checkbox') return false
  return ''
}

/** 值编辑器统一显示为字符串（boolean / number 也能安全绑定）。 */
function textValue(filter: DbFilter): string {
  return filter.value === null || filter.value === undefined ? '' : String(filter.value)
}

function addFilter() {
  const field = props.fields[0]
  if (!field) return
  const op = opsFor(field)[0]
  emitFilters([
    ...filters.value.map((f) => ({ ...f })),
    { id: newFilterId(), field: field.id, op, value: defaultValue(field, op) },
  ])
}

function updateFilter(id: string, patch: Partial<DbFilter>) {
  emitFilters(filters.value.map((f) => (f.id === id ? { ...f, ...patch } : { ...f })))
}

function changeField(filter: DbFilter, event: Event) {
  const fieldId = (event.target as HTMLSelectElement).value
  const field = props.fields.find((f) => f.id === fieldId)
  if (!field) return
  const op = opsFor(field)[0]
  updateFilter(filter.id, { field: field.id, op, value: defaultValue(field, op) })
}

function changeOp(filter: DbFilter, event: Event) {
  const op = (event.target as HTMLSelectElement).value as Op
  const field = props.fields.find((f) => f.id === filter.field)
  if (!field || !opsFor(field).includes(op)) return
  // 同为需要值的条件之间切换时保留已输入的值
  const value = !needsValue(op)
    ? null
    : needsValue(filter.op)
      ? filter.value
      : defaultValue(field, op)
  updateFilter(filter.id, { op, value })
}

function onTextValue(filter: DbFilter, event: Event) {
  const raw = (event.target as HTMLInputElement).value
  updateFilter(filter.id, { value: raw === '' ? null : raw })
}

function onNumberValue(filter: DbFilter, event: Event) {
  const raw = (event.target as HTMLInputElement).value
  const value = raw === '' ? null : Number(raw)
  updateFilter(filter.id, { value: value === null || Number.isNaN(value) ? null : value })
}

function onDateValue(filter: DbFilter, event: Event) {
  const raw = (event.target as HTMLInputElement).value
  updateFilter(filter.id, { value: raw || null })
}

function onSelectValue(filter: DbFilter, event: Event) {
  const raw = (event.target as HTMLSelectElement).value
  updateFilter(filter.id, { value: raw || null })
}

function onCheckboxValue(filter: DbFilter, event: Event) {
  updateFilter(filter.id, { value: (event.target as HTMLSelectElement).value === 'true' })
}

function removeFilter(id: string) {
  emitFilters(filters.value.filter((f) => f.id !== id).map((f) => ({ ...f })))
}

function clearFilters() {
  emitFilters([])
}

const canAddSort = computed(
  () =>
    sorts.value.length < 5 &&
    props.fields.some((f) => !sorts.value.some((s) => s.field === f.id)),
)

function addSort() {
  const used = new Set(sorts.value.map((s) => s.field))
  const field = props.fields.find((f) => !used.has(f.id))
  if (!field) return
  emitSorts([...sorts.value.map((s) => ({ ...s })), { field: field.id, direction: 'asc' }])
}

function changeSortField(sort: DbSort, event: Event) {
  const next = (event.target as HTMLSelectElement).value
  if (next === sort.field || sorts.value.some((s) => s.field === next)) return
  emitSorts(
    sorts.value.map((s) => (s.field === sort.field ? { ...s, field: next } : { ...s })),
  )
}

function toggleDirection(sort: DbSort) {
  emitSorts(
    sorts.value.map((s) =>
      s.field === sort.field ? { ...s, direction: s.direction === 'asc' ? 'desc' : 'asc' } : { ...s },
    ),
  )
}

function moveSort(index: number, delta: number) {
  const next = sorts.value.map((s) => ({ ...s }))
  const target = index + delta
  if (target < 0 || target >= next.length) return
  ;[next[index], next[target]] = [next[target], next[index]]
  emitSorts(next)
}

function removeSort(field: string) {
  emitSorts(sorts.value.filter((s) => s.field !== field).map((s) => ({ ...s })))
}

function clearSorts() {
  emitSorts([])
}
</script>

<template>
  <div class="flex items-center gap-1">
    <!-- 筛选 -->
    <KiwiDropdown width="w-[340px]">
      <template #trigger="{ open }">
        <button
          type="button"
          class="flex h-7 items-center gap-1 rounded-lg px-2 text-[11px] transition-colors"
          :class="
            open || filters.length
              ? 'bg-kiwi-50 text-kiwi-600'
              : 'text-slate-500 hover:bg-white hover:text-kiwi-600'
          "
          title="按字段筛选记录"
        >
          <KiwiIcon name="filter" :size="12" />
          筛选
          <span
            v-if="filters.length"
            class="grid h-4 min-w-[16px] place-items-center rounded-full bg-kiwi-100 px-1 text-[9px] tabular-nums text-kiwi-600"
          >
            {{ filters.length }}
          </span>
        </button>
      </template>
      <template #default>
        <div class="p-1">
          <div class="flex items-center justify-between px-1 pb-1.5">
            <span class="text-[11px] font-medium text-slate-500">筛选条件</span>
            <button
              v-if="filters.length"
              type="button"
              class="text-[10.5px] text-slate-400 hover:text-rose-500"
              @click="clearFilters"
            >
              清除全部
            </button>
          </div>

          <div
            v-for="row in filterRows"
            :key="row.filter.id"
            class="mb-1.5 space-y-1.5 rounded-lg border border-slate-100 bg-slate-50/60 p-1.5"
          >
            <div class="flex items-center gap-1">
              <select
                :value="row.filter.field"
                class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
                @change="changeField(row.filter, $event)"
              >
                <option v-for="field in fields" :key="field.id" :value="field.id">
                  {{ field.name }}
                </option>
              </select>
              <button
                type="button"
                class="grid h-6 w-6 shrink-0 place-items-center rounded text-slate-300 hover:bg-rose-50 hover:text-rose-500"
                title="移除条件"
                @click="removeFilter(row.filter.id)"
              >
                <KiwiIcon name="close" :size="10" />
              </button>
            </div>
            <div class="flex items-center gap-1">
              <select
                :value="row.filter.op"
                class="h-7 w-[86px] shrink-0 rounded-md border border-slate-200 bg-white px-1 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
                @change="changeOp(row.filter, $event)"
              >
                <option v-for="op in opsFor(row.field)" :key="op" :value="op">
                  {{ OP_LABEL[op] }}
                </option>
              </select>

              <template v-if="needsValue(row.filter.op) && row.field.type !== 'attachment'">
                <select
                  v-if="row.field.type === 'select' || row.field.type === 'multi_select'"
                  :value="textValue(row.filter)"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
                  @change="onSelectValue(row.filter, $event)"
                >
                  <option value="">选择选项…</option>
                  <option
                    v-for="option in row.field.options ?? []"
                    :key="option.id"
                    :value="option.id"
                  >
                    {{ option.name }}
                  </option>
                </select>
                <select
                  v-else-if="row.field.type === 'checkbox'"
                  :value="String(row.filter.value === true)"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
                  @change="onCheckboxValue(row.filter, $event)"
                >
                  <option value="true">已勾选</option>
                  <option value="false">未勾选</option>
                </select>
                <input
                  v-else-if="row.field.type === 'date'"
                  type="date"
                  :value="textValue(row.filter)"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
                  @change="onDateValue(row.filter, $event)"
                />
                <input
                  v-else-if="row.field.type === 'number' || row.field.type === 'rating' || row.field.type === 'progress'"
                  type="number"
                  :value="textValue(row.filter)"
                  placeholder="数值"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
                  @input="onNumberValue(row.filter, $event)"
                />
                <input
                  v-else
                  type="text"
                  :value="textValue(row.filter)"
                  placeholder="输入值"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
                  @input="onTextValue(row.filter, $event)"
                />
              </template>
            </div>
          </div>

          <div v-if="!filterRows.length" class="px-1 pb-2 text-[11px] text-slate-400">
            还没有筛选条件
          </div>

          <button
            type="button"
            class="flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-slate-200 py-1.5 text-[11px] text-slate-400 transition-colors hover:border-kiwi-300 hover:text-kiwi-600"
            @click="addFilter"
          >
            <KiwiIcon name="plus" :size="11" />
            添加筛选条件
          </button>
          <p class="px-1 pt-1.5 text-[10px] text-slate-400">多个条件需同时满足（AND）</p>
        </div>
      </template>
    </KiwiDropdown>

    <!-- 排序 -->
    <KiwiDropdown width="w-[324px]">
      <template #trigger="{ open }">
        <button
          type="button"
          class="flex h-7 items-center gap-1 rounded-lg px-2 text-[11px] transition-colors"
          :class="
            open || sorts.length
              ? 'bg-kiwi-50 text-kiwi-600'
              : 'text-slate-500 hover:bg-white hover:text-kiwi-600'
          "
          title="按字段排序记录"
        >
          <KiwiIcon name="sort" :size="12" />
          排序
          <span
            v-if="sorts.length"
            class="grid h-4 min-w-[16px] place-items-center rounded-full bg-kiwi-100 px-1 text-[9px] tabular-nums text-kiwi-600"
          >
            {{ sorts.length }}
          </span>
        </button>
      </template>
      <template #default>
        <div class="p-1">
          <div class="flex items-center justify-between px-1 pb-1.5">
            <span class="text-[11px] font-medium text-slate-500">排序规则</span>
            <button
              v-if="sorts.length"
              type="button"
              class="text-[10.5px] text-slate-400 hover:text-rose-500"
              @click="clearSorts"
            >
              清除全部
            </button>
          </div>

          <div
            v-for="row in sortRows"
            :key="row.sort.field"
            class="mb-1.5 flex items-center gap-1 rounded-lg border border-slate-100 bg-slate-50/60 p-1.5"
          >
            <select
              :value="row.sort.field"
              class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
              @change="changeSortField(row.sort, $event)"
            >
              <option
                v-for="field in fields"
                :key="field.id"
                :value="field.id"
                :disabled="
                  field.id !== row.sort.field && sorts.some((s) => s.field === field.id)
                "
              >
                {{ field.name }}
              </option>
            </select>
            <button
              type="button"
              class="flex h-7 shrink-0 items-center gap-0.5 rounded-md border border-slate-200 bg-white px-1.5 text-[10.5px] text-slate-500 hover:border-kiwi-300 hover:text-kiwi-600"
              :title="row.sort.direction === 'asc' ? '点击切换为降序' : '点击切换为升序'"
              @click="toggleDirection(row.sort)"
            >
              <KiwiIcon
                :name="row.sort.direction === 'asc' ? 'arrowUp' : 'arrowDown'"
                :size="10"
              />
              {{ row.sort.direction === 'asc' ? '升序' : '降序' }}
            </button>
            <button
              type="button"
              class="grid h-6 w-5 shrink-0 place-items-center rounded text-slate-300 hover:bg-white hover:text-kiwi-600 disabled:opacity-30"
              title="上移优先级"
              :disabled="row.index === 0"
              @click="moveSort(row.index, -1)"
            >
              <KiwiIcon name="arrowUp" :size="9" />
            </button>
            <button
              type="button"
              class="grid h-6 w-5 shrink-0 place-items-center rounded text-slate-300 hover:bg-white hover:text-kiwi-600 disabled:opacity-30"
              title="下移优先级"
              :disabled="row.index === sorts.length - 1"
              @click="moveSort(row.index, 1)"
            >
              <KiwiIcon name="arrowDown" :size="9" />
            </button>
            <button
              type="button"
              class="grid h-6 w-5 shrink-0 place-items-center rounded text-slate-300 hover:bg-rose-50 hover:text-rose-500"
              title="移除排序"
              @click="removeSort(row.sort.field)"
            >
              <KiwiIcon name="close" :size="9" />
            </button>
          </div>

          <div v-if="!sortRows.length" class="px-1 pb-2 text-[11px] text-slate-400">
            还没有排序规则
          </div>

          <button
            type="button"
            class="flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-slate-200 py-1.5 text-[11px] text-slate-400 transition-colors hover:border-kiwi-300 hover:text-kiwi-600 disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="!canAddSort"
            @click="addSort"
          >
            <KiwiIcon name="plus" :size="11" />
            添加排序字段
          </button>
          <p class="px-1 pt-1.5 text-[10px] text-slate-400">
            先按第一个字段排序，值相同时再比较后续字段（最多 5 个）
          </p>
        </div>
      </template>
    </KiwiDropdown>
  </div>
</template>
