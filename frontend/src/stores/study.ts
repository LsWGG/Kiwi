import { defineStore } from 'pinia'
import { ref } from 'vue'
import { errorMessage, request, upload } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'

export type QuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'fill_blank'
  | 'short_answer'
  | 'case_analysis'
  | 'essay'

export interface StudyProfile {
  id: string
  kb_id: string
  goal_type: 'exam' | 'domain' | 'explore'
  level_prior: 'beginner' | 'foundation' | 'advanced'
  daily_minutes: number
  exam_template_id: string | null
  target_date: string | null
  preferred_mode: 'auto' | 'drill' | 'mock'
  topics_focus: string[]
  weak_areas: string[]
  mastery: Record<string, number>
  profile_json: Record<string, unknown>
  onboarded: boolean
  status: string
  created_at: string
  updated_at: string
}

export interface Question {
  id: string
  question: string
  question_type: QuestionType
  options: string[]
  difficulty: 'basic' | 'medium' | 'hard'
  cite_slug: string | null
  cite_page_id?: string | null
  topic_slug: string | null
  cite_title: string | null
  material: string
  requirements: string
  min_words: number | null
  web_sources: Array<{ title: string; url: string; snippet?: string; provider?: string }>
  confidence_level: 'verified' | 'unverified' | 'disputed'
  multiple: boolean
}

export interface DrillAnswerPayload {
  selectedIndex?: number
  selectedIndexes?: number[]
  text?: string
  timeMs: number
}

export interface GradingDimension {
  key: string
  label: string
  score: number
  max_score: number
  comment: string
  weight?: number
  description?: string
}

export interface AnswerResult {
  correct: boolean
  score: number
  max_score: number
  explanation: string
  cite_slug: string | null
  correct_index: number
  correct_indexes: number[]
  correct_answer: string
  selected_index: number
  selected_indexes: number[]
  user_answer: string
  question_type: QuestionType
  dimensions: GradingDimension[]
  mastery: Record<string, number>
  review_due_at?: string | null
  variant_available: boolean
  confidence_level: string
}

export interface FinishResult {
  session_id: string
  correct_count: number
  question_count: number
  accuracy: number
  mastery: Record<string, number>
  weak_topics: Array<{ slug: string; title: string; accuracy: number; mastery: number }>
  recommended_mode: 'drill' | 'mock'
  break_hint: string | null
}

export interface Mistake {
  attempt_id: string
  question_id: string | null
  question: string
  question_type: QuestionType
  options: string[]
  correct_index: number
  correct_indexes: number[]
  selected_index: number
  selected_indexes: number[]
  user_answer: string
  score: number | null
  dimensions: GradingDimension[]
  explanation: string
  cite_slug: string | null
  cite_title: string
  difficulty: string
  created_at: string
  confidence_level: string
}

export interface MasteryItem {
  slug: string
  title: string
  score: number
  domain: string
  weak: boolean
  prerequisites: string[]
  content_updated: boolean
}

export interface ReviewItem {
  slug: string
  title: string
  mastery: number
  due_at: string
  interval_days: number
  repetitions: number
  domain?: string
  content_updated?: boolean
}

export interface WeeklyDailyStat {
  date: string
  attempts: number
  correct: number
  accuracy: number
  minutes: number
}

export interface WeeklyWeakTopic {
  slug: string
  title: string
  attempts: number
  accuracy: number
  mastery: number
}

export interface WeeklyRetentionBucket {
  bucket: string
  attempts: number
  accuracy: number
}

export interface WeeklyReport {
  start: string
  end: string
  days: number
  attempts: number
  correct: number
  accuracy: number
  minutes: number
  active_days: number
  previous_attempts: number
  previous_correct: number
  previous_accuracy: number
  previous_minutes: number
  mastery_average: number
  mastery_topics: number
  weak_count: number
  daily: WeeklyDailyStat[]
  weak_topics: WeeklyWeakTopic[]
  retention: WeeklyRetentionBucket[]
}

export interface ActiveSession {
  session_id: string
  mode: StudyMode
  answered_count: number
  correct_count: number
  size: number
  /** 离开时未作答的题目；恢复会话时优先展示 */
  question?: Question | null
}

export type StudyMode = 'drill' | 'review'

/** 主观题评分维度定义（模板配置，不含单次作答得分）。 */
export interface ScoringDimension {
  key: string
  label: string
  weight?: number
  description?: string
}

export interface ExamTemplateSection {
  type: QuestionType
  name: string
  count: number
  score: number
  duration_minutes?: number
  scoring?: { dimensions?: ScoringDimension[] }
}

export interface ExamTemplate {
  id: string
  kb_id: string | null
  name: string
  code: string
  description: string
  is_builtin: boolean
  question_types: ExamTemplateSection[]
  scoring_rules: Record<string, unknown>
  passing_criteria: { total?: number; subjects?: Array<{ name: string; min_score: number }> }
  duration_minutes: number
  difficulty_distribution: Record<string, number>
  coverage_domains: string[]
  created_at: string
}

export interface MockExamSummary {
  id: string
  kb_id: string
  title: string
  status: 'generating' | 'ready' | 'in_progress' | 'grading' | 'graded' | 'error'
  duration_minutes: number
  question_count: number
  total_score: number | null
  max_score: number
  passing_score: number | null
  generation_progress: number
  error: string | null
  started_at: string | null
  submitted_at: string | null
  paused_at?: string | null
  paused_seconds?: number
  generated_at: string
  created_at: string
}

export interface MockExamItem {
  id: string
  order_index: number
  section_type: QuestionType
  section_name: string
  score: number
  question_id: string | null
  question: string
  options: string[]
  material: string
  requirements: string
  min_words: number | null
  user_answer: string
  selected_index: number | null
  selected_indexes: number[]
  score_awarded: number | null
  answered: boolean
  correct: boolean | null
  correct_index: number | null
  correct_indexes: number[]
  correct_answer: string
  explanation: string
  dimensions: GradingDimension[]
  cite_slug: string | null
  cite_title: string
  confidence_level: string
}

export interface MockExamDetail extends MockExamSummary {
  template: {
    name?: string
    code?: string
    question_types?: ExamTemplateSection[]
    passing_criteria?: { total?: number; subjects?: Array<{ name: string; min_score: number }> }
    assembly_warnings?: string[]
    partial?: boolean
    coverage_check?: {
      requested_domains: string[]
      available_domains: string[]
      covered_domains: string[]
      missing_domains: string[]
      coverage_ratio: number | null
      warnings: string[]
    }
    [key: string]: unknown
  }
  items: MockExamItem[]
  score_breakdown: Record<string, unknown>
  time_spent: Record<string, unknown>
  remaining_seconds: number | null
}

export interface MockExamReport {
  exam_id: string
  title: string
  status: string
  total_score: number | null
  max_score: number
  passing_score: number | null
  passed: boolean | null
  accuracy: number
  sections: Array<{
    name: string
    type: string
    question_count: number
    score: number
    max_score: number
    accuracy: number
  }>
  knowledge_points: Array<{
    slug: string
    title: string
    question_count: number
    correct_count: number
    score: number
    max_score: number
    accuracy: number
    mastery: number
  }>
  weak_topics: Array<{ slug: string; title: string; accuracy: number; mastery: number }>
  time_analysis: {
    duration_minutes?: number
    used_minutes?: number
    per_section_seconds?: Record<string, number>
    anomalies?: string[]
  }
  items: MockExamItem[]
  advice: string
}

export interface PlanDay {
  date: string
  mode: 'drill' | 'mock'
  minutes: number
  focus: string[]
  note: string
  adjusted?: boolean
}

export interface StudyPlan {
  phase: 'initial' | 'middle' | 'late' | 'sprint'
  suggested_mode: 'drill' | 'mock'
  coverage: number
  accuracy_trend: number
  days_to_target: number | null
  weak_topics: Array<{ slug: string; title: string; mastery: number; domain?: string }>
  week: PlanDay[]
  rationale: string
  streak_days?: number
  due_count?: number
  exam_history?: {
    count: number
    avg_rate: number | null
    latest_rate: number | null
    passed: number
    passing_known: number
  }
  computed_at: string
}

export interface LearnGraphNode {
  id: string
  slug: string
  title: string
  mastery: number
  weak: boolean
  domain: string
  page_type: string
  link_count: number
  wiki_page_id: string | null
  due?: boolean
  due_at?: string | null
  content_updated?: boolean
}

export interface LearnGraph {
  nodes: LearnGraphNode[]
  edges: Array<{ source: string; target: string; type: string; prerequisite: boolean }>
  coverage: number
}

export interface Annotation {
  id: string
  kb_id: string
  target_type: 'wiki' | 'note' | 'question'
  target_id: string
  content_md: string
  quote: string
  created_at: string
  updated_at: string
}

export interface OnboardingTurn {
  reply: string
  done: boolean
  profile_patch: Record<string, unknown>
  missing: string[]
}

export interface OnboardingMessage {
  role: 'assistant' | 'user'
  content: string
}

/** 从 Content-Disposition 提取下载文件名（兼容 RFC 5987 中文名）。 */
function ankiFilename(disposition: string | null): string {
  if (!disposition) return 'kiwi-anki.apkg'
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1]
  if (encoded) {
    try {
      return decodeURIComponent(encoded)
    } catch {
      // 非法编码时退回普通 filename / 默认文件名。
    }
  }
  return /filename="?([^";]+)"?/i.exec(disposition)?.[1] || 'kiwi-anki.apkg'
}

export const QUESTION_TYPE_LABEL: Record<QuestionType, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_blank: '填空题',
  short_answer: '简答题',
  case_analysis: '案例分析',
  essay: '论文',
}

export const useStudyStore = defineStore('study', () => {
  const kbs = useKbsStore()

  const profile = ref<StudyProfile | null>(null)
  const profileLoading = ref(false)

  const sessionId = ref<string | null>(null)
  const sessionMode = ref<StudyMode>('drill')
  const currentQuestion = ref<Question | null>(null)
  const questionLoading = ref(false)
  const lastResult = ref<AnswerResult | null>(null)
  const sessionSize = ref(10)

  const dueReviews = ref<ReviewItem[]>([])
  const dueLoading = ref(false)
  const nextDueAt = ref<string | null>(null)
  const weeklyReport = ref<WeeklyReport | null>(null)
  const weeklyLoading = ref(false)
  const activeSession = ref<ActiveSession | null>(null)

  const answered = ref<AnswerResult[]>([])
  const answeredCount = ref(0)
  const correctCount = ref(0)

  const mistakes = ref<Mistake[]>([])
  const mistakesLoading = ref(false)
  const mistakesTotal = ref(0)

  const mastery = ref<MasteryItem[]>([])
  const masteryCoverage = ref(0)
  const masteryTotal = ref(0)
  const masteryMastered = ref(0)
  const masteryLoading = ref(false)

  const templates = ref<ExamTemplate[]>([])
  const templatesLoading = ref(false)

  const mockExams = ref<MockExamSummary[]>([])
  const mockExamsLoading = ref(false)
  const mockExam = ref<MockExamDetail | null>(null)
  const mockExamLoading = ref(false)
  const mockReport = ref<MockExamReport | null>(null)

  const plan = ref<StudyPlan | null>(null)
  const planLoading = ref(false)
  const learnGraph = ref<LearnGraph | null>(null)
  const graphLoading = ref(false)

  const annotations = ref<Annotation[]>([])
  const annotationsLoading = ref(false)

  const error = ref<string | null>(null)
  const kbId = () => kbs.activeLearnKbId

  function resetSession() {
    sessionId.value = null
    sessionMode.value = 'drill'
    currentQuestion.value = null
    lastResult.value = null
    answered.value = []
    answeredCount.value = 0
    correctCount.value = 0
  }

  // ---------- 画像 ----------
  async function loadProfile() {
    if (!kbId()) return
    profileLoading.value = true
    error.value = null
    try {
      profile.value = await request<StudyProfile | null>('/study/profile', { kbId: kbId() })
    } catch (e: any) {
      error.value = e.message
    } finally {
      profileLoading.value = false
    }
  }

  async function saveProfile(data: Partial<StudyProfile>) {
    if (!kbId()) return
    error.value = null
    try {
      profile.value = await request<StudyProfile>('/study/profile', {
        method: 'PUT',
        kbId: kbId(),
        body: JSON.stringify(data),
      })
      return profile.value
    } catch (e: any) {
      error.value = e.message
      throw e
    }
  }

  // ---------- 冷启动 ----------
  async function onboardingTurn(messages: OnboardingMessage[], draft: Record<string, unknown> = {}) {
    if (!kbId()) throw new Error('未选择知识库')
    return request<OnboardingTurn>('/study/onboarding/turn', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ messages, draft }),
    })
  }

  async function completeOnboarding(
    data: Partial<StudyProfile>,
    messages: OnboardingMessage[] = [],
    quickStart = false,
  ) {
    if (!kbId()) throw new Error('未选择知识库')
    profile.value = await request<StudyProfile>('/study/onboarding/complete', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ profile: data, messages, quick_start: quickStart }),
    })
    return profile.value
  }

  // ---------- 考试模板 ----------
  async function loadTemplates() {
    if (!kbId()) return
    templatesLoading.value = true
    try {
      templates.value = await request<ExamTemplate[]>('/study/exam-templates', {
        kbId: kbId(),
      })
    } catch (e: any) {
      error.value = e.message
    } finally {
      templatesLoading.value = false
    }
  }

  async function createTemplate(payload: Partial<ExamTemplate>) {
    if (!kbId()) throw new Error('未选择知识库')
    const row = await request<ExamTemplate>('/study/exam-templates', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify(payload),
    })
    templates.value.push(row)
    return row
  }

  async function updateTemplate(id: string, payload: Partial<ExamTemplate>) {
    if (!kbId()) throw new Error('未选择知识库')
    const row = await request<ExamTemplate>(`/study/exam-templates/${id}`, {
      method: 'PATCH',
      kbId: kbId(),
      body: JSON.stringify(payload),
    })
    const idx = templates.value.findIndex((t) => t.id === id)
    if (idx >= 0) templates.value[idx] = row
    return row
  }

  async function deleteTemplate(id: string) {
    if (!kbId()) throw new Error('未选择知识库')
    await request<void>(`/study/exam-templates/${id}`, {
      method: 'DELETE',
      kbId: kbId(),
    })
    templates.value = templates.value.filter((t) => t.id !== id)
  }

  // ---------- 训练 ----------
  async function startDrill(
    mode: StudyMode = 'drill',
    questionType?: QuestionType,
    topicSlug?: string,
  ) {
    if (!kbId()) return
    questionLoading.value = true
    error.value = null
    try {
      const query = new URLSearchParams({ mode })
      if (questionType) query.set('question_type', questionType)
      if (topicSlug) query.set('topic_slug', topicSlug)
      const res = await request<{
        session_id: string
        mode: StudyMode
        size: number
        question: Question
      }>(`/study/sessions?${query.toString()}`, { method: 'POST', kbId: kbId() })
      sessionId.value = res.session_id
      sessionMode.value = res.mode || mode
      sessionSize.value = res.size || 10
      currentQuestion.value = res.question
      lastResult.value = null
      answered.value = []
      answeredCount.value = 0
      correctCount.value = 0
      activeSession.value = {
        session_id: res.session_id,
        mode: sessionMode.value,
        answered_count: 0,
        correct_count: 0,
        size: sessionSize.value,
      }
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      questionLoading.value = false
    }
  }

  async function startWeakDrill() {
    if (!kbId()) return
    questionLoading.value = true
    error.value = null
    try {
      const res = await request<{
        session_id: string
        mode: StudyMode
        size: number
        question: Question
      }>('/study/sessions/weak', { method: 'POST', kbId: kbId() })
      sessionId.value = res.session_id
      sessionMode.value = res.mode || 'drill'
      sessionSize.value = res.size || 10
      currentQuestion.value = res.question
      lastResult.value = null
      answered.value = []
      answeredCount.value = 0
      correctCount.value = 0
      activeSession.value = {
        session_id: res.session_id,
        mode: sessionMode.value,
        answered_count: 0,
        correct_count: 0,
        size: sessionSize.value,
      }
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      questionLoading.value = false
    }
  }

  async function submitAnswer(payload: {
    questionId: string
    selectedIndex?: number
    selectedIndexes?: number[]
    text?: string
    timeMs?: number
  }): Promise<AnswerResult> {
    if (!kbId() || !sessionId.value) throw new Error('训练未开始')
    error.value = null
    const res = await request<AnswerResult>(
      `/study/sessions/${sessionId.value}/answer`,
      {
        method: 'POST',
        kbId: kbId(),
        body: JSON.stringify({
          question_id: payload.questionId,
          selected_index: payload.selectedIndex ?? -1,
          selected_indexes: payload.selectedIndexes ?? [],
          text: payload.text ?? '',
          time_ms: payload.timeMs ?? 0,
        }),
      },
    ).catch((e: any) => {
      error.value = e.message
      throw e
    })
    answered.value.push(res)
    answeredCount.value++
    if (res.correct) correctCount.value++
    if (activeSession.value) {
      activeSession.value.answered_count = answeredCount.value
      activeSession.value.correct_count = correctCount.value
    }
    for (const [slug, score] of Object.entries(res.mastery || {})) {
      const item = mastery.value.find((m) => m.slug === slug)
      if (item) {
        item.score = score
        item.weak = score < 0.4
      } else {
        mastery.value.push({
          slug,
          title: slug,
          score,
          domain: '',
          weak: score < 0.4,
          prerequisites: [],
          content_updated: false,
        })
      }
    }
    void loadDueReviews()
    return res
  }

  async function finishSession(): Promise<FinishResult> {
    if (!kbId() || !sessionId.value) throw new Error('训练未开始')
    error.value = null
    const res = await request<FinishResult>(`/study/sessions/${sessionId.value}/finish`, {
      method: 'POST',
      kbId: kbId(),
    }).catch((e: any) => {
      error.value = e.message
      throw e
    })
    sessionId.value = null
    sessionMode.value = 'drill'
    currentQuestion.value = null
    activeSession.value = null
    void loadDueReviews()
    return res
  }

  async function nextQuestion(questionType?: QuestionType) {
    if (!kbId() || !sessionId.value) throw new Error('训练未开始')
    questionLoading.value = true
    error.value = null
    try {
      const query = questionType ? `?question_type=${questionType}` : ''
      currentQuestion.value = await request<Question>(
        `/study/sessions/${sessionId.value}/questions${query}`,
        { method: 'POST', kbId: kbId() },
      )
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      questionLoading.value = false
    }
  }

  /** 同知识点变式题：替换当前题目，仍需在当前会话作答 */
  async function requestVariant(questionId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    questionLoading.value = true
    try {
      currentQuestion.value = await request<Question>(
        `/study/questions/${questionId}/variant`,
        { method: 'POST', kbId: kbId() },
      )
      lastResult.value = null
      return currentQuestion.value
    } finally {
      questionLoading.value = false
    }
  }

  async function sendQuestionFeedback(
    questionId: string,
    kind: 'content' | 'grading' | 'source',
    detail = '',
  ) {
    if (!kbId()) throw new Error('未选择知识库')
    return request<{ ok: boolean; message: string }>(
      `/study/questions/${questionId}/feedback`,
      {
        method: 'POST',
        kbId: kbId(),
        body: JSON.stringify({ kind, detail }),
      },
    )
  }

  async function verifyQuestion(questionId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    const updated = await request<Question>(`/study/questions/${questionId}/verify`, {
      method: 'POST',
      kbId: kbId(),
    })
    if (currentQuestion.value?.id === updated.id) currentQuestion.value = updated
    return updated
  }

  // ---------- 今日复习 / 继续学习 ----------
  async function loadDueReviews() {
    if (!kbId()) return
    dueLoading.value = true
    try {
      const res = await request<{
        total: number
        items: ReviewItem[]
        next_due_at: string | null
      }>('/study/reviews/due', { kbId: kbId() })
      dueReviews.value = res.items
      nextDueAt.value = res.next_due_at
    } catch (e: any) {
      error.value = e.message
    } finally {
      dueLoading.value = false
    }
  }

  /** 加载最近 N 天学习报告。 */
  async function loadWeeklyReport(days = 7) {
    if (!kbId()) return
    weeklyLoading.value = true
    try {
      weeklyReport.value = await request<WeeklyReport>(
        `/study/report/weekly?days=${days}`,
        { kbId: kbId() },
      )
    } catch (e: any) {
      error.value = e.message
    } finally {
      weeklyLoading.value = false
    }
  }

  /**
   * 下载当前知识库的 Anki 牌组包。
   * ``group_by`` 与后端约定：none / type / topic。
   */
  async function exportAnki(groupBy: 'none' | 'type' | 'topic' = 'none') {
    if (!kbId()) throw new Error('未选择知识库')
    const params = new URLSearchParams({ kb_id: kbId()!, group_by: groupBy })
    const res = await fetch(`/api/study/export/anki?${params.toString()}`)
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      throw new Error(
        errorMessage(body?.detail, res.statusText || '导出 Anki 牌组失败'),
      )
    }
    return {
      blob: await res.blob(),
      filename: ankiFilename(res.headers.get('Content-Disposition')),
      count: Number(res.headers.get('X-Kiwi-Anki-Count') || 0),
    }
  }

  /** 导入 Anki `.apkg` / `.colpkg`，返回题目、跳过与媒体数量。 */
  async function importAnki(file: File) {
    if (!kbId()) throw new Error('未选择知识库')
    const form = new FormData()
    form.append('file', file)
    return upload<{
      imported: number
      skipped: number
      media_files: number
      decks: string[]
    }>('/study/import/anki', form, kbId())
  }

  async function loadActiveSession() {
    if (!kbId()) return
    try {
      activeSession.value = await request<ActiveSession | null>(
        '/study/sessions/active',
        { kbId: kbId() },
      )
    } catch {
      activeSession.value = null
    }
  }

  async function resumeSession(): Promise<boolean> {
    if (!kbId()) return false
    await loadActiveSession()
    const active = activeSession.value
    if (!active) return false
    sessionId.value = active.session_id
    sessionMode.value = active.mode
    sessionSize.value = active.size || 10
    answered.value = []
    answeredCount.value = active.answered_count
    correctCount.value = active.correct_count
    lastResult.value = null
    currentQuestion.value = null
    if (active.question) {
      currentQuestion.value = active.question
    } else {
      await nextQuestion()
    }
    return true
  }

  // ---------- 错题本 ----------
  async function loadMistakes(filters: { questionType?: string; topicSlug?: string } = {}) {
    if (!kbId()) return
    mistakesLoading.value = true
    error.value = null
    try {
      const query = new URLSearchParams({ limit: '300' })
      if (filters.questionType) query.set('question_type', filters.questionType)
      if (filters.topicSlug) query.set('topic_slug', filters.topicSlug)
      const suffix = `?${query.toString()}`
      const res = await request<{ total: number; items: Mistake[] }>(
        `/study/mistakes${suffix}`,
        { kbId: kbId() },
      )
      mistakes.value = res.items
      mistakesTotal.value = res.total
    } catch (e: any) {
      error.value = e.message
    } finally {
      mistakesLoading.value = false
    }
  }

  // ---------- 掌握度 / 图谱 / 计划 ----------
  async function loadMastery() {
    if (!kbId()) return
    masteryLoading.value = true
    error.value = null
    try {
      const res = await request<{
        items: MasteryItem[]
        coverage: number
        mastered_count: number
        total_topics: number
      }>('/study/mastery', { kbId: kbId() })
      mastery.value = res.items
      masteryCoverage.value = res.coverage
      masteryMastered.value = res.mastered_count
      masteryTotal.value = res.total_topics
    } catch (e: any) {
      error.value = e.message
    } finally {
      masteryLoading.value = false
    }
  }

  async function loadLearnGraph() {
    if (!kbId()) return
    graphLoading.value = true
    try {
      learnGraph.value = await request<LearnGraph>('/study/graph', { kbId: kbId() })
    } catch (e: any) {
      error.value = e.message
    } finally {
      graphLoading.value = false
    }
  }

  async function loadPlan() {
    if (!kbId()) return
    planLoading.value = true
    try {
      plan.value = await request<StudyPlan>('/study/plan', { kbId: kbId() })
    } catch (e: any) {
      error.value = e.message
    } finally {
      planLoading.value = false
    }
  }

  async function adjustPlan(payload: {
    date: string
    mode?: 'drill' | 'mock'
    minutes?: number
    focus?: string[]
    note?: string
    clear?: boolean
  }) {
    if (!kbId()) throw new Error('未选择知识库')
    plan.value = await request<StudyPlan>('/study/plan', {
      method: 'PATCH',
      kbId: kbId(),
      body: JSON.stringify(payload),
    })
    return plan.value
  }

  // ---------- 仿真考试 ----------
  async function loadMockExams() {
    if (!kbId()) return
    mockExamsLoading.value = true
    try {
      mockExams.value = await request<MockExamSummary[]>('/study/mock-exams', {
        kbId: kbId(),
      })
    } catch (e: any) {
      error.value = e.message
    } finally {
      mockExamsLoading.value = false
    }
  }

  async function createMockExam(templateId: string, title?: string) {
    if (!kbId()) throw new Error('未选择知识库')
    const exam = await request<MockExamSummary>('/study/mock-exams', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify({ exam_template_id: templateId, title: title || null }),
    })
    mockExams.value.unshift(exam)
    return exam
  }

  async function loadMockExam(examId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    mockExamLoading.value = true
    try {
      mockExam.value = await request<MockExamDetail>(`/study/mock-exams/${examId}`, {
        kbId: kbId(),
      })
      return mockExam.value
    } finally {
      mockExamLoading.value = false
    }
  }

  async function startMockExam(examId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    const summary = await request<MockExamSummary>(
      `/study/mock-exams/${examId}/start`,
      { method: 'POST', kbId: kbId() },
    )
    await loadMockExam(examId)
    return summary
  }

  async function saveMockAnswer(
    examId: string,
    itemId: string,
    payload: {
      selectedIndex?: number | null
      selectedIndexes?: number[]
      text?: string
      timeSpentSeconds?: number
    },
  ) {
    if (!kbId()) throw new Error('未选择知识库')
    return request<{ ok: boolean }>(`/study/mock-exams/${examId}/items/${itemId}`, {
      method: 'PATCH',
      kbId: kbId(),
      body: JSON.stringify({
        selected_index: payload.selectedIndex ?? null,
        selected_indexes: payload.selectedIndexes ?? [],
        text: payload.text ?? '',
        time_spent_seconds: payload.timeSpentSeconds ?? 0,
      }),
    })
  }

  async function pauseMockExam(examId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    return request<MockExamSummary>(`/study/mock-exams/${examId}/pause`, {
      method: 'POST',
      kbId: kbId(),
    })
  }

  async function resumeMockExam(examId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    const summary = await request<MockExamSummary>(
      `/study/mock-exams/${examId}/resume`,
      { method: 'POST', kbId: kbId() },
    )
    await loadMockExam(examId)
    return summary
  }

  async function submitMockExam(examId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    const summary = await request<MockExamSummary>(
      `/study/mock-exams/${examId}/submit`,
      { method: 'POST', kbId: kbId() },
    )
    mockExam.value = null
    return summary
  }

  async function loadMockReport(examId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    mockReport.value = await request<MockExamReport>(
      `/study/mock-exams/${examId}/report`,
      { kbId: kbId() },
    )
    return mockReport.value
  }

  async function retryMockExam(examId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    return request<MockExamSummary>(`/study/mock-exams/${examId}/retry`, {
      method: 'POST',
      kbId: kbId(),
    })
  }

  async function retakeMockExam(examId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    const exam = await request<MockExamSummary>(
      `/study/mock-exams/${examId}/retake`,
      { method: 'POST', kbId: kbId() },
    )
    mockExams.value.unshift(exam)
    return exam
  }

  async function deleteMockExam(examId: string) {
    if (!kbId()) throw new Error('未选择知识库')
    await request<void>(`/study/mock-exams/${examId}`, {
      method: 'DELETE',
      kbId: kbId(),
    })
    mockExams.value = mockExams.value.filter((e) => e.id !== examId)
    if (mockExam.value?.id === examId) mockExam.value = null
  }

  // ---------- 批注 ----------
  async function loadAnnotations(targetType?: string, targetId?: string) {
    if (!kbId()) return
    annotationsLoading.value = true
    try {
      const query = new URLSearchParams()
      if (targetType) query.set('target_type', targetType)
      if (targetId) query.set('target_id', targetId)
      const suffix = query.toString() ? `?${query.toString()}` : ''
      annotations.value = await request<Annotation[]>(`/study/annotations${suffix}`, {
        kbId: kbId(),
      })
    } catch (e: any) {
      error.value = e.message
    } finally {
      annotationsLoading.value = false
    }
  }

  async function createAnnotation(payload: {
    target_type: 'wiki' | 'note' | 'question'
    target_id: string
    content_md: string
    quote?: string
  }) {
    if (!kbId()) throw new Error('未选择知识库')
    const row = await request<Annotation>('/study/annotations', {
      method: 'POST',
      kbId: kbId(),
      body: JSON.stringify(payload),
    })
    annotations.value.unshift(row)
    return row
  }

  async function updateAnnotation(id: string, contentMd: string) {
    if (!kbId()) throw new Error('未选择知识库')
    const row = await request<Annotation>(`/study/annotations/${id}`, {
      method: 'PATCH',
      kbId: kbId(),
      body: JSON.stringify({ content_md: contentMd }),
    })
    const idx = annotations.value.findIndex((a) => a.id === id)
    if (idx >= 0) annotations.value[idx] = row
    return row
  }

  async function deleteAnnotation(id: string) {
    if (!kbId()) throw new Error('未选择知识库')
    await request<void>(`/study/annotations/${id}`, {
      method: 'DELETE',
      kbId: kbId(),
    })
    annotations.value = annotations.value.filter((a) => a.id !== id)
  }

  function resetForKb() {
    resetSession()
    profile.value = null
    mastery.value = []
    masteryCoverage.value = 0
    dueReviews.value = []
    activeSession.value = null
    templates.value = []
    mockExams.value = []
    mockExam.value = null
    mockReport.value = null
    plan.value = null
    learnGraph.value = null
    annotations.value = []
    mistakes.value = []
  }

  return {
    profile,
    profileLoading,
    sessionId,
    sessionMode,
    currentQuestion,
    questionLoading,
    lastResult,
    sessionSize,
    dueReviews,
    dueLoading,
    nextDueAt,
    weeklyReport,
    weeklyLoading,
    loadWeeklyReport,
    activeSession,
    answered,
    answeredCount,
    correctCount,
    mistakes,
    mistakesLoading,
    mistakesTotal,
    mastery,
    masteryCoverage,
    masteryTotal,
    masteryMastered,
    masteryLoading,
    templates,
    templatesLoading,
    mockExams,
    mockExamsLoading,
    mockExam,
    mockExamLoading,
    mockReport,
    plan,
    planLoading,
    learnGraph,
    graphLoading,
    annotations,
    annotationsLoading,
    error,
    loadProfile,
    saveProfile,
    onboardingTurn,
    completeOnboarding,
    loadTemplates,
    createTemplate,
    updateTemplate,
    deleteTemplate,
    startDrill,
    startWeakDrill,
    submitAnswer,
    finishSession,
    nextQuestion,
    requestVariant,
    sendQuestionFeedback,
    verifyQuestion,
    loadDueReviews,
    exportAnki,
    importAnki,
    loadActiveSession,
    resumeSession,
    loadMistakes,
    loadMastery,
    loadLearnGraph,
    loadPlan,
    adjustPlan,
    loadMockExams,
    createMockExam,
    loadMockExam,
    startMockExam,
    pauseMockExam,
    resumeMockExam,
    saveMockAnswer,
    submitMockExam,
    loadMockReport,
    retryMockExam,
    retakeMockExam,
    deleteMockExam,
    loadAnnotations,
    createAnnotation,
    updateAnnotation,
    deleteAnnotation,
    resetForKb,
  }
})
