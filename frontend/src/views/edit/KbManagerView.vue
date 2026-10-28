<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useKbsStore, type KbOverview } from '@/stores/kbs'
import { useLlmStore } from '@/stores/llm'
import { request, uploadWithProgress } from '@/api/client'
import type { NoteFolder, NoteKind, NoteSummary } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiSkeleton from '@/components/ui/KiwiSkeleton.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import { toast } from '@/components/ui/toast'

const kbs = useKbsStore()
const llm = useLlmStore()
const router = useRouter()

/** 首次点击切换知识库；再次点击当前卡片直接进入笔记工作区。 */
function selectKbCard(id: string) {
  if (kbs.currentKbId === id) {
    router.push('/notes')
    return
  }
  kbs.currentKbId = id
}

/** 系统级向量模型：线上模式下各库的本地模型选择会被忽略 */
interface EmbeddingConfigInfo {
  provider: string
  api_base: string
  api_model: string
  active_space: string
  source: string
}
const embeddingConfig = ref<EmbeddingConfigInfo | null>(null)
const embeddingProvider = computed(() =>
  embeddingConfig.value?.provider === 'openai' ? 'openai' : 'local',
)
const embeddingIsRemote = computed(() => embeddingProvider.value === 'openai')
const embeddingHint = computed(() => {
  const config = embeddingConfig.value
  if (!config) return ''
  if (embeddingIsRemote.value) {
    return config.api_model
      ? `${config.api_model}（所有知识库共享）`
      : '线上向量模型（所有知识库共享）'
  }
  return config.active_space ? `本地默认：${config.active_space}` : '本地 fastembed'
})

onMounted(() => {
  // 拉 LLM 配置，用于映射「默认模型」绑定显示
  llm.fetchConfigs().catch(() => { /* 配置拉取失败不阻塞知识库管理 */ })
  // 内置演示库状态：决定是否展示「还原」入口
  void kbs.fetchBuiltinStatus()
  request<EmbeddingConfigInfo>('/settings/embedding')
    .then((c) => {
      embeddingConfig.value = c
    })
    .catch(() => { /* 旧后端或读取失败时按本地模式展示 */ })
})

// 置顶的知识库排在前面；同组按手动排序，再按创建时间倒序。
const sortedKbs = computed(() =>
  [...kbs.kbs].sort(
    (a, b) =>
      Number(!!b.pinned) - Number(!!a.pinned) ||
      (a.sort_order ?? 0) - (b.sort_order ?? 0) ||
      (b.created_at || '').localeCompare(a.created_at || ''),
  ),
)
const pinningKbId = ref<string | null>(null)

// ---- 视图模式：正常卡片 / 列表 / 紧凑 ----
type KbViewMode = 'grid' | 'list' | 'compact'
const VIEW_MODE_KEY = 'kiwi.kbs.view-mode'
const viewMode = ref<KbViewMode>((() => {
  try {
    const value = localStorage.getItem(VIEW_MODE_KEY)
    return value === 'list' || value === 'compact' ? value : 'grid'
  } catch {
    return 'grid'
  }
})())
watch(viewMode, (value) => {
  try {
    localStorage.setItem(VIEW_MODE_KEY, value)
  } catch {
    /* 隐私模式下忽略 */
  }
})
const VIEW_MODES: Array<{ value: KbViewMode; icon: string; label: string }> = [
  { value: 'grid', icon: 'layoutTemplate', label: '正常视图' },
  { value: 'list', icon: 'list', label: '列表视图' },
  { value: 'compact', icon: 'columns', label: '紧凑视图' },
]
function setViewMode(mode: KbViewMode) {
  viewMode.value = mode
}
const gridClass = computed(() => {
  if (viewMode.value === 'list') return 'grid grid-cols-1 gap-2.5'
  if (viewMode.value === 'compact') {
    return 'grid sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-2.5'
  }
  return 'grid md:grid-cols-2 2xl:grid-cols-3 gap-4'
})

// ---- 卡片拖拽排序 ----
const dragKbId = ref<string | null>(null)
const dragOver = ref<{ id: string; pos: 'before' | 'after' } | null>(null)
const reordering = ref(false)

function onKbDragStart(event: DragEvent, kb: KbOverview) {
  dragKbId.value = kb.id
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', kb.id)
    const card = (event.currentTarget as HTMLElement).closest('.kiwi-card') as HTMLElement | null
    if (card) {
      // 拖影必须按真实抓取点定位，否则会被默认偏移到卡片左上角，
      // 导致光标和卡片「错位」。
      const rect = card.getBoundingClientRect()
      const offsetX = Math.min(Math.max(event.clientX - rect.left, 0), rect.width)
      const offsetY = Math.min(Math.max(event.clientY - rect.top, 0), rect.height)
      event.dataTransfer.setDragImage(card, offsetX, offsetY)
    }
  }
}

function onKbDragOver(event: DragEvent, kb: KbOverview) {
  if (!dragKbId.value || dragKbId.value === kb.id) return
  const source = kbs.kbs.find((item) => item.id === dragKbId.value)
  // 置顶区与普通区不交叉排序；置顶优先级由 pinned 决定。
  if (!source || !!source.pinned !== !!kb.pinned) {
    dragOver.value = null
    return
  }
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  // 排序是行优先的阅读顺序；用垂直中线判断插入到卡片前 / 后，
  // 比按水平半区判断更贴合光标位置（网格与列表视图一致）。
  const pos = event.clientY - rect.top < rect.height / 2 ? 'before' : 'after'
  dragOver.value = { id: kb.id, pos }
}

async function onKbDrop(event: DragEvent, kb: KbOverview) {
  event.preventDefault()
  const sourceId = dragKbId.value
  const position = dragOver.value
  resetKbDrag()
  if (!sourceId || !position || sourceId === kb.id || reordering.value) return
  const ids = sortedKbs.value.map((item) => item.id)
  const from = ids.indexOf(sourceId)
  if (from < 0) return
  ids.splice(from, 1)
  const overIndex = ids.indexOf(kb.id)
  if (overIndex < 0) return
  ids.splice(position.pos === 'after' ? overIndex + 1 : overIndex, 0, sourceId)
  reordering.value = true
  try {
    await kbs.reorderKbs(ids)
  } catch (e: any) {
    toast.error(e.message || '保存排序失败')
    await kbs.fetchKbs()
  } finally {
    reordering.value = false
  }
}

function resetKbDrag() {
  dragKbId.value = null
  dragOver.value = null
}

function dragClassOf(kb: KbOverview): string {
  if (dragKbId.value === kb.id) return 'opacity-45'
  if (dragOver.value?.id !== kb.id) return ''
  return dragOver.value.pos === 'before' ? 'kb-drop-before' : 'kb-drop-after'
}

async function toggleKbPin(kb: (typeof kbs.kbs)[number]) {
  pinningKbId.value = kb.id
  try {
    await request(`/kbs/${kb.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ pinned: !kb.pinned }),
    })
    await kbs.fetchKbs()
    toast.success(kb.pinned ? '已取消置顶' : '知识库已置顶')
  } catch (e: any) {
    toast.error(e.message || '置顶失败')
  } finally {
    pinningKbId.value = null
  }
}

// ---- 卡片置顶区：每个知识库在目录树中被置顶的笔记 / 分组 ----
interface PinnedCardItem {
  type: 'folder' | 'note'
  id: string
  title: string
  kind?: NoteKind
  folderName?: string
}
interface TreeResponse {
  folders: NoteFolder[]
  notes: NoteSummary[]
}
const pinnedByKb = ref<Record<string, PinnedCardItem[]>>({})

function pinnedOf(kbId: string): PinnedCardItem[] {
  return pinnedByKb.value[kbId] ?? []
}

function kindIcon(kind?: NoteKind): string {
  switch (kind) {
    case 'database':
      return 'database'
    case 'canvas':
      return 'pen'
    case 'link':
      return 'link2'
    case 'import':
      return 'fileImport'
    case 'notebook':
      return 'notebook'
    case 'sheet':
      return 'table'
    default:
      return 'fileText'
  }
}

function kindColor(kind?: NoteKind): string {
  switch (kind) {
    case 'database':
      return 'text-kiwi-500'
    case 'canvas':
      return 'text-violet-500'
    case 'link':
      return 'text-sky-500'
    case 'import':
      return 'text-emerald-500'
    case 'notebook':
      return 'text-indigo-500'
    case 'sheet':
      return 'text-emerald-600'
    default:
      return 'text-blue-500'
  }
}

async function loadPinnedCards() {
  const list = kbs.kbs
  if (!list.length) {
    pinnedByKb.value = {}
    return
  }
  const entries = await Promise.allSettled(
    list.map(async (kb) => {
      const tree = await request<TreeResponse>('/notes/tree', { kbId: kb.id })
      const folderName = new Map(tree.folders.map((folder) => [folder.id, folder.name]))
      const notes: PinnedCardItem[] = tree.notes
        .filter((note) => !!note.props_json?.pinned)
        .map((note) => ({
          type: 'note' as const,
          id: note.id,
          title: note.title || '无标题',
          kind: note.kind,
          folderName: note.folder_id ? folderName.get(note.folder_id) : undefined,
        }))
      const folders: PinnedCardItem[] = tree.folders
        .filter((folder) => !!folder.pinned && folder.name.trim() !== '收件箱')
        .map((folder) => ({
          type: 'folder' as const,
          id: folder.id,
          title: folder.name,
        }))
      return { id: kb.id, items: [...notes, ...folders] }
    }),
  )
  const next: Record<string, PinnedCardItem[]> = {}
  for (const entry of entries) {
    if (entry.status === 'fulfilled') next[entry.value.id] = entry.value.items
  }
  pinnedByKb.value = next
}

// 知识库列表加载 / 变化后刷新置顶卡片；失败不影响知识库管理主流程。
watch(
  () => kbs.kbs.map((kb) => kb.id).join('|'),
  () => {
    loadPinnedCards().catch(() => { /* 置顶信息按可选增强处理 */ })
  },
  { immediate: true },
)

function openPinned(kbId: string, item: PinnedCardItem) {
  kbs.currentKbId = kbId
  if (item.type === 'note') router.push(`/notes/${item.id}`)
  else router.push('/notes')
}

/** 根据 llm_config_id 取配置名；null → 继承全局默认 */
function modelLabelOf(cfgId: string | null): string {
  if (!cfgId) return '继承全局默认'
  const cfg = llm.configs.find((c) => c.id === cfgId)
  if (!cfg) return '未知模型'
  return cfg.model_name ? `${cfg.name} · ${cfg.model_name}` : cfg.name
}
function modelColorOf(cfgId: string | null): string {
  return cfgId ? 'text-kiwi-600' : 'text-slate-400'
}

/** 学习画像状态标签（只读，来源学习模式）。 */
const goalLabels: Record<string, string> = {
  exam: '考试目标',
  domain: '领域掌握',
  explore: '兴趣探索',
}
function studyLabelOf(k: (typeof kbs.kbs)[number]): string {
  if (!k.onboarded) return '学习画像未冷启动'
  return goalLabels[k.goal_type || ''] || '学习画像已就绪'
}
function coverageOf(k: (typeof kbs.kbs)[number]): number {
  return Math.round((k.mastery_coverage || 0) * 100)
}

/** 相对时间：列表概览用于展示最近活动。 */
function relativeTime(iso: string | null): string {
  if (!iso) return '暂无活动'
  const time = new Date(iso).getTime()
  if (Number.isNaN(time)) return '暂无活动'
  const diff = Date.now() - time
  const minute = 60_000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

// ---- 编辑模态（新建 + 修改共用） ----
interface EditForm {
  id: string | null // null = 新建
  name: string
  description: string
  llmConfig: string // 'inherit' | config uuid
  embeddingModel: string
  /** 是否开启学习模式；关闭后该库仅用于记录与检索 */
  learningEnabled: boolean
  /** Wiki 定时编译：0 表示关闭 */
  wikiCompileInterval: number
  /** 待办汇总周期：0 表示关闭 */
  todoSyncInterval: number
}
/** fastembed 常用模型；维度可不同，各库使用独立向量 collection。 */
const EMBEDDING_MODELS = [
  { id: 'BAAI/bge-small-zh-v1.5', label: 'BGE-small-zh-v1.5（中文，推荐）' },
  { id: 'BAAI/bge-base-zh-v1.5', label: 'BGE-base-zh-v1.5（中文，更高精度）' },
  { id: 'BAAI/bge-small-en-v1.5', label: 'BGE-small-en-v1.5（英文）' },
  {
    id: 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
    label: 'Multilingual MiniLM（多语言）',
  },
]
const DEFAULT_EMBED_MODEL = EMBEDDING_MODELS[0].id
/**
 * 系统「向量设置」中配置的默认模型。
 * 本地模式以实际向量空间（active_space）为准；api_model 仅在线上模式有意义。
 */
const systemEmbedModel = computed(() => {
  const config = embeddingConfig.value
  if (!config) return ''
  return (
    (embeddingIsRemote.value ? config.api_model : config.active_space)?.trim() || ''
  )
})
const editing = ref(false)
const saving = ref(false)
const editErr = ref('')
const form = ref<EditForm>({
  id: null,
  name: '',
  description: '',
  llmConfig: 'inherit',
  embeddingModel: DEFAULT_EMBED_MODEL,
  learningEnabled: true,
  wikiCompileInterval: 0,
  todoSyncInterval: 0,
})
/**
 * 下拉选项 = 系统向量设置中的默认模型 + 内置 fastembed 模型。
 * 不再允许自由输入，避免填错模型名导致首次导入时才失败。
 */
const embeddingOptions = computed(() => {
  const list: { id: string; label: string }[] = []
  const seen = new Set<string>()
  const add = (id: string, label: string) => {
    if (!id || seen.has(id)) return
    seen.add(id)
    list.push({ id, label })
  }
  const configured = systemEmbedModel.value
  if (configured) add(configured, `${configured}（系统默认）`)
  for (const model of EMBEDDING_MODELS) add(model.id, model.label)
  // 编辑旧知识库时保留其已有模型，避免下拉框显示为空。
  const current = form.value.embeddingModel.trim()
  if (current) add(current, `${current}（当前配置）`)
  return list
})

// 配置可能在弹窗打开后才返回：未手动改过模型时，跟随系统默认。
watch(systemEmbedModel, (model) => {
  if (!model) return
  if (
    editing.value &&
    !form.value.id &&
    form.value.embeddingModel === DEFAULT_EMBED_MODEL
  ) {
    form.value.embeddingModel = model
  }
})

function openEdit(k: (typeof kbs.kbs)[number] | null) {
  editErr.value = ''
  form.value = k
    ? {
        id: k.id,
        name: k.name,
        description: k?.description ?? '',
        llmConfig: k.llm_config_id ?? 'inherit',
        embeddingModel: k.embedding_model || DEFAULT_EMBED_MODEL,
        learningEnabled: k.learning_enabled !== false,
        wikiCompileInterval: k.wiki_compile_interval_hours ?? 0,
        todoSyncInterval: k.todo_sync_interval_hours ?? 0,
      }
    : {
        id: null,
        name: '',
        description: '',
        llmConfig: 'inherit',
        embeddingModel: systemEmbedModel.value || DEFAULT_EMBED_MODEL,
        learningEnabled: true,
        wikiCompileInterval: 0,
        todoSyncInterval: 0,
      }
  editing.value = true
}

async function saveEdit() {
  editErr.value = ''
  if (!form.value.name.trim()) {
    editErr.value = '请填写知识库名称'
    return
  }
  if (!embeddingIsRemote.value && !form.value.embeddingModel.trim()) {
    editErr.value = '请选择 Embedding 模型'
    return
  }
  saving.value = true
  try {
    if (form.value.id) {
      // PATCH：llmConfig 显式设为 null 即清空绑定（回落全局默认）
      await request(`/kbs/${form.value.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: form.value.name.trim(),
          description: form.value.description.trim(),
          llm_config_id:
            form.value.llmConfig === 'inherit' ? null : form.value.llmConfig,
          // 线上向量模式忽略各库模型；编辑时不回写旧的本地模型。
          ...(embeddingIsRemote.value
            ? {}
            : { embedding_model: form.value.embeddingModel.trim() }),
          learning_enabled: form.value.learningEnabled,
          wiki_compile_interval_hours: form.value.wikiCompileInterval,
          todo_sync_interval_hours: form.value.todoSyncInterval,
        }),
      })
      await kbs.fetchKbs()
      toast.success('知识库已更新')
    } else {
      const kb = await request<{ id: string }>('/kbs', {
        method: 'POST',
        body: JSON.stringify({
          name: form.value.name.trim(),
          description: form.value.description.trim(),
          llm_config_id:
            form.value.llmConfig === 'inherit' ? null : form.value.llmConfig,
          embedding_model:
            form.value.embeddingModel.trim() ||
            systemEmbedModel.value ||
            DEFAULT_EMBED_MODEL,
          learning_enabled: form.value.learningEnabled,
          wiki_compile_interval_hours: form.value.wikiCompileInterval,
          todo_sync_interval_hours: form.value.todoSyncInterval,
        }),
      })
      await kbs.fetchKbs()
      kbs.currentKbId = kb.id
      toast.success('知识库已创建')
    }
    editing.value = false
  } catch (e: any) {
    editErr.value = e.message
  } finally {
    saving.value = false
  }
}

// ---- 删除 ----
const deleting = ref<KbDelete | null>(null)
interface KbDelete {
  id: string
  name: string
  sourceCount: number
  wikiCount: number
  noteCount: number
  /** 内置演示库：硬删除后可按随包内容重新创建 */
  isBuiltin: boolean
}
const removing = ref(false)
const restoring = ref(false)

async function confirmDelete(k: (typeof kbs.kbs)[number]) {
  deleting.value = {
    id: k.id,
    name: k.name,
    sourceCount: k.source_count,
    wikiCount: k.wiki_count,
    noteCount: k.note_count,
    isBuiltin: !!k.is_builtin,
  }
}

async function doDelete() {
  if (!deleting.value) return
  removing.value = true
  try {
    const wasBuiltin = deleting.value.isBuiltin
    await kbs.deleteKb(deleting.value.id)
    toast.success(wasBuiltin ? '已删除内置知识库，可在页面顶部重新创建' : '已删除知识库')
    deleting.value = null
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    removing.value = false
  }
}

/** 重新创建内置演示库（按当前随包内容生成）。 */
async function restoreBuiltin() {
  restoring.value = true
  try {
    await kbs.restoreBuiltin()
    toast.success('内置知识库已重新创建')
  } catch (e: any) {
    toast.error(e.message || '还原失败')
  } finally {
    restoring.value = false
  }
}

// ---- 定时任务 / 手动触发 ----
const compilingKbId = ref<string | null>(null)
const syncingKbId = ref<string | null>(null)

function intervalLabel(hours: number | null | undefined): string {
  const value = Number(hours) || 0
  if (value <= 0) return '未开启'
  if (value % 24 === 0) return `每 ${value / 24} 天`
  return `每 ${value} 小时`
}

function lastCompileLabel(kb: KbOverview): string {
  if (!kb.wiki_compile_last_at) return '尚未运行'
  const status = kb.wiki_compile_last_status || {}
  if (status.status === 'failed') return `${relativeTime(kb.wiki_compile_last_at)} · 失败`
  const scheduled = Number(status.scheduled) || 0
  return `${relativeTime(kb.wiki_compile_last_at)} · 提交 ${scheduled} 篇`
}

async function compileKbNow(kb: KbOverview) {
  compilingKbId.value = kb.id
  try {
    await request('/notes/compile-all', { method: 'POST', kbId: kb.id })
    toast.success('已提交 Wiki 编译任务，稍后自动完成')
    window.setTimeout(() => {
      void kbs.fetchKbs()
    }, 4000)
  } catch (e: any) {
    toast.error(e.message || '提交编译失败')
  } finally {
    compilingKbId.value = null
  }
}

async function syncKbTodos(kb: KbOverview) {
  syncingKbId.value = kb.id
  try {
    const result = await request<{ ok: boolean; open?: number; done?: number; error?: string }>(
      `/kbs/${kb.id}/todos/sync`,
      { method: 'POST' },
    )
    if (!result.ok) throw new Error(result.error || '同步失败')
    toast.success(`待办已同步：${result.open ?? 0} 项待办，${result.done ?? 0} 项已完成`)
    await kbs.fetchKbs()
  } catch (e: any) {
    toast.error(e.message || '同步待办失败')
  } finally {
    syncingKbId.value = null
  }
}

// ---- 全量导入 / 导出 ----
const importInput = ref<HTMLInputElement | null>(null)
const importingKb = ref(false)
const exportingKbId = ref<string | null>(null)

function exportKb(kb: KbOverview) {
  exportingKbId.value = kb.id
  const anchor = document.createElement('a')
  anchor.href = `/api/kbs/${kb.id}/export`
  anchor.download = `${kb.slug || kb.name}.kiwizip`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  toast.success('正在导出知识库，请稍候…')
  window.setTimeout(() => {
    exportingKbId.value = null
  }, 1500)
}

function pickImportKb() {
  importInput.value?.click()
}

async function onImportKbFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!/\.(kiwizip|zip)$/i.test(file.name)) {
    toast.info('请选择 .kiwizip 知识库导出包')
    return
  }
  importingKb.value = true
  const controller = new AbortController()
  const handle = toast.progress(`正在导入 ${file.name}`, 0, () => controller.abort())
  try {
    const data = new FormData()
    data.append('file', file)
    const result = await uploadWithProgress<{
      kb: KbOverview
      stats: Record<string, number>
    }>(
      '/kbs/import',
      data,
      null,
      (loaded, total) => {
        const ratio = total > 0 ? Math.min(1, loaded / total) : 0
        handle.update(
          ratio >= 1 ? `正在处理 ${file.name}…` : `正在导入 ${file.name}`,
          ratio,
        )
      },
      controller.signal,
    )
    await Promise.all([kbs.fetchKbs(), kbs.fetchBuiltinStatus()])
    kbs.currentKbId = result.kb.id
    const stats = Object.entries(result.stats || {})
      .filter(([, value]) => Number(value) > 0)
      .map(([key, value]) => `${key} ${value}`)
      .join(' · ')
    toast.success(stats ? `知识库已导入：${stats}` : '知识库已导入')
  } catch (e: any) {
    if (e?.name === 'AbortError') toast.info(`已取消导入 ${file.name}`)
    else toast.error(e.message || '导入知识库失败')
  } finally {
    handle.dismiss()
    importingKb.value = false
  }
}
</script>

<template>
  <div class="page-wrap px-8 py-8">
    <!-- 页头 -->
    <div class="flex items-end justify-between mb-8">
      <div class="animate-fade-up">
        <div class="flex items-center gap-3">
          <span
            class="w-10 h-10 rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 grid place-items-center text-white shadow-glow"
          >
            <KiwiIcon name="database" :size="20" />
          </span>
          <h1 class="text-2xl font-semibold text-slate-800">知识库</h1>
        </div>
        <p class="text-sm text-slate-500 mt-2">
          每个知识库是独立的知识边界，素材、Wiki、笔记与检索都在库内隔离。
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2 animate-fade-up">
        <!-- 视图模式 -->
        <div class="flex items-center rounded-xl border border-slate-200/70 bg-white/60 p-0.5">
          <button
            v-for="item in VIEW_MODES"
            :key="item.value"
            type="button"
            class="grid h-7 w-7 place-items-center rounded-lg transition-colors"
            :class="
              viewMode === item.value
                ? 'bg-white text-kiwi-600 shadow-sm'
                : 'text-slate-400 hover:text-slate-600'
            "
            :title="item.label"
            @click="setViewMode(item.value)"
          >
            <KiwiIcon :name="item.icon" :size="14" />
          </button>
        </div>
        <button
          class="kiwi-btn-secondary"
          :disabled="importingKb"
          title="导入 .kiwizip 知识库包"
          @click="pickImportKb"
        >
          <KiwiIcon :name="importingKb ? 'loader' : 'fileImport'" :size="15" :spin="importingKb" />
          {{ importingKb ? '导入中…' : '导入' }}
        </button>
        <button class="kiwi-btn-primary" @click="openEdit(null)">
          <KiwiIcon name="plus" :size="16" />
          新建知识库
        </button>
        <input
          ref="importInput"
          type="file"
          accept=".kiwizip,.zip"
          class="hidden"
          @change="onImportKbFile"
        />
      </div>
    </div>

    <!-- 内置演示库不存在（首次初始化失败或已被删除）时的创建入口 -->
    <div
      v-if="kbs.builtinStatus && (!kbs.builtinStatus.exists || kbs.builtinStatus.deleted)"
      class="mb-6 flex flex-col gap-3 rounded-2xl border border-kiwi-200/80 bg-gradient-to-r from-kiwi-50/90 via-white to-emerald-50/60 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="flex items-start gap-3">
        <span class="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-kiwi-100 text-kiwi-600">
          <KiwiIcon name="learn" :size="17" />
        </span>
        <div>
          <p class="text-sm font-medium text-slate-700">
            <template v-if="kbs.builtinStatus.deleted">
              内置知识库「{{ kbs.builtinStatus.name }}」已删除
            </template>
            <template v-else>
              内置知识库「{{ kbs.builtinStatus.name }}」尚未创建
            </template>
          </p>
          <p class="mt-0.5 text-xs leading-relaxed text-slate-500">
            创建后会按当前版本的随包内容生成完整演示数据；此前对演示库的修改不会保留。
          </p>
        </div>
      </div>
      <button
        class="kiwi-btn-primary shrink-0"
        :loading="restoring"
        @click="restoreBuiltin"
      >
        <KiwiIcon name="refresh" :size="14" />
        {{ restoring ? '创建中…' : '创建内置知识库' }}
      </button>
    </div>

    <!-- 加载骨架 -->
    <KiwiSkeleton v-if="kbs.loading" variant="card" :cols="2" />

    <!-- 空态 -->
    <KiwiEmpty
      v-else-if="!kbs.kbs.length"
      icon="database"
      title="还没有知识库"
      desc="创建一个开始你的知识编译之旅"
    >
      <button class="kiwi-btn-primary" @click="openEdit(null)">
        <KiwiIcon name="plus" :size="16" />
        创建第一个知识库
      </button>
    </KiwiEmpty>

    <!-- 卡片网格 -->
    <div v-else :class="gridClass">
      <div
        v-for="(k, i) in sortedKbs"
        :key="k.id"
        class="kiwi-card cursor-pointer group relative overflow-hidden"
        :class="[
          viewMode === 'compact' ? 'p-3.5' : 'p-5',
          k.pinned
            ? 'bg-gradient-to-br from-amber-50/70 via-white/80 to-white'
            : '',
          kbs.currentKbId === k.id
            ? 'border-kiwi-300 ring-2 ring-kiwi-400/50'
            : k.pinned
              ? 'border-amber-200/90'
              : '',
          dragClassOf(k),
        ]"
        :style="{ animationDelay: `${i * 70}ms` }"
        @click="selectKbCard(k.id)"
        @dragover="onKbDragOver($event, k)"
        @drop="onKbDrop($event, k)"
        @dragend="resetKbDrag"
      >
        <!-- 置顶标识：与普通卡片区分 -->
        <div
          v-if="k.pinned"
          class="pointer-events-none absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-amber-300 via-amber-400 to-amber-200"
        />
        <!-- hover 光晕 -->
        <div
          class="pointer-events-none absolute -top-10 -right-10 w-28 h-28 rounded-full bg-kiwi-200/40 blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500"
        />
        <div class="flex items-start gap-3 relative">
          <span
            class="w-12 h-12 shrink-0 grid place-items-center rounded-2xl font-bold text-lg transition-all duration-300"
            :class="
              kbs.currentKbId === k.id
                ? 'bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white shadow-glow'
                : 'bg-white border border-slate-200/80 text-kiwi-600 group-hover:border-kiwi-200'
            "
          >
            {{ k.name.slice(0, 1) }}
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 min-w-0">
              <h3 class="min-w-0 truncate font-semibold text-slate-800">{{ k.name }}</h3>
              <span
                v-if="k.pinned"
                class="inline-flex shrink-0 items-center gap-0.5 text-[10px] px-1.5 py-[1px] rounded-full bg-amber-100 text-amber-700 font-medium"
              >
                <KiwiIcon name="pin" :size="9" />
                置顶
              </span>
              <span
                v-if="kbs.currentKbId === k.id"
                class="inline-flex shrink-0 items-center gap-0.5 text-[10px] px-1.5 py-[1px] rounded-full bg-kiwi-100 text-kiwi-600 font-medium"
              >
                <KiwiIcon name="check" :size="9" />
                当前
              </span>
              <span
                v-if="k.is_builtin"
                class="inline-flex shrink-0 items-center gap-0.5 text-[10px] px-1.5 py-[1px] rounded-full bg-emerald-100 text-emerald-700 font-medium"
                title="系统内置演示库：删除后可按随包内容重新创建"
              >
                <KiwiIcon name="learn" :size="9" />
                内置演示
              </span>
              <span
                v-if="k.learning_enabled === false"
                class="inline-flex shrink-0 items-center gap-0.5 text-[10px] px-1.5 py-[1px] rounded-full bg-slate-100 text-slate-500 font-medium"
                title="仅用于记录与检索，学习模式已关闭"
              >
                仅记录
              </span>
            </div>
            <p class="text-xs text-slate-400 mt-0.5 truncate font-mono">{{ k.slug }}</p>
          </div>
          <div class="flex shrink-0 items-center gap-1 relative">
            <button
              type="button"
              draggable="true"
              class="cursor-grab touch-none p-1 text-slate-300 opacity-0 transition-all hover:bg-slate-100 hover:text-slate-500 active:cursor-grabbing group-hover:opacity-100"
              :class="reordering ? 'pointer-events-none' : ''"
              title="拖动排序（同一置顶分组内）"
              @click.stop
              @dragstart.stop="onKbDragStart($event, k)"
              @dragend="resetKbDrag"
            >
              <KiwiIcon name="grip" :size="15" />
            </button>
            <button
              class="transition-colors p-1 rounded-lg disabled:opacity-40"
              :class="
                k.pinned
                  ? 'text-amber-500 bg-amber-50 hover:bg-amber-100'
                  : 'text-slate-300 hover:text-kiwi-600 hover:bg-kiwi-50'
              "
              :title="k.pinned ? '取消置顶' : '置顶'"
              :disabled="pinningKbId === k.id"
              @click.stop="toggleKbPin(k)"
            >
              <KiwiIcon name="pin" :size="15" />
            </button>
            <button
              class="text-slate-300 hover:text-kiwi-600 transition-colors p-1 hover:bg-kiwi-50 hover:rounded-lg disabled:opacity-40"
              title="导出为 .kiwizip（含笔记、素材与 Wiki）"
              :disabled="exportingKbId === k.id"
              @click.stop="exportKb(k)"
            >
              <KiwiIcon
                name="fileExport"
                :size="15"
                :class="exportingKbId === k.id ? 'animate-pulse' : ''"
              />
            </button>
            <button
              class="text-slate-300 hover:text-kiwi-600 transition-colors p-1 hover:bg-kiwi-50 hover:rounded-lg"
              title="编辑"
              @click.stop="openEdit(k)"
            >
              <KiwiIcon name="edit" :size="15" />
            </button>
            <button
              class="text-slate-300 hover:text-red-400 transition-colors p-1 hover:bg-red-50 hover:rounded-lg"
              :title="k.is_builtin ? '删除（可重新创建）' : '删除'"
              @click.stop="confirmDelete(k)"
            >
              <KiwiIcon name="trash" :size="16" />
            </button>
          </div>
        </div>

        <p
          v-if="k.description"
          class="relative text-slate-500"
          :class="viewMode === 'compact' ? 'mt-2 line-clamp-1 text-xs' : 'mt-3 line-clamp-2 text-sm'"
        >
          {{ k.description }}
        </p>

        <!-- 置顶笔记 / 分组：与工作区目录树保持同一份置顶数据 -->
        <div
          v-if="pinnedOf(k.id).length && viewMode !== 'compact'"
          class="mt-3 relative"
        >
          <div class="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-amber-600">
            <KiwiIcon name="pin" :size="12" />
            置顶
            <span class="font-normal text-slate-300">{{ pinnedOf(k.id).length }}</span>
          </div>
          <div class="space-y-0.5">
            <button
              v-for="item in pinnedOf(k.id).slice(0, 4)"
              :key="`${item.type}-${item.id}`"
              type="button"
              class="flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-left text-xs text-slate-600 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
              :title="item.folderName ? `${item.folderName} / ${item.title}` : item.title"
              @click.stop="openPinned(k.id, item)"
            >
              <KiwiIcon
                :name="item.type === 'folder' ? 'folder' : kindIcon(item.kind)"
                :size="12"
                class="shrink-0"
                :class="item.type === 'folder' ? 'text-amber-400' : kindColor(item.kind)"
              />
              <span class="truncate">{{ item.title }}</span>
              <span
                v-if="item.type === 'folder'"
                class="ml-auto shrink-0 text-[10px] text-slate-300"
              >分组</span>
              <span
                v-else-if="item.folderName"
                class="ml-auto max-w-[38%] shrink-0 truncate text-[10px] text-slate-300"
              >{{ item.folderName }}</span>
            </button>
          </div>
          <p
            v-if="pinnedOf(k.id).length > 4"
            class="mt-1 pl-2 text-[10px] text-slate-400"
          >
            还有 {{ pinnedOf(k.id).length - 4 }} 个置顶项
          </p>
        </div>

        <!-- 计数 -->
        <div class="grid grid-cols-3 gap-2 mt-4 relative">
          <div class="flex items-center gap-1.5 text-sm text-slate-500">
            <span class="text-slate-300"><KiwiIcon name="file" :size="14" /></span>
            <span class="tabular-nums font-medium text-slate-700">{{ k.source_count }}</span>
            <span class="text-xs text-slate-400">素材</span>
          </div>
          <div class="flex items-center gap-1.5 text-sm text-slate-500">
            <span class="text-slate-300"><KiwiIcon name="wiki" :size="14" /></span>
            <span class="tabular-nums font-medium text-slate-700">{{ k.wiki_count }}</span>
            <span class="text-xs text-slate-400">Wiki</span>
          </div>
          <div class="flex items-center gap-1.5 text-sm text-slate-500">
            <span class="text-slate-300"><KiwiIcon name="note" :size="14" /></span>
            <span class="tabular-nums font-medium text-slate-700">{{ k.note_count }}</span>
            <span class="text-xs text-slate-400">笔记</span>
          </div>
        </div>

        <!-- 自动化：Wiki 定时编译 / 待办定时汇总，可手动触发 -->
        <div
          class="relative mt-3 space-y-1 rounded-xl border border-slate-100 bg-white/55 px-3 py-2"
        >
          <div class="flex items-center gap-1.5 text-[11px]">
            <KiwiIcon name="wiki" :size="12" class="shrink-0 text-kiwi-500" />
            <span class="shrink-0 text-slate-500">Wiki 编译</span>
            <span
              class="shrink-0 rounded-full bg-slate-100 px-1.5 py-[1px] text-[10px] text-slate-500"
            >
              {{ intervalLabel(k.wiki_compile_interval_hours) }}
            </span>
            <span
              class="min-w-0 flex-1 truncate text-right text-[10px] text-slate-400"
              :title="lastCompileLabel(k)"
            >
              {{ lastCompileLabel(k) }}
            </span>
            <button
              type="button"
              class="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-kiwi-600 transition-colors hover:bg-kiwi-50 disabled:opacity-40"
              :disabled="compilingKbId === k.id"
              @click.stop="compileKbNow(k)"
            >
              {{ compilingKbId === k.id ? '提交中…' : '立即编译' }}
            </button>
          </div>
          <div class="flex items-center gap-1.5 text-[11px]">
            <KiwiIcon name="checkSquare" :size="12" class="shrink-0 text-emerald-500" />
            <span class="shrink-0 text-slate-500">待办汇总</span>
            <span
              class="shrink-0 rounded-full bg-slate-100 px-1.5 py-[1px] text-[10px] text-slate-500"
            >
              {{ intervalLabel(k.todo_sync_interval_hours) }}
            </span>
            <span class="min-w-0 flex-1 truncate text-right text-[10px] text-slate-400">
              {{ k.todo_open_count }} 待办 · {{ k.todo_done_count }} 完成
            </span>
            <button
              type="button"
              class="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 transition-colors hover:bg-emerald-50 disabled:opacity-40"
              :disabled="syncingKbId === k.id"
              @click.stop="syncKbTodos(k)"
            >
              {{ syncingKbId === k.id ? '同步中…' : '立即同步' }}
            </button>
          </div>
        </div>

        <!-- 学习画像状态（只读）；关闭学习模式时展示记录库说明 -->
        <div
          v-if="viewMode !== 'compact' && k.learning_enabled === false"
          class="mt-3 rounded-xl border border-slate-100 bg-slate-50/60 px-3 py-2.5 relative"
        >
          <div class="flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
            <KiwiIcon name="note" :size="12" />
            仅记录知识库
          </div>
          <p class="mt-1 text-[10.5px] leading-relaxed text-slate-400">
            学习模式已关闭，不会生成学习画像、练习与测评；仍可正常记录笔记、导入素材与编译 Wiki。
          </p>
        </div>
        <div
          v-else-if="viewMode !== 'compact'"
          class="mt-3 rounded-xl border border-slate-100 bg-slate-50/70 px-3 py-2 relative"
        >
          <div class="flex items-center justify-between gap-2 text-[11px]">
            <span
              class="flex min-w-0 items-center gap-1.5 truncate"
              :class="k.onboarded ? 'text-kiwi-700' : 'text-slate-400'"
            >
              <KiwiIcon name="learn" :size="12" />
              {{ studyLabelOf(k) }}
            </span>
            <span class="shrink-0 tabular-nums text-slate-400">掌握度覆盖 {{ coverageOf(k) }}%</span>
          </div>
          <div class="mt-1.5 h-1 overflow-hidden rounded-full bg-slate-200/70">
            <div
              class="h-full rounded-full bg-gradient-to-r from-kiwi-400 to-kiwi-600 transition-all duration-500"
              :style="{ width: `${coverageOf(k)}%` }"
            />
          </div>
          <div class="mt-1 flex items-center gap-1.5 text-[10px] text-slate-400">
            <span>{{ k.mastered_topics }}/{{ k.wiki_count }} 个知识点已掌握</span>
            <span v-if="k.due_reviews" class="text-amber-600">· {{ k.due_reviews }} 个待复习</span>
          </div>
        </div>

        <p
          v-if="viewMode !== 'compact'"
          class="mt-2 text-xs truncate relative flex items-center gap-1.5"
          :class="modelColorOf(k.llm_config_id)"
        >
          <KiwiIcon name="settings" :size="12" />
          默认模型：{{ modelLabelOf(k.llm_config_id) }}
        </p>
        <p class="mt-1 text-[10.5px] text-slate-400 flex items-center gap-1 relative">
          <KiwiIcon name="refresh" :size="10" />
          最近活动：{{ relativeTime(k.last_activity_at) }}
        </p>
      </div>
    </div>

    <!-- 编辑 / 新建模态 -->
    <KiwiModal :open="editing" :title="form.id ? '编辑知识库' : '新建知识库'" @close="editing = false">
      <div class="space-y-4">
        <div>
          <label class="text-xs font-medium text-slate-500">名称</label>
          <input
            v-model="form.name"
            class="kiwi-input mt-1"
            placeholder="如：软考高项"
            autofocus
            @keyup.enter="saveEdit"
          />
        </div>
        <div>
          <label class="text-xs font-medium text-slate-500">描述（可选）</label>
          <textarea
            v-model="form.description"
            rows="3"
            class="kiwi-input mt-1 resize-none"
            placeholder="这个库的边界、用途…"
          />
        </div>
        <div>
          <label class="text-xs font-medium text-slate-500">默认模型</label>
          <select v-model="form.llmConfig" class="kiwi-input mt-1 appearance-none cursor-pointer">
            <option value="inherit">继承全局默认</option>
            <option v-for="c in llm.configs" :key="c.id" :value="c.id">
              {{ c.model_name ? `${c.name} · ${c.model_name}` : c.name }}
            </option>
          </select>
          <p class="text-[11px] text-slate-400 mt-1">
            {{ form.llmConfig === 'inherit'
              ? '未绑定，问答使用「设置」里的全局默认模型'
              : '该库的问答请求将固定使用此模型' }}
          </p>
        </div>
        <div>
          <div class="flex items-center justify-between gap-2">
            <label class="text-xs font-medium text-slate-500">Embedding 模型</label>
            <RouterLink
              to="/settings/models?tab=embedding"
              class="text-[11px] font-medium text-kiwi-600 hover:text-kiwi-700"
            >
              向量设置
            </RouterLink>
          </div>

          <!-- 线上向量服务：由系统设置统一提供，逐库模型选择不生效 -->
          <div
            v-if="embeddingIsRemote"
            class="mt-1 rounded-xl border border-amber-200/80 bg-amber-50/50 px-3 py-2.5"
          >
            <div class="flex items-center gap-1.5 text-xs font-medium text-amber-700">
              <KiwiIcon name="cloud" :size="13" />
              使用系统线上向量服务
            </div>
            <dl class="mt-1.5 space-y-0.5 text-[11px] text-slate-500">
              <div class="flex gap-1.5">
                <dt class="shrink-0 text-slate-400">模型</dt>
                <dd class="min-w-0 truncate font-mono text-slate-600">
                  {{ embeddingConfig?.api_model || '未配置' }}
                </dd>
              </div>
              <div class="flex gap-1.5">
                <dt class="shrink-0 text-slate-400">服务地址</dt>
                <dd class="min-w-0 truncate font-mono text-slate-600">
                  {{ embeddingConfig?.api_base || '—' }}
                </dd>
              </div>
              <div class="flex gap-1.5">
                <dt class="shrink-0 text-slate-400">向量空间</dt>
                <dd class="min-w-0 truncate font-mono text-slate-600">
                  {{ embeddingConfig?.active_space || '—' }}
                </dd>
              </div>
            </dl>
            <p class="mt-1.5 text-[10.5px] leading-relaxed text-amber-600/90">
              线上模式由全部知识库共用；切换服务地址或模型会影响所有库的检索，请在向量设置中统一调整。
            </p>
          </div>

          <!-- 本地 fastembed：每个知识库独立选择与编码 -->
          <template v-else>
            <div class="relative mt-1">
              <select
                v-model="form.embeddingModel"
                class="kiwi-input cursor-pointer appearance-none pr-9 font-mono text-[13px]"
              >
                <option v-for="m in embeddingOptions" :key="m.id" :value="m.id">
                  {{ m.label }}
                </option>
              </select>
              <KiwiIcon
                name="chevron"
                :size="14"
                class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400"
              />
            </div>
            <p class="mt-1 text-[11px] text-slate-400">
              {{ embeddingHint }}
            </p>
          </template>
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <label class="text-xs font-medium text-slate-500">Wiki 定时编译</label>
            <div class="relative mt-1">
              <input
                v-model.number="form.wikiCompileInterval"
                type="number"
                min="0"
                step="1"
                class="kiwi-input pr-12"
              />
              <span
                class="pointer-events-none absolute right-3 top-1/2 z-10 -translate-y-1/2 text-[11px] text-slate-400"
              >小时</span>
            </div>
            <p class="mt-1 text-[11px] leading-relaxed text-slate-400">
              0 表示关闭；有变更的笔记会自动编译进 Wiki。
            </p>
          </div>
          <div>
            <label class="text-xs font-medium text-slate-500">待办定时汇总</label>
            <div class="relative mt-1">
              <input
                v-model.number="form.todoSyncInterval"
                type="number"
                min="0"
                step="1"
                class="kiwi-input pr-12"
              />
              <span
                class="pointer-events-none absolute right-3 top-1/2 z-10 -translate-y-1/2 text-[11px] text-slate-400"
              >小时</span>
            </div>
            <p class="mt-1 text-[11px] leading-relaxed text-slate-400">
              0 表示关闭；按周期把各笔记待办汇总到收件箱。
            </p>
          </div>
        </div>
        <button
          type="button"
          class="flex w-full items-start gap-3 rounded-xl border px-3.5 py-3 text-left transition-colors"
          :class="
            form.learningEnabled
              ? 'border-kiwi-200 bg-kiwi-50/50'
              : 'border-slate-200 bg-slate-50/60'
          "
          role="switch"
          :aria-checked="form.learningEnabled"
          @click="form.learningEnabled = !form.learningEnabled"
        >
          <span
            class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl transition-colors"
            :class="
              form.learningEnabled
                ? 'bg-kiwi-100 text-kiwi-600'
                : 'bg-slate-200/70 text-slate-400'
            "
          >
            <KiwiIcon name="learn" :size="16" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="flex items-center gap-2 text-sm font-medium text-slate-700">
              开启学习模式
              <span
                class="inline-flex shrink-0 items-center rounded-full px-1.5 py-[1px] text-[10px] font-medium"
                :class="
                  form.learningEnabled
                    ? 'bg-kiwi-100 text-kiwi-600'
                    : 'bg-slate-200/80 text-slate-500'
                "
              >
                {{ form.learningEnabled ? '已开启' : '仅记录' }}
              </span>
            </span>
            <span class="mt-0.5 block text-[11px] leading-relaxed text-slate-400">
              {{
                form.learningEnabled
                  ? '可切换至学习模式：学习画像、练习、测评、复习计划与 Wiki 掌握度。'
                  : '仅用于记录、导入与检索：不显示学习入口，也不会生成练习与测评。'
              }}
            </span>
          </span>
          <span
            class="mt-1 relative h-5 w-9 shrink-0 rounded-full transition-colors"
            :class="form.learningEnabled ? 'bg-kiwi-500' : 'bg-slate-300'"
          >
            <span
              class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all duration-200"
              :class="form.learningEnabled ? 'left-[18px]' : 'left-0.5'"
            />
          </span>
        </button>
        <p v-if="editErr" class="text-red-500 text-sm flex items-center gap-1.5">
          <KiwiIcon name="alert" :size="14" />
          {{ editErr }}
        </p>
        <div class="flex gap-2 justify-end pt-1">
          <button class="kiwi-btn-ghost" @click="editing = false">取消</button>
          <button class="kiwi-btn-primary" :loading="saving" @click="saveEdit">
            {{ saving ? '保存中…' : form.id ? '保存' : '创建' }}
          </button>
        </div>
      </div>
    </KiwiModal>

    <!-- 删除确认模态：内置库与普通库均为不可撤销的硬删除 -->
    <KiwiModal
      :open="!!deleting"
      :title="deleting?.isBuiltin ? '删除内置知识库' : '删除知识库'"
      @close="deleting = null"
    >
      <div v-if="deleting" class="space-y-4">
        <template v-if="deleting.isBuiltin">
          <p class="text-sm leading-relaxed text-slate-600">
            确定删除 <b class="text-slate-800">{{ deleting.name }}</b> 吗？将同时删除：
          </p>
          <ul class="text-sm text-slate-500 space-y-1.5 bg-rose-50/60 border border-rose-100 rounded-xl p-4">
            <li class="flex items-center gap-2">
              <KiwiIcon name="file" :size="14" class="text-rose-400" />
              {{ deleting.sourceCount }} 个素材与分块
            </li>
            <li class="flex items-center gap-2">
              <KiwiIcon name="wiki" :size="14" class="text-rose-400" />
              {{ deleting.wikiCount }} 个 Wiki 页面
            </li>
            <li class="flex items-center gap-2">
              <KiwiIcon name="note" :size="14" class="text-rose-400" />
              {{ deleting.noteCount }} 篇笔记（含向量索引）
            </li>
          </ul>
          <div class="rounded-xl border border-kiwi-100 bg-kiwi-50/60 p-4 text-sm leading-relaxed text-slate-600">
            <p class="flex items-center gap-2 font-medium text-kiwi-700">
              <KiwiIcon name="learn" :size="14" />
              删除后可按当前随包内容重新创建
            </p>
            <p class="mt-1.5 text-xs text-slate-500">
              重建的演示数据不包含你对当前演示库所做的修改。
            </p>
          </div>
          <div class="flex justify-end gap-2 pt-1">
            <button class="kiwi-btn-ghost" @click="deleting = null">取消</button>
            <button class="kiwi-btn-danger" :loading="removing" @click="doDelete">
              {{ removing ? '删除中…' : '确认删除' }}
            </button>
          </div>
        </template>
        <template v-else>
          <p class="text-sm text-slate-600 leading-relaxed">
            确定删除 <b class="text-slate-800">{{ deleting.name }}</b> 吗？
            将同时删除：
          </p>
          <ul class="text-sm text-slate-500 space-y-1.5 bg-rose-50/60 border border-rose-100 rounded-xl p-4">
            <li class="flex items-center gap-2">
              <KiwiIcon name="file" :size="14" class="text-rose-400" />
              {{ deleting.sourceCount }} 个素材与分块
            </li>
            <li class="flex items-center gap-2">
              <KiwiIcon name="wiki" :size="14" class="text-rose-400" />
              {{ deleting.wikiCount }} 个 Wiki 页面
            </li>
            <li class="flex items-center gap-2">
              <KiwiIcon name="note" :size="14" class="text-rose-400" />
              {{ deleting.noteCount }} 篇笔记（含向量索引）
            </li>
          </ul>
          <p class="text-xs text-slate-400">此操作不可撤销。</p>
          <div class="flex gap-2 justify-end pt-1">
            <button class="kiwi-btn-ghost" @click="deleting = null">取消</button>
            <button class="kiwi-btn-danger" :loading="removing" @click="doDelete">
              {{ removing ? '删除中…' : '确认删除' }}
            </button>
          </div>
        </template>
      </div>
    </KiwiModal>
  </div>
</template>

<style scoped>
/* 卡片拖拽落点：在目标卡片内侧显示方向指示条 */
.kiwi-card.kb-drop-before::before,
.kiwi-card.kb-drop-after::before {
  content: '';
  position: absolute;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 9999px;
  background: rgb(var(--kiwi-500));
  box-shadow: 0 0 0 2px rgb(var(--kiwi-100));
  z-index: 2;
  pointer-events: none;
}
.kiwi-card.kb-drop-before::before {
  left: 3px;
}
.kiwi-card.kb-drop-after::before {
  right: 3px;
}
</style>