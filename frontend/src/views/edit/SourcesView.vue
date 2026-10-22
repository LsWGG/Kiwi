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
import { cancelJob, retryJob } from '@/api/operations'
import { useKbsStore } from '@/stores/kbs'
import { useNotesStore } from '@/stores/notes'
import type { ImportBatch, ImportBatchReport, NoteSummary } from '@/stores/notes'
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
type Tab = 'content' | 'batches' | 'jobs'
const tab = ref<Tab>('content')
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
    // 笔记与素材共用本页：编译状态既能看作业，也能看笔记自身的 Wiki 关联。
    try {
      await notesStore.fetchTree()
    } catch (e: any) {
      error.value = e.message || '笔记加载失败'
    }
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
    selectedKeys.value = []
    contentPage.value = 1
    tab.value = 'content'
    void load()
  },
)

onMounted(async () => {
  const initialTab = route.query.tab
  if (
    initialTab === 'content' ||
    initialTab === 'notes' ||
    initialTab === 'sources' ||
    initialTab === 'batches' ||
    initialTab === 'jobs'
  ) {
    tab.value = initialTab === 'notes' || initialTab === 'sources' ? 'content' : initialTab
  }
  await load()
  await openJobFromRoute()
})
let clockTimer: number | null = null
function stopDetailClock() {
  if (clockTimer !== null) {
    window.clearInterval(clockTimer)
    clockTimer = null
  }
}
onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  if (boostTimer !== null) window.clearTimeout(boostTimer)
  stopDetailClock()
  stopJobPolling()
})

// --------------------------------------------------------------------------- //
// 素材来源：编译笔记生成的 Source 快照不是用户素材，不单独展示
// --------------------------------------------------------------------------- //
function isNoteSnapshot(s: SourceItem) {
  return s.type === 'note' || (s.external_id || '').startsWith('note:')
}

const materialSources = computed(() => sources.value.filter((s) => !isNoteSnapshot(s)))

const batchLabelMap = computed(() => {
  const map = new Map<string, string>()
  for (const b of batches.value) {
    map.set(b.id, batchLabel(b))
  }
  return map
})

// --------------------------------------------------------------------------- //
// 统一内容视图：笔记是主体，导入素材是笔记的来源
// --------------------------------------------------------------------------- //
const NOTE_KIND_META: Record<string, { label: string; icon: string }> = {
  doc: { label: '文档', icon: 'fileText' },
  database: { label: '数据表', icon: 'database' },
  link: { label: '链接', icon: 'link2' },
  import: { label: '导入', icon: 'fileImport' },
  canvas: { label: '画布', icon: 'pen' },
  notebook: { label: 'Notebook', icon: 'notebook' },
}

/** 工作区活跃笔记；数据表行笔记随所属数据表一起编译，不单独列出。 */
const workspaceNotes = computed(() =>
  notesStore.notes.filter(
    (n) => n.status === 'active' && !n.props_json?.collection_row_id,
  ),
)

const folderNameMap = computed(() => {
  const map = new Map<string, string>()
  for (const folder of notesStore.folders) map.set(folder.id, folder.name)
  return map
})

const sourceById = computed(() => {
  const map = new Map<string, SourceItem>()
  for (const source of materialSources.value) map.set(source.id, source)
  return map
})

/** 导入笔记对应的原始素材；普通笔记没有。 */
function noteSource(note: NoteSummary) {
  const raw = note as NoteSummary & { source_id?: string | null }
  const sourceId = String(note.props_json?.import?.source_id || raw.source_id || '')
  return sourceId ? sourceById.value.get(sourceId) : undefined
}

/** 每篇笔记最近一次编译作业。 */
const noteJobMap = computed(() => {
  const map = new Map<string, IngestJob>()
  for (const job of jobs.value) {
    if (job.kind !== 'compile' || !job.note_id) continue
    const prev = map.get(job.note_id)
    if (
      !prev ||
      new Date(job.created_at).getTime() >= new Date(prev.created_at).getTime()
    ) {
      map.set(job.note_id, job)
    }
  }
  return map
})

type NoteState = 'compiled' | 'busy' | 'failed' | 'pending'

function noteState(note: NoteSummary): NoteState {
  const job = noteJobMap.value.get(note.id)
  if (job?.status === 'pending' || job?.status === 'running') return 'busy'
  if (job?.status === 'failed') return 'failed'
  const source = noteSource(note)
  if (
    job?.status === 'succeeded' ||
    note.wiki_page_id ||
    source?.status === 'compiled'
  ) {
    return 'compiled'
  }
  if (note.props_json?.import?.status === 'failed' || source?.status === 'failed') {
    return 'failed'
  }
  return 'pending'
}

const NOTE_STATE_META: Record<
  NoteState,
  { label: string; cls: string; icon: string; spin?: boolean }
> = {
  compiled: {
    label: '已编译',
    cls: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    icon: 'check',
  },
  busy: {
    label: '编译中',
    cls: 'border-kiwi-200 bg-kiwi-50 text-kiwi-700',
    icon: 'loader',
    spin: true,
  },
  failed: {
    label: '编译失败',
    cls: 'border-rose-200 bg-rose-50 text-rose-600',
    icon: 'alert',
  },
  pending: {
    label: '未编译',
    cls: 'border-slate-200 bg-slate-50 text-slate-500',
    icon: 'bookOpen',
  },
}

function noteStateMeta(note: NoteSummary) {
  const meta = NOTE_STATE_META[noteState(note)]
  const job = noteJobMap.value.get(note.id)
  const source = noteSource(note)
  return {
    ...meta,
    label: job?.status === 'pending' ? '排队中' : meta.label,
    title: job?.error || source?.quality_report?.error || '',
  }
}

const noteStats = computed(() => {
  const result = { total: 0, compiled: 0, busy: 0, failed: 0, pending: 0 }
  for (const note of workspaceNotes.value) {
    result.total += 1
    result[noteState(note)] += 1
  }
  return result
})

/** 已有笔记承载的素材不再作为独立行，避免同一份内容出现两次。 */
const linkedSourceIds = computed(() => {
  const ids = new Set<string>()
  for (const note of workspaceNotes.value) {
    const source = noteSource(note)
    if (source) ids.add(source.id)
  }
  return ids
})

const standaloneSources = computed(() =>
  materialSources.value.filter((source) => !linkedSourceIds.value.has(source.id)),
)

type ContentItem =
  | { key: string; type: 'note'; note: NoteSummary; updatedAt: string }
  | { key: string; type: 'source'; source: SourceItem; updatedAt: string }

function noteKey(id: string) {
  return `note:${id}`
}

function sourceKey(id: string) {
  return `source:${id}`
}

const contentItems = computed<ContentItem[]>(() => {
  const items: ContentItem[] = workspaceNotes.value.map((note) => ({
    key: noteKey(note.id),
    type: 'note' as const,
    note,
    updatedAt: note.updated_at,
  }))
  for (const source of standaloneSources.value) {
    items.push({
      key: sourceKey(source.id),
      type: 'source' as const,
      source,
      updatedAt: source.parsed_at || source.created_at,
    })
  }
  return items.sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  )
})

function sourceState(source: SourceItem): NoteState {
  if (source.status === 'received' || source.status === 'parsing') return 'busy'
  if (source.status === 'parsed') return 'pending'
  if (source.status === 'compiled') return 'compiled'
  if (source.status === 'failed') return 'failed'
  return 'pending'
}

function contentState(item: ContentItem): NoteState {
  return item.type === 'note' ? noteState(item.note) : sourceState(item.source)
}

function contentStateMeta(item: ContentItem) {
  if (item.type === 'note') return noteStateMeta(item.note)
  const meta = statusMeta(item.source.status)
  return {
    ...meta,
    title: item.source.quality_report?.error || '',
  }
}

function contentSource(item: ContentItem) {
  return item.type === 'source' ? item.source : noteSource(item.note)
}

function contentTitle(item: ContentItem) {
  return item.type === 'note' ? item.note.title || '无标题' : item.source.title
}

function contentSubtitle(item: ContentItem) {
  if (item.type === 'note') {
    const folder = item.note.folder_id
      ? folderNameMap.value.get(item.note.folder_id) || '未命名分组'
      : '根目录'
    const tags = item.note.tags?.length ? ` · ${item.note.tags.slice(0, 3).join(' / ')}` : ''
    return `${folder}${tags}`
  }
  const chars = Number(item.source.quality_report?.chars || 0)
  return `${item.source.sha256.slice(0, 10)}${chars ? ` · ${chars.toLocaleString()} 字` : ''}`
}

function contentKindMeta(item: ContentItem) {
  return item.type === 'note'
    ? noteKindMeta(item.note.kind)
    : { label: '素材', icon: 'fileText' }
}

function noteKindMeta(kind: string) {
  return NOTE_KIND_META[kind] || { label: kind, icon: 'fileText' }
}

function contentQuality(item: ContentItem) {
  return contentSource(item)?.parse_quality || ''
}

function contentError(item: ContentItem) {
  if (item.type === 'source') {
    return String(item.source.quality_report?.error || '')
  }
  return (
    noteJobMap.value.get(item.note.id)?.error ||
    String(item.note.props_json?.import?.error || '')
  )
}

function contentWikiId(item: ContentItem) {
  return item.type === 'note' ? item.note.wiki_page_id : null
}

function contentJob(item: ContentItem) {
  return item.type === 'note' ? noteJobMap.value.get(item.note.id) : undefined
}

function contentProcessTime(item: ContentItem) {
  if (item.type === 'source') return item.source.parsed_at || item.source.created_at
  return contentJob(item)?.created_at || null
}

function contentTags(item: ContentItem) {
  return item.type === 'note' ? item.note.tags || [] : []
}

const noteQuery = ref('')
const noteKindFilter = ref('all')
const noteStateFilter = ref('all')
const contentQualityFilter = ref('all')
const contentPage = ref(1)
const CONTENT_PAGE_SIZE = 20

const noteKindOptions = computed(() => {
  const kinds = new Set(workspaceNotes.value.map((n) => n.kind))
  const options = Object.keys(NOTE_KIND_META).filter((kind) => kinds.has(kind as any))
  if (standaloneSources.value.length) options.push('source')
  return options
})

const filteredContent = computed(() => {
  const q = noteQuery.value.trim().toLowerCase()
  return contentItems.value.filter((item) => {
    if (q) {
      const haystack = [
        contentTitle(item),
        contentSubtitle(item),
        ...contentTags(item),
        contentSource(item)?.sha256 || '',
      ]
        .join(' ')
        .toLowerCase()
      if (!haystack.includes(q)) return false
    }
    if (noteKindFilter.value !== 'all') {
      if (noteKindFilter.value === 'source') {
        if (item.type !== 'source') return false
      } else if (item.type !== 'note' || item.note.kind !== noteKindFilter.value) {
        return false
      }
    }
    if (
      noteStateFilter.value !== 'all' &&
      contentState(item) !== noteStateFilter.value
    ) {
      return false
    }
    if (contentQualityFilter.value !== 'all') {
      if (contentQuality(item) !== contentQualityFilter.value) return false
    }
    return true
  })
})

const contentPageCount = computed(() =>
  Math.max(1, Math.ceil(filteredContent.value.length / CONTENT_PAGE_SIZE)),
)
const pagedContent = computed(() =>
  filteredContent.value.slice(
    (contentPage.value - 1) * CONTENT_PAGE_SIZE,
    contentPage.value * CONTENT_PAGE_SIZE,
  ),
)

watch([noteQuery, noteKindFilter, noteStateFilter, contentQualityFilter], () => {
  contentPage.value = 1
})
watch(contentPageCount, (count) => {
  if (contentPage.value > count) contentPage.value = count
})

function noteFolderLabel(note: NoteSummary) {
  return note.folder_id
    ? folderNameMap.value.get(note.folder_id) || '未命名分组'
    : '根目录'
}

const compilingNoteId = ref('')

async function compileOneNote(note: NoteSummary) {
  if (!kbs.currentKbId || compilingNoteId.value) return
  compilingNoteId.value = note.id
  try {
    await notesStore.compileNote(note.id)
    toast.success(`已提交「${note.title}」的编译任务`)
    boostPolling()
    await load(true)
  } catch (e: any) {
    toast.error(e.message || '笔记编译任务提交失败')
  } finally {
    compilingNoteId.value = ''
  }
}

function openNote(note: NoteSummary) {
  void router.push({ name: 'notes', params: { id: note.id } })
}

function openNoteWiki(note: NoteSummary) {
  if (!note.wiki_page_id) return
  void router.push({ name: 'wiki-page', params: { id: note.wiki_page_id } })
}

function openSource(source: SourceItem) {
  void router.push({ name: 'source-preview', params: { id: source.id } })
}

function openContentItem(item: ContentItem) {
  if (item.type === 'note') openNote(item.note)
  else openSource(item.source)
}

function openItemSource(item: ContentItem) {
  const source = contentSource(item)
  if (source) openSource(source)
}

function openItemWiki(item: ContentItem) {
  const wikiId = contentWikiId(item)
  if (wikiId) void router.push({ name: 'wiki-page', params: { id: wikiId } })
}

// 统计：以「内容」为单位，导入素材与笔记不会重复计数
const contentStats = computed(() => {
  const result = {
    total: 0,
    notes: workspaceNotes.value.length,
    sources: standaloneSources.value.length,
    compiled: 0,
    busy: 0,
    failed: 0,
    pending: 0,
  }
  for (const item of contentItems.value) {
    result.total += 1
    result[contentState(item)] += 1
  }
  return result
})

const sourceStats = computed(() => {
  const list = materialSources.value
  return {
    total: list.length,
    compiled: list.filter((s) => s.status === 'compiled').length,
    pending: list.filter((s) => s.status === 'parsed').length,
    processing: list.filter(
      (s) => s.status === 'received' || s.status === 'parsing',
    ).length,
    review: list.filter((s) => s.parse_quality === 'review').length,
    failed: list.filter((s) => s.status === 'failed').length,
  }
})

const failedNotes = computed(() =>
  workspaceNotes.value.filter((note) => noteState(note) === 'failed').length,
)

// 统一列表的筛选 / 分页 / 多选
const selectedKeys = ref<string[]>([])
const selectedKeySet = computed(() => new Set(selectedKeys.value))
const contentPageAllSelected = computed(
  () =>
    pagedContent.value.length > 0 &&
    pagedContent.value.every((item) => selectedKeySet.value.has(item.key)),
)

function toggleContentSelect(key: string) {
  if (selectedKeySet.value.has(key)) {
    selectedKeys.value = selectedKeys.value.filter((x) => x !== key)
  } else {
    selectedKeys.value = [...selectedKeys.value, key]
  }
}

function toggleContentPage() {
  const keys = pagedContent.value.map((item) => item.key)
  if (contentPageAllSelected.value) {
    selectedKeys.value = selectedKeys.value.filter((key) => !keys.includes(key))
  } else {
    selectedKeys.value = Array.from(new Set([...selectedKeys.value, ...keys]))
  }
}

function clearContentSelection() {
  selectedKeys.value = []
}

const selectedContentItems = computed(() =>
  contentItems.value.filter((item) => selectedKeySet.value.has(item.key)),
)

function showFailedContent() {
  tab.value = 'content'
  noteStateFilter.value = 'failed'
  noteKindFilter.value = 'all'
  contentQualityFilter.value = 'all'
}

function showReviewContent() {
  tab.value = 'content'
  contentQualityFilter.value = 'review'
  noteStateFilter.value = 'all'
  noteKindFilter.value = 'all'
}

const compilingContent = ref(false)

/** 编译全部待处理内容：导入素材已由其笔记代表，不重复提交。 */
async function compileAllContent() {
  const kbId = kbs.currentKbId
  if (!kbId || compilingContent.value) return
  compilingContent.value = true
  try {
    const pendingSourceIds = standaloneSources.value
      .filter((source) => source.status === 'parsed')
      .map((source) => source.id)
    let sourceCount = 0
    for (let i = 0; i < pendingSourceIds.length; i += 20) {
      const res = await compileSources(kbId, pendingSourceIds.slice(i, i + 20))
      sourceCount += res.count
    }
    const res = await notesStore.compileAllNotes()
    if (!res.count && !sourceCount) {
      toast.info(
        res.skipped_busy
          ? `${res.skipped_busy} 篇笔记正在编译中，请稍后查看任务`
          : '没有需要编译的内容',
      )
      return
    }
    toast.success(
      `已提交 ${res.count} 篇笔记、${sourceCount} 个素材的编译任务`,
    )
    boostPolling()
    await load(true)
  } catch (e: any) {
    toast.error(e.message || '编译任务提交失败')
  } finally {
    compilingContent.value = false
  }
}

const compilingSelection = ref(false)

async function compileSelectedContent() {
  const kbId = kbs.currentKbId
  const items = selectedContentItems.value
  if (!kbId || !items.length || compilingSelection.value) return
  compilingSelection.value = true
  let noteCount = 0
  let sourceCount = 0
  let skipped = 0
  try {
    const noteIds = items
      .filter((item): item is Extract<ContentItem, { type: 'note' }> => item.type === 'note')
      .map((item) => item.note.id)
    const sourceIds = items
      .filter((item): item is Extract<ContentItem, { type: 'source' }> => item.type === 'source')
      .map((item) => item.source.id)

    for (const noteId of noteIds) {
      const note = workspaceNotes.value.find((n) => n.id === noteId)
      if (!note || noteState(note) === 'busy') {
        skipped += 1
        continue
      }
      try {
        await notesStore.compileNote(noteId)
        noteCount += 1
      } catch {
        skipped += 1
      }
    }
    for (let i = 0; i < sourceIds.length; i += 20) {
      try {
        const res = await compileSources(kbId, sourceIds.slice(i, i + 20))
        sourceCount += res.count
        skipped += res.skipped
      } catch {
        skipped += sourceIds.slice(i, i + 20).length
      }
    }
    if (noteCount || sourceCount) {
      toast.success(
        `已提交 ${noteCount} 篇笔记、${sourceCount} 个素材的编译任务${
          skipped ? `，${skipped} 个未提交` : ''
        }`,
      )
      clearContentSelection()
    } else {
      toast.info('所选内容暂时无法编译')
    }
    boostPolling()
    await load(true)
  } finally {
    compilingSelection.value = false
  }
}

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
    clearContentSelection()
    boostPolling()
    await load(true)
  } catch (e: any) {
    toast.error(e.message || '编译任务提交失败')
  } finally {
    compiling.value = false
  }
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
      selectedKeys.value = selectedKeys.value.filter(
        (key) => key !== sourceKey(s.id),
      )
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
  return materialSources.value.filter((s) => s.import_batch_id === batchId)
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
    label: '运行中',
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
  const start = new Date(job.created_at).getTime()
  if (Number.isNaN(start)) return '—'
  // 进行中的任务用本地时钟实时走字；已结束的任务用最后一次落库时间。
  const finished = job.status !== 'pending' && job.status !== 'running'
  const end = finished && job.updated_at ? new Date(job.updated_at).getTime() : nowMs.value
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes < 60) return `${minutes} 分 ${rest} 秒`
  return `${Math.floor(minutes / 60)} 时 ${minutes % 60} 分`
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
  stopJobPolling()
  try {
    const data = await getJob(kbId, jobId)
    if (jobDetail.value?.id !== jobId) return
    jobDetail.value = data
    if (data.status === 'pending' || data.status === 'running') {
      jobPollTimer = window.setTimeout(() => void refreshJobDetail(jobId), 2000)
    }
  } catch (e: any) {
    jobLoading.value = false
    // 轮询期间的瞬时失败不应让详情永久停在旧状态：仍在打开展示同一个任务时继续重试。
    if (jobDetail.value?.id === jobId) {
      jobPollTimer = window.setTimeout(() => void refreshJobDetail(jobId), 5000)
      return
    }
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

const jobActionId = ref<string | null>(null)

/** 编译页直接管理任务：失败可重试，排队 / 执行中可取消。 */
async function retryCompileJob(job: IngestJob) {
  if (!job.durable_job_id || jobActionId.value) return
  jobActionId.value = job.durable_job_id
  try {
    await retryJob(job.durable_job_id)
    toast.success('已重新提交编译任务')
    boostPolling()
    await load(true)
    await refreshJobDetail(job.id)
  } catch (e: any) {
    toast.error(e.message || '重试任务失败')
  } finally {
    jobActionId.value = null
  }
}

async function cancelCompileJob(job: IngestJob) {
  if (!job.durable_job_id || jobActionId.value) return
  jobActionId.value = job.durable_job_id
  try {
    await cancelJob(job.durable_job_id)
    toast.success('已提交取消请求')
    boostPolling()
    await load(true)
    await refreshJobDetail(job.id)
  } catch (e: any) {
    toast.error(e.message || '取消任务失败')
  } finally {
    jobActionId.value = null
  }
}

// 「用时」本地秒表：仅在进行中的详情弹窗打开时运行，避免整页无谓重渲染。
const nowMs = ref(Date.now())
function syncDetailClock(job: IngestJob | null) {
  const running = job?.status === 'pending' || job?.status === 'running'
  if (!running) {
    stopDetailClock()
    return
  }
  nowMs.value = Date.now()
  if (clockTimer === null) {
    clockTimer = window.setInterval(() => {
      nowMs.value = Date.now()
    }, 1000)
  }
}
watch(jobDetail, () => syncDetailClock(jobDetail.value))

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
    const res = await notesStore.compileAllNotes()
    if (res.count) {
      toast.success(
        `已提交 ${res.count} 篇笔记编译任务（文档 / 导入 / 链接 / 数据表 / 画布 / Notebook）`,
      )
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
        <h1 class="text-[19px] font-semibold tracking-tight text-slate-800">编译任务</h1>
        <p class="mt-0.5 text-[11.5px] text-slate-400">
          笔记与导入素材统一编译进 Wiki · 追踪解析质量、导入批次与任务进度
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
      <KiwiEmpty icon="database" title="请先选择知识库" desc="笔记、素材与编译任务按知识库隔离" />
    </div>

    <template v-else>
      <!-- 统计卡片：笔记与导入素材共用同一套 Wiki 编译流水线 -->
      <div class="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="note" :size="12" class="text-slate-400" />
            全部内容
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-slate-800">
            {{ contentStats.total }}
          </p>
          <p class="mt-1 text-[10px] text-slate-400">
            笔记 {{ contentStats.notes }} · 独立素材 {{ contentStats.sources }}
          </p>
        </div>
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="check" :size="12" class="text-emerald-500" />
            已编译
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-emerald-700">
            {{ contentStats.compiled }}
          </p>
          <p class="mt-1 text-[10px] text-slate-400">
            {{
              contentStats.total
                ? `${Math.round((contentStats.compiled / contentStats.total) * 100)}% 已进入 Wiki`
                : '尚未创建内容'
            }}
          </p>
        </div>
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="sparkle" :size="12" class="text-kiwi-500" />
            待编译
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-kiwi-700">
            {{ contentStats.pending }}
          </p>
          <button
            v-if="contentStats.pending"
            type="button"
            class="mt-1 text-[10px] text-kiwi-600 hover:underline disabled:opacity-40"
            :disabled="compilingContent"
            @click="compileAllContent"
          >
            全部编译 →
          </button>
          <p v-else class="mt-1 text-[10px] text-slate-400">没有积压</p>
        </div>
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="fileImport" :size="12" class="text-slate-400" />
            导入素材
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-slate-800">
            {{ sourceStats.total }}
          </p>
          <p class="mt-1 text-[10px] text-slate-400">
            {{ sourceStats.compiled }} 已编译
            <template v-if="sourceStats.processing"> · {{ sourceStats.processing }} 处理中</template>
            <template v-else-if="sourceStats.pending"> · {{ sourceStats.pending }} 待编译</template>
            <template v-else> · 原文不可变</template>
          </p>
        </div>
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="alert" :size="12" class="text-amber-500" />
            待人工复核
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-amber-700">
            {{ sourceStats.review }}
          </p>
          <button
            v-if="sourceStats.review"
            type="button"
            class="mt-1 text-[10px] text-amber-600 hover:underline"
            @click="showReviewContent"
          >
            查看待复核素材 →
          </button>
          <p v-else class="mt-1 text-[10px] text-slate-400">解析质量正常</p>
        </div>
        <div class="kiwi-card !rounded-xl px-3.5 py-2.5">
          <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
            <KiwiIcon name="trash" :size="12" class="text-rose-400" />
            失败
          </div>
          <p class="mt-1 text-[22px] font-bold leading-none tabular-nums text-rose-600">
            {{ contentStats.failed }}
          </p>
          <button
            v-if="contentStats.failed"
            type="button"
            class="mt-1 text-[10px] text-rose-500 hover:underline"
            @click="showFailedContent"
          >
            查看失败内容 →
          </button>
          <p v-else class="mt-1 text-[10px] text-slate-400">
            解析 {{ sourceStats.failed }} · 编译 {{ failedNotes }}
          </p>
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
            { key: 'content', label: '全部内容', count: contentStats.total },
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

      <!-- 全部内容：笔记是主体，导入素材作为笔记来源，不重复成行 -->
      <template v-if="tab === 'content'">
        <div class="mb-2 flex flex-wrap items-center gap-1.5">
          <div class="relative min-w-[190px] max-w-[280px] flex-1">
            <KiwiIcon
              name="search"
              :size="13"
              class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400"
            />
            <input
              v-model="noteQuery"
              type="search"
              placeholder="搜索标题 / 分组 / 标签 / 指纹…"
              class="kiwi-input !py-1.5 !pl-8 !text-[11.5px]"
            />
          </div>
          <select v-model="noteKindFilter" class="sources-select">
            <option value="all">全部类型</option>
            <option v-for="kind in noteKindOptions" :key="kind" :value="kind">
              {{ kind === 'source' ? '独立素材' : noteKindMeta(kind).label }}
            </option>
          </select>
          <select v-model="noteStateFilter" class="sources-select">
            <option value="all">全部编译状态</option>
            <option value="compiled">已编译</option>
            <option value="busy">处理中</option>
            <option value="pending">未编译</option>
            <option value="failed">失败</option>
          </select>
          <select v-model="contentQualityFilter" class="sources-select">
            <option value="all">全部解析质量</option>
            <option value="clean">解析干净</option>
            <option value="ocr_aided">OCR 辅助</option>
            <option value="review">待人工复核</option>
          </select>

          <div class="ml-auto flex items-center gap-1.5">
            <button
              v-if="selectedKeys.length"
              type="button"
              class="text-[10.5px] text-slate-400 hover:text-slate-600"
              @click="clearContentSelection"
            >
              已选 {{ selectedKeys.length }} · 清除
            </button>
            <button
              type="button"
              class="kiwi-btn-secondary !px-2.5 !py-1.5 !text-[11px]"
              :disabled="!selectedKeys.length || compilingSelection"
              @click="compileSelectedContent"
            >
              <KiwiIcon
                :name="compilingSelection ? 'loader' : 'play'"
                :size="12"
                :spin="compilingSelection"
              />
              编译所选
            </button>
          </div>
        </div>

        <div class="kiwi-card flex min-h-0 flex-1 flex-col overflow-hidden !rounded-xl">
          <div class="min-h-0 flex-1 overflow-auto">
            <table class="w-full min-w-[1040px] border-collapse text-left text-[11.5px]">
              <thead class="sticky top-0 z-10 bg-slate-50/95 text-[10.5px] text-slate-500 backdrop-blur">
                <tr>
                  <th class="w-9 px-3 py-2">
                    <input
                      type="checkbox"
                      :checked="contentPageAllSelected"
                      class="h-3.5 w-3.5 rounded border-slate-300 accent-kiwi-600"
                      @change="toggleContentPage"
                    />
                  </th>
                  <th class="px-2 py-2 font-medium">内容</th>
                  <th class="px-2 py-2 font-medium">类型</th>
                  <th class="px-2 py-2 font-medium">编译状态</th>
                  <th class="px-2 py-2 font-medium">解析质量</th>
                  <th class="px-2 py-2 font-medium">最近处理</th>
                  <th class="px-2 py-2 font-medium">Wiki 页面</th>
                  <th class="px-2 py-2 font-medium">更新时间</th>
                  <th class="w-28 px-2 py-2 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="loading && !contentItems.length">
                  <td colspan="9" class="px-4 py-12 text-center text-slate-400">
                    <span class="inline-flex items-center gap-2">
                      <KiwiIcon name="loader" :size="14" spin class="text-kiwi-500" />
                      正在加载内容…
                    </span>
                  </td>
                </tr>
                <tr v-else-if="!filteredContent.length">
                  <td colspan="9" class="px-4 py-12 text-center">
                    <p class="text-[12px] text-slate-500">
                      {{ contentItems.length ? '没有符合筛选条件的内容' : '知识库还没有内容' }}
                    </p>
                    <p class="mt-1 text-[10.5px] text-slate-400">
                      {{
                        contentItems.length
                          ? '试试调整搜索或筛选条件'
                          : '前往笔记工作区创建文档、数据表、画布，或导入素材'
                      }}
                    </p>
                    <RouterLink
                      v-if="!contentItems.length"
                      to="/notes"
                      class="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-kiwi-600 hover:underline"
                    >
                      打开笔记工作区
                      <KiwiIcon name="arrowRight" :size="11" />
                    </RouterLink>
                  </td>
                </tr>
                <tr
                  v-for="item in pagedContent"
                  v-else
                  :key="item.key"
                  class="border-t border-slate-100 transition-colors hover:bg-kiwi-50/40"
                  :class="selectedKeySet.has(item.key) && 'bg-kiwi-50/50'"
                >
                  <td class="px-3 py-2 align-top">
                    <input
                      type="checkbox"
                      :checked="selectedKeySet.has(item.key)"
                      class="mt-0.5 h-3.5 w-3.5 rounded border-slate-300 accent-kiwi-600"
                      @change="toggleContentSelect(item.key)"
                    />
                  </td>
                  <td class="max-w-[340px] px-2 py-2">
                    <div class="flex items-center gap-1.5">
                      <KiwiIcon
                        :name="contentKindMeta(item).icon"
                        :size="13"
                        class="shrink-0 text-slate-400"
                      />
                      <button
                        type="button"
                        class="truncate text-left font-medium text-slate-700 hover:text-kiwi-600"
                        :title="contentTitle(item)"
                        @click="openContentItem(item)"
                      >
                        {{ contentTitle(item) }}
                      </button>
                      <span
                        v-if="item.type === 'note' && contentSource(item)"
                        class="shrink-0 rounded bg-slate-100 px-1 py-0.5 text-[8.5px] font-semibold text-slate-400"
                        title="该笔记来源于导入素材"
                      >
                        有原文
                      </span>
                    </div>
                    <p class="mt-0.5 truncate text-[9.5px] text-slate-400">
                      {{ contentSubtitle(item) }}
                    </p>
                    <p
                      v-if="contentError(item)"
                      class="mt-0.5 line-clamp-1 text-[10px] text-rose-500"
                      :title="contentError(item)"
                    >
                      {{ contentError(item) }}
                    </p>
                  </td>
                  <td class="px-2 py-2 align-top">
                    <span
                      class="rounded-md bg-slate-100 px-1.5 py-0.5 text-[9.5px] font-semibold text-slate-500"
                      :title="item.type === 'source' ? item.source.type.toUpperCase() : undefined"
                    >
                      {{ contentKindMeta(item).label }}
                    </span>
                  </td>
                  <td class="px-2 py-2 align-top">
                    <span
                      class="inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px]"
                      :class="contentStateMeta(item).cls"
                      :title="contentStateMeta(item).title"
                    >
                      <KiwiIcon
                        :name="contentStateMeta(item).icon"
                        :size="10"
                        :spin="contentStateMeta(item).spin"
                      />
                      {{ contentStateMeta(item).label }}
                    </span>
                  </td>
                  <td class="px-2 py-2 align-top">
                    <span
                      v-if="contentQuality(item)"
                      class="rounded-full border px-1.5 py-0.5 text-[10px]"
                      :class="qualityMeta(contentQuality(item)).cls"
                    >
                      {{ qualityMeta(contentQuality(item)).label }}
                    </span>
                    <span v-else class="text-[10.5px] text-slate-300">—</span>
                  </td>
                  <td class="whitespace-nowrap px-2 py-2 align-top text-[10.5px] text-slate-500">
                    {{ shortTime(contentProcessTime(item)) }}
                  </td>
                  <td class="px-2 py-2 align-top">
                    <button
                      v-if="contentWikiId(item)"
                      type="button"
                      class="inline-flex items-center gap-1 text-[10.5px] font-medium text-kiwi-600 hover:underline"
                      @click="openItemWiki(item)"
                    >
                      <KiwiIcon name="wiki" :size="11" />
                      查看
                    </button>
                    <span v-else class="text-[10.5px] text-slate-300">—</span>
                  </td>
                  <td class="whitespace-nowrap px-2 py-2 align-top text-[10.5px] text-slate-500">
                    {{ shortTime(item.updatedAt) }}
                  </td>
                  <td class="px-2 py-2 align-top">
                    <div class="flex items-center justify-end gap-0.5">
                      <template v-if="item.type === 'note'">
                        <button
                          type="button"
                          class="row-action"
                          title="打开笔记"
                          @click="openNote(item.note)"
                        >
                          <KiwiIcon name="arrowUpRight" :size="13" />
                        </button>
                        <button
                          type="button"
                          class="row-action"
                          title="编译该笔记"
                          :disabled="compilingNoteId === item.note.id || noteState(item.note) === 'busy'"
                          @click="compileOneNote(item.note)"
                        >
                          <KiwiIcon
                            :name="compilingNoteId === item.note.id ? 'loader' : 'play'"
                            :size="12"
                            :spin="compilingNoteId === item.note.id"
                          />
                        </button>
                        <button
                          v-if="contentSource(item)"
                          type="button"
                          class="row-action"
                          title="查看原始素材"
                          @click="openItemSource(item)"
                        >
                          <KiwiIcon name="external" :size="12" />
                        </button>
                        <button
                          v-if="contentWikiId(item)"
                          type="button"
                          class="row-action"
                          title="查看编译生成的 Wiki 页面"
                          @click="openItemWiki(item)"
                        >
                          <KiwiIcon name="wiki" :size="12" />
                        </button>
                      </template>
                      <template v-else>
                        <button
                          type="button"
                          class="row-action"
                          title="查看素材原文"
                          @click="openSource(item.source)"
                        >
                          <KiwiIcon name="arrowUpRight" :size="13" />
                        </button>
                        <button
                          type="button"
                          class="row-action"
                          title="编译该素材"
                          :disabled="compiling || item.source.status === 'received' || item.source.status === 'parsing'"
                          @click="compileIds([item.source.id])"
                        >
                          <KiwiIcon name="play" :size="12" />
                        </button>
                        <button
                          type="button"
                          class="row-action"
                          title="重新解析"
                          @click="askReparse(item.source)"
                        >
                          <KiwiIcon name="refresh" :size="12" />
                        </button>
                        <button
                          type="button"
                          class="row-action hover:!text-rose-600"
                          title="删除素材"
                          @click="askDelete(item.source)"
                        >
                          <KiwiIcon name="trash" :size="12" />
                        </button>
                      </template>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div
            v-if="filteredContent.length"
            class="flex shrink-0 items-center justify-between border-t border-slate-100 bg-white/60 px-3 py-1.5 text-[10.5px] text-slate-500"
          >
            <span>
              共 {{ filteredContent.length }} 项
              <template v-if="filteredContent.length !== contentItems.length">
                （全部 {{ contentItems.length }} 项）
              </template>
              · 第 {{ contentPage }} / {{ contentPageCount }} 页
            </span>
            <div class="flex items-center gap-1">
              <button
                type="button"
                class="rounded-md border border-slate-200 bg-white px-2 py-1 disabled:opacity-40"
                :disabled="contentPage <= 1"
                @click="contentPage--"
              >
                上一页
              </button>
              <button
                type="button"
                class="rounded-md border border-slate-200 bg-white px-2 py-1 disabled:opacity-40"
                :disabled="contentPage >= contentPageCount"
                @click="contentPage++"
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
              title="把本库全部笔记（文档 / 导入 / 链接 / 数据表 / 画布 / Notebook）编译进 Wiki"
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
            <span
              v-if="jobDetail.status === 'pending' || jobDetail.status === 'running'"
              class="inline-flex items-center gap-1 text-[9.5px] text-slate-400"
              title="每 2 秒自动同步任务进度"
            >
              <span class="relative flex h-1.5 w-1.5">
                <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-kiwi-400 opacity-60" />
                <span class="relative inline-flex h-1.5 w-1.5 rounded-full bg-kiwi-500" />
              </span>
              实时同步中
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
          <p
            v-if="jobDetail.status === 'pending' || jobDetail.status === 'running'"
            class="mt-1.5 text-[10px] leading-relaxed text-slate-400"
          >
            {{
              jobDetail.progress >= 0.8
                ? '大模型正在生成并合并 Wiki 页面，长文档可能需要数分钟，请保持页面开启'
                : '正在解析与向量化内容'
            }}
            · 已用时 {{ jobDuration(jobDetail) }}
          </p>
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
              v-if="jobDetail.durable_job_id && (jobDetail.status === 'pending' || jobDetail.status === 'running')"
              type="button"
              class="kiwi-btn-secondary !text-[11.5px]"
              :disabled="!!jobActionId"
              @click="cancelCompileJob(jobDetail)"
            >
              <KiwiIcon name="close" :size="12" />
              取消任务
            </button>
            <button
              v-if="jobDetail.durable_job_id && jobDetail.status === 'failed'"
              type="button"
              class="kiwi-btn-primary !text-[11.5px]"
              :disabled="!!jobActionId"
              @click="retryCompileJob(jobDetail)"
            >
              <KiwiIcon name="refresh" :size="12" />
              重试编译
            </button>
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
