<script setup lang="ts">
/**
 * 知识库问答：会话历史、单库 / 多库 / 全局范围、Wiki/笔记意图路由、
 * 多轮对话、可点击引用、页面级模型覆盖与「回写为 Wiki 综合页」。
 *
 * 会话持久化在后端：刷新页面或切换视图后可继续历史对话；侧栏支持
 * 新建、重命名与删除。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useLlmStore } from '@/stores/llm'
import { useDesktopStore } from '@/stores/desktop'
import { openSSE } from '@/api/sse'
import { request } from '@/api/client'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import { toast } from '@/components/ui/toast'

interface Citation {
  /** 网页来源没有知识库归属。 */
  kb_id?: string | null
  kb_name: string
  collection: string
  title: string
  slug?: string | null
  chunk_text: string
  target_id: string
  kind?: string
  chunk_index?: number
  heading?: string
  quote?: string
  /** 联网检索来源的原始链接。 */
  url?: string
}

/** @ 指定的笔记 / 目录（仅作为本轮检索范围，不改变知识库选择）。 */
interface MentionRef {
  type: 'note' | 'folder'
  id: string
  title: string
}

interface MentionNote {
  id: string
  title: string
  kind: string
  folder_id: string | null
  parent_note_id: string | null
}

interface MentionFolder {
  id: string
  name: string
  parent_id: string | null
}

/** @ 选择器里的层级节点：目录可包含子目录与笔记，笔记可包含子文档。 */
interface MentionTreeNode {
  key: string
  type: 'folder' | 'note'
  id: string
  title: string
  kind?: string
  children: MentionTreeNode[]
}

interface ScopeFilters {
  note_kinds: string[]
  tag_ids: string[]
  updated_from: string
  updated_to: string
}

interface TagOption {
  id: string
  name: string
}

/** 流式回答的思考阶段：检索、联网、生成等，让等待过程可见。 */
interface ChatStep {
  id: string
  message: string
  detail?: string
  status: 'active' | 'done' | 'error'
}

interface Msg {
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  streaming?: boolean
  steps?: ChatStep[]
  startedAt?: number
  /** 流式结束时间，用于在完成后展示「用时」摘要。 */
  finishedAt?: number
  /** 完成后是否展开步骤明细；默认收起，点击摘要展开。 */
  stepsOpen?: boolean
  created_at?: string
}

interface SessionSummary {
  id: string
  title: string
  message_count: number
  scope: {
    kb_ids?: string[]
    scope?: ScopeMode
    note_kinds?: string[]
    tag_ids?: string[]
    updated_from?: string | null
    updated_to?: string | null
    note_ids?: string[]
    folder_ids?: string[]
    mentions?: MentionRef[]
  }
  /** 兼容旧数据：早期会话可能保存 raw，前端统一按 note 处理 */
  intent: Intent | 'raw'
  llm_config_id: string | null
  last_message_at: string | null
  updated_at: string
}

interface SessionDetail extends SessionSummary {
  messages: Msg[]
}

type ScopeMode = 'kb' | 'multi' | 'global'
type Intent = 'auto' | 'wiki' | 'note'

const SETTINGS_KEY = 'kiwi.chat.settings.v1'
const LEGACY_KEY = 'kiwi.chat.state.v1'

const kbs = useKbsStore()
const llm = useLlmStore()
const desktop = useDesktopStore()
/** 仅桌面构建 + 状态已就绪 + 没有可用大模型时拦截发送。 */
const llmMissing = computed(
  () => desktop.isDesktop && desktop.ready && !desktop.llmConfigured,
)
const router = useRouter()

const messages = ref<Msg[]>([])
const input = ref('')
const streaming = ref(false)
/** 流式等待计时器：让「已等待 N 秒」实时跳动，避免看起来卡死。 */
const nowTick = ref(Date.now())
const scrollEl = ref<HTMLElement>()
const autoScroll = ref(true)

const scopeMode = ref<ScopeMode>('kb')
const multiIds = ref<string[]>([])
const intent = ref<Intent>('auto')
const llmConfigId = ref('')
const scopeMenuOpen = ref(false)
const filterMenuOpen = ref(false)
const intentMenuOpen = ref(false)
const modelMenuOpen = ref(false)
const filterTags = ref<TagOption[]>([])
const filterTagsLoading = ref(false)
const filterKinds = ref<string[]>([])
const filterTagIds = ref<string[]>([])
const filterFrom = ref('')
const filterTo = ref('')

// ---------- @ 笔记 / 目录与 Agent 开关 ----------
const mentions = ref<MentionRef[]>([])
const mentionOpen = ref(false)
const mentionQuery = ref('')
const mentionLoading = ref(false)
const mentionNotes = ref<MentionNote[]>([])
const mentionFolders = ref<MentionFolder[]>([])
const mentionExpanded = ref<string[]>([])
const mentionActiveIndex = ref(0)
/** 输入框中触发 @ 的那段文本范围，选择后从正文里移除。 */
const mentionToken = ref<{ start: number; end: number } | null>(null)
const agentMode = ref(false)
const webSearch = ref(false)
const NOTE_KIND_OPTIONS = [
  { id: 'doc', label: '文档' },
  { id: 'import', label: '导入' },
  { id: 'database', label: '数据表' },
  { id: 'canvas', label: '画布' },
  { id: 'notebook', label: 'Notebook' },
  { id: 'link', label: '链接' },
]

// ---------- 会话列表 ----------
const sessions = ref<SessionSummary[]>([])
const currentSessionId = ref('')
const sessionsLoading = ref(false)
const sessionLoading = ref(false)
const sidebarOpen = ref(false)
const renamingId = ref('')
const renameTitle = ref('')
const deleteTarget = ref<SessionSummary | null>(null)
const clearOpen = ref(false)
const saving = ref(false)
const pendingSave = ref(false)
const activeCite = ref<{ msg: number; cite: number } | null>(null)
const sessionQuery = ref('')
const expandedCites = ref<Record<number, boolean>>({})
const showJump = ref(false)
const composerEl = ref<HTMLTextAreaElement>()

const filteredSessions = computed(() => {
  const query = sessionQuery.value.trim().toLowerCase()
  if (!query) return sessions.value
  return sessions.value.filter((item) => item.title.toLowerCase().includes(query))
})

const currentSession = computed(
  () => sessions.value.find((item) => item.id === currentSessionId.value) || null,
)

const currentTitle = computed(() => {
  const title = currentSession.value?.title
  if (title && title !== '新对话') return title
  const firstQuestion = messages.value
    .find((message) => message.role === 'user')
    ?.content.replace(/\s+/g, ' ')
    .slice(0, 40)
  return firstQuestion || title || '新对话'
})

const turnCount = computed(
  () => messages.value.filter((message) => message.role === 'user').length,
)

// ---------- 本地设置（范围 / 意图） ----------
function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    if (!raw) return
    const saved = JSON.parse(raw) as {
      scopeMode?: ScopeMode
      multiIds?: string[]
      intent?: Intent | 'raw'
      llmConfigId?: string
      agentMode?: boolean
      webSearch?: boolean
      filters?: Partial<ScopeFilters>
    }
    if (saved.scopeMode) scopeMode.value = saved.scopeMode
    if (Array.isArray(saved.multiIds)) multiIds.value = saved.multiIds
    const filters = saved.filters
    if (filters) {
      if (Array.isArray(filters.note_kinds)) filterKinds.value = filters.note_kinds
      if (Array.isArray(filters.tag_ids)) filterTagIds.value = filters.tag_ids
      if (typeof filters.updated_from === 'string') filterFrom.value = filters.updated_from
      if (typeof filters.updated_to === 'string') filterTo.value = filters.updated_to
    }
    if (saved.intent === 'raw') intent.value = 'note'
    else if (saved.intent) intent.value = saved.intent
    if (typeof saved.llmConfigId === 'string') llmConfigId.value = saved.llmConfigId
    if (typeof saved.agentMode === 'boolean') agentMode.value = saved.agentMode
    if (typeof saved.webSearch === 'boolean') webSearch.value = saved.webSearch
  } catch {
    /* 隐私模式忽略 */
  }
}

function saveSettings() {
  try {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({
        scopeMode: scopeMode.value,
        multiIds: multiIds.value,
        intent: intent.value,
        llmConfigId: llmConfigId.value,
        agentMode: agentMode.value,
        webSearch: webSearch.value,
        filters: {
          note_kinds: filterKinds.value,
          tag_ids: filterTagIds.value,
          updated_from: filterFrom.value,
          updated_to: filterTo.value,
        },
      }),
    )
  } catch {
    /* 忽略配额错误 */
  }
}

// ---------- 旧版单会话迁移 ----------
function readLegacyMessages(): { messages: Msg[]; scopeMode?: ScopeMode; multiIds?: string[] } {
  try {
    const raw = localStorage.getItem(LEGACY_KEY)
    if (!raw) return { messages: [] }
    const saved = JSON.parse(raw) as {
      messages?: Msg[]
      scopeMode?: ScopeMode
      multiIds?: string[]
      intent?: Intent | 'raw'
    }
    const valid = (saved.messages || [])
      .filter((m) => m && (m.role === 'user' || m.role === 'assistant'))
      .map((m) => ({
        role: m.role,
        content: String(m.content || ''),
        citations: Array.isArray(m.citations) ? m.citations : [],
        created_at: m.created_at,
      }))
    return { messages: valid, scopeMode: saved.scopeMode, multiIds: saved.multiIds }
  } catch {
    return { messages: [] }
  }
}

let streamTickTimer: number | undefined
onMounted(async () => {
  streamTickTimer = window.setInterval(() => {
    if (streaming.value) nowTick.value = Date.now()
  }, 500)
  document.addEventListener('click', onDocumentClick)
  loadSettings()
  await Promise.all([
    kbs.kbs.length ? Promise.resolve() : kbs.fetchKbs().catch(() => undefined),
    llm.configs.length ? Promise.resolve() : llm.fetchConfigs().catch(() => undefined),
  ])
  await bootstrapSessions()
  bootstrappedSessions = true
  scrollToBottom(true)
})
let bootstrappedSessions = false

/** 切换知识库后刷新会话列表：会话按知识库隔离，旧会话不应留在新库下。 */
watch(
  () => kbs.currentKbId,
  async (id, previous) => {
    if (!bootstrappedSessions || sessionLoading.value || !id || id === previous) return
    if (streaming.value) return
    mentions.value = []
    currentSessionId.value = ''
    messages.value = []
    activeCite.value = null
    expandedCites.value = {}
    await fetchSessions()
    if (sessions.value.length) await loadSession(sessions.value[0].id)
  },
)
onUnmounted(() => {
  window.clearInterval(streamTickTimer)
  document.removeEventListener('click', onDocumentClick)
  saveSettings()
  window.clearTimeout(saveTimer)
  void saveSessionNow()
})

// ---------- 会话 API ----------
function scopeFromSession(item: SessionSummary) {
  const scope = item.scope || {}
  if (scope.scope === 'global' || scope.scope === 'multi' || scope.scope === 'kb') {
    scopeMode.value = scope.scope
  }
  if (Array.isArray(scope.kb_ids)) multiIds.value = scope.kb_ids.map(String)
  filterKinds.value = Array.isArray(scope.note_kinds) ? scope.note_kinds.map(String) : []
  filterTagIds.value = Array.isArray(scope.tag_ids) ? scope.tag_ids.map(String) : []
  filterFrom.value = typeof scope.updated_from === 'string' ? scope.updated_from.slice(0, 10) : ''
  filterTo.value = typeof scope.updated_to === 'string' ? scope.updated_to.slice(0, 10) : ''
  // @ 笔记 / 目录：优先用会话里保存的标题；旧会话只有 id 时给通用名称。
  const savedMentions = Array.isArray(scope.mentions) ? scope.mentions : []
  if (savedMentions.length) {
    mentions.value = savedMentions
      .filter((m) => m && (m.type === 'note' || m.type === 'folder') && m.id)
      .map((m) => ({
        type: m.type,
        id: String(m.id),
        title: String(m.title || (m.type === 'note' ? '笔记' : '目录')),
      }))
  } else {
    const noteIds = Array.isArray(scope.note_ids) ? scope.note_ids : []
    const folderIds = Array.isArray(scope.folder_ids) ? scope.folder_ids : []
    mentions.value = [
      ...noteIds.map((id) => ({ type: 'note' as const, id: String(id), title: '笔记' })),
      ...folderIds.map((id) => ({ type: 'folder' as const, id: String(id), title: '目录' })),
    ]
  }
  if (item.intent === 'raw') intent.value = 'note'
  else if (item.intent) intent.value = item.intent
  llmConfigId.value = item.llm_config_id || ''
}

let hydratingSession = false
function applySession(detail: SessionDetail) {
  hydratingSession = true
  currentSessionId.value = detail.id
  const loaded: Msg[] = (detail.messages || []).map((m) => ({
    role: m.role,
    content: String(m.content || ''),
    citations: Array.isArray(m.citations) ? m.citations : [],
    streaming: false,
    created_at: m.created_at,
  }))
  // 历史消息同样只展示正文实际引用的来源；旧数据里的编号一并重排。
  for (const message of loaded) {
    if (message.role === 'assistant') normalizeCitations(message, message.citations)
  }
  messages.value = loaded
  scopeFromSession(detail)
  saveSettings()
  sidebarOpen.value = false
  scrollToBottom(true)
  void nextTick(() => {
    hydratingSession = false
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

function sessionsPath(): string {
  const kb = kbs.currentKbId
  return kb ? `/chat/sessions?kb_id=${encodeURIComponent(kb)}` : '/chat/sessions'
}

async function fetchSessions() {
  sessionsLoading.value = true
  try {
    const res = await request<{ items: SessionSummary[] }>(sessionsPath())
    sessions.value = res.items || []
  } catch (e: any) {
    toast.error(e.message || '会话列表加载失败')
  } finally {
    sessionsLoading.value = false
  }
}

async function bootstrapSessions() {
  sessionLoading.value = true
  try {
    await fetchSessions()
    if (sessions.value.length) {
      await loadSession(sessions.value[0].id)
      return
    }
    // 首次升级：把旧版 localStorage 中的会话迁移到后端。
    const legacy = readLegacyMessages()
    if (legacy.messages.length) {
      if (legacy.scopeMode) scopeMode.value = legacy.scopeMode
      if (Array.isArray(legacy.multiIds)) multiIds.value = legacy.multiIds
      const created = await request<SessionDetail>('/chat/sessions', {
        method: 'POST',
        body: JSON.stringify({
          messages: legacy.messages,
          scope: { kb_ids: scopeKbIds.value, scope: scopeMode.value },
          intent: intent.value,
          llm_config_id: llmConfigId.value || null,
        }),
      })
      try {
        localStorage.removeItem(LEGACY_KEY)
      } catch {
        /* 忽略 */
      }
      sessions.value = [created]
      applySession(created)
    }
  } catch (e: any) {
    toast.error(e.message || '会话初始化失败')
  } finally {
    sessionLoading.value = false
  }
}

async function loadSession(id: string) {
  if (streaming.value || !id) return
  if (id === currentSessionId.value) {
    sidebarOpen.value = false
    return
  }
  sessionLoading.value = true
  try {
    const detail = await request<SessionDetail>(`/chat/sessions/${id}`)
    if (detail.messages.length) {
      applySession(detail)
    } else {
      // 空会话：仍恢复范围与设置，但不覆盖当前正在编辑的内容。
      hydratingSession = true
      currentSessionId.value = detail.id
      messages.value = []
      scopeFromSession(detail)
      saveSettings()
      sidebarOpen.value = false
      void nextTick(() => {
        hydratingSession = false
      })
    }
  } catch (e: any) {
    toast.error(e.message || '会话加载失败')
  } finally {
    sessionLoading.value = false
  }
}

function sessionScopePayload() {
  return {
    kb_ids: scopeKbIds.value,
    scope: scopeMode.value,
    ...filtersPayload(),
    // 保存标题，刷新后 @ 选择器仍能显示可读名称（后端检索只用 id）。
    mentions: mentions.value.map((m) => ({ ...m })),
  }
}

function filtersPayload() {
  return {
    note_kinds: [...filterKinds.value],
    // 标签只在当前知识库内有意义；多库 / 全局时仍按 tag id 过滤，
    // 其他库的同名标签不会误命中。
    tag_ids: [...filterTagIds.value],
    updated_from: filterFrom.value ? new Date(`${filterFrom.value}T00:00:00`).toISOString() : null,
    updated_to: filterTo.value ? new Date(`${filterTo.value}T23:59:59`).toISOString() : null,
    // @ 指定笔记 / 目录：两者取并集，作为本轮检索的笔记范围。
    note_ids: mentions.value.filter((m) => m.type === 'note').map((m) => m.id),
    folder_ids: mentions.value.filter((m) => m.type === 'folder').map((m) => m.id),
  }
}

const activeFilterCount = computed(
  () =>
    filterKinds.value.length +
    filterTagIds.value.length +
    (filterFrom.value ? 1 : 0) +
    (filterTo.value ? 1 : 0),
)

function toggleFilterKind(kind: string) {
  const index = filterKinds.value.indexOf(kind)
  if (index >= 0) filterKinds.value.splice(index, 1)
  else filterKinds.value.push(kind)
}

function toggleFilterTag(id: string) {
  const index = filterTagIds.value.indexOf(id)
  if (index >= 0) filterTagIds.value.splice(index, 1)
  else filterTagIds.value.push(id)
}

function clearFilters() {
  filterKinds.value = []
  filterTagIds.value = []
  filterFrom.value = ''
  filterTo.value = ''
}

async function toggleFilterMenu() {
  const next = !filterMenuOpen.value
  closeHeaderMenus()
  filterMenuOpen.value = next
  if (!next || filterTags.value.length) return
  filterTagsLoading.value = true
  try {
    if (!kbs.currentKbId) return
    filterTags.value = await request<TagOption[]>('/notes/tags', {
      kbId: kbs.currentKbId,
    })
  } catch {
    /* 标签加载失败不阻塞其他筛选 */
  } finally {
    filterTagsLoading.value = false
  }
}

// ---------- @ 笔记 / 目录选择器 ----------
/** 目录的完整路径（用于 chip 标题与搜索匹配）。 */
const mentionFolderPaths = computed(() => {
  const byId = new Map(mentionFolders.value.map((folder) => [folder.id, folder]))
  const paths = new Map<string, string>()
  for (const folder of mentionFolders.value) {
    const names = [folder.name]
    let parent = folder.parent_id
    let guard = 0
    while (parent && guard < 12) {
      const node = byId.get(parent)
      if (!node) break
      names.unshift(node.name)
      parent = node.parent_id
      guard += 1
    }
    paths.set(folder.id, names.join(' / '))
  }
  return paths
})

/** 目录树：目录可嵌套目录，笔记挂在目录或父笔记下。 */
const mentionTree = computed<MentionTreeNode[]>(() => {
  const folderNodes = new Map<string, MentionTreeNode>()
  const noteNodes = new Map<string, MentionTreeNode>()
  for (const folder of mentionFolders.value) {
    folderNodes.set(folder.id, {
      key: `folder:${folder.id}`,
      type: 'folder',
      id: folder.id,
      title: folder.name,
      children: [],
    })
  }
  for (const note of mentionNotes.value) {
    noteNodes.set(note.id, {
      key: `note:${note.id}`,
      type: 'note',
      id: note.id,
      title: note.title || '未命名笔记',
      kind: note.kind,
      children: [],
    })
  }
  const roots: MentionTreeNode[] = []
  for (const folder of mentionFolders.value) {
    const node = folderNodes.get(folder.id)
    if (!node) continue
    const parent = folder.parent_id ? folderNodes.get(folder.parent_id) : undefined
    if (parent && parent !== node) parent.children.push(node)
    else roots.push(node)
  }
  for (const note of mentionNotes.value) {
    const node = noteNodes.get(note.id)
    if (!node) continue
    const parentNote = note.parent_note_id ? noteNodes.get(note.parent_note_id) : undefined
    const parentFolder = note.folder_id ? folderNodes.get(note.folder_id) : undefined
    if (parentNote && parentNote !== node) parentNote.children.push(node)
    else if (parentFolder) parentFolder.children.push(node)
    else roots.push(node)
  }
  return roots
})

/** 搜索时保留命中节点及其祖先；命中目录时保留整棵子树。 */
const mentionTreeView = computed<MentionTreeNode[]>(() => {
  const query = mentionQuery.value.trim().toLowerCase()
  if (!query) return mentionTree.value
  const filter = (nodes: MentionTreeNode[]): MentionTreeNode[] => {
    const out: MentionTreeNode[] = []
    for (const node of nodes) {
      const children = filter(node.children)
      const path = node.type === 'folder' ? mentionFolderPaths.value.get(node.id) || '' : ''
      const hit =
        node.title.toLowerCase().includes(query) || path.toLowerCase().includes(query)
      if (!hit && !children.length) continue
      out.push({ ...node, children: hit ? node.children : children })
    }
    return out
  }
  return filter(mentionTree.value)
})

function isMentionExpanded(key: string): boolean {
  return Boolean(mentionQuery.value.trim()) || mentionExpanded.value.includes(key)
}

function toggleMentionExpand(key: string) {
  const index = mentionExpanded.value.indexOf(key)
  if (index >= 0) mentionExpanded.value.splice(index, 1)
  else mentionExpanded.value.push(key)
}

/** 当前可见行（用于渲染和键盘上下选择）。 */
const mentionRows = computed(() => {
  const rows: { node: MentionTreeNode; depth: number }[] = []
  const walk = (nodes: MentionTreeNode[], depth: number) => {
    for (const node of nodes) {
      rows.push({ node, depth })
      if (node.children.length && isMentionExpanded(node.key)) {
        walk(node.children, depth + 1)
      }
    }
  }
  walk(mentionTreeView.value, 0)
  return rows
})

watch(mentionQuery, () => {
  mentionActiveIndex.value = 0
})

async function loadMentionCandidates() {
  const kb = kbs.currentKbId
  if (!kb) return
  mentionLoading.value = true
  try {
    const tree = await request<{ folders: MentionFolder[]; notes: MentionNote[] }>(
      '/notes/tree',
      { kbId: kb },
    )
    mentionFolders.value = tree.folders || []
    mentionNotes.value = (tree.notes || []).map((note) => ({
      id: String(note.id),
      title: note.title,
      kind: note.kind,
      folder_id: note.folder_id ? String(note.folder_id) : null,
      parent_note_id: note.parent_note_id ? String(note.parent_note_id) : null,
    }))
  } catch {
    /* 候选加载失败不阻断提问；当前范围仍可继续使用 */
  } finally {
    mentionLoading.value = false
  }
}

/** 读取光标前最后一个 `@关键词`，没有则返回 null。 */
function findMentionToken(): { query: string; start: number; end: number } | null {
  const el = composerEl.value
  const caret = el?.selectionStart ?? input.value.length
  const before = input.value.slice(0, caret)
  const match = before.match(/(?:^|[\s(（])@([^\s@]*)$/)
  if (!match) return null
  return { query: match[1], start: caret - match[1].length - 1, end: caret }
}

function onComposerInput() {
  resizeComposer()
  const token = findMentionToken()
  if (!token) {
    if (mentionOpen.value) closeMention()
    return
  }
  mentionToken.value = { start: token.start, end: token.end }
  mentionQuery.value = token.query
  if (!mentionOpen.value) {
    mentionOpen.value = true
    mentionActiveIndex.value = 0
    void loadMentionCandidates()
  }
}

function closeMention() {
  mentionOpen.value = false
  mentionQuery.value = ''
  mentionToken.value = null
  mentionActiveIndex.value = 0
}

function isMentioned(type: MentionRef['type'], id: string): boolean {
  return mentions.value.some((item) => item.type === type && item.id === id)
}

function toggleMention(type: MentionRef['type'], id: string, title: string) {
  const index = mentions.value.findIndex((item) => item.type === type && item.id === id)
  if (index >= 0) mentions.value.splice(index, 1)
  else mentions.value.push({ type, id, title })
}

/** 选中节点：把输入框里的 `@关键词` 替换为已选 chip。 */
function chooseMention(node: MentionTreeNode) {
  const token = mentionToken.value ?? findMentionToken()
  if (token) {
    input.value = input.value.slice(0, token.start) + input.value.slice(token.end)
  }
  const title =
    node.type === 'folder'
      ? mentionFolderPaths.value.get(node.id) || node.title
      : node.title
  toggleMention(node.type, node.id, title)
  const caret = token?.start ?? input.value.length
  closeMention()
  void nextTick(() => {
    resizeComposer()
    composerEl.value?.focus()
    composerEl.value?.setSelectionRange(caret, caret)
  })
}

function mentionMove(delta: number) {
  const total = mentionRows.value.length
  if (!total) return
  mentionActiveIndex.value =
    (mentionActiveIndex.value + delta + total) % total
  void nextTick(() => {
    document
      .querySelector('[data-mention-active="true"]')
      ?.scrollIntoView({ block: 'nearest' })
  })
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.isComposing) return
  if (mentionOpen.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeMention()
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      mentionMove(event.key === 'ArrowDown' ? 1 : -1)
      return
    }
    if (event.key === 'Tab') {
      // Tab 展开目录；已展开时再按 Tab 跳到第一个子节点，Shift+Tab 折叠。
      const row = mentionRows.value[mentionActiveIndex.value]
      if (row?.node.children.length) {
        event.preventDefault()
        if (!isMentionExpanded(row.node.key)) toggleMentionExpand(row.node.key)
        else if (event.shiftKey) toggleMentionExpand(row.node.key)
        else mentionMove(1)
      } else {
        // 面板打开时不让 Tab 把焦点移出输入框。
        event.preventDefault()
      }
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      const row = mentionRows.value[mentionActiveIndex.value]
      if (row) chooseMention(row.node)
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void ask()
  }
}

function removeMention(index: number) {
  mentions.value.splice(index, 1)
}

function toggleAgent() {
  agentMode.value = !agentMode.value
  saveSettings()
}

function toggleWebSearch() {
  webSearch.value = !webSearch.value
  saveSettings()
}

async function createSession(): Promise<SessionDetail | null> {
  try {
    const created = await request<SessionDetail>('/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({
        scope: sessionScopePayload(),
        intent: intent.value,
        llm_config_id: llmConfigId.value || null,
      }),
    })
    sessions.value = [created, ...sessions.value]
    currentSessionId.value = created.id
    return created
  } catch (e: any) {
    toast.error(e.message || '新建会话失败')
    return null
  }
}

async function ensureSession(): Promise<boolean> {
  if (currentSessionId.value) return true
  return (await createSession()) !== null
}

function sessionPayload() {
  return {
    title: undefined as string | undefined,
    messages: messages.value
      .filter((m) => !m.streaming)
      .map((m) => ({
        role: m.role,
        content: m.content,
        citations: m.citations,
        created_at: m.created_at,
      })),
    scope: sessionScopePayload(),
    intent: intent.value,
    llm_config_id: llmConfigId.value || null,
  }
}

async function saveSessionNow() {
  const id = currentSessionId.value
  if (!id) return
  if (saving.value) {
    pendingSave.value = true
    return
  }
  saving.value = true
  try {
    const updated = await request<SessionDetail>(`/chat/sessions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(sessionPayload()),
    })
    const index = sessions.value.findIndex((item) => item.id === id)
    if (index >= 0) {
      sessions.value[index] = { ...sessions.value[index], ...updated, messages: undefined } as any
      // 最近使用的会话排到最前
      const [current] = sessions.value.splice(index, 1)
      sessions.value.unshift(current)
    }
  } catch (e: any) {
    console.warn('保存会话失败', e)
  } finally {
    saving.value = false
    if (pendingSave.value) {
      pendingSave.value = false
      void saveSessionNow()
    }
  }
}

let saveTimer: number | undefined
function scheduleSave(delay = 500) {
  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => void saveSessionNow(), delay)
}

function newConversation() {
  if (streaming.value) {
    toast.info('请等待当前回答完成')
    return
  }
  currentSessionId.value = ''
  messages.value = []
  activeCite.value = null
  expandedCites.value = {}
  showJump.value = false
  sidebarOpen.value = false
  autoScroll.value = true
}

function startRename(item: SessionSummary) {
  renamingId.value = item.id
  renameTitle.value = item.title
  nextTick(() => {
    const input = document.querySelector<HTMLInputElement>(
      `[data-rename-input="${item.id}"]`,
    )
    input?.focus()
    input?.select()
  })
}

async function commitRename(item: SessionSummary) {
  if (renamingId.value !== item.id) return
  const title = renameTitle.value.trim()
  renamingId.value = ''
  if (!title || title === item.title) return
  const previous = item.title
  item.title = title
  try {
    const updated = await request<SessionDetail>(`/chat/sessions/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    })
    item.title = updated.title
  } catch (e: any) {
    item.title = previous
    toast.error(e.message || '重命名失败')
  }
}

async function deleteSession() {
  const target = deleteTarget.value
  if (!target) return
  deleteTarget.value = null
  try {
    await request(`/chat/sessions/${target.id}`, { method: 'DELETE' })
    sessions.value = sessions.value.filter((item) => item.id !== target.id)
    if (currentSessionId.value === target.id) newConversation()
    toast.success('会话已删除')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

async function clearAllSessions() {
  clearOpen.value = false
  try {
    await request(sessionsPath(), { method: 'DELETE' })
    sessions.value = []
    newConversation()
    toast.success('当前知识库的会话历史已清空')
  } catch (e: any) {
    toast.error(e.message || '清空失败')
  }
}

// ---------- 展示 ----------
function pushUser(text: string) {
  messages.value.push({
    role: 'user',
    content: text,
    citations: [],
    created_at: new Date().toISOString(),
  })
}

function pushAssistant() {
  const msg: Msg = {
    role: 'assistant',
    content: '',
    citations: [],
    streaming: true,
    steps: [],
    startedAt: Date.now(),
    created_at: new Date().toISOString(),
  }
  messages.value.push(msg)
  return msg
}

function scrollToBottom(force = false) {
  if (!autoScroll.value && !force) return
  if (force) showJump.value = false
  void nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

function onScroll() {
  if (!scrollEl.value) return
  const el = scrollEl.value
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  showJump.value = !autoScroll.value && messages.value.length > 0
}

function jumpToBottom() {
  autoScroll.value = true
  showJump.value = false
  scrollToBottom(true)
}

function resizeComposer() {
  const el = composerEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 144)}px`
}

const scopeKbIds = computed(() => {
  if (scopeMode.value === 'global') return []
  if (scopeMode.value === 'multi') return multiIds.value
  return kbs.currentKbId ? [kbs.currentKbId] : []
})

function requestScope() {
  return {
    kb_ids: scopeKbIds.value,
    scope: scopeMode.value,
    ...filtersPayload(),
  }
}

function validateScope(): boolean {
  if (scopeMode.value === 'global') return true
  if (scopeMode.value === 'multi' && !multiIds.value.length) {
    toast.info('请勾选至少一个知识库')
    return false
  }
  if (scopeMode.value === 'kb' && !kbs.currentKbId) {
    toast.info('请先选择一个知识库')
    return false
  }
  return true
}

function toggleMultiKb(id: string) {
  const index = multiIds.value.indexOf(id)
  if (index >= 0) multiIds.value.splice(index, 1)
  else multiIds.value.push(id)
  scopeMode.value = 'multi'
}

const scopeLabel = computed(() => {
  if (scopeMode.value === 'global') return '全局（全部知识库）'
  if (scopeMode.value === 'multi') {
    if (!multiIds.value.length) return '多库（未选择）'
    return `多库（${multiIds.value.length} 个）`
  }
  return kbs.currentKb?.name || '未选择知识库'
})

const intentOptions: { id: Intent; label: string; hint: string }[] = [
  { id: 'auto', label: '自动路由', hint: '按问题类型在 Wiki 与笔记之间自动选择侧重' },
  { id: 'wiki', label: 'Wiki 优先', hint: '概念解释、综合对比，沿链接扩展 1-2 跳' },
  { id: 'note', label: '笔记优先', hint: '精确引用、事实核验，优先检索笔记与出处' },
]

const intentLabel = computed(
  () => intentOptions.find((opt) => opt.id === intent.value)?.label || '自动路由',
)
const intentHint = computed(
  () => intentOptions.find((opt) => opt.id === intent.value)?.hint || '',
)
const currentLlmConfig = computed(() =>
  llm.configs.find((cfg) => cfg.id === llmConfigId.value),
)
const modelLabel = computed(() => currentLlmConfig.value?.name || '默认模型')
const modelHint = computed(() =>
  currentLlmConfig.value
    ? `${currentLlmConfig.value.name} · ${currentLlmConfig.value.model_name}`
    : '使用知识库或全局默认模型',
)

function closeHeaderMenus() {
  scopeMenuOpen.value = false
  filterMenuOpen.value = false
  intentMenuOpen.value = false
  modelMenuOpen.value = false
}

function toggleScopeMenu() {
  const next = !scopeMenuOpen.value
  closeHeaderMenus()
  scopeMenuOpen.value = next
}

function toggleIntentMenu() {
  const next = !intentMenuOpen.value
  closeHeaderMenus()
  intentMenuOpen.value = next
}

function toggleModelMenu() {
  const next = !modelMenuOpen.value
  closeHeaderMenus()
  modelMenuOpen.value = next
}

function chooseIntent(id: Intent) {
  intent.value = id
  closeHeaderMenus()
}

function chooseModel(id: string) {
  llmConfigId.value = id
  closeHeaderMenus()
}

/** 点击菜单与输入区之外时关闭所有浮层（@ 选择器由 composer 自行管理）。 */
function onDocumentClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (target?.closest('[data-chat-menu]')) return
  closeHeaderMenus()
  if (mentionOpen.value) closeMention()
}

function historyMessages() {
  return messages.value
    .filter((m) => !m.streaming && m.content.trim())
    .slice(-12)
    .map((m) => ({ role: m.role, content: m.content }))
}

// ---------- 流式思考过程 ----------
function applyStage(msg: Msg, data: any) {
  const id = String(data?.stage || '').trim()
  if (!id) return
  const status: ChatStep['status'] =
    data?.status === 'done' ? 'done' : data?.status === 'error' ? 'error' : 'active'
  const message = String(data?.message || '').trim()
  const detail = String(data?.detail || '').trim()
  if (!msg.steps) msg.steps = []
  const existing = msg.steps.find((step) => step.id === id)
  if (existing) {
    if (message) existing.message = message
    if (detail) existing.detail = detail
    existing.status = status
  } else {
    msg.steps.push({ id, message: message || '处理中', detail, status })
  }
}

function finishSteps(msg: Msg, status: 'done' | 'error') {
  for (const step of msg.steps || []) {
    if (step.status === 'active') step.status = status
  }
  msg.finishedAt = Date.now()
  // 完成后收起明细，只保留一行「已完成 N 个步骤」；出错时展开便于排查。
  msg.stepsOpen = status === 'error'
}

function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m${String(seconds % 60).padStart(2, '0')}s`
}

function stepSummary(msg: Msg): string {
  const steps = msg.steps || []
  const failed = steps.some((step) => step.status === 'error')
  const span = msg.startedAt && msg.finishedAt ? msg.finishedAt - msg.startedAt : 0
  const used = span > 0 ? ` · 用时 ${formatDuration(span)}` : ''
  return `${failed ? '执行中断' : '已完成'} ${steps.length} 个步骤${used}`
}

function currentStep(msg: Msg): ChatStep | undefined {
  return [...(msg.steps || [])].reverse().find((step) => step.status === 'active')
}

function streamStatusLabel(msg: Msg): string {
  const step = currentStep(msg)
  if (step) return `${step.message}…`
  if (msg.content) return '正在生成回答'
  return '正在思考'
}

function elapsedLabel(msg: Msg): string {
  if (!msg.startedAt) return ''
  const seconds = Math.max(0, Math.floor((nowTick.value - msg.startedAt) / 1000))
  return seconds >= 1 ? `${seconds}s` : ''
}

function isSlowStream(msg: Msg): boolean {
  if (!msg.startedAt) return false
  return nowTick.value - msg.startedAt >= 20_000
}

// ---------- 提问 ----------
async function ask() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  closeMention()
  if (llmMissing.value) {
    toast.error('尚未配置大模型，请先在「设置 → 模型」中完成配置')
    return
  }
  if (!validateScope()) return
  if (!(await ensureSession())) return
  input.value = ''
  void nextTick(() => resizeComposer())
  pushUser(text)
  const payloadMessages = historyMessages()
  const assistant = pushAssistant()
  streaming.value = true
  autoScroll.value = true
  scrollToBottom(true)
  // 先保存用户问题：即使页面中途关闭，历史里仍保留提问。
  scheduleSave(0)

  // 引用先暂存，等回答完成后再按正文实际引用过滤，避免先闪出 10 条。
  let pendingCitations: Citation[] = []

  openSSE(
    '/chat/stream',
    {
      messages: payloadMessages,
      scope: requestScope(),
      intent: intent.value,
      llm_config_id: llmConfigId.value || null,
      agent: agentMode.value,
      web_search: webSearch.value,
    },
    {
      onMessage: (msg) => {
        if (msg.event === 'stage') {
          applyStage(assistant, msg.data)
          scrollToBottom()
        } else if (msg.event === 'chunk') {
          assistant.content += msg.data?.text ?? ''
          scrollToBottom()
        } else if (msg.event === 'citation') {
          pendingCitations = msg.data?.citations ?? []
        } else if (msg.event === 'notice') {
          const notice = String(msg.data?.message || '').trim()
          if (notice) toast.info(notice)
        } else if (msg.event === 'done') {
          finishSteps(assistant, 'done')
          assistant.streaming = false
          streaming.value = false
          normalizeCitations(assistant, pendingCitations)
          assistant.created_at = new Date().toISOString()
          scrollToBottom(true)
          void saveSessionNow()
        } else if (msg.event === 'error') {
          finishSteps(assistant, 'error')
          assistant.content += `\n\n⚠️ ${msg.data?.message ?? '出错了'}`
          assistant.streaming = false
          streaming.value = false
          void saveSessionNow()
        }
      },
      onError: (e) => {
        finishSteps(assistant, 'error')
        assistant.content += `\n\n⚠️ 连接失败：${e.message}`
        assistant.streaming = false
        streaming.value = false
        void saveSessionNow()
      },
    },
  )
}

const suggestions = [
  { icon: 'search', text: '这个知识库里有什么？' },
  { icon: 'sparkle', text: '总结最近的 Wiki 与笔记内容' },
  { icon: 'link2', text: '查找关于…的笔记出处' },
]

function suggest(q: { text: string }) {
  input.value = q.text
  void ask()
}

const canSend = computed(
  () => input.value.trim().length > 0 && !streaming.value && !llmMissing.value,
)

// ---------- 引用跳转与定位 ----------
const NOTE_KIND_LABEL: Record<string, string> = {
  doc: '文档',
  import: '导入',
  database: '数据表',
  canvas: '画布',
  notebook: 'Notebook',
  link: '链接',
}

function citationLabel(citation: Citation): string {
  if (citation.collection === 'web') return '网页'
  if (citation.collection === 'note') {
    return NOTE_KIND_LABEL[citation.kind || ''] || '笔记'
  }
  return 'Wiki'
}

/** 引用卡片配色：笔记 / Wiki / 网页三种来源。 */
function citationTone(citation: Citation): 'web' | 'note' | 'wiki' {
  if (citation.collection === 'web') return 'web'
  return citation.collection === 'note' ? 'note' : 'wiki'
}

/** 来源预览去掉 Markdown 标记，避免卡片里出现 #、[[ ]]、``` 等噪声。 */
function citationPreview(text: string): string {
  return (text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\[\[([^\]]+)\]\]/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[*_`>#]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

// 正文里的引用标记：[1] / [1,2] / [1-3] / 【1】 / ［1］。
const CITE_REF_RE =
  /(?:\[|【|［)(\d+(?:\s*[-–]\s*\d+)?(?:\s*[,，、]\s*\d+(?:\s*[-–]\s*\d+)?)*)(?:\]|】|］)/g

function expandCitationGroup(group: string): number[] {
  const numbers: number[] = []
  for (const part of group.split(/[,，、]/)) {
    const range = part.split(/[-–]/)
    if (range.length === 2) {
      const start = Number(range[0].trim())
      const end = Number(range[1].trim())
      if (!Number.isFinite(start) || !Number.isFinite(end)) continue
      const low = Math.min(start, end)
      const high = Math.max(start, end)
      // 防御异常范围（如 [1-999999]），最多展开 20 个。
      for (let n = low; n <= high && n - low < 20; n += 1) numbers.push(n)
    } else {
      const n = Number(part.trim())
      if (Number.isFinite(n)) numbers.push(n)
    }
  }
  return numbers
}

/**
 * 引用列表只保留回答正文真正提到的来源，并按出现顺序重新编号。
 * 检索每次最多返回 10 条，但模型通常只用其中几条；直接展示全部会让
 * 引用区看起来像检索结果列表，而不是依据。
 */
function normalizeCitations(msg: Msg, all: Citation[]) {
  const content = msg.content || ''
  const order: number[] = []
  let match: RegExpExecArray | null
  CITE_REF_RE.lastIndex = 0
  while ((match = CITE_REF_RE.exec(content))) {
    for (const n of expandCitationGroup(match[1])) {
      if (n >= 1 && n <= all.length && !order.includes(n)) order.push(n)
    }
  }
  if (!order.length) {
    msg.citations = []
    return
  }
  const mapping = new Map(order.map((n, index) => [n, index + 1]))
  msg.content = content.replace(CITE_REF_RE, (whole, group: string) => {
    const mapped = expandCitationGroup(group)
      .map((n) => mapping.get(n))
      .filter((n): n is number => typeof n === 'number')
    return mapped.length ? mapped.map((n) => `[${n}]`).join('') : whole
  })
  msg.citations = order.map((n) => all[n - 1])
}

function openCitation(citation: Citation) {
  const query: Record<string, string> = {}
  const quote = (citation.quote || citation.chunk_text || '').slice(0, 200)
  if (quote) query.quote = quote
  if (citation.heading) query.heading = citation.heading.slice(0, 120)
  if (citation.chunk_index) query.chunk = String(citation.chunk_index)
  if (citation.collection === 'web' && citation.url) {
    window.open(citation.url, '_blank', 'noopener,noreferrer')
    return
  }
  if (citation.collection === 'wiki' && citation.target_id) {
    void router.push({
      name: 'wiki-page',
      params: { id: citation.target_id },
      query,
    })
  } else if (citation.collection === 'note' && citation.target_id) {
    void router.push({
      name: 'notes',
      params: { id: citation.target_id },
      query,
    })
  }
}

const CITATION_PREVIEW = 6

function visibleCitations(msg: Msg, index: number): Citation[] {
  return expandedCites.value[index]
    ? msg.citations
    : msg.citations.slice(0, CITATION_PREVIEW)
}

function toggleCites(index: number) {
  expandedCites.value = {
    ...expandedCites.value,
    [index]: !expandedCites.value[index],
  }
}

async function focusCitation(msg: Msg, citeNumber: number) {
  const msgIndex = messages.value.indexOf(msg)
  if (msgIndex < 0) return
  const citeIndex = citeNumber - 1
  if (citeIndex < 0 || citeIndex >= msg.citations.length) return

  // 引用的来源卡片默认折叠，点击正文里的 [n] 时先展开再定位。
  if (citeIndex >= CITATION_PREVIEW && !expandedCites.value[msgIndex]) {
    expandedCites.value = { ...expandedCites.value, [msgIndex]: true }
    await nextTick()
  }
  activeCite.value = { msg: msgIndex, cite: citeIndex }
  await nextTick()
  document
    .getElementById(`chat-cite-${msgIndex}-${citeNumber}`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  window.setTimeout(() => {
    if (activeCite.value?.msg === msgIndex && activeCite.value.cite === citeIndex) {
      activeCite.value = null
    }
  }, 1800)
}

async function copyMessage(msg: Msg) {
  try {
    await navigator.clipboard.writeText(msg.content)
    toast.success('回答已复制')
  } catch {
    toast.error('复制失败，请手动选择文本')
  }
}

// ---------- 回写为 Wiki 综合页 ----------
const writebackOpen = ref(false)
const writebackMsg = ref<Msg | null>(null)
const writebackTitle = ref('')
const writebackKbId = ref('')
const writebackSaving = ref(false)

function openWriteback(msg: Msg) {
  if (!msg.content.trim()) return
  writebackMsg.value = msg
  writebackKbId.value = msg.citations[0]?.kb_id || kbs.currentKbId || ''
  const index = messages.value.indexOf(msg)
  const question =
    [...messages.value.slice(0, index)]
      .reverse()
      .find((m) => m.role === 'user')?.content || '知识库问答'
  writebackTitle.value = `问答总结：${question.replace(/\s+/g, ' ').slice(0, 40)}`
  writebackOpen.value = true
}

function citationMarkdown(msg: Msg): string {
  if (!msg.citations.length) return ''
  const lines = msg.citations.map((c, i) => {
    const kind = citationLabel(c)
    const href =
      c.collection === 'web'
        ? c.url || c.target_id
        : c.collection === 'wiki'
          ? `/wiki/${c.target_id}`
          : `/notes/${c.target_id}`
    return `${i + 1}. [${kind}：${c.title}](${href})` + (c.kb_name ? `（${c.kb_name}）` : '')
  })
  return `\n\n---\n\n## 引用来源\n\n${lines.join('\n')}`
}

async function saveWriteback() {
  const msg = writebackMsg.value
  const title = writebackTitle.value.trim()
  if (!msg || !title) {
    toast.info('请填写页面标题')
    return
  }
  if (!writebackKbId.value) {
    toast.info('请选择回写的知识库')
    return
  }
  writebackSaving.value = true
  try {
    const page = await request<{ id: string }>('/wiki', {
      method: 'POST',
      kbId: writebackKbId.value,
      body: JSON.stringify({
        title,
        body_md: msg.content + citationMarkdown(msg),
        page_type: 'synthesis',
        tags: ['问答回写'],
      }),
    })
    writebackOpen.value = false
    toast.success('已回写为 Wiki 综合页')
    void router.push({ name: 'wiki-page', params: { id: page.id } })
  } catch (e: any) {
    toast.error(e.message || '回写失败')
  } finally {
    writebackSaving.value = false
  }
}

// ---------- 辅助展示 ----------
function sessionTime(item: SessionSummary): string {
  const raw = item.last_message_at || item.updated_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  return sameDay
    ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

watch(
  [scopeMode, intent, multiIds, llmConfigId],
  () => {
    saveSettings()
    // 已落库的会话同步范围 / 意图 / 模型选择；正在流式回答时等完成后再存。
    if (!hydratingSession && currentSessionId.value && !streaming.value) {
      scheduleSave(800)
    }
  },
  { deep: true },
)
</script>

<template>
  <div class="relative flex h-full min-h-0">
    <!-- 移动端遮罩 -->
    <div
      v-if="sidebarOpen"
      class="fixed inset-0 z-20 bg-slate-900/20 backdrop-blur-[1px] md:hidden"
      @click="sidebarOpen = false"
    />

    <!-- 会话侧栏 -->
    <aside
      class="z-30 flex h-full w-64 shrink-0 flex-col border-r border-slate-200/70 bg-white/70 backdrop-blur-xl"
      :class="sidebarOpen ? 'absolute inset-y-0 left-0 flex shadow-xl md:static md:shadow-none' : 'hidden md:flex'"
    >
      <div class="flex items-center gap-2 px-3 pb-2 pt-3">
        <button
          type="button"
          class="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-gradient-to-br from-kiwi-500 to-kiwi-700 px-3 py-2 text-xs font-medium text-white shadow-glow transition hover:brightness-105 active:scale-[0.98]"
          @click="newConversation"
        >
          <KiwiIcon name="plus" :size="13" />
          新对话
        </button>
        <button
          type="button"
          class="grid h-8 w-8 place-items-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 md:hidden"
          title="关闭"
          @click="sidebarOpen = false"
        >
          <KiwiIcon name="close" :size="15" />
        </button>
      </div>

      <!-- 会话搜索 -->
      <div class="px-2 pb-2">
        <div class="relative">
          <KiwiIcon
            name="search"
            :size="12"
            class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            v-model="sessionQuery"
            type="text"
            placeholder="搜索会话"
            class="w-full rounded-lg border border-slate-200/80 bg-white/70 py-1.5 pl-7 pr-7 text-[11.5px] text-slate-600 outline-none transition placeholder:text-slate-400 focus:border-kiwi-300 focus:bg-white focus:ring-2 focus:ring-kiwi-200/40"
          />
          <button
            v-if="sessionQuery"
            type="button"
            class="absolute right-1.5 top-1/2 grid h-5 w-5 -translate-y-1/2 place-items-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            title="清除搜索"
            @click="sessionQuery = ''"
          >
            <KiwiIcon name="close" :size="10" />
          </button>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto px-2 pb-2">
        <p class="flex items-center justify-between px-2 pb-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
          <span>会话历史</span>
          <span v-if="sessions.length" class="font-normal normal-case tracking-normal">{{ filteredSessions.length }} / {{ sessions.length }}</span>
        </p>
        <div v-if="sessionsLoading" class="flex items-center gap-2 px-2 py-3 text-[11px] text-slate-400">
          <KiwiIcon name="loader" :size="12" :spin="true" />
          正在加载…
        </div>
        <p
          v-else-if="!sessions.length"
          class="px-2 py-4 text-[11px] leading-relaxed text-slate-400"
        >
          还没有会话。发送第一个问题后，历史会自动保留在这里。
        </p>
        <p
          v-else-if="!filteredSessions.length"
          class="px-2 py-4 text-[11px] leading-relaxed text-slate-400"
        >
          没有匹配「{{ sessionQuery }}」的会话。
        </p>
        <div
          v-for="item in filteredSessions"
          :key="item.id"
          class="group relative mb-0.5 rounded-xl px-2.5 py-2 text-left transition-colors"
          :class="item.id === currentSessionId ? 'bg-kiwi-50/90 text-kiwi-800' : 'text-slate-600 hover:bg-slate-100/80'"
        >
          <span
            v-if="item.id === currentSessionId"
            class="absolute bottom-2 left-0 top-2 w-0.5 rounded-full bg-kiwi-500"
          />
          <button type="button" class="block w-full text-left" @click="loadSession(item.id)">
            <input
              v-if="renamingId === item.id"
              v-model="renameTitle"
              :data-rename-input="item.id"
              class="w-full rounded-md border border-kiwi-300 bg-white px-1.5 py-0.5 text-[12px] outline-none"
              @click.stop
              @keydown.enter.prevent="commitRename(item)"
              @keydown.esc.prevent="renamingId = ''"
              @blur="commitRename(item)"
            />
            <template v-else>
              <span class="line-clamp-2 block pr-12 text-[12px] leading-snug">{{ item.title }}</span>
              <span class="mt-1 flex items-center gap-1.5 text-[9.5px] text-slate-400">
                <span>{{ item.message_count }} 条消息</span>
                <span v-if="sessionTime(item)">· {{ sessionTime(item) }}</span>
              </span>
            </template>
          </button>
          <div
            v-if="renamingId !== item.id"
            class="absolute right-1.5 top-1.5 hidden items-center gap-0.5 rounded-md bg-white/95 px-0.5 py-0.5 shadow-sm group-hover:flex"
          >
            <button
              type="button"
              class="grid h-5 w-5 place-items-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              title="重命名"
              @click.stop="startRename(item)"
            >
              <KiwiIcon name="edit" :size="11" />
            </button>
            <button
              type="button"
              class="grid h-5 w-5 place-items-center rounded text-slate-400 hover:bg-rose-50 hover:text-rose-500"
              title="删除"
              @click.stop="deleteTarget = item"
            >
              <KiwiIcon name="trash" :size="11" />
            </button>
          </div>
        </div>
      </div>

      <div v-if="sessions.length" class="border-t border-slate-200/60 p-2">
        <button
          type="button"
          class="flex w-full items-center justify-center gap-1 rounded-lg px-2 py-1.5 text-[10.5px] text-slate-400 transition hover:bg-rose-50 hover:text-rose-500"
          @click="clearOpen = true"
        >
          <KiwiIcon name="trash" :size="11" />
          清空本库历史
        </button>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="relative flex min-w-0 flex-1 flex-col">
      <!-- 会话标题 / 范围 / 意图 / 模型 -->
      <header class="relative z-20 shrink-0 border-b border-slate-200/60 bg-white/55 px-4 py-2 backdrop-blur-xl">
        <div class="mx-auto flex w-full max-w-[1120px] items-center gap-2">
          <button
            type="button"
            class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white/80 text-slate-600 hover:border-kiwi-300 hover:text-kiwi-700 md:hidden"
            title="会话历史"
            @click="sidebarOpen = true"
          >
            <KiwiIcon name="list" :size="13" />
          </button>

          <div class="min-w-0 flex-1">
            <h1 class="truncate text-[13px] font-medium leading-tight text-slate-700">{{ currentTitle }}</h1>
            <p class="mt-0.5 flex items-center gap-2 text-[10px] leading-tight text-slate-400">
              <span>{{ turnCount }} 轮对话</span>
              <span class="inline-flex items-center gap-1">
                <span
                  class="inline-block h-1 w-1 rounded-full"
                  :class="saving ? 'animate-pulse bg-amber-400' : 'bg-emerald-400'"
                />
                {{ saving ? '保存中…' : '已自动保存' }}
              </span>
              <span v-if="sessionLoading" class="inline-flex items-center gap-1">
                <KiwiIcon name="loader" :size="9" :spin="true" />
                加载会话…
              </span>
            </p>
          </div>

          <div class="flex shrink-0 items-center gap-1.5">
            <div class="relative" data-chat-menu>
              <button
                type="button"
                class="inline-flex h-7 items-center gap-1.5 rounded-lg border border-slate-200 bg-white/80 px-2.5 text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700"
                @click="toggleScopeMenu"
              >
                <KiwiIcon name="database" :size="12" class="text-slate-400" />
                <span class="max-w-[11rem] truncate">范围：{{ scopeLabel }}</span>
                <KiwiIcon name="chevron" :size="11" class="text-slate-400" />
              </button>
              <div
                v-if="scopeMenuOpen"
                class="absolute left-0 top-full z-30 mt-1 w-72 rounded-xl border border-slate-200 bg-white p-2 shadow-lifted"
              >
                <div class="mb-1 flex rounded-lg bg-slate-100 p-0.5 text-[10.5px]">
                  <button
                    v-for="mode in (['kb', 'multi', 'global'] as ScopeMode[])"
                    :key="mode"
                    type="button"
                    class="flex-1 rounded-md px-2 py-1"
                    :class="scopeMode === mode ? 'bg-white font-medium text-kiwi-700 shadow-sm' : 'text-slate-500'"
                    @click="scopeMode = mode"
                  >
                    {{ mode === 'kb' ? '单库' : mode === 'multi' ? '多库' : '全局' }}
                  </button>
                </div>
                <template v-if="scopeMode === 'multi'">
                  <p class="px-1 pb-1 text-[10px] text-slate-400">勾选要一起检索的知识库</p>
                  <label
                    v-for="kb in kbs.kbs"
                    :key="kb.id"
                    class="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-[11.5px] text-slate-600 hover:bg-kiwi-50/60"
                  >
                    <input
                      type="checkbox"
                      :checked="multiIds.includes(kb.id)"
                      @change="toggleMultiKb(kb.id)"
                    />
                    <span class="truncate">{{ kb.name }}</span>
                    <span class="ml-auto text-[9.5px] text-slate-400">{{ kb.wiki_count }} Wiki</span>
                  </label>
                </template>
                <template v-else-if="scopeMode === 'kb'">
                  <button
                    v-for="kb in kbs.kbs"
                    :key="kb.id"
                    type="button"
                    class="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[11.5px] hover:bg-kiwi-50/60"
                    :class="kbs.currentKbId === kb.id ? 'text-kiwi-700' : 'text-slate-600'"
                    @click="kbs.currentKbId = kb.id"
                  >
                    <span class="truncate">{{ kb.name }}</span>
                    <KiwiIcon
                      v-if="kbs.currentKbId === kb.id"
                      name="check"
                      :size="11"
                      class="ml-auto text-kiwi-500"
                    />
                  </button>
                </template>
                <p v-else class="px-2 py-1 text-[10.5px] leading-relaxed text-slate-400">
                  在所有知识库中检索，引用卡片会标注来源库名称。
                </p>
                <button
                  type="button"
                  class="mt-1 w-full rounded-md bg-slate-50 py-1 text-[10.5px] text-slate-500 hover:bg-slate-100"
                  @click="scopeMenuOpen = false"
                >
                  完成
                </button>
              </div>
            </div>

            <div class="relative" data-chat-menu>
              <button
                type="button"
                class="inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] transition"
                :class="activeFilterCount
                  ? 'border-kiwi-300 bg-kiwi-50/70 text-kiwi-700'
                  : 'border-slate-200 bg-white/80 text-slate-600 hover:border-kiwi-300 hover:text-kiwi-700'"
                @click="toggleFilterMenu"
              >
                <KiwiIcon name="filter" :size="12" :class="activeFilterCount ? 'text-kiwi-500' : 'text-slate-400'" />
                筛选
                <span
                  v-if="activeFilterCount"
                  class="rounded-full bg-kiwi-500 px-1.5 text-[9px] font-medium leading-4 text-white"
                >{{ activeFilterCount }}</span>
                <KiwiIcon name="chevron" :size="11" class="text-slate-400" />
              </button>
              <div
                v-if="filterMenuOpen"
                class="absolute left-0 top-full z-30 mt-1 w-80 rounded-xl border border-slate-200 bg-white p-3 shadow-lifted"
              >
                <div class="mb-2 flex items-center justify-between">
                  <span class="text-[11px] font-medium text-slate-600">笔记筛选</span>
                  <button
                    v-if="activeFilterCount"
                    type="button"
                    class="text-[10.5px] text-slate-400 hover:text-kiwi-600"
                    @click="clearFilters"
                  >
                    清除
                  </button>
                </div>
                <p class="mb-1 text-[10px] text-slate-400">按类型</p>
                <div class="mb-2.5 flex flex-wrap gap-1">
                  <button
                    v-for="kind in NOTE_KIND_OPTIONS"
                    :key="kind.id"
                    type="button"
                    class="rounded-full border px-2 py-0.5 text-[10.5px] transition"
                    :class="filterKinds.includes(kind.id)
                      ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
                      : 'border-slate-200 text-slate-500 hover:border-kiwi-200'"
                    @click="toggleFilterKind(kind.id)"
                  >
                    {{ kind.label }}
                  </button>
                </div>
                <p class="mb-1 text-[10px] text-slate-400">按标签（当前知识库）</p>
                <div v-if="filterTagsLoading" class="py-1 text-[10.5px] text-slate-400">加载中…</div>
                <div v-else-if="filterTags.length" class="mb-2.5 flex max-h-24 flex-wrap gap-1 overflow-auto">
                  <button
                    v-for="tag in filterTags"
                    :key="tag.id"
                    type="button"
                    class="rounded-full border px-2 py-0.5 text-[10.5px] transition"
                    :class="filterTagIds.includes(tag.id)
                      ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
                      : 'border-slate-200 text-slate-500 hover:border-kiwi-200'"
                    @click="toggleFilterTag(tag.id)"
                  >
                    #{{ tag.name }}
                  </button>
                </div>
                <p v-else class="mb-2.5 text-[10.5px] text-slate-400">当前知识库还没有标签</p>
                <p class="mb-1 text-[10px] text-slate-400">按更新时间</p>
                <div class="flex items-center gap-1.5 text-[10.5px] text-slate-500">
                  <input v-model="filterFrom" type="date" class="min-w-0 flex-1 rounded-lg border border-slate-200 px-1.5 py-1" />
                  <span class="text-slate-300">→</span>
                  <input v-model="filterTo" type="date" class="min-w-0 flex-1 rounded-lg border border-slate-200 px-1.5 py-1" />
                </div>
                <p class="mt-2 rounded-lg bg-slate-50 px-2 py-1.5 text-[10px] leading-relaxed text-slate-400">
                  设置任一筛选后只检索笔记，Wiki 没有类型 / 标签 / 更新时间属性。
                </p>
              </div>
            </div>

            <div class="relative" data-chat-menu>
              <button
                type="button"
                class="inline-flex h-7 items-center gap-1.5 rounded-lg border border-slate-200 bg-white/80 px-2.5 text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700"
                :title="intentHint"
                @click="toggleIntentMenu"
              >
                <KiwiIcon name="layers" :size="12" class="text-slate-400" />
                <span>{{ intentLabel }}</span>
                <KiwiIcon name="chevron" :size="11" class="text-slate-400" />
              </button>
              <div
                v-if="intentMenuOpen"
                class="absolute right-0 top-full z-30 mt-1 w-64 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lifted"
              >
                <button
                  v-for="opt in intentOptions"
                  :key="opt.id"
                  type="button"
                  class="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-[11.5px] transition-colors"
                  :class="intent === opt.id ? 'bg-kiwi-50 text-kiwi-800' : 'text-slate-600 hover:bg-slate-50'"
                  @click="chooseIntent(opt.id)"
                >
                  <span class="min-w-0 flex-1">
                    <span class="block font-medium">{{ opt.label }}</span>
                    <span class="mt-0.5 block text-[10px] leading-snug text-slate-400">{{ opt.hint }}</span>
                  </span>
                  <KiwiIcon
                    v-if="intent === opt.id"
                    name="check"
                    :size="12"
                    class="mt-0.5 shrink-0 text-kiwi-500"
                  />
                </button>
              </div>
            </div>

            <div class="relative hidden sm:block" data-chat-menu>
              <button
                type="button"
                class="inline-flex h-7 max-w-[14rem] items-center gap-1.5 rounded-lg border border-slate-200 bg-white/80 px-2.5 text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700"
                :title="`本次对话模型：${modelHint}`"
                @click="toggleModelMenu"
              >
                <KiwiIcon name="bot" :size="12" class="text-slate-400" />
                <span class="max-w-[9rem] truncate">{{ modelLabel }}</span>
                <KiwiIcon name="chevron" :size="11" class="text-slate-400" />
              </button>
              <div
                v-if="modelMenuOpen"
                class="absolute right-0 top-full z-30 mt-1 w-72 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lifted"
              >
                <button
                  type="button"
                  class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11.5px] transition-colors"
                  :class="!llmConfigId ? 'bg-kiwi-50 text-kiwi-800' : 'text-slate-600 hover:bg-slate-50'"
                  @click="chooseModel('')"
                >
                  <span class="min-w-0 flex-1">
                    <span class="block font-medium">默认模型</span>
                    <span class="mt-0.5 block text-[10px] text-slate-400">使用知识库或全局默认模型</span>
                  </span>
                  <KiwiIcon v-if="!llmConfigId" name="check" :size="12" class="shrink-0 text-kiwi-500" />
                </button>
                <button
                  v-for="cfg in llm.configs"
                  :key="cfg.id"
                  type="button"
                  class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11.5px] transition-colors"
                  :class="llmConfigId === cfg.id ? 'bg-kiwi-50 text-kiwi-800' : 'text-slate-600 hover:bg-slate-50'"
                  @click="chooseModel(cfg.id)"
                >
                  <span class="min-w-0 flex-1">
                    <span class="block truncate font-medium">{{ cfg.name }}</span>
                    <span class="mt-0.5 block truncate text-[10px] text-slate-400">{{ cfg.model_name }}</span>
                  </span>
                  <KiwiIcon
                    v-if="llmConfigId === cfg.id"
                    name="check"
                    :size="12"
                    class="shrink-0 text-kiwi-500"
                  />
                </button>
                <p v-if="!llm.configs.length" class="px-2 py-3 text-center text-[10.5px] text-slate-400">
                  尚未配置模型，请到「设置 → 模型」新增
                </p>
              </div>
            </div>
          </div>
        </div>
      </header>

      <!-- 消息区 -->
      <div ref="scrollEl" class="flex-1 overflow-y-auto px-4 py-6 sm:px-6" @scroll="onScroll">
        <div class="mx-auto w-full space-y-6" style="max-width: min(1120px, 100%)">
          <!-- 空态：建议 chips；桌面版未配置模型时给出明确入口 -->
          <div v-if="!messages.length" class="text-center pt-12 sm:pt-16 animate-fade-up">
            <template v-if="llmMissing">
              <div
                class="w-16 h-16 mx-auto rounded-2xl bg-gradient-to-br from-slate-400 to-slate-600 grid place-items-center text-white shadow-glow mb-5"
              >
                <KiwiIcon name="monitor" :size="28" />
              </div>
              <h2 class="text-lg font-semibold text-slate-700">尚未配置大模型</h2>
              <p class="text-sm text-slate-400 mt-1.5 mb-6 max-w-md mx-auto leading-relaxed">
                桌面版不内置模型。可连接本机 Ollama / LM Studio，或在「设置 → 桌面」中显式允许外部模型接口。
              </p>
              <button
                type="button"
                class="kiwi-btn-primary"
                @click="router.push('/settings/models')"
              >
                <KiwiIcon name="settings" :size="14" />
                去配置模型
              </button>
              <p class="mt-5 text-[11px] text-slate-400">
                笔记编辑、本地导入与笔记搜索不需要模型，可正常使用。
              </p>
            </template>
            <template v-else>
              <div
                class="w-16 h-16 mx-auto rounded-2xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 grid place-items-center text-white shadow-glow mb-5"
              >
                <KiwiIcon name="chat" :size="28" />
              </div>
              <h2 class="text-lg font-semibold text-slate-700">向你的知识库提问</h2>
              <p class="text-sm text-slate-400 mt-1.5 mb-8">
                回答综合 Wiki 与笔记内容，并标注可点击的引用来源
              </p>
              <div class="flex flex-col sm:flex-row gap-3 items-center justify-center">
                <button
                  v-for="(s, i) in suggestions"
                  :key="i"
                  class="px-4 py-2.5 rounded-2xl glass hover:border-kiwi-300 hover:shadow-lifted hover:-translate-y-0.5 text-sm text-slate-600 hover:text-kiwi-700 flex items-center gap-2 transition-all duration-200 animate-fade-up"
                  :style="{ animationDelay: `${200 + i * 80}ms` }"
                  @click="suggest(s)"
                >
                  <KiwiIcon :name="s.icon" :size="14" class="text-kiwi-400" />
                  {{ s.text }}
                </button>
              </div>
            </template>
          </div>

          <!-- 消息 -->
          <div
            v-for="(m, i) in messages"
            :key="i"
            class="animate-message-in"
            :class="m.role === 'user' ? 'flex justify-end' : 'group flex gap-3'"
          >
            <!-- 用户问题 -->
            <div
              v-if="m.role === 'user'"
              class="chat-user-bubble max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-gradient-to-br from-kiwi-500 to-kiwi-700 px-4 py-2.5 text-[13.5px] leading-relaxed text-white shadow-sm sm:max-w-[80%]"
            >
              {{ m.content }}
            </div>

            <!-- 助手回答：不加边框，贴合页面背景 -->
            <template v-else>
              <div
                class="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white shadow-sm"
              >
                <KiwiIcon name="sparkle" :size="13" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="mb-1 flex items-center gap-2 text-[10.5px] text-slate-400">
                  <span class="font-medium text-slate-500">Kiwi</span>
                  <span v-if="m.streaming" class="inline-flex min-w-0 items-center gap-1 text-kiwi-500">
                    <KiwiIcon name="loader" :size="9" :spin="true" />
                    <span class="kiwi-thinking-shimmer truncate font-medium">{{ streamStatusLabel(m) }}</span>
                    <span v-if="elapsedLabel(m)" class="shrink-0 text-slate-400">· {{ elapsedLabel(m) }}</span>
                  </span>
                  <span v-else-if="m.citations?.length">{{ m.citations.length }} 个引用来源</span>
                </div>

                <!-- 思考过程：检索 / 联网 / 生成阶段实时打勾；完成后保留摘要可展开回看 -->
                <div
                  v-if="m.steps?.length"
                  class="mb-2.5 overflow-hidden rounded-xl border border-kiwi-100/80 bg-gradient-to-br from-kiwi-50/60 via-white/80 to-sky-50/40 px-3 py-2"
                >
                  <button
                    v-if="!m.streaming"
                    type="button"
                    class="flex w-full items-center gap-1.5 text-[10.5px] text-slate-500 transition-colors hover:text-kiwi-600"
                    @click="m.stepsOpen = !m.stepsOpen"
                  >
                    <KiwiIcon
                      :name="m.steps.some((step) => step.status === 'error') ? 'alert' : 'check'"
                      :size="9"
                      :class="m.steps.some((step) => step.status === 'error') ? 'text-amber-500' : 'text-emerald-500'"
                    />
                    <span class="flex-1 text-left">{{ stepSummary(m) }}</span>
                    <KiwiIcon
                      :name="m.stepsOpen ? 'chevron' : 'chevronRight'"
                      :size="9"
                      class="shrink-0 text-slate-400"
                    />
                  </button>
                  <template v-if="m.streaming || m.stepsOpen">
                    <div
                      v-if="m.streaming"
                      class="mb-1.5 h-0.5 w-full overflow-hidden rounded-full bg-kiwi-100/80"
                    >
                      <div class="kiwi-thinking-bar h-full w-1/3 rounded-full bg-gradient-to-r from-transparent via-kiwi-400 to-transparent" />
                    </div>
                    <ol class="space-y-1" :class="m.streaming ? '' : 'pt-1.5'">
                      <li
                        v-for="step in m.steps || []"
                        :key="step.id"
                        class="flex items-start gap-1.5 text-[10.5px] leading-relaxed"
                      >
                        <span
                          class="mt-0.5 grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full"
                          :class="step.status === 'done'
                            ? 'bg-emerald-100 text-emerald-600'
                            : step.status === 'error'
                              ? 'bg-amber-100 text-amber-600'
                              : 'bg-kiwi-100 text-kiwi-600'"
                        >
                          <KiwiIcon v-if="step.status === 'done'" name="check" :size="8" />
                          <span v-else-if="step.status === 'error'" class="text-[8px] font-bold leading-none">!</span>
                          <span v-else class="h-1 w-1 animate-pulse rounded-full bg-current" />
                        </span>
                        <span class="min-w-0">
                          <span :class="step.status === 'active' ? 'font-medium text-slate-600' : 'text-slate-500'">
                            {{ step.message }}
                          </span>
                          <span v-if="step.detail" class="text-slate-400"> · {{ step.detail }}</span>
                        </span>
                      </li>
                    </ol>
                    <p v-if="m.streaming && isSlowStream(m)" class="mt-1.5 flex items-center gap-1 text-[10px] text-amber-600">
                      <KiwiIcon name="alert" :size="10" />
                      模型响应较慢，仍在处理，请稍候…
                    </p>
                  </template>
                </div>

                <div class="text-[13.5px] leading-7 text-slate-700">
                  <MarkdownView
                    :content="m.content"
                    :citation-count="m.citations?.length || 0"
                    @citation-click="(n: number) => focusCitation(m, n)"
                  />
                  <span
                    v-if="m.streaming && m.content"
                    class="ml-0.5 inline-block h-3.5 w-[2px] translate-y-0.5 animate-pulse rounded-full bg-kiwi-400 align-baseline"
                  />
                </div>

                <!-- 引用来源：紧凑单行，悬浮查看摘要，点击打开原文 -->
                <div
                  v-if="m.citations?.length"
                  class="mt-2 rounded-lg border border-slate-200/70 bg-white/40 px-1.5 py-1.5 backdrop-blur-sm"
                >
                  <div class="mb-1 flex items-center gap-1.5 px-0.5 text-[10px] text-slate-400">
                    <KiwiIcon name="link2" :size="10" />
                    <span class="font-medium">引用来源</span>
                    <span>{{ m.citations.length }} 条</span>
                    <span class="ml-auto hidden sm:inline">点击打开 · 悬浮查看摘要</span>
                  </div>
                  <div class="flex flex-wrap gap-1">
                    <button
                      v-for="(c, ci) in visibleCitations(m, i)"
                      :id="`chat-cite-${i}-${ci + 1}`"
                      :key="ci"
                      type="button"
                      class="inline-flex max-w-full min-w-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-left transition-colors duration-150"
                      :class="[
                        citationTone(c) === 'note'
                          ? 'hover:bg-sky-50'
                          : citationTone(c) === 'web'
                            ? 'hover:bg-amber-50'
                            : 'hover:bg-kiwi-50',
                        activeCite?.msg === i && activeCite?.cite === ci
                          ? 'bg-kiwi-50 ring-1 ring-kiwi-400/80'
                          : '',
                      ]"
                      :title="citationPreview(c.chunk_text)"
                      @click="openCitation(c)"
                    >
                      <span
                        class="grid h-4 w-4 shrink-0 place-items-center rounded text-[9px] font-semibold"
                        :class="citationTone(c) === 'note'
                          ? 'bg-sky-100 text-sky-700'
                          : citationTone(c) === 'web'
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-kiwi-100 text-kiwi-700'"
                      >
                        {{ ci + 1 }}
                      </span>
                      <span class="max-w-[15rem] truncate text-[11px] text-slate-600">{{ c.title }}</span>
                      <span
                        class="shrink-0 rounded px-1 text-[9px]"
                        :class="citationTone(c) === 'note'
                          ? 'bg-sky-50 text-sky-600'
                          : citationTone(c) === 'web'
                            ? 'bg-amber-50 text-amber-600'
                            : 'bg-kiwi-50 text-kiwi-600'"
                      >
                        {{ citationLabel(c) }}
                      </span>
                    </button>
                  </div>
                  <button
                    v-if="m.citations.length > CITATION_PREVIEW"
                    type="button"
                    class="mt-0.5 flex w-full items-center justify-center gap-1 rounded py-0.5 text-[10px] text-slate-400 transition hover:bg-slate-50 hover:text-kiwi-700"
                    @click="toggleCites(i)"
                  >
                    {{ expandedCites[i] ? '收起' : `展开全部 ${m.citations.length} 条` }}
                    <KiwiIcon
                      name="chevron"
                      :size="9"
                      class="transition-transform"
                      :class="expandedCites[i] ? 'rotate-180' : ''"
                    />
                  </button>
                </div>

                <!-- 回答操作 -->
                <div
                  v-if="!m.streaming && m.content.trim()"
                  class="mt-1.5 flex items-center gap-1 text-[10.5px] text-slate-400 opacity-80 transition-opacity group-hover:opacity-100"
                >
                  <button
                    type="button"
                    class="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 transition hover:bg-kiwi-50 hover:text-kiwi-700"
                    title="复制回答"
                    @click="copyMessage(m)"
                  >
                    <KiwiIcon name="copy" :size="11" />
                    复制
                  </button>
                  <button
                    v-if="m.citations?.length"
                    type="button"
                    class="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 transition hover:bg-kiwi-50 hover:text-kiwi-700"
                    @click="openWriteback(m)"
                  >
                    <KiwiIcon name="wiki" :size="11" />
                    回写为 Wiki 综合页
                  </button>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 回到最新 -->
      <button
        v-if="showJump"
        type="button"
        class="absolute bottom-24 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-slate-200 bg-white/90 px-3 py-1.5 text-[11px] text-slate-500 shadow-lifted backdrop-blur transition hover:border-kiwi-300 hover:text-kiwi-700"
        @click="jumpToBottom"
      >
        <KiwiIcon name="arrowDown" :size="12" />
        回到最新
      </button>

      <!-- 输入区：透明背景，与聊天区的环境渐变保持连续 -->
      <div class="px-4 pb-4 pt-2 sm:px-6">
        <div class="mx-auto w-full" style="max-width: min(1120px, 100%)">
          <!-- 已选 @ 范围：只作用于本轮检索，不改变知识库选择 -->
          <div v-if="mentions.length" class="mb-1.5 flex flex-wrap items-center gap-1.5">
            <span
              v-for="(mention, mi) in mentions"
              :key="`${mention.type}:${mention.id}`"
              class="inline-flex max-w-[16rem] items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px]"
              :class="mention.type === 'folder'
                ? 'border-amber-200 bg-amber-50 text-amber-700'
                : 'border-sky-200 bg-sky-50 text-sky-700'"
              :title="mention.type === 'folder' ? `目录：${mention.title}` : `笔记：${mention.title}`"
            >
              <KiwiIcon :name="mention.type === 'folder' ? 'folder' : 'note'" :size="10" />
              <span class="truncate">{{ mention.title }}</span>
              <button
                type="button"
                class="grid h-3.5 w-3.5 place-items-center rounded-full opacity-70 transition hover:bg-white/70 hover:opacity-100"
                title="移除"
                @click="removeMention(mi)"
              >
                <KiwiIcon name="close" :size="8" />
              </button>
            </span>
            <button
              type="button"
              class="rounded px-1 text-[10px] text-slate-400 transition hover:text-kiwi-600"
              @click="mentions = []"
            >
              清空
            </button>
          </div>

          <!-- data-chat-menu：点击输入区时不应关闭 @ 选择器 -->
          <div
            data-chat-menu
            class="relative rounded-2xl border border-slate-300/70 bg-transparent p-1.5 transition-all duration-200 focus-within:border-kiwi-400/70 focus-within:ring-2 focus-within:ring-kiwi-300/30"
          >
            <!-- 工具条：Agent / 联网开关；@ 范围在输入框内触发 -->
            <div class="flex flex-wrap items-center gap-1 px-1">
              <button
                type="button"
                role="switch"
                :aria-checked="agentMode"
                class="inline-flex items-center gap-1 rounded-lg px-1.5 py-0.5 text-[10.5px] transition-colors"
                :class="agentMode
                  ? 'bg-kiwi-50 text-kiwi-700'
                  : 'text-slate-400 hover:bg-slate-50 hover:text-slate-600'"
                title="Agent：自动拆分问题并多轮检索笔记 / 目录 / Wiki"
                @click="toggleAgent"
              >
                <KiwiIcon name="sparkle" :size="12" />
                Agent
              </button>
              <button
                type="button"
                role="switch"
                :aria-checked="webSearch"
                class="inline-flex items-center gap-1 rounded-lg px-1.5 py-0.5 text-[10.5px] transition-colors"
                :class="webSearch
                  ? 'bg-amber-50 text-amber-700'
                  : 'text-slate-400 hover:bg-slate-50 hover:text-slate-600'"
                title="联网检索：在知识库之外补充网页结果（需后端配置检索服务）"
                @click="toggleWebSearch"
              >
                <KiwiIcon name="globe" :size="12" />
                联网
              </button>
            </div>

            <div class="flex items-end gap-2">
              <textarea
                ref="composerEl"
                v-model="input"
                rows="1"
                placeholder="输入问题，@ 引用笔记或目录，Enter 发送…"
                class="max-h-36 flex-1 resize-none bg-transparent px-3 py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400"
                @input="onComposerInput"
                @keydown="onComposerKeydown"
              />
              <button
                class="grid h-9 w-9 shrink-0 place-items-center rounded-xl text-white transition-all duration-200 disabled:pointer-events-none disabled:opacity-35 active:scale-95"
                :class="canSend ? 'bg-gradient-to-br from-kiwi-500 to-kiwi-700 shadow-glow hover:brightness-105' : 'bg-slate-300'"
                :disabled="!canSend"
                @click="ask"
                title="发送"
              >
                <KiwiIcon name="send" :size="15" />
              </button>
            </div>

            <!-- @ 笔记 / 目录选择器：在输入框中键入 @ 触发，按层级展示 -->
            <div
              v-if="mentionOpen"
              data-chat-menu
              class="absolute bottom-full left-0 z-30 mb-1.5 w-[min(32rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lifted"
            >
              <div class="flex items-center gap-2 border-b border-slate-100 px-2.5 py-1.5">
                <KiwiIcon name="at" :size="12" class="shrink-0 text-kiwi-500" />
                <span class="shrink-0 text-[11px] font-medium text-slate-600">引用笔记 / 目录</span>
                <span v-if="mentionQuery" class="min-w-0 flex-1 truncate text-[11px] text-slate-400">
                  “{{ mentionQuery }}”
                </span>
                <span v-else class="flex-1" />
                <KiwiIcon v-if="mentionLoading" name="loader" :size="11" :spin="true" class="shrink-0 text-slate-400" />
                <span class="shrink-0 text-[9.5px] text-slate-400">↑↓ 选择 · Tab 展开 · Enter 确认 · Esc 关闭</span>
              </div>
              <div class="max-h-72 overflow-y-auto p-1">
                <div
                  v-for="(row, idx) in mentionRows"
                  :key="row.node.key"
                  class="flex cursor-pointer items-center gap-1 rounded-lg py-1 pr-1.5 text-[11.5px] transition-colors"
                  :class="[
                    idx === mentionActiveIndex ? 'bg-kiwi-50/80 text-kiwi-800' : 'text-slate-600',
                    row.node.type === 'folder'
                      ? (isMentioned('folder', row.node.id) ? 'bg-amber-50/70 text-amber-700' : '')
                      : (isMentioned('note', row.node.id) ? 'bg-sky-50/70 text-sky-700' : ''),
                  ]"
                  :style="{ paddingLeft: `${row.depth * 14 + 3}px` }"
                  :data-mention-active="idx === mentionActiveIndex ? 'true' : undefined"
                  @mousedown.prevent
                  @click="chooseMention(row.node)"
                  @mouseenter="mentionActiveIndex = idx"
                >
                  <button
                    v-if="row.node.children.length"
                    type="button"
                    class="grid h-4 w-4 shrink-0 place-items-center rounded text-slate-400 transition hover:bg-white/70 hover:text-slate-600"
                    :title="isMentionExpanded(row.node.key) ? '折叠' : '展开'"
                    @click.stop="toggleMentionExpand(row.node.key)"
                  >
                    <KiwiIcon
                      :name="isMentionExpanded(row.node.key) ? 'chevron' : 'chevronRight'"
                      :size="10"
                    />
                  </button>
                  <span v-else class="h-4 w-4 shrink-0" />
                  <KiwiIcon
                    :name="row.node.type === 'folder'
                      ? (isMentionExpanded(row.node.key) ? 'folderOpen' : 'folder')
                      : 'note'"
                    :size="12"
                    class="shrink-0"
                    :class="row.node.type === 'folder'
                      ? (isMentioned('folder', row.node.id) ? 'text-amber-500' : 'text-amber-400/80')
                      : (isMentioned('note', row.node.id) ? 'text-sky-500' : 'text-slate-400')"
                  />
                  <span class="min-w-0 flex-1 truncate">{{ row.node.title }}</span>
                  <span v-if="row.node.type === 'note'" class="shrink-0 text-[9.5px] text-slate-400">
                    {{ NOTE_KIND_OPTIONS.find((k) => k.id === row.node.kind)?.label || row.node.kind }}
                  </span>
                  <KiwiIcon
                    v-if="isMentioned(row.node.type, row.node.id)"
                    name="check"
                    :size="12"
                    class="shrink-0"
                    :class="row.node.type === 'folder' ? 'text-amber-500' : 'text-sky-500'"
                  />
                </div>
                <p
                  v-if="!mentionRows.length && !mentionLoading"
                  class="px-2 py-6 text-center text-[11px] text-slate-400"
                >
                  没有匹配的笔记或目录
                </p>
                <p
                  v-else-if="!mentionRows.length"
                  class="px-2 py-6 text-center text-[11px] text-slate-400"
                >
                  正在加载目录…
                </p>
              </div>
              <p class="border-t border-slate-100 px-2.5 py-1.5 text-[10px] leading-relaxed text-slate-400">
                继续输入可筛选；勾选目录包含整棵子树。未勾选时按顶部「范围」检索。
              </p>
            </div>
          </div>

          <p class="mt-2 flex flex-wrap items-center gap-1.5 text-[10.5px] text-slate-400">
            <span
              class="inline-block h-1.5 w-1.5 rounded-full"
              :class="scopeMode === 'global' || kbs.currentKb ? 'animate-pulse-ring bg-kiwi-500' : 'bg-slate-300'"
            />
            检索范围：{{ scopeLabel }}
            <span v-if="mentions.length" class="text-slate-300">·</span>
            <span v-if="mentions.length">@ {{ mentions.length }} 项</span>
            <span class="text-slate-300">·</span>
            {{ intent === 'wiki' ? 'Wiki 优先' : intent === 'note' ? '笔记优先' : '自动路由' }}
            <span v-if="agentMode" class="inline-flex items-center gap-0.5 rounded bg-kiwi-50 px-1 text-kiwi-600">
              <KiwiIcon name="sparkle" :size="9" />
              Agent
            </span>
            <span v-if="webSearch" class="inline-flex items-center gap-0.5 rounded bg-amber-50 px-1 text-amber-600">
              <KiwiIcon name="globe" :size="9" />
              联网
            </span>
            <span class="ml-auto hidden sm:inline">Enter 发送 · Shift + Enter 换行</span>
          </p>
        </div>
      </div>
    </div>

    <!-- 删除会话确认 -->
    <KiwiModal
      :open="!!deleteTarget"
      title="删除会话"
      max-w="max-w-md"
      @close="deleteTarget = null"
    >
      <p class="text-sm text-slate-600">
        确定删除「{{ deleteTarget?.title }}」及其全部消息吗？此操作不可恢复。
      </p>
      <div class="mt-4 flex justify-end gap-2">
        <button type="button" class="kiwi-btn-secondary" @click="deleteTarget = null">取消</button>
        <button type="button" class="kiwi-btn-danger" @click="deleteSession">删除</button>
      </div>
    </KiwiModal>

    <!-- 清空历史确认 -->
    <KiwiModal :open="clearOpen" title="清空本库会话历史" max-w="max-w-md" @close="clearOpen = false">
      <p class="text-sm text-slate-600">
        确定清空当前知识库的全部 {{ sessions.length }} 个会话吗？其他知识库的会话不受影响，历史消息删除后不可恢复。
      </p>
      <div class="mt-4 flex justify-end gap-2">
        <button type="button" class="kiwi-btn-secondary" @click="clearOpen = false">取消</button>
        <button type="button" class="kiwi-btn-danger" @click="clearAllSessions">清空</button>
      </div>
    </KiwiModal>

    <!-- 回写确认 -->
    <KiwiModal :open="writebackOpen" title="回写为 Wiki 综合页" max-w="max-w-lg" @close="writebackOpen = false">
      <div class="space-y-3">
        <label class="block">
          <span class="mb-1 block text-[11px] font-medium text-slate-500">页面标题</span>
          <input v-model="writebackTitle" class="kiwi-input" placeholder="给这篇综合页起个标题" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[11px] font-medium text-slate-500">回写到知识库</span>
          <select v-model="writebackKbId" class="kiwi-input">
            <option v-for="kb in kbs.kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
          </select>
        </label>
        <div class="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2">
          <p class="mb-1 text-[10.5px] text-slate-400">将写入综合页正文，并附 {{ writebackMsg?.citations.length || 0 }} 条引用来源。</p>
          <div class="max-h-32 overflow-y-auto">
            <MarkdownView :content="writebackMsg?.content || ''" />
          </div>
        </div>
        <p class="text-[10px] leading-relaxed text-slate-400">
          回写页面标记为人工编辑，后续素材编译不会覆盖；可在 Wiki 中继续修改。
        </p>
      </div>
      <div class="mt-4 flex justify-end gap-2">
        <button type="button" class="kiwi-btn-secondary" @click="writebackOpen = false">取消</button>
        <button type="button" class="kiwi-btn-primary" :disabled="writebackSaving" @click="saveWriteback">
          <KiwiIcon :name="writebackSaving ? 'loader' : 'wiki'" :size="13" :spin="writebackSaving" />
          确认回写
        </button>
      </div>
    </KiwiModal>
  </div>
</template>

<style scoped>
@keyframes blink {
  0%, 100% { opacity: 0.2; }
  50% { opacity: 1; }
}
.animate-blink {
  animation: blink 1.2s ease-in-out infinite;
}
@keyframes message-in {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.animate-message-in {
  animation: message-in 0.3s cubic-bezier(0.21, 0.75, 0.28, 1) both;
}
</style>
