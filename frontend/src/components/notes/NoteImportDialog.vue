<script setup lang="ts">
/** 导入中心：文件批次、分片续传、语雀双路径、解析质量报告。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { request } from '@/api/client'
import { CHUNKED_THRESHOLD, uploadFileInChunks } from '@/lib/chunkedUpload'
import { useKbsStore } from '@/stores/kbs'
import {
  useNotesStore,
  type ImportBatch,
  type NoteOut,
  type TablePreview,
} from '@/stores/notes'
import { toast } from '@/components/ui/toast'

const props = withDefaults(
  defineProps<{
    open: boolean
    folderId?: string | null
    /** 非空时导入结果成为该笔记的子笔记（语雀批量迁移仍按分组导入） */
    parentNoteId?: string | null
  }>(),
  { folderId: null, parentNoteId: null },
)

const emit = defineEmits<{ (e: 'close'): void; (e: 'created', note: NoteOut): void }>()

const ACCEPT = [
  '.md', '.markdown', '.txt', '.text', '.pdf', '.docx', '.doc', '.ipynb',
  '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff',
]
const TABLE_ACCEPT = ['.csv', '.xlsx', '.xls']
const MAX_BYTES = 200 * 1024 * 1024
const MAX_TABLE_BYTES = 20 * 1024 * 1024
const MAX_FILES = 50

type Tab = 'files' | 'sheet' | 'url' | 'yuque' | 'history'
type RowStatus = 'pending' | 'uploading' | 'submitted' | 'failed'

const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'files', label: '文件上传' },
  { key: 'sheet', label: '表格导入' },
  { key: 'url', label: '线上文件' },
  { key: 'yuque', label: '语雀迁移' },
  { key: 'history', label: '导入记录' },
]

interface FileRow {
  file: File
  status: RowStatus
  percent: number
  message: string
  noteId?: string
  note?: NoteOut
}

const kbs = useKbsStore()
const notes = useNotesStore()

const tab = ref<Tab>('files')
const rows = ref<FileRow[]>([])
const dragOver = ref(false)
const input = ref<HTMLInputElement | null>(null)
const compileNow = ref(false)
const readonlyImport = ref(false)
const tableInput = ref<HTMLInputElement | null>(null)
const tableFile = ref<File | null>(null)
const tableDrag = ref(false)
const tableHasHeader = ref(true)
const tableSheet = ref('')
const tablePreview = ref<TablePreview | null>(null)
const tablePreviewLoading = ref(false)
const tableImporting = ref(false)
const tableTitle = ref('')
let tablePreviewSeq = 0
const urlText = ref('')
const urlTitle = ref('')
const submitting = ref(false)
const error = ref('')
const batch = ref<ImportBatch | null>(null)
const history = ref<ImportBatch[]>([])
const historyLoading = ref(false)
const firstNote = ref<NoteOut | null>(null)
const reportOpen = ref(true)
let pollTimer: number | null = null

// 默认推荐「导出包」：无需申请令牌，也不受语雀接口限流影响。
const yuqueMode = ref<'token' | 'zip'>('zip')
const token = ref('')
const repo = ref('')
const zipFile = ref<File | null>(null)
const zipInput = ref<HTMLInputElement | null>(null)
const yuqueCompile = ref(false)
const createNotes = ref(true)
const yuqueSubmitting = ref(false)

interface YuqueRepo {
  id: number | string
  name: string
  namespace: string
  description: string
  items_count: number
  updated_at: string | null
  group: string | null
}
const repos = ref<YuqueRepo[]>([])
const reposLoading = ref(false)

async function fetchYuqueRepos() {
  if (!token.value.trim()) {
    error.value = '请先填写语雀访问令牌'
    return
  }
  if (reposLoading.value) return
  reposLoading.value = true
  error.value = ''
  try {
    repos.value = await request<YuqueRepo[]>('/ingest/yuque/repos', {
      method: 'POST',
      body: JSON.stringify({ token: token.value.trim() }),
    })
    if (!repos.value.length) {
      error.value = '该令牌下没有可访问的知识库'
    } else if (!repo.value.trim()) {
      repo.value = repos.value[0].namespace
    }
  } catch (e: any) {
    repos.value = []
    error.value = e?.message || '拉取语雀知识库列表失败'
  } finally {
    reposLoading.value = false
  }
}

const pendingRows = computed(() => rows.value.filter((r) => r.status !== 'submitted'))
const urlList = computed(() =>
  Array.from(
    new Set(
      urlText.value
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean),
    ),
  ),
)
const busy = computed(
  () => submitting.value || yuqueSubmitting.value || tableImporting.value,
)
const batchRunning = computed(() => batch.value?.status === 'running')
const report = computed(() => batch.value?.report_json || {})
const reportItems = computed(() => report.value.items || [])
const progressPercent = computed(() => {
  if (!batch.value) return 0
  if (batch.value.status !== 'running') return 100
  const total = Math.max(batch.value.total_sources, 1)
  return Math.min(99, Math.round((batch.value.processed_count / total) * 100))
})

function reset() {
  rows.value = []
  dragOver.value = false
  compileNow.value = false
  readonlyImport.value = false
  tableInput.value = null
  tableFile.value = null
  tableDrag.value = false
  tableHasHeader.value = true
  tableSheet.value = ''
  tablePreview.value = null
  tablePreviewLoading.value = false
  tableImporting.value = false
  tableTitle.value = ''
  urlText.value = ''
  urlTitle.value = ''
  submitting.value = false
  error.value = ''
  batch.value = null
  firstNote.value = null
  reportOpen.value = true
  tab.value = 'files'
  tokReset()
  stopPoll()
}

function tokReset() {
  token.value = ''
  repo.value = ''
  repos.value = []
  reposLoading.value = false
  zipFile.value = null
  yuqueMode.value = 'zip'
  yuqueCompile.value = false
  createNotes.value = true
  yuqueSubmitting.value = false
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      reset()
      void loadHistory()
    } else {
      stopPoll()
    }
  },
)

function stopPoll() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function switchTab(key: Tab) {
  tab.value = key
  if (key === 'history') void loadHistory()
}

onBeforeUnmount(stopPoll)

function extOf(name: string) {
  return `.${name.split('.').pop()?.toLowerCase() ?? ''}`
}

/** `.ipynb` 走 Notebook 导入端点，而不是文档解析流水线。 */
function isNotebookFile(name: string) {
  return extOf(name) === '.ipynb'
}

function sizeText(bytes: number) {
  const kb = bytes / 1024
  if (kb > 1024) return `${(kb / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(kb))} KB`
}

function addFiles(list: FileList | File[] | null) {
  if (!list) return
  const incoming = Array.from(list)
  for (const file of incoming) {
    if (rows.value.length >= MAX_FILES) {
      error.value = `单批最多 ${MAX_FILES} 个文件`
      break
    }
    if (!ACCEPT.includes(extOf(file.name))) {
      error.value = `不支持的文件类型：${file.name}`
      continue
    }
    if (file.size > MAX_BYTES) {
      error.value = `${file.name} 超过 200MB`
      continue
    }
    if (isNotebookFile(file.name) && file.size > MAX_TABLE_BYTES) {
      error.value = `${file.name} 超过 20MB`
      continue
    }
    if (rows.value.some((r) => r.file.name === file.name && r.file.size === file.size)) {
      continue
    }
    rows.value.push({ file, status: 'pending', percent: 0, message: '' })
  }
}

function pick(list: FileList | null) {
  addFiles(list)
  if (input.value) input.value.value = ''
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  addFiles(e.dataTransfer?.files ?? null)
}

function removeRow(index: number) {
  if (busy.value) return
  rows.value.splice(index, 1)
}

function close() {
  if (busy.value) return
  stopPoll()
  void notes.fetchTree()
  emit('close')
}

async function loadHistory() {
  historyLoading.value = true
  try {
    history.value = await notes.fetchImportBatches(30)
  } catch (e: any) {
    // 历史加载失败不阻塞导入
    console.warn('load import batches failed', e)
  } finally {
    historyLoading.value = false
  }
}

function watchBatch(batchId: string) {
  stopPoll()
  const tick = async () => {
    try {
      const fresh = await notes.fetchImportBatch(batchId)
      batch.value = fresh
      if (fresh.status === 'running') {
        pollTimer = window.setTimeout(tick, 2000)
      } else {
        pollTimer = null
        await notes.fetchTree()
        void loadHistory()
        if (firstNote.value) {
          emit('created', firstNote.value)
          firstNote.value = null
        }
      }
    } catch (e: any) {
      pollTimer = window.setTimeout(tick, 4000)
      error.value = e?.message || '读取批次状态失败'
    }
  }
  void tick()
}

async function submitFiles() {
  if (!rows.value.length) {
    error.value = '请选择要导入的文件'
    return
  }
  if (submitting.value) return
  if (!kbs.currentKbId) {
    error.value = '请先选择知识库'
    return
  }
  submitting.value = true
  error.value = ''
  const targets = rows.value.filter((r) => r.status !== 'submitted')
  const notebookTargets = targets.filter((r) => isNotebookFile(r.file.name))
  const ingestTargets = targets.filter((r) => !isNotebookFile(r.file.name))
  const batchLabel =
    targets.length === 1 ? targets[0].file.name : `${targets[0].file.name} 等 ${targets.length} 个文件`
  let currentBatch: ImportBatch | null = null
  try {
    let batchId: string | null = null
    if (ingestTargets.length) {
      currentBatch = await notes.createImportBatch('upload', batchLabel, ingestTargets.length)
      batch.value = currentBatch
      batchId = currentBatch.id
    }
    for (const row of targets) {
      row.status = 'uploading'
      row.message = ''
      try {
        if (isNotebookFile(row.file.name)) {
          const note = await notes.importNotebook(row.file, {
            folder_id: props.folderId,
            parent_note_id: props.parentNoteId,
            open: false,
          })
          row.status = 'submitted'
          row.percent = 1
          row.noteId = note.id
          row.note = note
          if (!firstNote.value) firstNote.value = note
          row.message = 'Notebook 已创建'
          continue
        }
        let uploadId: string | undefined
        if (row.file.size > CHUNKED_THRESHOLD) {
          uploadId = await uploadFileInChunks(row.file, kbs.currentKbId!, (p) => {
            row.percent = p.percent
            row.message = `${Math.round(p.percent * 100)}%（分片续传）`
          })
        }
        const res = await notes.importFile(uploadId ? null : row.file, {
          folder_id: props.folderId,
          parent_note_id: props.parentNoteId,
          batch_id: batchId ?? undefined,
          upload_id: uploadId,
          compile_now: readonlyImport.value ? false : compileNow.value,
          readonly: readonlyImport.value,
          open: false,
        })
        row.status = 'submitted'
        row.percent = 1
        row.noteId = res.note.id
        row.note = res.note
        if (!firstNote.value) firstNote.value = res.note
        row.message = readonlyImport.value ? '已创建只读笔记' : '已提交解析'
      } catch (e: any) {
        row.status = 'failed'
        row.message = e?.message || '导入失败'
      }
    }
    if (batchId) {
      await notes.closeImportBatch(batchId)
      watchBatch(batchId)
    } else {
      await notes.fetchTree()
      if (firstNote.value) {
        emit('created', firstNote.value)
        firstNote.value = null
      }
    }
    const failed = rows.value.filter((r) => r.status === 'failed').length
    if (failed) {
      toast.error(`有 ${failed} 个文件提交失败，其余已处理`)
    } else if (notebookTargets.length && !ingestTargets.length) {
      toast.success(`已导入 ${notebookTargets.length} 个 Notebook`)
    } else {
      toast.success('文件已提交，正在后台解析')
    }
  } catch (e: any) {
    error.value = e?.message || '创建导入批次失败'
    if (currentBatch) {
      try {
        batch.value = await notes.fetchImportBatch(currentBatch.id)
      } catch {
        /* ignore */
      }
    }
  } finally {
    submitting.value = false
  }
}

function invalidUrl(value: string) {
  try {
    const parsed = new URL(value)
    return parsed.protocol !== 'http:' && parsed.protocol !== 'https:'
  } catch {
    return true
  }
}

async function submitUrls() {
  if (!urlList.value.length) {
    error.value = '请粘贴至少一个线上文件链接'
    return
  }
  const invalid = urlList.value.find(invalidUrl)
  if (invalid) {
    error.value = `链接格式不正确：${invalid}`
    return
  }
  if (submitting.value) return
  if (!kbs.currentKbId) {
    error.value = '请先选择知识库'
    return
  }
  submitting.value = true
  error.value = ''
  const targets = urlList.value
  const label = targets.length === 1 ? targets[0] : `${targets[0]} 等 ${targets.length} 个链接`
  let currentBatch: ImportBatch | null = null
  let failed = 0
  let lastError = ''
  try {
    currentBatch = await notes.createImportBatch('url', label, targets.length)
    batch.value = currentBatch
    const batchId = currentBatch.id
    for (const url of targets) {
      try {
        const res = await notes.importRemoteFile({
          url,
          folder_id: props.folderId,
          parent_note_id: props.parentNoteId,
          batch_id: batchId,
          title: targets.length === 1 ? urlTitle.value.trim() : '',
          compile_now: readonlyImport.value ? false : compileNow.value,
          readonly: readonlyImport.value,
        })
        if (!firstNote.value) firstNote.value = res.note
      } catch (e: any) {
        failed += 1
        lastError = e?.message || '导入失败'
      }
    }
    await notes.closeImportBatch(batchId)
    watchBatch(batchId)
    if (failed) {
      toast.error(`${failed} 个链接导入失败${lastError ? `：${lastError}` : ''}`)
    } else {
      toast.success('线上文件已提交，正在后台下载解析')
    }
  } catch (e: any) {
    error.value = e?.message || '创建线上文件导入批次失败'
    if (currentBatch) {
      try {
        batch.value = await notes.fetchImportBatch(currentBatch.id)
      } catch {
        /* ignore */
      }
    }
  } finally {
    submitting.value = false
  }
}

// ---------- 表格导入 ----------
const FIELD_TYPE_LABEL: Record<string, string> = {
  text: '文本',
  long_text: '长文本',
  number: '数字',
  date: '日期',
  checkbox: '复选框',
  url: '链接',
}

function fieldTypeLabel(type: string) {
  return FIELD_TYPE_LABEL[type] ?? type
}

function tableExt(name: string) {
  return `.${name.split('.').pop()?.toLowerCase() ?? ''}`
}

async function loadTablePreview(file: File, sheet?: string) {
  const seq = ++tablePreviewSeq
  tablePreviewLoading.value = true
  error.value = ''
  try {
    const preview = await notes.previewTable(file, {
      sheet,
      has_header: tableHasHeader.value,
    })
    if (seq !== tablePreviewSeq || !props.open) return
    tablePreview.value = preview
    tableSheet.value = preview.sheet
  } catch (e: any) {
    if (seq !== tablePreviewSeq) return
    tablePreview.value = null
    error.value = e?.message || '表格解析失败'
  } finally {
    if (seq === tablePreviewSeq) tablePreviewLoading.value = false
  }
}

function pickTable(list: FileList | null) {
  const file = list?.[0]
  if (!file) return
  if (!TABLE_ACCEPT.includes(tableExt(file.name))) {
    error.value = '请选择 .csv、.xlsx 或 .xls 表格文件'
    return
  }
  if (file.size > MAX_TABLE_BYTES) {
    error.value = '表格文件超过 20MB 上限'
    return
  }
  tableFile.value = file
  tableTitle.value = file.name.replace(/\.[^.]+$/, '').slice(0, 300)
  tableSheet.value = ''
  tablePreview.value = null
  error.value = ''
  void loadTablePreview(file)
  if (tableInput.value) tableInput.value.value = ''
}

function onTableDrop(e: DragEvent) {
  tableDrag.value = false
  pickTable(e.dataTransfer?.files ?? null)
}

function reloadTablePreview() {
  if (tableFile.value) void loadTablePreview(tableFile.value, tableSheet.value || undefined)
}

function onTableSheetChange() {
  if (tableFile.value) void loadTablePreview(tableFile.value, tableSheet.value)
}

async function submitTable() {
  if (!tableFile.value || !tablePreview.value) {
    error.value = '请先选择并预览表格文件'
    return
  }
  if (!kbs.currentKbId) {
    error.value = '请先选择知识库'
    return
  }
  if (tableImporting.value) return
  tableImporting.value = true
  error.value = ''
  try {
    const res = await notes.importTable(tableFile.value, {
      folder_id: props.folderId,
      parent_note_id: props.parentNoteId,
      title: tableTitle.value,
      sheet: tableSheet.value,
      has_header: tableHasHeader.value,
    })
    toast.success(`已导入 ${res.row_count} 条记录到数据表`)
    tableImporting.value = false
    emit('created', res.note)
    close()
  } catch (e: any) {
    error.value = e?.message || '表格导入失败'
  } finally {
    tableImporting.value = false
  }
}

function pickZip(list: FileList | null) {
  const file = list?.[0]
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    error.value = '请选择 .zip 格式的语雀 Markdown 导出包'
    return
  }
  if (file.size > MAX_BYTES) {
    error.value = '导出包超过 200MB'
    return
  }
  zipFile.value = file
  error.value = ''
}

const zipDragging = ref(false)
function onZipDrop(event: DragEvent) {
  zipDragging.value = false
  if (busy.value) return
  pickZip(event.dataTransfer?.files ?? null)
}

/** 粘贴令牌后自动尝试获取一次知识库列表，减少手动点击。 */
function maybeFetchRepos() {
  if (reposLoading.value || busy.value) return
  if (token.value.trim().length < 10 || repos.value.length) return
  void fetchYuqueRepos()
}

function scheduleRepoFetch() {
  window.setTimeout(maybeFetchRepos, 180)
}

async function submitYuqueToken() {
  if (!token.value.trim() || !repo.value.trim()) {
    error.value = '请填写语雀访问令牌与知识库路径'
    return
  }
  if (yuqueSubmitting.value) return
  yuqueSubmitting.value = true
  error.value = ''
  try {
    const created = await notes.importYuqueToken({
      token: token.value.trim(),
      repo: repo.value.trim(),
      compile_now: yuqueCompile.value,
      folder_id: props.folderId,
      create_notes: createNotes.value,
    })
    if (!created) {
      error.value = '语雀导入失败'
      return
    }
    batch.value = created
    reportOpen.value = true
    watchBatch(created.id)
    toast.success('已开始从语雀拉取文档')
  } catch (e: any) {
    error.value = e?.message || '语雀导入失败'
  } finally {
    yuqueSubmitting.value = false
  }
}

async function submitYuqueZip() {
  if (!zipFile.value) {
    error.value = '请选择语雀导出包'
    return
  }
  if (yuqueSubmitting.value) return
  yuqueSubmitting.value = true
  error.value = ''
  try {
    const created = await notes.importYuqueZip(zipFile.value, {
      compile_now: yuqueCompile.value,
      folder_id: props.folderId,
      create_notes: createNotes.value,
    })
    if (!created) {
      error.value = '导出包导入失败'
      return
    }
    batch.value = created
    reportOpen.value = true
    watchBatch(created.id)
    toast.success('导出包已提交，正在解压入库')
  } catch (e: any) {
    error.value = e?.message || '导出包导入失败'
  } finally {
    yuqueSubmitting.value = false
  }
}

async function selectHistory(item: ImportBatch) {
  batch.value = item
  reportOpen.value = true
  if (item.status === 'running') {
    watchBatch(item.id)
  } else {
    stopPoll()
  }
}

function providerLabel(provider: string) {
  if (provider === 'yuque_token') return '语雀令牌'
  if (provider === 'yuque_zip') return '语雀导出包'
  if (provider === 'url') return '线上文件'
  return '文件上传'
}

function statusLabel(status: string) {
  if (status === 'running') return '进行中'
  if (status === 'completed') return '已完成'
  if (status === 'partial') return '部分失败'
  if (status === 'failed') return '失败'
  return status
}

function statusClass(status: string) {
  if (status === 'completed') return 'bg-emerald-50 text-emerald-600'
  if (status === 'partial') return 'bg-amber-50 text-amber-600'
  if (status === 'failed') return 'bg-rose-50 text-rose-600'
  return 'bg-sky-50 text-sky-600'
}

function qualityLabel(quality?: string | null) {
  if (!quality) return '—'
  if (quality === 'clean') return '干净'
  if (quality === 'ocr_aided') return 'OCR 辅助'
  if (quality === 'review') return '待复核'
  return quality
}

function scanLabel(status?: string | null) {
  if (!status) return '—'
  if (status === 'clean') return 'ClamAV 通过'
  if (status === 'heuristic') return '启发式检查'
  if (status === 'unavailable') return '未扫描'
  if (status === 'infected') return '检出威胁'
  if (status === 'error') return '扫描异常'
  return status
}

function formatTime(value?: string | null) {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}
</script>

<template>
  <KiwiModal :open="open" title="导入" max-w="max-w-3xl" @close="close">
    <div class="space-y-4">
      <div class="flex items-center gap-1 rounded-lg bg-slate-100/80 p-1 w-fit">
        <button
          v-for="item in TABS"
          :key="item.key"
          class="px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors"
          :class="tab === item.key ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
          @click="switchTab(item.key)"
        >
          {{ item.label }}
        </button>
      </div>

      <!-- 文件上传 -->
      <div v-if="tab === 'files'" class="space-y-3">
        <input
          ref="input"
          type="file"
          multiple
          :accept="ACCEPT.join(',')"
          class="hidden"
          @change="pick(($event.target as HTMLInputElement).files)"
        />
        <div
          class="rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors cursor-pointer"
          :class="dragOver ? 'border-kiwi-400 bg-kiwi-50/70' : 'border-slate-200 bg-white/50 hover:border-kiwi-300 hover:bg-kiwi-50/40'"
          @click="!busy && input?.click()"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="onDrop"
        >
          <div class="w-10 h-10 mx-auto rounded-xl bg-kiwi-50 text-kiwi-500 grid place-items-center mb-2">
            <KiwiIcon name="fileImport" :size="19" />
          </div>
          <p class="text-[12.5px] font-medium text-slate-600">拖拽文件到这里，或点击选择（支持多选）</p>
          <p class="text-[11px] text-slate-400 mt-0.5">
            Markdown / 文本 / PDF / Word / Jupyter Notebook / 图片（OCR）；≤20MB 直传，更大文件自动分片续传，单文件上限 200MB；Notebook 上限 20MB
          </p>
        </div>

        <div v-if="rows.length" class="max-h-52 overflow-y-auto rounded-lg border border-slate-100 divide-y divide-slate-100">
          <div
            v-for="(row, index) in rows"
            :key="row.file.name + row.file.size"
            class="px-3 py-2 flex items-center gap-2"
          >
            <KiwiIcon
              :name="row.status === 'failed' ? 'alert' : row.status === 'submitted' ? 'check' : 'file'"
              :size="14"
              :class="row.status === 'failed' ? 'text-rose-500' : row.status === 'submitted' ? 'text-emerald-500' : 'text-slate-400'"
            />
            <div class="min-w-0 flex-1">
              <p class="text-[12px] text-slate-700 truncate">{{ row.file.name }}</p>
              <p class="text-[10.5px] text-slate-400">
                {{ sizeText(row.file.size) }}
                <span v-if="row.noteId" class="text-emerald-500"> · 已生成文档</span>
                <span v-if="row.message" :class="row.status === 'failed' ? 'text-rose-500' : ''"> · {{ row.message }}</span>
              </p>
              <div v-if="row.status === 'uploading'" class="h-1 rounded-full bg-slate-100 mt-1 overflow-hidden">
                <div class="h-full bg-kiwi-400 transition-all" :style="{ width: `${Math.round(row.percent * 100)}%` }" />
              </div>
            </div>
            <button
              v-if="!busy && row.status !== 'submitted'"
              class="p-1 text-slate-300 hover:text-rose-500"
              title="移除"
              @click="removeRow(index)"
            >
              <KiwiIcon name="close" :size="13" />
            </button>
          </div>
        </div>

        <div class="space-y-1.5">
          <label class="flex items-center gap-2 text-[11.5px] text-slate-500">
            <input v-model="readonlyImport" type="checkbox" class="rounded border-slate-300" />
            只读导入：保留原始文件，仅阅读，不解析为可编辑文档
          </label>
          <label
            class="flex items-center gap-2 text-[11.5px]"
            :class="readonlyImport ? 'text-slate-300' : 'text-slate-500'"
          >
            <input
              v-model="compileNow"
              type="checkbox"
              class="rounded border-slate-300"
              :disabled="readonlyImport"
            />
            入库后立即编译为 Wiki（默认仅入库，稍后按需编译）
          </label>
        </div>
      </div>

      <!-- 表格导入 -->
      <div v-else-if="tab === 'sheet'" class="space-y-3">
        <input
          ref="tableInput"
          type="file"
          accept=".csv,.xlsx,.xls"
          class="hidden"
          @change="pickTable(($event.target as HTMLInputElement).files)"
        />
        <div
          class="rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors cursor-pointer"
          :class="tableDrag ? 'border-kiwi-400 bg-kiwi-50/70' : 'border-slate-200 bg-white/50 hover:border-kiwi-300 hover:bg-kiwi-50/40'"
          @click="!busy && tableInput?.click()"
          @dragover.prevent="tableDrag = true"
          @dragleave.prevent="tableDrag = false"
          @drop.prevent="onTableDrop"
        >
          <div class="w-10 h-10 mx-auto rounded-xl bg-kiwi-50 text-kiwi-500 grid place-items-center mb-2">
            <KiwiIcon name="table" :size="19" />
          </div>
          <p v-if="tableFile" class="text-[12.5px] font-medium text-slate-700 truncate">
            {{ tableFile.name }}
          </p>
          <p v-else class="text-[12.5px] font-medium text-slate-600">
            拖拽 CSV / Excel 到这里，或点击选择
          </p>
          <p class="text-[11px] text-slate-400 mt-0.5">
            支持 .csv / .xlsx / .xls，≤20MB；会转换为数据表。导入后可在表格中勾选记录，按需生成可编辑笔记
          </p>
        </div>

        <template v-if="tableFile">
          <div class="flex flex-wrap items-center gap-4 text-[11.5px] text-slate-500">
            <label v-if="(tablePreview?.sheets.length ?? 0) > 1" class="flex items-center gap-1.5">
              工作表
              <select v-model="tableSheet" class="kiwi-input !py-1 !text-[11.5px]" @change="onTableSheetChange">
                <option v-for="sheet in tablePreview?.sheets ?? []" :key="sheet.name" :value="sheet.name">
                  {{ sheet.name }}（{{ sheet.row_count }} 行）
                </option>
              </select>
            </label>
            <label class="flex items-center gap-1.5">
              <input
                v-model="tableHasHeader"
                type="checkbox"
                class="rounded border-slate-300"
                @change="reloadTablePreview"
              />
              首行作为表头
            </label>
            <span v-if="tablePreview" class="text-slate-400 tabular-nums">
              {{ tablePreview.row_count }} 行 × {{ tablePreview.fields.length }} 列
            </span>
          </div>

          <div v-if="tablePreviewLoading" class="flex items-center gap-2 py-6 text-[12px] text-slate-400">
            <KiwiIcon name="loader" :size="14" spin />
            正在解析并推断字段类型…
          </div>

          <template v-else-if="tablePreview">
            <div class="rounded-lg border border-slate-100 overflow-auto max-h-56">
              <table class="w-full text-left text-[11px]">
                <thead class="sticky top-0 bg-slate-50/95 backdrop-blur">
                  <tr>
                    <th
                      v-for="field in tablePreview.fields"
                      :key="field.id"
                      class="whitespace-nowrap border-b border-slate-100 px-2 py-1.5 font-medium text-slate-600"
                    >
                      {{ field.name }}
                      <span class="ml-1 rounded bg-white px-1 py-px text-[9px] font-normal text-slate-400 border border-slate-100">
                        {{ fieldTypeLabel(field.type) }}
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, index) in tablePreview.sample_rows" :key="index" class="border-b border-slate-50 last:border-0">
                    <td
                      v-for="field in tablePreview.fields"
                      :key="field.id"
                      class="max-w-[220px] truncate px-2 py-1 text-slate-500"
                    >
                      {{ row[field.id] === null || row[field.id] === undefined || row[field.id] === '' ? '—' : row[field.id] }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="tablePreview.truncated" class="text-[11px] text-amber-600">
              表格行数较多，仅导入前 5000 行。
            </p>
            <div>
              <label class="block text-[11px] font-medium text-slate-500 mb-1.5">数据表标题</label>
              <input v-model="tableTitle" class="kiwi-input" placeholder="默认使用文件名" />
            </div>
          </template>
        </template>
      </div>

      <!-- 线上文件 -->
      <div v-else-if="tab === 'url'" class="space-y-3">
        <div>
          <label class="block text-[11px] font-medium text-slate-500 mb-1.5">线上文件链接</label>
          <textarea
            v-model="urlText"
            rows="5"
            spellcheck="false"
            class="kiwi-input font-mono !text-[11.5px] leading-relaxed resize-y"
            placeholder="https://example.com/paper.pdf&#10;https://example.com/notes.md&#10;每行一个直链，支持 PDF / Word / Markdown / 文本"
          />
          <p class="mt-1 text-[11px] leading-relaxed text-slate-400">
            服务端下载后再入库，单个文件上限 50MB；会拒绝内网与本机地址。网页正文请使用「新建 → 链接」。
          </p>
        </div>
        <div>
          <label class="block text-[11px] font-medium text-slate-500 mb-1.5">
            标题（可选，仅单个链接生效）
          </label>
          <input
            v-model="urlTitle"
            class="kiwi-input"
            placeholder="留空时使用文件名"
            @keydown.enter.prevent="submitUrls"
          />
        </div>
        <div class="space-y-1.5">
          <label class="flex items-center gap-2 text-[11.5px] text-slate-500">
            <input v-model="readonlyImport" type="checkbox" class="rounded border-slate-300" />
            只读导入：保留下载的原始文件，仅阅读，不解析为可编辑文档
          </label>
          <label
            class="flex items-center gap-2 text-[11.5px]"
            :class="readonlyImport ? 'text-slate-300' : 'text-slate-500'"
          >
            <input
              v-model="compileNow"
              type="checkbox"
              class="rounded border-slate-300"
              :disabled="readonlyImport"
            />
            入库后立即编译为 Wiki（默认仅入库，稍后按需编译）
          </label>
        </div>
      </div>

      <!-- 语雀：面向非技术用户的迁移向导，默认推荐「导出包」 -->
      <div v-else-if="tab === 'yuque'" class="space-y-3">
        <div class="flex items-start gap-2.5 rounded-xl border border-kiwi-100 bg-kiwi-50/50 px-3.5 py-3">
          <span class="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-white text-kiwi-600 shadow-sm">
            <KiwiIcon name="fileImport" :size="15" />
          </span>
          <div class="min-w-0">
            <p class="text-[12.5px] font-medium text-slate-700">把语雀知识库搬进 Kiwi</p>
            <p class="mt-0.5 text-[11.5px] leading-relaxed text-slate-500">
              推荐从语雀导出 Markdown 压缩包再上传：不用申请令牌，也不受接口限流影响。
              导入后会按原目录结构生成可编辑笔记。
            </p>
          </div>
        </div>

        <div class="flex items-center gap-1 rounded-lg bg-slate-100/70 p-1 w-fit">
          <button
            class="px-3 py-1.5 rounded-md text-[11.5px] font-medium transition-colors"
            :class="yuqueMode === 'zip' ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-500'"
            @click="yuqueMode = 'zip'"
          >
            上传导出包 · 推荐
          </button>
          <button
            class="px-3 py-1.5 rounded-md text-[11.5px] font-medium transition-colors"
            :class="yuqueMode === 'token' ? 'bg-white text-slate-700 shadow-sm' : 'text-slate-500'"
            @click="yuqueMode = 'token'"
          >
            令牌直连 · 进阶
          </button>
        </div>

        <template v-if="yuqueMode === 'zip'">
          <ol class="space-y-1 rounded-xl bg-slate-50/70 px-3.5 py-2.5 text-[11.5px] leading-relaxed text-slate-500">
            <li><span class="font-medium text-slate-600">1.</span> 打开语雀知识库，点右上角「…」→「导出」→ 选择 Markdown，下载压缩包。</li>
            <li><span class="font-medium text-slate-600">2.</span> 把 .zip 文件拖到下方，或点击选择文件。</li>
            <li><span class="font-medium text-slate-600">3.</span> 点击「开始迁移」，完成后在左侧的笔记目录里查看。</li>
          </ol>
          <input
            ref="zipInput"
            type="file"
            accept=".zip"
            class="hidden"
            @change="pickZip(($event.target as HTMLInputElement).files)"
          />
          <div
            class="cursor-pointer rounded-xl border-2 border-dashed px-4 py-7 text-center transition-colors"
            :class="
              zipDragging
                ? 'border-kiwi-400 bg-kiwi-50/70'
                : 'border-slate-200 bg-white/50 hover:border-kiwi-300 hover:bg-kiwi-50/40'
            "
            @click="!busy && zipInput?.click()"
            @dragover.prevent="zipDragging = true"
            @dragleave.prevent="zipDragging = false"
            @drop.prevent="onZipDrop($event)"
          >
            <KiwiIcon name="fileImport" :size="22" class="text-kiwi-500 mx-auto mb-1.5" />
            <p v-if="zipFile" class="truncate px-4 text-[12.5px] font-medium text-slate-700">
              {{ zipFile.name }}
            </p>
            <p v-else class="text-[12.5px] font-medium text-slate-600">
              {{ zipDragging ? '松手即可导入' : '把语雀导出的 .zip 拖到这里' }}
            </p>
            <p class="mt-0.5 text-[11px] text-slate-400">或点击选择文件 · 最大 200MB</p>
            <p v-if="zipFile" class="mt-1 text-[10.5px] text-kiwi-600">点击可重新选择文件</p>
          </div>
        </template>

        <template v-else>
          <ol class="space-y-1 rounded-xl bg-slate-50/70 px-3.5 py-2.5 text-[11.5px] leading-relaxed text-slate-500">
            <li>
              <span class="font-medium text-slate-600">1.</span>
              登录语雀，在
              <a
                href="https://www.yuque.com/settings/tokens"
                target="_blank"
                rel="noopener noreferrer"
                class="font-medium text-kiwi-600 underline decoration-kiwi-300 underline-offset-2 hover:text-kiwi-700"
              >账户设置 → 令牌</a>
              页面新建一个令牌（只读即可）。
            </li>
            <li><span class="font-medium text-slate-600">2.</span> 把令牌粘贴到下面，会自动列出你有权限的知识库。</li>
            <li><span class="font-medium text-slate-600">3.</span> 选择知识库，点击「开始迁移」。</li>
          </ol>
          <div>
            <label class="block text-[11px] font-medium text-slate-500 mb-1.5">
              语雀访问令牌
              <span class="font-normal text-slate-400">· 仅本次导入使用，不会保存</span>
            </label>
            <input
              v-model="token"
              type="password"
              name="yuque-token"
              autocomplete="new-password"
              spellcheck="false"
              class="kiwi-input"
              placeholder="粘贴语雀令牌"
              @blur="maybeFetchRepos"
              @paste="scheduleRepoFetch"
            />
          </div>
          <div>
            <div class="mb-1.5 flex items-center justify-between">
              <label class="block text-[11px] font-medium text-slate-500">要迁移的知识库</label>
              <button
                type="button"
                class="flex items-center gap-1 text-[11px] text-kiwi-600 hover:text-kiwi-700 disabled:text-slate-300"
                :disabled="reposLoading || !token.trim()"
                @click="fetchYuqueRepos"
              >
                <KiwiIcon name="refresh" :size="11" :spin="reposLoading" />
                {{ reposLoading ? '正在获取…' : '获取知识库列表' }}
              </button>
            </div>
            <select
              v-if="repos.length"
              v-model="repo"
              class="kiwi-input mb-1.5"
            >
              <option v-for="item in repos" :key="item.namespace" :value="item.namespace">
                {{ item.group ? `[${item.group}] ` : '' }}{{ item.name }} · {{ item.namespace }}
                （{{ item.items_count }} 篇）
              </option>
            </select>
            <input
              v-model="repo"
              name="yuque-repo"
              autocomplete="off"
              spellcheck="false"
              class="kiwi-input"
              placeholder="也可以直接粘贴知识库链接或 user/repo"
            />
          </div>
          <p class="flex items-start gap-1.5 text-[11px] leading-relaxed text-slate-400">
            <KiwiIcon name="alert" :size="12" class="mt-0.5 shrink-0" />
            为遵守语雀接口限流，文档会逐篇拉取，篇数多时需要一些时间；附件会保留原始链接。
          </p>
        </template>

        <div class="space-y-1.5 rounded-xl border border-slate-100 bg-slate-50/50 px-3.5 py-2.5">
          <p class="text-[11px] font-medium text-slate-500">导入后</p>
          <label class="flex items-start gap-2 text-[11.5px] text-slate-600">
            <input v-model="createNotes" type="checkbox" class="mt-0.5 rounded border-slate-300" />
            <span>
              生成可编辑笔记
              <span class="block text-[10.5px] text-slate-400">在左侧目录中按语雀原结构创建文档，可继续编辑。</span>
            </span>
          </label>
          <label class="flex items-start gap-2 text-[11.5px] text-slate-600">
            <input v-model="yuqueCompile" type="checkbox" class="mt-0.5 rounded border-slate-300" />
            <span>
              导入后立即编译 Wiki
              <span class="block text-[10.5px] text-slate-400">耗时更长；不勾选也可以稍后在知识库卡片上手动编译。</span>
            </span>
          </label>
        </div>
      </div>

      <!-- 历史批次 -->
      <div v-else class="space-y-2">
        <div class="flex items-center justify-between">
          <p class="text-[11.5px] text-slate-400">最近 30 个批次</p>
          <button class="text-[11.5px] text-kiwi-600 hover:underline flex items-center gap-1" @click="loadHistory">
            <KiwiIcon name="refresh" :size="12" :spin="historyLoading" /> 刷新
          </button>
        </div>
        <div v-if="history.length" class="rounded-lg border border-slate-100 divide-y divide-slate-100 max-h-64 overflow-y-auto">
          <button
            v-for="item in history"
            :key="item.id"
            class="w-full text-left px-3 py-2 hover:bg-slate-50/70 flex items-center gap-2"
            @click="selectHistory(item)"
          >
            <span class="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" :class="statusClass(item.status)">
              {{ statusLabel(item.status) }}
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-[12px] text-slate-700 truncate">
                {{ item.report_json?.label || providerLabel(item.provider) }}
              </p>
              <p class="text-[10.5px] text-slate-400">
                {{ providerLabel(item.provider) }} · 成功 {{ item.processed_count }} / {{ item.total_sources }}
                <span v-if="item.failed_count"> · 失败 {{ item.failed_count }}</span>
                <span v-if="item.skipped_count"> · 跳过 {{ item.skipped_count }}</span>
                · {{ formatTime(item.created_at) }}
              </p>
            </div>
            <KiwiIcon name="chevronRight" :size="12" class="text-slate-300" />
          </button>
        </div>
        <p v-else class="text-[12px] text-slate-400 text-center py-6">还没有导入记录</p>
      </div>

      <p v-if="error" class="text-[11.5px] text-rose-500">{{ error }}</p>

      <!-- 批次进度与报告 -->
      <div v-if="batch" class="rounded-xl border border-slate-100 bg-slate-50/50">
        <button
          class="w-full px-3 py-2.5 flex items-center gap-2 text-left"
          @click="reportOpen = !reportOpen"
        >
          <span class="text-[10px] px-1.5 py-0.5 rounded-full" :class="statusClass(batch.status)">
            {{ statusLabel(batch.status) }}
          </span>
          <span class="text-[12px] font-medium text-slate-700 flex-1 truncate">
            {{ batch.report_json?.label || providerLabel(batch.provider) }}
          </span>
          <span class="text-[11px] text-slate-400">
            {{ batch.processed_count }}/{{ batch.total_sources }}
            <template v-if="batch.failed_count"> · 失败 {{ batch.failed_count }}</template>
            <template v-if="batch.skipped_count"> · 跳过 {{ batch.skipped_count }}</template>
          </span>
          <KiwiIcon :name="reportOpen ? 'arrowUp' : 'arrowDown'" :size="12" class="text-slate-400" />
        </button>
        <div v-if="batch.status === 'running'" class="px-3 pb-2">
          <div class="h-1.5 rounded-full bg-white overflow-hidden border border-slate-100">
            <div class="h-full bg-kiwi-400 transition-all" :style="{ width: `${progressPercent}%` }" />
          </div>
          <p class="text-[10.5px] text-slate-400 mt-1">解析与向量化在后台进行，完成后自动生成报告</p>
        </div>

        <div v-if="reportOpen" class="px-3 pb-3 space-y-2.5">
          <p v-if="batch.error" class="text-[11.5px] text-rose-500">{{ batch.error }}</p>

          <div v-if="report.summary" class="grid grid-cols-4 gap-1.5 text-center">
            <div class="rounded-lg bg-white border border-slate-100 py-1.5">
              <p class="text-[15px] font-semibold text-slate-700">{{ report.summary.processed }}</p>
              <p class="text-[10px] text-slate-400">成功</p>
            </div>
            <div class="rounded-lg bg-white border border-slate-100 py-1.5">
              <p class="text-[15px] font-semibold" :class="report.summary.failed ? 'text-rose-500' : 'text-slate-700'">
                {{ report.summary.failed }}
              </p>
              <p class="text-[10px] text-slate-400">失败</p>
            </div>
            <div class="rounded-lg bg-white border border-slate-100 py-1.5">
              <p class="text-[15px] font-semibold text-slate-700">{{ report.summary.skipped }}</p>
              <p class="text-[10px] text-slate-400">跳过</p>
            </div>
            <div class="rounded-lg bg-white border border-slate-100 py-1.5">
              <p class="text-[15px] font-semibold text-slate-700">{{ report.summary.compiled }}</p>
              <p class="text-[10px] text-slate-400">已编译</p>
            </div>
          </div>

          <div v-if="report.quality" class="flex flex-wrap gap-1.5">
            <span
              v-for="(count, quality) in report.quality"
              :key="quality"
              class="text-[10.5px] px-2 py-0.5 rounded-full"
              :class="quality === 'review' ? 'bg-amber-50 text-amber-600' : quality === 'ocr_aided' ? 'bg-sky-50 text-sky-600' : 'bg-emerald-50 text-emerald-600'"
            >
              解析质量 {{ qualityLabel(String(quality)) }} · {{ count }}
            </span>
            <span
              v-for="(count, engine) in report.engines"
              :key="`engine-${engine}`"
              class="text-[10.5px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-500"
            >
              {{ engine }} · {{ count }}
            </span>
            <span
              v-for="(count, scan) in report.scan"
              :key="`scan-${scan}`"
              class="text-[10.5px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-500"
            >
              安全 {{ scanLabel(String(scan)) }} · {{ count }}
            </span>
          </div>

          <div v-if="report.failures?.length" class="rounded-lg bg-rose-50/60 border border-rose-100 px-2.5 py-2 space-y-1">
            <p class="text-[11px] font-medium text-rose-600">失败条目</p>
            <p v-for="(failure, i) in report.failures" :key="i" class="text-[11px] text-rose-500">
              {{ failure.title }}：{{ failure.error }}
            </p>
          </div>

          <div v-if="reportItems.length" class="rounded-lg border border-slate-100 bg-white max-h-52 overflow-y-auto divide-y divide-slate-50">
            <div v-for="(item, i) in reportItems" :key="i" class="px-2.5 py-1.5">
              <div class="flex items-center gap-1.5">
                <KiwiIcon
                  :name="item.status === 'skipped' ? 'minus' : item.status === 'failed' ? 'alert' : 'check'"
                  :size="11"
                  :class="item.status === 'failed' ? 'text-rose-400' : item.status === 'skipped' ? 'text-slate-300' : 'text-emerald-400'"
                />
                <span class="text-[11.5px] text-slate-600 truncate flex-1">{{ item.title }}</span>
                <span v-if="item.note_id" class="text-[10px] text-emerald-500">文档</span>
                <span v-if="item.error" class="text-[10.5px] text-rose-400 truncate max-w-[45%]">{{ item.error }}</span>
              </div>
            </div>
          </div>

          <div v-if="report.sources?.length" class="space-y-1">
            <p class="text-[10.5px] text-slate-400">素材解析明细</p>
            <div class="rounded-lg border border-slate-100 bg-white max-h-48 overflow-y-auto divide-y divide-slate-50">
              <div v-for="source in report.sources" :key="source.id" class="px-2.5 py-1.5">
                <div class="flex items-center gap-1.5">
                  <span class="text-[11.5px] text-slate-600 truncate flex-1">{{ source.title }}</span>
                  <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">{{ source.type }}</span>
                  <span
                    class="text-[10px] px-1.5 py-0.5 rounded"
                    :class="source.parse_quality === 'review' ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-600'"
                  >
                    {{ qualityLabel(source.parse_quality) }}
                  </span>
                </div>
                <p class="text-[10px] text-slate-400 mt-0.5">
                  {{ source.parse_engine }} · {{ source.chars }} 字 · {{ scanLabel(source.scan_status) }}
                  <span v-if="source.warnings?.length" class="text-amber-500"> · {{ source.warnings.join('；') }}</span>
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="flex items-center justify-between gap-2 mt-5">
      <p class="text-[10.5px] text-slate-400">
        <template v-if="busy">正在处理，请勿关闭…</template>
        <template v-else-if="tab === 'yuque'">迁移会保留语雀的目录结构与正文顺序；附件保留原始链接。</template>
        <template v-else-if="tab === 'sheet'">表格会转换为数据表，每行生成一条记录；导入后可在表格中勾选记录按需生成笔记。</template>
        <template v-else>导入默认仅入库；编译可在素材或 Wiki 中按需触发。</template>
      </p>
      <div class="flex gap-2">
        <button class="kiwi-btn-secondary" :disabled="busy" @click="close">关闭</button>
        <button
          v-if="tab === 'files'"
          class="kiwi-btn-primary"
          :disabled="busy || !pendingRows.length"
          @click="submitFiles"
        >
          <KiwiIcon v-if="submitting" name="loader" :size="14" spin />
          {{ submitting ? '上传中…' : `开始导入${rows.length > 1 ? `（${rows.length}）` : ''}` }}
        </button>
        <button
          v-else-if="tab === 'sheet'"
          class="kiwi-btn-primary"
          :disabled="busy || !tableFile || !tablePreview || !tablePreview.fields.length"
          @click="submitTable"
        >
          <KiwiIcon v-if="tableImporting" name="loader" :size="14" spin />
          {{ tableImporting ? '导入中…' : `导入为数据表${tablePreview ? `（${tablePreview.row_count} 行）` : ''}` }}
        </button>
        <button
          v-else-if="tab === 'url'"
          class="kiwi-btn-primary"
          :disabled="busy || !urlList.length"
          @click="submitUrls"
        >
          <KiwiIcon v-if="submitting" name="loader" :size="14" spin />
          {{ submitting ? '提交中…' : `导入链接${urlList.length > 1 ? `（${urlList.length}）` : ''}` }}
        </button>
        <button
          v-else-if="tab === 'yuque'"
          class="kiwi-btn-primary"
          :disabled="busy || (yuqueMode === 'token' ? !token.trim() || !repo.trim() : !zipFile)"
          @click="yuqueMode === 'token' ? submitYuqueToken() : submitYuqueZip()"
        >
          <KiwiIcon v-if="yuqueSubmitting" name="loader" :size="14" spin />
          {{ yuqueSubmitting ? '提交中…' : '开始迁移' }}
        </button>
        <button v-else class="kiwi-btn-secondary" @click="tab = 'files'">去导入</button>
      </div>
    </div>
  </KiwiModal>
</template>
