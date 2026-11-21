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
import { openSSE, type SSEMessage } from '@/api/sse'
import { request } from '@/api/client'
import { autoCollapseNav, restoreNav } from '@/composables/useSideNav'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiDateInput from '@/components/ui/KiwiDateInput.vue'
import KiwiSelect from '@/components/ui/KiwiSelect.vue'
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

/** Agent 行动计划：模型先列出步骤，再逐项执行。 */
interface AgentPlanStep {
  id: string
  title: string
  status: 'pending' | 'active' | 'done'
}

/** 写操作待确认信息，由后端 `approval` 事件下发。 */
interface PendingAction {
  action_id: string
  tool: string
  label: string
  summary: string
  args: Record<string, unknown>
  /** 后端工具注册表提供的参数中文标签。 */
  arg_labels?: Record<string, string>
  expires_at?: number
}

/** 右侧引用预览：笔记 / Wiki 正文从详情接口读取。 */
interface CitationPaneState {
  citation: Citation
  collection: 'note' | 'wiki'
  msgIndex: number
  citeIndex: number
  loading: boolean
  error: string
  title: string
  body: string
  kind: string
  kbName: string
  updatedAt: string
  locked: boolean
  lockHint: string
}

interface NotePreviewResponse {
  id: string
  title: string
  body_md: string
  kind: string
  updated_at?: string
  is_locked?: boolean
  lock_hint?: string | null
}

interface WikiPreviewResponse {
  id: string
  title: string
  body_md: string
  page_type?: string
  updated_at?: string
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
  /** Agent 行动计划。 */
  plan?: AgentPlanStep[]
  /** 等待用户确认的写操作；确认或取消后保留到本轮结束。 */
  pendingAction?: PendingAction | null
  actionState?: 'idle' | 'approving' | 'approved' | 'failed' | 'rejected' | 'expired'
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
/** 去掉 @ token 后的正文：只有引用、没有问题时不允许发送。 */
const inputBody = ref('')
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

// ---------- @ 笔记 / 目录 ----------
const mentions = ref<MentionRef[]>([])
const mentionOpen = ref(false)
const mentionQuery = ref('')
const mentionLoading = ref(false)
const mentionNotes = ref<MentionNote[]>([])
const mentionFolders = ref<MentionFolder[]>([])
const mentionExpanded = ref<string[]>([])
const mentionActiveIndex = ref(0)
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
/** 桌面端会话栏折叠状态：默认展开，只由用户手动切换，不随引用预览变化。 */
const sidebarCollapsed = ref(false)
/** 引用预览与聊天区的宽度比例（0.35–0.72），拖动分隔条调整。 */
const splitRatio = ref(0.5)
const splitEl = ref<HTMLElement>()
const isWide = ref(false)
let wideQuery: MediaQueryList | null = null
let splitDrag: { startX: number; startRatio: number; width: number } | null = null
// v1 曾在打开引用预览时自动写入折叠状态，换新键让旧值失效，会话栏默认展开。
const SIDEBAR_COLLAPSED_KEY = 'kiwi.chat.sessionListCollapsed.v1'
const SPLIT_RATIO_KEY = 'kiwi.chat.splitRatio.v1'
const renamingId = ref('')
const renameTitle = ref('')
const deleteTarget = ref<SessionSummary | null>(null)
const clearOpen = ref(false)
const saving = ref(false)
const pendingSave = ref(false)
const activeCite = ref<{ msg: number; cite: number } | null>(null)
const citationPane = ref<CitationPaneState | null>(null)
let citationPaneSeq = 0
const sessionQuery = ref('')
const expandedCites = ref<Record<number, boolean>>({})
const showJump = ref(false)
/** 输入区改为 contenteditable：@ 引用作为行内高亮 token 与正文一起显示。 */
const composerEl = ref<HTMLElement>()
const composerEmpty = ref(true)
const composerComposing = ref(false)

const filteredSessions = computed(() => {
  const query = sessionQuery.value.trim().toLowerCase()
  if (!query) return sessions.value
  return sessions.value.filter((item) => item.title.toLowerCase().includes(query))
})

const currentSession = computed(
  () => sessions.value.find((item) => item.id === currentSessionId.value) || null,
)

const chatColumnStyle = computed(() => {
  if (!citationPane.value || !isWide.value) return undefined
  const basis = `${((1 - splitRatio.value) * 100).toFixed(2)}%`
  return { flex: `0 0 ${basis}`, maxWidth: basis }
})

const citationPaneStyle = computed<Record<string, string>>(() => {
  const style: Record<string, string> = {
    // 阅读面板使用主题表面色但不叠透明度：强背景图透过来会干扰正文，
    // 这里优先保证长文可读性，主题风格由表面色、强调色与边框承载。
    background: 'rgb(var(--theme-surface))',
    borderColor: 'rgb(var(--theme-border) / 0.75)',
  }
  if (citationPane.value && isWide.value) {
    const basis = `${(splitRatio.value * 100).toFixed(2)}%`
    style.flex = `0 0 ${basis}`
    style.maxWidth = basis
  }
  return style
})

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
  document.addEventListener('keydown', onDocumentKeydown)
  wideQuery = window.matchMedia('(min-width: 1024px)')
  isWide.value = wideQuery.matches
  wideQuery.addEventListener('change', onWideChange)
  loadChatLayout()
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
    // @ token 属于旧知识库，跟着输入区一起清空。
    resetComposer()
    currentSessionId.value = ''
    messages.value = []
    closeCitationPane()
    expandedCites.value = {}
    await fetchSessions()
    if (sessions.value.length) await loadSession(sessions.value[0].id)
  },
)
onUnmounted(() => {
  stopRevealingApproval()
  window.clearInterval(streamTickTimer)
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown)
  wideQuery?.removeEventListener('change', onWideChange)
  stopSplitDrag()
  // 离开聊天页时恢复被预览临时收起的主导航。
  restoreNav()
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
  closeCitationPane()
  scopeFromSession(detail)
  const restoredMentions = mentions.value.slice()
  saveSettings()
  sidebarOpen.value = false
  scrollToBottom(true)
  void nextTick(() => {
    hydratingSession = false
    // 会话里保存的 @ 引用还原成输入区里的高亮 token，而不是隐藏状态。
    if (restoredMentions.length) restoreComposerMentions(restoredMentions)
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

/** 输入区里的 @ 引用是原子 token：contenteditable="false"，随正文一起显示与删除。 */
function buildMentionToken(
  type: MentionRef['type'],
  id: string,
  title: string,
): HTMLElement {
  const token = document.createElement('span')
  token.className = 'chat-mention'
  token.contentEditable = 'false'
  token.dataset.mentionType = type
  token.dataset.mentionId = id
  token.dataset.mentionTitle = title
  token.textContent = `@${title}`
  return token
}

/**
 * 序列化输入区：token 记为 `@标题`，<br> 记为换行。
 * includeMentions=false 时跳过 token，用来判断用户是否真的写了问题正文。
 */
function serializeComposer(node: Node, includeMentions = true): string {
  let out = ''
  node.childNodes.forEach((child) => {
    if (child.nodeType === Node.TEXT_NODE) {
      out += (child.textContent || '').replace(/ /g, ' ')
      return
    }
    if (!(child instanceof HTMLElement)) return
    if (child.dataset.mentionId) {
      if (includeMentions) {
        out += `@${child.dataset.mentionTitle || (child.textContent || '').replace(/^@/, '')}`
      }
      return
    }
    if (child.tagName === 'BR') {
      out += '\n'
      return
    }
    out += serializeComposer(child)
  })
  return out
}

/** 输入区唯一数据源：正文、空状态与 @ 引用都从 DOM 同步回来。 */
function syncComposer() {
  const el = composerEl.value
  if (!el) return
  const text = serializeComposer(el).replace(/\n+$/, '')
  input.value = text
  inputBody.value = serializeComposer(el, false).replace(/\n+$/, '')
  composerEmpty.value = !text.trim()
  const next: MentionRef[] = []
  el.querySelectorAll<HTMLElement>('[data-mention-id]').forEach((node) => {
    const id = node.dataset.mentionId || ''
    if (!id) return
    const type: MentionRef['type'] = node.dataset.mentionType === 'folder' ? 'folder' : 'note'
    if (next.some((item) => item.type === type && item.id === id)) return
    next.push({
      type,
      id,
      title: node.dataset.mentionTitle || (node.textContent || '').replace(/^@/, ''),
    })
  })
  mentions.value = next
  resizeComposer()
}

/** 清空输入区（含 @ token）。 */
function resetComposer() {
  const el = composerEl.value
  if (el) el.textContent = ''
  input.value = ''
  inputBody.value = ''
  composerEmpty.value = true
  mentions.value = []
  resizeComposer()
}

/** 光标所在文本节点里 `@关键词` 的关键词；光标在 token 上时不触发。 */
function mentionQueryAtCaret(): string | null {
  const sel = window.getSelection()
  if (!sel || !sel.rangeCount || !sel.isCollapsed) return null
  const range = sel.getRangeAt(0)
  if (range.startContainer.nodeType !== Node.TEXT_NODE) return null
  const before = (range.startContainer.textContent || '')
    .slice(0, range.startOffset)
    .replace(/ /g, ' ')
  const match = before.match(/(?:^|[\s(（])@([^\s@]*)$/)
  return match ? match[1] : null
}

function onComposerInput() {
  syncComposer()
  // 中文输入法拼写期间不驱动 @ 选择器，等 compositionend 再统一处理。
  if (composerComposing.value) return
  const query = mentionQueryAtCaret()
  if (query === null) {
    if (mentionOpen.value) closeMention()
    return
  }
  mentionQuery.value = query
  if (!mentionOpen.value) {
    mentionOpen.value = true
    mentionActiveIndex.value = 0
    void loadMentionCandidates()
  }
}

function onComposerCompositionStart() {
  composerComposing.value = true
}

function onComposerCompositionEnd() {
  composerComposing.value = false
  onComposerInput()
}

function closeMention() {
  mentionOpen.value = false
  mentionQuery.value = ''
  mentionActiveIndex.value = 0
}

function isMentioned(type: MentionRef['type'], id: string): boolean {
  return mentions.value.some((item) => item.type === type && item.id === id)
}

/** 在光标处插入纯文本（粘贴 / Shift+Enter 换行共用），只保留换行不保留富文本。 */
function insertComposerText(text: string) {
  const sel = window.getSelection()
  if (!sel || !sel.rangeCount) return
  const range = sel.getRangeAt(0)
  range.deleteContents()
  const frag = document.createDocumentFragment()
  text.split(/\r?\n/).forEach((line, index) => {
    if (index) frag.appendChild(document.createElement('br'))
    if (line) frag.appendChild(document.createTextNode(line))
  })
  const last = frag.lastChild
  range.insertNode(frag)
  if (last) {
    const after = document.createRange()
    after.setStartAfter(last)
    after.collapse(true)
    sel.removeAllRanges()
    sel.addRange(after)
  }
  syncComposer()
}

function onComposerPaste(event: ClipboardEvent) {
  // 粘贴只取纯文本，避免把外部 HTML / 内联样式带进输入区。
  event.preventDefault()
  const text = event.clipboardData?.getData('text/plain') || ''
  if (text) insertComposerText(text)
}

/** 选中节点：把输入区里的 `@关键词` 原地替换为高亮 token，并补一个空格。 */
function chooseMention(node: MentionTreeNode) {
  const el = composerEl.value
  const title =
    node.type === 'folder'
      ? mentionFolderPaths.value.get(node.id) || node.title
      : node.title
  const token = buildMentionToken(node.type, node.id, title)
  const tail = document.createTextNode(' ')
  const sel = window.getSelection()
  let range: Range | null = null
  if (el && sel && sel.rangeCount) {
    const current = sel.getRangeAt(0)
    if (el.contains(current.startContainer)) range = current
  }
  if (el && range) {
    // 只在文本节点内删除 `@关键词`；光标落在已有 token 上时不改动正文。
    if (range.startContainer.nodeType === Node.TEXT_NODE) {
      const before = (range.startContainer.textContent || '').slice(0, range.startOffset)
      const match = before.match(/(?:^|[\s(（])@([^\s@]*)$/)
      if (match) {
        range.setStart(range.startContainer, range.startOffset - match[1].length - 1)
      }
    }
    // insertNode 只负责插入，不会删除范围内容；先把 `@关键词` 真实删掉。
    range.deleteContents()
    const frag = document.createDocumentFragment()
    frag.appendChild(token)
    frag.appendChild(tail)
    range.insertNode(frag)
    const after = document.createRange()
    after.setStartAfter(tail)
    after.collapse(true)
    sel?.removeAllRanges()
    sel?.addRange(after)
  } else if (el) {
    el.appendChild(document.createTextNode(' '))
    el.appendChild(token)
    el.appendChild(tail)
  }
  closeMention()
  syncComposer()
  void nextTick(() => composerEl.value?.focus())
}

/** 会话载入时把保存的 @ 引用还原成输入区里的 token。 */
function restoreComposerMentions(items: MentionRef[]) {
  const el = composerEl.value
  if (!el || !items.length) return
  const existing = new Set(
    Array.from(el.querySelectorAll<HTMLElement>('[data-mention-id]')).map(
      (node) => `${node.dataset.mentionType}:${node.dataset.mentionId}`,
    ),
  )
  const missing = items.filter((item) => !existing.has(`${item.type}:${item.id}`))
  if (!missing.length) return
  const hasContent = (el.textContent || '').trim().length > 0
  missing.forEach((item, index) => {
    if (hasContent || index > 0) el.appendChild(document.createTextNode(' '))
    el.appendChild(buildMentionToken(item.type, item.id, item.title))
  })
  el.appendChild(document.createTextNode(' '))
  syncComposer()
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
  if (event.key === 'Enter' && event.shiftKey) {
    // contenteditable 默认会插入 <div> 块，统一成 <br>，序列化时才可控。
    event.preventDefault()
    insertComposerText('\n')
    return
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void ask()
  }
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
      // 等待写操作确认时回答为空，不写入会话，避免刷新后出现空白气泡。
      .filter((m) => !m.streaming && (m.role === 'user' || m.content.trim()))
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
  closeCitationPane()
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
  // 必须返回数组里的响应式代理：直接改原始对象不会触发 Vue 更新，
  // 审批卡片 / 步骤 / 流式正文就只能等定时器或其它交互顺带重渲染，
  // 表现为「确认框不及时弹出，点一下页面才出现」。
  return messages.value[messages.value.length - 1] as Msg
}

function scrollToBottom(force = false) {
  if (!autoScroll.value && !force) return
  if (force) showJump.value = false
  void nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

let approvalRevealTimer: number | undefined
let approvalRevealSeq = 0

/**
 * 把待确认卡片滚进视口。
 *
 * 审批卡片出现时，前面的步骤明细会从展开收成一行，正文里的图片 / Mermaid
 * 也可能在之后才完成布局；只在 nextTick 滚一次会被后续高度变化顶出视口，
 * 表现为「卡片不会自动出现，点一下才看到」。这里在随后的布局稳定期内
 * 反复检查，直到卡片完整可见或超时。
 */
function revealApproval(actionId: string) {
  if (!actionId) return
  const seq = ++approvalRevealSeq
  window.clearTimeout(approvalRevealTimer)
  const tick = (remaining: number) => {
    if (seq !== approvalRevealSeq) return
    const container = scrollEl.value
    const card = container?.querySelector<HTMLElement>(
      `[data-approval-action="${CSS.escape(actionId)}"]`,
    )
    if (container && card) {
      const cardRect = card.getBoundingClientRect()
      const containerRect = container.getBoundingClientRect()
      const viewportH = window.visualViewport?.height ?? window.innerHeight
      const fullyVisible =
        cardRect.top >= containerRect.top - 1 &&
        cardRect.bottom <= containerRect.bottom - 1 &&
        cardRect.top >= -1 &&
        cardRect.bottom <= viewportH + 1
      if (fullyVisible) return
      // 极少数布局下 .chat-scroll 不是真正的滚动容器（外层页面在滚），
      // 先用 scrollIntoView 让浏览器自己找到滚动祖先，再按容器校正。
      if (cardRect.top < -1 || cardRect.bottom > viewportH + 1) {
        card.scrollIntoView({ block: 'nearest', behavior: 'auto' })
      }
      const nextCardRect = card.getBoundingClientRect()
      const nextContainerRect = container.getBoundingClientRect()
      const tall = nextCardRect.height > nextContainerRect.height - 24
      // 卡片能完整放下时把它顶到聊天区上方，比贴着底部更醒目；
      // 卡片高于可视区时对齐底部，保证「允许执行 / 取消」始终看得见。
      const target = tall
        ? container.scrollTop + (nextCardRect.bottom - nextContainerRect.bottom)
        : container.scrollTop + (nextCardRect.top - nextContainerRect.top) - 16
      container.scrollTo({
        top: Math.max(0, target),
        // 必须立即到位：平滑滚动 + 逐次重试会让卡片在流结束后还要过一秒才
        // 露出来，看起来就像「根本没自动出现」。
        behavior: 'auto',
      })
    }
    if (remaining > 0) {
      approvalRevealTimer = window.setTimeout(() => tick(remaining - 1), 150)
    }
  }
  void nextTick(() => requestAnimationFrame(() => tick(20)))
}

function stopRevealingApproval() {
  approvalRevealSeq += 1
  window.clearTimeout(approvalRevealTimer)
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

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && citationPane.value) closeCitationPane()
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

// ---------- Agent 计划与写操作确认 ----------
function applyPlan(msg: Msg, data: any) {
  const steps = Array.isArray(data?.steps) ? data.steps : []
  msg.plan = steps
    .map((step: any, index: number) => ({
      id: String(step?.id || `plan-${index + 1}`),
      title: String(step?.title || '').trim(),
      status:
        step?.status === 'done'
          ? ('done' as const)
          : step?.status === 'active'
            ? ('active' as const)
            : ('pending' as const),
    }))
    .filter((step: AgentPlanStep) => step.title)
}

function planProgress(msg: Msg): string {
  const steps = msg.plan || []
  if (!steps.length) return ''
  return `${steps.filter((step) => step.status === 'done').length}/${steps.length}`
}

const ACTION_ARG_LABELS: Record<string, string> = {
  note_id: '笔记',
  folder_id: '目录',
  database_id: '数据表',
  row_id: '行',
  parent_id: '上级',
  title: '标题',
  name: '名称',
  body_md: '正文',
  query: '关键词',
  fields: '字段',
  values: '内容',
  limit: '数量',
}

function displayArg(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function actionArgRows(action: PendingAction | null | undefined) {
  if (!action) return []
  return Object.entries(action.args || {})
    .filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== '')
    .slice(0, 5)
    .map(([key, value]) => {
      const text = displayArg(value)
      return {
        key,
        label: action.arg_labels?.[key] || ACTION_ARG_LABELS[key] || key,
        value: text.length > 120 ? `${text.slice(0, 120)}…` : text,
      }
    })
}

function normalizePendingAction(data: any): PendingAction {
  const expires = Number(data?.expires_at || 0)
  return {
    action_id: String(data?.action_id || ''),
    tool: String(data?.tool || ''),
    label: String(data?.label || '待确认操作').trim(),
    summary: String(data?.summary || '').trim(),
    args: data?.args && typeof data.args === 'object' ? data.args : {},
    arg_labels:
      data?.arg_labels && typeof data.arg_labels === 'object'
        ? (data.arg_labels as Record<string, string>)
        : undefined,
    expires_at: expires > 0 ? expires : undefined,
  }
}

function isActionExpired(action: PendingAction | null | undefined): boolean {
  return Boolean(action?.expires_at && Date.now() / 1000 >= action.expires_at)
}

/** 首轮流式检索先暂存引用；恢复写操作不会重发 citation，需保留原有引用。 */
interface StreamCitations {
  value: Citation[]
  received: boolean
}

/** 应用一条 Agent SSE 事件；首轮提问与确认后恢复共用同一套处理。 */
function handleStreamEvent(assistant: Msg, event: SSEMessage, pendingCitations: StreamCitations) {
  const data: any = event.data
  if (event.event === 'stage') {
    applyStage(assistant, data)
    scrollToBottom()
  } else if (event.event === 'plan') {
    applyPlan(assistant, data)
    scrollToBottom()
  } else if (event.event === 'chunk') {
    assistant.content += data?.text ?? ''
    scrollToBottom()
  } else if (event.event === 'citation') {
    pendingCitations.value.splice(0, pendingCitations.value.length, ...(data?.citations ?? []))
    pendingCitations.received = true
  } else if (event.event === 'notice') {
    const notice = String(data?.message || '').trim()
    if (notice) toast.info(notice)
  } else if (event.event === 'tool_result') {
    if (assistant.actionState === 'approving') {
      assistant.actionState = data?.ok ? 'approved' : 'failed'
    }
  } else if (event.event === 'approval') {
    assistant.pendingAction = normalizePendingAction(data)
    assistant.actionState = 'idle'
    scrollToBottom()
    revealApproval(assistant.pendingAction.action_id)
  } else if (event.event === 'done') {
    finishSteps(assistant, 'done')
    assistant.streaming = false
    streaming.value = false
    if (pendingCitations.received) normalizeCitations(assistant, pendingCitations.value)
    assistant.created_at = new Date().toISOString()
    if (data?.awaiting_approval) {
      // 等待用户确认：保留审批卡片，不把空回答写入会话。
      if (!assistant.pendingAction) assistant.actionState = 'expired'
      scrollToBottom(true)
      if (assistant.pendingAction) revealApproval(assistant.pendingAction.action_id)
      return
    }
    if (data?.cancelled) assistant.actionState = 'rejected'
    else if (assistant.actionState === 'approving') assistant.actionState = 'approved'
    assistant.pendingAction = null
    scrollToBottom(true)
    void saveSessionNow()
  } else if (event.event === 'error') {
    finishSteps(assistant, 'error')
    if (assistant.actionState === 'approving') assistant.actionState = 'failed'
    assistant.content += `\n\n⚠️ ${data?.message ?? '出错了'}`
    assistant.streaming = false
    streaming.value = false
    void saveSessionNow()
  }
}

function handleStreamError(assistant: Msg, error: Error) {
  finishSteps(assistant, 'error')
  if (assistant.actionState === 'approving') assistant.actionState = 'failed'
  assistant.content += `\n\n⚠️ 连接失败：${error.message}`
  assistant.streaming = false
  streaming.value = false
  void saveSessionNow()
}

/** 确认或取消待执行的写操作，恢复同一个 Agent 循环。 */
function resolveAction(msg: Msg, approve: boolean) {
  const action = msg.pendingAction
  if (!action || streaming.value || msg.actionState === 'approving') return
  stopRevealingApproval()
  if (isActionExpired(action)) {
    msg.actionState = 'expired'
    toast.error('这条操作确认已过期，请重新提问')
    return
  }
  msg.actionState = 'approving'
  msg.streaming = true
  // 用户思考确认的时间不计入本轮执行时长。
  msg.startedAt = Date.now()
  msg.finishedAt = undefined
  streaming.value = true
  autoScroll.value = true
  scrollToBottom(true)
  const pendingCitations: StreamCitations = { value: [], received: false }
  openSSE(
    '/chat/stream',
    {
      messages: [{ role: 'user', content: approve ? '确认执行' : '取消执行' }],
      resume_action_id: action.action_id,
      approve,
      agent: true,
      web_search: true,
    },
    {
      onMessage: (event) => handleStreamEvent(msg, event, pendingCitations),
      onError: (error) => handleStreamError(msg, error),
    },
  )
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
  if (!text || !inputBody.value.trim() || streaming.value) return
  stopRevealingApproval()
  closeMention()
  closeCitationPane()
  if (llmMissing.value) {
    toast.error('尚未配置大模型，请先在「设置 → 模型」中完成配置')
    return
  }
  if (!validateScope()) return
  if (!(await ensureSession())) return
  resetComposer()
  pushUser(text)
  const payloadMessages = historyMessages()
  const assistant = pushAssistant()
  streaming.value = true
  autoScroll.value = true
  scrollToBottom(true)
  // 先保存用户问题：即使页面中途关闭，历史里仍保留提问。
  scheduleSave(0)

  // 引用先暂存，等回答完成后再按正文实际引用过滤，避免先闪出 10 条。
  const pendingCitations: StreamCitations = { value: [], received: false }

  openSSE(
    '/chat/stream',
    {
      messages: payloadMessages,
      scope: requestScope(),
      intent: intent.value,
      llm_config_id: llmConfigId.value || null,
      // Agent 规划与联网能力默认开启；联网仍由规划器按问题决定是否真的发起。
      agent: true,
      web_search: true,
    },
    {
      onMessage: (msg) => handleStreamEvent(assistant, msg, pendingCitations),
      onError: (e) => handleStreamError(assistant, e),
    },
  )
}

const suggestions = [
  { icon: 'search', text: '这个知识库里有什么？' },
  { icon: 'sparkle', text: '总结最近的 Wiki 与笔记内容' },
  { icon: 'link2', text: '查找关于…的笔记出处' },
]

function suggest(q: { text: string }) {
  const el = composerEl.value
  if (el) {
    el.textContent = q.text
    syncComposer()
  } else {
    input.value = q.text
  }
  void ask()
}

const canSend = computed(
  () => inputBody.value.trim().length > 0 && !streaming.value && !llmMissing.value,
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

function formatPreviewTime(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function persistChatLayout() {
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed.value ? '1' : '0')
    localStorage.setItem(SPLIT_RATIO_KEY, String(splitRatio.value))
  } catch {
    /* 隐私模式下 localStorage 可能不可用 */
  }
}

function loadChatLayout() {
  try {
    sidebarCollapsed.value = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1'
    const ratio = Number(localStorage.getItem(SPLIT_RATIO_KEY))
    if (Number.isFinite(ratio) && ratio >= 0.35 && ratio <= 0.72) {
      splitRatio.value = ratio
    }
  } catch {
    /* 忽略不可用的本地存储 */
  }
}

function setSidebarCollapsed(value: boolean) {
  sidebarCollapsed.value = value
  persistChatLayout()
}

function toggleSidebarCollapsed() {
  setSidebarCollapsed(!sidebarCollapsed.value)
}

/** 引用预览展开时收起左侧主导航，把宽度让给双栏阅读。 */
function maybeCollapseNavForPreview() {
  if (!isWide.value) return
  autoCollapseNav()
}

function onWideChange(event: MediaQueryListEvent) {
  isWide.value = event.matches
  if (!event.matches) {
    stopSplitDrag()
    // 预览变成窄屏抽屉后不再占用双栏宽度，导航恢复原状。
    restoreNav()
  } else if (citationPane.value) {
    // 窄屏抽屉在拉宽后变回并排双栏，同样给阅读区让位。
    maybeCollapseNavForPreview()
  }
}

function onSplitDrag(event: PointerEvent) {
  if (!splitDrag) return
  const delta = (splitDrag.startX - event.clientX) / splitDrag.width
  splitRatio.value = Math.min(0.72, Math.max(0.35, splitDrag.startRatio + delta))
}

function stopSplitDrag() {
  if (!splitDrag) return
  splitDrag = null
  window.removeEventListener('pointermove', onSplitDrag)
  window.removeEventListener('pointerup', stopSplitDrag)
  window.removeEventListener('pointercancel', stopSplitDrag)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  persistChatLayout()
}

function startSplitDrag(event: PointerEvent) {
  if (!isWide.value || !citationPane.value) return
  const el = splitEl.value
  if (!el) return
  splitDrag = {
    startX: event.clientX,
    startRatio: splitRatio.value,
    width: Math.max(el.getBoundingClientRect().width, 1),
  }
  window.addEventListener('pointermove', onSplitDrag)
  window.addEventListener('pointerup', stopSplitDrag)
  window.addEventListener('pointercancel', stopSplitDrag)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function closeCitationPane() {
  citationPaneSeq += 1
  citationPane.value = null
  activeCite.value = null
  restoreNav()
}

/** 点击引用来源：笔记 / Wiki 默认在右侧预览，网页仍在新标签打开。 */
async function previewCitation(citation: Citation, msgIndex: number, citeIndex: number) {
  if (citation.collection === 'web') {
    openCitation(citation)
    return
  }
  if (
    (citation.collection !== 'note' && citation.collection !== 'wiki') ||
    !citation.target_id
  ) {
    openCitation(citation)
    return
  }
  const collection: 'note' | 'wiki' = citation.collection === 'wiki' ? 'wiki' : 'note'
  const wasOpen = citationPane.value !== null
  const seq = ++citationPaneSeq
  activeCite.value = { msg: msgIndex, cite: citeIndex }
  citationPane.value = {
    citation,
    collection,
    msgIndex,
    citeIndex,
    loading: true,
    error: '',
    title: citation.title || (collection === 'note' ? '笔记' : 'Wiki'),
    body: '',
    kind: citation.kind || '',
    kbName: citation.kb_name || '',
    updatedAt: '',
    locked: false,
    lockHint: '',
  }
  if (!wasOpen) maybeCollapseNavForPreview()
  const kbId = citation.kb_id || kbs.currentKbId || undefined
  try {
    if (collection === 'note') {
      const note = await request<NotePreviewResponse>(
        `/notes/${encodeURIComponent(citation.target_id)}`,
        { kbId },
      )
      if (seq !== citationPaneSeq || !citationPane.value) return
      citationPane.value.title = note.title || citationPane.value.title
      citationPane.value.body = note.body_md || ''
      citationPane.value.kind = note.kind || citationPane.value.kind
      citationPane.value.updatedAt = note.updated_at || ''
      citationPane.value.locked = Boolean(note.is_locked)
      citationPane.value.lockHint = note.lock_hint || ''
    } else {
      const page = await request<WikiPreviewResponse>(
        `/wiki/${encodeURIComponent(citation.target_id)}`,
        { kbId },
      )
      if (seq !== citationPaneSeq || !citationPane.value) return
      citationPane.value.title = page.title || citationPane.value.title
      citationPane.value.body = page.body_md || ''
      citationPane.value.kind = page.page_type || ''
      citationPane.value.updatedAt = page.updated_at || ''
    }
  } catch (e: any) {
    if (seq !== citationPaneSeq || !citationPane.value) return
    citationPane.value.error = e?.message || '内容加载失败'
  } finally {
    if (seq === citationPaneSeq && citationPane.value) {
      citationPane.value.loading = false
    }
  }
}

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** 点击回答里的笔记链接：在右侧预览，不离开当前问答。 */
function previewNoteLink(payload: { collection: 'note' | 'wiki'; id: string }) {
  // 模型偶尔会把工具返回的 UUID 抄错，直接请求只会得到 422；给出可读提示。
  if (!UUID_RE.test(payload.id)) {
    toast.error('这条笔记链接已损坏，请重新提问生成')
    return
  }
  const citation: Citation = {
    kb_id: kbs.currentKbId,
    kb_name: '',
    collection: payload.collection,
    title: '',
    chunk_text: '',
    target_id: payload.id,
  }
  void previewCitation(citation, -1, -1)
}

/** 右侧预览里的「打开完整笔记 / Wiki」沿用原有深链跳转。 */
function openPreviewTarget() {
  const pane = citationPane.value
  if (!pane) return
  const citation = pane.citation
  closeCitationPane()
  openCitation(citation)
}

function retryCitationPane() {
  const pane = citationPane.value
  if (!pane) return
  void previewCitation(pane.citation, pane.msgIndex, pane.citeIndex)
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
const writebackKbOptions = computed(() =>
  kbs.kbs.map((kb) => ({ value: kb.id, label: kb.name })),
)

function setWritebackKb(value: string | number) {
  writebackKbId.value = String(value)
}

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
      class="fixed inset-0 z-20 bg-slate-900/20 backdrop-blur-[1px] lg:hidden"
      @click="sidebarOpen = false"
    />

    <!-- 会话侧栏 -->
    <aside
      class="chat-sidebar z-30 flex h-full w-64 shrink-0 flex-col border-r border-slate-200/70 bg-white/70 backdrop-blur-xl"
      :class="
        sidebarOpen
          ? 'absolute inset-y-0 left-0 flex shadow-xl lg:static lg:shadow-none'
          : sidebarCollapsed
            ? 'hidden'
            : 'hidden lg:flex'
      "
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
          class="hidden h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 lg:grid"
          title="收起会话列表"
          aria-label="收起会话列表"
          @click="toggleSidebarCollapsed"
        >
          <KiwiIcon name="panelLeftClose" :size="15" />
        </button>
        <button
          type="button"
          class="grid h-8 w-8 place-items-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 lg:hidden"
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
    <div class="chat-main relative flex min-w-0 flex-1 flex-col">
      <!-- 会话标题 / 范围 / 意图 / 模型 -->
      <header class="chat-header relative z-20 shrink-0 border-b border-slate-200/60 bg-white/55 px-4 py-2 backdrop-blur-xl max-md:px-2">
        <div class="mx-auto flex w-full max-w-[1120px] flex-wrap items-center gap-2">
          <button
            v-if="sidebarCollapsed"
            type="button"
            class="hidden h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white/80 text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700 lg:inline-flex"
            title="展开会话列表"
            aria-label="展开会话列表"
            @click="setSidebarCollapsed(false)"
          >
            <KiwiIcon name="panelLeftOpen" :size="13" />
          </button>
          <button
            type="button"
            class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white/80 text-slate-600 hover:border-kiwi-300 hover:text-kiwi-700 lg:hidden"
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
                  :class="saving ? 'animate-pulse' : ''"
                  :style="{
                    background: saving
                      ? 'rgb(var(--theme-text-subtle))'
                      : 'rgb(var(--theme-accent))',
                  }"
                />
                {{ saving ? '保存中…' : '已自动保存' }}
              </span>
              <span v-if="sessionLoading" class="inline-flex items-center gap-1">
                <KiwiIcon name="loader" :size="9" :spin="true" />
                加载会话…
              </span>
            </p>
          </div>

          <div class="flex shrink-0 items-center gap-1.5 max-md:w-full max-md:justify-end max-md:overflow-x-auto max-md:pb-0.5">
            <div class="relative shrink-0" data-chat-menu>
              <button
                type="button"
                class="inline-flex h-7 items-center gap-1.5 rounded-lg border border-slate-200 bg-white/80 px-2.5 text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700"
                @click="toggleScopeMenu"
              >
                <KiwiIcon name="database" :size="12" class="text-slate-400" />
                <span class="max-w-[11rem] truncate max-md:max-w-[5.5rem]">范围：{{ scopeLabel }}</span>
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

            <div class="relative shrink-0" data-chat-menu>
              <button
                type="button"
                class="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg border px-2.5 text-[11px] transition"
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
                  <KiwiDateInput
                    v-model="filterFrom"
                    class="min-w-0 flex-1"
                    trigger-class="!h-7 !w-full !px-1.5 !text-[10.5px]"
                    placeholder="开始"
                  />
                  <span class="text-slate-300">→</span>
                  <KiwiDateInput
                    v-model="filterTo"
                    :min="filterFrom"
                    class="min-w-0 flex-1"
                    trigger-class="!h-7 !w-full !px-1.5 !text-[10.5px]"
                    placeholder="结束"
                  />
                </div>
                <p class="mt-2 rounded-lg bg-slate-50 px-2 py-1.5 text-[10px] leading-relaxed text-slate-400">
                  设置任一筛选后只检索笔记，Wiki 没有类型 / 标签 / 更新时间属性。
                </p>
              </div>
            </div>

            <div class="relative shrink-0" data-chat-menu>
              <button
                type="button"
                class="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg border border-slate-200 bg-white/80 px-2.5 text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700"
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

      <!-- 聊天主列 + 引用预览：桌面双栏（默认 50/50，可拖动分隔条），移动端预览为右侧抽屉 -->
      <div ref="splitEl" class="relative flex min-h-0 flex-1">
        <div class="flex min-w-0 flex-1 flex-col" :style="chatColumnStyle">
      <!-- 消息区 -->
      <div ref="scrollEl" class="chat-scroll flex-1 overflow-y-auto px-4 py-6 sm:px-6" @scroll="onScroll">
        <div class="chat-thread mx-auto w-full space-y-6" style="max-width: min(1120px, 100%)">
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

                <!-- Agent 行动计划：先列步骤，再逐项执行，完成后保留回看 -->
                <div
                  v-if="m.plan?.length"
                  class="mb-2 rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2 backdrop-blur-sm"
                >
                  <div class="mb-1.5 flex items-center gap-1.5 text-[10.5px] font-medium text-slate-500">
                    <KiwiIcon name="sparkle" :size="10" />
                    <span>行动计划</span>
                    <span class="ml-auto rounded px-1 text-[9.5px] tabular-nums text-slate-400">
                      {{ planProgress(m) }}
                    </span>
                  </div>
                  <ol class="space-y-1">
                    <li
                      v-for="(step, si) in m.plan"
                      :key="step.id"
                      class="flex items-start gap-1.5 text-[11px] leading-relaxed"
                    >
                      <span
                        class="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border text-[8px] font-medium"
                        :class="step.status === 'pending' ? 'border-slate-200 text-slate-300' : 'border-transparent'"
                        :style="step.status === 'pending'
                          ? undefined
                          : { background: 'rgb(var(--theme-accent) / 0.12)', color: 'rgb(var(--theme-accent))' }"
                      >
                        <KiwiIcon v-if="step.status === 'done'" name="check" :size="8" />
                        <span
                          v-else-if="step.status === 'active'"
                          class="h-1 w-1 animate-pulse rounded-full bg-current"
                        />
                        <span v-else>{{ si + 1 }}</span>
                      </span>
                      <span
                        class="min-w-0"
                        :class="step.status === 'active'
                          ? 'font-medium text-slate-600'
                          : step.status === 'done'
                            ? 'text-slate-500'
                            : 'text-slate-400'"
                      >
                        {{ step.title }}
                      </span>
                    </li>
                  </ol>
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
                      :class="m.steps.some((step) => step.status === 'error') ? 'text-amber-500' : ''"
                      :style="m.steps.some((step) => step.status === 'error')
                        ? undefined
                        : { color: 'rgb(var(--theme-accent))' }"
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
                          :class="step.status === 'error' ? 'bg-amber-100 text-amber-600' : ''"
                          :style="step.status === 'error'
                            ? undefined
                            : {
                                background: 'rgb(var(--theme-accent) / 0.14)',
                                color: 'rgb(var(--theme-accent))',
                              }"
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
                    :note-ref-sources="m.citations"
                    note-link-mode="preview"
                    @citation-click="(n: number) => focusCitation(m, n)"
                    @note-click="previewNoteLink"
                  />
                  <span
                    v-if="m.streaming && m.content"
                    class="ml-0.5 inline-block h-3.5 w-[2px] translate-y-0.5 animate-pulse rounded-full bg-kiwi-400 align-baseline"
                  />
                </div>

                <!-- 写操作确认：危险操作先询问，用户确认前不落库 -->
                <div
                  v-if="m.pendingAction
                    && (m.actionState === 'idle'
                      || m.actionState === 'approving'
                      || m.actionState === 'failed'
                      || m.actionState === 'expired')"
                  :data-approval-action="m.pendingAction.action_id"
                  class="mt-2.5 overflow-hidden rounded-xl border bg-white/70 backdrop-blur-sm"
                  :style="{ borderColor: 'rgb(var(--theme-accent) / 0.28)' }"
                >
                  <div class="flex items-start gap-2 px-3 pt-2.5">
                    <span
                      class="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg"
                      :style="{
                        background: 'rgb(var(--theme-accent) / 0.12)',
                        color: 'rgb(var(--theme-accent))',
                      }"
                    >
                      <KiwiIcon name="alert" :size="11" />
                    </span>
                    <div class="min-w-0 flex-1">
                      <p class="text-[11px] font-medium text-slate-600">需要你确认后才会执行</p>
                      <p class="mt-0.5 break-words text-[12px] leading-relaxed text-slate-700">
                        {{ m.pendingAction.label }}
                      </p>
                      <p
                        v-if="m.pendingAction.summary && m.pendingAction.summary !== m.pendingAction.label"
                        class="mt-0.5 break-words text-[10.5px] leading-relaxed text-slate-400"
                      >
                        {{ m.pendingAction.summary }}
                      </p>
                      <dl
                        v-if="actionArgRows(m.pendingAction).length"
                        class="mt-1.5 space-y-0.5 rounded-lg px-2 py-1.5"
                        style="background: rgb(var(--theme-surface-muted))"
                      >
                        <div
                          v-for="row in actionArgRows(m.pendingAction)"
                          :key="row.key"
                          class="flex gap-1.5 text-[10.5px] leading-relaxed"
                        >
                          <dt class="w-12 shrink-0 text-slate-400">{{ row.label }}</dt>
                          <dd class="min-w-0 whitespace-pre-wrap break-words text-slate-600">
                            {{ row.value }}
                          </dd>
                        </div>
                      </dl>
                    </div>
                  </div>
                  <div class="mt-2 flex items-center justify-end gap-2 border-t border-slate-100 px-3 py-2">
                    <template v-if="m.actionState === 'idle'">
                      <button
                        type="button"
                        class="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700"
                        @click="resolveAction(m, false)"
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        class="rounded-lg px-2.5 py-1 text-[11px] font-medium shadow-sm transition hover:opacity-90"
                        :style="{
                          background: 'rgb(var(--theme-accent))',
                          color: 'rgb(var(--theme-accent-foreground))',
                        }"
                        @click="resolveAction(m, true)"
                      >
                        允许执行
                      </button>
                    </template>
                    <span
                      v-else-if="m.actionState === 'approving'"
                      class="inline-flex items-center gap-1 text-[10.5px] text-slate-400"
                    >
                      <KiwiIcon name="loader" :size="10" :spin="true" />
                      正在执行…
                    </span>
                    <span v-else-if="m.actionState === 'failed'" class="text-[10.5px] text-amber-600">
                      执行失败，请重新提问
                    </span>
                    <span v-else-if="m.actionState === 'expired'" class="text-[10.5px] text-slate-400">
                      确认已过期，请重新提问
                    </span>
                  </div>
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
                    <span class="ml-auto hidden sm:inline">点击预览 · 悬浮查看摘要</span>
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
                      @click="previewCitation(c, i, ci)"
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
      <div class="chat-composer px-4 pb-4 pt-2 sm:px-6">
        <div class="mx-auto w-full" style="max-width: min(1120px, 100%)">
          <!-- data-chat-menu：点击输入区时不应关闭 @ 选择器 -->
          <div
            data-chat-menu
            class="chat-composer-inner relative rounded-2xl border border-slate-300/70 bg-transparent p-1.5 transition-all duration-200 focus-within:border-kiwi-400/70 focus-within:ring-2 focus-within:ring-kiwi-300/30"
          >
            <div class="flex items-end gap-2">
              <!-- contenteditable：@ 引用作为行内高亮 token 与正文一起显示、一起删除 -->
              <div
                ref="composerEl"
                contenteditable="true"
                role="textbox"
                aria-multiline="true"
                aria-label="输入问题"
                spellcheck="false"
                data-placeholder="输入问题，@ 引用笔记或目录…"
                :data-empty="composerEmpty ? 'true' : 'false'"
                class="composer-editor max-h-36 min-h-9 flex-1 overflow-y-auto whitespace-pre-wrap break-words bg-transparent px-3 py-2 text-sm text-slate-700 outline-none"
                @input="onComposerInput"
                @keydown="onComposerKeydown"
                @paste="onComposerPaste"
                @blur="syncComposer"
                @compositionstart="onComposerCompositionStart"
                @compositionend="onComposerCompositionEnd"
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
            <span class="ml-auto hidden sm:inline">Enter 发送 · Shift + Enter 换行</span>
          </p>
        </div>
      </div>
        </div>

        <!-- 移动端遮罩：点击聊天区关闭预览 -->
        <div
          v-if="citationPane"
          class="absolute inset-0 z-20 bg-slate-900/15 lg:hidden"
          @click="closeCitationPane"
        />

        <!-- 右侧引用预览：桌面与聊天区并排，移动端从右侧滑出 -->
        <Transition name="citation-pane">
          <aside
            v-if="citationPane"
            class="citation-pane absolute inset-y-0 right-0 z-30 flex w-full max-w-[32rem] flex-col border-l shadow-xl lg:relative lg:z-auto lg:w-1/2 lg:max-w-none lg:shadow-none"
            :style="citationPaneStyle"
            aria-label="引用预览"
          >
            <!-- 桌面端拖动分隔条：在 35%–72% 之间调整预览宽度 -->
            <div
              v-if="isWide"
              class="citation-resize-handle hidden lg:block"
              title="拖动调整宽度"
              aria-label="拖动调整预览宽度"
              @pointerdown.prevent="startSplitDrag"
            />

            <div
              class="h-0.5 shrink-0"
              :style="{
                background:
                  'linear-gradient(90deg, rgb(var(--theme-accent) / 0.55), rgb(var(--theme-accent) / 0.06) 58%, transparent)',
              }"
            />

            <header class="shrink-0 border-b" :style="{ borderColor: 'rgb(var(--theme-border) / 0.7)' }">
              <div class="flex items-center gap-2 px-4 pt-3 text-[10px] text-slate-400">
                <span
                  class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium"
                  :style="{
                    background: 'rgb(var(--theme-accent) / 0.1)',
                    color: 'rgb(var(--theme-accent))',
                  }"
                >
                  <KiwiIcon :name="citationPane.collection === 'wiki' ? 'wiki' : 'note'" :size="11" />
                  {{ citationPane.collection === 'wiki' ? 'Wiki' : (NOTE_KIND_LABEL[citationPane.kind] || '笔记') }}
                </span>
                <span v-if="citationPane.kbName" class="min-w-0 truncate">{{ citationPane.kbName }}</span>
                <span v-if="formatPreviewTime(citationPane.updatedAt)" class="ml-auto shrink-0 tabular-nums">
                  {{ formatPreviewTime(citationPane.updatedAt) }}
                </span>
              </div>
              <div class="flex items-start gap-3 px-4 pb-3 pt-1.5">
                <h3 class="line-clamp-2 min-w-0 flex-1 text-[15px] font-semibold leading-snug text-slate-800">
                  {{ citationPane.title }}
                </h3>
                <div class="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    class="inline-flex h-7 items-center gap-1 rounded-lg border px-2 text-[11px] font-medium transition hover:opacity-90"
                    :style="{
                      borderColor: 'rgb(var(--theme-accent) / 0.32)',
                      background: 'rgb(var(--theme-accent) / 0.08)',
                      color: 'rgb(var(--theme-accent))',
                    }"
                    :title="citationPane.collection === 'wiki' ? '在 Wiki 中打开完整页面' : '在笔记中打开完整内容'"
                    @click="openPreviewTarget"
                  >
                    <KiwiIcon name="external" :size="12" />
                    <span class="whitespace-nowrap">打开{{ citationPane.collection === 'wiki' ? ' Wiki' : '笔记' }}</span>
                  </button>
                  <button
                    type="button"
                    class="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                    title="关闭预览（Esc）"
                    aria-label="关闭预览"
                    @click="closeCitationPane"
                  >
                    <KiwiIcon name="close" :size="14" />
                  </button>
                </div>
              </div>
            </header>

            <div class="min-h-0 flex-1 overflow-y-auto">
              <div class="mx-auto w-full max-w-[46rem] px-5 py-5 lg:px-7 lg:py-6">
                <div v-if="citationPane.loading" class="space-y-3 py-1">
                  <div class="flex items-center gap-1.5 text-[11px] text-slate-400">
                    <KiwiIcon name="loader" :size="11" :spin="true" />
                    正在读取内容…
                  </div>
                  <div class="h-3 w-2/5 animate-pulse rounded-full bg-slate-100" />
                  <div class="h-3 w-full animate-pulse rounded-full bg-slate-100" />
                  <div class="h-3 w-11/12 animate-pulse rounded-full bg-slate-100" />
                  <div class="h-3 w-4/5 animate-pulse rounded-full bg-slate-100" />
                  <div class="h-3 w-3/5 animate-pulse rounded-full bg-slate-100" />
                </div>

                <div
                  v-else-if="citationPane.error"
                  class="rounded-xl border px-4 py-3"
                  :style="{
                    borderColor: 'rgb(var(--theme-border) / 0.9)',
                    background: 'rgb(var(--theme-surface-muted) / 0.65)',
                  }"
                >
                  <p class="flex items-center gap-1.5 text-[12px] font-medium text-slate-600">
                    <KiwiIcon name="alert" :size="13" />
                    {{ citationPane.error }}
                  </p>
                  <button
                    type="button"
                    class="mt-2.5 inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[11px] font-medium transition hover:opacity-85"
                    :style="{
                      borderColor: 'rgb(var(--theme-accent) / 0.32)',
                      color: 'rgb(var(--theme-accent))',
                    }"
                    @click="retryCitationPane"
                  >
                    <KiwiIcon name="refresh" :size="11" />
                    重试
                  </button>
                </div>

                <div
                  v-else-if="citationPane.locked"
                  class="rounded-xl border px-4 py-3"
                  :style="{
                    borderColor: 'rgb(var(--theme-border) / 0.9)',
                    background: 'rgb(var(--theme-surface-muted) / 0.65)',
                  }"
                >
                  <p class="flex items-center gap-1.5 text-[12px] font-medium text-slate-600">
                    <KiwiIcon name="lock" :size="13" />
                    该笔记已上锁
                  </p>
                  <p class="mt-1 text-[11px] leading-relaxed text-slate-400">
                    预览不展示上锁正文{{ citationPane.lockHint ? `（提示：${citationPane.lockHint}）` : '' }}，请打开笔记后输入密码查看。
                  </p>
                </div>

                <template v-else>
                  <div
                    v-if="citationPane.body.trim()"
                    class="citation-pane-markdown text-[13.5px] leading-7 text-slate-700"
                  >
                    <MarkdownView :content="citationPane.body" />
                  </div>
                  <div v-else class="space-y-3">
                    <p class="text-[11px] leading-relaxed text-slate-400">
                      这篇{{ citationPane.collection === 'wiki' ? ' Wiki 页面' : '笔记' }}没有可预览的 Markdown 正文，下面是命中的来源片段。
                    </p>
                    <p
                      class="whitespace-pre-wrap break-words rounded-xl border px-4 py-3 text-[12.5px] leading-relaxed text-slate-600"
                      :style="{
                        borderColor: 'rgb(var(--theme-border) / 0.85)',
                        background: 'rgb(var(--theme-surface-muted) / 0.55)',
                      }"
                    >
                      {{ citationPreview(citationPane.citation.chunk_text) || citationPreview(citationPane.citation.quote || '') || '（无片段）' }}
                    </p>
                  </div>
                </template>
              </div>
            </div>
          </aside>
        </Transition>
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
          <KiwiSelect
            :model-value="writebackKbId"
            :options="writebackKbOptions"
            width="w-64"
            variant="input"
            trigger-class="!h-9 !w-full !justify-between !rounded-xl !border !border-slate-200 !bg-white !px-3 !text-[13px] !text-slate-600"
            @update:model-value="setWritebackKb"
          />
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
/* 拖动分隔条：细线只在 hover / 拖动时显形，避免打断阅读。 */
.citation-resize-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  left: -5px;
  z-index: 10;
  width: 10px;
  cursor: col-resize;
  touch-action: none;
}
.citation-resize-handle::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 4px;
  width: 1px;
  background: transparent;
  transition: background 0.15s ease;
}
.citation-resize-handle:hover::after,
.citation-resize-handle:active::after {
  background: rgb(var(--theme-accent) / 0.55);
}
.citation-pane-enter-active,
.citation-pane-leave-active {
  transition: transform 0.22s ease, opacity 0.22s ease;
}
.citation-pane-enter-from,
.citation-pane-leave-to {
  opacity: 0;
  transform: translateX(16px);
}
@media (max-width: 1023px) {
  .citation-pane-enter-from,
  .citation-pane-leave-to {
    transform: translateX(100%);
  }
}
.citation-pane-markdown :deep(img),
.citation-pane-markdown :deep(video) {
  max-width: 100%;
  height: auto;
  border-radius: 8px;
}
.citation-pane-markdown :deep(pre) {
  overflow-x: auto;
}
.citation-pane-markdown :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}

/* contenteditable 没有原生 placeholder：空状态用伪元素，颜色走主题令牌。 */
.composer-editor {
  position: relative;
}
.composer-editor[data-empty='true']::before {
  content: attr(data-placeholder);
  position: absolute;
  left: 0.75rem;
  top: 0.5rem;
  pointer-events: none;
  color: rgb(var(--theme-text-subtle));
}
/* @ 引用 token：正文里高亮显示，原子删除，配色跟随当前主题强调色。 */
.composer-editor :deep(.chat-mention) {
  display: inline;
  margin: 0 0.05em;
  padding: 0.05em 0.35em;
  border-radius: 0.375rem;
  font-weight: 500;
  white-space: nowrap;
  color: rgb(var(--theme-accent));
  background: rgb(var(--theme-accent) / 0.14);
  box-shadow: inset 0 0 0 1px rgb(var(--theme-accent) / 0.22);
}
.composer-editor :deep(.chat-mention[data-mention-type='folder']) {
  box-shadow: inset 0 0 0 1px rgb(var(--theme-accent) / 0.32);
  font-style: italic;
}
</style>
