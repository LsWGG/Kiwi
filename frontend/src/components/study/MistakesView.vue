<script setup lang="ts">
// MistakesView：错题本 —— 覆盖客观题与主观题，支持按题型筛选、展开解析与评分维度。
import { computed, onMounted, ref } from 'vue'
import {
  useStudyStore,
  QUESTION_TYPE_LABEL,
  type Mistake,
  type QuestionType,
} from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'

const emit = defineEmits<{ (e: 'cite', slug: string): void }>()

const study = useStudyStore()
const expanded = ref<Set<string>>(new Set())
const filterType = ref<'all' | QuestionType>('all')
const filterTopic = ref<'all' | string>('all')

const filters: Array<{ value: 'all' | QuestionType; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'single_choice', label: '单选' },
  { value: 'multiple_choice', label: '多选' },
  { value: 'true_false', label: '判断' },
  { value: 'fill_blank', label: '填空' },
  { value: 'short_answer', label: '简答' },
  { value: 'case_analysis', label: '案例' },
  { value: 'essay', label: '论文' },
]

const filtered = computed(() =>
  study.mistakes.filter(
    (m) =>
      (filterType.value === 'all' || m.question_type === filterType.value) &&
      (filterTopic.value === 'all' || m.cite_slug === filterTopic.value),
  ),
)

// 知识点筛选项从已加载错题中归纳，按出现次数降序。
const topicOptions = computed(() => {
  const counts = new Map<string, { slug: string; title: string; count: number }>()
  for (const m of study.mistakes) {
    if (!m.cite_slug) continue
    const entry = counts.get(m.cite_slug)
    if (entry) entry.count += 1
    else
      counts.set(m.cite_slug, {
        slug: m.cite_slug,
        title: m.cite_title || m.cite_slug,
        count: 1,
      })
  }
  return [...counts.values()].sort((a, b) => b.count - a.count)
})

function difficultyTone(d?: string) {
  return d === 'hard'
    ? 'bg-rose-100/80 text-rose-700'
    : d === 'medium'
      ? 'bg-amber-100/80 text-amber-700'
      : 'bg-emerald-100/80 text-emerald-700'
}
const difficultyText: Record<string, string> = { basic: '基础', medium: '进阶', hard: '挑战' }

function toggle(id: string) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function fmtTime(s?: string) {
  if (!s) return ''
  const d = new Date(s)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const letter = (i: number) => String.fromCharCode(65 + i)

function chosenLabels(m: Mistake) {
  const set = m.selected_indexes?.length
    ? m.selected_indexes
    : m.selected_index >= 0
      ? [m.selected_index]
      : []
  return set.map(letter)
}
function correctLabels(m: Mistake) {
  const set = m.correct_indexes?.length
    ? m.correct_indexes
    : m.correct_index >= 0
      ? [m.correct_index]
      : []
  return set.map(letter)
}

const isChoice = (m: Mistake) =>
  ['single_choice', 'multiple_choice', 'true_false'].includes(m.question_type)
const isSubjective = (m: Mistake) =>
  ['short_answer', 'case_analysis', 'essay'].includes(m.question_type)

function reload() {
  // 全量加载，题型 / 知识点在本地组合筛选，保证筛选项不随题型变化
  study.loadMistakes()
}

onMounted(reload)
</script>

<template>
  <div class="space-y-3 animate-fade-up">
    <div class="flex items-center justify-between mb-1">
      <div class="flex items-center gap-2">
        <span class="w-9 h-9 rounded-xl bg-gradient-to-br from-rose-400 to-rose-600 text-white grid place-items-center shadow-sm">
          <KiwiIcon name="target" :size="16" />
        </span>
        <div>
          <h3 class="font-semibold text-slate-800">错题本</h3>
          <p class="text-xs text-slate-400">
            {{ study.mistakesTotal }} 道曾答错的题 · 覆盖主客观题型
          </p>
        </div>
      </div>
      <button class="kiwi-btn-ghost !p-1.5" title="刷新" @click="reload">
        <KiwiIcon name="refresh" :size="15" />
      </button>
    </div>

    <!-- 题型 / 知识点筛选 -->
    <div class="flex flex-wrap items-center gap-1.5">
      <button
        v-for="f in filters"
        :key="f.value"
        class="px-2.5 py-1 rounded-lg text-[11px] border transition-colors"
        :class="
          filterType === f.value
            ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700 font-medium'
            : 'border-slate-200/70 bg-white/60 text-slate-400 hover:border-kiwi-200'
        "
        @click="filterType = f.value"
      >
        {{ f.label }}
      </button>

      <span class="mx-0.5 h-4 w-px bg-slate-200/80" />

      <select
        v-model="filterTopic"
        class="h-[26px] max-w-[220px] rounded-lg border border-slate-200/70 bg-white/60 px-1.5 text-[11px] text-slate-500 outline-none focus:border-kiwi-300"
        title="按知识点筛选"
      >
        <option value="all">全部知识点</option>
        <option v-for="t in topicOptions" :key="t.slug" :value="t.slug">
          {{ t.title }}（{{ t.count }}）
        </option>
      </select>

      <button
        v-if="filterType !== 'all' || filterTopic !== 'all'"
        class="px-2 py-1 rounded-lg text-[11px] text-slate-400 hover:text-slate-600 underline underline-offset-2"
        @click="filterType = 'all'; filterTopic = 'all'"
      >
        清除筛选
      </button>
    </div>

    <!-- 加载中 -->
    <div v-if="study.mistakesLoading" class="grid md:grid-cols-2 gap-3">
      <div v-for="i in 4" :key="i" class="kiwi-card p-4 space-y-2">
        <div class="h-3 rounded bg-slate-200/60 animate-pulse w-3/4" />
        <div class="h-2.5 rounded bg-slate-200/40 animate-pulse w-1/2" />
        <div class="h-2.5 rounded bg-slate-200/40 animate-pulse w-2/3" />
      </div>
    </div>

    <!-- 空态 -->
    <KiwiEmpty
      v-else-if="!filtered.length"
      icon="check"
      title="还没有错题"
      :desc="
        filterType === 'all' && filterTopic === 'all'
          ? '答题中答错的题目会沉淀到这里，方便集中回顾弱点'
          : '当前筛选条件下没有错题记录'
      "
    />

    <!-- 错题列表 -->
    <div v-else class="grid md:grid-cols-2 gap-3">
      <div v-for="m in filtered" :key="m.attempt_id" class="kiwi-card p-4 flex flex-col">
        <div class="flex items-start gap-2 mb-2">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1.5 mb-1">
              <span class="px-1.5 py-0.5 rounded bg-slate-100 text-[10px] text-slate-500">
                {{ QUESTION_TYPE_LABEL[m.question_type] || '题目' }}
              </span>
              <span
                class="px-1.5 py-0.5 rounded-full text-[10px] font-medium"
                :class="difficultyTone(m.difficulty)"
              >
                {{ difficultyText[m.difficulty] || m.difficulty }}
              </span>
              <span
                v-if="m.cite_title"
                class="max-w-[150px] truncate px-1.5 py-0.5 rounded bg-kiwi-50/80 text-[10px] text-kiwi-600"
                :title="m.cite_title"
              >
                {{ m.cite_title }}
              </span>
            </div>
            <p class="text-sm text-slate-700 leading-relaxed line-clamp-3">{{ m.question }}</p>
          </div>
        </div>

        <!-- 作答情况 -->
        <div v-if="isChoice(m)" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs mb-2.5">
          <span class="text-rose-500 flex items-center gap-1">
            <KiwiIcon name="close" :size="12" />
            你选了 {{ chosenLabels(m).join('、') || '未选' }}
          </span>
          <span class="text-emerald-600 flex items-center gap-1">
            <KiwiIcon name="check" :size="12" />
            正确 {{ correctLabels(m).join('、') || '见解析' }}
          </span>
        </div>
        <div v-else-if="isSubjective(m)" class="text-xs mb-2.5 flex items-center gap-2">
          <span class="text-slate-400">得分</span>
          <span class="font-semibold tabular-nums text-slate-600">
            {{ m.score ?? '—' }} / 100
          </span>
          <span class="text-slate-300">·</span>
          <span class="text-slate-400">{{ fmtTime(m.created_at) }}</span>
        </div>
        <div v-else class="text-xs mb-2.5">
          <span class="text-slate-400">你的答案：</span>
          <span class="text-rose-500">{{ m.user_answer || '未作答' }}</span>
        </div>

        <!-- 展开 -->
        <button
          class="inline-flex items-center gap-1 text-xs text-kiwi-600 hover:text-kiwi-700 font-medium mt-auto self-start"
          @click="toggle(m.attempt_id)"
        >
          <KiwiIcon name="chevron" :size="13" :class="expanded.has(m.attempt_id) ? 'rotate-180' : ''" />
          {{ expanded.has(m.attempt_id) ? '收起解析' : '查看解析与作答' }}
        </button>

        <div v-if="expanded.has(m.attempt_id)" class="mt-3 pt-3 border-t border-slate-100 animate-fade-in space-y-3">
          <!-- 主观题作答 -->
          <div v-if="m.user_answer && !isChoice(m)">
            <p class="text-[11px] font-medium text-slate-500 mb-1">你的作答</p>
            <p class="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto rounded-lg bg-slate-50/70 px-3 py-2">
              {{ m.user_answer }}
            </p>
          </div>

          <!-- 评分维度 -->
          <div v-if="m.dimensions?.length" class="space-y-1.5">
            <p class="text-[11px] font-medium text-slate-500">评分维度</p>
            <div
              v-for="d in m.dimensions"
              :key="d.key"
              class="flex items-center gap-2 text-[11px]"
            >
              <span class="w-16 shrink-0 text-slate-500">{{ d.label }}</span>
              <div class="flex-1 h-1.5 rounded-full bg-slate-200/60 overflow-hidden">
                <div
                  class="h-full rounded-full bg-kiwi-500"
                  :style="{ width: `${d.max_score ? (d.score / d.max_score) * 100 : 0}%` }"
                />
              </div>
              <span class="text-slate-400 tabular-nums shrink-0">{{ d.score }} / {{ d.max_score }}</span>
            </div>
          </div>

          <div>
            <p class="text-[11px] font-medium text-slate-500 mb-1">解析</p>
            <p class="text-xs text-slate-500 leading-relaxed whitespace-pre-wrap">
              {{ m.explanation || '暂无解析' }}
            </p>
          </div>

          <button
            v-if="m.cite_slug"
            class="text-[11px] text-slate-400 hover:text-kiwi-600 flex items-center gap-1 transition-colors"
            @click="emit('cite', m.cite_slug || '')"
          >
            <KiwiIcon name="wiki" :size="11" />
            出自：{{ m.cite_slug }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
