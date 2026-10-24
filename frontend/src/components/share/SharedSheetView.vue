<script setup lang="ts">
/** 公开分享页的表格笔记只读视图：工作表页签 + 单元格网格。 */
import { computed, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  cellAddress,
  columnLabel,
  mergeLayout,
  normalizeWorkbook,
  parseAddress,
  type MergeSpan,
  type SheetCell,
} from '@/components/notes/sheet/types'

interface SheetPayload {
  workbook?: unknown
}

const props = defineProps<{ payload?: SheetPayload | null }>()

const MAX_RENDER_ROWS = 120
const MAX_RENDER_COLS = 30

const workbook = computed(() => normalizeWorkbook(props.payload?.workbook))
const activeId = ref('')

watch(
  workbook,
  (value) => {
    if (value.sheets.some((item) => item.id === activeId.value)) return
    activeId.value =
      value.sheets.find((item) => item.id === value.active)?.id || value.sheets[0]?.id || ''
  },
  { immediate: true },
)

const sheet = computed(
  () =>
    workbook.value.sheets.find((item) => item.id === activeId.value) ||
    workbook.value.sheets[0],
)

const bounds = computed(() => {
  const current = sheet.value
  if (!current) return null
  let minRow = Number.POSITIVE_INFINITY
  let minCol = Number.POSITIVE_INFINITY
  let maxRow = -1
  let maxCol = -1
  for (const address of Object.keys(current.cells)) {
    const position = parseAddress(address)
    if (!position) continue
    minRow = Math.min(minRow, position.row)
    minCol = Math.min(minCol, position.col)
    maxRow = Math.max(maxRow, position.row)
    maxCol = Math.max(maxCol, position.col)
  }
  if (maxRow < 0) return null
  const startRow = Math.max(0, minRow)
  const startCol = Math.max(0, minCol)
  const endRow = Math.min(maxRow, startRow + MAX_RENDER_ROWS - 1)
  const endCol = Math.min(maxCol, startCol + MAX_RENDER_COLS - 1)
  return {
    startRow,
    startCol,
    endRow,
    endCol,
    totalRows: maxRow - startRow + 1,
    totalCols: maxCol - startCol + 1,
    truncated: endRow < maxRow || endCol < maxCol,
  }
})

const rowIndexes = computed(() => {
  const value = bounds.value
  if (!value) return []
  return Array.from({ length: value.endRow - value.startRow + 1 }, (_, index) => value.startRow + index)
})

const colIndexes = computed(() => {
  const value = bounds.value
  if (!value) return []
  return Array.from({ length: value.endCol - value.startCol + 1 }, (_, index) => value.startCol + index)
})

const merges = computed<{ anchors: Map<string, MergeSpan>; covered: Set<string> }>(() =>
  sheet.value
    ? mergeLayout(sheet.value)
    : { anchors: new Map<string, MergeSpan>(), covered: new Set<string>() },
)

function cellAt(row: number, col: number): SheetCell | undefined {
  return sheet.value?.cells[cellAddress(row, col)]
}

function isCovered(row: number, col: number): boolean {
  return merges.value.covered.has(cellAddress(row, col))
}

function spansAt(row: number, col: number): { rowSpan: number; colSpan: number } {
  const span = merges.value.anchors.get(cellAddress(row, col))
  const value = bounds.value
  if (!span || !value) return { rowSpan: 1, colSpan: 1 }
  return {
    rowSpan: Math.min(span.rowSpan, value.endRow - row + 1),
    colSpan: Math.min(span.colSpan, value.endCol - col + 1),
  }
}

function cellText(cell?: SheetCell): string {
  if (!cell) return ''
  const value = cell.v ?? cell.cached
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE'
  return String(value)
}

function safeColor(value?: string): string | undefined {
  return value && /^#[0-9a-f]{6}$/i.test(value) ? value : undefined
}

function cellStyle(cell?: SheetCell): Record<string, string | undefined> {
  const style = cell?.s || {}
  return {
    fontWeight: style.bold ? '600' : '400',
    fontStyle: style.italic ? 'italic' : undefined,
    textDecoration: style.underline ? 'underline' : undefined,
    color: safeColor(style.color) || '#334155',
    backgroundColor: safeColor(style.bg) || undefined,
    textAlign: style.align || 'left',
  }
}
</script>

<template>
  <div v-if="sheet && bounds">
    <div class="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
      <span class="inline-flex items-center gap-1">
        <KiwiIcon name="table" :size="11" />
        {{ sheet.name }}
      </span>
      <span>{{ bounds.totalRows }} 行 × {{ bounds.totalCols }} 列</span>
      <span v-if="bounds.truncated">
        仅展示左上 {{ rowIndexes.length }} × {{ colIndexes.length }} 区域
      </span>
    </div>

    <div
      v-if="workbook.sheets.length > 1"
      class="mb-2 flex flex-wrap items-center gap-1.5"
    >
      <button
        v-for="item in workbook.sheets"
        :key="item.id"
        type="button"
        class="rounded-lg border px-2.5 py-1 text-[11px] transition-colors"
        :class="
          item.id === sheet.id
            ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
            : 'border-slate-200 bg-white/70 text-slate-500 hover:border-kiwi-200'
        "
        @click="activeId = item.id"
      >
        {{ item.name }}
      </button>
    </div>

    <div class="overflow-hidden rounded-2xl border border-slate-200/70 bg-white shadow-soft">
      <div class="max-h-[68vh] overflow-auto">
        <table class="w-full border-collapse text-left text-[12px]">
          <thead>
            <tr>
              <th
                class="sticky left-0 top-0 z-30 h-7 min-w-10 border-b border-r border-slate-200 bg-slate-100 px-2 text-[10px] font-medium text-slate-400"
              />
              <th
                v-for="col in colIndexes"
                :key="col"
                class="sticky top-0 z-20 h-7 min-w-[96px] border-b border-r border-slate-200 bg-slate-100 px-2 text-[10px] font-medium text-slate-400 last:border-r-0"
              >
                {{ columnLabel(col) }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rowIndexes" :key="row">
              <th
                class="sticky left-0 z-10 h-7 min-w-10 border-b border-r border-slate-200 bg-slate-50 px-2 text-[10px] font-normal text-slate-400"
              >
                {{ row + 1 }}
              </th>
              <template v-for="col in colIndexes" :key="col">
                <td
                  v-if="!isCovered(row, col)"
                  :rowspan="spansAt(row, col).rowSpan"
                  :colspan="spansAt(row, col).colSpan"
                  class="h-7 max-w-[320px] min-w-[96px] whitespace-pre-wrap break-words border-b border-r border-slate-200 px-2 py-0.5 align-top last:border-r-0"
                  :style="cellStyle(cellAt(row, col))"
                >
                  {{ cellText(cellAt(row, col)) }}
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div v-else class="rounded-2xl border border-slate-200/70 bg-white/70 px-4 py-16 text-center">
    <p class="text-[12px] text-slate-400">这张表格还没有内容。</p>
  </div>
</template>
