<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useLlmStore } from '@/stores/llm'
import { request } from '@/api/client'
import type { NoteFolder, NoteKind, NoteSummary } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiSkeleton from '@/components/ui/KiwiSkeleton.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import { toast } from '@/components/ui/toast'

const kbs = useKbsStore()
const llm = useLlmStore()
const router = useRouter()

/** 系统级向量模型：线上模式下各库的本地模型选择会被忽略 */
const embeddingProvider = ref<'local' | 'openai'>('local')

onMounted(() => {
  // 拉 LLM 配置，用于映射「默认模型」绑定显示
  llm.fetchConfigs().catch(() => { /* 配置拉取失败不阻塞知识库管理 */ })
  // 内置演示库状态：决定是否展示「还原」入口
  void kbs.fetchBuiltinStatus()
  request<{ provider: string }>('/settings/embedding')
    .then((c) => {
      embeddingProvider.value = c.provider === 'openai' ? 'openai' : 'local'
    })
    .catch(() => { /* 旧后端或读取失败时按本地模式展示 */ })
})

// 置顶的知识库排在前面；同等状态按创建时间倒序。
const sortedKbs = computed(() =>
  [...kbs.kbs].sort(
    (a, b) =>
      Number(!!b.pinned) - Number(!!a.pinned) ||
      (b.created_at || '').localeCompare(a.created_at || ''),
  ),
)
const pinningKbId = ref<string | null>(null)

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
})
const embeddingOptions = computed(() => {
  const list = [...EMBEDDING_MODELS]
  const current = form.value.embeddingModel
  if (current && !list.some((m) => m.id === current)) {
    list.push({ id: current, label: `${current}（当前配置）` })
  }
  return list
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
      }
    : {
        id: null,
        name: '',
        description: '',
        llmConfig: 'inherit',
        embeddingModel: DEFAULT_EMBED_MODEL,
        learningEnabled: true,
      }
  editing.value = true
}

async function saveEdit() {
  editErr.value = ''
  if (!form.value.name.trim()) {
    editErr.value = '请填写知识库名称'
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
          embedding_model: form.value.embeddingModel,
          learning_enabled: form.value.learningEnabled,
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
          embedding_model: form.value.embeddingModel,
          learning_enabled: form.value.learningEnabled,
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
      <button class="kiwi-btn-primary animate-fade-up" @click="openEdit(null)">
        <KiwiIcon name="plus" :size="16" />
        新建知识库
      </button>
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
    <div v-else class="grid md:grid-cols-2 2xl:grid-cols-3 gap-4">
      <div
        v-for="(k, i) in sortedKbs"
        :key="k.id"
        class="kiwi-card p-5 cursor-pointer group relative overflow-hidden"
        :style="{ animationDelay: `${i * 70}ms` }"
        :class="[
          k.pinned
            ? 'bg-gradient-to-br from-amber-50/70 via-white/80 to-white'
            : '',
          kbs.currentKbId === k.id
            ? 'border-kiwi-300 ring-2 ring-kiwi-400/50'
            : k.pinned
              ? 'border-amber-200/90'
              : '',
        ]"
        @click="kbs.currentKbId = k.id"
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

        <p v-if="k.description" class="text-sm text-slate-500 mt-3 line-clamp-2 relative">
          {{ k.description }}
        </p>

        <!-- 置顶笔记 / 分组：与工作区目录树保持同一份置顶数据 -->
        <div v-if="pinnedOf(k.id).length" class="mt-3 relative">
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

        <!-- 学习画像状态（只读）；关闭学习模式时展示记录库说明 -->
        <div
          v-if="k.learning_enabled === false"
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
          v-else
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
          <label class="text-xs font-medium text-slate-500">Embedding 模型</label>
          <select
            v-model="form.embeddingModel"
            class="kiwi-input mt-1 appearance-none cursor-pointer"
          >
            <option v-for="m in embeddingOptions" :key="m.id" :value="m.id">
              {{ m.label }}
            </option>
          </select>
          <p v-if="embeddingProvider === 'openai'" class="text-[11px] text-amber-600 mt-1">
            系统已启用线上向量模型，此处选择暂不生效。
            <RouterLink to="/settings/embedding" class="underline hover:text-amber-700">
              前往设置
            </RouterLink>
          </p>
          <p v-else class="text-[11px] text-slate-400 mt-1">
            每个知识库独立编码与检索；更换模型后需重新导入素材以重建向量。
          </p>
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