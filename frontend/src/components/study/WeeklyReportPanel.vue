<script setup lang="ts">
/** 学习周报：答题量、正确率、薄弱知识点与留存曲线。 */
import { computed, onMounted } from 'vue'
import { useStudyStore } from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const study = useStudyStore()

const report = computed(() => study.weeklyReport)
const loading = computed(() => study.weeklyLoading && !study.weeklyReport)

const deltaAttempts = computed(
  () => (report.value?.attempts ?? 0) - (report.value?.previous_attempts ?? 0),
)
const deltaAccuracy = computed(() =>
  Math.round(((report.value?.accuracy ?? 0) - (report.value?.previous_accuracy ?? 0)) * 100),
)

const maxDaily = computed(() =>
  Math.max(1, ...(report.value?.daily.map((day) => day.attempts) ?? [1])),
)

function pct(value: number): number {
  return Math.round((value || 0) * 100)
}

function duration(minutes: number): string {
  if (minutes >= 60) return `${(minutes / 60).toFixed(1)} 小时`
  return `${Math.round(minutes)} 分钟`
}

function dayLabel(value: string): string {
  const date = new Date(`${value}T00:00:00`)
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', weekday: 'short' })
}

function signed(value: number): string {
  return value > 0 ? `+${value}` : `${value}`
}

function refresh() {
  void study.loadWeeklyReport()
}

onMounted(refresh)
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-4 animate-fade-up">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span
          class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white shadow-sm"
        >
          <KiwiIcon name="trendingUp" :size="16" />
        </span>
        <div>
          <h3 class="font-semibold text-slate-800">学习周报</h3>
          <p class="text-xs text-slate-400">
            {{ report ? `${report.start} 至 ${report.end} · 最近 ${report.days} 天` : '按周统计学习表现' }}
          </p>
        </div>
      </div>
      <button
        class="kiwi-btn-ghost !p-1.5"
        :disabled="study.weeklyLoading"
        title="刷新周报"
        @click="refresh"
      >
        <KiwiIcon name="refresh" :size="15" :spin="study.weeklyLoading" />
      </button>
    </div>

    <div v-if="loading" class="kiwi-card flex items-center justify-center gap-2 p-12 text-[12px] text-slate-400">
      <KiwiIcon name="loader" :size="15" :spin="true" />
      正在统计本周学习记录…
    </div>

    <template v-else-if="report">
      <!-- 关键指标：数字 + 与上周的差值，不依赖颜色传达趋势 -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div class="kiwi-card p-3.5">
          <p class="text-[11px] text-slate-400">本周答题</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-slate-800">{{ report.attempts }}</p>
          <p class="mt-0.5 text-[10.5px]" :class="deltaAttempts >= 0 ? 'text-emerald-600' : 'text-rose-500'">
            较上周 {{ signed(deltaAttempts) }}
          </p>
        </div>
        <div class="kiwi-card p-3.5">
          <p class="text-[11px] text-slate-400">正确率</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-slate-800">{{ pct(report.accuracy) }}%</p>
          <p class="mt-0.5 text-[10.5px]" :class="deltaAccuracy >= 0 ? 'text-emerald-600' : 'text-rose-500'">
            较上周 {{ signed(deltaAccuracy) }} 个百分点
          </p>
        </div>
        <div class="kiwi-card p-3.5">
          <p class="text-[11px] text-slate-400">学习时长</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-slate-800">{{ duration(report.minutes) }}</p>
          <p class="mt-0.5 text-[10.5px] text-slate-400">上周 {{ duration(report.previous_minutes) }}</p>
        </div>
        <div class="kiwi-card p-3.5">
          <p class="text-[11px] text-slate-400">活跃天数</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-slate-800">
            {{ report.active_days }}<span class="text-sm font-normal text-slate-400"> / {{ report.days }}</span>
          </p>
          <p class="mt-0.5 text-[10.5px] text-slate-400">
            掌握 {{ pct(report.mastery_average) }}% · {{ report.mastery_topics }} 个知识点
          </p>
        </div>
      </div>

      <div v-if="!report.attempts" class="kiwi-card p-8 text-center">
        <div class="mx-auto grid h-11 w-11 place-items-center rounded-2xl bg-kiwi-50 text-kiwi-500">
          <KiwiIcon name="trendingUp" :size="18" />
        </div>
        <p class="mt-3 text-[13px] font-medium text-slate-700">本周还没有答题记录</p>
        <p class="mt-1 text-[11.5px] text-slate-400">完成一次训练或复习后，这里会自动生成统计与薄弱点分析。</p>
      </div>

      <template v-else>
        <section class="kiwi-card p-4">
          <div class="mb-3 flex items-baseline justify-between">
            <h4 class="text-[12px] font-semibold text-slate-700">留存曲线</h4>
            <span class="text-[10.5px] text-slate-400">同一知识点两次作答间隔越久，正确率通常越低</span>
          </div>
          <div class="space-y-2.5">
            <div v-for="item in report.retention" :key="item.bucket" class="flex items-center gap-3">
              <span class="w-16 shrink-0 text-[11px] text-slate-500">{{ item.bucket }}</span>
              <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                <div
                  class="h-full rounded-full bg-kiwi-500 transition-[width] duration-500"
                  :style="{ width: `${pct(item.accuracy)}%` }"
                  :title="`${item.bucket}：正确率 ${pct(item.accuracy)}%，${item.attempts} 次作答`"
                />
              </div>
              <span class="w-20 shrink-0 text-right text-[10.5px] tabular-nums text-slate-400">
                {{ item.attempts ? `${pct(item.accuracy)}% · ${item.attempts} 次` : '暂无数据' }}
              </span>
            </div>
          </div>
        </section>

        <div class="grid gap-3 md:grid-cols-2">
          <section class="kiwi-card p-4">
            <h4 class="mb-2.5 text-[12px] font-semibold text-slate-700">薄弱知识点</h4>
            <p v-if="!report.weak_topics.length" class="py-6 text-center text-[11px] text-slate-400">
              本周没有明显薄弱点，保持节奏。
            </p>
            <ul v-else class="space-y-2">
              <li
                v-for="topic in report.weak_topics"
                :key="topic.slug || topic.title"
                class="rounded-lg bg-slate-50/70 px-2.5 py-2"
              >
                <div class="flex items-center gap-2">
                  <span class="min-w-0 flex-1 truncate text-[11.5px] text-slate-700" :title="topic.title">
                    {{ topic.title }}
                  </span>
                  <span class="shrink-0 text-[10.5px] tabular-nums text-rose-500">
                    {{ pct(topic.accuracy) }}%
                  </span>
                </div>
                <p class="mt-0.5 text-[10px] text-slate-400">
                  {{ topic.attempts }} 次作答 · 掌握度 {{ pct(topic.mastery) }}%
                </p>
              </li>
            </ul>
          </section>

          <section class="kiwi-card p-4">
            <h4 class="mb-2.5 text-[12px] font-semibold text-slate-700">每日节奏</h4>
            <div class="space-y-2">
              <div v-for="day in report.daily" :key="day.date" class="flex items-center gap-2">
                <span class="w-20 shrink-0 text-[10.5px] text-slate-500">{{ dayLabel(day.date) }}</span>
                <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div
                    class="h-full rounded-full bg-kiwi-400"
                    :style="{ width: `${Math.round((day.attempts / maxDaily) * 100)}%` }"
                    :title="`${day.date}：${day.attempts} 题，正确率 ${pct(day.accuracy)}%`"
                  />
                </div>
                <span class="w-14 shrink-0 text-right text-[10.5px] tabular-nums text-slate-400">
                  {{ day.attempts ? `${day.attempts} 题` : '—' }}
                </span>
              </div>
            </div>
            <p class="mt-2 text-right text-[10px] text-slate-300">
              最长单日 {{ maxDaily }} 题
            </p>
          </section>
        </div>
      </template>
    </template>
  </div>
</template>
