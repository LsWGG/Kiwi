<script setup lang="ts">
// MockExamPanel：仿真考试 —— 组卷列表、计时答题、自动保存、交卷批阅与成绩报告。
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  useStudyStore,
  QUESTION_TYPE_LABEL,
  type MockExamItem,
  type QuestionType,
} from '@/stores/study'
import { useDesktopStore } from '@/stores/desktop'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import ExamTemplateManager from '@/components/study/ExamTemplateManager.vue'
import KnowledgeRadar from '@/components/study/KnowledgeRadar.vue'
import { toast } from '@/components/ui/toast'

const emit = defineEmits<{
  (e: 'practice-weak'): void
  (e: 'practice-topic', slug: string): void
  (e: 'cite', slug: string): void
}>()

const study = useStudyStore()
const desktop = useDesktopStore()
const router = useRouter()

/** 组卷与主观题批阅都需要大模型。 */
const llmMissing = computed(
  () => desktop.isDesktop && desktop.ready && !desktop.llmConfigured,
)

type View = 'list' | 'intro' | 'taking' | 'report'
const view = ref<View>('list')
const currentExamId = ref<string | null>(null)
const showTemplates = ref(false)
const showCreate = ref(false)
const createTemplateId = ref('')
const createTitle = ref('')
const creating = ref(false)
const submitting = ref(false)
const confirmSubmit = ref(false)

const templateOptions = computed(() => study.templates)
const selectedTemplate = computed(() =>
  study.templates.find((t) => t.id === createTemplateId.value),
)

// ---------- 轮询（组卷 / 批阅） ----------
let pollTimer: ReturnType<typeof setTimeout> | null = null
function clearPoll() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}
function schedulePoll() {
  clearPoll()
  const busy =
    study.mockExams.some((e) => e.status === 'generating' || e.status === 'grading') ||
    (study.mockExam &&
      ['generating', 'grading'].includes(study.mockExam.status))
  if (!busy) return
  pollTimer = setTimeout(async () => {
    await study.loadMockExams()
    if (study.mockExam) {
      try {
        await study.loadMockExam(study.mockExam.id)
        if (study.mockExam.status === 'graded' && view.value !== 'report') {
          await openReport(study.mockExam.id)
        }
      } catch {
        /* 忽略单次轮询错误 */
      }
    }
    schedulePoll()
  }, 3500)
}

async function refreshList() {
  await study.loadMockExams()
  schedulePoll()
}

// ---------- 列表 ----------
function fmtDate(s?: string | null) {
  if (!s) return ''
  return new Date(s).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  generating: { label: '组卷中', cls: 'bg-amber-100 text-amber-700' },
  ready: { label: '待开始', cls: 'bg-kiwi-100 text-kiwi-700' },
  in_progress: { label: '进行中', cls: 'bg-sky-100 text-sky-700' },
  grading: { label: '批阅中', cls: 'bg-violet-100 text-violet-700' },
  graded: { label: '已批阅', cls: 'bg-emerald-100 text-emerald-700' },
  error: { label: '生成失败', cls: 'bg-rose-100 text-rose-700' },
}

async function createExam() {
  if (llmMissing.value) {
    toast.error('桌面版尚未配置大模型，无法自动组卷')
    return
  }
  if (!createTemplateId.value) return
  creating.value = true
  try {
    await study.createMockExam(createTemplateId.value, createTitle.value.trim() || undefined)
    showCreate.value = false
    createTitle.value = ''
    toast.success('已开始组卷，生成期间可以继续其他学习')
    schedulePoll()
  } catch (e: any) {
    toast.error(e.message || '创建试卷失败')
  } finally {
    creating.value = false
  }
}

async function enterExam(id: string) {
  currentExamId.value = id
  try {
    const exam = await study.loadMockExam(id)
    if (!exam) return
    if (exam.status === 'graded') {
      await openReport(id)
      return
    }
    if (exam.status === 'in_progress') {
      // 上次离开学习模式时已暂停：回到这里自动继续计时
      if (exam.paused_at) await study.resumeMockExam(id)
      initRunner()
      view.value = 'taking'
      return
    }
    view.value = 'intro'
    schedulePoll()
  } catch (e: any) {
    toast.error(e.message || '加载试卷失败')
  }
}

async function openReport(id: string) {
  currentExamId.value = id
  try {
    await study.loadMockReport(id)
    view.value = 'report'
  } catch (e: any) {
    toast.error(e.message || '加载报告失败')
  }
}

async function startExam() {
  if (!currentExamId.value) return
  try {
    await study.startMockExam(currentExamId.value)
    initRunner()
    view.value = 'taking'
  } catch (e: any) {
    toast.error(e.message || '开始考试失败')
  }
}

async function retryExam(id: string) {
  try {
    const summary = await study.retryMockExam(id)
    await study.loadMockExams()
    schedulePoll()
    toast.info('已重新组卷')
    void summary
  } catch (e: any) {
    toast.error(e.message || '重试失败')
  }
}

async function retakeExam(id: string) {
  try {
    await study.retakeMockExam(id)
    await study.loadMockExams()
    schedulePoll()
    toast.info('已按原模板重新组卷，可稍后开始重做')
  } catch (e: any) {
    toast.error(e.message || '重做组卷失败')
  }
}

function practiceTopic(slug: string) {
  emit('practice-topic', slug)
}

async function removeExam(id: string) {
  if (!window.confirm('确定删除这份试卷及作答记录？删除后不可恢复。')) return
  try {
    await study.deleteMockExam(id)
    if (currentExamId.value === id) {
      view.value = 'list'
      currentExamId.value = null
    }
    toast.success('已删除')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

function backToList() {
  clearPoll()
  pauseCurrentExam()
  view.value = 'list'
  currentExamId.value = null
  study.mockExam = null
  study.mockReport = null
  void refreshList()
}

// ---------- 答题器 ----------
interface LocalAnswer {
  selectedIndex: number | null
  selectedIndexes: number[]
  text: string
}
const answers = reactive<Record<string, LocalAnswer>>({})
const index = ref(0)
const flagged = reactive<Set<string>>(new Set())
const saveState = reactive<Record<string, 'idle' | 'saving' | 'saved'>>({})
const timeSpent = reactive<Record<string, number>>({})
const itemEnteredAt = ref(Date.now())
const remaining = ref(0)
const currentItem = computed<MockExamItem | null>(
  () => study.mockExam?.items[index.value] || null,
)
const examItems = computed(() => study.mockExam?.items || [])
const answeredItemIds = computed(
  () =>
    new Set(
      examItems.value
        .filter((it) => isAnswered(it.id))
        .map((it) => it.id),
    ),
)

function isAnswered(itemId: string) {
  const a = answers[itemId]
  if (!a) return false
  return a.selectedIndex !== null || a.selectedIndexes.length > 0 || !!a.text.trim()
}

const currentType = computed<QuestionType>(
  () => (currentItem.value?.section_type as QuestionType) || 'single_choice',
)
const currentIsChoice = computed(() =>
  ['single_choice', 'multiple_choice', 'true_false'].includes(currentType.value),
)
const currentIsMulti = computed(() => currentType.value === 'multiple_choice')
const currentIsSubjective = computed(() =>
  ['short_answer', 'case_analysis', 'essay'].includes(currentType.value),
)
const currentIsFill = computed(() => currentType.value === 'fill_blank')

function initRunner() {
  const exam = study.mockExam
  if (!exam) return
  for (const key of Object.keys(answers)) delete answers[key]
  for (const key of Object.keys(timeSpent)) delete timeSpent[key]
  for (const key of Object.keys(saveState)) delete saveState[key]
  flagged.clear()
  for (const item of exam.items) {
    const persistedIndexes = item.selected_indexes || []
    answers[item.id] = {
      selectedIndex: item.selected_index,
      selectedIndexes: [...persistedIndexes],
      text: item.user_answer || '',
    }
    saveState[item.id] = 'idle'
    timeSpent[item.id] = Number(exam.time_spent?.[item.id] || 0)
  }
  const firstUnanswered = exam.items.findIndex((it) => !isAnswered(it.id))
  index.value = firstUnanswered >= 0 ? firstUnanswered : 0
  itemEnteredAt.value = Date.now()
  remaining.value = exam.remaining_seconds ?? exam.duration_minutes * 60
  startTimer()
}

let timer: ReturnType<typeof setInterval> | null = null
function startTimer() {
  stopTimer()
  timer = setInterval(() => {
    if (remaining.value <= 0) return
    remaining.value -= 1
    if (remaining.value === 0) {
      void autoSubmit()
    }
  }, 1000)
}
function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

/** 离开答题器/学习模式时暂停计时，避免「后台继续倒计时」的不公平。 */
function pauseCurrentExam() {
  const exam = study.mockExam
  if (!exam || submitting.value || view.value !== 'taking' || exam.status !== 'in_progress') return
  stopTimer()
  void study.pauseMockExam(exam.id).catch(() => {
    /* 网络失败不阻断离开页面；下次进入仍会按 started_at 计时 */
  })
}

const remainingLabel = computed(() => {
  const s = Math.max(0, remaining.value)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(sec).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
})
const lowTime = computed(() => remaining.value > 0 && remaining.value <= 300)

const debounceTimers: Record<string, ReturnType<typeof setTimeout>> = {}
function queueSave(itemId: string) {
  saveState[itemId] = 'saving'
  if (debounceTimers[itemId]) clearTimeout(debounceTimers[itemId])
  debounceTimers[itemId] = setTimeout(() => {
    void persistAnswer(itemId)
  }, 600)
}

async function persistAnswer(itemId: string, keepState = false) {
  if (!currentExamId.value) return
  const a = answers[itemId]
  if (!a) return
  try {
    await study.saveMockAnswer(currentExamId.value, itemId, {
      selectedIndex: a.selectedIndex,
      selectedIndexes: a.selectedIndexes,
      text: a.text,
      timeSpentSeconds: Math.round(timeSpent[itemId] || 0),
    })
    if (!keepState) saveState[itemId] = 'saved'
  } catch (e: any) {
    saveState[itemId] = 'idle'
    if (String(e.message || '').includes('时间已到')) {
      await autoSubmit()
    }
  }
}

async function flushAll() {
  const dirty = Object.keys(debounceTimers)
  for (const itemId of dirty) {
    clearTimeout(debounceTimers[itemId])
    delete debounceTimers[itemId]
    await persistAnswer(itemId, true)
  }
}

function accumulateTime() {
  const it = currentItem.value
  if (it) {
    const elapsed = (Date.now() - itemEnteredAt.value) / 1000
    timeSpent[it.id] = (timeSpent[it.id] || 0) + elapsed
  }
  itemEnteredAt.value = Date.now()
}

function goTo(i: number) {
  if (i < 0 || i >= examItems.value.length) return
  accumulateTime()
  const prev = currentItem.value
  if (prev && debounceTimers[prev.id]) {
    clearTimeout(debounceTimers[prev.id])
    delete debounceTimers[prev.id]
    void persistAnswer(prev.id, true)
  }
  index.value = i
  itemEnteredAt.value = Date.now()
}

function chooseOption(i: number) {
  const it = currentItem.value
  if (!it) return
  const a = answers[it.id]
  if (currentIsMulti.value) {
    const pos = a.selectedIndexes.indexOf(i)
    if (pos >= 0) a.selectedIndexes.splice(pos, 1)
    else a.selectedIndexes.push(i)
    a.selectedIndexes.sort((x, y) => x - y)
  } else {
    a.selectedIndex = i
  }
  queueSave(it.id)
}

function onTextInput() {
  const it = currentItem.value
  if (!it) return
  queueSave(it.id)
}

function toggleFlag() {
  const it = currentItem.value
  if (!it) return
  if (flagged.has(it.id)) flagged.delete(it.id)
  else flagged.add(it.id)
}

const answeredCount = computed(() => answeredItemIds.value.size)

async function doSubmit() {
  confirmSubmit.value = false
  if (!currentExamId.value || submitting.value) return
  submitting.value = true
  accumulateTime()
  try {
    await flushAll()
    await study.submitMockExam(currentExamId.value)
    stopTimer()
    toast.success('已交卷，正在批阅')
    const examId = currentExamId.value
    // 等后台批阅完成
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 3000))
      try {
        const detail = await study.loadMockExam(examId)
        if (detail && detail.status === 'graded') {
          await openReport(examId)
          return
        }
        if (detail && detail.status === 'error') {
          toast.error(detail.error || '批阅失败')
          view.value = 'list'
          return
        }
      } catch {
        /* 继续等待 */
      }
    }
    toast.info('批阅仍在进行，可稍后在列表查看报告')
    view.value = 'list'
  } catch (e: any) {
    toast.error(e.message || '交卷失败')
  } finally {
    submitting.value = false
  }
}

async function autoSubmit() {
  if (submitting.value) return
  stopTimer()
  await doSubmit()
}

function questionLabel(type: string) {
  return QUESTION_TYPE_LABEL[type as QuestionType] || '题目'
}

const optionLetter = (i: number) => String.fromCharCode(65 + i)

// ---------- 报告 ----------
const report = computed(() => study.mockReport)
const expandedItem = ref<string | null>(null)

function fmtScore(v: number | null | undefined) {
  if (v === null || v === undefined) return '—'
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

function pct(v: number) {
  return Math.round((v || 0) * 100)
}

function fmtMinutes(sec: number | undefined) {
  if (!sec) return '0 分钟'
  return `${Math.round(sec / 60)} 分钟`
}

function itemCorrectOption(it: MockExamItem) {
  return new Set(it.correct_indexes?.length ? it.correct_indexes : it.correct_index !== null && it.correct_index >= 0 ? [it.correct_index] : [])
}
function itemChosen(it: MockExamItem) {
  if (it.selected_indexes?.length) return new Set(it.selected_indexes)
  return new Set(it.selected_index !== null && it.selected_index >= 0 ? [it.selected_index] : [])
}

onMounted(async () => {
  if (!study.templates.length) await study.loadTemplates()
  await refreshList()
  if (study.templates.length) createTemplateId.value = study.templates[0].id
})

onBeforeUnmount(() => {
  pauseCurrentExam()
  clearPoll()
  for (const t of Object.values(debounceTimers)) clearTimeout(t)
})
</script>

<template>
  <div class="animate-fade-up">
    <!-- ================= 列表 ================= -->
    <template v-if="view === 'list'">
      <div class="flex items-center justify-between mb-5">
        <div class="flex items-center gap-2.5">
          <span class="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-400 to-violet-600 text-white grid place-items-center shadow-sm">
            <KiwiIcon name="book" :size="16" />
          </span>
          <div>
            <h3 class="font-semibold text-slate-800">仿真考试</h3>
            <p class="text-xs text-slate-400">按考试模板整卷组题 · 计时作答 · 交卷后分维度批阅</p>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button class="kiwi-btn-ghost !text-xs !py-1.5" @click="showTemplates = true">
            <KiwiIcon name="settings" :size="13" />
            模板
          </button>
          <button class="kiwi-btn-ghost !text-xs !py-1.5" title="刷新" @click="refreshList">
            <KiwiIcon name="refresh" :size="14" />
          </button>
          <button
            v-if="!llmMissing"
            class="kiwi-btn-primary !py-2"
            @click="showCreate = true"
          >
            <KiwiIcon name="plus" :size="14" />
            新建试卷
          </button>
          <button
            v-else
            class="kiwi-btn-primary !py-2"
            @click="router.push('/settings/models')"
          >
            <KiwiIcon name="settings" :size="14" />
            去配置模型
          </button>
        </div>
      </div>

      <!-- 桌面版未配置模型 -->
      <div
        v-if="llmMissing"
        class="mb-4 flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3"
      >
        <KiwiIcon name="alert" :size="15" class="mt-0.5 shrink-0 text-amber-500" />
        <p class="text-[12px] leading-relaxed text-amber-700">
          桌面版尚未配置大模型，无法按模板组卷或批阅主观题。已有试卷仍可查看；配置模型后即可新建与批阅。
        </p>
      </div>

      <!-- 新建试卷 -->
      <div v-if="showCreate" class="kiwi-card p-5 mb-4 animate-fade-in">
        <div class="flex items-center justify-between mb-3">
          <p class="text-sm font-semibold text-slate-700">新建仿真试卷</p>
          <button class="kiwi-btn-ghost !p-1" @click="showCreate = false">
            <KiwiIcon name="close" :size="14" />
          </button>
        </div>
        <div class="grid md:grid-cols-2 gap-3">
          <select v-model="createTemplateId" class="kiwi-input text-sm">
            <option v-for="t in templateOptions" :key="t.id" :value="t.id">
              {{ t.name }} · {{ t.duration_minutes }} 分钟
            </option>
            <option v-if="!templateOptions.length" value="">暂无可用模板</option>
          </select>
          <input v-model="createTitle" class="kiwi-input text-sm" placeholder="试卷标题（可选）" />
        </div>
        <div v-if="selectedTemplate" class="mt-3 rounded-xl bg-slate-50/80 border border-slate-200/60 p-3.5">
          <p class="text-xs text-slate-600 mb-1.5">{{ selectedTemplate.description }}</p>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="s in selectedTemplate.question_types"
              :key="s.type + s.name"
              class="px-2 py-0.5 rounded bg-white border border-slate-200 text-[10px] text-slate-500"
            >
              {{ s.name || QUESTION_TYPE_LABEL[s.type] }} {{ s.count }} 题 × {{ s.score }} 分
            </span>
            <span class="px-2 py-0.5 rounded bg-white border border-slate-200 text-[10px] text-slate-500">
              及格 {{ selectedTemplate.passing_criteria?.total ?? '—' }} 分
            </span>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-4">
          <button class="kiwi-btn-secondary !py-2" @click="showCreate = false">取消</button>
          <button
            class="kiwi-btn-primary !py-2"
            :disabled="!createTemplateId || creating"
            @click="createExam"
          >
            <KiwiIcon v-if="creating" name="loader" :size="14" spin />
            <KiwiIcon v-else name="play" :size="14" />
            开始组卷
          </button>
        </div>
      </div>

      <!-- 试卷列表 -->
      <div v-if="study.mockExamsLoading && !study.mockExams.length" class="space-y-2.5">
        <div v-for="i in 3" :key="i" class="kiwi-card p-4 h-20 animate-pulse bg-slate-100/50" />
      </div>

      <KiwiEmpty
        v-else-if="!study.mockExams.length"
        icon="book"
        title="还没有仿真试卷"
        desc="选择一套考试模板（软考高项/中项、PMP 或自定义），系统会从知识库按题型和难度组卷"
      >
        <button class="kiwi-btn-primary" @click="showCreate = true">
          <KiwiIcon name="plus" :size="14" />
          新建试卷
        </button>
      </KiwiEmpty>

      <div v-else class="space-y-2.5">
        <div
          v-for="exam in study.mockExams"
          :key="exam.id"
          class="kiwi-card p-4 hover:border-kiwi-200 transition-colors cursor-pointer"
          @click="exam.status !== 'generating' && enterExam(exam.id)"
        >
          <div class="flex items-center gap-3">
            <span
              class="w-10 h-10 shrink-0 rounded-xl grid place-items-center"
              :class="exam.status === 'graded' ? 'bg-emerald-50 text-emerald-600' : 'bg-violet-50 text-violet-600'"
            >
              <KiwiIcon :name="exam.status === 'graded' ? 'checkSquare' : 'book'" :size="18" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 flex-wrap">
                <p class="text-sm font-medium text-slate-700 truncate">{{ exam.title }}</p>
                <span class="px-1.5 py-0.5 rounded text-[10px] font-medium" :class="STATUS_META[exam.status]?.cls">
                  {{ STATUS_META[exam.status]?.label || exam.status }}
                </span>
              </div>
              <p class="text-[11px] text-slate-400 mt-1">
                {{ exam.question_count }} 题 · {{ exam.duration_minutes }} 分钟 · 满分 {{ fmtScore(exam.max_score) }}
                <template v-if="exam.passing_score !== null"> · 及格 {{ fmtScore(exam.passing_score) }}</template>
                <template v-if="exam.status === 'graded' && exam.total_score !== null">
                  · 得分 <span class="text-slate-700 font-medium">{{ fmtScore(exam.total_score) }}</span>
                </template>
                · {{ fmtDate(exam.created_at) }}
              </p>
              <div v-if="exam.status === 'generating'" class="mt-2">
                <div class="h-1.5 rounded-full bg-slate-200/60 overflow-hidden">
                  <div
                    class="h-full rounded-full bg-gradient-to-r from-violet-400 to-violet-600 transition-all duration-500"
                    :style="{ width: `${Math.round(exam.generation_progress * 100)}%` }"
                  />
                </div>
                <p class="text-[10px] text-slate-400 mt-1">
                  正在组卷 {{ Math.round(exam.generation_progress * 100) }}%，可离开此页面
                </p>
              </div>
              <p v-if="exam.status === 'error'" class="text-[11px] text-rose-500 mt-1 line-clamp-2">
                {{ exam.error }}
              </p>
            </div>
            <div class="shrink-0 flex items-center gap-1.5" @click.stop>
              <button
                v-if="exam.status === 'ready'"
                class="kiwi-btn-primary !px-3 !py-1.5 !text-xs"
                @click="enterExam(exam.id)"
              >
                开始考试
              </button>
              <button
                v-else-if="exam.status === 'in_progress'"
                class="kiwi-btn-primary !px-3 !py-1.5 !text-xs"
                @click="enterExam(exam.id)"
              >
                继续作答
              </button>
              <button
                v-else-if="exam.status === 'graded'"
                class="kiwi-btn-secondary !px-3 !py-1.5 !text-xs"
                @click="openReport(exam.id)"
              >
                查看报告
              </button>
              <button
                v-else-if="exam.status === 'error'"
                class="kiwi-btn-secondary !px-3 !py-1.5 !text-xs"
                @click="retryExam(exam.id)"
              >
                <KiwiIcon name="refresh" :size="12" />
                重试
              </button>
              <span
                v-else-if="exam.status === 'grading'"
                class="text-[11px] text-violet-500 flex items-center gap-1"
              >
                <KiwiIcon name="loader" :size="13" spin />
                批阅中
              </span>
              <button
                v-if="exam.status !== 'generating'"
                class="kiwi-btn-ghost !p-1.5 text-slate-400 hover:text-rose-500"
                title="删除试卷"
                @click="removeExam(exam.id)"
              >
                <KiwiIcon name="trash" :size="14" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ================= 考前说明 ================= -->
    <template v-else-if="view === 'intro' && study.mockExam">
      <div class="flex items-center justify-between mb-5">
        <button class="kiwi-btn-ghost !text-xs !py-1.5" @click="backToList">
          <KiwiIcon name="arrowLeft" :size="14" />
          返回列表
        </button>
      </div>
      <div class="max-w-xl mx-auto kiwi-card p-7 text-center">
        <div class="mx-auto w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-400 to-violet-600 text-white grid place-items-center shadow-glow mb-4">
          <KiwiIcon name="book" :size="26" />
        </div>
        <h3 class="text-lg font-semibold text-slate-800">{{ study.mockExam.title }}</h3>
        <p class="text-xs text-slate-400 mt-1">
          {{ study.mockExam.template?.name || '自定义试卷' }} · {{ study.mockExam.duration_minutes }} 分钟
        </p>

        <div class="grid grid-cols-3 gap-3 my-6">
          <div class="rounded-xl bg-slate-50/80 border border-slate-200/60 py-3">
            <p class="text-xl font-bold text-slate-800 tabular-nums">{{ study.mockExam.question_count }}</p>
            <p class="text-[11px] text-slate-400 mt-0.5">题目数量</p>
          </div>
          <div class="rounded-xl bg-slate-50/80 border border-slate-200/60 py-3">
            <p class="text-xl font-bold text-slate-800 tabular-nums">{{ fmtScore(study.mockExam.max_score) }}</p>
            <p class="text-[11px] text-slate-400 mt-0.5">试卷满分</p>
          </div>
          <div class="rounded-xl bg-slate-50/80 border border-slate-200/60 py-3">
            <p class="text-xl font-bold text-slate-800 tabular-nums">
              {{ fmtScore(study.mockExam.passing_score) }}
            </p>
            <p class="text-[11px] text-slate-400 mt-0.5">及格分数</p>
          </div>
        </div>

        <div
          v-if="study.mockExam.template?.assembly_warnings?.length"
          class="text-left rounded-xl bg-rose-50/70 border border-rose-100 p-4 mb-4"
        >
          <p class="text-xs font-medium text-rose-700 mb-1.5 flex items-center gap-1">
            <KiwiIcon name="alert" :size="12" />
            组卷提示
          </p>
          <ul class="text-[11px] text-rose-700/80 space-y-1 leading-relaxed">
            <li v-for="(w, i) in study.mockExam.template.assembly_warnings" :key="i">· {{ w }}</li>
          </ul>
          <p
            v-if="study.mockExam.template?.coverage_check?.coverage_ratio !== null && study.mockExam.template?.coverage_check?.coverage_ratio !== undefined"
            class="text-[10px] text-rose-500/70 mt-1.5"
          >
            大纲知识域覆盖 {{ pct(study.mockExam.template.coverage_check.coverage_ratio) }}%
            （{{ study.mockExam.template.coverage_check.covered_domains.join('、') || '无' }}
            / {{ study.mockExam.template.coverage_check.requested_domains.join('、') }}）
          </p>
        </div>

        <div class="text-left rounded-xl bg-amber-50/70 border border-amber-100 p-4 mb-6">
          <p class="text-xs font-medium text-amber-700 mb-1.5 flex items-center gap-1">
            <KiwiIcon name="alert" :size="12" />
            考试须知
          </p>
          <ul class="text-[11px] text-amber-700/80 space-y-1 leading-relaxed">
            <li>· 时间结束自动交卷；中途切换到编辑模式会自动暂停计时，返回后继续。</li>
            <li>· 作答会自动保存；切换题目、刷新页面后可从「继续作答」恢复。</li>
            <li>· 主观题按评分维度由教练批阅，交卷后可能需要一到两分钟。</li>
            <li>· 考试结果会更新知识点掌握度，并自动生成错题与复习计划。</li>
          </ul>
        </div>

        <button class="kiwi-btn-primary px-8" @click="startExam">
          <KiwiIcon name="play" :size="15" />
          开始考试
        </button>
      </div>
    </template>

    <!-- ================= 答题 ================= -->
    <template v-else-if="view === 'taking' && study.mockExam">
      <!-- 顶栏：计时 + 进度 + 交卷 -->
      <div class="sticky top-0 z-20 -mx-1 px-1 py-3 mb-3 bg-gradient-to-b from-white/95 to-white/70 backdrop-blur-md">
        <div class="flex items-center gap-3 flex-wrap">
          <button class="kiwi-btn-ghost !text-xs !py-1.5" @click="backToList">
            <KiwiIcon name="arrowLeft" :size="13" />
            离开
          </button>
          <div class="min-w-0">
            <p class="text-sm font-medium text-slate-700 truncate max-w-xs">{{ study.mockExam.title }}</p>
            <p class="text-[10px] text-slate-400">
              已答 {{ answeredCount }} / {{ examItems.length }} 题
            </p>
          </div>
          <div class="flex-1" />
          <div
            class="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border tabular-nums"
            :class="
              lowTime
                ? 'border-rose-200 bg-rose-50 text-rose-600 animate-pulse'
                : 'border-slate-200/70 bg-white/80 text-slate-600'
            "
          >
            <KiwiIcon name="clock" :size="14" />
            <span class="text-sm font-semibold">{{ remainingLabel }}</span>
          </div>
          <button class="kiwi-btn-primary !py-2" :disabled="submitting" @click="confirmSubmit = true">
            <KiwiIcon v-if="submitting" name="loader" :size="14" spin />
            <KiwiIcon v-else name="send" :size="14" />
            交卷
          </button>
        </div>
        <!-- 题号导航 -->
        <div class="flex gap-1.5 mt-2.5 overflow-x-auto pb-1">
          <button
            v-for="(it, i) in examItems"
            :key="it.id"
            class="w-7 h-7 shrink-0 rounded-lg text-[11px] font-medium border transition-all relative"
            :class="
              i === index
                ? 'border-kiwi-500 bg-kiwi-500 text-white shadow-sm'
                : answeredItemIds.has(it.id)
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : 'border-slate-200 bg-white text-slate-400 hover:border-kiwi-300'
            "
            :title="`第 ${i + 1} 题 · ${it.section_name}`"
            @click="goTo(i)"
          >
            {{ i + 1 }}
            <span
              v-if="flagged.has(it.id)"
              class="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-amber-400 border border-white"
            />
          </button>
        </div>
      </div>

      <div v-if="currentItem" class="max-w-3xl mx-auto">
        <div class="flex items-center justify-between mb-2 px-1">
          <span class="text-[11px] text-slate-400">
            第 {{ index + 1 }} 题 / {{ examItems.length }} · {{ currentItem.section_name }} ·
            {{ currentItem.score }} 分
          </span>
          <div class="flex items-center gap-2">
            <span class="text-[10px]" :class="saveState[currentItem.id] === 'saved' ? 'text-emerald-500' : 'text-slate-300'">
              {{ saveState[currentItem.id] === 'saving' ? '保存中…' : saveState[currentItem.id] === 'saved' ? '已自动保存' : '未保存' }}
            </span>
            <button
              class="kiwi-btn-ghost !text-[11px] !py-1"
              :class="flagged.has(currentItem.id) ? 'text-amber-600' : 'text-slate-400'"
              @click="toggleFlag"
            >
              <KiwiIcon name="star" :size="12" />
              {{ flagged.has(currentItem.id) ? '已标记' : '标记待查' }}
            </button>
          </div>
        </div>

        <div class="kiwi-card p-6">
          <!-- 材料 -->
          <div
            v-if="currentItem.material"
            class="mb-4 rounded-xl border border-slate-200/70 bg-slate-50/70 px-4 py-3 max-h-60 overflow-y-auto"
          >
            <p class="text-[11px] font-medium text-slate-400 mb-1.5">材料</p>
            <p class="text-[13px] text-slate-600 leading-relaxed whitespace-pre-wrap">{{ currentItem.material }}</p>
          </div>

          <p class="text-[15px] leading-relaxed text-slate-800 mb-4 whitespace-pre-wrap">
            {{ currentItem.question }}
          </p>

          <div v-if="currentItem.requirements" class="mb-4 rounded-lg bg-kiwi-50/70 border border-kiwi-100 px-3.5 py-2.5">
            <p class="text-[11px] font-medium text-kiwi-600 mb-0.5">作答要求</p>
            <p class="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">{{ currentItem.requirements }}</p>
          </div>

          <!-- 选择题 -->
          <div v-if="currentIsChoice" class="space-y-2.5">
            <button
              v-for="(opt, i) in currentItem.options"
              :key="i"
              class="w-full flex items-center gap-3 text-left px-4 py-3 rounded-xl border transition-all duration-200"
              :class="
                (currentIsMulti
                  ? answers[currentItem.id].selectedIndexes.includes(i)
                  : answers[currentItem.id].selectedIndex === i)
                  ? 'border-kiwi-400 bg-kiwi-50/60 shadow-soft'
                  : 'border-slate-200/80 bg-white/70 hover:border-kiwi-200'
              "
              @click="chooseOption(i)"
            >
              <span
                class="w-7 h-7 shrink-0 grid place-items-center rounded-lg text-xs font-semibold"
                :class="
                  (currentIsMulti
                    ? answers[currentItem.id].selectedIndexes.includes(i)
                    : answers[currentItem.id].selectedIndex === i)
                    ? 'bg-gradient-to-br from-kiwi-500 to-kiwi-700 text-white'
                    : 'bg-slate-100 text-slate-500'
                "
              >
                {{ optionLetter(i) }}
              </span>
              <span class="text-sm flex-1 leading-relaxed text-slate-600">{{ opt }}</span>
              <span
                v-if="currentIsMulti"
                class="w-4 h-4 rounded border grid place-items-center shrink-0"
                :class="
                  answers[currentItem.id].selectedIndexes.includes(i)
                    ? 'border-kiwi-400 bg-kiwi-500 text-white'
                    : 'border-slate-300'
                "
              >
                <KiwiIcon
                  v-if="answers[currentItem.id].selectedIndexes.includes(i)"
                  name="check"
                  :size="10"
                />
              </span>
            </button>
          </div>

          <!-- 填空 -->
          <input
            v-else-if="currentIsFill"
            v-model="answers[currentItem.id].text"
            class="kiwi-input"
            placeholder="输入答案"
            @input="onTextInput"
          />

          <!-- 主观题 -->
          <div v-else-if="currentIsSubjective">
            <textarea
              v-model="answers[currentItem.id].text"
              rows="9"
              class="kiwi-input resize-y leading-relaxed text-sm"
              placeholder="在这里作答。建议先列要点，再展开论述。"
              @input="onTextInput"
            />
            <div class="flex justify-between mt-1.5 px-0.5 text-[11px] text-slate-400">
              <span>字数 {{ answers[currentItem.id].text.trim().length }}</span>
              <span v-if="currentItem.min_words">建议不少于 {{ currentItem.min_words }} 字</span>
            </div>
          </div>

          <!-- 上一题 / 下一题 -->
          <div class="flex items-center justify-between mt-6">
            <button class="kiwi-btn-secondary !py-2" :disabled="index === 0" @click="goTo(index - 1)">
              <KiwiIcon name="arrowLeft" :size="14" />
              上一题
            </button>
            <span class="text-[11px] text-slate-400">
              {{ questionLabel(currentItem.section_type) }}
            </span>
            <button
              v-if="index < examItems.length - 1"
              class="kiwi-btn-primary !py-2"
              @click="goTo(index + 1)"
            >
              下一题
              <KiwiIcon name="arrowRight" :size="14" />
            </button>
            <button v-else class="kiwi-btn-primary !py-2" @click="confirmSubmit = true">
              交卷
              <KiwiIcon name="send" :size="14" />
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- ================= 报告 ================= -->
    <template v-else-if="view === 'report' && report">
      <div class="flex items-center justify-between mb-5">
        <button class="kiwi-btn-ghost !text-xs !py-1.5" @click="backToList">
          <KiwiIcon name="arrowLeft" :size="14" />
          返回列表
        </button>
        <div class="flex items-center gap-2">
          <button
            class="kiwi-btn-ghost !text-xs !py-1.5"
            :disabled="!report.exam_id"
            @click="retakeExam(report.exam_id)"
          >
            <KiwiIcon name="refresh" :size="13" />
            按原模板重做
          </button>
          <button class="kiwi-btn-ghost !text-xs !py-1.5" @click="emit('practice-weak')">
            <KiwiIcon name="target" :size="13" />
            针对薄弱点训练
          </button>
        </div>
      </div>

      <div class="max-w-4xl mx-auto space-y-4">
        <!-- 成绩头 -->
        <div class="kiwi-card p-6 relative overflow-hidden">
          <div class="absolute -right-8 -top-8 w-40 h-40 rounded-full bg-gradient-to-br from-violet-100/70 to-kiwi-100/40 blur-2xl pointer-events-none" />
          <div class="flex items-center gap-6 flex-wrap relative">
            <div class="text-center">
              <p class="text-4xl font-bold tabular-nums" :class="report.passed === false ? 'text-rose-500' : 'text-slate-800'">
                {{ fmtScore(report.total_score) }}
              </p>
              <p class="text-[11px] text-slate-400 mt-0.5">总分 / {{ fmtScore(report.max_score) }}</p>
            </div>
            <div class="h-12 w-px bg-slate-200/70 hidden sm:block" />
            <div class="flex-1 min-w-[200px]">
              <div class="flex items-center gap-2 mb-1.5">
                <h3 class="font-semibold text-slate-800">{{ report.title }}</h3>
                <span
                  v-if="report.passed !== null"
                  class="px-2 py-0.5 rounded-full text-[10px] font-semibold"
                  :class="report.passed ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'"
                >
                  {{ report.passed ? '通过' : '未通过' }}
                </span>
              </div>
              <p class="text-xs text-slate-400">
                正确率 {{ pct(report.accuracy) }}%
                <template v-if="report.passing_score !== null"> · 及格线 {{ fmtScore(report.passing_score) }}</template>
                · 用时 {{ report.time_analysis?.used_minutes ?? 0 }} / {{ report.time_analysis?.duration_minutes ?? '—' }} 分钟
              </p>
              <p v-if="report.advice" class="text-xs text-slate-600 leading-relaxed mt-2">
                {{ report.advice }}
              </p>
            </div>
          </div>
        </div>

        <!-- 分卷得分 -->
        <div v-if="report.sections.length" class="kiwi-card p-5">
          <p class="text-sm font-semibold text-slate-700 mb-3">分卷表现</p>
          <div class="space-y-3">
            <div v-for="s in report.sections" :key="s.name">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-xs text-slate-600 flex-1 truncate">{{ s.name }}</span>
                <span class="text-[11px] text-slate-400 tabular-nums">
                  {{ fmtScore(s.score) }} / {{ fmtScore(s.max_score) }} 分 · 正确率 {{ pct(s.accuracy) }}%
                </span>
              </div>
              <div class="h-2 rounded-full bg-slate-200/50 overflow-hidden">
                <div
                  class="h-full rounded-full transition-all duration-700"
                  :class="pct(s.accuracy) >= 70 ? 'bg-emerald-500' : pct(s.accuracy) >= 50 ? 'bg-amber-500' : 'bg-rose-500'"
                  :style="{ width: `${Math.max(2, pct(s.accuracy))}%` }"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- 知识点雷达图 -->
        <div v-if="report.knowledge_points.length" class="kiwi-card p-5">
          <p class="text-sm font-semibold text-slate-700">知识点雷达图</p>
          <KnowledgeRadar :points="report.knowledge_points" />
        </div>

        <div class="grid md:grid-cols-2 gap-4">
          <!-- 知识点 -->
          <div class="kiwi-card p-5">
            <p class="text-sm font-semibold text-slate-700 mb-3">知识点得分</p>
            <div v-if="report.knowledge_points.length" class="space-y-2.5 max-h-72 overflow-y-auto pr-1">
              <div
                v-for="kp in report.knowledge_points"
                :key="kp.slug"
                class="rounded-xl border border-slate-200/60 px-3 py-2.5"
              >
                <div class="flex items-center gap-2">
                  <span class="text-xs text-slate-600 flex-1 truncate">{{ kp.title }}</span>
                  <span class="text-[10px] text-slate-400 tabular-nums shrink-0">
                    {{ kp.correct_count }} / {{ kp.question_count }} · 掌握 {{ pct(kp.mastery) }}%
                  </span>
                </div>
                <div class="h-1.5 rounded-full bg-slate-200/50 overflow-hidden mt-1.5">
                  <div
                    class="h-full rounded-full"
                    :class="kp.accuracy >= 0.7 ? 'bg-emerald-500' : kp.accuracy >= 0.4 ? 'bg-amber-500' : 'bg-rose-500'"
                    :style="{ width: `${Math.max(2, pct(kp.accuracy))}%` }"
                  />
                </div>
              </div>
            </div>
            <p v-else class="text-xs text-slate-400">本卷未关联知识点</p>
          </div>

          <!-- 时间分析 -->
          <div class="kiwi-card p-5">
            <p class="text-sm font-semibold text-slate-700 mb-3">时间分析</p>
            <div class="space-y-2">
              <div
                v-for="(sec, name) in report.time_analysis?.per_section_seconds || {}"
                :key="name"
                class="flex items-center gap-2"
              >
                <span class="text-xs text-slate-500 flex-1 truncate">{{ name }}</span>
                <span class="text-[11px] text-slate-400 tabular-nums">{{ fmtMinutes(sec) }}</span>
              </div>
            </div>
            <div
              v-if="report.time_analysis?.anomalies?.length"
              class="mt-3 rounded-xl bg-amber-50/70 border border-amber-100 p-3"
            >
              <p class="text-[11px] font-medium text-amber-700 mb-1 flex items-center gap-1">
                <KiwiIcon name="alert" :size="11" />
                作答节奏提醒
              </p>
              <ul class="text-[10px] text-amber-700/80 space-y-0.5 leading-relaxed">
                <li v-for="(a, i) in report.time_analysis.anomalies" :key="i">· {{ a }}</li>
              </ul>
            </div>
            <div v-if="report.weak_topics.length" class="mt-3">
              <p class="text-[11px] font-medium text-slate-500 mb-1.5">薄弱知识点</p>
              <div class="flex flex-wrap gap-1.5">
                <button
                  v-for="w in report.weak_topics"
                  :key="w.slug"
                  class="px-2 py-0.5 rounded-lg bg-rose-50 border border-rose-100 text-[10px] text-rose-600 hover:bg-rose-100 transition-colors"
                  :title="`针对「${w.title}」开始专项训练`"
                  @click="practiceTopic(w.slug)"
                >
                  {{ w.title }} {{ pct(w.accuracy) }}%
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 逐题回顾 -->
        <div class="kiwi-card p-5">
          <p class="text-sm font-semibold text-slate-700 mb-3">逐题回顾</p>
          <div class="space-y-2">
            <div
              v-for="(it, i) in report.items"
              :key="it.id"
              class="rounded-xl border transition-colors"
              :class="it.correct ? 'border-emerald-200/60' : 'border-rose-200/60'"
            >
              <button
                class="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left"
                @click="expandedItem = expandedItem === it.id ? null : it.id"
              >
                <span
                  class="w-6 h-6 shrink-0 rounded-lg grid place-items-center text-[10px] font-semibold"
                  :class="it.correct ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'"
                >
                  {{ i + 1 }}
                </span>
                <span class="text-xs text-slate-600 flex-1 truncate">{{ it.question }}</span>
                <span class="text-[10px] text-slate-400 shrink-0 tabular-nums">
                  {{ fmtScore(it.score_awarded) }} / {{ fmtScore(it.score) }} 分
                </span>
                <KiwiIcon
                  name="chevron"
                  :size="13"
                  class="text-slate-400 shrink-0"
                  :class="expandedItem === it.id ? 'rotate-180' : ''"
                />
              </button>
              <div v-if="expandedItem === it.id" class="px-3.5 pb-3.5 border-t border-slate-100 pt-3 animate-fade-in">
                <p class="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap mb-2.5">{{ it.question }}</p>
                <div v-if="it.options.length" class="space-y-1.5 mb-2.5">
                  <div
                    v-for="(opt, oi) in it.options"
                    :key="oi"
                    class="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px]"
                    :class="
                      itemCorrectOption(it).has(oi)
                        ? 'bg-emerald-50 text-emerald-700'
                        : itemChosen(it).has(oi)
                          ? 'bg-rose-50 text-rose-600'
                          : 'text-slate-500'
                    "
                  >
                    <span class="font-semibold shrink-0">{{ optionLetter(oi) }}.</span>
                    <span class="flex-1">{{ opt }}</span>
                  </div>
                </div>
                <p v-if="it.user_answer && !it.options.length" class="text-[11px] text-slate-500 mb-2 whitespace-pre-wrap">
                  你的作答：{{ it.user_answer }}
                </p>
                <p
                  v-if="it.correct_answer && it.section_type === 'fill_blank'"
                  class="text-[11px] text-emerald-700 mb-2"
                >
                  参考答案：{{ it.correct_answer }}
                </p>
                <div v-if="it.dimensions?.length" class="space-y-1 mb-2">
                  <div
                    v-for="d in it.dimensions"
                    :key="d.key"
                    class="flex items-center gap-2 text-[10px] text-slate-500"
                  >
                    <span class="w-16 shrink-0">{{ d.label }}</span>
                    <div class="flex-1 h-1 rounded-full bg-slate-200/60 overflow-hidden">
                      <div
                        class="h-full rounded-full bg-kiwi-500"
                        :style="{ width: `${d.max_score ? (d.score / d.max_score) * 100 : 0}%` }"
                      />
                    </div>
                    <span class="tabular-nums shrink-0">{{ d.score }} / {{ d.max_score }}</span>
                  </div>
                </div>
                <p v-if="it.explanation" class="text-[11px] text-slate-500 leading-relaxed whitespace-pre-wrap">
                  <span class="font-medium text-slate-600">解析：</span>{{ it.explanation }}
                </p>
                <button
                  v-if="it.cite_slug"
                  class="mt-2 inline-flex items-center gap-1 text-[11px] text-kiwi-600 hover:text-kiwi-700 transition-colors"
                  @click="emit('cite', it.cite_slug)"
                >
                  <KiwiIcon name="wiki" :size="11" />
                  查看源页面{{ it.cite_title ? `：${it.cite_title}` : `：${it.cite_slug}` }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ================= 交卷确认 ================= -->
    <Teleport to="body">
      <div
        v-if="confirmSubmit"
        class="fixed inset-0 z-50 grid place-items-center bg-slate-900/30 backdrop-blur-sm"
        @click.self="confirmSubmit = false"
      >
        <div class="w-[min(92vw,380px)] rounded-2xl bg-white shadow-xl border border-slate-200 p-6 animate-fade-up">
          <h4 class="font-semibold text-slate-800 mb-1.5">确认交卷？</h4>
          <p class="text-xs text-slate-500 leading-relaxed">
            已作答 {{ answeredCount }} / {{ examItems.length }} 题。
            <template v-if="answeredCount < examItems.length">
              还有 {{ examItems.length - answeredCount }} 题未作答，交卷后将按未答计分。
            </template>
            交卷后不可再修改答案。
          </p>
          <div class="flex justify-end gap-2 mt-5">
            <button class="kiwi-btn-secondary !py-2" @click="confirmSubmit = false">继续作答</button>
            <button class="kiwi-btn-primary !py-2" :disabled="submitting" @click="doSubmit">
              <KiwiIcon v-if="submitting" name="loader" :size="14" spin />
              确认交卷
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 模板管理 -->
    <ExamTemplateManager v-if="showTemplates" @close="showTemplates = false" />
  </div>
</template>
