<script setup lang="ts">
/** 素材管理：原文、解析质量、安全扫描、导入批次与编译进度。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { request } from '@/api/client'
import {
  cancelBatch,
  compileSources,
  deleteSource,
  getJob,
  listBatches,
  listJobs,
  listSources,
  reparseSource,
  type IngestJob,
  type SourceItem,
} from '@/api/sources'
import { useKbsStore } from '@/stores/kbs'
import { useNotesStore } from '@/stores/notes'
import type { ImportBatch, ImportBatchReport } from '@/stores/notes'
import NoteImportDialog from '@/components/notes/NoteImportDialog.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiProgress from '@/components/ui/KiwiProgress.vue'
import { toast } from '@/components/ui/toast'

const route = useRoute()
const router = useRouter()
const kbs = useKbsStore()
const notesStore = useNotesStore()

// --------------------------------------------------------------------------- //
// 数据
// --------------------------------------------------------------------------- //
type Tab = 'sources' | 'batches' | 'jobs'
const tab = ref<Tab>('sources')
const sources = ref<SourceItem[]>([])
const batches = ref<ImportBatch[]>([])
const jobs = ref<IngestJob[]>([])
const loading = ref(false)
const error = ref('')
const lastLoaded = ref<Date | null>(null)
const importOpen = ref(false)

async function load(silent = false) {
  const kbId = kbs.currentKbId
  if (!kbId) {
    sources.value = []
    batches.value = []
    jobs.value = []
    return
  }
  if (!silent) loading.value = true
  try {
    const [s, b, j] = await Promise.all([
      listSources(kbId),
      listBatches(kbId),
      listJobs(kbId),
    ])
    sources.value = s
    batches.value = b
    jobs.value = j
    error.value = ''
  } catch (e: any) {
    if (!silent) error.value = e.message || '素材加载失败'
  } finally {
    loading.value = false
    lastLoaded.value = new Date()
    syncPolling()
  }
}

// 有进行中的任务 / 批次时自动轮询，结束后停止
const pollBoost = ref(false)
let boostTimer: number | null = null
let pollTimer: number | null = null

const activeJobs = computed(() =>
  jobs.value.filter((j) => j.status === 'pending' || j.status === 'running'),
)
const active = computed(
  () =>
    pollBoost.value ||
    activeJobs.value.length > 0 ||
    batches.value.some((b) => b.status === 'running') ||
    sources.value.some((s) => s.status === 'received' || s.status === 'parsing'),
)

function syncPolling() {
  if (active.value) {
    if (pollTimer === null) {
      pollTimer = window.setInterval(() => void load(true), 3500)
    }
  } else if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function boostPolling(ms = 15000) {
  pollBoost.value = true
  if (boostTimer !== null) window.clearTimeout(boostTimer)
  boostTimer = window.setTimeout(() => {
    pollBoost.value = false
    boostTimer = null
    syncPolling()
  }, ms)
  syncPolling()
}

watch(active, syncPolling)

watch(
  () => kbs.currentKbId,
  () => {
    selectedIds.value = []
    page.value = 1
    tab.value = 'sources'
    void load()
  },
)

onMounted(async () => {
  if (route.query.tab === 'jobs') tab.value = 'jobs'
  await load()
  await openJobFromRoute()
})
onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  if (boostTimer !== null) window.clearTimeout(boostTimer)
  stopJobPolling()
})

// --------------------------------------------------------------------------- //
// 素材筛选 / 分页 / 选择
// --------------------------------------------------------------------------- //
const query = ref('')
const statusFilter = ref('all')
const qualityFilter = ref('all')
const typeFilter = ref('all')
const batchFilter = ref('all')
const page = ref(1)
const PAGE_SIZE = 20
const selectedIds = ref<string[]>([])

const STATUS_FILTERS = [
  { value: 'all', label: '全部状态' },
  { value: 'received', label: '待处理' },
  { value: 'parsing', label: '解析中' },
  { value: 'parsed', label: '待编译' },
  { value: 'compiled', label: '已编译' },
  { value: 'failed', label: '解析失败' },
]

const QUALITY_FILTERS = [
  { value: 'all', label: '全部质量' },
  { value: 'clean', label: '解析干净' },
  { value: 'ocr_aided', label: 'OCR 辅助' },
  { value: 'review', label: '待人工复核' },
]

const typeOptions = computed(() => {
  const set = new Set(sources.value.map((s) => s.type))
  return Array.from(set).sort()
})

const batchLabelMap = computed(() => {
  const map = new Map<string, string>()
  for (const b of batches.value) {
    map.set(b.id, batchLabel(b))
  }
  return map
})

const filteredSources = computed(() => {
  const q = query.value.trim().toLowerCase()
  return sources.value.filter((s) => {
    if (q && !s.title.toLowerCase().includes(q) && !s.sha256.startsWith(q)) return false
    if (statusFilter.value !== 'all' && s.status !== statusFilter.value) return false
    if (qualityFilter.value !== 'all' && s.parse_quality !== qualityFilter.value) return false
    if (typeFilter.value !== 'all' && s.type !== typeFilter.value) return false
    if (batchFilter.value === 'none') return !s.import_batch_id
    if (batchFilter.value !== 'all' && s.import_batch_id !== batchFilter.value) return false
    return true
  })
})

const pageCount = computed(() =>
  Math.max(1, Math.ceil(filteredSources.value.length / PAGE_SIZE)),
)
const pagedSources = computed(() =>
  filteredSources.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE),
)
const pageAllSelected = computed(
  () =>
    pagedSources.value.length > 0 &&
    pagedSources.value.every((s) => selectedIds.value.includes(s.id)),
)

watch([query, statusFilter, qualityFilter, typeFilter, batchFilter], () => {
  page.value = 1
})
watch(pageCount, (count) => {
  if (page.value > count) page.value = count
})

const selectedSet = computed(() => new Set(selectedIds.value))

function toggleSelect(id: string) {
  if (selectedSet.value.has(id)) {
    selectedIds.value = selectedIds.value.filter((x) => x !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

function togglePage() {
  const ids = pagedSources.value.map((s) => s.id)
  if (pageAllSelected.value) {
    selectedIds.value = selectedIds.value.filter((id) => !ids.includes(id))
  } else {
    selectedIds.value = Array.from(new Set([...selectedIds.value, ...ids]))
  }
}

function clearSelection() {
  selectedIds.value = []
}

// --------------------------------------------------------------------------- //
// 统计
// --------------------------------------------------------------------------- //
const stats = computed(() => {
  const list = sources.value
  return {
    total: list.length,
    compiled: list.filter((s) => s.status === 'compiled').length,
    pending: list.filter((s) => s.status === 'parsed').length,
    processing: list.filter((s) => s.status === 'received' || s.status === 'parsing').length,
    review: list.filter((s) => s.parse_quality === 'review').length,
    failed: list.filter((s) => s.status === 'failed').length,
  }
})

const pendingIds = computed(() =>
  sources.value.filter((s) => s.status === 'parsed').map((s) => s.id),
)

// --------------------------------------------------------------------------- //
// 操作
// --------------------------------------------------------------------------- //
const compiling = ref(false)

/** 后端单次最多 20 个，前端按 20 分批提交。 */
async function compileIds(ids: string[]) {
  const kbId = kbs.currentKbId
  const unique = Array.from(new Set(ids))
  if (!kbId || !unique.length) return
  compiling.value = true
  let submitted = 0
  let skipped = 0
  try {
    for (let i = 0; i < unique.length; i += 20) {
      const res = await compileSources(kbId, unique.slice(i, i + 20))
      submitted += res.count
      skipped += res.skipped
    }
    toast.success(
      skipped
        ? `已提交 ${submitted} 个编译任务，${skipped} 个未提交`
        : `已提交 ${submitted} 个编译任务`,
    )
    clearSelection()
    boostPolling()
    await load(true)
  } catch (e: any) {
    toast.error(e.message || '编译任务提交失败')
  } finally {
    compiling.value = false
  }
}

function compileSelected() {
  void compileIds(selectedIds.value)
}

function compileAllPending() {
  if (!pendingIds.value.length) {
    toast.info('没有待编译的素材')
    return
  }
  void compileIds(pendingIds.value)
}

function compileBatch(b: ImportBatch) {
  const ids = batchSources(b.id)
    .filter((s) => s.status === 'parsed')
    .map((s) => s.id)
  if (!ids.length) {
    toast.info('该批次没有待编译的素材')
    return
  }
  reportBatch.value = null
  void compileIds(ids)
}

function preview(s: SourceItem) {
  void router.push({ name: 'source-preview', params: { id: s.id } })
}

interface ConfirmAsk {
  title: string
  message: string
  confirmText: string
  danger: boolean
  run: () => Promise<void>
}
const confirmAsk = ref<ConfirmAsk | null>(null)
const confirming = ref(false)

async function runConfirm() {
  if (!confirmAsk.value) return
  const ask = confirmAsk.value
  confirming.value = true
  try {
    await ask.run()
    confirmAsk.value = null
  } catch (e: any) {
    toast.error(e.message || '操作失败')
  } finally {
    confirming.value = false
  }
}

function askReparse(s: SourceItem) {
  confirmAsk.value = {
    title: '重新解析素材',
    message: `将重新解析「${s.title}」并重建向量索引。原文文件不会被修改，已有 Wiki 页面也不会被覆盖。`,
    confirmText: '重新解析',
    danger: false,
    run: async () => {
      if (!kbs.currentKbId) return
      await reparseSource(kbs.currentKbId, s.id)
      toast.success('已提交重新解析任务')
      boostPolling()
      await load(true)
    },
  }
}

function askDelete(s: SourceItem) {
  confirmAsk.value = {
    title: '删除素材',
    message: `「${s.title}」及其向量索引将被删除；由它编译的 Wiki 页面会保留。此操作不可撤销。`,
    confirmText: '删除',
    danger: true,
    run: async () => {
      if (!kbs.currentKbId) return
      await deleteSource(kbs.currentKbId, s.id)
      selectedIds.value = selectedIds.value.filter((id) => id !== s.id)
      toast.success('素材已删除')
      await load(true)
    },
  }
}

function askCancelBatch(b: ImportBatch) {
  confirmAsk.value = {
    title: '取消导入批次',
    message: `将中止「${batchLabel(b)}」中尚未完成的解析任务，已完成的素材会保留。`,
    confirmText: '取消批次',
    danger: true,
    run: async () => {
      if (!kbs.currentKbId) return
      await cancelBatch(kbs.currentKbId, b.id)
      toast.success('批次已取消')
      await load(true)
    },
  }
}

// --------------------------------------------------------------------------- //
// 批次
// --------------------------------------------------------------------------- //
const PROVIDER_META: Record<string, { label: string; icon: string }> = {
  upload: { label: '文件上传', icon: 'upload' },
  yuque_token: { label: '语雀令牌', icon: 'book' },
  yuque_zip: { label: '语雀导出包', icon: 'fileImport' },
}

const BATCH_STATUS_META: Record<
  string,
  { label: string; cls: string; progress: 'running' | 'done' | 'error' }
> = {
  running: { label: '进行中', cls: 'bg-amber-50 text-amber-700 border-amber-200', progress: 'running' },
  completed: { label: '已完成', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', progress: 'done' },
  partial: { label: '部分成功', cls: 'bg-amber-50 text-amber-700 border-amber-200', progress: 'done' },
  failed: { label: '失败', cls: 'bg-rose-50 text-rose-700 border-rose-200', progress: 'error' },
}

function providerOf(b: ImportBatch) {
  return PROVIDER_META[b.provider] || { label: b.provider, icon: 'fileText' }
}

function batchLabel(b: ImportBatch) {
  const label = String(b.report_json?.label || '').trim()
  if (label) return label
  return `${providerOf(b).label} · ${shortTime(b.created_at)}`
}

function batchSources(batchId: string) {
  return sources.value.filter((s) => s.import_batch_id === batchId)
}

interface BatchStat {
  total: number
  processed: number
  failed: number
  skipped: number
  compiled: number
  quality: Record<string, number>
}

function batchStat(b: ImportBatch): BatchStat {
  const report = (b.report_json || {}) as ImportBatchReport
  const list = batchSources(b.id)
  if (b.status !== 'running' && report.summary) {
    return {
      total: report.summary.total,
      processed: report.summary.processed,
      failed: report.summary.failed,
      skipped: report.summary.skipped,
      compiled: report.summary.compiled,
      quality: report.quality || qualityDist(list),
    }
  }
  const processed = list.filter((s) => s.status === 'parsed' || s.status === 'compiled').length
  const failed = list.filter((s) => s.status === 'failed').length
  const total = Math.max(b.total_sources, list.length, 0)
  return {
    total,
    processed,
    failed,
    skipped: b.skipped_count,
    compiled: list.filter((s) => s.status === 'compiled').length,
    quality: qualityDist(list),
  }
}

function qualityDist(list: SourceItem[]) {
  const dist: Record<string, number> = {}
  for (const s of list) {
    const key = s.parse_quality || 'unknown'
    dist[key] = (dist[key] || 0) + 1
  }
  return dist
}

function batchPercent(b: ImportBatch) {
  if (b.status === 'completed' || b.status === 'partial' || b.status === 'failed') return 100
  const stat = batchStat(b)
  if (!stat.total) return 0
  return Math.min(
    99,
    Math.round(((stat.processed + stat.failed + stat.skipped) / stat.total) * 100),
  )
}

function batchProgressStatus(b: ImportBatch) {
  return BATCH_STATUS_META[b.status]?.progress || 'running'
}

const runningBatches = computed(() => batches.value.filter((b) => b.status === 'running'))

// --------------------------------------------------------------------------- //
// 导入报告
// --------------------------------------------------------------------------- //
const reportBatch = ref<ImportBatch | null>(null)
const report = computed<ImportBatchReport>(
  () => (reportBatch.value?.report_json || {}) as ImportBatchReport,
)
const reportStat = computed(() =>
  reportBatch.value ? batchStat(reportBatch.value) : null,
)
const reportSources = computed(() => {
  const b = reportBatch.value
  if (!b) return []
  const fromReport = report.value.sources
  if (fromReport?.length) {
    return fromReport.map((s) => ({
      id: s.id,
      title: s.title,
      type: s.type,
      status: s.status,
      parse_quality: s.parse_quality,
      parse_engine: s.parse_engine,
      chars: s.chars || 0,
      warnings: s.warnings || [],
    }))
  }
  return batchSources(b.id).map((s) => ({
    id: s.id,
    title: s.title,
    type: s.type,
    status: s.status,
    parse_quality: s.parse_quality,
    parse_engine: s.parse_engine,
    chars: Number(s.quality_report?.chars || 0),
    warnings: Array.isArray(s.quality_report?.warnings)
      ? (s.quality_report.warnings as string[])
      : [],
  }))
})

function openReport(b: ImportBatch) {
  reportBatch.value = b
}

// --------------------------------------------------------------------------- //
// 文案 / 格式化
// --------------------------------------------------------------------------- //
const STATUS_META: Record<string, { label: string; cls: string; icon: string; spin?: boolean }> = {
  received: { label: '待处理', cls: 'bg-slate-100 text-slate-600 border-slate-200', icon: 'loader', spin: true },
  parsing: { label: '解析中', cls: 'bg-amber-50 text-amber-700 border-amber-200', icon: 'loader', spin: true },
  parsed: { label: '待编译', cls: 'bg-kiwi-50 text-kiwi-700 border-kiwi-200', icon: 'bookOpen' },
  compiled: { label: '已编译', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', icon: 'check' },
  failed: { label: '解析失败', cls: 'bg-rose-50 text-rose-700 border-rose-200', icon: 'alert' },
}

const QUALITY_META: Record<string, { label: string; cls: string }> = {
  clean: { label: '解析干净', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  ocr_aided: { label: 'OCR 辅助', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  review: { label: '待复核', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
  unknown: { label: '未知', cls: 'bg-slate-100 text-slate-500 border-slate-200' },
}

const SCAN_LABEL: Record<string, string> = {
  clean: '安全扫描通过',
  heuristic: '启发式检测通过',
  unavailable: '未启用扫描',
  infected: '发现威胁',
  error: '扫描异常',
}

function statusMeta(status: string) {
  return STATUS_META[status] || { label: status, cls: 'bg-slate-100 text-slate-500 border-slate-200', icon: 'fileText' }
}

function qualityMeta(quality: string) {
  return QUALITY_META[quality] || QUALITY_META.unknown
}

function qualityLabel(key: string) {
  return QUALITY_META[key]?.label || key
}

function typeLabel(type: string) {
  return (type || 'unknown').toUpperCase()
}

function charsOf(s: SourceItem) {
  const n = Number(s.quality_report?.chars || 0)
  return n > 0 ? `${n.toLocaleString()} 字` : '—'
}

function shortTime(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleString('zh-CN', {
    ...(sameYear ? {} : { year: 'numeric' }),
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function timeLabel(iso: string | null) {
  return iso ? new Date(iso).toLocaleString('zh-CN') : '—'
}

function durationLabel(b: ImportBatch) {
  const seconds = Number(b.report_json?.duration_seconds || 0)
  if (!seconds) return '—'
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  return `${(seconds / 60).toFixed(1)} 分钟`
}

function batchSourceIds(b: ImportBatch) {
  return batchSources(b.id).map((s) => s.id)
}

// --------------------------------------------------------------------------- //
// 编译任务：列表、执行阶段与详情
// --------------------------------------------------------------------------- //
const JOB_STATUS_META: Record<
  string,
  { label: string; cls: string; progress: 'running' | 'done' | 'error' }
> = {
  pending: {
    label: '排队中',
    cls: 'border-slate-200 bg-slate-50 text-slate-500',
    progress: 'running',
  },
  running: {
    label: '执行中',
    cls: 'border-kiwi-200 bg-kiwi-50 text-kiwi-700',
    progress: 'running',
  },
  succeeded: {
    label: '已完成',
    cls: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    progress: 'done',
  },
  failed: {
    label: '失败',
    cls: 'border-rose-200 bg-rose-50 text-rose-600',
    progress: 'error',
  },
}

function jobStatusMeta(job: IngestJob) {
  return (
    JOB_STATUS_META[job.status] || {
      label: job.status,
      cls: 'border-slate-200 bg-slate-50 text-slate-500',
      progress: 'done' as const,
    }
  )
}

function jobKindLabel(job: IngestJob) {
  if (job.kind === 'compile') return job.note_id ? '笔记编译' : '素材编译'
  if (job.kind === 'reparse') return '重新解析'
  if (job.kind === 'import') return '导入解析'
  return job.kind
}

function jobKindIcon(job: IngestJob) {
  if (job.kind === 'compile') return 'sparkle'
  if (job.kind === 'reparse') return 'refresh'
  return 'fileImport'
}

function jobTitle(job: IngestJob) {
  return job.note_title || job.source_title || '未知来源'
}

function jobPageCount(job: IngestJob) {
  if (job.touched_pages?.length) return job.touched_pages.length
  return job.touched_page_ids?.length || 0
}

function jobDuration(job: IngestJob) {
  if (!job.updated_at) return '—'
  const seconds = Math.max(
    0,
    Math.round(
      (new Date(job.updated_at).getTime() - new Date(job.created_at).getTime()) / 1000,
    ),
  )
  if (seconds < 60) return `${seconds} 秒`
  return `${(seconds / 60).toFixed(1)} 分钟`
}

const COMPILE_STEPS = [
  { at: 0.05, label: '读取内容', hint: '解析原始素材 / 笔记正文' },
  { at: 0.3, label: '切分知识块', hint: '按标题与段落生成 chunk' },
  { at: 0.6, label: '向量化', hint: '写入原始素材检索索引' },
  { at: 0.8, label: '生成 Wiki', hint: 'LLM 抽取概念并合并页面' },
  { at: 1, label: '完成', hint: '更新双向链接与页面索引' },
]

function jobSteps(job: IngestJob) {
  const progress = Number(job.progress || 0)
  const failed = job.status === 'failed'
  return COMPILE_STEPS.map((step, index) => {
    const next = COMPILE_STEPS[index + 1]?.at ?? 1.01
    let state: 'done' | 'active' | 'todo' | 'failed' = 'todo'
    if (job.status === 'succeeded') state = 'done'
    else if (progress >= next) state = 'done'
    else if (progress >= step.at || index === 0) {
      state = failed ? 'failed' : job.status === 'pending' ? 'todo' : 'active'
    }
    return { ...step, state }
  })
}

const jobDetail = ref<IngestJob | null>(null)
const jobLoading = ref(false)
let jobPollTimer: number | null = null

function stopJobPolling() {
  if (jobPollTimer !== null) {
    window.clearTimeout(jobPollTimer)
    jobPollTimer = null
  }
}

async function refreshJobDetail(jobId: string) {
  const kbId = kbs.currentKbId
  if (!kbId) return
  try {
    const data = await getJob(kbId, jobId)
    jobDetail.value = data
    if (data.status === 'pending' || data.status === 'running') {
      stopJobPolling()
      jobPollTimer = window.setTimeout(() => void refreshJobDetail(jobId), 2000)
    }
  } catch (e: any) {
    toast.error(e.message || '任务详情加载失败')
  } finally {
    jobLoading.value = false
  }
}

async function openJob(job: IngestJob) {
  stopJobPolling()
  jobDetail.value = job
  jobLoading.value = true
  await refreshJobDetail(job.id)
}

function closeJob() {
  stopJobPolling()
  jobDetail.value = null
  jobLoading.value = false
}

async function openJobFromRoute() {
  const jobId = typeof route.query.job === 'string' ? route.query.job : ''
  if (!jobId) return
  tab.value = 'jobs'
  const cached = jobs.value.find((job) => job.id === jobId)
  if (cached) {
    await openJob(cached)
    return
  }
  const kbId = kbs.currentKbId
  if (!kbId) return
  jobLoading.value = true
  jobDetail.value = null
  await refreshJobDetail(jobId)
}

watch(
  () => route.query.job,
  () => void openJobFromRoute(),
)

const compilingNotes = ref(false)

async function compileAllNotes() {
  if (!kbs.currentKbId) return
  compilingNotes.value = true
  try {
    const res = await notesStore.compileAllNotes(20)
    if (res.count) {
      toast.success(`已提交 ${res.count} 个笔记编译任务`)
      tab.value = 'jobs'
      boostPolling()
      await load(true)
    } else if (res.skipped_busy) {
      toast.info(`${res.skipped_busy} 篇笔记正在编译中，请稍后查看任务`)
      tab.value = 'jobs'
    } else {
      toast.info('没有需要编译的笔记')
    }
  } catch (e: any) {
    toast.error(e.message || '提交笔记编译失败')
  } finally {
    compilingNotes.value = false
  }
}
</script>

<template>
  <div class="mx-auto flex h-full max-w-[1440px] flex-col px-5 py-4">
    <!-- 标题栏 -->
    <header class="mb-3 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-[19px] font-semibold tracking-tight text-slate-800">素材与任务</h1>
        <p class="mt-0.5 text-[11.5px] text-slate-400">
          原始素材不可变 · 统一管理解析质量、安全扫描、导入批次与编译任务
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="lastLoaded" class="mr-1 hidden text-[10.5px] text-slate-400 sm:inline">
          更新于 {{ lastLoaded.toLocaleTimeString('zh-CN') }}
        </span>
        <button
          type="button"
          class="kiwi-btn-secondary !px-3 !py-1.5 !text-[12px]"
          :disabled="loading"
          @click="load()"
        >
          <KiwiIcon name="refresh" :size="13" :spin="loading" />
          刷新
        </button>
        <button
          type="button"
          class="kiwi-btn-primary !px-3 !py-1.5 !text-[12px]"
          :disabled="!kbs.currentKbId"
          @click="importOpen = true"
        >
          <KiwiIcon name="fileImport" :size="13" />
          导入素材
        </button>
      </div>
    </header>

    <div v-if="!kbs.currentKbId" class="flex-1 grid place-items-center">
      <KiwiEmpty icon="database" title="请先选择知识库" desc="素材与导入批次按知识库隔离" />
    </div>

    <template v-else>
      <!-- 统计卡片 -->
      <div class="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="bookOpen" :size="12" class="text-slate-400" />
            素材总数
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-slate-800">
            {{ stats.total }}
          </p>
          <p class="mt-1 text-[10px] text-slate-400">
            {{ stats.processing ? `${stats.processing} 个处理中` : '原文不可变' }}
          </p>
        </div>
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="check" :size="12" class="text-emerald-500" />
            已编译
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-emerald-700">
            {{ stats.compiled }}
          </p>
          <p class="mt-1 text-[10px] text-slate-400">已沉淀为 Wiki 页面</p>
        </div>
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="book" :size="12" class="text-kiwi-500" />
            待编译
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-kiwi-700">
            {{ stats.pending }}
          </p>
          <button
            v-if="stats.pending"
            type="button"
            class="mt-1 text-[10px] text-kiwi-600 hover:underline disabled:opacity-40"
            :disabled="compiling"
            @click="compileAllPending"
          >
            全部编译 →
          </button>
          <p v-else class="mt-1 text-[10px] text-slate-400">没有积压</p>
        </div>
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="alert" :size="12" class="text-amber-500" />
            待人工复核
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-amber-700">
            {{ stats.review }}
          </p>
          <p class="mt-1 text-[10px] text-slate-400">低置信度 OCR / 表格异常</p>
        </div>
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="trash" :size="12" class="text-rose-400" />
            解析失败
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-rose-600">
            {{ stats.failed }}
          </p>
          <button
            v-if="stats.failed"
            type="button"
            class="mt-1 text-[10px] text-rose-500 hover:underline"
            @click="statusFilter = 'failed'; tab = 'sources'"
          >
            查看失败素材 →
          </button>
          <p v-else class="mt-1 text-[10px] text-slate-400">解析链路正常</p>
        </div>
      </div>

      <!-- 进行中的批次 -->
      <div
        v-for="b in runningBatches"
        :key="b.id"
        class="mb-2 flex items-center gap-3 rounded-xl border border-kiwi-200/70 bg-kiwi-50/60 px-3.5 py-2"
      >
        <KiwiIcon name="loader" :size="14" spin class="shrink-0 text-kiwi-600" />
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <p class="truncate text-[11.5px] font-medium text-slate-700">
              正在导入「{{ batchLabel(b) }}」
            </p>
            <span class="shrink-0 text-[10.5px] tabular-nums text-kiwi-700">
              {{ batchPercent(b) }}%
            </span>
          </div>
          <KiwiProgress class="mt-1" :value="batchPercent(b) / 100" status="running" />
        </div>
        <button
          type="button"
          class="shrink-0 text-[10.5px] text-slate-500 hover:text-rose-600"
          @click="askCancelBatch(b)"
        >
          取消
        </button>
      </div>

      <!-- 页签 -->
      <div class="mb-2.5 flex items-center gap-1 border-b border-slate-200/70">
        <button
          v-for="t in [
            { key: 'sources', label: '素材库', count: sources.length },
            { key: 'batches', label: '导入批次', count: batches.length },
            { key: 'jobs', label: '编译任务', count: jobs.length },
          ]"
          :key="t.key"
          type="button"
          class="relative px-3 py-2 text-[12.5px] font-medium transition-colors"
          :class="tab === t.key ? 'text-kiwi-700' : 'text-slate-400 hover:text-slate-600'"
          @click="tab = t.key as Tab"
        >
          {{ t.label }}
          <span
            class="ml-1 rounded-full px-1.5 py-0.5 text-[9.5px] tabular-nums"
            :class="tab === t.key ? 'bg-kiwi-100 text-kiwi-700' : 'bg-slate-100 text-slate-400'"
          >
            {{ t.count }}
          </span>
          <span
            v-if="tab === t.key"
            class="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-kiwi-500"
          />
        </button>
        <p v-if="error" class="ml-auto text-[11px] text-rose-500">{{ error }}</p>
      </div>

      <!-- 素材库 -->
      <template v-if="tab === 'sources'">
        <div class="mb-2 flex flex-wrap items-center gap-1.5">
          <div class="relative min-w-[190px] max-w-[280px] flex-1">
            <KiwiIcon
              name="search"
              :size="13"
              class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400"
            />
            <input
              v-model="query"
              type="search"
              placeholder="搜索标题 / 指纹…"
              class="kiwi-input !py-1.5 !pl-8 !text-[11.5px]"
            />
          </div>
          <select v-model="statusFilter" class="sources-select">
            <option v-for="o in STATUS_FILTERS" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <select v-model="qualityFilter" class="sources-select">
            <option v-for="o in QUALITY_FILTERS" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <select v-model="typeFilter" class="sources-select">
            <option value="all">全部类型</option>
            <option v-for="t in typeOptions" :key="t" :value="t">{{ typeLabel(t) }}</option>
          </select>
          <select v-model="batchFilter" class="sources-select max-w-[190px]">
            <option value="all">全部批次</option>
            <option value="none">未归属批次</option>
            <option v-for="b in batches" :key="b.id" :value="b.id">
              {{ batchLabelMap.get(b.id) }}
            </option>
          </select>

          <div class="ml-auto flex items-center gap-1.5">
            <button
              v-if="selectedIds.length"
              type="button"
              class="text-[10.5px] text-slate-400 hover:text-slate-600"
              @click="clearSelection"
            >
              已选 {{ selectedIds.length }} · 清除
            </button>
            <button
              type="button"
              class="kiwi-btn-secondary !px-2.5 !py-1.5 !text-[11px]"
              :disabled="!selectedIds.length || compiling"
              @click="compileSelected"
            >
              <KiwiIcon name="play" :size="12" />
              编译所选
            </button>
          </div>
        </div>

        <div class="kiwi-card flex min-h-0 flex-1 flex-col overflow-hidden !rounded-xl">
          <div class="min-h-0 flex-1 overflow-auto">
            <table class="w-full min-w-[940px] border-collapse text-left text-[11.5px]">
              <thead class="sticky top-0 z-10 bg-slate-50/95 text-[10.5px] text-slate-500 backdrop-blur">
                <tr>
                  <th class="w-9 px-3 py-2">
                    <input
                      type="checkbox"
                      :checked="pageAllSelected"
                      class="h-3.5 w-3.5 rounded border-slate-300 accent-kiwi-600"
                      @change="togglePage"
                    />
                  </th>
                  <th class="px-2 py-2 font-medium">素材</th>
                  <th class="px-2 py-2 font-medium">类型</th>
                  <th class="px-2 py-2 font-medium">状态</th>
                  <th class="px-2 py-2 font-medium">解析质量</th>
                  <th class="px-2 py-2 font-medium">解析引擎</th>
                  <th class="px-2 py-2 font-medium">批次</th>
                  <th class="px-2 py-2 font-medium">导入时间</th>
                  <th class="w-24 px-2 py-2 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="loading && !sources.length">
                  <td colspan="9" class="px-4 py-12 text-center text-slate-400">
                    <span class="inline-flex items-center gap-2">
                      <KiwiIcon name="loader" :size="14" spin class="text-kiwi-500" />
                      正在加载素材…
                    </span>
                  </td>
                </tr>
                <tr v-else-if="!filteredSources.length">
                  <td colspan="9" class="px-4 py-12 text-center">
                    <p class="text-[12px] text-slate-500">
                      {{ sources.length ? '没有符合筛选条件的素材' : '还没有素材' }}
                    </p>
                    <p class="mt-1 text-[10.5px] text-slate-400">
                      {{ sources.length ? '试试调整搜索或筛选条件' : '点击右上角「导入素材」上传文件或迁移语雀文档' }}
                    </p>
                  </td>
                </tr>
                <tr
                  v-for="s in pagedSources"
                  v-else
                  :key="s.id"
                  class="border-t border-slate-100 transition-colors hover:bg-kiwi-50/40"
                  :class="selectedSet.has(s.id) && 'bg-kiwi-50/50'"
                >
                  <td class="px-3 py-2 align-top">
                    <input
                      type="checkbox"
                      :checked="selectedSet.has(s.id)"
                      class="mt-0.5 h-3.5 w-3.5 rounded border-slate-300 accent-kiwi-600"
                      @change="toggleSelect(s.id)"
                    />
                  </td>
                  <td class="max-w-[300px] px-2 py-2">
                    <div class="flex items-center gap-1.5">
                      <KiwiIcon name="fileText" :size="13" class="shrink-0 text-slate-400" />
                      <button
                        type="button"
                        class="truncate text-left font-medium text-slate-700 hover:text-kiwi-600"
                        :title="s.title"
                        @click="preview(s)"
                      >
                        {{ s.title }}
                      </button>
                      <a
                        v-if="s.source_url"
                        :href="s.source_url"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="shrink-0 text-slate-400 hover:text-kiwi-500"
                        title="打开原始链接"
                      >
                        <KiwiIcon name="external" :size="11" />
                      </a>
                    </div>
                    <p class="mt-0.5 truncate font-mono text-[9.5px] text-slate-400">
                      {{ s.sha256.slice(0, 10) }} · {{ charsOf(s) }}
                      <span v-if="s.scan_status && s.scan_status !== 'clean'">
                        · {{ SCAN_LABEL[s.scan_status] || s.scan_status }}
                      </span>
                    </p>
                    <p
                      v-if="s.status === 'failed'"
                      class="mt-0.5 line-clamp-1 text-[10px] text-rose-500"
                    >
                      {{ s.quality_report?.error || '解析失败，可尝试重新解析' }}
                    </p>
                  </td>
                  <td class="px-2 py-2 align-top">
                    <span class="rounded-md bg-slate-100 px-1.5 py-0.5 text-[9.5px] font-semibold text-slate-500">
                      {{ typeLabel(s.type) }}
                    </span>
                  </td>
                  <td class="px-2 py-2 align-top">
                    <span
                      class="inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px]"
                      :class="statusMeta(s.status).cls"
                    >
                      <KiwiIcon
                        :name="statusMeta(s.status).icon"
                        :size="10"
                        :spin="statusMeta(s.status).spin"
                      />
                      {{ statusMeta(s.status).label }}
                    </span>
                  </td>
                  <td class="px-2 py-2 align-top">
                    <span
                      class="rounded-full border px-1.5 py-0.5 text-[10px]"
                      :class="qualityMeta(s.parse_quality).cls"
                    >
                      {{ qualityMeta(s.parse_quality).label }}
                    </span>
                  </td>
                  <td class="whitespace-nowrap px-2 py-2 align-top text-[10.5px] text-slate-500">
                    {{ s.parse_engine || '—' }}
                  </td>
                  <td class="max-w-[150px] px-2 py-2 align-top">
                    <span
                      class="block truncate text-[10.5px] text-slate-500"
                      :title="s.import_batch_id ? batchLabelMap.get(s.import_batch_id) : '未归属批次'"
                    >
                      {{ (s.import_batch_id && batchLabelMap.get(s.import_batch_id)) || '—' }}
                    </span>
                  </td>
                  <td class="whitespace-nowrap px-2 py-2 align-top text-[10.5px] text-slate-500">
                    {{ shortTime(s.created_at) }}
                  </td>
                  <td class="px-2 py-2 align-top">
                    <div class="flex items-center justify-end gap-0.5">
                      <button
                        type="button"
                        class="row-action"
                        title="查看原文"
                        @click="preview(s)"
                      >
                        <KiwiIcon name="arrowUpRight" :size="13" />
                      </button>
                      <button
                        type="button"
                        class="row-action"
                        title="编译该素材"
                        :disabled="compiling || s.status === 'received' || s.status === 'parsing'"
                        @click="compileIds([s.id])"
                      >
                        <KiwiIcon name="play" :size="12" />
                      </button>
                      <button
                        type="button"
                        class="row-action"
                        title="重新解析"
                        @click="askReparse(s)"
                      >
                        <KiwiIcon name="refresh" :size="12" />
                      </button>
                      <button
                        type="button"
                        class="row-action hover:!text-rose-600"
                        title="删除素材"
                        @click="askDelete(s)"
                      >
                        <KiwiIcon name="trash" :size="12" />
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 分页 -->
          <div
            v-if="filteredSources.length"
            class="flex shrink-0 items-center justify-between border-t border-slate-100 bg-white/60 px-3 py-1.5 text-[10.5px] text-slate-500"
          >
            <span>
              共 {{ filteredSources.length }} 条
              <template v-if="filteredSources.length !== sources.length">
                （全部 {{ sources.length }} 条）
              </template>
              · 第 {{ page }} / {{ pageCount }} 页
            </span>
            <div class="flex items-center gap-1">
              <button
                type="button"
                class="rounded-md border border-slate-200 bg-white px-2 py-1 disabled:opacity-40"
                :disabled="page <= 1"
                @click="page--"
              >
                上一页
              </button>
              <button
                type="button"
                class="rounded-md border border-slate-200 bg-white px-2 py-1 disabled:opacity-40"
                :disabled="page >= pageCount"
                @click="page++"
              >
                下一页
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- 导入批次 -->
      <template v-else-if="tab === 'batches'">
        <div v-if="loading && !batches.length" class="py-14 text-center text-[12px] text-slate-400">
          <span class="inline-flex items-center gap-2">
            <KiwiIcon name="loader" :size="14" spin class="text-kiwi-500" />
            正在加载批次…
          </span>
        </div>
        <div v-else-if="!batches.length" class="flex-1 grid place-items-center">
          <KiwiEmpty
            icon="fileImport"
            title="还没有导入批次"
            desc="每次文件上传或语雀迁移都会生成一个批次，并在完成后产出导入报告。"
          >
            <button class="kiwi-btn-primary" @click="importOpen = true">
              <KiwiIcon name="fileImport" :size="14" />
              导入素材
            </button>
          </KiwiEmpty>
        </div>
        <div v-else class="min-h-0 flex-1 space-y-2 overflow-y-auto pb-2">
          <article
            v-for="b in batches"
            :key="b.id"
            class="rounded-xl border border-slate-200/70 bg-white/70 px-4 py-3 shadow-soft backdrop-blur transition-colors hover:border-kiwi-200"
          >
            <div class="flex flex-wrap items-start gap-3">
              <div
                class="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-kiwi-100 bg-gradient-to-br from-kiwi-50 to-white text-kiwi-500"
              >
                <KiwiIcon :name="providerOf(b).icon" :size="16" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <h3 class="truncate text-[13px] font-medium text-slate-800">{{ batchLabel(b) }}</h3>
                  <span
                    class="rounded-full border px-1.5 py-0.5 text-[9.5px]"
                    :class="BATCH_STATUS_META[b.status]?.cls"
                  >
                    {{ BATCH_STATUS_META[b.status]?.label || b.status }}
                  </span>
                  <span
                    v-if="b.status === 'running' && b.report_json?.closed"
                    class="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9.5px] text-slate-500"
                  >
                    已停止接收新文档
                  </span>
                </div>
                <p class="mt-0.5 text-[10.5px] text-slate-400">
                  {{ providerOf(b).label }} · {{ timeLabel(b.created_at) }}
                  <template v-if="b.status !== 'running'"> · 用时 {{ durationLabel(b) }}</template>
                  <template v-if="b.error"> · <span class="text-rose-500">{{ b.error }}</span></template>
                </p>
              </div>
              <div class="flex shrink-0 items-center gap-1.5">
                <button
                  type="button"
                  class="kiwi-btn-ghost !px-2 !py-1 !text-[11px]"
                  @click="openReport(b)"
                >
                  <KiwiIcon name="fileText" :size="12" />
                  导入报告
                </button>
                <button
                  type="button"
                  class="kiwi-btn-secondary !px-2 !py-1 !text-[11px]"
                  :disabled="compiling || !batchSourceIds(b).length"
                  @click="compileBatch(b)"
                >
                  <KiwiIcon name="play" :size="11" />
                  编译本批
                </button>
                <button
                  v-if="b.status === 'running'"
                  type="button"
                  class="kiwi-btn-ghost !px-2 !py-1 !text-[11px] hover:!text-rose-600"
                  @click="askCancelBatch(b)"
                >
                  取消
                </button>
              </div>
            </div>

            <div class="mt-2.5 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
              <div class="rounded-lg bg-slate-50/80 px-2.5 py-1.5">
                <p class="text-[9.5px] text-slate-400">成功入库</p>
                <p class="text-[15px] font-semibold leading-tight tabular-nums text-emerald-700">
                  {{ batchStat(b).processed }}
                </p>
              </div>
              <div class="rounded-lg bg-slate-50/80 px-2.5 py-1.5">
                <p class="text-[9.5px] text-slate-400">失败</p>
                <p class="text-[15px] font-semibold leading-tight tabular-nums text-rose-600">
                  {{ batchStat(b).failed }}
                </p>
              </div>
              <div class="rounded-lg bg-slate-50/80 px-2.5 py-1.5">
                <p class="text-[9.5px] text-slate-400">跳过（内容未变）</p>
                <p class="text-[15px] font-semibold leading-tight tabular-nums text-slate-500">
                  {{ batchStat(b).skipped }}
                </p>
              </div>
              <div class="rounded-lg bg-slate-50/80 px-2.5 py-1.5">
                <p class="text-[9.5px] text-slate-400">已编译</p>
                <p class="text-[15px] font-semibold leading-tight tabular-nums text-kiwi-700">
                  {{ batchStat(b).compiled }}
                </p>
              </div>
            </div>

            <div class="mt-2.5 flex items-center gap-2.5">
              <KiwiProgress
                class="flex-1"
                :value="batchPercent(b) / 100"
                :status="batchProgressStatus(b)"
              />
              <span class="w-16 text-right text-[10px] tabular-nums text-slate-500">
                {{ batchStat(b).processed + batchStat(b).failed + batchStat(b).skipped }}
                / {{ batchStat(b).total || '—' }}
              </span>
            </div>

            <div class="mt-2 flex flex-wrap items-center gap-1.5">
              <span class="text-[9.5px] text-slate-400">解析质量</span>
              <span
                v-for="(count, key) in batchStat(b).quality"
                :key="key"
                class="rounded-full border px-1.5 py-0.5 text-[9.5px]"
                :class="qualityMeta(String(key)).cls"
              >
                {{ qualityLabel(String(key)) }} {{ count }}
              </span>
              <span
                v-if="!Object.keys(batchStat(b).quality).length"
                class="text-[9.5px] text-slate-400"
              >
                等待解析结果
              </span>
              <span
                v-if="b.report_json?.summary?.total"
                class="ml-auto text-[9.5px] text-slate-400"
              >
                报告共 {{ b.report_json.summary.total }} 条
              </span>
            </div>
          </article>
        </div>
      </template>

      <!-- 编译任务：导入 / 重解析 / 笔记编译统一时间线 -->
      <template v-else>
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <p class="text-[10.5px] text-slate-400">
            最近 100 个任务 · 点击查看执行阶段、错误与受影响的 Wiki 页面
          </p>
          <span
            v-if="activeJobs.length"
            class="inline-flex items-center gap-1 rounded-full border border-kiwi-200 bg-kiwi-50 px-2 py-0.5 text-[9.5px] text-kiwi-700"
          >
            <KiwiIcon name="loader" :size="9" spin />
            {{ activeJobs.length }} 个执行中
          </span>
          <div class="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              class="kiwi-btn-secondary !px-2.5 !py-1 !text-[11px]"
              :disabled="compilingNotes || !kbs.currentKbId"
              @click="compileAllNotes"
            >
              <KiwiIcon :name="compilingNotes ? 'loader' : 'sparkle'" :size="12" :spin="compilingNotes" />
              编译全部笔记
            </button>
            <button
              type="button"
              class="kiwi-btn-ghost !px-2 !py-1 !text-[11px]"
              :disabled="loading"
              @click="load(true)"
            >
              <KiwiIcon name="refresh" :size="12" :spin="loading" />
              刷新
            </button>
          </div>
        </div>

        <div class="min-h-0 flex-1 space-y-2 overflow-y-auto pb-2">
          <div v-if="loading && !jobs.length" class="py-14 text-center text-[12px] text-slate-400">
            <span class="inline-flex items-center gap-2">
              <KiwiIcon name="loader" :size="14" spin class="text-kiwi-500" />
              正在加载任务…
            </span>
          </div>
          <div v-else-if="!jobs.length" class="flex-1 grid place-items-center">
            <KiwiEmpty
              icon="sparkle"
              title="还没有编译任务"
              desc="导入素材、重新解析或编译笔记后，这里会记录每一步执行细节。"
            >
              <button
                class="kiwi-btn-primary"
                :disabled="compilingNotes"
                @click="compileAllNotes"
              >
                <KiwiIcon name="sparkle" :size="14" />
                编译全部笔记
              </button>
            </KiwiEmpty>
          </div>
          <button
            v-for="job in jobs"
            :key="job.id"
            type="button"
            class="block w-full rounded-xl border border-slate-200/70 bg-white/70 px-3.5 py-2.5 text-left shadow-soft backdrop-blur transition-colors hover:border-kiwi-200"
            @click="openJob(job)"
          >
            <div class="flex flex-wrap items-center gap-2">
              <span
                class="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-kiwi-100 bg-gradient-to-br from-kiwi-50 to-white text-kiwi-500"
              >
                <KiwiIcon :name="jobKindIcon(job)" :size="13" />
              </span>
              <span class="min-w-0 flex-1 truncate text-[12.5px] font-medium text-slate-700">
                {{ jobTitle(job) }}
              </span>
              <span class="rounded-full border px-1.5 py-0.5 text-[9.5px]" :class="jobStatusMeta(job).cls">
                {{ jobStatusMeta(job).label }}
              </span>
              <span class="text-[10px] tabular-nums text-slate-400">
                {{ Math.round((job.progress || 0) * 100) }}%
              </span>
            </div>
            <div class="mt-1.5 flex items-center gap-2">
              <KiwiProgress
                class="flex-1"
                :value="job.progress || 0"
                :status="jobStatusMeta(job).progress"
              />
              <span class="shrink-0 text-[9.5px] text-slate-400">
                {{ jobKindLabel(job) }} · {{ jobPageCount(job) }} 页 · {{ timeLabel(job.created_at) }}
              </span>
            </div>
            <p v-if="job.error" class="mt-1 truncate text-[10px] text-rose-500">
              {{ job.error }}
            </p>
          </button>
        </div>
      </template>
    </template>

    <!-- 导入弹窗（复用笔记工作区导入中心） -->
    <NoteImportDialog
      :open="importOpen"
      @close="importOpen = false"
      @created="importOpen = false; load(true)"
    />

    <!-- 编译任务详情 -->
    <KiwiModal
      :open="!!jobDetail"
      title="编译任务详情"
      max-w="max-w-2xl"
      @close="closeJob"
    >
      <div v-if="jobDetail" class="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
        <div class="rounded-xl border border-slate-200/70 bg-slate-50/70 px-3.5 py-3">
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-kiwi-100 bg-white text-kiwi-500"
            >
              <KiwiIcon :name="jobKindIcon(jobDetail)" :size="15" />
            </span>
            <p class="min-w-0 flex-1 truncate text-[13px] font-semibold text-slate-800">
              {{ jobTitle(jobDetail) }}
            </p>
            <span
              class="rounded-full border px-1.5 py-0.5 text-[9.5px]"
              :class="jobStatusMeta(jobDetail).cls"
            >
              {{ jobStatusMeta(jobDetail).label }}
            </span>
          </div>
          <div class="mt-2 grid gap-x-4 gap-y-1 text-[10.5px] text-slate-500 sm:grid-cols-2">
            <p>任务类型：{{ jobKindLabel(jobDetail) }}</p>
            <p>来源：{{ jobDetail.note_title ? '工作区笔记' : jobDetail.source_type === 'note' ? '内部笔记快照' : '导入素材' }}</p>
            <p>创建时间：{{ timeLabel(jobDetail.created_at) }}</p>
            <p>用时：{{ jobDuration(jobDetail) }}</p>
            <p class="sm:col-span-2 truncate font-mono text-[9.5px] text-slate-400">
              job {{ jobDetail.id }}
            </p>
          </div>
        </div>

        <div>
          <div class="flex items-center justify-between text-[10.5px] text-slate-500">
            <span>总进度</span>
            <span class="tabular-nums">{{ Math.round((jobDetail.progress || 0) * 100) }}%</span>
          </div>
          <KiwiProgress
            class="mt-1"
            :value="jobDetail.progress || 0"
            :status="jobStatusMeta(jobDetail).progress"
          />
          <div
            v-if="jobDetail.error"
            class="mt-2 rounded-lg border border-rose-200/70 bg-rose-50/60 px-2.5 py-2 text-[10.5px] leading-relaxed text-rose-600"
          >
            {{ jobDetail.error }}
          </div>
        </div>

        <div>
          <p class="text-[10.5px] font-semibold uppercase tracking-wide text-slate-400">
            执行阶段
          </p>
          <ol class="mt-2 space-y-2">
            <li
              v-for="step in jobSteps(jobDetail)"
              :key="step.label"
              class="flex items-start gap-2.5"
            >
              <span
                class="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border"
                :class="
                  step.state === 'done'
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-600'
                    : step.state === 'failed'
                      ? 'border-rose-200 bg-rose-50 text-rose-500'
                      : step.state === 'active'
                        ? 'border-kiwi-200 bg-kiwi-50 text-kiwi-600'
                        : 'border-slate-200 bg-white text-slate-300'
                "
              >
                <KiwiIcon
                  :name="
                    step.state === 'done'
                      ? 'check'
                      : step.state === 'failed'
                        ? 'close'
                        : step.state === 'active'
                          ? 'loader'
                          : 'circle'
                  "
                  :size="10"
                  :spin="step.state === 'active'"
                />
              </span>
              <div class="min-w-0 flex-1">
                <p
                  class="text-[11.5px]"
                  :class="step.state === 'todo' ? 'text-slate-400' : 'font-medium text-slate-700'"
                >
                  {{ step.label }}
                </p>
                <p class="text-[10px] text-slate-400">{{ step.hint }}</p>
              </div>
              <span class="mt-0.5 text-[9.5px] tabular-nums text-slate-300">
                {{ Math.round(step.at * 100) }}%
              </span>
            </li>
          </ol>
        </div>

        <div>
          <p class="text-[10.5px] font-semibold uppercase tracking-wide text-slate-400">
            受影响的 Wiki 页面 · {{ jobPageCount(jobDetail) }}
          </p>
          <div v-if="jobDetail.touched_pages?.length" class="mt-2 space-y-1">
            <button
              v-for="page in jobDetail.touched_pages"
              :key="page.id"
              type="button"
              class="flex w-full items-center gap-2 rounded-lg border border-slate-200/70 bg-white/70 px-2.5 py-1.5 text-left transition-colors hover:border-kiwi-200 hover:bg-kiwi-50/40"
              @click="closeJob(); router.push(`/wiki/${page.id}`)"
            >
              <KiwiIcon name="wiki" :size="12" class="shrink-0 text-kiwi-400" />
              <span class="min-w-0 flex-1 truncate text-[11.5px] text-slate-600">
                {{ page.title }}
              </span>
              <span
                v-if="page.slug !== page.title"
                class="shrink-0 font-mono text-[9px] text-slate-300"
              >
                slug:{{ page.slug }}
              </span>
              <KiwiIcon name="arrowUpRight" :size="11" class="shrink-0 text-slate-300" />
            </button>
          </div>
          <p v-else class="mt-1.5 text-[10.5px] text-slate-400">
            该任务尚未产生页面变更（编译中或没有可沉淀的新知识）。
          </p>
        </div>

        <div class="flex items-center justify-between border-t border-slate-200/60 pt-3">
          <button
            v-if="jobDetail.note_id"
            type="button"
            class="kiwi-btn-ghost !text-[11.5px]"
            @click="closeJob(); router.push(`/notes/${jobDetail.note_id}`)"
          >
            <KiwiIcon name="fileText" :size="12" />
            打开来源笔记
          </button>
          <span v-else />
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="kiwi-btn-secondary !text-[11.5px]"
              :disabled="jobLoading"
              @click="refreshJobDetail(jobDetail.id)"
            >
              <KiwiIcon name="refresh" :size="12" :spin="jobLoading" />
              刷新详情
            </button>
            <button type="button" class="kiwi-btn-primary !text-[11.5px]" @click="closeJob">
              关闭
            </button>
          </div>
        </div>
      </div>
    </KiwiModal>

    <!-- 导入报告 -->
    <KiwiModal
      :open="!!reportBatch"
      title="导入报告"
      max-w="max-w-3xl"
      @close="reportBatch = null"
    >
      <div v-if="reportBatch" class="max-h-[68vh] space-y-3 overflow-y-auto pr-1">
        <div class="rounded-xl border border-slate-200/70 bg-slate-50/70 px-3.5 py-2.5">
          <div class="flex flex-wrap items-center gap-2">
            <p class="text-[13px] font-medium text-slate-800">{{ batchLabel(reportBatch) }}</p>
            <span
              class="rounded-full border px-1.5 py-0.5 text-[9.5px]"
              :class="BATCH_STATUS_META[reportBatch.status]?.cls"
            >
              {{ BATCH_STATUS_META[reportBatch.status]?.label || reportBatch.status }}
            </span>
          </div>
          <p class="mt-1 text-[10.5px] text-slate-500">
            {{ providerOf(reportBatch).label }} · 开始于 {{ timeLabel(reportBatch.created_at) }}
            <template v-if="reportBatch.finished_at"> · 完成于 {{ timeLabel(reportBatch.finished_at) }}</template>
            · 用时 {{ durationLabel(reportBatch) }}
          </p>
        </div>

        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div class="rounded-xl border border-emerald-100 bg-emerald-50/60 px-3 py-2">
            <p class="text-[9.5px] text-emerald-600">成功入库</p>
            <p class="text-xl font-semibold tabular-nums text-emerald-700">
              {{ reportStat?.processed ?? 0 }}
            </p>
          </div>
          <div class="rounded-xl border border-rose-100 bg-rose-50/60 px-3 py-2">
            <p class="text-[9.5px] text-rose-600">失败</p>
            <p class="text-xl font-semibold tabular-nums text-rose-700">
              {{ reportStat?.failed ?? 0 }}
            </p>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2">
            <p class="text-[9.5px] text-slate-500">跳过</p>
            <p class="text-xl font-semibold tabular-nums text-slate-600">
              {{ reportStat?.skipped ?? 0 }}
            </p>
          </div>
          <div class="rounded-xl border border-kiwi-100 bg-kiwi-50/60 px-3 py-2">
            <p class="text-[9.5px] text-kiwi-600">已编译</p>
            <p class="text-xl font-semibold tabular-nums text-kiwi-700">
              {{ reportStat?.compiled ?? 0 }}
            </p>
          </div>
        </div>

        <div class="grid gap-2 sm:grid-cols-2">
          <div class="rounded-xl border border-slate-200/70 bg-white/70 p-3">
            <p class="mb-1.5 text-[10.5px] font-medium text-slate-500">解析质量分布</p>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="(count, key) in report.quality || reportStat?.quality || {}"
                :key="key"
                class="rounded-full border px-1.5 py-0.5 text-[10px]"
                :class="qualityMeta(String(key)).cls"
              >
                {{ qualityLabel(String(key)) }} {{ count }}
              </span>
              <span
                v-if="!Object.keys(report.quality || reportStat?.quality || {}).length"
                class="text-[10px] text-slate-400"
              >
                暂无数据
              </span>
            </div>
          </div>
          <div class="rounded-xl border border-slate-200/70 bg-white/70 p-3">
            <p class="mb-1.5 text-[10.5px] font-medium text-slate-500">文件类型 / 解析引擎</p>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="(count, key) in report.types || {}"
                :key="`t-${key}`"
                class="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-600"
              >
                {{ typeLabel(String(key)) }} {{ count }}
              </span>
              <span
                v-for="(count, key) in report.engines || {}"
                :key="`e-${key}`"
                class="rounded-full border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] text-slate-500"
              >
                {{ key }} {{ count }}
              </span>
              <span
                v-if="!Object.keys(report.types || {}).length && !Object.keys(report.engines || {}).length"
                class="text-[10px] text-slate-400"
              >
                暂无数据
              </span>
            </div>
          </div>
        </div>

        <div
          v-if="report.scan && Object.keys(report.scan).length"
          class="rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2"
        >
          <p class="mb-1 text-[10.5px] font-medium text-slate-500">安全扫描</p>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="(count, key) in report.scan"
              :key="`s-${key}`"
              class="rounded-full border px-1.5 py-0.5 text-[10px]"
              :class="key === 'clean' || key === 'heuristic'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-amber-200 bg-amber-50 text-amber-700'"
            >
              {{ SCAN_LABEL[String(key)] || key }} {{ count }}
            </span>
          </div>
        </div>

        <div v-if="report.warnings?.length" class="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3">
          <p class="mb-1.5 flex items-center gap-1.5 text-[10.5px] font-medium text-amber-700">
            <KiwiIcon name="alert" :size="12" />
            需要人工复核
          </p>
          <ul class="space-y-1">
            <li
              v-for="(w, i) in report.warnings"
              :key="`w-${i}`"
              class="text-[10.5px] leading-relaxed text-slate-600"
            >
              <span class="font-medium text-slate-700">{{ w.title }}：</span>
              {{ (w.warnings || []).join('；') }}
            </li>
          </ul>
        </div>

        <div v-if="report.failures?.length" class="rounded-xl border border-rose-200/70 bg-rose-50/60 p-3">
          <p class="mb-1.5 flex items-center gap-1.5 text-[10.5px] font-medium text-rose-700">
            <KiwiIcon name="alert" :size="12" />
            失败条目
          </p>
          <ul class="space-y-1">
            <li
              v-for="(f, i) in report.failures"
              :key="`f-${i}`"
              class="text-[10.5px] leading-relaxed text-slate-600"
            >
              <span class="font-medium text-slate-700">{{ f.title }}：</span>{{ f.error }}
            </li>
          </ul>
        </div>

        <div>
          <p class="mb-1.5 text-[10.5px] font-medium text-slate-500">
            批次素材（{{ reportSources.length }}）
          </p>
          <div class="max-h-56 overflow-y-auto rounded-xl border border-slate-200/70">
            <table class="w-full text-left text-[10.5px]">
              <thead class="sticky top-0 bg-slate-50 text-slate-500">
                <tr>
                  <th class="px-2.5 py-1.5 font-medium">标题</th>
                  <th class="px-2 py-1.5 font-medium">状态</th>
                  <th class="px-2 py-1.5 font-medium">质量</th>
                  <th class="px-2 py-1.5 font-medium">引擎</th>
                  <th class="px-2 py-1.5 text-right font-medium">字符</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="s in reportSources"
                  :key="s.id"
                  class="border-t border-slate-100"
                >
                  <td class="max-w-[260px] truncate px-2.5 py-1.5 text-slate-700" :title="s.title">
                    {{ s.title }}
                  </td>
                  <td class="px-2 py-1.5">
                    <span class="rounded-full border px-1.5 py-0.5 text-[9px]" :class="statusMeta(s.status).cls">
                      {{ statusMeta(s.status).label }}
                    </span>
                  </td>
                  <td class="px-2 py-1.5">
                    <span class="rounded-full border px-1.5 py-0.5 text-[9px]" :class="qualityMeta(s.parse_quality).cls">
                      {{ qualityMeta(s.parse_quality).label }}
                    </span>
                  </td>
                  <td class="whitespace-nowrap px-2 py-1.5 text-slate-500">{{ s.parse_engine }}</td>
                  <td class="px-2 py-1.5 text-right tabular-nums text-slate-500">
                    {{ s.chars ? s.chars.toLocaleString() : '—' }}
                  </td>
                </tr>
                <tr v-if="!reportSources.length">
                  <td colspan="5" class="px-3 py-6 text-center text-slate-400">暂无素材明细</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="mt-4 flex items-center justify-end gap-2">
        <button class="kiwi-btn-secondary !py-1.5 !text-[12px]" @click="reportBatch = null">
          关闭
        </button>
        <button
          class="kiwi-btn-primary !py-1.5 !text-[12px]"
          :disabled="!reportBatch || compiling"
          @click="reportBatch && compileBatch(reportBatch)"
        >
          <KiwiIcon name="play" :size="12" />
          编译本批待编译素材
        </button>
      </div>
    </KiwiModal>

    <!-- 通用确认 -->
    <KiwiConfirm
      :model-value="!!confirmAsk"
      :title="confirmAsk?.title"
      :message="confirmAsk?.message"
      :confirm-text="confirming ? '处理中…' : confirmAsk?.confirmText"
      :danger="confirmAsk?.danger"
      @update:model-value="(v) => { if (!v && !confirming) confirmAsk = null }"
      @confirm="runConfirm"
    />
  </div>
</template>

<style scoped>
.sources-select {
  height: 30px;
  border-radius: 0.5rem;
  border: 1px solid rgb(226 232 240 / 0.9);
  background: rgb(255 255 255 / 0.8);
  padding: 0 0.5rem;
  font-size: 11.5px;
  color: rgb(71 85 105);
  outline: none;
  max-width: 140px;
}
.sources-select:focus {
  border-color: rgb(167 243 208);
  box-shadow: 0 0 0 2px rgb(209 250 229 / 0.6);
}
.row-action {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 0.375rem;
  color: rgb(148 163 184);
  transition: color 0.15s, background-color 0.15s;
}
.row-action:hover {
  color: rgb(13 148 136);
  background: rgb(240 253 250);
}
.row-action:disabled {
  opacity: 0.35;
  pointer-events: none;
}
</style>
