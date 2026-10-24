<script setup lang="ts">
/**
 * 「贴一贴」结构化笔记预览：表格 / 数据表 / 画布 / Notebook。
 *
 * 浮窗里做只读展示：表格支持切换工作表并计算公式，数据表展示全部字段与
 * 记录，画布渲染为静态 SVG；编辑仍在主窗口完成。
 */
import { computed, ref, watch } from 'vue'
import type { NoteOut } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  normalizeWorkbook,
  parseAddress,
  type SheetData,
} from '@/components/notes/sheet/types'
import {
  evaluateWorkbook,
  formatSheetValue,
} from '@/components/notes/sheet/formula'
import { canvasDocToSvg } from '@/components/notes/canvas/canvasSvgExport'
import { normalizeDoc } from '@/components/notes/canvas/types'

type DbField = { id: string; name?: string; type?: string }
type DbRow = { id: string; data: Record<string, any> }

const props = defineProps<{
  note: NoteOut
  /** 数据表字段与记录由父组件按需加载。 */
  fields?: DbField[]
  rows?: DbRow[]
}>()

// 表格按工作表展示完整内容，仅对超大数据做 DOM 保护。
const MAX_SHEET_ROWS = 200
const MAX_SHEET_COLS = 20

const kind = computed(() => props.note.kind)

// ---------- 表格 ----------
const workbook = computed(() => normalizeWorkbook(props.note.props_json?.sheet))
const sheetResults = computed(() => evaluateWorkbook(workbook.value))
const activeSheetId = ref('')

watch(
  () => props.note.id,
  () => {
    activeSheetId.value = workbook.value.active
  },
  { immediate: true },
)
watch(workbook, (next) => {
  if (!next.sheets.some((sheet) => sheet.id === activeSheetId.value)) {
    activeSheetId.value = next.active
  }
})

const activeSheet = computed<SheetData>(
  () =>
    workbook.value.sheets.find((sheet) => sheet.id === activeSheetId.value) ??
    workbook.value.sheets[0],
)

function displayCell(sheetId: string, address: string): string {
  const sheet = workbook.value.sheets.find((item) => item.id === sheetId)
  const cell = sheet?.cells[address]
  const result = sheetResults.value.get(`${sheetId}!${address}`)
  if (result?.error) return result.error
  return formatSheetValue(result?.value ?? cell?.cached ?? cell?.v ?? null, cell?.s?.fmt)
}

const sheetView = computed(() => {
  if (kind.value !== 'sheet') return null
  const sheet = activeSheet.value
  if (!sheet) return null
  const sheets = workbook.value.sheets.map((item) => ({ id: item.id, name: item.name }))
  const addressList = Object.keys(sheet.cells)
  if (!addressList.length) {
    return {
      name: sheet.name,
      sheetCount: sheets.length,
      sheets,
      active: sheet.id,
      grid: [],
      truncated: false,
    }
  }
  let minRow = Number.POSITIVE_INFINITY
  let minCol = Number.POSITIVE_INFINITY
  let maxRow = 0
  let maxCol = 0
  const lookup = new Map<string, string>()
  for (const address of addressList) {
    const position = parseAddress(address)
    if (!position) continue
    const text = displayCell(sheet.id, address)
    if (!text) continue
    minRow = Math.min(minRow, position.row)
    minCol = Math.min(minCol, position.col)
    maxRow = Math.max(maxRow, position.row)
    maxCol = Math.max(maxCol, position.col)
    lookup.set(`${position.row}:${position.col}`, text)
  }
  if (!lookup.size) {
    return {
      name: sheet.name,
      sheetCount: sheets.length,
      sheets,
      active: sheet.id,
      grid: [],
      truncated: false,
    }
  }
  const firstRow = Math.max(0, minRow)
  const firstCol = Math.max(0, minCol)
  const rowCount = Math.min(maxRow - firstRow + 1, MAX_SHEET_ROWS)
  const colCount = Math.min(maxCol - firstCol + 1, MAX_SHEET_COLS)
  const grid: string[][] = []
  for (let row = firstRow; row < firstRow + rowCount; row += 1) {
    const line: string[] = []
    for (let col = firstCol; col < firstCol + colCount; col += 1) {
      line.push(lookup.get(`${row}:${col}`) || '')
    }
    grid.push(line)
  }
  return {
    name: sheet.name,
    sheetCount: sheets.length,
    sheets,
    active: sheet.id,
    grid,
    truncated:
      maxRow - firstRow + 1 > rowCount || maxCol - firstCol + 1 > colCount,
  }
})

function selectSheet(id: string) {
  if (workbook.value.sheets.some((sheet) => sheet.id === id)) {
    activeSheetId.value = id
  }
}

// ---------- 数据表 ----------
function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) {
    return value
      .map((item) =>
        item && typeof item === 'object'
          ? String((item as any).name ?? (item as any).label ?? (item as any).id ?? '')
          : String(item),
      )
      .filter(Boolean)
      .join('、')
  }
  if (typeof value === 'object') {
    const data = value as Record<string, unknown>
    return String(data.name ?? data.label ?? data.id ?? '')
  }
  return String(value)
}

const databaseView = computed(() => {
  if (kind.value !== 'database') return null
  // 数据表在便签里展示全部字段与记录，窗口内滚动查看。
  const fields = (props.fields || []).filter((field) => field && field.id)
  const rows = props.rows || []
  return {
    fields,
    rows,
    totalRows: rows.length,
    totalFields: fields.length,
  }
})

// ---------- 画布 ----------
const canvasDoc = computed(() =>
  kind.value === 'canvas' ? normalizeDoc(props.note.props_json?.canvas_doc) : null,
)

const canvasView = computed(() => {
  const doc = canvasDoc.value
  if (!doc) return null
  let svg = ''
  if (doc.nodes.length || doc.edges.length) {
    try {
      svg = canvasDocToSvg(doc)
    } catch {
      svg = ''
    }
  }
  return { totalNodes: doc.nodes.length, totalEdges: doc.edges.length, svg }
})

// ---------- Notebook ----------
function outputText(cell: any): string {
  const blocks: string[] = []
  for (const output of Array.isArray(cell?.outputs) ? cell.outputs : []) {
    const text = String(output?.text || '').trim()
    if (text) {
      blocks.push(text)
      continue
    }
    const html = String(output?.html || '').trim()
    if (html) {
      blocks.push(html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim())
    }
  }
  return blocks.join('\n').slice(0, 500)
}

const notebookView = computed(() => {
  if (kind.value !== 'notebook') return null
  const doc = (props.note.props_json?.notebook_doc || {}) as Record<string, any>
  const cells = Array.isArray(doc.cells) ? doc.cells : []
  return {
    totalCells: cells.length,
    language: String(doc.language || 'python'),
    cells: cells
      .filter((cell: any) => String(cell?.source || '').trim())
      .slice(0, 8)
      .map((cell: any, index: number) => ({
        index: index + 1,
        kind: cell?.type === 'markdown' ? 'markdown' : 'code',
        source: String(cell.source || '').slice(0, 800),
        output: outputText(cell),
      })),
  }
})
</script>

<template>
  <!-- 表格 -->
  <div v-if="kind === 'sheet'" class="space-y-2 px-3 py-2.5">
    <div class="flex items-center gap-1.5 text-[10px] text-slate-400">
      <KiwiIcon name="table" :size="12" />
      <span class="truncate">{{ sheetView?.name || '工作表' }}</span>
      <span class="ml-auto shrink-0">{{ sheetView?.sheetCount || 0 }} 个工作表</span>
    </div>
    <div v-if="(sheetView?.sheets.length || 0) > 1" class="flex flex-wrap gap-1">
      <button
        v-for="sheet in sheetView?.sheets"
        :key="sheet.id"
        type="button"
        class="max-w-[120px] truncate rounded-md px-1.5 py-0.5 text-[9.5px] transition-colors"
        :class="
          sheet.id === sheetView?.active
            ? 'bg-kiwi-50 font-medium text-kiwi-700'
            : 'bg-slate-50 text-slate-500 hover:bg-slate-100'
        "
        @click="selectSheet(sheet.id)"
      >
        {{ sheet.name }}
      </button>
    </div>
    <div
      v-if="sheetView?.grid.length"
      class="overflow-auto rounded-lg border border-slate-100"
    >
      <table class="min-w-full border-collapse text-[10.5px]">
        <tbody>
          <tr v-for="(row, rowIndex) in sheetView.grid" :key="rowIndex">
            <td
              v-for="(cell, colIndex) in row"
              :key="colIndex"
              class="max-w-[160px] truncate border-b border-r border-slate-100 px-1.5 py-1 last:border-r-0"
              :class="
                rowIndex === 0
                  ? 'bg-slate-50 font-medium text-slate-600'
                  : 'text-slate-600'
              "
              :title="cell"
            >
              {{ cell }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="rounded-lg bg-slate-50 px-3 py-4 text-center text-[11px] text-slate-400">
      工作表还是空的，打开主窗口开始填写。
    </p>
    <p v-if="sheetView?.truncated" class="text-[9.5px] text-slate-400">
      仅展示前 {{ MAX_SHEET_ROWS }} 行 × {{ MAX_SHEET_COLS }} 列。
    </p>
  </div>

  <!-- 数据表 -->
  <div v-else-if="kind === 'database'" class="space-y-2 px-3 py-2.5">
    <div class="flex items-center gap-1.5 text-[10px] text-slate-400">
      <KiwiIcon name="database" :size="12" />
      <span>{{ databaseView?.totalFields || 0 }} 个字段</span>
      <span class="ml-auto">{{ databaseView?.totalRows || 0 }} 条记录</span>
    </div>
    <div
      v-if="databaseView?.rows.length && databaseView.fields.length"
      class="overflow-auto rounded-lg border border-slate-100"
    >
      <table class="min-w-full border-collapse text-[10.5px]">
        <thead>
          <tr class="bg-slate-50 text-slate-500">
            <th
              v-for="field in databaseView.fields"
              :key="field.id"
              class="max-w-[140px] truncate border-b border-r border-slate-100 px-1.5 py-1 text-left font-medium last:border-r-0"
            >
              {{ field.name || field.id }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in databaseView.rows" :key="row.id">
            <td
              v-for="field in databaseView.fields"
              :key="field.id"
              class="max-w-[140px] truncate border-b border-r border-slate-100 px-1.5 py-1 text-slate-600 last:border-r-0"
              :title="displayValue(row.data?.[field.id])"
            >
              {{ displayValue(row.data?.[field.id]) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="rounded-lg bg-slate-50 px-3 py-4 text-center text-[11px] text-slate-400">
      数据表还没有记录，打开主窗口添加。
    </p>
  </div>

  <!-- 画布 -->
  <div v-else-if="kind === 'canvas'" class="space-y-2 px-3 py-2.5">
    <div class="flex items-center gap-1.5 text-[10px] text-slate-400">
      <KiwiIcon name="pen" :size="12" />
      <span>{{ canvasView?.totalNodes || 0 }} 个节点</span>
      <span class="ml-auto">{{ canvasView?.totalEdges || 0 }} 条连线</span>
    </div>
    <div
      v-if="canvasView?.svg"
      class="sticky-canvas overflow-auto rounded-lg border border-slate-100 bg-white p-1"
    >
      <!-- canvasDocToSvg 已转义节点与连线文本，仅输出 SVG 结构。 -->
      <div class="min-w-[420px]" v-html="canvasView.svg" />
    </div>
    <p v-else class="rounded-lg bg-slate-50 px-3 py-4 text-center text-[11px] text-slate-400">
      画布还是空的，打开主窗口开始绘制。
    </p>
  </div>

  <!-- Notebook -->
  <div v-else-if="kind === 'notebook'" class="space-y-2 px-3 py-2.5">
    <div class="flex items-center gap-1.5 text-[10px] text-slate-400">
      <KiwiIcon name="notebook" :size="12" />
      <span>{{ notebookView?.totalCells || 0 }} 个单元</span>
      <span class="ml-auto font-mono">{{ notebookView?.language }}</span>
    </div>
    <div v-if="notebookView?.cells.length" class="space-y-1.5">
      <div
        v-for="cell in notebookView.cells"
        :key="cell.index"
        class="overflow-hidden rounded-lg border border-slate-100"
      >
        <p
          v-if="cell.kind === 'markdown'"
          class="whitespace-pre-wrap px-2 py-1.5 text-[11px] leading-relaxed text-slate-600"
        >
          {{ cell.source }}
        </p>
        <pre
          v-else
          class="overflow-x-auto bg-slate-900/95 px-2 py-1.5 text-[10px] leading-relaxed text-slate-100"
        ><code>{{ cell.source }}</code></pre>
        <pre
          v-if="cell.output"
          class="max-h-24 overflow-auto border-t border-slate-100 bg-slate-50/80 px-2 py-1.5 text-[9.5px] leading-relaxed text-slate-500"
        >{{ cell.output }}</pre>
      </div>
    </div>
    <p v-else class="rounded-lg bg-slate-50 px-3 py-4 text-center text-[11px] text-slate-400">
      Notebook 还没有代码单元，打开主窗口开始编写。
    </p>
  </div>
</template>

<style scoped>
.sticky-canvas :deep(svg) {
  display: block;
  width: 100%;
  height: auto;
}
</style>
