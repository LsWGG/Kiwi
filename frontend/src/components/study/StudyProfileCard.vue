<script setup lang="ts">
// StudyProfileCard：学习画像表单 —— 目标/水平/时长/考试模板/目标日期/训练偏好/关注与薄弱知识点。
import { computed, onMounted, ref, watch } from 'vue'
import { useStudyStore } from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

const emit = defineEmits<{
  (e: 'saved'): void
  (e: 're-onboard'): void
}>()

const study = useStudyStore()

const goalType = ref<'exam' | 'domain' | 'explore'>('domain')
const levelPrior = ref<'beginner' | 'foundation' | 'advanced'>('foundation')
const dailyMinutes = ref(30)
const topicInput = ref('')
const topics = ref<string[]>([])
const weakInput = ref('')
const weakAreas = ref<string[]>([])
const templateId = ref<string | null>(null)
const targetDate = ref<string>('')
const preferredMode = ref<'auto' | 'drill' | 'mock'>('auto')

const saving = ref(false)

const goalOptions: { value: 'exam' | 'domain' | 'explore'; label: string; desc: string }[] = [
  { value: 'exam', label: '考试导向', desc: '围绕考点与真题训练' },
  { value: 'domain', label: '领域掌握', desc: '建立知识图谱与深度理解' },
  { value: 'explore', label: '兴趣探索', desc: '轻量广览新领域' },
]

const levelOptions: { value: 'beginner' | 'foundation' | 'advanced'; label: string; desc: string }[] = [
  { value: 'beginner', label: '入门', desc: '刚开始接触' },
  { value: 'foundation', label: '进阶', desc: '有基础，需系统化' },
  { value: 'advanced', label: '熟练', desc: '补齐薄弱与冲刺' },
]

const modeOptions: { value: 'auto' | 'drill' | 'mock'; label: string; desc: string }[] = [
  { value: 'auto', label: '系统安排', desc: '按阶段自动切换' },
  { value: 'drill', label: '渐进训练', desc: '一题一练，即时反馈' },
  { value: 'mock', label: '仿真考试', desc: '整卷计时，检验水平' },
]

const minutePresets = [15, 30, 45, 60]

const examTemplates = computed(() => study.templates)

function addTopic() {
  const t = topicInput.value.trim()
  if (t && !topics.value.includes(t)) {
    topics.value.push(t)
    topicInput.value = ''
  }
}
function removeTopic(i: number) {
  topics.value.splice(i, 1)
}
function addWeak() {
  const t = weakInput.value.trim()
  if (t && !weakAreas.value.includes(t)) {
    weakAreas.value.push(t)
    weakInput.value = ''
  }
}
function removeWeak(i: number) {
  weakAreas.value.splice(i, 1)
}

/** 选中考试模板时自动带出默认时长 */
function onTemplateChange() {
  const tpl = study.templates.find((t) => t.id === templateId.value)
  if (tpl && goalType.value === 'exam' && tpl.duration_minutes) {
    // 仿真卷时长较长，画像的每日时长不强行等于考试时长
  }
}

async function submit() {
  saving.value = true
  try {
    await study.saveProfile({
      goal_type: goalType.value,
      level_prior: levelPrior.value,
      daily_minutes: dailyMinutes.value,
      topics_focus: topics.value,
      weak_areas: weakAreas.value,
      exam_template_id: templateId.value || null,
      target_date: targetDate.value || null,
      preferred_mode: preferredMode.value,
      onboarded: true,
    })
    toast.success('画像已保存')
    emit('saved')
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function fillFromProfile() {
  const p = study.profile
  if (!p) return
  goalType.value = (p.goal_type as any) || 'domain'
  levelPrior.value = (p.level_prior as any) || 'foundation'
  dailyMinutes.value = p.daily_minutes || 30
  topics.value = [...(p.topics_focus || [])]
  weakAreas.value = [...(p.weak_areas || [])]
  templateId.value = p.exam_template_id || null
  targetDate.value = p.target_date || ''
  preferredMode.value = (p.preferred_mode as any) || 'auto'
}
onMounted(async () => {
  fillFromProfile()
  if (!study.templates.length) await study.loadTemplates()
})
watch(() => study.profile, fillFromProfile)
watch(() => study.templates, () => {}, { deep: true })
</script>

<template>
  <div class="kiwi-card p-6 animate-fade-up">
    <div class="flex items-center gap-3 mb-6">
      <span
        class="w-10 h-10 rounded-xl bg-gradient-to-br from-kiwi-100 to-white border border-kiwi-100 text-kiwi-600 grid place-items-center"
      >
        <KiwiIcon name="edit" :size="18" />
      </span>
      <div class="flex-1">
        <h3 class="font-semibold text-slate-800">学习画像</h3>
        <p class="text-xs text-slate-400 mt-0.5">Kiwi 依据目标、水平与偏好安排出题、难度和复习节奏</p>
      </div>
      <button
        v-if="study.profile"
        class="kiwi-btn-ghost !text-xs !py-1.5"
        title="重新通过对话梳理目标"
        @click="emit('re-onboard')"
      >
        <KiwiIcon name="chat" :size="13" />
        对话式重设
      </button>
    </div>

    <div class="space-y-6">
      <!-- 目标类型 -->
      <section>
        <p class="text-xs font-medium text-slate-500 mb-2">学习目标</p>
        <div class="grid sm:grid-cols-3 gap-2.5">
          <button
            v-for="g in goalOptions"
            :key="g.value"
            class="text-left rounded-xl px-3.5 py-3 border transition-all duration-200"
            :class="
              goalType === g.value
                ? 'border-kiwi-300 bg-kiwi-50 shadow-soft'
                : 'border-slate-200/80 bg-white/70 hover:border-kiwi-200'
            "
            @click="goalType = g.value"
          >
            <span class="block text-sm font-medium" :class="goalType === g.value ? 'text-kiwi-700' : 'text-slate-600'">
              {{ g.label }}
            </span>
            <span class="block text-xs text-slate-400 mt-0.5">{{ g.desc }}</span>
          </button>
        </div>
      </section>

      <!-- 考试模板 + 目标日期（考试导向） -->
      <section v-if="goalType === 'exam'" class="grid sm:grid-cols-2 gap-4">
        <div>
          <p class="text-xs font-medium text-slate-500 mb-2">考试场景模板</p>
          <select v-model="templateId" class="kiwi-input text-sm" @change="onTemplateChange">
            <option :value="null">不指定模板（使用通用题型轮换）</option>
            <option v-for="t in examTemplates" :key="t.id" :value="t.id">
              {{ t.name }}{{ t.is_builtin ? '（内置）' : '' }}
            </option>
          </select>
          <p v-if="examTemplates.find((t) => t.id === templateId)" class="text-[10px] text-slate-400 mt-1.5 leading-relaxed">
            {{ examTemplates.find((t) => t.id === templateId)?.description }}
          </p>
        </div>
        <div>
          <p class="text-xs font-medium text-slate-500 mb-2">目标日期</p>
          <input v-model="targetDate" type="date" class="kiwi-input text-sm" />
          <p class="text-[10px] text-slate-400 mt-1.5">用于计算剩余天数与冲刺阶段</p>
        </div>
      </section>

      <!-- 水平先验 -->
      <section>
        <p class="text-xs font-medium text-slate-500 mb-2">当前水平</p>
        <div class="grid sm:grid-cols-3 gap-2.5">
          <button
            v-for="l in levelOptions"
            :key="l.value"
            class="px-4 py-2.5 rounded-xl border text-left transition-all duration-200"
            :class="
              levelPrior === l.value
                ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
                : 'border-slate-200/80 bg-white/70 text-slate-500 hover:border-kiwi-200'
            "
            @click="levelPrior = l.value"
          >
            <span class="block text-sm font-medium">{{ l.label }}</span>
            <span class="block text-[10px] mt-0.5" :class="levelPrior === l.value ? 'text-kiwi-500' : 'text-slate-400'">
              {{ l.desc }}
            </span>
          </button>
        </div>
      </section>

      <!-- 每日时长 -->
      <section>
        <p class="text-xs font-medium text-slate-500 mb-2">
          每日目标时长 <span class="text-kiwi-600 font-semibold">{{ dailyMinutes }} 分钟</span>
        </p>
        <div class="flex items-center gap-2.5">
          <button
            v-for="m in minutePresets"
            :key="m"
            class="px-3.5 py-1.5 rounded-lg border text-xs transition-all duration-200"
            :class="
              dailyMinutes === m
                ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700 font-medium'
                : 'border-slate-200/80 bg-white/70 text-slate-500 hover:border-kiwi-200'
            "
            @click="dailyMinutes = m"
          >
            {{ m }}
          </button>
          <input
            v-model.number="dailyMinutes"
            type="range"
            min="5"
            max="180"
            step="5"
            class="flex-1 accent-kiwi-500"
          />
        </div>
      </section>

      <!-- 训练偏好 -->
      <section>
        <p class="text-xs font-medium text-slate-500 mb-2">训练偏好</p>
        <div class="grid sm:grid-cols-3 gap-2.5">
          <button
            v-for="m in modeOptions"
            :key="m.value"
            class="rounded-xl px-3.5 py-2.5 border text-left transition-all duration-200"
            :class="
              preferredMode === m.value
                ? 'border-kiwi-300 bg-kiwi-50'
                : 'border-slate-200/80 bg-white/70 hover:border-kiwi-200'
            "
            @click="preferredMode = m.value"
          >
            <span class="block text-sm font-medium" :class="preferredMode === m.value ? 'text-kiwi-700' : 'text-slate-600'">
              {{ m.label }}
            </span>
            <span class="block text-[10px] text-slate-400 mt-0.5">{{ m.desc }}</span>
          </button>
        </div>
      </section>

      <div class="grid md:grid-cols-2 gap-6">
        <!-- 关注知识点 -->
        <section>
          <p class="text-xs font-medium text-slate-500 mb-2">关注知识点（优先出题）</p>
          <div class="flex flex-wrap gap-1.5 mb-2.5 min-h-[24px]">
            <span
              v-for="(t, i) in topics"
              :key="t"
              class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-kiwi-100/80 text-kiwi-700 text-xs"
            >
              {{ t }}
              <button class="hover:text-rose-500" @click="removeTopic(i)">
                <KiwiIcon name="close" :size="11" />
              </button>
            </span>
            <span v-if="!topics.length" class="text-[11px] text-slate-400">未添加，按库内页面热度出题</span>
          </div>
          <div class="flex gap-2">
            <input
              v-model="topicInput"
              class="kiwi-input !py-2 text-sm"
              placeholder="如：HTTP 缓存"
              @keydown.enter.prevent="addTopic"
            />
            <button class="kiwi-btn-secondary shrink-0 !px-3" @click="addTopic">
              <KiwiIcon name="plus" :size="15" />
            </button>
          </div>
        </section>

        <!-- 薄弱环节 -->
        <section>
          <p class="text-xs font-medium text-slate-500 mb-2">自述薄弱环节</p>
          <div class="flex flex-wrap gap-1.5 mb-2.5 min-h-[24px]">
            <span
              v-for="(t, i) in weakAreas"
              :key="t"
              class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-amber-100/80 text-amber-700 text-xs"
            >
              {{ t }}
              <button class="hover:text-rose-500" @click="removeWeak(i)">
                <KiwiIcon name="close" :size="11" />
              </button>
            </span>
            <span v-if="!weakAreas.length" class="text-[11px] text-slate-400">用于优先安排薄弱点复习</span>
          </div>
          <div class="flex gap-2">
            <input
              v-model="weakInput"
              class="kiwi-input !py-2 text-sm"
              placeholder="如：挣值分析、合同管理"
              @keydown.enter.prevent="addWeak"
            />
            <button class="kiwi-btn-secondary shrink-0 !px-3" @click="addWeak">
              <KiwiIcon name="plus" :size="15" />
            </button>
          </div>
        </section>
      </div>
    </div>

    <div class="mt-7 flex items-center justify-between">
      <p class="text-[10px] text-slate-300">
        画像仅用于本地出题与复习调度，不会写入 Wiki。
      </p>
      <button class="kiwi-btn-primary" :disabled="saving" @click="submit">
        <KiwiIcon v-if="saving" name="loader" :size="15" spin />
        <KiwiIcon v-else name="check" :size="15" />
        保存画像
      </button>
    </div>
  </div>
</template>
