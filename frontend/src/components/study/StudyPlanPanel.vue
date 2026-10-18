<script setup lang="ts">
// StudyPlanPanel：学习计划 —— 阶段判定、14 天训练节奏、薄弱知识点与今日建议。
import { computed, onMounted, reactive, ref } from 'vue'
import { useStudyStore, type PlanDay } from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiEmpty from '@/components/ui/KiwiEmpty.vue'
import { toast } from '@/components/ui/toast'

const emit = defineEmits<{
  (e: 'start-mode', mode: 'drill' | 'mock'): void
  (e: 'open-graph'): void
}>()

const study = useStudyStore()
const plan = computed(() => study.plan)

const PHASE_META: Record<string, { label: string; desc: string; cls: string; icon: string }> = {
  initial: {
    label: '起步期',
    desc: '建立知识面，先跑通渐进训练',
    cls: 'from-sky-400 to-sky-600',
    icon: 'learn',
  },
  middle: {
    label: '提升期',
    desc: '补齐薄弱点，穿插整卷检验',
    cls: 'from-kiwi-400 to-kiwi-600',
    icon: 'target',
  },
  late: {
    label: '巩固期',
    desc: '以仿真考试检验综合水平',
    cls: 'from-violet-400 to-violet-600',
    icon: 'book',
  },
  sprint: {
    label: '冲刺期',
    desc: '临近目标，整卷节奏与错题复盘',
    cls: 'from-amber-400 to-rose-500',
    icon: 'play',
  },
}

const meta = computed(() => PHASE_META[plan.value?.phase || 'initial'])

const todayStr = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
})

const weekDays = computed(() => plan.value?.week || [])
const todayPlan = computed(() => weekDays.value.find((d) => d.date === todayStr.value))

const weekGroups = computed(() => {
  const first = weekDays.value.slice(0, 7)
  const second = weekDays.value.slice(7, 14)
  return [first, second].filter((g) => g.length)
})

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function dayParts(dateStr: string) {
  const [y, m, d] = dateStr.split('-').map(Number)
  const dt = new Date(y, (m || 1) - 1, d || 1)
  return {
    weekday: WEEKDAYS[dt.getDay()],
    label: `${String(m).padStart(2, '0')}/${String(d).padStart(2, '0')}`,
    isToday: dateStr === todayStr.value,
  }
}

function pct(v: number | undefined | null) {
  return Math.round((v || 0) * 100)
}

function refresh() {
  study.loadPlan()
}

// ---------- 手动调整未来节奏 ----------
const editingDate = ref('')
const savingDay = ref(false)
const editForm = reactive({
  mode: 'drill' as 'drill' | 'mock',
  minutes: 30,
  focus: '',
  note: '',
})

function startEdit(day: PlanDay) {
  editingDate.value = day.date
  editForm.mode = day.mode
  editForm.minutes = day.minutes
  editForm.focus = day.focus.join('、')
  editForm.note = day.note
}

async function saveEdit(clear = false) {
  if (!editingDate.value || savingDay.value) return
  savingDay.value = true
  try {
    await study.adjustPlan({
      date: editingDate.value,
      mode: editForm.mode,
      minutes: Number(editForm.minutes) || 30,
      focus: editForm.focus
        .split(/[、,，;；\s]+/)
        .map((x) => x.trim())
        .filter(Boolean)
        .slice(0, 6),
      note: editForm.note,
      clear,
    })
    toast.success(clear ? '已恢复自动安排' : '已保存当天安排')
    editingDate.value = ''
  } catch (e: any) {
    toast.error(e.message || '保存计划失败')
  } finally {
    savingDay.value = false
  }
}

onMounted(() => {
  study.loadPlan()
})
</script>

<template>
  <div class="space-y-4 animate-fade-up">
    <div class="flex items-start justify-between gap-3">
      <div class="flex items-center gap-2.5">
        <span class="w-9 h-9 rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white grid place-items-center shadow-sm">
          <KiwiIcon name="calendar" :size="16" />
        </span>
        <div>
          <h3 class="font-semibold text-slate-800">学习计划</h3>
          <p class="text-xs text-slate-400">根据覆盖度、正确率趋势与目标日期动态调整</p>
        </div>
      </div>
      <button class="kiwi-btn-ghost !p-1.5" title="重新计算计划" @click="refresh">
        <KiwiIcon name="refresh" :size="15" />
      </button>
    </div>

    <div v-if="study.planLoading && !plan" class="grid md:grid-cols-2 gap-3">
      <div v-for="i in 4" :key="i" class="kiwi-card h-28 animate-pulse bg-slate-100/50" />
    </div>

    <KiwiEmpty
      v-else-if="!plan"
      icon="calendar"
      title="暂无学习计划"
      desc="开始第一组训练后，Kiwi 会根据掌握度与目标日期生成 14 天节奏"
    >
      <button class="kiwi-btn-primary" @click="emit('start-mode', 'drill')">
        <KiwiIcon name="target" :size="14" />
        开始一组训练
      </button>
    </KiwiEmpty>

    <template v-else>
      <!-- 阶段总览 -->
      <div class="kiwi-card p-5 relative overflow-hidden">
        <div
          class="absolute right-0 top-0 w-44 h-44 rounded-full bg-gradient-to-br opacity-[0.12] blur-2xl -translate-y-1/3 translate-x-1/4"
          :class="meta.cls"
        />
        <div class="flex items-center gap-4 flex-wrap relative">
          <div
            class="w-12 h-12 shrink-0 rounded-2xl bg-gradient-to-br text-white grid place-items-center shadow-glow"
            :class="meta.cls"
          >
            <KiwiIcon :name="meta.icon" :size="22" />
          </div>
          <div class="flex-1 min-w-[200px]">
            <div class="flex items-center gap-2 mb-0.5">
              <p class="text-sm font-semibold text-slate-800">{{ meta.label }}</p>
              <span class="px-1.5 py-0.5 rounded bg-slate-100 text-[10px] text-slate-500">
                {{ plan.suggested_mode === 'mock' ? '建议整卷' : '建议渐进训练' }}
              </span>
            </div>
            <p class="text-xs text-slate-400">{{ meta.desc }}</p>
          </div>
          <div v-if="plan.days_to_target !== null" class="text-right">
            <p class="text-2xl font-bold tabular-nums" :class="plan.days_to_target <= 14 ? 'text-rose-500' : 'text-slate-700'">
              {{ Math.max(0, plan.days_to_target) }}
            </p>
            <p class="text-[10px] text-slate-400">天后目标</p>
          </div>
        </div>

        <div class="grid grid-cols-3 gap-3 mt-5">
          <div class="rounded-xl bg-slate-50/80 border border-slate-200/60 px-3 py-2.5">
            <p class="text-[10px] text-slate-400 mb-0.5">知识覆盖</p>
            <p class="text-lg font-bold text-slate-700 tabular-nums">{{ pct(plan.coverage) }}%</p>
          </div>
          <div class="rounded-xl bg-slate-50/80 border border-slate-200/60 px-3 py-2.5">
            <p class="text-[10px] text-slate-400 mb-0.5">近 30 题正确率</p>
            <p class="text-lg font-bold text-slate-700 tabular-nums">{{ pct(plan.accuracy_trend) }}%</p>
          </div>
          <div class="rounded-xl bg-slate-50/80 border border-slate-200/60 px-3 py-2.5">
            <p class="text-[10px] text-slate-400 mb-0.5">薄弱知识点</p>
            <p class="text-lg font-bold text-slate-700 tabular-nums">{{ plan.weak_topics.length }}</p>
          </div>
        </div>

        <div class="mt-4 rounded-xl bg-kiwi-50/60 border border-kiwi-100 px-3.5 py-2.5">
          <p class="text-[11px] text-slate-600 leading-relaxed flex items-start gap-1.5">
            <KiwiIcon name="sparkle" :size="12" class="text-kiwi-500 mt-0.5 shrink-0" />
            {{ plan.rationale }}
          </p>
          <div
            v-if="plan.exam_history?.count"
            class="mt-1.5 pl-[18px] flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-slate-400"
          >
            <span class="inline-flex items-center gap-1 text-slate-500">
              <KiwiIcon name="book" :size="11" />
              最近 {{ plan.exam_history.count }} 次仿真
            </span>
            <span>均分 {{ pct(plan.exam_history.avg_rate ?? 0) }}%</span>
            <span>最近一次 {{ pct(plan.exam_history.latest_rate ?? 0) }}%</span>
            <span v-if="plan.exam_history.passing_known">
              合格 {{ plan.exam_history.passed }}/{{ plan.exam_history.passing_known }}
            </span>
          </div>
        </div>

        <div class="flex items-center gap-2 mt-4">
          <button class="kiwi-btn-primary !py-2" @click="emit('start-mode', plan.suggested_mode as 'drill' | 'mock')">
            <KiwiIcon :name="plan.suggested_mode === 'mock' ? 'book' : 'target'" :size="14" />
            {{ plan.suggested_mode === 'mock' ? '开始一场仿真考试' : '开始渐进训练' }}
          </button>
          <button class="kiwi-btn-secondary !py-2" @click="emit('open-graph')">
            <KiwiIcon name="graph" :size="14" />
            查看学习图谱
          </button>
          <button
            v-if="todayPlan"
            class="kiwi-btn-ghost !py-2 !text-xs"
            @click="emit('start-mode', todayPlan.mode as 'drill' | 'mock')"
          >
            按今日安排：{{ todayPlan.mode === 'mock' ? '整卷' : '渐进' }}
          </button>
        </div>
      </div>

      <!-- 14 天节奏 -->
      <div class="kiwi-card p-5">
        <div class="flex items-center justify-between mb-3">
          <p class="text-sm font-semibold text-slate-700">未来 14 天节奏</p>
          <span class="text-[10px] text-slate-400">每天约 {{ study.profile?.daily_minutes || 30 }} 分钟基础量，整卷日翻倍</span>
        </div>

        <div v-for="(group, gi) in weekGroups" :key="gi" class="mb-3 last:mb-0">
          <p class="text-[10px] text-slate-300 mb-1.5">第 {{ gi + 1 }} 周</p>
          <div class="grid grid-cols-7 gap-1.5">
            <button
              v-for="d in group"
              :key="d.date"
              class="relative rounded-xl border px-2 py-2.5 text-center transition-all hover:shadow-sm hover:-translate-y-0.5"
              :class="
                editingDate === d.date
                  ? 'border-kiwi-400 ring-2 ring-kiwi-200/60 bg-kiwi-50/70'
                  : dayParts(d.date).isToday
                    ? 'border-kiwi-300 bg-kiwi-50/70'
                    : d.mode === 'mock'
                      ? 'border-violet-200/70 bg-violet-50/40'
                      : 'border-slate-200/60 bg-white/60'
              "
              :title="`${d.note || '点击调整当天安排'}`"
              @click="startEdit(d)"
            >
              <span
                v-if="d.adjusted"
                class="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-amber-400 border border-white"
                title="已手动调整"
              />
              <p class="text-[9px] text-slate-400">{{ dayParts(d.date).weekday }}</p>
              <p class="text-[11px] font-medium text-slate-600 mt-0.5">{{ dayParts(d.date).label }}</p>
              <div class="my-1.5 flex justify-center">
                <span
                  class="w-6 h-6 rounded-lg grid place-items-center"
                  :class="
                    d.mode === 'mock'
                      ? 'bg-violet-100 text-violet-600'
                      : 'bg-kiwi-100 text-kiwi-600'
                  "
                >
                  <KiwiIcon :name="d.mode === 'mock' ? 'book' : 'target'" :size="12" />
                </span>
              </div>
              <p class="text-[9px] text-slate-500 tabular-nums">{{ d.minutes }} 分钟</p>
              <p class="text-[9px] text-slate-300 truncate mt-0.5" :title="d.focus.join('、')">
                {{ d.focus[0] || '—' }}
              </p>
            </button>
          </div>
        </div>

        <!-- 手动调整 -->
        <div
          v-if="editingDate"
          class="mt-3 rounded-xl border border-kiwi-200/70 bg-kiwi-50/40 p-3.5 animate-fade-up"
        >
          <div class="flex items-center gap-2 mb-2.5">
            <span class="text-xs font-medium text-slate-700">调整 {{ editingDate }}</span>
            <span class="text-[10px] text-slate-400">手动安排后，重算计划不会覆盖这一天</span>
            <button class="ml-auto kiwi-btn-ghost !p-1" title="收起" @click="editingDate = ''">
              <KiwiIcon name="close" :size="13" />
            </button>
          </div>
          <div class="flex flex-wrap items-end gap-2.5">
            <label class="text-[10px] text-slate-500">
              形式
              <div class="flex gap-1 mt-1">
                <button
                  class="px-2 py-1 rounded-lg border text-[11px]"
                  :class="editForm.mode === 'drill' ? 'border-kiwi-400 bg-white text-kiwi-700' : 'border-slate-200 bg-white/60 text-slate-500'"
                  @click="editForm.mode = 'drill'"
                >
                  渐进训练
                </button>
                <button
                  class="px-2 py-1 rounded-lg border text-[11px]"
                  :class="editForm.mode === 'mock' ? 'border-violet-400 bg-white text-violet-700' : 'border-slate-200 bg-white/60 text-slate-500'"
                  @click="editForm.mode = 'mock'"
                >
                  整卷仿真
                </button>
              </div>
            </label>
            <label class="text-[10px] text-slate-500">
              目标时长（分钟）
              <input v-model.number="editForm.minutes" type="number" min="5" max="600" class="kiwi-input !py-1.5 !px-2 text-xs mt-1 w-24" />
            </label>
            <label class="text-[10px] text-slate-500 flex-1 min-w-[160px]">
              关注知识点（顿号分隔）
              <input v-model="editForm.focus" class="kiwi-input !py-1.5 !px-2 text-xs mt-1" placeholder="如：范围管理、进度管理" />
            </label>
          </div>
          <div class="flex items-center gap-2 mt-2.5">
            <input v-model="editForm.note" class="kiwi-input !py-1.5 !px-2 text-xs flex-1" placeholder="备注（可选）" />
            <button class="kiwi-btn-primary !py-1.5 !px-3 text-xs" :disabled="savingDay" @click="saveEdit(false)">
              保存
            </button>
            <button
              v-if="weekDays.find((x) => x.date === editingDate)?.adjusted"
              class="kiwi-btn-ghost !py-1.5 !px-2 text-[11px]"
              :disabled="savingDay"
              @click="saveEdit(true)"
            >
              恢复自动
            </button>
            <button class="kiwi-btn-ghost !py-1.5 !px-2 text-[11px]" @click="editingDate = ''">取消</button>
          </div>
        </div>

        <div class="flex items-center gap-4 mt-2 text-[10px] text-slate-400">
          <span class="flex items-center gap-1">
            <span class="w-2.5 h-2.5 rounded bg-kiwi-100" /> 渐进训练
          </span>
          <span class="flex items-center gap-1">
            <span class="w-2.5 h-2.5 rounded bg-violet-100" /> 整卷仿真
          </span>
          <span class="flex items-center gap-1">
            <span class="w-2.5 h-2.5 rounded bg-kiwi-50 border border-kiwi-300" /> 今天
          </span>
        </div>
      </div>

      <!-- 薄弱点 -->
      <div v-if="plan.weak_topics.length" class="kiwi-card p-5">
        <p class="text-sm font-semibold text-slate-700 mb-3">需要优先补齐</p>
        <div class="grid sm:grid-cols-2 gap-2.5">
          <div
            v-for="w in plan.weak_topics"
            :key="w.slug"
            class="rounded-xl border border-slate-200/60 px-3 py-2.5"
          >
            <div class="flex items-center gap-2">
              <span class="text-xs text-slate-600 flex-1 truncate">{{ w.title }}</span>
              <span class="text-[10px] text-rose-500 tabular-nums">{{ pct(w.mastery) }}%</span>
            </div>
            <div class="h-1.5 rounded-full bg-slate-200/60 overflow-hidden mt-1.5">
              <div
                class="h-full rounded-full bg-gradient-to-r from-rose-300 to-rose-500"
                :style="{ width: `${Math.max(2, pct(w.mastery))}%` }"
              />
            </div>
            <p v-if="w.domain" class="text-[9px] text-slate-300 mt-1">{{ w.domain }}</p>
          </div>
        </div>
        <button class="kiwi-btn-secondary !py-2 !text-xs mt-3" @click="emit('start-mode', 'drill')">
          <KiwiIcon name="target" :size="12" />
          薄弱点专项训练
        </button>
      </div>
    </template>
  </div>
</template>
