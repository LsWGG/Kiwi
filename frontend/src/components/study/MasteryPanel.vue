<script setup lang="ts">
// MasteryPanel：学习模式右侧进度面板 —— 掌握度热力条 + 学习计划进度 + 统计。
import { computed, onMounted } from 'vue'
import { useStudyStore } from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const emit = defineEmits<{
  (e: 'open-plan'): void
  (e: 'open-review'): void
}>()

const study = useStudyStore()

onMounted(() => {
  if (!study.plan) study.loadPlan()
  if (!study.dueReviews.length) study.loadDueReviews()
})

const plan = computed(() => study.plan)
const weekPreview = computed(() => (study.plan?.week || []).slice(0, 7))

function weekdayLabel(iso: string) {
  const d = new Date(`${iso}T00:00:00`)
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
}

const avg = computed(() => {
  if (!study.mastery.length) return 0
  return study.mastery.reduce((s, it) => s + it.score, 0) / study.mastery.length
})

// 掌握度热力条颜色
function heatColor(score: number) {
  if (score >= 0.8) return 'bg-emerald-500'
  if (score >= 0.5) return 'bg-kiwi-500'
  if (score >= 0.3) return 'bg-amber-500'
  return 'bg-rose-500'
}

// 今日新增掌握（答卷数增量）
const todayNew = computed(() => study.mastery.filter((it) => it.score > 0).length)

const accuracyPct = computed(() =>
  study.answeredCount ? Math.round((study.correctCount / study.answeredCount) * 100) : 0,
)

function pct(v: number) {
  return Math.round(v * 100)
}
</script>

<template>
  <div class="space-y-4">
    <!-- 掌握度总览 -->
    <div class="kiwi-card p-5 animate-fade-up">
      <div class="flex items-center justify-between mb-3">
        <p class="text-sm font-semibold text-slate-700">掌握度</p>
        <span class="text-[11px] text-slate-400">
          覆盖 {{ Math.round(study.masteryCoverage * 100) }}%
        </span>
      </div>

      <!-- 平均掌握度环 -->
      <div class="flex items-center gap-3 mb-4">
        <div class="relative w-14 h-14 shrink-0">
          <svg viewBox="0 0 48 48" class="w-full h-full -rotate-90">
            <circle cx="24" cy="24" r="20" fill="none" stroke="#eceef7" stroke-width="5" />
            <circle
              cx="24"
              cy="24"
              r="20"
              fill="none"
              stroke="#6f72dc"
              stroke-width="5"
              stroke-linecap="round"
              :stroke-dasharray="`${(avg * 125.6)} 125.6`"
              class="transition-all duration-700"
            />
          </svg>
          <span class="absolute inset-0 grid place-items-center text-sm font-bold text-slate-700">
            {{ pct(avg) }}%
          </span>
        </div>
        <div class="min-w-0">
          <p class="text-sm font-medium text-slate-700">平均掌握度</p>
          <p class="text-xs text-slate-400 mt-0.5">已掌握 {{ todayNew }} 个知识点</p>
        </div>
      </div>

      <!-- 掌握度热力条（最近几项） -->
      <div v-if="study.mastery.length" class="space-y-1.5 max-h-52 overflow-y-auto pr-1">
        <div
          v-for="it in study.mastery.slice(0, 12)"
          :key="it.slug"
          class="flex items-center gap-2"
        >
          <span class="text-[11px] text-slate-500 truncate w-24 shrink-0">{{ it.title }}</span>
          <div class="flex-1 h-1.5 rounded-full bg-slate-200/50 overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-500"
              :class="heatColor(it.score)"
              :style="{ width: `${it.score * 100}%` }"
            />
          </div>
          <span class="text-[10px] text-slate-400 tabular-nums w-7 text-right">{{ pct(it.score) }}%</span>
        </div>
      </div>
      <div v-else class="text-xs text-slate-400 text-center py-4">
        开始训练后，这里会显示各知识点掌握度
      </div>
    </div>

    <!-- 学习计划进度（README 14.6.4） -->
    <div class="kiwi-card p-5 animate-fade-up" style="animation-delay: 60ms">
      <div class="flex items-center justify-between mb-3">
        <p class="text-sm font-semibold text-slate-700">学习计划</p>
        <button class="text-[11px] text-kiwi-600 hover:text-kiwi-700" @click="emit('open-plan')">
          查看计划
        </button>
      </div>
      <div v-if="plan" class="space-y-3">
        <div class="flex items-center gap-2 flex-wrap">
          <span
            class="px-2 py-0.5 rounded-full text-[10px] font-medium"
            :class="
              plan.suggested_mode === 'mock'
                ? 'bg-amber-100/80 text-amber-700'
                : 'bg-kiwi-100/80 text-kiwi-700'
            "
          >
            当前建议：{{ plan.suggested_mode === 'mock' ? '仿真考试' : '渐进训练' }}
          </span>
          <span
            v-if="plan.days_to_target !== null"
            class="px-2 py-0.5 rounded-full bg-slate-100 text-[10px] text-slate-600"
          >
            距目标 {{ Math.max(0, plan.days_to_target) }} 天
          </span>
          <span
            v-if="(plan.streak_days || 0) > 0"
            class="px-2 py-0.5 rounded-full bg-emerald-50 text-[10px] text-emerald-700"
            title="连续学习天数"
          >
            连续 {{ plan.streak_days }} 天
          </span>
        </div>

        <div>
          <div class="flex items-center justify-between text-[10px] text-slate-400 mb-1">
            <span>掌握度覆盖率</span>
            <span class="tabular-nums">{{ Math.round(plan.coverage * 100) }}%</span>
          </div>
          <div class="h-2 rounded-full bg-slate-200/60 overflow-hidden">
            <div
              class="h-full rounded-full bg-gradient-to-r from-kiwi-400 to-kiwi-600 transition-all duration-700"
              :style="{ width: `${Math.min(100, Math.round(plan.coverage * 100))}%` }"
            />
          </div>
        </div>

        <button
          class="w-full rounded-xl border border-amber-100 bg-amber-50/60 px-3 py-2 text-left hover:border-amber-200 transition-colors"
          @click="emit('open-review')"
        >
          <div class="flex items-center justify-between">
            <span class="text-[11px] font-medium text-amber-700">今日到期复习</span>
            <span class="text-sm font-bold text-amber-700 tabular-nums">{{ plan.due_count || 0 }}</span>
          </div>
          <p class="text-[10px] text-amber-600/70 mt-0.5">
            {{ (plan.due_count || 0) > 0 ? '按间隔调度，优先巩固即将遗忘的知识点' : '今日无到期知识点' }}
          </p>
        </button>

        <div v-if="weekPreview.length" class="space-y-1">
          <div
            v-for="day in weekPreview"
            :key="day.date"
            class="flex items-center gap-2 text-[10px]"
          >
            <span class="w-8 shrink-0 text-slate-400">{{ weekdayLabel(day.date) }}</span>
            <span
              class="px-1.5 py-0.5 rounded shrink-0"
              :class="
                day.mode === 'mock'
                  ? 'bg-amber-100/70 text-amber-700'
                  : 'bg-kiwi-50 text-kiwi-700'
              "
            >
              {{ day.mode === 'mock' ? '整卷' : '训练' }}
            </span>
            <span class="text-slate-400">{{ day.minutes }} 分钟</span>
            <span class="text-slate-500 truncate">{{ day.focus.join(' · ') }}</span>
          </div>
        </div>
      </div>
      <div v-else class="text-xs text-slate-400 py-2">
        完成冷启动后，这里会显示覆盖率、建议形态与本周计划。
      </div>
    </div>

    <!-- 本次训练统计 -->
    <div class="kiwi-card p-5 animate-fade-up" style="animation-delay: 80ms">
      <p class="text-sm font-semibold text-slate-700 mb-3">本次训练</p>
      <div class="grid grid-cols-2 gap-3">
        <div class="rounded-xl bg-slate-50/80 border border-slate-200/60 p-3">
          <div class="flex items-center gap-1.5 text-slate-500">
            <KiwiIcon name="target" :size="13" class="text-kiwi-500" />
            <span class="text-[11px]">已答题</span>
          </div>
          <p class="text-xl font-bold text-slate-800 tabular-nums mt-1">{{ study.answeredCount }}</p>
        </div>
        <div class="rounded-xl bg-slate-50/80 border border-slate-200/60 p-3">
          <div class="flex items-center gap-1.5 text-slate-500">
            <KiwiIcon name="check" :size="13" class="text-emerald-500" />
            <span class="text-[11px]">正确率</span>
          </div>
          <p class="text-xl font-bold text-slate-800 tabular-nums mt-1">{{ accuracyPct }}%</p>
        </div>
      </div>
    </div>
  </div>
</template>