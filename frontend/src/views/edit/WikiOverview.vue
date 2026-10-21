<script setup lang="ts">
/** Wiki 总览：图谱 / 页面卡片、学习画像与掌握度、健康检查、近期活动。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { request } from '@/api/client'
import { compileSources, listSources } from '@/api/sources'
import { useKbsStore } from '@/stores/kbs'
import { useModeStore } from '@/stores/mode'
import { useNotesStore } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiStat from '@/components/ui/KiwiStat.vue'
import KiwiSkeleton from '@/components/ui/KiwiSkeleton.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import KiwiProgress from '@/components/ui/KiwiProgress.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import WikiGraphPanel from '@/components/graph/WikiGraphPanel.vue'
import { toast } from '@/components/ui/toast'

interface WikiPage {
  id: string
  kb_id: string
  slug: string
  page_type: string
  title: string
  version: number
  human_edited: boolean
  updated_at: string
  link_count: number
  summary: string
  tags: string[]
  mastery: number | null
  annotation_count: number
  source_count: number
}

interface StudyStatus {
  has_profile: boolean
  onboarded: boolean
  goal_type: string | null
  topic_count: number
  covered_topic_count: number
  mastery_coverage: number
  average_mastery: number
  weak_count: number
  target_date: string | null
}

interface ActivityItem {
  at: string
  kind: string
  status: string
  title: string
  detail: string
  job_id?: string | null
  note_id?: string | null
  source_id?: string | null
  progress?: number
}

interface Overview {
  page_count: number
  page_type_distribution: Record<string, number>
  pending_compile_count: number
  pending_review_count: number
  note_compile_candidate_count: number
  human_edited_count: number
  study_status: StudyStatus
  recent_activity: ActivityItem[]
  pages: WikiPage[]
}

interface LintIssue {
  code: string
  severity: string
  category: string
  message: string
  page_id: string | null
  page_title: string | null
  detail: string | null
}

interface LintReport {
  id?: string
  generated_at: string
  summary: {
    page_count?: number
    issue_count?: number
    error_count?: number
    warning_count?: number
    info_count?: number
    by_category?: Record<string, number>
    by_severity?: Record<string, number>
  }
  issues: LintIssue[]
  semantic_status: string
  semantic_error: string | null
  trigger?: string
}

const kbs = useKbsStore()
const mode = useModeStore()
const notesStore = useNotesStore()
const router = useRouter()
/** 学习模式下 Wiki 总览跟随学习知识库，避免从引用跳转时落到编辑库。 */
const kbId = computed(() =>
  mode.mode === 'learn' ? kbs.activeLearnKbId : kbs.currentKbId,
)
const ov = ref<Overview | null>(null)
const loading = ref(false)
const activeType = ref<string | null>(null)
const query = ref('')
const viewMode = ref<'graph' | 'cards'>('graph')

async function load() {
  if (!kbId.value) return
  loading.value = true
  void loadLatestLint()
  try {
    ov.value = await request<Overview>('/wiki/overview', { kbId: kbId.value })
  } catch (e: any) {
    toast.error(e.message || 'Wiki 总览加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => kbId.value, load)

const compilingNotes = ref(false)
const compilingSources = ref(false)
const rebuilding = ref(false)

/** 清空全部 Wiki 页面与向量，再把全部笔记 / 独立素材重新编译。 */
async function rebuildWiki() {
  if (!kbId.value || rebuilding.value) return
  const pageCount = ov.value?.page_count ?? 0
  const ok = window.confirm(
    `将删除本库全部 ${pageCount} 个 Wiki 页面、页面批注与健康检查历史，` +
      '并重新编译全部笔记和独立素材。人工编辑保护的页面也会被删除，此操作不可撤销。\n\n' +
      '确定继续重建吗？',
  )
  if (!ok) return
  rebuilding.value = true
  try {
    const res = await request<{
      deleted_pages: number
      note_jobs: unknown[]
      source_jobs: unknown[]
      count: number
      skipped_empty: number
      skipped_busy: number
    }>('/wiki/rebuild', { method: 'POST', kbId: kbId.value })
    const skipped = res.skipped_empty + res.skipped_busy
    toast.success(
      `已清空 ${res.deleted_pages} 个页面，提交 ${res.count} 个编译任务` +
        (skipped ? `（${skipped} 篇暂无可编译内容）` : ''),
    )
    await load()
    if (res.count) router.push({ name: 'sources', query: { tab: 'jobs' } })
  } catch (e: any) {
    toast.error(e.message || 'Wiki 重建失败')
  } finally {
    rebuilding.value = false
  }
}

/** Wiki 内的按需编译入口：把已解析、尚未编译的素材提交编译。 */
async function compilePendingSources() {
  if (!kbId.value) return
  compilingSources.value = true
  try {
    const list = await listSources(kbId.value)
    const ids = list.filter((s) => s.status === 'parsed').map((s) => s.id)
    if (!ids.length) {
      toast.info('没有待编译的素材')
      await load()
      return
    }
    let submitted = 0
    let skipped = 0
    for (let i = 0; i < ids.length; i += 20) {
      const res = await compileSources(kbId.value, ids.slice(i, i + 20))
      submitted += res.count
      skipped += res.skipped
    }
    toast.success(
      skipped
        ? `已提交 ${submitted} 个编译任务，${skipped} 个未提交`
        : `已提交 ${submitted} 个编译任务`,
    )
    router.push({ name: 'sources', query: { tab: 'jobs' } })
  } catch (e: any) {
    toast.error(e.message || '提交素材编译失败')
  } finally {
    compilingSources.value = false
  }
}

async function compileAllNotes() {
  if (!kbId.value) return
  compilingNotes.value = true
  try {
    const res = await notesStore.compileAllNotes()
    if (res.count) {
      toast.success(
        `已提交 ${res.count} 篇笔记编译任务（文档 / 导入 / 链接 / 数据表 / 画布 / Notebook）`,
      )
      router.push({ name: 'sources', query: { tab: 'jobs' } })
    } else if (res.skipped_busy) {
      toast.info(`${res.skipped_busy} 篇笔记正在编译中`)
      router.push({ name: 'sources', query: { tab: 'jobs' } })
    } else {
      toast.info('没有需要编译的笔记')
    }
  } catch (e: any) {
    toast.error(e.message || '提交笔记编译失败')
  } finally {
    compilingNotes.value = false
  }
}

function openActivity(item: ActivityItem) {
  if (item.job_id) {
    router.push({ name: 'sources', query: { tab: 'jobs', job: item.job_id } })
  } else if (item.note_id) {
    router.push({ name: 'notes', params: { id: item.note_id } })
  }
}

const TYPES = ['entity', 'concept', 'summary', 'synthesis']
const TYPE_LABEL: Record<string, string> = {
  entity: '实体',
  concept: '概念',
  summary: '摘要',
  synthesis: '综合',
}
const TYPE_BADGE: Record<string, string> = {
  entity: 'bg-kiwi-50 text-kiwi-600',
  concept: 'bg-sky-50 text-sky-600',
  summary: 'bg-amber-50 text-amber-600',
  synthesis: 'bg-violet-50 text-violet-600',
}
const GOAL_LABEL: Record<string, string> = {
  exam: '考试备考',
  domain: '领域学习',
  explore: '探索了解',
}

const filtered = computed(() => {
  if (!ov.value) return []
  const keyword = query.value.trim().toLowerCase()
  return ov.value.pages.filter((p) => {
    if (activeType.value && p.page_type !== activeType.value) return false
    if (!keyword) return true
    return (
      p.title.toLowerCase().includes(keyword) ||
      p.slug.toLowerCase().includes(keyword) ||
      (p.summary || '').toLowerCase().includes(keyword) ||
      p.tags.some((t) => t.toLowerCase().includes(keyword))
    )
  })
})

const allCount = computed(() => ov.value?.page_count ?? 0)
const study = computed<StudyStatus | null>(() => ov.value?.study_status ?? null)
const coveragePct = computed(() =>
  study.value ? Math.round((study.value.mastery_coverage || 0) * 100) : 0,
)
const masteryPct = computed(() =>
  study.value ? Math.round((study.value.average_mastery || 0) * 100) : 0,
)

function openPage(id: string) {
  void router.push({ name: 'wiki-page', params: { id } })
}

/** 图谱节点点击：wiki 节点进入详情，note 节点进入笔记工作区。 */
function openGraphNode(nodeId: string) {
  if (nodeId.startsWith('wiki:')) {
    openPage(nodeId.slice(5))
  } else if (nodeId.startsWith('note:')) {
    void router.push({ name: 'notes', params: { id: nodeId.slice(5) } })
  }
}

function fmtDate(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const ACTIVITY_META: Record<string, { icon: string; color: string; label: string }> = {
  import: { icon: 'fileImport', color: 'text-sky-500 bg-sky-50', label: '导入' },
  compile: { icon: 'wiki', color: 'text-kiwi-500 bg-kiwi-50', label: '编译' },
  wiki: { icon: 'edit', color: 'text-amber-500 bg-amber-50', label: '页面更新' },
}

function activityMeta(kind: string) {
  return ACTIVITY_META[kind] ?? { icon: 'sparkle', color: 'text-slate-400 bg-slate-50', label: kind }
}

// ---------- 健康检查 ----------
const lintOpen = ref(false)
const linting = ref(false)
const lintFull = ref(false)
const lintReport = ref<LintReport | null>(null)
const lintError = ref('')
const latestLint = ref<LintReport | null>(null)

async function loadLatestLint() {
  if (!kbId.value) return
  try {
    latestLint.value = await request<LintReport | null>('/wiki/lint/latest', {
      kbId: kbId.value,
    })
  } catch {
    latestLint.value = null
  }
}

function openSavedLint() {
  if (!latestLint.value) return
  lintReport.value = latestLint.value
  lintFull.value = latestLint.value.trigger === 'full'
  lintError.value = ''
  linting.value = false
  lintOpen.value = true
}

const severityClass: Record<string, string> = {
  error: 'bg-rose-50 text-rose-600',
  warning: 'bg-amber-50 text-amber-600',
  info: 'bg-slate-100 text-slate-500',
}
const categoryLabel: Record<string, string> = {
  dead_link: '死链',
  orphan: '孤立页面',
  frontmatter: 'Frontmatter',
  slug: 'Slug',
  index: '索引',
  conflict: '语义冲突',
  gap: '知识缺口',
  drift: '源漂移',
}

async function runLint(full: boolean) {
  if (!kbId.value) return
  lintOpen.value = true
  linting.value = true
  lintFull.value = full
  lintError.value = ''
  lintReport.value = null
  try {
    lintReport.value = await request<LintReport>(
      `/wiki/lint?include_semantic=${full ? 'true' : 'false'}`,
      { method: 'POST', kbId: kbId.value },
    )
    latestLint.value = lintReport.value
  } catch (e: any) {
    lintError.value = e.message || '健康检查失败'
  } finally {
    linting.value = false
  }
}

function openIssuePage(issue: LintIssue) {
  if (issue.page_id) {
    lintOpen.value = false
    openPage(issue.page_id)
  }
}

// ---------- Wiki Schema（编译规范） ----------
interface WikiSchema {
  content: string
  customized: boolean
  default_content: string
  max_chars: number
}

const schemaOpen = ref(false)
const schemaLoading = ref(false)
const schemaSaving = ref(false)
const schemaReindexing = ref(false)
const schemaData = ref<WikiSchema | null>(null)
const schemaDraft = ref('')
const schemaErr = ref('')

async function openSchema() {
  if (!kbId.value) return
  schemaOpen.value = true
  schemaLoading.value = true
  schemaErr.value = ''
  try {
    schemaData.value = await request<WikiSchema>('/wiki/schema', { kbId: kbId.value })
    schemaDraft.value = schemaData.value.content
  } catch (e: any) {
    schemaErr.value = e.message || 'Schema 加载失败'
  } finally {
    schemaLoading.value = false
  }
}

async function saveSchema() {
  if (!kbId.value) return
  if (!schemaDraft.value.trim()) {
    schemaErr.value = 'Schema 不能为空；如需恢复默认请点击「恢复默认」'
    return
  }
  schemaSaving.value = true
  schemaErr.value = ''
  try {
    schemaData.value = await request<WikiSchema>('/wiki/schema', {
      method: 'PUT',
      kbId: kbId.value,
      body: JSON.stringify({ content: schemaDraft.value }),
    })
    schemaDraft.value = schemaData.value.content
    toast.success('Schema 已保存，下次编译生效')
  } catch (e: any) {
    schemaErr.value = e.message || 'Schema 保存失败'
  } finally {
    schemaSaving.value = false
  }
}

async function resetSchema() {
  if (!kbId.value) return
  if (!window.confirm('恢复内置默认 Schema？当前自定义内容将被删除（不影响已有 Wiki 页面）。')) return
  schemaSaving.value = true
  schemaErr.value = ''
  try {
    await request('/wiki/schema', { method: 'DELETE', kbId: kbId.value })
    if (schemaData.value) {
      schemaData.value = {
        ...schemaData.value,
        content: schemaData.value.default_content,
        customized: false,
      }
      schemaDraft.value = schemaData.value.default_content
    }
    toast.success('已恢复默认 Schema')
  } catch (e: any) {
    schemaErr.value = e.message || '恢复默认失败'
  } finally {
    schemaSaving.value = false
  }
}

async function reindexWiki() {
  if (!kbId.value) return
  schemaReindexing.value = true
  try {
    const res = await request<{ indexed: number }>('/wiki/reindex', {
      method: 'POST',
      kbId: kbId.value,
    })
    toast.success(`已用当前 embedding 模型重建 ${res.indexed} 个 Wiki 页向量`)
  } catch (e: any) {
    toast.error(e.message || '向量重建失败')
  } finally {
    schemaReindexing.value = false
  }
}
</script>

<template>
  <div class="page-wrap px-8 py-8">
    <!-- 页头 -->
    <div class="flex flex-wrap items-end justify-between gap-4 mb-8 animate-fade-up">
      <div class="flex items-center gap-3">
        <span
          class="w-10 h-10 rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 grid place-items-center text-white shadow-glow"
        >
          <KiwiIcon name="wiki" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">Wiki</h1>
          <p class="text-sm text-slate-500 mt-1">知识库编译产物、引用网络与学习状态</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button class="kiwi-btn-secondary" @click="openSchema">
          <KiwiIcon name="settings" :size="14" />
          编译 Schema
        </button>
        <button
          v-if="latestLint"
          type="button"
          class="mr-1 flex items-center gap-1.5 text-[10.5px] text-slate-400 transition-colors hover:text-kiwi-700"
          :title="`查看最近一次${latestLint.trigger === 'full' ? '深度' : '快速'}健康检查`"
          @click="openSavedLint"
        >
          <span
            class="h-1.5 w-1.5 rounded-full"
            :class="
              latestLint.summary.error_count
                ? 'bg-rose-400'
                : latestLint.summary.warning_count
                  ? 'bg-amber-400'
                  : 'bg-emerald-400'
            "
          />
          最近检查 {{ fmtDate(latestLint.generated_at) }}
          <span class="tabular-nums">· {{ latestLint.summary.issue_count ?? 0 }} 项问题</span>
        </button>
        <button
          type="button"
          class="kiwi-btn-secondary !text-rose-600 hover:!border-rose-200 hover:!bg-rose-50"
          :disabled="rebuilding || !ov?.page_count"
          title="删除全部 Wiki 页面，并从全部笔记与独立素材重新编译"
          @click="rebuildWiki"
        >
          <KiwiIcon :name="rebuilding ? 'loader' : 'trash'" :size="14" :spin="rebuilding" />
          {{ rebuilding ? '重建中…' : '重建 Wiki' }}
        </button>
        <button class="kiwi-btn-secondary" :disabled="linting" @click="runLint(false)">
          <KiwiIcon name="check" :size="14" />
          健康检查
        </button>
        <button class="kiwi-btn-secondary" @click="load">
          <KiwiIcon name="refresh" :size="14" :class="loading ? 'animate-spin' : ''" />
          刷新
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div v-if="ov" class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6 animate-fade-up">
      <KiwiStat label="Wiki 页面" :value="ov.page_count" accent="kiwi">
        <template #icon><KiwiIcon name="wiki" :size="18" /></template>
      </KiwiStat>
      <KiwiStat label="待编译素材" :value="ov.pending_compile_count" accent="amber">
        <template #icon><KiwiIcon name="file" :size="18" /></template>
      </KiwiStat>
      <KiwiStat label="待复核素材" :value="ov.pending_review_count" accent="emerald">
        <template #icon><KiwiIcon name="alert" :size="18" /></template>
      </KiwiStat>
      <KiwiStat label="人工保护页面" :value="ov.human_edited_count" accent="kiwi">
        <template #icon><KiwiIcon name="edit" :size="18" /></template>
      </KiwiStat>
    </div>
    <KiwiSkeleton v-else-if="loading" variant="stat" :cols="4" />

    <!-- 学习状态 + 近期活动：学习状态仅在进入学习模式后展示 -->
    <div
      v-if="ov"
      class="grid gap-4 mb-6 animate-fade-up"
      :class="mode.mode === 'learn' ? 'lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]' : 'grid-cols-1'"
    >
      <div v-if="mode.mode === 'learn'" class="kiwi-card p-5">
        <div class="flex items-center justify-between">
          <p class="text-sm font-medium text-slate-600 flex items-center gap-2">
            <KiwiIcon name="learn" :size="15" class="text-kiwi-500" />
            学习状态
          </p>
          <button class="text-[11px] text-kiwi-600 hover:text-kiwi-700" @click="mode.setMode('learn'); router.push({ name: 'learn' })">
            进入学习模式
            <KiwiIcon name="arrowRight" :size="10" class="inline" />
          </button>
        </div>

        <template v-if="study?.has_profile">
          <div class="grid sm:grid-cols-3 gap-4 mt-4">
            <div>
              <p class="text-[11px] text-slate-400">学习目标</p>
              <p class="text-sm text-slate-700 mt-0.5">
                {{ GOAL_LABEL[study.goal_type ?? ''] ?? '未设置' }}
                <span v-if="study.target_date" class="text-[10px] text-slate-400 ml-1">
                  截止 {{ study.target_date }}
                </span>
              </p>
            </div>
            <div>
              <p class="text-[11px] text-slate-400">知识点覆盖</p>
              <p class="text-sm text-slate-700 mt-0.5 tabular-nums">
                {{ study.covered_topic_count }} / {{ study.topic_count }}
                <span class="text-[10px] text-slate-400">（{{ coveragePct }}%）</span>
              </p>
            </div>
            <div>
              <p class="text-[11px] text-slate-400">平均掌握度 / 薄弱项</p>
              <p class="text-sm text-slate-700 mt-0.5 tabular-nums">
                {{ masteryPct }}%
                <span class="text-[10px]" :class="study.weak_count ? 'text-rose-500' : 'text-slate-400'">
                  · {{ study.weak_count }} 个薄弱
                </span>
              </p>
            </div>
          </div>
          <div class="mt-4 grid sm:grid-cols-2 gap-4">
            <div>
              <div class="flex justify-between text-[10px] text-slate-400 mb-1">
                <span>知识点覆盖</span><span>{{ coveragePct }}%</span>
              </div>
              <KiwiProgress :value="study.mastery_coverage" :status="coveragePct >= 80 ? 'done' : 'running'" />
            </div>
            <div>
              <div class="flex justify-between text-[10px] text-slate-400 mb-1">
                <span>平均掌握度</span><span>{{ masteryPct }}%</span>
              </div>
              <KiwiProgress :value="study.average_mastery" :status="masteryPct >= 80 ? 'done' : 'running'" />
            </div>
          </div>
        </template>
        <div v-else class="mt-4 flex items-center gap-3">
          <p class="text-xs text-slate-400 leading-relaxed">
            尚未建立学习画像。进入学习模式完成冷启动对话后，这里会展示掌握度覆盖与薄弱项。
          </p>
          <button class="kiwi-btn-primary !py-1.5 shrink-0" @click="mode.setMode('learn'); router.push({ name: 'learn' })">
            开始
          </button>
        </div>
      </div>

      <div class="kiwi-card p-5">
        <div class="flex flex-wrap items-center gap-2">
          <p class="text-sm font-medium text-slate-600 flex items-center gap-2">
            <KiwiIcon name="refresh" :size="14" class="text-slate-400" />
            近期活动
          </p>
          <div class="ml-auto flex items-center gap-1.5">
            <button
              v-if="ov.pending_compile_count"
              type="button"
              class="text-[11px] text-amber-600 transition-colors hover:text-amber-700 disabled:text-slate-300"
              :disabled="compilingSources"
              @click="compilePendingSources"
            >
              <KiwiIcon
                :name="compilingSources ? 'loader' : 'file'"
                :size="11"
                :spin="compilingSources"
                class="inline"
              />
              编译待处理素材 {{ ov.pending_compile_count }}
            </button>
            <span v-if="ov.pending_compile_count" class="text-slate-200">|</span>
            <button
              type="button"
              class="text-[11px] text-slate-500 transition-colors hover:text-kiwi-700"
              :disabled="compilingNotes"
              title="把本库全部笔记（文档 / 导入 / 链接 / 数据表 / 画布 / Notebook）编译进 Wiki"
              @click="compileAllNotes"
            >
              <KiwiIcon
                :name="compilingNotes ? 'loader' : 'sparkle'"
                :size="11"
                :spin="compilingNotes"
                class="inline"
              />
              编译全部笔记
              <span v-if="ov.note_compile_candidate_count" class="tabular-nums">
                · {{ ov.note_compile_candidate_count }} 篇
              </span>
            </button>
            <span class="text-slate-200">|</span>
            <button
              type="button"
              class="text-[11px] text-kiwi-600 hover:text-kiwi-700"
              @click="router.push({ name: 'sources', query: { tab: 'jobs' } })"
            >
              编译任务
              <KiwiIcon name="arrowRight" :size="10" class="inline" />
            </button>
          </div>
        </div>
        <div v-if="ov.recent_activity.length" class="mt-3 space-y-1 max-h-40 overflow-y-auto pr-1">
          <component
            :is="item.job_id || item.note_id ? 'button' : 'div'"
            v-for="(item, i) in ov.recent_activity"
            :key="`${item.at}-${i}`"
            :type="item.job_id || item.note_id ? 'button' : undefined"
            class="flex w-full items-start gap-2.5 rounded-lg px-1 py-1.5 text-left transition-colors"
            :class="item.job_id || item.note_id ? 'hover:bg-kiwi-50/50' : ''"
            @click="openActivity(item)"
          >
            <span
              class="w-6 h-6 shrink-0 rounded-lg grid place-items-center"
              :class="activityMeta(item.kind).color"
            >
              <KiwiIcon :name="activityMeta(item.kind).icon" :size="11" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-[12px] text-slate-600 truncate">{{ item.title }}</p>
              <p class="text-[10px] text-slate-400 truncate">
                {{ activityMeta(item.kind).label }} · {{ item.detail }}
              </p>
            </div>
            <KiwiIcon
              v-if="item.job_id"
              name="arrowUpRight"
              :size="11"
              class="mt-1 shrink-0 text-slate-300"
            />
            <span v-else class="text-[10px] text-slate-300 shrink-0">{{ fmtDate(item.at) }}</span>
          </component>
        </div>
        <p v-else class="text-xs text-slate-300 mt-4">暂无可展示的活动</p>
      </div>
    </div>

    <!-- 视图切换 + 搜索 -->
    <div class="flex flex-wrap items-center gap-2 mb-5 animate-fade-up" style="animation-delay: 40ms">
      <div class="inline-flex p-1 rounded-xl bg-slate-200/60 backdrop-blur-sm border border-slate-200/60">
        <button
          class="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium transition-all duration-200"
          :class="viewMode === 'graph' ? 'bg-white text-kiwi-700 shadow-soft' : 'text-slate-500 hover:text-slate-700'"
          @click="viewMode = 'graph'"
        >
          <KiwiIcon name="graph" :size="13" />
          图谱
        </button>
        <button
          class="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium transition-all duration-200"
          :class="viewMode === 'cards' ? 'bg-white text-kiwi-700 shadow-soft' : 'text-slate-500 hover:text-slate-700'"
          @click="viewMode = 'cards'"
        >
          <KiwiIcon name="wiki" :size="13" />
          卡片
        </button>
      </div>

      <template v-if="viewMode === 'cards'">
        <button
          v-for="t in [null, ...TYPES]"
          :key="t ?? 'all'"
          class="px-3 py-1 rounded-full text-xs font-medium border transition-all duration-200 active:scale-95"
          :class="
            activeType === t
              ? 'bg-gradient-to-r from-kiwi-500 to-kiwi-700 text-white border-transparent shadow-glow'
              : 'bg-white/70 text-slate-600 border-slate-200 hover:border-kiwi-300 hover:text-kiwi-700'
          "
          @click="activeType = t"
        >
          {{ t === null ? '全部' : TYPE_LABEL[t] ?? t }}
          <span class="opacity-70" :class="activeType === t ? 'text-kiwi-100' : 'text-slate-400'">
            {{ t === null ? allCount : ov?.page_type_distribution[t] || 0 }}
          </span>
        </button>
        <div class="relative ml-auto">
          <KiwiIcon
            name="search"
            :size="13"
            class="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-300"
          />
          <input
            v-model="query"
            class="w-56 rounded-lg border border-slate-200 bg-white/80 pl-8 pr-3 py-1.5 text-xs focus:border-kiwi-400 focus:outline-none"
            placeholder="搜索标题、摘要、标签…"
          />
        </div>
      </template>
      <span v-else class="text-xs text-slate-400 ml-auto">
        节点大小表示被引用次数 · 点击进入页面
      </span>
    </div>

    <!-- 图谱 -->
    <WikiGraphPanel
      v-if="viewMode === 'graph'"
      class="mb-6 animate-fade-up"
      @select:node="openGraphNode"
    />

    <!-- 卡片 -->
    <template v-else>
      <KiwiSkeleton v-if="loading && !ov" variant="card" :cols="3" />
      <KiwiEmpty
        v-else-if="!ov?.page_count"
        icon="wiki"
        title="还没有编译产物"
        desc="在笔记工作区创建素材并触发编译，或直接创建 Wiki 页面。"
      >
        <button class="kiwi-btn-primary" @click="router.push({ name: 'notes' })">
          <KiwiIcon name="note" :size="14" />
          去笔记工作区
        </button>
      </KiwiEmpty>

      <div v-else-if="filtered.length" class="grid md:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-4">
        <div
          v-for="(p, i) in filtered"
          :key="p.id"
          class="kiwi-card p-4 cursor-pointer group relative overflow-hidden animate-fade-up"
          :style="{ animationDelay: `${Math.min(i, 12) * 40}ms` }"
          @click="openPage(p.id)"
        >
          <div class="pointer-events-none absolute -top-8 -right-8 w-24 h-24 rounded-full bg-kiwi-100/70 blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
          <div class="flex items-center gap-2 relative">
            <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="TYPE_BADGE[p.page_type] ?? 'bg-slate-100 text-slate-500'">
              {{ TYPE_LABEL[p.page_type] ?? p.page_type }}
            </span>
            <span
              v-if="p.human_edited"
              class="text-[10px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-600 flex items-center gap-1"
              title="人工编辑保护"
            >
              <KiwiIcon name="edit" :size="9" />
              已保护
            </span>
            <span class="ml-auto text-[11px] text-slate-300 flex items-center gap-0.5">
              <KiwiIcon name="link2" :size="11" />
              {{ p.link_count }}
            </span>
          </div>

          <h3 class="font-semibold text-slate-800 mt-3 group-hover:text-kiwi-700 transition-colors truncate">
            {{ p.title }}
          </h3>
          <p class="text-xs text-slate-400 mt-1 line-clamp-2 min-h-[2.4rem] leading-relaxed">
            {{ p.summary || '暂无摘要' }}
          </p>

          <div v-if="p.tags.length" class="flex flex-wrap gap-1 mt-2">
            <span
              v-for="tag in p.tags.slice(0, 3)"
              :key="tag"
              class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500"
            >
              {{ tag }}
            </span>
            <span v-if="p.tags.length > 3" class="text-[10px] text-slate-300">
              +{{ p.tags.length - 3 }}
            </span>
          </div>

          <div v-if="p.mastery != null" class="mt-3">
            <div class="flex justify-between text-[10px] text-slate-400 mb-1">
              <span>掌握度</span>
              <span>{{ Math.round(p.mastery * 100) }}%</span>
            </div>
            <KiwiProgress :value="p.mastery" :status="p.mastery >= 0.8 ? 'done' : 'running'" />
          </div>

          <div class="flex items-center justify-between mt-3 pt-3 border-t border-slate-100 text-[11px] text-slate-400">
            <span class="font-mono truncate max-w-[55%]">{{ p.slug }}</span>
            <span class="flex items-center gap-2 shrink-0">
              <span v-if="p.source_count" class="flex items-center gap-0.5" title="编译素材数">
                <KiwiIcon name="file" :size="10" />
                {{ p.source_count }}
              </span>
              <span class="flex items-center gap-0.5" title="批注数">
                <KiwiIcon name="quote" :size="10" />
                {{ p.annotation_count }}
              </span>
              <span>v{{ p.version }}</span>
            </span>
          </div>
        </div>
      </div>

      <KiwiEmpty
        v-else
        icon="search"
        title="没有匹配的页面"
        desc="调整类型筛选或搜索关键词后重试"
      />
    </template>

    <!-- 编译 Schema（LLM Wiki 的结构化规范） -->
    <KiwiModal :open="schemaOpen" :maxW="'max-w-4xl'" @close="schemaOpen = false">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h2 class="text-lg font-semibold text-slate-800 flex items-center gap-2">
            <KiwiIcon name="settings" :size="17" class="text-kiwi-500" />
            编译 Schema
          </h2>
          <p class="text-xs text-slate-400 mt-1 leading-relaxed">
            每个知识库一份独立规范，定义页面类型与模板、slug / wikilink 规则、质量标准与 ingest 指令。
            编译时整份注入 LLM 上下文；保存后在下一次编译生效。
          </p>
        </div>
        <span
          class="shrink-0 text-[10px] px-2 py-0.5 rounded-full font-medium"
          :class="schemaData?.customized ? 'bg-kiwi-50 text-kiwi-600' : 'bg-slate-100 text-slate-500'"
        >
          {{ schemaData?.customized ? '已自定义' : '内置默认' }}
        </span>
      </div>

      <div v-if="schemaLoading" class="py-14 flex flex-col items-center gap-3 text-slate-400">
        <KiwiIcon name="loader" :size="22" spin class="text-kiwi-500" />
        <p class="text-sm">正在读取 Schema…</p>
      </div>

      <div v-else class="mt-4">
        <textarea
          v-model="schemaDraft"
          rows="18"
          spellcheck="false"
          class="w-full rounded-xl border border-slate-200 bg-slate-50/60 p-4 font-mono text-[12px] leading-relaxed text-slate-700 focus:border-kiwi-400 focus:bg-white focus:outline-none resize-y"
          placeholder="在此编写 Wiki 编译规范…"
        />
        <div class="flex flex-wrap items-center justify-between gap-2 mt-2">
          <p class="text-[11px]" :class="schemaErr ? 'text-rose-500' : 'text-slate-400'">
            {{ schemaErr || `Markdown 格式 · ${schemaDraft.length} / ${schemaData?.max_chars ?? 100000} 字符` }}
          </p>
          <button
            class="kiwi-btn-ghost !py-1.5 !text-xs"
            :disabled="schemaReindexing"
            title="更换 embedding 模型后，用当前模型重建全部 Wiki 页向量"
            @click="reindexWiki"
          >
            <KiwiIcon name="refresh" :size="12" :class="schemaReindexing ? 'animate-spin' : ''" />
            {{ schemaReindexing ? '重建中…' : '重建 Wiki 向量' }}
          </button>
        </div>
      </div>

      <div class="flex items-center justify-between gap-2 pt-3 mt-3 border-t border-slate-100">
        <button class="kiwi-btn-ghost !text-xs" :disabled="schemaSaving || !schemaData?.customized" @click="resetSchema">
          恢复默认
        </button>
        <div class="flex gap-2">
          <button class="kiwi-btn-ghost" @click="schemaOpen = false">取消</button>
          <button class="kiwi-btn-primary" :disabled="schemaSaving || schemaLoading" @click="saveSchema">
            <KiwiIcon v-if="schemaSaving" name="loader" :size="12" spin />
            {{ schemaSaving ? '保存中…' : '保存 Schema' }}
          </button>
        </div>
      </div>
    </KiwiModal>

    <!-- 健康检查报告 -->
    <KiwiModal :open="lintOpen" :maxW="'max-w-3xl'" @close="lintOpen = false">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h2 class="text-lg font-semibold text-slate-800 flex items-center gap-2">
            <KiwiIcon name="check" :size="17" class="text-kiwi-500" />
            Wiki 健康检查
          </h2>
          <p class="text-xs text-slate-400 mt-1">
            死链、孤立页面、frontmatter、slug、索引一致性、源漂移与语义冲突 / 缺口
          </p>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <button class="kiwi-btn-secondary !py-1.5 !text-xs" :disabled="linting" @click="runLint(false)">
            快速检查
          </button>
          <button class="kiwi-btn-primary !py-1.5 !text-xs" :disabled="linting" @click="runLint(true)">
            <KiwiIcon v-if="linting && lintFull" name="loader" :size="12" spin />
            完整检查
          </button>
        </div>
      </div>

      <div v-if="linting" class="py-12 flex flex-col items-center gap-3 text-slate-400">
        <KiwiIcon name="loader" :size="22" spin class="text-kiwi-500" />
        <p class="text-sm">
          {{ lintFull ? '正在执行确定性扫描与语义审查…' : '正在扫描…' }}
        </p>
        <p v-if="lintFull" class="text-[11px] text-slate-300">语义审查需要调用大模型，通常 10–60 秒</p>
      </div>

      <div v-else-if="lintError" class="py-10 text-center">
        <KiwiIcon name="alert" :size="24" class="text-rose-400 mx-auto" />
        <p class="text-sm text-slate-500 mt-2">{{ lintError }}</p>
      </div>

      <template v-else-if="lintReport">
        <div class="grid grid-cols-4 gap-2 mt-4">
          <div class="rounded-xl bg-slate-50 p-3 text-center">
            <p class="text-lg font-semibold text-slate-700 tabular-nums">
              {{ lintReport.summary.page_count ?? 0 }}
            </p>
            <p class="text-[10px] text-slate-400">页面</p>
          </div>
          <div class="rounded-xl bg-rose-50 p-3 text-center">
            <p class="text-lg font-semibold text-rose-600 tabular-nums">
              {{ lintReport.summary.error_count ?? 0 }}
            </p>
            <p class="text-[10px] text-rose-400">错误</p>
          </div>
          <div class="rounded-xl bg-amber-50 p-3 text-center">
            <p class="text-lg font-semibold text-amber-600 tabular-nums">
              {{ lintReport.summary.warning_count ?? 0 }}
            </p>
            <p class="text-[10px] text-amber-400">警告</p>
          </div>
          <div class="rounded-xl bg-sky-50 p-3 text-center">
            <p class="text-lg font-semibold text-sky-600 tabular-nums">
              {{ lintReport.summary.info_count ?? 0 }}
            </p>
            <p class="text-[10px] text-sky-400">提示</p>
          </div>
        </div>

        <p class="text-[11px] text-slate-400 mt-3">
          <template v-if="lintReport.semantic_status === 'ok'">
            ✓ 语义审查已完成（冲突 / 知识缺口）
          </template>
          <template v-else-if="lintReport.semantic_status === 'failed'">
            ⚠ 语义审查失败：{{ lintReport.semantic_error || '未知错误' }}；以下为确定性扫描结果。
          </template>
          <template v-else>
            快速检查不含语义审查，可点击「完整检查」补充冲突与知识缺口分析。
          </template>
        </p>

        <div class="mt-4 max-h-[26rem] overflow-y-auto space-y-2 pr-1">
          <p v-if="!lintReport.issues.length" class="py-8 text-center text-sm text-slate-400">
            未发现问题，Wiki 状态良好 🎉
          </p>
          <button
            v-for="(issue, i) in lintReport.issues"
            :key="`${issue.code}-${i}`"
            type="button"
            class="w-full text-left rounded-xl border border-slate-100 bg-white p-3 transition-colors"
            :class="issue.page_id ? 'hover:border-kiwi-200 hover:bg-kiwi-50/30 cursor-pointer' : 'cursor-default'"
            @click="openIssuePage(issue)"
          >
            <div class="flex items-center gap-2">
              <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium" :class="severityClass[issue.severity] ?? 'bg-slate-100 text-slate-500'">
                {{ issue.severity }}
              </span>
              <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">
                {{ categoryLabel[issue.category] ?? issue.category }}
              </span>
              <span v-if="issue.page_title" class="text-[11px] text-slate-400 truncate">
                {{ issue.page_title }}
              </span>
              <KiwiIcon
                v-if="issue.page_id"
                name="arrowRight"
                :size="11"
                class="ml-auto text-slate-300 shrink-0"
              />
            </div>
            <p class="text-[12px] text-slate-600 mt-1.5">{{ issue.message }}</p>
            <p v-if="issue.detail" class="text-[10.5px] text-slate-400 mt-0.5 truncate">
              {{ issue.detail }}
            </p>
          </button>
        </div>
        <p class="text-[10px] text-slate-300 mt-2 text-right">
          生成于 {{ fmtDate(lintReport.generated_at) }}
        </p>
      </template>
    </KiwiModal>
  </div>
</template>
