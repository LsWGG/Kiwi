<script setup lang="ts">
// StudyView：学习模式主框架（3 栏）。
// 左：学习导航；中：冷启动/训练/仿真/图谱/计划/错题/画像；右：掌握度面板。
// 知识库切换在全局顶栏右上角，与编辑模式一致。
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useModeStore } from '@/stores/mode'
import { request } from '@/api/client'
import {
  useStudyStore,
  QUESTION_TYPE_LABEL,
  type DrillAnswerPayload,
  type FinishResult,
  type QuestionType,
  type StudyMode,
} from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import StudyProfileCard from '@/components/study/StudyProfileCard.vue'
import OnboardingChat from '@/components/study/OnboardingChat.vue'
import DrillCard from '@/components/study/DrillCard.vue'
import MasteryPanel from '@/components/study/MasteryPanel.vue'
import MistakesView from '@/components/study/MistakesView.vue'
import ReviewQueue from '@/components/study/ReviewQueue.vue'
import MockExamPanel from '@/components/study/MockExamPanel.vue'
import LearnGraphPanel from '@/components/study/LearnGraphPanel.vue'
import StudyPlanPanel from '@/components/study/StudyPlanPanel.vue'
import { toast } from '@/components/ui/toast'

const kbs = useKbsStore()
const study = useStudyStore()
const mode = useModeStore()
const router = useRouter()
const route = useRoute()

type Pane = 'review' | 'train' | 'mock' | 'graph' | 'plan' | 'mistakes' | 'profile'
const PANES: Pane[] = ['review', 'train', 'mock', 'graph', 'plan', 'mistakes', 'profile']

function paneFromQuery(): Pane {
  const raw = typeof route.query.pane === 'string' ? route.query.pane : ''
  return (PANES as string[]).includes(raw) ? (raw as Pane) : 'review'
}
const active = ref<Pane>(paneFromQuery())

// 冷启动 / 画像表单切换
const forceOnboarding = ref(false)
const profileFormMode = ref(false)

watch(active, (value) => {
  if (route.name !== 'learn' || route.query.pane === value) return
  void router.replace({ name: 'learn', query: { ...route.query, pane: value } })
})

const learnKb = computed(() => {
  const kb = kbs.kbs.find((k) => k.id === kbs.activeLearnKbId) ?? null
  // 关闭学习模式的库仅用于记录，不进入学习空间
  return kb && kb.learning_enabled !== false ? kb : null
})
const hasKb = computed(() => !!learnKb.value)
/** 有知识库但都未开启学习模式：给出针对性引导，而不是“还没选择知识库”。 */
const noLearnableKb = computed(
  () => kbs.kbs.length > 0 && !kbs.kbs.some((k) => k.learning_enabled !== false),
)
// README：知识库为空或尚无 Wiki 页面时，学习模式入口置灰并提示先导入编译。
const learnReady = computed(() => (learnKb.value?.wiki_count ?? 0) > 0)
const onboarded = computed(() => !!study.profile?.onboarded)
const showOnboarding = computed(
  () =>
    hasKb.value &&
    learnReady.value &&
    !profileFormMode.value &&
    (!onboarded.value || forceOnboarding.value),
)

const showRight = computed(
  () =>
    hasKb.value &&
    learnReady.value &&
    !showOnboarding.value &&
    ['review', 'train', 'mistakes'].includes(active.value),
)

function goEditForCompile() {
  mode.setMode('edit')
  router.push('/wiki')
}

function goKbManager() {
  mode.setMode('edit')
  router.push('/kbs')
}

// ---------- 训练 ----------
type TypeChoice = 'auto' | QuestionType
const typeChoice = ref<TypeChoice>('auto')
const trainMode = ref<StudyMode>('drill')
const finishResult = ref<FinishResult | null>(null)
const drillLoading = ref(false)
const answerLoading = ref(false)

const TYPE_OPTIONS: Array<{ value: TypeChoice; label: string; desc: string }> = [
  { value: 'auto', label: '自动轮换', desc: '按模板与掌握度混合出题' },
  { value: 'single_choice', label: '单选题', desc: '四选一，快速检验' },
  { value: 'multiple_choice', label: '多选题', desc: '选出全部正确项' },
  { value: 'true_false', label: '判断题', desc: '判断陈述正误' },
  { value: 'fill_blank', label: '填空题', desc: '回忆关键术语' },
  { value: 'short_answer', label: '简答题', desc: '要点覆盖与表达' },
  { value: 'case_analysis', label: '案例分析', desc: '定位问题并给方案' },
  { value: 'essay', label: '论文题', desc: '结构化作答，维度评分' },
]

async function startTrain(mode: StudyMode = 'drill', topicSlug?: string) {
  finishResult.value = null
  trainMode.value = mode
  drillLoading.value = true
  active.value = 'train'
  try {
    await study.startDrill(
      mode,
      typeChoice.value === 'auto' ? undefined : typeChoice.value,
      topicSlug,
    )
  } catch (e: any) {
    toast.error(e.message || '出题失败，请稍后重试')
  } finally {
    drillLoading.value = false
  }
}

/** 从 Wiki 页「针对本页发起学习」进入时，自动开始该知识点的专项训练。 */
const pendingTopicSlug = ref(
  typeof route.query.topic_slug === 'string' ? route.query.topic_slug : '',
)

async function maybeStartPendingTopic() {
  const slug = pendingTopicSlug.value
  if (!slug || !study.profile?.onboarded) return
  const queryKb = typeof route.query.kb === 'string' ? route.query.kb : ''
  if (queryKb && kbs.learnKbId !== queryKb) {
    kbs.learnKbId = queryKb
    return
  }
  pendingTopicSlug.value = ''
  await router.replace({ name: 'learn' })
  await startTrain('drill', slug)
}

async function startWeak() {
  finishResult.value = null
  drillLoading.value = true
  active.value = 'train'
  try {
    await study.startWeakDrill()
  } catch (e: any) {
    toast.error(e.message || '薄弱点训练启动失败')
  } finally {
    drillLoading.value = false
  }
}

async function resumeTraining() {
  if (drillLoading.value) return
  active.value = 'train'
  drillLoading.value = true
  finishResult.value = null
  try {
    const ok = await study.resumeSession()
    if (!ok) {
      toast.info('没有未完成的训练')
      return
    }
    trainMode.value = study.sessionMode
  } catch (e: any) {
    if (study.sessionMode === 'review' && String(e.message || '').includes('已完成')) {
      await finish()
      return
    }
    toast.error(e.message || '恢复训练失败')
  } finally {
    drillLoading.value = false
  }
}

/** 复习队列发起 */
function startFromReview(mode: StudyMode) {
  void startTrain(mode)
}

async function onAnswer(payload: DrillAnswerPayload) {
  const q = study.currentQuestion
  if (!q) return
  answerLoading.value = true
  try {
    const res = await study.submitAnswer({
      questionId: q.id,
      selectedIndex: payload.selectedIndex,
      selectedIndexes: payload.selectedIndexes,
      text: payload.text,
      timeMs: payload.timeMs,
    })
    study.lastResult = res
  } catch (e: any) {
    toast.error(e.message || '提交失败')
  } finally {
    answerLoading.value = false
  }
}

async function onNext() {
  finishResult.value = null
  if (study.answeredCount >= study.sessionSize) {
    await finish()
    return
  }
  study.lastResult = null
  study.currentQuestion = null
  try {
    await study.nextQuestion(typeChoice.value === 'auto' ? undefined : typeChoice.value)
  } catch (e: any) {
    if (study.sessionMode === 'review' && String(e.message || '').includes('已完成')) {
      await finish()
      return
    }
    toast.error(e.message || '出题失败')
  }
}

async function finish() {
  try {
    const res = await study.finishSession()
    finishResult.value = res
    await Promise.all([study.loadMastery(), study.loadDueReviews(), study.loadActiveSession()])
  } catch (e: any) {
    toast.error(e.message || '结束训练失败')
  }
}

async function onVariant() {
  const q = study.currentQuestion
  if (!q) return
  try {
    await study.requestVariant(q.id)
    toast.info('已换一道同知识点变式题')
  } catch (e: any) {
    toast.error(e.message || '变式题生成失败')
  }
}

async function onVerify() {
  const q = study.currentQuestion
  if (!q) return
  try {
    const updated = await study.verifyQuestion(q.id)
    if (study.lastResult) {
      study.lastResult = { ...study.lastResult, confidence_level: updated.confidence_level }
    }
    toast.info(
      updated.web_sources.length
        ? `已找到 ${updated.web_sources.length} 条参考来源`
        : '暂未找到可靠的联网来源',
    )
  } catch (e: any) {
    toast.error(e.message || '联网核查失败')
  }
}

async function onFeedback(kind: 'content' | 'grading' | 'source') {
  const q = study.currentQuestion
  if (!q) return
  try {
    const res = await study.sendQuestionFeedback(q.id, kind)
    toast.success(res.message || '反馈已记录')
  } catch (e: any) {
    toast.error(e.message || '反馈提交失败')
  }
}

async function openCite(slug: string) {
  if (!slug) return
  const current = study.currentQuestion
  let pageId =
    current && current.cite_slug === slug ? current.cite_page_id || null : null
  if (!pageId && kbs.activeLearnKbId) {
    try {
      const pages = await request<Array<{ id: string; slug: string }>>(
        `/wiki?q=${encodeURIComponent(slug)}`,
        { kbId: kbs.activeLearnKbId },
      )
      pageId =
        pages.find((p) => p.slug === slug)?.id ||
        pages[0]?.id ||
        null
    } catch {
      /* 回落到 Wiki 总览 */
    }
  }
  // 引用在「学习模式」内打开：Wiki 正文只读，但批注可写
  mode.setMode('learn')
  if (pageId) router.push({ name: 'wiki-page', params: { id: pageId } })
  else router.push({ name: 'wiki', query: { slug } })
}

function openWikiPage(pageId: string) {
  if (!pageId) return
  mode.setMode('learn')
  router.push({ name: 'wiki-page', params: { id: pageId } })
}

function practiceWeak() {
  active.value = 'train'
  void startWeak()
}

function practiceTopic(slug: string) {
  if (!slug) return
  void startTrain('drill', slug)
}

function onPlanStart(mode: 'drill' | 'mock') {
  if (mode === 'mock') {
    active.value = 'mock'
    return
  }
  void startTrain('drill')
}

// ---------- KB 切换 ----------
watch(
  () => kbs.activeLearnKbId,
  async (id) => {
    if (!id) return
    study.resetForKb()
    finishResult.value = null
    forceOnboarding.value = false
    profileFormMode.value = false
    active.value = paneFromQuery()
    await Promise.all([
      study.loadProfile(),
      study.loadMastery(),
      study.loadDueReviews(),
      study.loadActiveSession(),
      study.loadTemplates(),
    ])
    await maybeStartPendingTopic()
  },
  { immediate: true },
)

async function onProfileSaved() {
  profileFormMode.value = false
  forceOnboarding.value = false
  active.value = 'review'
  await Promise.all([study.loadProfile(), study.loadMastery(), study.loadDueReviews()])
  await maybeStartPendingTopic()
}

async function onOnboarded() {
  forceOnboarding.value = false
  profileFormMode.value = false
  active.value = 'review'
  await Promise.all([
    study.loadProfile(),
    study.loadMastery(),
    study.loadDueReviews(),
    study.loadActiveSession(),
  ])
  await maybeStartPendingTopic()
}

function resetOnboarding() {
  forceOnboarding.value = true
  profileFormMode.value = false
  active.value = 'profile'
}

// 左侧导航在 App 层，通过 query.pane 与主舞台同步。
// 放在所有 ref / 函数声明之后并立即执行，确保首屏 ?pane=resume 也能恢复训练。
watch(
  () => route.query.pane,
  (raw) => {
    if (typeof raw !== 'string') return
    if (raw === 'resume') {
      void resumeTraining()
      return
    }
    if ((PANES as string[]).includes(raw)) {
      active.value = raw as Pane
      profileFormMode.value = false
      forceOnboarding.value = false
    }
  },
  { immediate: true },
)

onMounted(() => {
  if (!kbs.kbs.length) kbs.fetchKbs()
})
</script>

<template>
  <div class="h-full min-h-0 flex">
    <!-- 中栏：主舞台 -->
    <main class="flex-1 min-w-0 overflow-y-auto p-6">
      <!-- 有知识库但均未开启学习模式 -->
      <KiwiEmpty
        v-if="noLearnableKb"
        icon="learn"
        title="还没有开启学习模式的知识库"
        desc="学习模式已关闭的知识库仅用于记录与检索。可在知识库管理中新建或编辑知识库时开启学习模式。"
      >
        <button class="kiwi-btn-primary" @click="goKbManager">
          <KiwiIcon name="settings" :size="14" />
          去知识库管理
        </button>
      </KiwiEmpty>

      <!-- 无知识库 -->
      <KiwiEmpty
        v-else-if="!hasKb"
        icon="wiki"
        title="还没有选择知识库"
        desc="请先在左侧选择一个知识库，或到编辑模式创建一个"
      >
        <button class="kiwi-btn-secondary" @click="kbs.fetchKbs()">
          <KiwiIcon name="refresh" :size="14" />
          刷新列表
        </button>
      </KiwiEmpty>

      <!-- 尚无 Wiki 页面：学习模式置灰引导 -->
      <KiwiEmpty
        v-else-if="!learnReady"
        icon="wiki"
        title="知识库还没有 Wiki 页面"
        desc="学习模式依赖已编译的 Wiki 页面。请先在编辑模式导入素材并完成编译，再回来开始学习。"
      >
        <button class="kiwi-btn-primary" @click="goEditForCompile">
          <KiwiIcon name="edit" :size="14" />
          去编辑模式导入并编译
        </button>
      </KiwiEmpty>

      <!-- 冷启动对话 -->
      <div v-else-if="showOnboarding" class="h-full min-h-[540px]">
        <OnboardingChat
          @done="onOnboarded"
          @open-form="profileFormMode = true"
        />
      </div>

      <!-- 画像（首次 / 编辑） -->
      <div
        v-else-if="!onboarded || active === 'profile'"
        class="max-w-3xl mx-auto"
      >
        <StudyProfileCard @saved="onProfileSaved" @re-onboard="resetOnboarding" />
      </div>

      <!-- 今日复习 -->
      <div v-else-if="active === 'review'" class="max-w-2xl mx-auto">
        <ReviewQueue @start="startFromReview" />
      </div>

      <!-- 错题本 -->
      <MistakesView
        v-else-if="active === 'mistakes'"
        @cite="openCite"
      />

      <!-- 仿真考试 -->
      <MockExamPanel
        v-else-if="active === 'mock'"
        @practice-weak="practiceWeak"
        @practice-topic="practiceTopic"
        @cite="openCite"
      />

      <!-- 学习图谱 -->
      <LearnGraphPanel
        v-else-if="active === 'graph'"
        @start-weak="startWeak"
        @open-wiki="openWikiPage"
      />

      <!-- 学习计划 -->
      <StudyPlanPanel
        v-else-if="active === 'plan'"
        @start-mode="onPlanStart"
        @open-graph="active = 'graph'"
      />

      <!-- 训练 -->
      <div v-else class="max-w-3xl mx-auto">
        <!-- 出题中 -->
        <div
          v-if="!study.currentQuestion && !finishResult && (drillLoading || study.questionLoading)"
          class="text-center py-20 animate-fade-up"
        >
          <KiwiIcon name="loader" :size="30" spin class="text-kiwi-500 mx-auto mb-4" />
          <p class="text-sm text-slate-400">正在准备题目…</p>
          <p class="text-[11px] text-slate-300 mt-1">主观题生成可能需要十几秒</p>
        </div>

        <!-- 未开始 -->
        <div v-else-if="!study.currentQuestion && !finishResult" class="animate-fade-up">
          <div class="text-center py-6">
            <div class="mx-auto w-16 h-16 rounded-3xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 grid place-items-center text-white shadow-glow mb-5">
              <KiwiIcon name="target" :size="30" />
            </div>
            <h3 class="text-lg font-semibold text-slate-800 mb-1.5">开始一组渐进式训练</h3>
            <p class="text-sm text-slate-400 max-w-sm mx-auto">
              每答一题 Kiwi 都会根据掌握度调整难度，结束后沉淀错题与复习计划。
            </p>
          </div>

          <!-- 题型选择 -->
          <div class="kiwi-card p-5">
            <p class="text-xs font-medium text-slate-500 mb-2.5">题型偏好</p>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
              <button
                v-for="t in TYPE_OPTIONS"
                :key="t.value"
                class="rounded-xl border px-3 py-2.5 text-left transition-all duration-200"
                :class="
                  typeChoice === t.value
                    ? 'border-kiwi-300 bg-kiwi-50/80'
                    : 'border-slate-200/70 bg-white/60 hover:border-kiwi-200'
                "
                @click="typeChoice = t.value"
              >
                <span
                  class="block text-xs font-medium"
                  :class="typeChoice === t.value ? 'text-kiwi-700' : 'text-slate-600'"
                >
                  {{ t.label }}
                </span>
                <span class="block text-[9px] text-slate-400 mt-0.5 leading-snug">{{ t.desc }}</span>
              </button>
            </div>

            <div class="flex flex-wrap items-center gap-2 mt-5">
              <button class="kiwi-btn-primary px-6" :disabled="drillLoading" @click="startTrain('drill')">
                <KiwiIcon v-if="drillLoading" name="loader" :size="16" spin />
                <KiwiIcon v-else name="play" :size="15" />
                开始训练（{{ study.sessionSize }} 题一组）
              </button>
              <button class="kiwi-btn-secondary" @click="startWeak">
                <KiwiIcon name="target" :size="14" />
                薄弱点专项
              </button>
              <button
                v-if="study.activeSession"
                class="kiwi-btn-ghost !text-xs"
                @click="resumeTraining"
              >
                继续上次训练（已答 {{ study.activeSession.answered_count }}）
              </button>
            </div>
          </div>

          <div class="grid sm:grid-cols-3 gap-2.5 mt-3">
            <div class="rounded-xl border border-slate-200/60 bg-white/50 px-3.5 py-3">
              <p class="text-[11px] font-medium text-slate-600 mb-0.5">自适应难度</p>
              <p class="text-[10px] text-slate-400 leading-relaxed">连续答对升难度，连续答错降难度并回顾前置知识</p>
            </div>
            <div class="rounded-xl border border-slate-200/60 bg-white/50 px-3.5 py-3">
              <p class="text-[11px] font-medium text-slate-600 mb-0.5">维度判分</p>
              <p class="text-[10px] text-slate-400 leading-relaxed">简答、案例、论文按评分维度给分并附改进建议</p>
            </div>
            <div class="rounded-xl border border-slate-200/60 bg-white/50 px-3.5 py-3">
              <p class="text-[11px] font-medium text-slate-600 mb-0.5">SM-2 复习</p>
              <p class="text-[10px] text-slate-400 leading-relaxed">按掌握度安排下次复习，到期自动进入今日队列</p>
            </div>
          </div>
        </div>

        <!-- 进行中 -->
        <div v-else-if="study.currentQuestion" class="space-y-3">
          <div class="flex items-center justify-between px-1 text-[11px] text-slate-400">
            <span class="flex items-center gap-1.5 flex-wrap">
              <span
                class="px-1.5 py-0.5 rounded text-[10px] font-medium"
                :class="
                  study.sessionMode === 'review'
                    ? 'bg-amber-100/80 text-amber-700'
                    : 'bg-kiwi-100/80 text-kiwi-700'
                "
              >
                {{ study.sessionMode === 'review' ? '复习' : '训练' }}
              </span>
              <span>{{ QUESTION_TYPE_LABEL[study.currentQuestion.question_type] || '题目' }}</span>
              <span class="text-slate-300">·</span>
              <span>第 {{ study.answeredCount + (study.lastResult ? 0 : 1) }} 题</span>
              <span class="text-slate-300">/ {{ study.sessionSize }}</span>
            </span>
            <button class="kiwi-btn-ghost !px-2 !py-1 !text-xs" @click="finish">
              结束本组
            </button>
          </div>
          <DrillCard
            :question="study.currentQuestion"
            :result="study.lastResult"
            :submitting="answerLoading"
            :is-last="study.answeredCount >= study.sessionSize"
            @answer="onAnswer"
            @next="onNext"
            @cite="openCite"
            @variant="onVariant"
            @verify="onVerify"
            @feedback="onFeedback"
          />
        </div>

        <!-- 已完成 -->
        <div v-else-if="finishResult" class="max-w-lg mx-auto text-center py-8 animate-fade-up">
          <div class="mx-auto w-16 h-16 rounded-full bg-gradient-to-br from-emerald-400 to-emerald-600 text-white grid place-items-center shadow-glow mb-5">
            <KiwiIcon name="check" :size="30" />
          </div>
          <h3 class="text-lg font-semibold text-slate-800 mb-2">本组完成</h3>
          <p class="text-4xl font-bold text-slate-800 tabular-nums mb-1">
            {{ Math.round(finishResult.accuracy * 100) }}%
          </p>
          <p class="text-sm text-slate-400 mb-4">
            答对 {{ finishResult.correct_count }} / {{ finishResult.question_count }}
          </p>

          <div
            v-if="finishResult.weak_topics.length"
            class="rounded-xl border border-amber-100 bg-amber-50/60 p-3.5 mb-4 text-left"
          >
            <p class="text-[11px] font-medium text-amber-700 mb-1.5">本组暴露的薄弱点</p>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="w in finishResult.weak_topics"
                :key="w.slug"
                class="px-2 py-0.5 rounded-lg bg-white/80 border border-amber-200/60 text-[10px] text-amber-700"
              >
                {{ w.title }} {{ Math.round(w.accuracy * 100) }}%
              </span>
            </div>
          </div>

          <p v-if="finishResult.break_hint" class="text-xs text-slate-400 mb-4">
            {{ finishResult.break_hint }}
          </p>

          <div class="flex flex-wrap gap-2 justify-center">
            <button class="kiwi-btn-secondary" @click="active = 'mistakes'">
              <KiwiIcon name="bookOpen" :size="14" />
              查看错题
            </button>
            <button
              v-if="finishResult.recommended_mode === 'mock'"
              class="kiwi-btn-secondary"
              @click="active = 'mock'"
            >
              <KiwiIcon name="book" :size="14" />
              试试仿真考试
            </button>
            <button class="kiwi-btn-primary" @click="startTrain(trainMode)">
              <KiwiIcon name="arrowRight" :size="14" />
              再来一组
            </button>
          </div>
        </div>
      </div>
    </main>

    <!-- 右栏：掌握度 -->
    <aside
      v-if="showRight"
      class="w-72 shrink-0 border-l border-slate-200/50 bg-white/40 backdrop-blur-xl p-4 overflow-y-auto"
    >
      <MasteryPanel @open-plan="active = 'plan'" @open-review="active = 'review'" />
    </aside>
  </div>
</template>
