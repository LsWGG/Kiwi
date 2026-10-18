import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request, upload } from '@/api/client'
import { useKbsStore } from './kbs'

export type NoteKind = 'doc' | 'database' | 'link' | 'import' | 'canvas' | 'notebook'

export interface NoteOut {
  id: string
  kb_id: string
  title: string
  body_md: string
  kind: NoteKind
  folder_id: string | null
  source_id: string | null
  status: string
  view_mode: string
  sort_order: number
  props_json: Record<string, any>
  tags: string[]
  wiki_page_id: string | null
  created_at: string
  updated_at: string
}

export interface NoteSummary {
  id: string
  kb_id: string
  title: string
  kind: NoteKind
  folder_id: string | null
  status: string
  sort_order: number
  props_json: Record<string, any>
  tags: string[]
  wiki_page_id: string | null
  /** 反向链接条目附带引用上下文 */
  context?: string
  created_at?: string
  updated_at: string
}

export interface NoteTag {
  id: string
  name: string
  parent_id: string | null
  usage_count: number
  last_used_at?: string | null
}

export interface NoteTemplate {
  id: string
  kb_id: string
  name: string
  description: string
  icon: string
  title_pattern: string
  body_md: string
  tags_json: string[]
  props_json: Record<string, any>
  is_builtin: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

export interface NoteSearchItem {
  note: NoteSummary
  snippet: string
  matched_fields: string[]
  score: number
}

export interface NoteSearchResult {
  total: number
  items: NoteSearchItem[]
}

export interface RelatedNoteItem {
  note: NoteSummary
  score: number
  reasons: string[]
}

export interface NoteTrash {
  total: number
  items: NoteSummary[]
  retention_days: number
}

export interface NoteCompileStatus {
  job_id: string | null
  status: string
  progress: number
  error: string | null
  source_id: string | null
  compiled: boolean
  page_count: number
  finished_at: string | null
}

export interface NoteStudyPoint {
  id: string
  text: string
  wiki_slug: string | null
  created_at: string
}

export interface NoteWikiLink {
  wiki_page_id: string | null
  slug: string | null
  title: string | null
}

export interface NoteSearchFilters {
  q?: string
  /** 跨知识库检索时指定；缺省为当前编辑知识库 */
  kb_id?: string
  folder_id?: string | null
  tag_ids?: string[]
  kind?: string | null
  status?: string | null
  created_from?: string | null
  created_to?: string | null
  updated_from?: string | null
  updated_to?: string | null
  limit?: number
  offset?: number
}

export interface NoteFolder {
  id: string
  name: string
  parent_id: string | null
  sort_order: number
  /** 置顶：在同一层级内优先展示 */
  pinned?: boolean
}

export interface NoteTree {
  folders: NoteFolder[]
  notes: NoteSummary[]
}

export interface ImportStatus {
  status: 'importing' | 'ready' | 'failed'
  progress: number
  error: string | null
  source_id: string | null
  job_id: string | null
  source_status: string | null
  parse_quality: string | null
  parse_engine: string | null
  scan_status: string | null
  scan_detail: string | null
  quality_report: Record<string, unknown>
  warnings: string[]
  body_ready: boolean
}

export interface TablePreviewSheet {
  name: string
  row_count: number
  column_count: number
}

export interface TablePreview {
  sheets: TablePreviewSheet[]
  sheet: string
  fields: Array<{ id: string; name: string; type: string }>
  sample_rows: Array<Record<string, any>>
  row_count: number
  truncated: boolean
}

export interface TableImportResult {
  note: NoteOut
  sheet: string
  fields: Array<{ id: string; name: string; type: string }>
  row_count: number
  truncated: boolean
}

export interface ImportBatchItem {
  title: string
  status: string
  source_id: string | null
  job_id: string | null
  note_id: string | null
  error: string
  warnings: string[]
  external_id: string
  submitted_at: string
}

export interface ImportBatchReport {
  summary?: {
    total: number
    processed: number
    failed: number
    skipped: number
    compiled: number
  }
  quality?: Record<string, number>
  types?: Record<string, number>
  scan?: Record<string, number>
  engines?: Record<string, number>
  warnings?: Array<{ title: string; warnings: string[] }>
  failures?: Array<{ title: string; error: string }>
  items?: ImportBatchItem[]
  sources?: Array<{
    id: string
    title: string
    type: string
    status: string
    parse_quality: string
    parse_engine: string
    scan_status: string
    source_url: string
    external_id: string | null
    chars: number
    warnings: string[]
  }>
  generated_at?: string
  duration_seconds?: number
  label?: string
  [key: string]: unknown
}

export interface ImportBatch {
  id: string
  kb_id: string
  provider: string
  status: 'running' | 'completed' | 'partial' | 'failed'
  total_sources: number
  processed_count: number
  failed_count: number
  skipped_count: number
  report_json: ImportBatchReport
  error: string | null
  created_at: string
  finished_at: string | null
}

export interface LinkMeta {
  url: string
  final_url: string
  site: string
  favicon: string
  excerpt: string
  fetch_status: 'ok' | 'failed'
  fetch_error: string | null
  fetched_at: string
}

export const useNotesStore = defineStore('notes', () => {
  const kbs = useKbsStore()

  const folders = ref<NoteFolder[]>([])
  const notes = ref<NoteSummary[]>([])
  const currentNote = ref<NoteOut | null>(null)
  const loading = ref(false)
  const treeLoading = ref(false)
  const importStatus = ref<ImportStatus | null>(null)
  const importNoteId = ref<string | null>(null)
  const tags = ref<NoteTag[]>([])
  const templates = ref<NoteTemplate[]>([])
  const archived = ref<NoteSummary[]>([])
  const trash = ref<NoteTrash | null>(null)
  let pollTimer: number | null = null

  function kbId() {
    return kbs.currentKbId
  }

  function noteSummary(note: NoteOut): NoteSummary {
    return {
      id: note.id,
      kb_id: note.kb_id,
      title: note.title,
      kind: note.kind,
      folder_id: note.folder_id,
      status: note.status,
      sort_order: note.sort_order,
      props_json: note.props_json,
      tags: note.tags || [],
      wiki_page_id: note.wiki_page_id,
      created_at: note.created_at,
      updated_at: note.updated_at,
    }
  }

  function upsertSummary(note: NoteOut) {
    const idx = notes.value.findIndex((n) => n.id === note.id)
    const summary = noteSummary(note)
    if (idx >= 0) notes.value[idx] = { ...notes.value[idx], ...summary }
    else notes.value.push(summary)
  }

  async function fetchTree() {
    if (!kbId()) {
      folders.value = []
      notes.value = []
      return
    }
    treeLoading.value = true
    try {
      const tree = await request<NoteTree>('/notes/tree', { kbId: kbId() })
      folders.value = tree.folders
      notes.value = tree.notes
    } finally {
      treeLoading.value = false
    }
  }

  async function getNote(id: string) {
    const note = await request<NoteOut>(`/notes/${id}`, { kbId: kbId() })
    currentNote.value = note
    if (note.kind === 'import') {
      startImportPolling(note.id)
    }
    return note
  }

  async function createNote(data: {
    title: string
    kind?: 'doc' | 'database' | 'canvas' | 'notebook'
    folder_id?: string | null
    body_md?: string
    tags?: string[]
  }) {
    const note = await request<NoteOut>('/notes', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({
        title: data.title,
        kind: data.kind ?? 'doc',
        folder_id: data.folder_id ?? null,
        body_md: data.body_md ?? '',
        tags: data.tags ?? [],
      }),
    })
    await fetchTree()
    currentNote.value = note
    return note
  }

  async function updateNote(id: string, patch: Partial<NoteOut>) {
    const note = await request<NoteOut>(`/notes/${id}`, {
      method: 'PATCH',
      kbId: kbId(),
      body: JSON.stringify(patch),
    })
    if (currentNote.value?.id === id) currentNote.value = note
    upsertSummary(note)
    return note
  }

  async function moveNote(id: string, folderId: string | null) {
    return updateNote(id, { folder_id: folderId })
  }

  async function deleteNote(id: string) {
    await request(`/notes/${id}`, { method: 'DELETE', kbId: kbId() })
    if (currentNote.value?.id === id) currentNote.value = null
    if (importNoteId.value === id) stopImportPolling()
    notes.value = notes.value.filter((n) => n.id !== id)
  }

  /** 复制笔记（数据表连同字段/视图/记录一起复制）。 */
  async function copyNote(id: string, opts: { title?: string; folder_id?: string | null } = {}) {
    const body: Record<string, any> = {}
    if (opts.title !== undefined) body.title = opts.title
    if (opts.folder_id !== undefined) body.folder_id = opts.folder_id
    const note = await request<NoteOut>(`/notes/${id}/copy`, {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify(body),
    })
    await fetchTree()
    return note
  }

  /** 跨知识库移动笔记；调用方负责在成功后处理当前笔记状态。 */
  async function transferNote(
    id: string,
    targetKbId: string,
    folderId: string | null = null,
  ) {
    const note = await request<NoteOut>(`/notes/${id}/transfer`, {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ target_kb_id: targetKbId, folder_id: folderId }),
    })
    notes.value = notes.value.filter((n) => n.id !== id)
    if (currentNote.value?.id === id) currentNote.value = null
    if (importNoteId.value === id) stopImportPolling()
    return note
  }

  // ---------- 分组 ----------
  async function createFolder(name: string, parentId: string | null = null) {
    const folder = await request<NoteFolder>('/notes/folders', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ name, parent_id: parentId }),
    })
    await fetchTree()
    return folder
  }

  async function updateFolder(
    id: string,
    patch: { name?: string; parent_id?: string | null; pinned?: boolean },
  ) {
    const folder = await request<NoteFolder>(`/notes/folders/${id}`, {
      method: 'PATCH',
      kbId: kbId(),
      body: JSON.stringify(patch),
    })
    await fetchTree()
    return folder
  }

  async function deleteFolder(id: string) {
    await request(`/notes/folders/${id}`, { method: 'DELETE', kbId: kbId() })
    await fetchTree()
    if (currentNote.value && !notes.value.some((n) => n.id === currentNote.value!.id)) {
      currentNote.value = null
    }
  }

  // ---------- 排序 ----------
  async function reorder(
    parentId: string | null,
    target: 'note' | 'folder',
    orderedIds: string[],
  ) {
    await request('/notes/reorder', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ parent_id: parentId, target, ordered_ids: orderedIds }),
    })
    const list = target === 'note' ? notes.value : folders.value
    orderedIds.forEach((id, index) => {
      const item = (list as Array<{ id: string; sort_order: number }>).find((x) => x.id === id)
      if (item) item.sort_order = index
    })
  }

  // ---------- 导入 ----------
  async function importFile(
    file: File | null,
    opts: {
      folder_id?: string | null
      title?: string
      batch_id?: string
      upload_id?: string
      compile_now?: boolean
      open?: boolean
    } = {},
  ) {
    const fd = new FormData()
    if (file) fd.append('file', file)
    if (!file && !opts.upload_id) throw new Error('缺少文件')
    if (opts.upload_id) fd.append('upload_id', opts.upload_id)
    if (opts.batch_id) fd.append('batch_id', opts.batch_id)
    if (opts.folder_id) fd.append('folder_id', opts.folder_id)
    if (opts.title?.trim()) fd.append('title', opts.title.trim())
    if (opts.compile_now) fd.append('compile_now', 'true')
    const res = await upload<{ note: NoteOut; job_id: string }>('/notes/import', fd, kbId())
    await fetchTree()
    if (opts.open !== false) {
      currentNote.value = res.note
      startImportPolling(res.note.id)
    }
    return res
  }

  /** 导入 `.ipynb`：生成 Notebook 笔记（单元格与输出一并保留）。 */
  async function importNotebook(
    file: File,
    opts: { folder_id?: string | null; title?: string; open?: boolean } = {},
  ) {
    const fd = new FormData()
    fd.append('file', file)
    if (opts.folder_id) fd.append('folder_id', opts.folder_id)
    if (opts.title?.trim()) fd.append('title', opts.title.trim())
    const note = await upload<NoteOut>('/notebooks/import', fd, kbId())
    await fetchTree()
    if (opts.open !== false) currentNote.value = note
    return note
  }

  async function importRemoteFile(data: {
    url: string
    folder_id?: string | null
    title?: string
    batch_id?: string
    compile_now?: boolean
  }) {
    const res = await request<{ note: NoteOut; job_id: string }>('/notes/import-url', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({
        url: data.url,
        folder_id: data.folder_id || null,
        title: data.title?.trim() || null,
        batch_id: data.batch_id || null,
        compile_now: !!data.compile_now,
      }),
    })
    await fetchTree()
    return res
  }

  async function previewTable(
    file: File,
    opts: { sheet?: string; has_header?: boolean } = {},
  ) {
    const fd = new FormData()
    fd.append('file', file)
    if (opts.sheet) fd.append('sheet', opts.sheet)
    fd.append('has_header', opts.has_header === false ? 'false' : 'true')
    return upload<TablePreview>('/notes/table-preview', fd)
  }

  async function importTable(
    file: File,
    opts: {
      folder_id?: string | null
      title?: string
      sheet?: string
      has_header?: boolean
    } = {},
  ) {
    const fd = new FormData()
    fd.append('file', file)
    if (opts.folder_id) fd.append('folder_id', opts.folder_id)
    if (opts.title?.trim()) fd.append('title', opts.title.trim())
    if (opts.sheet) fd.append('sheet', opts.sheet)
    fd.append('has_header', opts.has_header === false ? 'false' : 'true')
    const res = await upload<TableImportResult>('/notes/import-table', fd, kbId())
    await fetchTree()
    return res
  }

  async function createImportBatch(
    provider: 'upload' | 'url' | 'yuque_token' | 'yuque_zip',
    label: string,
    expectedCount = 0,
  ) {
    return request<ImportBatch>('/ingest/batches', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ provider, label, expected_count: expectedCount }),
    })
  }

  async function closeImportBatch(batchId: string) {
    return request<ImportBatch>(`/ingest/batches/${batchId}/close`, {
      method: 'POST',
      kbId: kbId(),
    })
  }

  async function fetchImportBatch(batchId: string) {
    return request<ImportBatch>(`/ingest/batches/${batchId}`, { kbId: kbId() })
  }

  async function fetchImportBatches(limit = 30) {
    return request<ImportBatch[]>(`/ingest/batches?limit=${limit}`, { kbId: kbId() })
  }

  async function importYuqueToken(data: {
    token: string
    repo: string
    compile_now?: boolean
    folder_id?: string | null
    create_notes?: boolean
  }) {
    const batch = await request<ImportBatch>('/ingest/yuque/token', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify(data),
    })
    await fetchTree()
    return batch
  }

  async function importYuqueZip(
    file: File,
    opts: {
      compile_now?: boolean
      folder_id?: string | null
      create_notes?: boolean
    } = {},
  ) {
    const fd = new FormData()
    fd.append('file', file)
    if (opts.compile_now) fd.append('compile_now', 'true')
    if (opts.folder_id) fd.append('folder_id', opts.folder_id)
    fd.append('create_notes', opts.create_notes === false ? 'false' : 'true')
    const batch = await upload<ImportBatch>('/ingest/yuque/zip', fd, kbId())
    await fetchTree()
    return batch
  }

  function stopImportPolling() {
    if (pollTimer !== null) {
      window.clearTimeout(pollTimer)
      pollTimer = null
    }
    importNoteId.value = null
  }

  function startImportPolling(noteId: string) {
    stopImportPolling()
    importNoteId.value = noteId
    importStatus.value = null
    const tick = async () => {
      if (importNoteId.value !== noteId) return
      try {
        const status = await request<ImportStatus>(`/notes/${noteId}/import`, {
          kbId: kbId(),
        })
        if (importNoteId.value !== noteId) return
        importStatus.value = status
        if (currentNote.value?.id === noteId) {
          const before = (currentNote.value.props_json?.import as any)?.status
          if (status.status === 'ready' || status.status === 'failed' || status.body_ready) {
            if (before !== status.status || status.body_ready) {
              const fresh = await request<NoteOut>(`/notes/${noteId}`, { kbId: kbId() })
              if (importNoteId.value !== noteId) return
              currentNote.value = fresh
              upsertSummary(fresh)
            }
          }
        }
        if (status.status !== 'importing') {
          stopImportPolling()
          await fetchTree()
          return
        }
      } catch {
        // 单次失败继续重试，直到组件切换或状态完成
      }
      if (importNoteId.value === noteId) {
        pollTimer = window.setTimeout(tick, 1500)
      }
    }
    void tick()
  }

  // ---------- 链接 ----------
  async function createLink(data: {
    url: string
    title?: string
    folder_id?: string | null
  }) {
    const note = await request<NoteOut>('/notes/link', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify(data),
    })
    await fetchTree()
    currentNote.value = note
    return note
  }

  async function refreshLink(id: string) {
    const note = await request<NoteOut>(`/notes/${id}/link/refresh`, {
      method: 'POST',
      kbId: kbId(),
    })
    if (currentNote.value?.id === id) currentNote.value = note
    upsertSummary(note)
    return note
  }

  // ---------- 反向链接 ----------
  async function getBacklinks(id: string) {
    return request<NoteSummary[]>(`/notes/${id}/backlinks`, { kbId: kbId() })
  }

  async function getRelated(id: string) {
    return request<RelatedNoteItem[]>(`/notes/related/${id}`, { kbId: kbId() })
  }

  // ---------- 标签 ----------
  async function fetchTags(q?: string) {
    const qs = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''
    tags.value = await request<NoteTag[]>(`/notes/tags${qs}`, { kbId: kbId() })
    return tags.value
  }

  async function createTag(name: string, parentId: string | null = null) {
    const tag = await request<NoteTag>('/notes/tags', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ name, parent_id: parentId }),
    })
    await fetchTags()
    return tag
  }

  async function updateTag(
    id: string,
    patch: { name?: string; parent_id?: string | null },
  ) {
    const tag = await request<NoteTag>(`/notes/tags/${id}`, {
      method: 'PATCH',
      kbId: kbId(),
      body: JSON.stringify(patch),
    })
    await fetchTags()
    return tag
  }

  async function deleteTag(id: string) {
    await request(`/notes/tags/${id}`, { method: 'DELETE', kbId: kbId() })
    await fetchTags()
    await fetchTree()
  }

  async function setNoteTags(id: string, names: string[]) {
    const note = await request<NoteOut>(`/notes/${id}/tags`, {
      method: 'PUT',
      kbId: kbId(),
      body: JSON.stringify({ names }),
    })
    if (currentNote.value?.id === id) currentNote.value = note
    upsertSummary(note)
    await fetchTags()
    return note
  }

  // ---------- 模板 ----------
  async function fetchTemplates() {
    templates.value = await request<NoteTemplate[]>('/notes/templates', { kbId: kbId() })
    return templates.value
  }

  async function createTemplate(data: {
    name: string
    description?: string
    icon?: string
    title_pattern?: string
    body_md?: string
    tags_json?: string[]
    props_json?: Record<string, any>
  }) {
    const template = await request<NoteTemplate>('/notes/templates', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify(data),
    })
    await fetchTemplates()
    return template
  }

  async function updateTemplate(id: string, patch: Partial<NoteTemplate>) {
    const template = await request<NoteTemplate>(`/notes/templates/${id}`, {
      method: 'PATCH',
      kbId: kbId(),
      body: JSON.stringify(patch),
    })
    await fetchTemplates()
    return template
  }

  async function deleteTemplate(id: string) {
    await request(`/notes/templates/${id}`, { method: 'DELETE', kbId: kbId() })
    await fetchTemplates()
  }

  async function useTemplate(
    id: string,
    opts: { title?: string; folder_id?: string | null } = {},
  ) {
    const note = await request<NoteOut>(`/notes/templates/${id}/use`, {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ title: opts.title, folder_id: opts.folder_id ?? null }),
    })
    await fetchTree()
    currentNote.value = note
    return note
  }

  // ---------- 快速捕获 ----------
  async function quickCapture(text: string, title?: string) {
    const note = await request<NoteOut>('/notes/quick-capture', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ text, title }),
    })
    await fetchTree()
    currentNote.value = note
    return note
  }

  // ---------- 搜索 ----------
  async function searchNotes(filters: NoteSearchFilters) {
    const params = new URLSearchParams()
    if (filters.q?.trim()) params.set('q', filters.q.trim())
    if (filters.folder_id) params.set('folder_id', filters.folder_id)
    if (filters.kind) params.set('kind', filters.kind)
    if (filters.status) params.set('status', filters.status)
    if (filters.created_from) params.set('created_from', filters.created_from)
    if (filters.created_to) params.set('created_to', filters.created_to)
    if (filters.updated_from) params.set('updated_from', filters.updated_from)
    if (filters.updated_to) params.set('updated_to', filters.updated_to)
    for (const tagId of filters.tag_ids ?? []) params.append('tag_ids', tagId)
    if (filters.limit) params.set('limit', String(filters.limit))
    if (filters.offset) params.set('offset', String(filters.offset))
    const qs = params.toString()
    return request<NoteSearchResult>(`/notes/search${qs ? `?${qs}` : ''}`, {
      kbId: filters.kb_id || kbId(),
    })
  }

  // ---------- 生命周期 ----------
  function dropFromTree(id: string) {
    notes.value = notes.value.filter((n) => n.id !== id)
    if (currentNote.value?.id === id) currentNote.value = null
    if (importNoteId.value === id) stopImportPolling()
  }

  async function archiveNote(id: string) {
    const note = await request<NoteOut>(`/notes/${id}/archive`, {
      method: 'POST',
      kbId: kbId(),
    })
    dropFromTree(id)
    return note
  }

  async function unarchiveNote(id: string) {
    const note = await request<NoteOut>(`/notes/${id}/unarchive`, {
      method: 'POST',
      kbId: kbId(),
    })
    archived.value = archived.value.filter((n) => n.id !== id)
    await fetchTree()
    return note
  }

  async function fetchArchived() {
    const res = await request<{ total: number; items: NoteSummary[] }>(
      '/notes/archived',
      { kbId: kbId() },
    )
    archived.value = res.items
    return res
  }

  async function fetchTrash() {
    trash.value = await request<NoteTrash>('/notes/trash', { kbId: kbId() })
    return trash.value
  }

  async function restoreNote(id: string) {
    const note = await request<NoteOut>(`/notes/${id}/restore`, {
      method: 'POST',
      kbId: kbId(),
    })
    if (trash.value) {
      trash.value = {
        ...trash.value,
        total: Math.max(0, trash.value.total - 1),
        items: trash.value.items.filter((n) => n.id !== id),
      }
    }
    await fetchTree()
    return note
  }

  async function permanentDeleteNote(id: string) {
    await request(`/notes/${id}/permanent`, { method: 'DELETE', kbId: kbId() })
    if (trash.value) {
      trash.value = {
        ...trash.value,
        total: Math.max(0, trash.value.total - 1),
        items: trash.value.items.filter((n) => n.id !== id),
      }
    }
  }

  async function emptyTrash() {
    await request('/notes/trash', { method: 'DELETE', kbId: kbId() })
    trash.value = { total: 0, items: [], retention_days: 30 }
  }

  // ---------- 编译 / Wiki 关联 / 学习要点 ----------
  async function compileNote(id: string) {
    return request<{ job_id: string; source_id: string; reused_source: boolean }>(
      `/notes/${id}/compile`,
      { method: 'POST', kbId: kbId() },
    )
  }

  async function compileAllNotes(limit = 20) {
    return request<{
      jobs: Array<{
        job_id: string
        note_id: string
        note_title: string
        source_id: string
      }>
      count: number
      candidates: number
      skipped_empty: number
      skipped_busy: number
      skipped_limit: number
    }>(`/notes/compile-all?limit=${limit}`, { method: 'POST', kbId: kbId() })
  }

  async function getCompileStatus(id: string) {
    return request<NoteCompileStatus>(`/notes/${id}/compile/status`, {
      kbId: kbId(),
    })
  }

  async function getNoteWiki(id: string) {
    return request<NoteWikiLink>(`/notes/${id}/wiki`, { kbId: kbId() })
  }

  async function setNoteWiki(id: string, wikiPageId: string | null) {
    return request<NoteWikiLink>(`/notes/${id}/wiki`, {
      method: 'PUT',
      kbId: kbId(),
      body: JSON.stringify({ wiki_page_id: wikiPageId }),
    })
  }

  async function getStudyPoints(id: string) {
    return request<NoteStudyPoint[]>(`/notes/${id}/study-points`, { kbId: kbId() })
  }

  async function setStudyPoints(
    id: string,
    points: Array<{ text: string; wiki_slug?: string | null }>,
  ) {
    return request<NoteStudyPoint[]>(`/notes/${id}/study-points`, {
      method: 'PUT',
      kbId: kbId(),
      body: JSON.stringify({ points }),
    })
  }

  function resetForKb() {
    folders.value = []
    notes.value = []
    currentNote.value = null
    tags.value = []
    templates.value = []
    archived.value = []
    trash.value = null
    stopImportPolling()
  }

  return {
    folders,
    notes,
    currentNote,
    loading,
    treeLoading,
    importStatus,
    importNoteId,
    tags,
    templates,
    archived,
    trash,
    fetchTree,
    getNote,
    createNote,
    updateNote,
    moveNote,
    deleteNote,
    copyNote,
    transferNote,
    createFolder,
    updateFolder,
    deleteFolder,
    reorder,
    importFile,
    importNotebook,
    importRemoteFile,
    previewTable,
    importTable,
    createImportBatch,
    closeImportBatch,
    fetchImportBatch,
    fetchImportBatches,
    importYuqueToken,
    importYuqueZip,
    startImportPolling,
    stopImportPolling,
    createLink,
    refreshLink,
    getBacklinks,
    getRelated,
    fetchTags,
    createTag,
    updateTag,
    deleteTag,
    setNoteTags,
    fetchTemplates,
    createTemplate,
    updateTemplate,
    deleteTemplate,
    useTemplate,
    quickCapture,
    searchNotes,
    archiveNote,
    unarchiveNote,
    fetchArchived,
    fetchTrash,
    restoreNote,
    permanentDeleteNote,
    emptyTrash,
    compileNote,
    compileAllNotes,
    getCompileStatus,
    getNoteWiki,
    setNoteWiki,
    getStudyPoints,
    setStudyPoints,
    resetForKb,
  }
})
