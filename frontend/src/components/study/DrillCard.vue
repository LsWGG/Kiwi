<script setup lang="ts">
// DrillCard：单题训练卡 —— 覆盖选择/判断/多选/填空/简答/案例/论文七种题型。
// 提交后展示判分（主观题含评分维度）、解析、引用、联网来源、复习时间与反馈入口。
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type {
  Question,
  AnswerResult,
  QuestionType,
  DrillAnswerPayload,
} from '@/stores/study'
import { QUESTION_TYPE_LABEL } from '@/stores/study'
import { useKbsStore } from '@/stores/kbs'
import { request } from '@/api/client'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

interface TopicNote {
  note_id: string
  title: string
  excerpt: string
  updated_at: string
}

const props = defineProps<{
  question: Question
  result: AnswerResult | null
  submitting?: boolean
  isLast?: boolean
}>()

const emit = defineEmits<{
  (e: 'answer', payload: DrillAnswerPayload): void
  (e: 'next'): void
  (e: 'cite', slug: string): void
  (e: 'variant'): void
  (e: 'verify'): void
  (e: 'feedback', kind: 'content' | 'grading' | 'source'): void
}>()

const kbs = useKbsStore()
const selected = ref<number | null>(null)
const selectedMulti = ref<number[]>([])
const textAnswer = ref('')
const startedAt = ref(Date.now())
const showSources = ref(false)
const showFeedback = ref(false)

// 「我的笔记」：笔记中被标记为关联本知识点的块，复习时与 Wiki 原文一起辅助回忆。
const topicNotes = ref<TopicNote[]>([])
const notesLoading = ref(false)
const showNotes = ref(false)
let notesSeq = 0

async function loadTopicNotes() {
  const seq = ++notesSeq
  topicNotes.value = []
  showNotes.value = false
  const slug = props.question?.topic_slug
  const kbId = kbs.activeLearnKbId
  if (!slug || !kbId) return
  notesLoading.value = true
  try {
    const rows = await request<TopicNote[]>(
      `/study/topics/by-slug/${encodeURIComponent(slug)}/notes`,
      { kbId },
    )
    if (seq === notesSeq) topicNotes.value = rows
  } catch {
    // 知识点可能尚未生成，或没有关联笔记；不打断答题。
    if (seq === notesSeq) topicNotes.value = []
  } finally {
    if (seq === notesSeq) notesLoading.value = false
  }
}

watch(
  () => props.question?.id,
  () => {
    selected.value = null
    selectedMulti.value = []
    textAnswer.value = ''
    startedAt.value = Date.now()
    showSources.value = false
    showFeedback.value = false
    void loadTopicNotes()
  },
  { immediate: true },
)

const answered = computed(() => props.result !== null)
const qtype = computed<QuestionType>(() => props.question.question_type || 'single_choice')
const isChoice = computed(() =>
  ['single_choice', 'multiple_choice', 'true_false'].includes(qtype.value),
)
const isMulti = computed(
  () => qtype.value === 'multiple_choice' || (props.question.multiple && qtype.value !== 'true_false'),
)
const isSubjective = computed(() =>
  ['short_answer', 'case_analysis', 'essay'].includes(qtype.value),
)
const isFill = computed(() => qtype.value === 'fill_blank')

const difficultyText: Record<string, string> = { basic: '基础', medium: '进阶', hard: '挑战' }
const difficultyTone: Record<string, string> = {
  basic: 'bg-emerald-100/80 text-emerald-700',
  medium: 'bg-amber-100/80 text-amber-700',
  hard: 'bg-rose-100/80 text-rose-700',
}

const correctSet = computed(() => {
  if (!props.result) return new Set<number>()
  if (props.result.correct_indexes?.length) return new Set(props.result.correct_indexes)
  if (props.result.correct_index >= 0) return new Set([props.result.correct_index])
  return new Set<number>()
})

const chosenSet = computed(() => {
  if (props.result) {
    if (isMulti.value) {
      return new Set(
        props.result.selected_indexes?.length
          ? props.result.selected_indexes
          : selectedMulti.value,
      )
    }
    return new Set([props.result.selected_index])
  }
  return new Set(isMulti.value ? selectedMulti.value : selected.value === null ? [] : [selected.value])
})

function label(i: number) {
  return String.fromCharCode(65 + i)
}

function isCorrectOption(i: number) {
  return answered.value && correctSet.value.has(i)
}
function isWrongChosen(i: number) {
  return answered.value && chosenSet.value.has(i) && !correctSet.value.has(i)
}

function optionClass(i: number) {
  if (!answered.value) {
    return chosenSet.value.has(i)
      ? 'border-kiwi-400 bg-kiwi-50/60 shadow-soft'
      : 'border-slate-200/80 bg-white/70 hover:border-kiwi-200 hover:bg-white'
  }
  if (isCorrectOption(i)) return 'border-emerald-300 bg-emerald-50/60'
  if (isWrongChosen(i)) return 'border-rose-300 bg-rose-50/60'
  return 'border-slate-200/60 bg-white/50 opacity-60'
}

function optionBadgeClass(i: number) {
  if (!answered.value) {
    return chosenSet.value.has(i)
      ? 'bg-gradient-to-br from-kiwi-500 to-kiwi-700 text-white'
      : 'bg-slate-100 text-slate-500'
  }
  if (isCorrectOption(i)) return 'bg-emerald-500 text-white'
  if (isWrongChosen(i)) return 'bg-rose-500 text-white'
  return 'bg-slate-100 text-slate-400'
}

function choose(i: number) {
  if (answered.value || props.submitting) return
  if (isMulti.value) {
    const idx = selectedMulti.value.indexOf(i)
    if (idx >= 0) selectedMulti.value.splice(idx, 1)
    else selectedMulti.value.push(i)
  } else {
    selected.value = i
  }
}

const canSubmit = computed(() => {
  if (props.submitting) return false
  if (isChoice.value) {
    return isMulti.value ? selectedMulti.value.length > 0 : selected.value !== null
  }
  return textAnswer.value.trim().length > 0
})

const wordCount = computed(() => {
  // 中文按字计、英文按词计，近似于常见字数统计
  const raw = textAnswer.value.trim()
  if (!raw) return 0
  const cjk = (raw.match(/[一-鿿]/g) || []).length
  const words = raw
    .replace(/[一-鿿]/g, ' ')
    .split(/\s+/)
    .filter(Boolean).length
  return cjk + words
})

function submit() {
  if (!canSubmit.value) return
  const timeMs = Date.now() - startedAt.value
  emit('answer', {
    selectedIndex: isChoice.value && !isMulti.value ? selected.value ?? -1 : -1,
    selectedIndexes: isMulti.value ? [...selectedMulti.value].sort((a, b) => a - b) : [],
    text: isChoice.value ? '' : textAnswer.value,
    timeMs,
  })
}

const confidenceMeta = computed(() => {
  const level = (props.result?.confidence_level || props.question.confidence_level || 'unverified')
  if (level === 'verified') return { text: '来源已核查', cls: 'bg-emerald-100/80 text-emerald-700', icon: 'check' }
  if (level === 'disputed') return { text: '来源存疑', cls: 'bg-rose-100/80 text-rose-700', icon: 'alert' }
  return { text: '未联网核查', cls: 'bg-slate-100 text-slate-500', icon: 'globe' }
})

const sources = computed(() => props.question.web_sources || [])

const scorePct = computed(() =>
  props.result && props.result.max_score
    ? Math.round((props.result.score / props.result.max_score) * 100)
    : 0,
)

function reviewDueLabel(iso: string) {
  const d = new Date(iso)
  const diffDays = Math.round(
    (new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() -
      new Date().setHours(0, 0, 0, 0)) /
      86400000,
  )
  const time = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  if (diffDays <= 0) return `今天 ${time}`
  if (diffDays === 1) return `明天 ${time}`
  return `${d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${time}`
}

function dimensionPct(score: number, max: number) {
  return max > 0 ? Math.round((score / max) * 100) : 0
}

onBeforeUnmount(() => {
  startedAt.value = 0
})
</script>

<template>
  <div class="kiwi-card p-6 animate-fade-up">
    <!-- 顶部：题型 + 难度 + 置信度 -->
    <div class="flex items-start justify-between gap-3 mb-4">
      <div class="flex items-center gap-2.5 min-w-0">
        <span
          class="w-8 h-8 shrink-0 rounded-lg bg-gradient-to-br from-kiwi-500 to-kiwi-700 text-white grid place-items-center shadow-sm"
        >
          <KiwiIcon name="target" :size="15" />
        </span>
        <div class="min-w-0">
          <p class="text-sm font-semibold text-slate-800 truncate">
            {{ QUESTION_TYPE_LABEL[qtype] || '题目' }}
          </p>
          <p class="text-[11px] text-slate-400 truncate">
            <template v-if="qtype === 'multiple_choice'">多选 · 选出所有正确项</template>
            <template v-else-if="qtype === 'true_false'">判断 · 二选一</template>
            <template v-else-if="isFill">填空 · 按要点匹配</template>
            <template v-else-if="isSubjective">主观题 · 按评分维度判分</template>
            <template v-else>单选 · 四选一</template>
            <template v-if="question.cite_title"> · {{ question.cite_title }}</template>
          </p>
        </div>
      </div>
      <div class="flex items-center gap-1.5 shrink-0">
        <span class="px-2 py-0.5 rounded-full text-[10px] font-medium" :class="confidenceMeta.cls">
          {{ confidenceMeta.text }}
        </span>
        <span
          class="px-2.5 py-1 rounded-full text-[11px] font-medium"
          :class="difficultyTone[question.difficulty] || difficultyTone.basic"
        >
          {{ difficultyText[question.difficulty] || question.difficulty }}
        </span>
      </div>
    </div>

    <!-- 材料（主观题） -->
    <div
      v-if="question.material"
      class="mb-4 rounded-xl border border-slate-200/70 bg-slate-50/70 px-4 py-3 max-h-64 overflow-y-auto"
    >
      <p class="text-[11px] font-medium text-slate-400 mb-1.5">材料</p>
      <p class="text-[13px] text-slate-600 leading-relaxed whitespace-pre-wrap">{{ question.material }}</p>
    </div>

    <!-- 题干 -->
    <p class="text-[15px] leading-relaxed text-slate-800 mb-4 whitespace-pre-wrap">{{ question.question }}</p>

    <!-- 作答要求 -->
    <div v-if="question.requirements" class="mb-4 rounded-lg bg-kiwi-50/70 border border-kiwi-100 px-3.5 py-2.5">
      <p class="text-[11px] font-medium text-kiwi-600 mb-0.5">作答要求</p>
      <p class="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">{{ question.requirements }}</p>
    </div>

    <!-- 我的笔记：知识点关联块 -->
    <div
      v-if="notesLoading || topicNotes.length"
      class="mb-4 rounded-xl border border-amber-200/70 bg-amber-50/50 px-3.5 py-2.5"
    >
      <button
        class="flex w-full items-center gap-1.5 text-[11px] font-medium text-amber-700"
        @click="showNotes = !showNotes"
      >
        <KiwiIcon name="note" :size="12" />
        我的笔记
        <span v-if="notesLoading" class="text-[10px] font-normal text-amber-500">加载中…</span>
        <span v-else class="text-[10px] font-normal text-amber-500">
          {{ topicNotes.length }} 条关联
        </span>
        <KiwiIcon
          name="chevron"
          :size="12"
          class="ml-auto transition-transform"
          :class="showNotes ? 'rotate-180' : ''"
        />
      </button>
      <div v-if="showNotes" class="mt-2 space-y-2">
        <div
          v-for="n in topicNotes"
          :key="n.note_id"
          class="rounded-lg bg-white/70 border border-amber-100 px-3 py-2"
        >
          <p class="text-[11px] font-medium text-slate-600 truncate">{{ n.title }}</p>
          <p class="mt-1 text-[12px] leading-relaxed text-slate-600 whitespace-pre-wrap max-h-48 overflow-y-auto">
            {{ n.excerpt }}
          </p>
        </div>
      </div>
    </div>

    <!-- 选择题 / 判断题 -->
    <div v-if="isChoice" class="space-y-2.5">
      <button
        v-for="(opt, i) in question.options"
        :key="i"
        class="w-full flex items-center gap-3 text-left px-4 py-3 rounded-xl border transition-all duration-200"
        :class="optionClass(i)"
        :disabled="answered || submitting"
        @click="choose(i)"
      >
        <span
          class="w-7 h-7 shrink-0 grid place-items-center rounded-lg text-xs font-semibold transition-colors"
          :class="optionBadgeClass(i)"
        >
          {{ label(i) }}
        </span>
        <span
          class="text-sm flex-1 leading-relaxed"
          :class="
            !answered
              ? chosenSet.has(i)
                ? 'text-kiwi-800'
                : 'text-slate-600'
              : isCorrectOption(i)
                ? 'text-emerald-800'
                : isWrongChosen(i)
                  ? 'text-rose-800'
                  : 'text-slate-400'
          "
        >
          {{ opt }}
        </span>
        <template v-if="answered">
          <KiwiIcon v-if="isCorrectOption(i)" name="check" :size="17" class="text-emerald-500 shrink-0" />
          <KiwiIcon v-else-if="isWrongChosen(i)" name="close" :size="17" class="text-rose-500 shrink-0" />
        </template>
        <span
          v-else-if="isMulti"
          class="w-4 h-4 rounded border grid place-items-center shrink-0"
          :class="chosenSet.has(i) ? 'border-kiwi-400 bg-kiwi-500 text-white' : 'border-slate-300'"
        >
          <KiwiIcon v-if="chosenSet.has(i)" name="check" :size="10" />
        </span>
      </button>
    </div>

    <!-- 填空题 -->
    <div v-else-if="isFill">
      <input
        v-model="textAnswer"
        class="kiwi-input"
        placeholder="输入答案（多个答案用分号分隔）"
        :disabled="answered || submitting"
        @keydown.enter.prevent="submit"
      />
      <p v-if="answered && result!.correct_answer" class="text-xs text-slate-500 mt-2.5">
        参考答案：<span class="text-emerald-700 font-medium">{{ result!.correct_answer }}</span>
      </p>
    </div>

    <!-- 主观题 -->
    <div v-else-if="isSubjective">
      <textarea
        v-model="textAnswer"
        rows="8"
        class="kiwi-input resize-y leading-relaxed text-sm"
        placeholder="在这里作答。建议先列要点，再展开论述。"
        :disabled="answered || submitting"
      />
      <div class="flex items-center justify-between mt-1.5 px-0.5">
        <span
          class="text-[11px]"
          :class="
            question.min_words && wordCount < question.min_words
              ? 'text-amber-600'
              : 'text-slate-400'
          "
        >
          字数 {{ wordCount }}
          <template v-if="question.min_words"> / 建议不少于 {{ question.min_words }} 字</template>
        </span>
        <span class="text-[10px] text-slate-300">提交后将按评分维度给出分项得分</span>
      </div>
    </div>

    <!-- 未作答：提交 -->
    <div v-if="!answered" class="mt-5 flex justify-end">
      <button class="kiwi-btn-primary" :disabled="!canSubmit" @click="submit">
        <KiwiIcon v-if="submitting" name="loader" :size="15" spin />
        <KiwiIcon v-else name="send" :size="14" />
        提交答案
      </button>
    </div>

    <!-- 已作答：判分 + 解析 -->
    <div v-else class="mt-5 animate-fade-in">
      <!-- 结果横幅 -->
      <div
        class="flex items-center gap-2.5 px-4 py-3 rounded-xl mb-4 flex-wrap"
        :class="
          result!.correct
            ? 'bg-emerald-50/80 border border-emerald-200 text-emerald-700'
            : result!.score > 0
              ? 'bg-amber-50/80 border border-amber-200 text-amber-700'
              : 'bg-rose-50/80 border border-rose-200 text-rose-700'
        "
      >
        <KiwiIcon :name="result!.correct ? 'check' : result!.score > 0 ? 'alert' : 'close'" :size="16" />
        <span class="text-sm font-medium">
          <template v-if="result!.correct">回答正确</template>
          <template v-else-if="result!.score > 0">部分正确</template>
          <template v-else>回答错误</template>
        </span>
        <span v-if="isSubjective" class="text-xs tabular-nums">
          {{ result!.score }} / {{ result!.max_score }} 分 · {{ scorePct }}%
        </span>
        <template v-else-if="!result!.correct">
          <span class="text-xs text-slate-400 mx-1">·</span>
          <span class="text-xs text-slate-500">
            正确答案：
            <template v-if="result!.correct_indexes.length">
              {{ result!.correct_indexes.map((i) => label(i)).join('、') }}
            </template>
            <template v-else-if="result!.correct_index >= 0">{{ label(result!.correct_index) }}</template>
            <template v-else>{{ result!.correct_answer || '见解析' }}</template>
          </span>
        </template>
      </div>

      <!-- 主观题评分维度 -->
      <div v-if="result!.dimensions.length" class="mb-4 space-y-2">
        <p class="text-xs font-medium text-slate-500 flex items-center gap-1">
          <KiwiIcon name="listOrdered" :size="12" />
          评分维度
        </p>
        <div
          v-for="dim in result!.dimensions"
          :key="dim.key"
          class="rounded-lg border border-slate-200/70 bg-white/60 px-3.5 py-2.5"
        >
          <div class="flex items-center gap-2 mb-1.5">
            <span class="text-xs font-medium text-slate-700 flex-1">{{ dim.label }}</span>
            <span class="text-[11px] text-slate-400 tabular-nums">
              {{ dim.score }} / {{ dim.max_score }}
            </span>
          </div>
          <div class="h-1.5 rounded-full bg-slate-200/60 overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-500"
              :class="
                dimensionPct(dim.score, dim.max_score) >= 80
                  ? 'bg-emerald-500'
                  : dimensionPct(dim.score, dim.max_score) >= 50
                    ? 'bg-amber-500'
                    : 'bg-rose-500'
              "
              :style="{ width: `${dimensionPct(dim.score, dim.max_score)}%` }"
            />
          </div>
          <p v-if="dim.comment" class="text-[11px] text-slate-500 leading-relaxed mt-1.5">
            {{ dim.comment }}
          </p>
        </div>
      </div>

      <!-- 你作答的内容（主观题/填空题） -->
      <div v-if="result!.user_answer && !isChoice" class="mb-4">
        <p class="text-xs font-medium text-slate-500 mb-1.5">你的作答</p>
        <p class="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap rounded-lg bg-slate-50/80 border border-slate-200/60 px-3.5 py-2.5 max-h-48 overflow-y-auto">
          {{ result!.user_answer }}
        </p>
      </div>

      <!-- 解析 -->
      <div v-if="result!.explanation" class="mb-4">
        <p class="text-xs font-medium text-slate-500 mb-1.5 flex items-center gap-1">
          <KiwiIcon name="sparkle" :size="12" />
          解析
        </p>
        <p class="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">{{ result!.explanation }}</p>
      </div>

      <!-- 引用 / 来源 -->
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 mb-4 text-[11px] text-slate-400">
        <button
          v-if="result!.cite_slug || question.cite_slug"
          class="inline-flex items-center gap-1 hover:text-kiwi-600 transition-colors"
          @click="emit('cite', result!.cite_slug || question.cite_slug || '')"
        >
          <KiwiIcon name="wiki" :size="11" />
          出自：{{ question.cite_title || result!.cite_slug || question.cite_slug }}
        </button>
        <span v-if="result!.review_due_at" class="inline-flex items-center gap-1">
          <KiwiIcon name="refresh" :size="11" />
          下次复习：{{ reviewDueLabel(result!.review_due_at) }}
        </span>
      </div>

      <!-- 联网来源 -->
      <div v-if="sources.length" class="mb-4">
        <button
          class="inline-flex items-center gap-1 text-[11px] text-kiwi-600 hover:text-kiwi-700"
          @click="showSources = !showSources"
        >
          <KiwiIcon name="globe" :size="12" />
          参考来源（{{ sources.length }}）
          <KiwiIcon name="chevron" :size="12" :class="showSources ? 'rotate-180' : ''" />
        </button>
        <div v-if="showSources" class="mt-2 space-y-1.5">
          <a
            v-for="s in sources"
            :key="s.url"
            :href="s.url"
            target="_blank"
            rel="noopener noreferrer"
            class="block rounded-lg border border-slate-200/60 px-3 py-2 hover:border-kiwi-200 transition-colors"
          >
            <span class="text-xs text-slate-700 font-medium line-clamp-1">{{ s.title }}</span>
            <span class="text-[10px] text-slate-400 line-clamp-1">{{ s.url }}</span>
          </a>
        </div>
      </div>

      <!-- 操作区 -->
      <div class="flex flex-wrap items-center gap-2">
        <button
          v-if="sources.length === 0 && result!.confidence_level !== 'verified'"
          class="kiwi-btn-ghost !text-xs !py-1.5"
          title="用联网搜索核对本题来源"
          @click="emit('verify')"
        >
          <KiwiIcon name="globe" :size="13" />
          联网核查
        </button>
        <button
          v-if="result!.variant_available"
          class="kiwi-btn-ghost !text-xs !py-1.5"
          title="同一知识点换一道变式题"
          @click="emit('variant')"
        >
          <KiwiIcon name="refresh" :size="13" />
          换一道变式题
        </button>
        <div class="relative">
          <button
            class="kiwi-btn-ghost !text-xs !py-1.5"
            title="反馈题目或判分问题"
            @click="showFeedback = !showFeedback"
          >
            <KiwiIcon name="alert" :size="13" />
            题目反馈
          </button>
          <div
            v-if="showFeedback"
            class="absolute z-20 bottom-full mb-1.5 left-0 w-44 rounded-xl border border-slate-200 bg-white shadow-lg p-1.5"
          >
            <button class="w-full text-left px-2.5 py-1.5 rounded-lg text-xs text-slate-600 hover:bg-slate-50" @click="emit('feedback', 'content'); showFeedback = false">
              题目表述有误
            </button>
            <button class="w-full text-left px-2.5 py-1.5 rounded-lg text-xs text-slate-600 hover:bg-slate-50" @click="emit('feedback', 'grading'); showFeedback = false">
              判分不合理
            </button>
            <button class="w-full text-left px-2.5 py-1.5 rounded-lg text-xs text-slate-600 hover:bg-slate-50" @click="emit('feedback', 'source'); showFeedback = false">
              来源不可靠
            </button>
          </div>
        </div>

        <div class="flex-1" />
        <button class="kiwi-btn-primary" @click="emit('next')">
          <template v-if="isLast">结束训练</template>
          <template v-else>
            下一题
            <KiwiIcon name="arrowRight" :size="14" />
          </template>
        </button>
      </div>
    </div>
  </div>
</template>
