<script setup lang="ts">
/** Wiki 页面详情：Markdown 阅读 / 人工编辑 / 反向链接 / 素材溯源 / 学习批注。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import { useModeStore } from '@/stores/mode'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiProgress from '@/components/ui/KiwiProgress.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import KiwiSkeleton from '@/components/ui/KiwiSkeleton.vue'
import WikiMarkdown from '@/components/wiki/WikiMarkdown.vue'
import WikiPageTree from '@/components/wiki/WikiPageTree.vue'
import {
  extractHeadings,
  stripLeadingTitleHeading,
  type HeadingItem,
  type WikiLinkTarget,
} from '@/lib/wikiMarkdown'
import { toast } from '@/components/ui/toast'

interface WikiSource {
  id: string
  title: string
  type: string
  status: string
  parse_quality: string
  sha256: string
  import_batch_id: string | null
  parsed_at: string | null
  /** 由该素材导入生成的笔记；用于从来源反向跳转到原始笔记。 */
  note_id: string | null
}

interface RelatedNote {
  id: string
  title: string
  kind: string
  status: string
}

interface WikiPageDetail {
  id: string
  kb_id: string
  slug: string
  page_type: string
  title: string
  body_md: string
  frontmatter_json: Record<string, unknown>
  compiled_from_source_ids: string[]
  version: number
  human_edited: boolean
  created_at: string
  updated_at: string
  tags: string[]
  mastery: number | null
  backlink_count: number
  annotation_count: number
  sources: WikiSource[]
  related_notes: RelatedNote[]
}

interface WikiSummary {
  id: string
  slug: string
  title: string
  page_type: string
  summary: string
  tags: string[]
  mastery: number | null
  annotation_count: number
  link_count: number
  source_count: number
  version: number
  human_edited: boolean
  updated_at: string
}

interface Annotation {
  id: string
  target_type: string
  target_id: string
  content_md: string
  quote: string
  created_at: string
  updated_at: string
}

const route = useRoute()
const router = useRouter()
const kbs = useKbsStore()
const mode = useModeStore()

/** 学习模式下 Wiki 详情属于学习知识库；设置页等共享页也沿用当前模式的知识库。 */
const kbId = computed(() =>
  mode.mode === 'learn' ? kbs.activeLearnKbId : kbs.currentKbId,
)

const page = ref<WikiPageDetail | null>(null)
const pages = ref<WikiSummary[]>([])
const backlinks = ref<WikiSummary[]>([])
const outlinks = ref<WikiSummary[]>([])
const annotations = ref<Annotation[]>([])
const loading = ref(false)
const error = ref('')
const annotationsLoading = ref(false)
const indexLoading = ref(false)
const treeOpen = ref(false)

const readOnly = computed(() => mode.mode === 'learn')
// 学习批注属于学习数据：学习模式可写，编辑模式只读（README 14.1 边界）
const canAnnotate = computed(() => mode.mode === 'learn')

function startLearningHere() {
  if (!page.value) return
  mode.setMode('learn')
  router.push({
    name: 'learn',
    query: { topic_slug: page.value.slug, kb: page.value.kb_id },
  })
}
const pageId = computed(() =>
  typeof route.params.id === 'string' ? route.params.id : '',
)

const TYPE_LABEL: Record<string, string> = {
  entity: '实体',
  concept: '概念',
  summary: '摘要',
  synthesis: '综合',
}

const linkIndex = computed<WikiLinkTarget[]>(() =>
  pages.value.map((p) => ({ id: p.id, slug: p.slug, title: p.title })),
)

const displayBody = computed(() =>
  stripLeadingTitleHeading(page.value?.body_md || '', page.value?.title || ''),
)

const headings = computed<HeadingItem[]>(() => extractHeadings(displayBody.value))
const toc = computed(() => headings.value.filter((h) => h.level <= 3))

// 增量重导入后，引用该素材的人工编辑页会带源漂移标记
const sourceDrift = computed(() => {
  const raw = page.value?.frontmatter_json?.source_drift
  return raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null
})

// ---------- 编辑状态 ----------
const editing = ref(false)
const saving = ref(false)
const draftTitle = ref('')
const draftBody = ref('')
const draftTags = ref('')
const draftType = ref('concept')
const deleteOpen = ref(false)

function startEdit() {
  if (!page.value) return
  draftTitle.value = page.value.title
  draftBody.value = page.value.body_md
  draftTags.value = page.value.tags.join(', ')
  draftType.value = page.value.page_type
  editing.value = true
}

function cancelEdit() {
  editing.value = false
}

async function save() {
  if (!page.value || !kbId.value) return
  saving.value = true
  try {
    const updated = await request<WikiPageDetail>(`/wiki/${page.value.id}`, {
      method: 'PATCH',
      kbId: kbId.value,
      body: JSON.stringify({
        title: draftTitle.value.trim() || page.value.title,
        body_md: draftBody.value,
        page_type: draftType.value,
        tags: draftTags.value
          .split(/[,，]/)
          .map((t) => t.trim())
          .filter(Boolean),
      }),
    })
    const sources = page.value.sources
    const related = page.value.related_notes
    page.value = { ...updated, sources, related_notes: related }
    editing.value = false
    toast.success('已保存，人工编辑内容不会被后续编译覆盖')
    await loadIndexes()
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function removePage() {
  if (!page.value || !kbId.value) return
  try {
    await request<void>(`/wiki/${page.value.id}`, {
      method: 'DELETE',
      kbId: kbId.value,
    })
    toast.success('Wiki 页面已删除')
    void router.replace({ name: 'wiki' })
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

// ---------- 数据加载 ----------
let seq = 0

async function loadIndexes() {
  if (!kbId.value || !pageId.value) return
  indexLoading.value = true
  try {
    const [list, back, out] = await Promise.all([
      request<WikiSummary[]>('/wiki', { kbId: kbId.value }),
      request<WikiSummary[]>(`/wiki/${pageId.value}/backlinks`, { kbId: kbId.value }),
      request<WikiSummary[]>(`/wiki/${pageId.value}/outlinks`, { kbId: kbId.value }),
    ])
    pages.value = list
    backlinks.value = back
    outlinks.value = out
  } catch {
    /* 索引是辅助信息，失败不阻塞正文 */
  } finally {
    indexLoading.value = false
  }
}

async function loadAnnotations() {
  if (!kbId.value || !pageId.value) return
  annotationsLoading.value = true
  try {
    annotations.value = await request<Annotation[]>(
      `/study/annotations?target_type=wiki&target_id=${encodeURIComponent(pageId.value)}`,
      { kbId: kbId.value },
    )
  } catch (e: any) {
    annotations.value = []
    toast.error(e.message || '批注加载失败')
  } finally {
    annotationsLoading.value = false
  }
}

async function load() {
  seq += 1
  const mySeq = seq
  const id = pageId.value
  if (!id || !kbId.value) {
    if (!id) void router.replace({ name: 'wiki' })
    return
  }
  loading.value = true
  error.value = ''
  editing.value = false
  page.value = null
  try {
    const detail = await request<WikiPageDetail>(`/wiki/${id}`, {
      kbId: kbId.value,
    })
    if (mySeq !== seq) return
    page.value = detail
    void loadIndexes()
    void loadAnnotations()
  } catch (e: any) {
    if (mySeq !== seq) return
    error.value = e.message || '页面加载失败'
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

onMounted(load)
watch([pageId, () => kbId.value], load)

// ---------- 批注 ----------
const annotationText = ref('')
const annotationQuote = ref('')
const annotationSaving = ref(false)
const editingAnnotationId = ref<string | null>(null)
const editAnnotationText = ref('')
type PanelTab = 'toc' | 'links' | 'annotations' | 'sources'
const activeTab = ref<PanelTab>('toc')
const PANEL_TABS: { key: PanelTab; label: string }[] = [
  { key: 'toc', label: '大纲' },
  { key: 'links', label: '链接' },
  { key: 'annotations', label: '批注' },
  { key: 'sources', label: '来源' },
]

function captureSelection() {
  const selected = window.getSelection()?.toString().trim() ?? ''
  if (selected) annotationQuote.value = selected.slice(0, 500)
  else toast.error('请先在正文中选中要引用的文字')
}

async function addAnnotation() {
  if (!kbId.value || !page.value) return
  const content = annotationText.value.trim()
  if (!content) return
  annotationSaving.value = true
  try {
    const row = await request<Annotation>('/study/annotations', {
      method: 'POST',
      kbId: kbId.value,
      body: JSON.stringify({
        target_type: 'wiki',
        target_id: page.value.id,
        content_md: content,
        quote: annotationQuote.value.trim(),
      }),
    })
    annotations.value.unshift(row)
    annotationText.value = ''
    annotationQuote.value = ''
    if (page.value) page.value.annotation_count += 1
    toast.success('批注已添加')
  } catch (e: any) {
    toast.error(e.message || '批注添加失败')
  } finally {
    annotationSaving.value = false
  }
}

function startEditAnnotation(row: Annotation) {
  editingAnnotationId.value = row.id
  editAnnotationText.value = row.content_md
}

async function saveAnnotation(row: Annotation) {
  if (!kbId.value) return
  const content = editAnnotationText.value.trim()
  if (!content) return
  try {
    const updated = await request<Annotation>(`/study/annotations/${row.id}`, {
      method: 'PATCH',
      kbId: kbId.value,
      body: JSON.stringify({ content_md: content }),
    })
    const idx = annotations.value.findIndex((a) => a.id === row.id)
    if (idx >= 0) annotations.value[idx] = updated
    editingAnnotationId.value = null
  } catch (e: any) {
    toast.error(e.message || '批注更新失败')
  }
}

async function removeAnnotation(row: Annotation) {
  if (!kbId.value) return
  try {
    await request<void>(`/study/annotations/${row.id}`, {
      method: 'DELETE',
      kbId: kbId.value,
    })
    annotations.value = annotations.value.filter((a) => a.id !== row.id)
    if (page.value) page.value.annotation_count = Math.max(0, page.value.annotation_count - 1)
  } catch (e: any) {
    toast.error(e.message || '批注删除失败')
  }
}

// ---------- 导航与展示 ----------
function openPage(id: string) {
  treeOpen.value = false
  if (id === pageId.value) return
  void router.push({ name: 'wiki-page', params: { id } })
}

function openNote(id: string) {
  void router.push({ name: 'notes', params: { id } })
}

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function fmtDate(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const masteryPct = computed(() =>
  page.value?.mastery == null ? null : Math.round(page.value.mastery * 100),
)

const tabCounts = computed(() => ({
  toc: toc.value.length,
  links: backlinks.value.length + outlinks.value.length,
  annotations: annotations.value.length,
  sources: (page.value?.sources.length ?? 0) + (page.value?.related_notes.length ?? 0),
}))
</script>

<template>
  <div class="page-wrap px-6 py-6 max-w-[1500px] mx-auto">
    <!-- 页头 -->
    <div class="flex items-center gap-2 mb-5 animate-fade-up">
      <button
        class="kiwi-btn-ghost !px-2"
        :title="readOnly ? '返回学习' : '返回 Wiki'"
        @click="router.push({ name: readOnly ? 'learn' : 'wiki' })"
      >
        <KiwiIcon name="arrowLeft" :size="16" />
      </button>
      <button
        class="kiwi-btn-ghost !px-2 xl:hidden"
        title="页面目录"
        @click="treeOpen = true"
      >
        <KiwiIcon name="listTree" :size="16" />
      </button>
      <span class="text-xs text-slate-400">Wiki</span>
      <KiwiIcon name="chevronRight" :size="12" class="text-slate-300" />
      <span class="text-xs text-slate-500 truncate max-w-[24rem]">
        {{ page?.title || '页面' }}
      </span>
      <span
        v-if="readOnly"
        class="ml-auto text-[11px] px-2 py-1 rounded-full bg-sky-50 text-sky-600 flex items-center gap-1"
      >
        <KiwiIcon name="bookOpen" :size="11" />
        学习模式只读
      </span>
    </div>

    <!-- 加载 -->
    <div v-if="loading" class="grid lg:grid-cols-[minmax(0,1fr)_18rem] gap-6">
      <KiwiSkeleton variant="card" :cols="1" class="!h-96" />
      <KiwiSkeleton variant="card" :cols="1" class="!h-72" />
    </div>

    <!-- 错误 -->
    <div v-else-if="error" class="kiwi-card p-10 text-center">
      <KiwiIcon name="alert" :size="28" class="text-rose-400 mx-auto" />
      <p class="text-sm text-slate-600 mt-3">{{ error }}</p>
      <button class="kiwi-btn-secondary mt-4" @click="router.push({ name: 'wiki' })">
        返回 Wiki 总览
      </button>
    </div>

    <div
      v-else-if="page"
      class="grid lg:grid-cols-[minmax(0,1fr)_19rem] xl:grid-cols-[14rem_minmax(0,1fr)_19rem] gap-6 items-start"
    >
      <!-- 左侧：页面树 -->
      <aside
        class="sticky top-4 hidden flex-col overflow-hidden kiwi-card p-3 xl:flex"
        :style="{
          height: 'var(--wiki-tree-h, calc(100dvh - 9.75rem))',
          maxHeight: 'var(--wiki-tree-h, calc(100dvh - 9.75rem))',
        }"
      >
        <div class="mb-2 flex shrink-0 items-center justify-between px-1">
          <p class="text-xs font-medium text-slate-500 flex items-center gap-1.5">
            <KiwiIcon name="listTree" :size="12" class="text-kiwi-500" />
            页面目录
          </p>
          <span class="text-[10px] tabular-nums text-slate-300">{{ pages.length }}</span>
        </div>
        <WikiPageTree
          :pages="pages"
          :active-id="pageId"
          :loading="indexLoading"
          @select="openPage"
        />
      </aside>

      <!-- 正文 -->
      <article class="kiwi-card p-6 md:p-9 min-w-0 animate-fade-up">
        <div class="flex items-start gap-3">
          <div class="min-w-0 flex-1">
            <input
              v-if="editing"
              v-model="draftTitle"
              class="w-full text-2xl font-semibold text-slate-800 bg-transparent border-b border-slate-200 focus:border-kiwi-400 focus:outline-none pb-1"
              placeholder="页面标题"
            />
            <h1 v-else class="text-2xl md:text-3xl font-semibold text-slate-800 leading-tight">
              {{ page.title }}
            </h1>
            <div class="flex flex-wrap items-center gap-2 mt-2.5 text-[11px]">
              <span class="px-2 py-0.5 rounded-full bg-kiwi-50 text-kiwi-600">
                {{ TYPE_LABEL[page.page_type] ?? page.page_type }}
              </span>
              <span class="px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 font-mono">
                {{ page.slug }}
              </span>
              <span class="text-slate-400">v{{ page.version }}</span>
              <span
                v-if="page.human_edited"
                class="px-2 py-0.5 rounded-full bg-amber-50 text-amber-600 flex items-center gap-1"
              >
                <KiwiIcon name="edit" :size="9" />
                人工保护
              </span>
              <span
                v-for="tag in page.tags"
                :key="tag"
                class="px-2 py-0.5 rounded-full bg-slate-100 text-slate-500"
              >
                {{ tag }}
              </span>
            </div>
          </div>

          <div class="flex items-center gap-1.5 shrink-0">
            <template v-if="editing">
              <button class="kiwi-btn-secondary !py-1.5" :disabled="saving" @click="cancelEdit">
                取消
              </button>
              <button class="kiwi-btn-primary !py-1.5" :disabled="saving" @click="save">
                <KiwiIcon name="loader" v-if="saving" :size="13" spin />
                <KiwiIcon name="check" v-else :size="13" />
                保存
              </button>
            </template>
            <template v-else>
              <button
                v-if="!readOnly"
                class="kiwi-btn-secondary !py-1.5"
                @click="startEdit"
              >
                <KiwiIcon name="edit" :size="13" />
                编辑
              </button>
              <button class="kiwi-btn-ghost !px-2" title="刷新" @click="load">
                <KiwiIcon name="refresh" :size="15" />
              </button>
            </template>
          </div>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
          <span>更新于 {{ fmtDate(page.updated_at) }}</span>
          <span class="flex items-center gap-1">
            <KiwiIcon name="link2" :size="11" />
            被引用 {{ page.backlink_count }} 次
          </span>
          <span class="flex items-center gap-1">
            <KiwiIcon name="file" :size="11" />
            编译自 {{ page.compiled_from_source_ids.length }} 个素材
          </span>
          <span class="flex items-center gap-1">
            <KiwiIcon name="bookOpen" :size="11" />
            {{ page.annotation_count }} 条批注
          </span>
        </div>

        <div class="my-5 h-px bg-gradient-to-r from-slate-200/80 via-slate-100 to-transparent" />

        <!-- 源漂移提示（人工保护页不被增量重导入覆盖） -->
        <div
          v-if="sourceDrift"
          class="mb-5 rounded-xl border border-amber-200/80 bg-amber-50/70 px-3.5 py-2.5 flex items-start gap-2"
        >
          <KiwiIcon name="alert" :size="14" class="text-amber-500 mt-0.5 shrink-0" />
          <div class="min-w-0">
            <p class="text-xs font-medium text-amber-700">源素材已更新，本页受人工保护未被覆盖</p>
            <p class="text-[11px] text-amber-600/90 mt-0.5 leading-relaxed">
              「{{ sourceDrift.source_title || '素材' }}」内容有变化，请对照素材核对正文；
              编辑并保存后即视为已核对，提示会自动清除。
            </p>
          </div>
        </div>

        <!-- 编辑态 -->
        <div v-if="editing" class="space-y-4">
          <div class="flex flex-wrap items-center gap-3">
            <label class="text-xs text-slate-500 flex items-center gap-1.5">
              页面类型
              <select
                v-model="draftType"
                class="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 focus:border-kiwi-400 focus:outline-none"
              >
                <option v-for="(label, key) in TYPE_LABEL" :key="key" :value="key">
                  {{ label }}
                </option>
              </select>
            </label>
            <label class="text-xs text-slate-500 flex items-center gap-1.5 flex-1 min-w-[16rem]">
              标签
              <input
                v-model="draftTags"
                class="flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 focus:border-kiwi-400 focus:outline-none"
                placeholder="用逗号分隔，例如：数据库, 索引"
              />
            </label>
          </div>
          <textarea
            v-model="draftBody"
            class="w-full min-h-[32rem] rounded-xl border border-slate-200 bg-slate-50/50 p-4 font-mono text-[13px] leading-relaxed text-slate-700 focus:border-kiwi-400 focus:bg-white focus:outline-none"
            spellcheck="false"
            placeholder="使用 Markdown 编写正文；[[slug]] 会生成页面间链接。"
          />
          <p class="text-[11px] text-slate-400">
            保存后该页标记为「人工保护」，后续素材编译不会覆盖你的修改。链接关系会按 [[slug]] 自动重建。
          </p>
        </div>

        <!-- 阅读态 -->
        <WikiMarkdown v-else :content="displayBody" :pages="linkIndex" />

        <div
          v-if="!editing && page.related_notes.length"
          class="mt-8 pt-5 border-t border-slate-100"
        >
          <p class="text-xs font-medium text-slate-500 mb-2.5 flex items-center gap-1.5">
            <KiwiIcon name="note" :size="12" />
            关联笔记
          </p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="note in page.related_notes"
              :key="note.id"
              class="px-3 py-1.5 rounded-lg bg-slate-50 hover:bg-kiwi-50 text-xs text-slate-600 hover:text-kiwi-700 transition-colors"
              @click="openNote(note.id)"
            >
              {{ note.title }}
            </button>
          </div>
        </div>
      </article>

      <!-- 右侧栏 -->
      <aside class="space-y-4 lg:sticky lg:top-4 animate-fade-up" style="animation-delay: 60ms">
        <!-- 学习状态 -->
        <div class="kiwi-card p-4">
          <div class="flex items-center justify-between">
            <p class="text-xs font-medium text-slate-500 flex items-center gap-1.5">
              <KiwiIcon name="target" :size="13" class="text-kiwi-500" />
              学习掌握度
            </p>
            <span class="text-sm font-semibold tabular-nums" :class="masteryPct == null ? 'text-slate-300' : 'text-kiwi-600'">
              {{ masteryPct == null ? '未评估' : `${masteryPct}%` }}
            </span>
          </div>
          <KiwiProgress
            v-if="masteryPct != null"
            class="mt-2.5"
            :value="(page.mastery ?? 0)"
            :status="masteryPct >= 80 ? 'done' : 'running'"
          />
          <p v-else class="text-[11px] text-slate-400 mt-2 leading-relaxed">
            完成一次训练或练习后，这里会累积掌握度。
          </p>
          <button class="kiwi-btn-ghost w-full mt-2 !text-[11px]" @click="startLearningHere">
            <KiwiIcon name="learn" :size="12" />
            针对本页发起学习
          </button>
        </div>

        <!-- Tab 面板 -->
        <div class="kiwi-card overflow-hidden">
          <div class="grid grid-cols-4 border-b border-slate-100 text-[11px]">
            <button
              v-for="tab in PANEL_TABS"
              :key="tab.key"
              class="py-2.5 transition-colors relative"
              :class="activeTab === tab.key ? 'text-kiwi-700 font-medium' : 'text-slate-400 hover:text-slate-600'"
              @click="activeTab = tab.key"
            >
              {{ tab.label }}
              <span
                class="ml-0.5 text-[10px]"
                :class="activeTab === tab.key ? 'text-kiwi-400' : 'text-slate-300'"
              >
                {{ tabCounts[tab.key] }}
              </span>
              <span
                v-if="activeTab === tab.key"
                class="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-kiwi-500"
              />
            </button>
          </div>

          <!-- 大纲 -->
          <div v-if="activeTab === 'toc'" class="p-3 max-h-[26rem] overflow-y-auto">
            <p v-if="!toc.length" class="text-[11px] text-slate-400 py-3 text-center">
              正文暂无标题
            </p>
            <button
              v-for="h in toc"
              :key="h.id"
              class="block w-full text-left text-[12px] py-1.5 rounded-lg px-2 text-slate-500 hover:text-kiwi-700 hover:bg-kiwi-50 transition-colors truncate"
              :style="{ paddingLeft: `${(h.level - 1) * 12 + 8}px` }"
              @click="scrollTo(h.id)"
            >
              {{ h.text }}
            </button>
          </div>

          <!-- 链接 -->
          <div v-else-if="activeTab === 'links'" class="p-3 max-h-[26rem] overflow-y-auto space-y-4">
            <div>
              <p class="text-[10.5px] text-slate-400 mb-1.5">反向链接（{{ backlinks.length }}）</p>
              <p v-if="!backlinks.length" class="text-[11px] text-slate-300 py-1">
                暂无页面引用本页
              </p>
              <button
                v-for="p in backlinks"
                :key="p.id"
                class="block w-full text-left px-2 py-1.5 rounded-lg hover:bg-kiwi-50 transition-colors group"
                @click="openPage(p.id)"
              >
                <span class="text-[12px] text-slate-600 group-hover:text-kiwi-700 line-clamp-1">
                  {{ p.title }}
                </span>
                <span class="text-[10px] text-slate-300 font-mono">{{ p.slug }}</span>
              </button>
            </div>
            <div class="pt-3 border-t border-slate-100">
              <p class="text-[10.5px] text-slate-400 mb-1.5">出链（{{ outlinks.length }}）</p>
              <p v-if="!outlinks.length" class="text-[11px] text-slate-300 py-1">
                本页未链接其他页面
              </p>
              <button
                v-for="p in outlinks"
                :key="p.id"
                class="block w-full text-left px-2 py-1.5 rounded-lg hover:bg-kiwi-50 transition-colors group"
                @click="openPage(p.id)"
              >
                <span class="text-[12px] text-slate-600 group-hover:text-kiwi-700 line-clamp-1">
                  {{ p.title }}
                </span>
                <span class="text-[10px] text-slate-300 font-mono">{{ p.slug }}</span>
              </button>
            </div>
          </div>

          <!-- 批注 -->
          <div v-else-if="activeTab === 'annotations'" class="p-3 max-h-[30rem] overflow-y-auto">
            <p
              v-if="!canAnnotate"
              class="text-[10.5px] text-slate-400 rounded-lg bg-slate-50 px-2.5 py-2 mb-3 flex items-center gap-1.5"
            >
              <KiwiIcon name="bookOpen" :size="11" />
              批注在学习模式中编辑；编辑模式只读查看。
            </p>
            <div v-if="canAnnotate" class="space-y-2 mb-3">
              <div
                v-if="annotationQuote"
                class="flex items-start gap-1.5 rounded-lg bg-slate-50 px-2 py-1.5 text-[11px] text-slate-500"
              >
                <KiwiIcon name="quote" :size="11" class="mt-0.5 shrink-0 text-slate-300" />
                <span class="flex-1 line-clamp-2">{{ annotationQuote }}</span>
                <button class="text-slate-300 hover:text-slate-500" @click="annotationQuote = ''">
                  <KiwiIcon name="close" :size="10" />
                </button>
              </div>
              <textarea
                v-model="annotationText"
                rows="2"
                class="w-full rounded-lg border border-slate-200 bg-white p-2 text-[12px] focus:border-kiwi-400 focus:outline-none"
                placeholder="写下你的理解、疑问或记忆点…"
              />
              <div class="flex items-center gap-1.5">
                <button class="kiwi-btn-ghost !px-2 !py-1 !text-[10.5px]" @click="captureSelection">
                  <KiwiIcon name="quote" :size="11" />
                  引用选中文本
                </button>
                <button
                  class="kiwi-btn-primary !px-2.5 !py-1 !text-[10.5px] ml-auto"
                  :disabled="annotationSaving || !annotationText.trim()"
                  @click="addAnnotation"
                >
                  添加批注
                </button>
              </div>
            </div>

            <p v-if="annotationsLoading" class="text-[11px] text-slate-300 text-center py-3">
              加载中…
            </p>
            <p v-else-if="!annotations.length" class="text-[11px] text-slate-300 text-center py-3">
              还没有批注。这里的内容仅自己可见，不写回 Wiki。
            </p>
            <div v-else class="space-y-2">
              <div
                v-for="row in annotations"
                :key="row.id"
                class="rounded-lg border border-slate-100 bg-slate-50/60 p-2.5 group"
              >
                <blockquote
                  v-if="row.quote"
                  class="text-[10.5px] text-slate-400 border-l-2 border-slate-200 pl-2 mb-1.5 line-clamp-2"
                >
                  {{ row.quote }}
                </blockquote>
                <template v-if="editingAnnotationId === row.id">
                  <textarea
                    v-model="editAnnotationText"
                    rows="2"
                    class="w-full rounded-md border border-slate-200 bg-white p-1.5 text-[11.5px] focus:outline-none"
                  />
                  <div class="flex justify-end gap-1.5 mt-1.5">
                    <button class="text-[10.5px] text-slate-400" @click="editingAnnotationId = null">
                      取消
                    </button>
                    <button class="text-[10.5px] text-kiwi-600" @click="saveAnnotation(row)">
                      保存
                    </button>
                  </div>
                </template>
                <template v-else>
                  <p class="text-[11.5px] text-slate-600 leading-relaxed whitespace-pre-wrap">
                    {{ row.content_md }}
                  </p>
                  <div class="flex items-center gap-2 mt-1.5 text-[10px] text-slate-300">
                    <span>{{ fmtDate(row.created_at) }}</span>
                    <template v-if="canAnnotate">
                      <button class="ml-auto hover:text-kiwi-600" @click="startEditAnnotation(row)">
                        编辑
                      </button>
                      <button class="hover:text-rose-500" @click="removeAnnotation(row)">删除</button>
                    </template>
                  </div>
                </template>
              </div>
            </div>
          </div>

          <!-- 来源 -->
          <div v-else class="p-3 max-h-[26rem] overflow-y-auto space-y-3">
            <div>
              <p class="text-[10.5px] text-slate-400 mb-1">编译素材（{{ page.sources.length }}）</p>
              <p class="text-[10px] text-slate-300 leading-relaxed mb-1.5">
                编译时的原始解析结果；导入工作区后会自动生成同名可编辑笔记，点击即可打开。
              </p>
              <p v-if="!page.sources.length" class="text-[11px] text-slate-300 py-1">
                人工创建或暂无可追溯素材
              </p>
              <component
                :is="s.note_id ? 'button' : 'div'"
                v-for="s in page.sources"
                :key="s.id"
                class="block w-full text-left px-2 py-1.5 rounded-lg"
                :class="s.note_id ? 'hover:bg-kiwi-50 group cursor-pointer' : 'hover:bg-slate-50'"
                :title="s.note_id ? '打开由该素材生成的笔记' : s.title"
                @click="s.note_id && openNote(s.note_id)"
              >
                <p class="text-[12px] text-slate-600 truncate flex items-center gap-1" :title="s.title">
                  <span class="truncate">{{ s.title }}</span>
                  <KiwiIcon
                    v-if="s.note_id"
                    name="arrowUpRight"
                    :size="11"
                    class="shrink-0 text-slate-300 group-hover:text-kiwi-500"
                  />
                </p>
                <p class="text-[10px] text-slate-300 flex items-center gap-1.5 mt-0.5">
                  <span>{{ s.type }}</span>
                  <span>·</span>
                  <span>{{ s.parse_quality }}</span>
                  <span v-if="s.note_id" class="text-kiwi-400/80">已生成笔记</span>
                  <span class="ml-auto font-mono">{{ s.sha256.slice(0, 8) }}</span>
                </p>
              </component>
            </div>
            <div class="pt-2 border-t border-slate-100">
              <p class="text-[10.5px] text-slate-400 mb-0.5">
                关联笔记（{{ page.related_notes.length }}）
              </p>
              <p class="text-[10px] text-slate-300 leading-relaxed mb-1.5">
                在笔记中手动关联到此页的笔记，与上方素材来源相互独立。
              </p>
              <p v-if="!page.related_notes.length" class="text-[11px] text-slate-300 py-1">
                暂无手动关联的笔记
              </p>
              <button
                v-for="n in page.related_notes"
                :key="n.id"
                class="flex w-full items-center gap-1.5 text-left px-2 py-1.5 rounded-lg hover:bg-kiwi-50 text-[12px] text-slate-600 hover:text-kiwi-700"
                @click="openNote(n.id)"
              >
                <span class="truncate">{{ n.title }}</span>
                <span class="ml-auto shrink-0 text-[9.5px] text-slate-300">{{ n.kind }}</span>
              </button>
            </div>
          </div>
        </div>

        <!-- 危险操作 -->
        <div v-if="!readOnly" class="kiwi-card p-3">
          <button
            class="w-full text-[11px] text-slate-400 hover:text-rose-500 transition-colors py-1"
            @click="deleteOpen = true"
          >
            删除此 Wiki 页面
          </button>
        </div>
      </aside>
    </div>

    <!-- 窄屏页面树抽屉 -->
    <Teleport to="body">
      <div v-if="treeOpen" class="fixed inset-0 z-50 xl:hidden">
        <div
          class="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
          @click="treeOpen = false"
        />
        <div class="absolute inset-y-0 left-0 flex w-72 flex-col bg-white shadow-xl p-3">
          <div class="mb-2 flex shrink-0 items-center justify-between px-1">
            <p class="text-xs font-medium text-slate-500 flex items-center gap-1.5">
              <KiwiIcon name="listTree" :size="12" class="text-kiwi-500" />
              页面目录
            </p>
            <button
              class="grid h-6 w-6 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              title="关闭"
              @click="treeOpen = false"
            >
              <KiwiIcon name="close" :size="13" />
            </button>
          </div>
          <WikiPageTree
            :pages="pages"
            :active-id="pageId"
            :loading="indexLoading"
            @select="openPage"
          />
        </div>
      </div>
    </Teleport>

    <KiwiConfirm
      v-model="deleteOpen"
      title="删除 Wiki 页面"
      :message="`将删除「${page?.title || ''}」及其引用边、向量索引；关联笔记会解除绑定。此操作不可撤销。`"
      confirm-text="删除"
      danger
      @confirm="removePage"
    />
  </div>
</template>
