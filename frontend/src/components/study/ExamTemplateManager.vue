<script setup lang="ts">
// ExamTemplateManager：考试场景模板管理 —— 查看内置模板，复制并自定义题型配比与及格线。
import { computed, onMounted, reactive, ref } from 'vue'
import {
  useStudyStore,
  QUESTION_TYPE_LABEL,
  type ExamTemplate,
  type ExamTemplateSection,
  type ScoringDimension,
  type QuestionType,
} from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

const emit = defineEmits<{ (e: 'close'): void }>()

const study = useStudyStore()

const editing = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)

interface EditorDimension {
  label: string
  weight: number
}
interface EditorSection {
  type: QuestionType
  name: string
  count: number
  score: number
  duration_minutes: number
  dimensions: EditorDimension[]
}
const form = reactive({
  name: '',
  code: '',
  description: '',
  duration_minutes: 120,
  passing_total: 45,
  coverage_domains: '',
  subject_minima: '',
  difficulty_basic: 50,
  difficulty_medium: 35,
  difficulty_hard: 15,
  sections: [] as EditorSection[],
})

const TYPE_OPTIONS: QuestionType[] = [
  'single_choice',
  'multiple_choice',
  'true_false',
  'fill_blank',
  'short_answer',
  'case_analysis',
  'essay',
]

const totalQuestions = computed(() => form.sections.reduce((s, x) => s + Number(x.count || 0), 0))
const totalScore = computed(() =>
  form.sections.reduce((s, x) => s + Number(x.count || 0) * Number(x.score || 0), 0),
)

const SUBJECTIVE_TYPES = ['short_answer', 'case_analysis', 'essay']

const DEFAULT_DIMENSIONS: Record<string, EditorDimension[]> = {
  short_answer: [
    { label: '要点覆盖', weight: 60 },
    { label: '表述准确', weight: 40 },
  ],
  case_analysis: [
    { label: '要点识别', weight: 40 },
    { label: '分析深度', weight: 40 },
    { label: '表达结构', weight: 20 },
  ],
  essay: [
    { label: '论点与结构', weight: 40 },
    { label: '论据与深度', weight: 40 },
    { label: '表达规范', weight: 20 },
  ],
}

function defaultDimensions(type: QuestionType): EditorDimension[] {
  return (DEFAULT_DIMENSIONS[type] || []).map((d) => ({ ...d }))
}

function dimensionsFromTemplate(s: ExamTemplateSection): EditorDimension[] {
  const dims = s.scoring?.dimensions || []
  return dims.map((d: ScoringDimension) => ({
    label: d.label,
    weight: Number(d.weight ?? 0) || 1,
  }))
}

function minimaText(criteria: ExamTemplate['passing_criteria']) {
  return (criteria?.subjects || [])
    .map((s) => `${s.name}:${s.min_score}`)
    .join('、')
}

function resetForm() {
  editingId.value = null
  form.name = ''
  form.code = ''
  form.description = ''
  form.duration_minutes = 120
  form.passing_total = 45
  form.coverage_domains = ''
  form.subject_minima = ''
  form.difficulty_basic = 50
  form.difficulty_medium = 35
  form.difficulty_hard = 15
  form.sections = [
    {
      type: 'single_choice',
      name: '单选题',
      count: 20,
      score: 1,
      duration_minutes: 0,
      dimensions: [],
    },
    {
      type: 'multiple_choice',
      name: '多选题',
      count: 5,
      score: 2,
      duration_minutes: 0,
      dimensions: [],
    },
  ]
}

function loadTemplate(t: ExamTemplate, clone: boolean) {
  editingId.value = clone ? null : t.id
  form.name = clone ? `${t.name}（副本）` : t.name
  form.code = clone ? '' : t.code
  form.description = t.description
  form.duration_minutes = t.duration_minutes
  form.passing_total = Number(
    t.passing_criteria?.total ?? (clone ? Math.round(t.duration_minutes / 2) : 0),
  )
  form.coverage_domains = (t.coverage_domains || []).join('、')
  form.subject_minima = minimaText(t.passing_criteria)
  const dist = t.difficulty_distribution || {}
  form.difficulty_basic = Math.round(Number(dist.basic ?? 0.5) * 100)
  form.difficulty_medium = Math.round(Number(dist.medium ?? 0.35) * 100)
  form.difficulty_hard = Math.round(Number(dist.hard ?? 0.15) * 100)
  form.sections = (t.question_types || []).map((s) => ({
    type: s.type,
    name: s.name || QUESTION_TYPE_LABEL[s.type],
    count: Number(s.count || 1),
    score: Number(s.score || 1),
    duration_minutes: Number(s.duration_minutes || 0),
    dimensions: dimensionsFromTemplate(s),
  }))
  editing.value = true
}

function cloneTemplate(t: ExamTemplate) {
  loadTemplate(t, true)
}

function editTemplate(t: ExamTemplate) {
  if (t.is_builtin) return
  loadTemplate(t, false)
}

function addSection() {
  form.sections.push({
    type: 'short_answer',
    name: QUESTION_TYPE_LABEL.short_answer,
    count: 2,
    score: 10,
    duration_minutes: 0,
    dimensions: defaultDimensions('short_answer'),
  })
}

function addDimension(s: EditorSection) {
  s.dimensions.push({ label: '', weight: 20 })
}

function removeDimension(s: EditorSection, i: number) {
  s.dimensions.splice(i, 1)
}

function removeSection(i: number) {
  form.sections.splice(i, 1)
}

function onTypeChange(s: EditorSection) {
  s.name = QUESTION_TYPE_LABEL[s.type] || s.name
  // 主观题默认分值更高，并带出评分维度
  if (SUBJECTIVE_TYPES.includes(s.type)) {
    if (s.score < 5) s.score = 10
    if (!s.dimensions.length) s.dimensions = defaultDimensions(s.type)
  } else {
    s.dimensions = []
  }
}

function splitTerms(text: string): string[] {
  return text
    .split(/[、,，;；\n]+/)
    .map((x) => x.trim())
    .filter(Boolean)
}

function parseSubjectMinima(text: string): Array<{ name: string; min_score: number }> {
  const rows: Array<{ name: string; min_score: number }> = []
  for (const part of splitTerms(text)) {
    const [name, score] = part.split(/[:：]/)
    if (!name?.trim()) continue
    const min = Number(score)
    if (Number.isFinite(min) && min >= 0) {
      rows.push({ name: name.trim(), min_score: min })
    }
  }
  return rows
}

async function save() {
  if (!form.name.trim()) {
    toast.error('请填写模板名称')
    return
  }
  if (!form.sections.length || totalQuestions.value <= 0) {
    toast.error('至少配置一种题型，且题目数量大于 0')
    return
  }
  const sections: ExamTemplateSection[] = form.sections.map((s) => ({
    type: s.type,
    name: s.name || QUESTION_TYPE_LABEL[s.type],
    count: Number(s.count),
    score: Number(s.score),
    duration_minutes: Number(s.duration_minutes || 0),
    scoring:
      SUBJECTIVE_TYPES.includes(s.type) && s.dimensions.length
        ? {
            dimensions: s.dimensions
              .filter((d) => d.label.trim())
              .map((d, i) => ({
                key: `dim_${i + 1}`,
                label: d.label.trim(),
                weight: Number(d.weight) || 1,
                description: '',
              })),
          }
        : undefined,
  }))
  const basic = Number(form.difficulty_basic) || 0
  const medium = Number(form.difficulty_medium) || 0
  const hard = Number(form.difficulty_hard) || 0
  const diffTotal = basic + medium + hard || 100
  const subjects = parseSubjectMinima(form.subject_minima)
  const payload: Partial<ExamTemplate> = {
    name: form.name.trim(),
    code: form.code.trim() || undefined,
    description: form.description.trim(),
    question_types: sections,
    duration_minutes: Number(form.duration_minutes),
    passing_criteria: {
      total: Number(form.passing_total) || Math.round(totalScore.value * 0.6),
      ...(subjects.length ? { subjects } : {}),
    },
    scoring_rules: {},
    difficulty_distribution: {
      basic: Math.round((basic / diffTotal) * 100) / 100,
      medium: Math.round((medium / diffTotal) * 100) / 100,
      hard: Math.round((hard / diffTotal) * 100) / 100,
    },
    coverage_domains: splitTerms(form.coverage_domains),
  }
  saving.value = true
  try {
    if (editingId.value) {
      await study.updateTemplate(editingId.value, payload)
      toast.success('模板已更新')
    } else {
      await study.createTemplate(payload)
      toast.success('自定义模板已创建')
    }
    editing.value = false
  } catch (e: any) {
    toast.error(e.message || '保存模板失败')
  } finally {
    saving.value = false
  }
}

async function remove(t: ExamTemplate) {
  if (!window.confirm(`确定删除自定义模板「${t.name}」？已生成的试卷不受影响。`)) return
  try {
    await study.deleteTemplate(t.id)
    toast.success('已删除模板')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

onMounted(() => {
  if (!study.templates.length) study.loadTemplates()
  resetForm()
})
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 grid place-items-center bg-slate-900/30 backdrop-blur-sm p-4"
      @click.self="emit('close')"
    >
      <div class="w-[min(94vw,860px)] max-h-[88vh] flex flex-col rounded-2xl bg-white shadow-2xl border border-slate-200 overflow-hidden animate-fade-up">
        <!-- 头 -->
        <div class="shrink-0 flex items-center gap-3 px-6 py-4 border-b border-slate-200/70">
          <span class="w-9 h-9 rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white grid place-items-center">
            <KiwiIcon name="layoutTemplate" :size="17" />
          </span>
          <div class="flex-1">
            <h3 class="font-semibold text-slate-800">考试场景模板</h3>
            <p class="text-[11px] text-slate-400">模板决定题型配比、分值、时长与及格标准；内置模板不可修改</p>
          </div>
          <button class="kiwi-btn-ghost !p-1.5" @click="emit('close')">
            <KiwiIcon name="close" :size="17" />
          </button>
        </div>

        <!-- 模板列表 -->
        <div v-if="!editing" class="flex-1 min-h-0 overflow-y-auto p-6">
          <div class="flex items-center justify-between mb-3">
            <p class="text-xs text-slate-400">共 {{ study.templates.length }} 套模板</p>
            <button class="kiwi-btn-primary !py-2 !text-xs" @click="resetForm(); editing = true">
              <KiwiIcon name="plus" :size="13" />
              新建自定义模板
            </button>
          </div>

          <div class="grid sm:grid-cols-2 gap-3">
            <div
              v-for="t in study.templates"
              :key="t.id"
              class="rounded-xl border border-slate-200/70 p-4 hover:border-kiwi-200 transition-colors"
            >
              <div class="flex items-start gap-2 mb-1.5">
                <p class="text-sm font-semibold text-slate-700 flex-1">{{ t.name }}</p>
                <span
                  class="px-1.5 py-0.5 rounded text-[10px] shrink-0"
                  :class="t.is_builtin ? 'bg-kiwi-50 text-kiwi-600' : 'bg-violet-50 text-violet-600'"
                >
                  {{ t.is_builtin ? '内置' : '自定义' }}
                </span>
              </div>
              <p class="text-[11px] text-slate-400 leading-relaxed line-clamp-2 mb-2.5 min-h-[30px]">
                {{ t.description || '自定义考试场景' }}
              </p>
              <div class="flex flex-wrap gap-1 mb-3">
                <span
                  v-for="s in t.question_types.slice(0, 4)"
                  :key="s.type + s.name"
                  class="px-1.5 py-0.5 rounded bg-slate-50 border border-slate-200/60 text-[10px] text-slate-500"
                >
                  {{ s.name || QUESTION_TYPE_LABEL[s.type] }} {{ s.count }}
                </span>
                <span v-if="t.question_types.length > 4" class="text-[10px] text-slate-400 self-center">
                  +{{ t.question_types.length - 4 }}
                </span>
              </div>
              <div class="flex items-center justify-between text-[10px] text-slate-400">
                <span>{{ t.duration_minutes }} 分钟 · 及格 {{ t.passing_criteria?.total ?? '—' }}</span>
                <div class="flex items-center gap-1">
                  <button class="text-kiwi-600 hover:text-kiwi-700 font-medium" @click="cloneTemplate(t)">
                    以此为模板新建
                  </button>
                  <template v-if="!t.is_builtin">
                    <span class="text-slate-200">|</span>
                    <button class="hover:text-slate-700" @click="editTemplate(t)">编辑</button>
                    <span class="text-slate-200">|</span>
                    <button class="hover:text-rose-500" @click="remove(t)">删除</button>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 编辑器 -->
        <div v-else class="flex-1 min-h-0 overflow-y-auto p-6">
          <div class="flex items-center gap-3 mb-4">
            <button class="kiwi-btn-ghost !p-1" @click="editing = false">
              <KiwiIcon name="arrowLeft" :size="15" />
            </button>
            <p class="text-sm font-semibold text-slate-700">
              {{ editingId ? '编辑自定义模板' : '新建自定义模板' }}
            </p>
          </div>

          <div class="grid md:grid-cols-2 gap-3 mb-4">
            <label class="block">
              <span class="text-xs text-slate-500 mb-1 block">模板名称 *</span>
              <input v-model="form.name" class="kiwi-input text-sm" placeholder="如：我的高项冲刺卷" />
            </label>
            <label class="block">
              <span class="text-xs text-slate-500 mb-1 block">模板代码（可选）</span>
              <input v-model="form.code" class="kiwi-input text-sm" placeholder="如：my_gaoxiang" />
            </label>
            <label class="block md:col-span-2">
              <span class="text-xs text-slate-500 mb-1 block">说明</span>
              <input v-model="form.description" class="kiwi-input text-sm" placeholder="这套模板适用的考试与特点" />
            </label>
            <label class="block">
              <span class="text-xs text-slate-500 mb-1 block">考试时长（分钟）</span>
              <input v-model.number="form.duration_minutes" type="number" min="5" max="1440" class="kiwi-input text-sm" />
            </label>
            <label class="block">
              <span class="text-xs text-slate-500 mb-1 block">及格总分</span>
              <input v-model.number="form.passing_total" type="number" min="0" class="kiwi-input text-sm" />
            </label>
            <label class="block md:col-span-2">
              <span class="text-xs text-slate-500 mb-1 block">知识域覆盖要求（顿号分隔，可留空）</span>
              <input
                v-model="form.coverage_domains"
                class="kiwi-input text-sm"
                placeholder="如：项目管理、信息系统、法律法规；组卷时优先覆盖这些领域"
              />
            </label>
            <label class="block md:col-span-2">
              <span class="text-xs text-slate-500 mb-1 block">分卷最低分（可选，格式：题型名称:最低分）</span>
              <input
                v-model="form.subject_minima"
                class="kiwi-input text-sm"
                placeholder="如：案例分析:15、论文:20；未达到则整卷判定不合格"
              />
            </label>
          </div>

          <div class="mb-4">
            <p class="text-xs text-slate-500 mb-1.5">难度分布（相对权重）</p>
            <div class="grid grid-cols-3 gap-2">
              <label class="flex items-center gap-2 rounded-lg border border-slate-200/70 px-2.5 py-2">
                <span class="text-[11px] text-slate-500 flex-1">基础</span>
                <input v-model.number="form.difficulty_basic" type="number" min="0" class="kiwi-input !py-1 !px-2 !text-xs w-16" />
              </label>
              <label class="flex items-center gap-2 rounded-lg border border-slate-200/70 px-2.5 py-2">
                <span class="text-[11px] text-slate-500 flex-1">进阶</span>
                <input v-model.number="form.difficulty_medium" type="number" min="0" class="kiwi-input !py-1 !px-2 !text-xs w-16" />
              </label>
              <label class="flex items-center gap-2 rounded-lg border border-slate-200/70 px-2.5 py-2">
                <span class="text-[11px] text-slate-500 flex-1">挑战</span>
                <input v-model.number="form.difficulty_hard" type="number" min="0" class="kiwi-input !py-1 !px-2 !text-xs w-16" />
              </label>
            </div>
          </div>

          <div class="flex items-center justify-between mb-2">
            <p class="text-xs font-medium text-slate-500">题型与分值配置</p>
            <button class="kiwi-btn-secondary !py-1.5 !text-xs" @click="addSection">
              <KiwiIcon name="plus" :size="12" />
              添加题型
            </button>
          </div>

          <div class="rounded-xl border border-slate-200/70 overflow-hidden">
            <div class="grid grid-cols-[1.3fr_1.3fr_0.7fr_0.7fr_2.4rem] gap-2 px-3 py-2 bg-slate-50/80 text-[10px] text-slate-400 font-medium">
              <span>题型</span>
              <span>分卷名称</span>
              <span>题数</span>
              <span>每题分值</span>
              <span />
            </div>
            <div v-for="(s, i) in form.sections" :key="i" class="border-t border-slate-100">
              <div class="grid grid-cols-[1.3fr_1.3fr_0.7fr_0.7fr_2.4rem] gap-2 px-3 py-2 items-center">
                <select v-model="s.type" class="kiwi-input !py-1.5 !text-xs" @change="onTypeChange(s)">
                  <option v-for="t in TYPE_OPTIONS" :key="t" :value="t">{{ QUESTION_TYPE_LABEL[t] }}</option>
                </select>
                <input v-model="s.name" class="kiwi-input !py-1.5 !text-xs" />
                <input v-model.number="s.count" type="number" min="1" max="200" class="kiwi-input !py-1.5 !text-xs" />
                <input v-model.number="s.score" type="number" min="0.5" step="0.5" class="kiwi-input !py-1.5 !text-xs" />
                <button class="text-slate-300 hover:text-rose-500 transition-colors" @click="removeSection(i)">
                  <KiwiIcon name="trash" :size="13" />
                </button>
              </div>
              <div
                v-if="SUBJECTIVE_TYPES.includes(s.type)"
                class="px-3 pb-2.5 space-y-1.5"
              >
                <div class="flex items-center gap-2">
                  <span class="text-[10px] text-slate-400">评分维度</span>
                  <button class="text-[10px] text-kiwi-600 hover:text-kiwi-700" @click="addDimension(s)">
                    + 添加维度
                  </button>
                </div>
                <div v-for="(d, di) in s.dimensions" :key="di" class="flex items-center gap-1.5">
                  <input
                    v-model="d.label"
                    class="kiwi-input !py-1 !px-2 !text-[11px] flex-1"
                    placeholder="维度名称，如：分析深度"
                  />
                  <span class="text-[10px] text-slate-400">权重</span>
                  <input
                    v-model.number="d.weight"
                    type="number"
                    min="1"
                    class="kiwi-input !py-1 !px-2 !text-[11px] w-16"
                  />
                  <button class="text-slate-300 hover:text-rose-500" @click="removeDimension(s, di)">
                    <KiwiIcon name="close" :size="11" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div class="flex items-center gap-4 mt-3 text-[11px] text-slate-400">
            <span>共 <b class="text-slate-600">{{ totalQuestions }}</b> 题</span>
            <span>满分 <b class="text-slate-600">{{ totalScore }}</b> 分</span>
            <span>及格线 <b class="text-slate-600">{{ form.passing_total }}</b> 分</span>
          </div>

          <div class="rounded-xl bg-amber-50/60 border border-amber-100 p-3 mt-4">
            <p class="text-[11px] text-amber-700/90 leading-relaxed">
              组卷时系统会按题型从知识库页面出题，并按难度分布混合基础、进阶和挑战题。
              主观题数量越多，组卷与批阅耗时越长。
            </p>
          </div>
        </div>

        <!-- 底 -->
        <div class="shrink-0 flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-200/70 bg-slate-50/40">
          <template v-if="editing">
            <button class="kiwi-btn-secondary !py-2" @click="editing = false">取消</button>
            <button class="kiwi-btn-primary !py-2" :disabled="saving" @click="save">
              <KiwiIcon v-if="saving" name="loader" :size="14" spin />
              <KiwiIcon v-else name="check" :size="14" />
              保存模板
            </button>
          </template>
          <button v-else class="kiwi-btn-secondary !py-2" @click="emit('close')">关闭</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
