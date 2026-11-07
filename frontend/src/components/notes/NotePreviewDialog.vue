<script setup lang="ts">
/**
 * @ 提及的笔记大屏预览：与附件预览一致的遮罩窗口。
 *
 * 按笔记类型渲染只读内容：
 * - 文档 / 导入 / Wiki：Markdown 正文
 * - 数据表：完整字段与记录（横向滚动）
 * - Notebook：Markdown + 代码单元格
 * - 表格：活动工作表的只读网格
 * - 链接：书签信息 + 正文
 * - 画布：入口提示（画布交互交给正式笔记页）
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import { useKbsStore } from '@/stores/kbs'
import { usePaneOpen } from '@/components/notes/workspace/usePaneOpen'
import {
  columnLabel,
  normalizeWorkbook,
  parseAddress,
  type SheetData,
  type SheetWorkbook,
} from '@/components/notes/sheet/types'
import { evaluateWorkbook, formatSheetValue } from '@/components/notes/sheet/formula'
import {
  attachmentsOf,
  databaseCellText,
  fetchNotePreview,
  type NotePreviewData,
  type NotePreviewField,
  type NotePreviewKind,
  type NotePreviewRow,
} from './notePreviewData'

const props = withDefaults(
  defineProps<{
    open: boolean
    noteId: string
    target?: 'note' | 'wiki'
    label?: string
    /** 提及节点已经加载好的数据，避免打开预览时重复请求。 */
    preload?: NotePreviewData | null
  }>(),
  { target: 'note', label: '', preload: null },
)
const emit = defineEmits<{ (e: 'close'): void }>()

const router = useRouter()
const kbs = useKbsStore()
const paneOpen = usePaneOpen()

const KIND_META: Record<NotePreviewKind, { icon: string; label: string }> = {
  doc: { icon: 'fileText', label: '文档' },
  database: { icon: 'database', label: '数据表' },
  link: { icon: 'link2', label: '链接' },
  import: { icon: 'fileImport', label: '导入' },
  canvas: { icon: 'pen', label: '画布' },
  notebook: { icon: 'notebook', label: 'Notebook' },
  sheet: { icon: 'table', label: '表格' },
  wiki: { icon: 'wiki', label: 'Wiki 页面' },
}

const data = ref<NotePreviewData | null>(null)
const loading = ref(false)
const failed = ref(false)
let requestSeq = 0

const kind = computed<NotePreviewKind>(() =>
  props.target === 'wiki' ? 'wiki' : data.value?.kind || 'doc',
)
const kindMeta = computed(() => KIND_META[kind.value] || KIND_META.doc)
const title = computed(() => data.value?.title || props.label || props.noteId)

async function load() {
  if (!props.open || !props.noteId) return
  const kbId = kbs.currentKbId
  if (!kbId) {
    failed.value = true
    return
  }
  const seq = ++requestSeq
  loading.value = true
  failed.value = false
  try {
    const next = await fetchNotePreview(kbId, props.noteId, props.target)
    if (seq === requestSeq) data.value = next
  } catch {
    if (seq === requestSeq) failed.value = true
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

watch(
  () => [props.open, props.noteId, props.target] as const,
  ([open]) => {
    if (!open) {
      requestSeq += 1
      loading.value = false
      return
    }
    data.value = props.preload ?? null
    if (!data.value) void load()
  },
  { immediate: true },
)

function close() {
  emit('close')
}

function openNote() {
  if (!props.noteId) return
  close()
  void router.push(
    props.target === 'wiki' ? `/wiki/${props.noteId}` : `/notes/${props.noteId}`,
  )
}

function openInPane() {
  if (props.target !== 'note') return
  if (paneOpen.openNotePane(props.noteId, kbs.currentKbId || undefined)) close()
}

function onKey(event: KeyboardEvent) {
  if (props.open && event.key === 'Escape') close()
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// ---------- 数据表 ----------
const dbFields = computed<NotePreviewField[]>(() => data.value?.fields ?? [])
const dbRows = computed<NotePreviewRow[]>(() => data.value?.rows ?? [])

// ---------- Notebook ----------
const notebookCells = computed(() => data.value?.notebook?.cells ?? [])

// ---------- 表格 ----------
const SHEET_MAX_ROWS = 40
const SHEET_MAX_COLS = 12

const workbook = computed<SheetWorkbook | null>(() => {
  const raw = data.value?.sheet
  if (!raw || !Array.isArray(raw.sheets) || !raw.sheets.length) return null
  try {
    return normalizeWorkbook(raw)
  } catch {
    return null
  }
})
const formulaResults = computed(() =>
  workbook.value ? evaluateWorkbook(workbook.value) : new Map(),
)
const activeSheet = computed<SheetData | null>(() => {
  const book = workbook.value
  if (!book) return null
  return book.sheets.find((item) => item.id === book.active) ?? book.sheets[0] ?? null
})

interface SheetCellView {
  text: string
  align: string
  bold: boolean
  color: string
  background: string
}

interface SheetRowView {
  index: number
  cells: SheetCellView[]
}

const sheetGrid = computed<{
  name: string
  columns: string[]
  rows: SheetRowView[]
  truncated: boolean
} | null>(() => {
  const sheet = activeSheet.value
  if (!sheet) return null
  let maxRow = -1
  let maxCol = -1
  for (const [address, cell] of Object.entries(sheet.cells)) {
    const hasValue =
      (cell.v !== undefined && cell.v !== null && String(cell.v).trim() !== '') ||
      Boolean(cell.f) ||
      (cell.cached !== undefined && cell.cached !== null && String(cell.cached) !== '')
    if (!hasValue) continue
    const pos = parseAddress(address)
    if (!pos) continue
    maxRow = Math.max(maxRow, pos.row)
    maxCol = Math.max(maxCol, pos.col)
  }
  if (maxRow < 0 || maxCol < 0) {
    return { name: sheet.name, columns: [], rows: [], truncated: false }
  }
  const rowCount = Math.min(maxRow + 1, SHEET_MAX_ROWS)
  const colCount = Math.min(maxCol + 1, SHEET_MAX_COLS)
  const columns = Array.from({ length: colCount }, (_, index) => columnLabel(index))
  const rows: SheetRowView[] = []
  for (let row = 0; row < rowCount; row += 1) {
    const cells: SheetCellView[] = []
    for (let col = 0; col < colCount; col += 1) {
      const address = `${columnLabel(col)}${row + 1}`
      const cell = sheet.cells[address]
      const result = formulaResults.value.get(`${sheet.id}!${address}`)
      const value = result ? result.value : cell?.v ?? cell?.cached ?? null
      const text = result?.error
        ? result.error
        : formatSheetValue(value as string | number | boolean | null, cell?.s?.fmt)
      cells.push({
        text,
        align:
          cell?.s?.align === 'center'
            ? 'center'
            : cell?.s?.align === 'right'
              ? 'right'
              : 'left',
        bold: Boolean(cell?.s?.bold),
        color: cell?.s?.color || '',
        background: cell?.s?.bg || '',
      })
    }
    rows.push({ index: row + 1, cells })
  }
  return {
    name: sheet.name,
    columns,
    rows,
    truncated: maxRow + 1 > SHEET_MAX_ROWS || maxCol + 1 > SHEET_MAX_COLS,
  }
})

// ---------- 链接 ----------
const linkMeta = computed(() => data.value?.link)
</script>

<template>
  <Teleport to="html">
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-active-class="transition-opacity duration-150"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open && noteId"
        class="note-preview-overlay fixed inset-0 z-[300] flex flex-col bg-slate-950/85 backdrop-blur-sm"
        @click.self="close"
      >
        <header class="shrink-0 flex items-center gap-3 px-5 py-3 text-white/90">
          <span class="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/10 text-white/70">
            <KiwiIcon :name="kindMeta.icon" :size="15" />
          </span>
          <span class="min-w-0 truncate text-[13px] font-medium">{{ title }}</span>
          <span class="shrink-0 rounded-full border border-white/15 px-2 py-0.5 text-[10.5px] text-white/55">
            {{ kindMeta.label }}
          </span>
          <div class="flex-1" />
          <button
            v-if="target === 'note'"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/10 px-2.5 py-1.5 text-[11.5px] text-white/80 transition-colors hover:bg-white/20 hover:text-white"
            title="在分栏中打开"
            @click.stop="openInPane"
          >
            <KiwiIcon name="columns" :size="12" />
            在分栏中打开
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/10 px-2.5 py-1.5 text-[11.5px] text-white/80 transition-colors hover:bg-white/20 hover:text-white"
            :title="target === 'wiki' ? '打开页面' : '打开笔记'"
            @click.stop="openNote"
          >
            <KiwiIcon name="external" :size="12" />
            {{ target === 'wiki' ? '打开页面' : '打开笔记' }}
          </button>
          <button
            type="button"
            class="grid h-8 w-8 place-items-center rounded-lg text-white/60 transition-colors hover:bg-white/15 hover:text-white"
            title="关闭（Esc）"
            @click.stop="close"
          >
            <KiwiIcon name="close" :size="16" />
          </button>
        </header>

        <div class="flex-1 min-h-0 mx-4 mb-4 overflow-hidden rounded-2xl bg-white shadow-2xl">
          <div class="h-full overflow-auto">
            <div v-if="loading && !data" class="grid h-full place-items-center gap-2 text-[12.5px] text-slate-400">
              <span class="flex items-center gap-2">
                <KiwiIcon name="loader" :size="15" class="animate-spin" />
                正在读取内容…
              </span>
            </div>
            <div v-else-if="failed && !data" class="grid h-full place-items-center text-[12.5px] text-slate-400">
              无法读取{{ target === 'wiki' ? '该 Wiki 页面' : '该笔记' }}，可能已被删除或没有访问权限。
            </div>

            <!-- 数据表：完整字段与记录 -->
            <div v-else-if="kind === 'database'" class="flex h-full flex-col">
              <div class="flex shrink-0 items-center gap-2 border-b border-slate-100 px-5 py-2.5 text-[11px] text-slate-400">
                <KiwiIcon name="database" :size="13" class="text-kiwi-500" />
                共 {{ dbRows.length }} 条记录 · {{ dbFields.length }} 个字段
                <span v-if="!dbRows.length" class="text-slate-400">（这张数据表还没有记录）</span>
              </div>
              <div v-if="dbFields.length" class="min-h-0 flex-1 overflow-auto">
                <table class="w-full border-collapse text-[12px]">
                  <thead class="sticky top-0 z-[1] bg-slate-50/95 backdrop-blur">
                    <tr>
                      <th
                        v-for="field in dbFields"
                        :key="field.id"
                        class="whitespace-nowrap border-b border-r border-slate-200 px-3 py-2 text-left text-[11.5px] font-semibold text-slate-600 last:border-r-0"
                      >
                        {{ field.name }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in dbRows" :key="row.id" class="transition-colors hover:bg-kiwi-50/40">
                      <td
                        v-for="field in dbFields"
                        :key="field.id"
                        class="max-w-[320px] truncate whitespace-nowrap border-b border-r border-slate-100 px-3 py-2 text-slate-600 last:border-r-0"
                      >
                        <template v-if="field.type === 'attachment'">
                          <span v-if="attachmentsOf(row, field).length" class="inline-flex items-center gap-1 text-slate-500">
                            <KiwiIcon name="paperclip" :size="11" />
                            {{ attachmentsOf(row, field).length }} 个附件
                          </span>
                          <template v-else>—</template>
                        </template>
                        <template v-else>{{ databaseCellText(row, field) }}</template>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else-if="!loading" class="grid flex-1 place-items-center text-[12.5px] text-slate-400">
                这张数据表还没有字段。
              </div>
            </div>

            <!-- Notebook：Markdown + 代码单元格 -->
            <div v-else-if="kind === 'notebook'" class="mx-auto w-full max-w-4xl space-y-3 px-8 py-6">
              <p class="text-[11px] text-slate-400">
                只读预览 · {{ notebookCells.length }} 个单元格
              </p>
              <template v-if="notebookCells.length">
                <div v-for="(cell, index) in notebookCells" :key="index" class="min-w-0">
                  <div v-if="cell.type === 'code'" class="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
                    <div class="border-b border-slate-200/70 bg-white/70 px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
                      代码单元格 · {{ index + 1 }}
                    </div>
                    <pre class="max-h-80 overflow-auto whitespace-pre-wrap break-words px-3 py-2.5 font-mono text-[11.5px] leading-relaxed text-slate-700">{{ cell.source || '' }}</pre>
                  </div>
                  <MarkdownView v-else-if="cell.source?.trim()" :content="cell.source" />
                </div>
              </template>
              <div v-else class="py-16 text-center text-[12.5px] text-slate-400">
                这个 Notebook 还没有单元格。
              </div>
            </div>

            <!-- 表格：活动工作表的只读网格 -->
            <div v-else-if="kind === 'sheet'" class="flex h-full flex-col">
              <div class="flex shrink-0 items-center gap-2 border-b border-slate-100 px-5 py-2.5 text-[11px] text-slate-400">
                <KiwiIcon name="table" :size="13" class="text-kiwi-500" />
                {{ sheetGrid?.name || '工作表' }}
                <span v-if="sheetGrid?.truncated">· 仅预览前 {{ SHEET_MAX_ROWS }} 行 × {{ SHEET_MAX_COLS }} 列</span>
              </div>
              <div v-if="sheetGrid && sheetGrid.rows.length" class="min-h-0 flex-1 overflow-auto">
                <table class="border-collapse text-[12px]">
                  <thead class="sticky top-0 z-[1] bg-slate-50/95 backdrop-blur">
                    <tr>
                      <th class="sticky left-0 z-[2] w-11 border-b border-r border-slate-200 bg-slate-50 px-2 py-1.5 text-center text-[10px] font-medium text-slate-400" />
                      <th
                        v-for="column in sheetGrid.columns"
                        :key="column"
                        class="min-w-[96px] border-b border-r border-slate-200 px-2.5 py-1.5 text-left text-[10.5px] font-medium text-slate-400"
                      >
                        {{ column }}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in sheetGrid.rows" :key="row.index" class="hover:bg-kiwi-50/30">
                      <td class="sticky left-0 z-[1] border-b border-r border-slate-200 bg-slate-50 px-2 py-1.5 text-center text-[10px] tabular-nums text-slate-400">
                        {{ row.index }}
                      </td>
                      <td
                        v-for="(cell, index) in row.cells"
                        :key="index"
                        class="max-w-[280px] truncate whitespace-nowrap border-b border-r border-slate-100 px-2.5 py-1.5 text-slate-600"
                        :style="{
                          textAlign: cell.align as 'left' | 'center' | 'right',
                          fontWeight: cell.bold ? 600 : 400,
                          color: cell.color || undefined,
                          background: cell.background || undefined,
                        }"
                      >
                        {{ cell.text }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else-if="!loading" class="grid flex-1 place-items-center text-[12.5px] text-slate-400">
                这个工作表还没有内容。
              </div>
            </div>

            <!-- 链接：书签 + 正文 -->
            <div v-else-if="kind === 'link'" class="mx-auto w-full max-w-4xl px-8 py-6">
              <div class="mb-4 rounded-xl border border-slate-200 bg-gradient-to-br from-kiwi-50/60 via-white to-white px-4 py-3">
                <div class="flex items-center gap-2 text-[12px] font-semibold text-slate-700">
                  <KiwiIcon name="globe" :size="14" class="text-sky-500" />
                  {{ linkMeta?.site || '外部链接' }}
                </div>
                <a
                  v-if="linkMeta?.final_url || linkMeta?.url"
                  :href="linkMeta?.final_url || linkMeta?.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="mt-1 block break-all text-[11.5px] text-kiwi-600 hover:underline"
                >
                  {{ linkMeta?.final_url || linkMeta?.url }}
                </a>
                <p v-if="linkMeta?.excerpt" class="mt-1.5 line-clamp-3 text-[11.5px] leading-relaxed text-slate-500">
                  {{ linkMeta.excerpt }}
                </p>
              </div>
              <MarkdownView v-if="data?.body_md?.trim()" :content="data.body_md" />
              <p v-else class="text-[12.5px] text-slate-400">这篇链接笔记还没有正文。</p>
            </div>

            <!-- 画布：入口提示 -->
            <div v-else-if="kind === 'canvas'" class="grid h-full place-items-center">
              <div class="flex max-w-md flex-col items-center gap-3 px-6 text-center">
                <span class="grid h-12 w-12 place-items-center rounded-2xl border border-kiwi-100 bg-kiwi-50 text-kiwi-500">
                  <KiwiIcon name="pen" :size="22" />
                </span>
                <p class="text-[13px] font-semibold text-slate-700">画布内容需要在笔记中查看与编辑</p>
                <p class="text-[11.5px] leading-relaxed text-slate-400">
                  可以点击右上角「打开笔记」，或在分栏中与其他笔记并排查看。
                </p>
              </div>
            </div>

            <!-- 文档 / 导入 / Wiki -->
            <div v-else class="mx-auto w-full max-w-4xl px-8 py-6">
              <MarkdownView v-if="data?.body_md?.trim()" :content="data.body_md" />
              <p v-else class="py-16 text-center text-[12.5px] text-slate-400">
                {{ target === 'wiki' ? '该页面还没有正文。' : '这篇笔记还没有正文。' }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
