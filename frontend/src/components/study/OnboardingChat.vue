<script setup lang="ts">
// OnboardingChat：学习冷启动对话 —— LLM 引导采集目标/水平/时间/偏好，失败时自动退化为脚本提问。
// 完成后写入画像；也可跳过对话直接使用默认画像。
import { computed, nextTick, onMounted, ref } from 'vue'
import { useStudyStore, type OnboardingMessage } from '@/stores/study'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { toast } from '@/components/ui/toast'

const emit = defineEmits<{
  (e: 'done'): void
  (e: 'open-form'): void
}>()

const study = useStudyStore()
const messages = ref<OnboardingMessage[]>([])
const draft = ref<Record<string, unknown>>({})
const input = ref('')
const sending = ref(false)
const finishing = ref(false)
const lastTurnDone = ref(false)
const scrollEl = ref<HTMLDivElement>()
const inputEl = ref<HTMLTextAreaElement>()

const userTurns = computed(() => messages.value.filter((m) => m.role === 'user').length)
const canFinish = computed(() => userTurns.value > 0 || lastTurnDone.value)

const GOAL_LABEL: Record<string, string> = {
  exam: '考试导向',
  domain: '领域掌握',
  explore: '兴趣探索',
}
const LEVEL_LABEL: Record<string, string> = {
  beginner: '入门',
  foundation: '进阶',
  advanced: '熟练',
}
const MODE_LABEL: Record<string, string> = {
  auto: '系统安排',
  drill: '渐进训练',
  mock: '仿真考试',
}

const draftChips = computed(() => {
  const d = draft.value as Record<string, any>
  const chips: Array<{ key: string; text: string }> = []
  if (d.goal_type) chips.push({ key: 'goal', text: GOAL_LABEL[d.goal_type] || d.goal_type })
  if (d.level_prior) chips.push({ key: 'level', text: LEVEL_LABEL[d.level_prior] || d.level_prior })
  if (d.daily_minutes) chips.push({ key: 'minutes', text: `每日 ${d.daily_minutes} 分钟` })
  if (d.target_date) chips.push({ key: 'date', text: `目标 ${d.target_date}` })
  if (d.preferred_mode) chips.push({ key: 'mode', text: MODE_LABEL[d.preferred_mode] || d.preferred_mode })
  for (const t of d.weak_areas || []) chips.push({ key: `weak:${t}`, text: `薄弱：${t}` })
  for (const t of d.topics_focus || []) chips.push({ key: `focus:${t}`, text: `关注：${t}` })
  return chips
})

function mergePatch(patch: Record<string, unknown>) {
  const next = { ...draft.value }
  for (const [k, v] of Object.entries(patch || {})) {
    if (v === null || v === undefined || v === '') continue
    if (Array.isArray(v) && !v.length) continue
    next[k] = v
  }
  draft.value = next
}

async function scrollBottom() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function intro() {
  try {
    const res = await study.onboardingTurn([])
    messages.value.push({ role: 'assistant', content: res.reply })
    mergePatch(res.profile_patch)
    lastTurnDone.value = res.done
  } catch (e: any) {
    messages.value.push({
      role: 'assistant',
      content: e.message || '冷启动对话暂时不可用，你可以直接点击“跳过对话，快速开始”。',
    })
  }
  scrollBottom()
}

async function send(preset?: string) {
  const text = preset?.trim() || input.value.trim()
  if (!text || sending.value) return
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  sending.value = true
  scrollBottom()
  try {
    const res = await study.onboardingTurn(messages.value, draft.value)
    messages.value.push({ role: 'assistant', content: res.reply })
    mergePatch(res.profile_patch)
    lastTurnDone.value = res.done
  } catch (e: any) {
    toast.error(e.message || '发送失败')
    messages.value.push({
      role: 'assistant',
      content: '刚才没能连上教练服务，你可以再试一次，或直接点击“跳过对话，快速开始”。',
    })
  } finally {
    sending.value = false
    scrollBottom()
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void send()
  }
}

async function finish(quick = false) {
  if (finishing.value) return
  finishing.value = true
  try {
    const d = draft.value as Record<string, any>
    const payload: Record<string, unknown> = quick
      ? {
          goal_type: 'domain',
          level_prior: 'beginner',
          daily_minutes: 30,
          preferred_mode: 'auto',
          onboarded: true,
        }
      : {
          goal_type: d.goal_type || 'domain',
          level_prior: d.level_prior || 'beginner',
          daily_minutes: d.daily_minutes || 30,
          topics_focus: d.topics_focus || [],
          weak_areas: d.weak_areas || [],
          preferred_mode: d.preferred_mode || 'auto',
          target_date: d.target_date || null,
          exam_template_id: d.exam_template_id || null,
          onboarded: true,
        }
    await study.completeOnboarding(
      payload as any,
      quick ? [] : messages.value,
      quick,
    )
    toast.success(quick ? '已使用默认画像开始' : '画像已生成，开始学习吧')
    emit('done')
  } catch (e: any) {
    toast.error(e.message || '生成画像失败')
  } finally {
    finishing.value = false
  }
}

onMounted(() => {
  void intro()
  inputEl.value?.focus()
})
</script>

<template>
  <div class="h-full min-h-0 flex flex-col animate-fade-up">
    <!-- 顶部说明 -->
    <div class="shrink-0 flex items-start gap-3 mb-4">
      <span
        class="w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white grid place-items-center shadow-glow"
      >
        <KiwiIcon name="smile" :size="19" />
      </span>
      <div class="min-w-0">
        <h3 class="font-semibold text-slate-800">先聊聊你的学习目标</h3>
        <p class="text-xs text-slate-400 mt-0.5 leading-relaxed">
          Kiwi 会据此选择考试模板、安排难度与复习节奏。对话只用于生成本地学习画像。
        </p>
      </div>
    </div>

    <div class="flex-1 min-h-0 flex gap-4">
      <!-- 对话区 -->
      <div class="flex-1 min-w-0 flex flex-col kiwi-card overflow-hidden">
        <div ref="scrollEl" class="flex-1 min-h-0 overflow-y-auto p-5 space-y-4">
          <div
            v-for="(m, i) in messages"
            :key="i"
            class="flex"
            :class="m.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div
              class="max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap"
              :class="
                m.role === 'user'
                  ? 'bg-gradient-to-br from-kiwi-500 to-kiwi-700 text-white rounded-br-md'
                  : 'bg-slate-50 border border-slate-200/70 text-slate-700 rounded-bl-md'
              "
            >
              {{ m.content }}
            </div>
          </div>

          <div v-if="!messages.length" class="flex items-center gap-2 text-xs text-slate-400">
            <KiwiIcon name="loader" :size="14" spin />
            正在读取知识库概况…
          </div>

          <div v-if="sending" class="flex justify-start">
            <div class="rounded-2xl rounded-bl-md bg-slate-50 border border-slate-200/70 px-4 py-3">
              <span class="inline-flex gap-1">
                <span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" />
                <span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style="animation-delay: 120ms" />
                <span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style="animation-delay: 240ms" />
              </span>
            </div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="shrink-0 border-t border-slate-200/60 p-3.5">
          <div class="flex items-end gap-2">
            <textarea
              ref="inputEl"
              v-model="input"
              rows="2"
              class="kiwi-input resize-none flex-1 !py-2.5 text-sm"
              placeholder="说说你的目标、考试名称、可投入时间…（Enter 发送，Shift+Enter 换行）"
              :disabled="sending"
              @keydown="onKeydown"
            />
            <button
              class="kiwi-btn-primary shrink-0 !px-3.5 !py-2.5"
              :disabled="!input.trim() || sending"
              @click="send()"
            >
              <KiwiIcon name="send" :size="15" />
            </button>
          </div>
          <div class="flex items-center justify-between mt-2.5 px-0.5">
            <div class="flex items-center gap-3">
              <button
                class="text-xs text-slate-400 hover:text-kiwi-600 transition-colors"
                @click="emit('open-form')"
              >
                直接填写画像表单 →
              </button>
              <button
                class="text-xs text-slate-400 hover:text-kiwi-600 transition-colors"
                :disabled="sending || lastTurnDone"
                @click="send('（跳过这个问题，请继续下一个问题）')"
              >
                跳过这个问题
              </button>
            </div>
            <span class="text-[10px] text-slate-300">{{ userTurns }} 轮对话</span>
          </div>
        </div>
      </div>

      <!-- 采集摘要 -->
      <aside class="w-64 shrink-0 hidden xl:flex flex-col gap-3">
        <div class="kiwi-card p-4">
          <p class="text-xs font-medium text-slate-500 mb-2.5 flex items-center gap-1.5">
            <KiwiIcon name="sparkle" :size="12" class="text-kiwi-500" />
            已识别的信息
          </p>
          <div v-if="draftChips.length" class="flex flex-wrap gap-1.5">
            <span
              v-for="c in draftChips"
              :key="c.key"
              class="px-2 py-1 rounded-lg bg-kiwi-50 border border-kiwi-100 text-[11px] text-kiwi-700"
            >
              {{ c.text }}
            </span>
          </div>
          <p v-else class="text-[11px] text-slate-400 leading-relaxed">
            对话中提到的目标、水平、时长会实时出现在这里。
          </p>
        </div>

        <div class="kiwi-card p-4 space-y-2">
          <button
            class="w-full kiwi-btn-primary !py-2.5 text-sm"
            :disabled="!canFinish || finishing"
            @click="finish(false)"
          >
            <KiwiIcon v-if="finishing" name="loader" :size="14" spin />
            <KiwiIcon v-else name="check" :size="14" />
            生成画像并开始
          </button>
          <button
            class="w-full kiwi-btn-secondary !py-2 text-xs"
            :disabled="finishing"
            @click="finish(true)"
          >
            跳过对话，快速开始
          </button>
          <p class="text-[10px] text-slate-300 leading-relaxed pt-1">
            快速开始使用「领域掌握 · 入门 · 每日 30 分钟 · 系统安排」。
          </p>
        </div>
      </aside>
    </div>
  </div>
</template>
