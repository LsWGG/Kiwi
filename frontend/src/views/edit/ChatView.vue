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
import { openSSE } from '@/api/sse'
import { request } from '@/api/client'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import { toast } from '@/components/ui/toast'

interface Citation {
  kb_id: string
  kb_name: string
  collection: string
  title: string
  slug?: string | null
  chunk_text: string
  target_id: string
  kind?: string
}

interface Msg {
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  streaming?: boolean
  created_at?: string
}

interface SessionSummary {
  id: string
  title: string
  message_count: number
  scope: { kb_ids?: string[]; scope?: ScopeMode }
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
const router = useRouter()

const messages = ref<Msg[]>([])
const input = ref('')
const streaming = ref(false)
const scrollEl = ref<HTMLElement>()
const autoScroll = ref(true)

const scopeMode = ref<ScopeMode>('kb')
const multiIds = ref<string[]>([])
const intent = ref<Intent>('auto')
const llmConfigId = ref('')
const scopeMenuOpen = ref(false)

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
    }
    if (saved.scopeMode) scopeMode.value = saved.scopeMode
    if (Array.isArray(saved.multiIds)) multiIds.value = saved.multiIds
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

onMounted(async () => {
  loadSettings()
  await Promise.all([
    kbs.kbs.length ? Promise.resolve() : kbs.fetchKbs().catch(() => undefined),
    llm.configs.length ? Promise.resolve() : llm.fetchConfigs().catch(() => undefined),
  ])
  await bootstrapSessions()
  scrollToBottom(true)
})
onUnmounted(() => {
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
  if (item.intent === 'raw') intent.value = 'note'
  else if (item.intent) intent.value = item.intent
  llmConfigId.value = item.llm_config_id || ''
}

let hydratingSession = false
function applySession(detail: SessionDetail) {
  hydratingSession = true
  currentSessionId.value = detail.id
  messages.value = (detail.messages || []).map((m) => ({
    role: m.role,
    content: String(m.content || ''),
    citations: Array.isArray(m.citations) ? m.citations : [],
    streaming: false,
    created_at: m.created_at,
  }))
  scopeFromSession(detail)
  saveSettings()
  sidebarOpen.value = false
  scrollToBottom(true)
  void nextTick(() => {
    hydratingSession = false
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

async function fetchSessions() {
  sessionsLoading.value = true
  try {
    const res = await request<{ items: SessionSummary[] }>('/chat/sessions')
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
  return { kb_ids: scopeKbIds.value, scope: scopeMode.value }
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
    await request('/chat/sessions', { method: 'DELETE' })
    sessions.value = []
    newConversation()
    toast.success('会话历史已清空')
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

function historyMessages() {
  return messages.value
    .filter((m) => !m.streaming && m.content.trim())
    .slice(-12)
    .map((m) => ({ role: m.role, content: m.content }))
}

// ---------- 提问 ----------
async function ask() {
  const text = input.value.trim()
  if (!text || streaming.value) return
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

  openSSE(
    '/chat/stream',
    {
      messages: payloadMessages,
      scope: requestScope(),
      intent: intent.value,
      llm_config_id: llmConfigId.value || null,
    },
    {
      onMessage: (msg) => {
        if (msg.event === 'chunk') {
          assistant.content += msg.data?.text ?? ''
          scrollToBottom()
        } else if (msg.event === 'citation') {
          assistant.citations = msg.data?.citations ?? []
        } else if (msg.event === 'done') {
          assistant.streaming = false
          streaming.value = false
          assistant.created_at = new Date().toISOString()
          scrollToBottom(true)
          void saveSessionNow()
        } else if (msg.event === 'error') {
          assistant.content += `\n\n⚠️ ${msg.data?.message ?? '出错了'}`
          assistant.streaming = false
          streaming.value = false
          void saveSessionNow()
        }
      },
      onError: (e) => {
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

const canSend = computed(() => input.value.trim().length > 0 && !streaming.value)

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
  if (citation.collection === 'note') {
    return NOTE_KIND_LABEL[citation.kind || ''] || '笔记'
  }
  return 'Wiki'
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

function openCitation(citation: Citation) {
  if (citation.collection === 'wiki' && citation.target_id) {
    void router.push({ name: 'wiki-page', params: { id: citation.target_id } })
  } else if (citation.collection === 'note' && citation.target_id) {
    void router.push(`/notes/${citation.target_id}`)
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
      c.collection === 'wiki' ? `/wiki/${c.target_id}` : `/notes/${c.target_id}`
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
          清空全部历史
        </button>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="relative flex min-w-0 flex-1 flex-col">
      <!-- 会话标题 / 范围 / 意图 / 模型 -->
      <header class="shrink-0 border-b border-slate-200/60 bg-white/55 px-4 py-2 backdrop-blur-xl">
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
            <div class="relative">
              <button
                type="button"
                class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white/80 px-2.5 py-1 text-[11px] text-slate-600 transition hover:border-kiwi-300 hover:text-kiwi-700"
                @click="scopeMenuOpen = !scopeMenuOpen"
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

            <select
              v-model="intent"
              class="kiwi-input !w-auto !py-1 text-[11px]"
              title="检索侧重"
            >
              <option v-for="opt in intentOptions" :key="opt.id" :value="opt.id" :title="opt.hint">
                {{ opt.label }}
              </option>
            </select>

            <select
              v-model="llmConfigId"
              class="kiwi-input hidden !w-auto !py-1 text-[11px] sm:block"
              title="仅本次对话覆盖模型"
            >
              <option value="">默认模型</option>
              <option v-for="cfg in llm.configs" :key="cfg.id" :value="cfg.id">
                {{ cfg.name }} · {{ cfg.model_name }}
              </option>
            </select>
          </div>
        </div>
      </header>

      <!-- 消息区 -->
      <div ref="scrollEl" class="flex-1 overflow-y-auto px-4 py-6 sm:px-6" @scroll="onScroll">
        <div class="mx-auto w-full space-y-6" style="max-width: min(1120px, 100%)">
          <!-- 空态：建议 chips -->
          <div v-if="!messages.length" class="text-center pt-12 sm:pt-16 animate-fade-up">
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
              class="max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-gradient-to-br from-kiwi-500 to-kiwi-700 px-4 py-2.5 text-[13.5px] leading-relaxed text-white shadow-sm sm:max-w-[80%]"
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
                  <span v-if="m.streaming" class="inline-flex items-center gap-1 text-kiwi-500">
                    <span class="h-1 w-1 animate-pulse rounded-full bg-kiwi-500" />
                    正在检索并生成回答…
                  </span>
                  <span v-else-if="m.citations?.length">{{ m.citations.length }} 个引用来源</span>
                </div>

                <div class="text-[13.5px] leading-7 text-slate-700">
                  <MarkdownView
                    :content="m.content"
                    :citation-count="m.citations?.length || 0"
                    @citation-click="(n: number) => focusCitation(m, n)"
                  />
                  <span
                    v-if="m.streaming"
                    class="ml-1 inline-flex items-center gap-0.5 align-baseline text-kiwi-500"
                  >
                    <span class="h-1 w-1 animate-blink rounded-full bg-current" :style="{ animationDelay: '0ms' }" />
                    <span class="h-1 w-1 animate-blink rounded-full bg-current" :style="{ animationDelay: '200ms' }" />
                    <span class="h-1 w-1 animate-blink rounded-full bg-current" :style="{ animationDelay: '400ms' }" />
                  </span>
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
                        c.collection === 'note'
                          ? 'hover:bg-sky-50'
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
                        :class="c.collection === 'note' ? 'bg-sky-100 text-sky-700' : 'bg-kiwi-100 text-kiwi-700'"
                      >
                        {{ ci + 1 }}
                      </span>
                      <span class="max-w-[15rem] truncate text-[11px] text-slate-600">{{ c.title }}</span>
                      <span
                        class="shrink-0 rounded px-1 text-[9px]"
                        :class="c.collection === 'note' ? 'bg-sky-50 text-sky-600' : 'bg-kiwi-50 text-kiwi-600'"
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
          <div
            class="flex items-end gap-2 rounded-2xl border border-slate-300/70 bg-transparent p-1.5 transition-all duration-200 focus-within:border-kiwi-400/70 focus-within:ring-2 focus-within:ring-kiwi-300/30"
          >
            <textarea
              ref="composerEl"
              v-model="input"
              rows="1"
              placeholder="输入问题，Enter 发送（Shift+Enter 换行）…"
              class="max-h-36 flex-1 resize-none bg-transparent px-3 py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400"
              @input="resizeComposer"
              @keydown.enter.exact.prevent="ask"
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
          <p class="mt-2 flex items-center gap-1.5 text-[10.5px] text-slate-400">
            <span
              class="inline-block h-1.5 w-1.5 rounded-full"
              :class="scopeMode === 'global' || kbs.currentKb ? 'animate-pulse-ring bg-kiwi-500' : 'bg-slate-300'"
            />
            检索范围：{{ scopeLabel }}
            <span class="text-slate-300">·</span>
            {{ intent === 'wiki' ? 'Wiki 优先' : intent === 'note' ? '笔记优先' : '自动路由' }}
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
    <KiwiModal :open="clearOpen" title="清空会话历史" max-w="max-w-md" @close="clearOpen = false">
      <p class="text-sm text-slate-600">
        确定清空全部 {{ sessions.length }} 个会话吗？所有历史消息都会被删除，且不可恢复。
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
