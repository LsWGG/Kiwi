<script setup lang="ts">
/**
 * 知识库问答：单库 / 多库 / 全局范围、Wiki/Raw 意图路由、多轮对话、
 * 可点击引用、页面级模型覆盖与「回写为 Wiki 综合页」。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useKbsStore } from '@/stores/kbs'
import { useLlmStore } from '@/stores/llm'
import { openSSE } from '@/api/sse'
import { request } from '@/api/client'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import { toast } from '@/components/ui/toast'

interface Citation {
  kb_id: string
  kb_name: string
  collection: string
  title: string
  chunk_text: string
  target_id: string
}

interface Msg {
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  streaming?: boolean
}

type ScopeMode = 'kb' | 'multi' | 'global'
type Intent = 'auto' | 'wiki' | 'raw'

const STORAGE_KEY = 'kiwi.chat.state.v1'

const kbs = useKbsStore()
const llm = useLlmStore()
const router = useRouter()

const messages = ref<Msg[]>([])
const input = ref('')
const streaming = ref(false)
const scrollEl = ref<HTMLElement>()
const autoScroll = ref(true)

const scopeMode = ref<ScopeMode>('kb')
const multiIds = ref<string[]>([])
const intent = ref<Intent>('auto')
const llmConfigId = ref('')
const scopeMenuOpen = ref(false)

// ---------- 会话持久化（视图切换不丢上下文） ----------
function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw) as {
      messages?: Msg[]
      scopeMode?: ScopeMode
      multiIds?: string[]
      intent?: Intent
    }
    if (Array.isArray(saved.messages)) {
      messages.value = saved.messages
        .filter((m) => m && (m.role === 'user' || m.role === 'assistant'))
        .map((m) => ({ ...m, streaming: false }))
    }
    if (saved.scopeMode) scopeMode.value = saved.scopeMode
    if (Array.isArray(saved.multiIds)) multiIds.value = saved.multiIds
    if (saved.intent) intent.value = saved.intent
  } catch {
    /* 隐私模式忽略 */
  }
}

function saveState() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        messages: messages.value.filter((m) => m.content.trim() || !m.streaming),
        scopeMode: scopeMode.value,
        multiIds: multiIds.value,
        intent: intent.value,
      }),
    )
  } catch {
    /* 忽略配额错误 */
  }
}

watch(messages, saveState, { deep: true })
watch([scopeMode, intent, multiIds], saveState, { deep: true })

onMounted(async () => {
  loadState()
  if (!llm.configs.length) void llm.fetchConfigs().catch(() => undefined)
  if (!kbs.kbs.length) void kbs.fetchKbs().catch(() => undefined)
  scrollToBottom(true)
})
onUnmounted(saveState)

// ---------- 展示 ----------
function pushUser(text: string) {
  messages.value.push({ role: 'user', content: text, citations: [] })
}

function pushAssistant() {
  const msg: Msg = { role: 'assistant', content: '', citations: [], streaming: true }
  messages.value.push(msg)
  return msg
}

function scrollToBottom(force = false) {
  if (!autoScroll.value && !force) return
  void nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
}

function onScroll() {
  if (!scrollEl.value) return
  const el = scrollEl.value
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

const scopeKbIds = computed(() => {
  if (scopeMode.value === 'global') return []
  if (scopeMode.value === 'multi') return multiIds.value
  return kbs.currentKbId ? [kbs.currentKbId] : []
})

function requestScope() {
  return {
    kb_ids: scopeKbIds.value,
    scope: scopeMode.value,
  }
}

function validateScope(): boolean {
  if (scopeMode.value === 'global') return true
  if (scopeMode.value === 'multi' && !multiIds.value.length) {
    toast.info('请勾选至少一个知识库')
    return false
  }
  if (scopeMode.value === 'kb' && !kbs.currentKbId) {
    toast.info('请先选择一个知识库')
    return false
  }
  return true
}

function toggleMultiKb(id: string) {
  const index = multiIds.value.indexOf(id)
  if (index >= 0) multiIds.value.splice(index, 1)
  else multiIds.value.push(id)
  scopeMode.value = 'multi'
}

const scopeLabel = computed(() => {
  if (scopeMode.value === 'global') return '全局（全部知识库）'
  if (scopeMode.value === 'multi') {
    if (!multiIds.value.length) return '多库（未选择）'
    return `多库（${multiIds.value.length} 个）`
  }
  return kbs.currentKb?.name || '未选择知识库'
})

const intentOptions: { id: Intent; label: string; hint: string }[] = [
  { id: 'auto', label: '自动路由', hint: '按问题类型自动选择 Wiki 优先或原文优先' },
  { id: 'wiki', label: 'Wiki 优先', hint: '概念解释、综合对比，沿链接扩展 1-2 跳' },
  { id: 'raw', label: '原文优先', hint: '精确引用、事实核验，优先检索原始素材' },
]

function historyMessages() {
  return messages.value
    .filter((m) => !m.streaming && m.content.trim())
    .slice(-12)
    .map((m) => ({ role: m.role, content: m.content }))
}

// ---------- 提问 ----------
function ask() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  if (!validateScope()) return
  input.value = ''
  pushUser(text)
  const payloadMessages = historyMessages()
  const assistant = pushAssistant()
  streaming.value = true
  autoScroll.value = true
  scrollToBottom(true)

  openSSE(
    '/chat/stream',
    {
      messages: payloadMessages,
      scope: requestScope(),
      intent: intent.value,
      llm_config_id: llmConfigId.value || null,
    },
    {
      onMessage: (msg) => {
        if (msg.event === 'chunk') {
          assistant.content += msg.data?.text ?? ''
          scrollToBottom()
        } else if (msg.event === 'citation') {
          assistant.citations = msg.data?.citations ?? []
        } else if (msg.event === 'done') {
          assistant.streaming = false
          streaming.value = false
          scrollToBottom(true)
        } else if (msg.event === 'error') {
          assistant.content += `\n\n⚠️ ${msg.data?.message ?? '出错了'}`
          assistant.streaming = false
          streaming.value = false
        }
      },
      onError: (e) => {
        assistant.content += `\n\n⚠️ 连接失败：${e.message}`
        assistant.streaming = false
        streaming.value = false
      },
    },
  )
}

function clearChat() {
  if (streaming.value) return
  messages.value = []
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* 忽略 */
  }
}

const suggestions = [
  { icon: 'search', text: '这个知识库里有什么？' },
  { icon: 'sparkle', text: '总结最近的 Wiki 内容' },
  { icon: 'link2', text: '查找关于…的原文出处' },
]

function suggest(q: { text: string }) {
  input.value = q.text
  ask()
}

const canSend = computed(() => input.value.trim().length > 0 && !streaming.value)

// ---------- 引用跳转 ----------
function openCitation(citation: Citation) {
  if (citation.collection === 'wiki' && citation.target_id) {
    void router.push({ name: 'wiki-page', params: { id: citation.target_id } })
  } else if (citation.collection === 'raw' && citation.target_id) {
    void router.push({ name: 'source-preview', params: { id: citation.target_id } })
  }
}

// ---------- 回写为 Wiki 综合页 ----------
const writebackOpen = ref(false)
const writebackMsg = ref<Msg | null>(null)
const writebackTitle = ref('')
const writebackKbId = ref('')
const writebackSaving = ref(false)

function openWriteback(msg: Msg) {
  if (!msg.content.trim()) return
  writebackMsg.value = msg
  writebackKbId.value = msg.citations[0]?.kb_id || kbs.currentKbId || ''
  const index = messages.value.indexOf(msg)
  const question =
    [...messages.value.slice(0, index)]
      .reverse()
      .find((m) => m.role === 'user')?.content || '知识库问答'
  writebackTitle.value = `问答总结：${question.replace(/\s+/g, ' ').slice(0, 40)}`
  writebackOpen.value = true
}

function citationMarkdown(msg: Msg): string {
  if (!msg.citations.length) return ''
  const lines = msg.citations.map((c, i) => {
    const kind = c.collection === 'wiki' ? 'Wiki' : '原文'
    const href =
      c.collection === 'wiki' ? `/wiki/${c.target_id}` : `/sources/${c.target_id}`
    return `${i + 1}. [${kind}：${c.title}](${href})` + (c.kb_name ? `（${c.kb_name}）` : '')
  })
  return `\n\n---\n\n## 引用来源\n\n${lines.join('\n')}`
}

async function saveWriteback() {
  const msg = writebackMsg.value
  const title = writebackTitle.value.trim()
  if (!msg || !title) {
    toast.info('请填写页面标题')
    return
  }
  if (!writebackKbId.value) {
    toast.info('请选择回写的知识库')
    return
  }
  writebackSaving.value = true
  try {
    const page = await request<{ id: string }>('/wiki', {
      method: 'POST',
      kbId: writebackKbId.value,
      body: JSON.stringify({
        title,
        body_md: msg.content + citationMarkdown(msg),
        page_type: 'synthesis',
        tags: ['问答回写'],
      }),
    })
    writebackOpen.value = false
    toast.success('已回写为 Wiki 综合页')
    void router.push({ name: 'wiki-page', params: { id: page.id } })
  } catch (e: any) {
    toast.error(e.message || '回写失败')
  } finally {
    writebackSaving.value = false
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- 范围 / 意图 / 模型 -->
    <header class="shrink-0 border-b border-slate-200/60 bg-white/50 px-4 py-2">
      <div class="mx-auto flex w-full max-w-[960px] flex-wrap items-center gap-2">
        <div class="relative">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white/80 px-2.5 py-1 text-[11px] text-slate-600 hover:border-kiwi-300 hover:text-kiwi-700"
            @click="scopeMenuOpen = !scopeMenuOpen"
          >
            <KiwiIcon name="database" :size="12" class="text-slate-400" />
            范围：{{ scopeLabel }}
            <KiwiIcon name="chevron" :size="11" class="text-slate-400" />
          </button>
          <div
            v-if="scopeMenuOpen"
            class="absolute left-0 top-full z-30 mt-1 w-72 rounded-xl border border-slate-200 bg-white p-2 shadow-lifted"
          >
            <div class="mb-1 flex rounded-lg bg-slate-100 p-0.5 text-[10.5px]">
              <button
                v-for="mode in (['kb', 'multi', 'global'] as ScopeMode[])"
                :key="mode"
                type="button"
                class="flex-1 rounded-md px-2 py-1"
                :class="scopeMode === mode ? 'bg-white font-medium text-kiwi-700 shadow-sm' : 'text-slate-500'"
                @click="scopeMode = mode"
              >
                {{ mode === 'kb' ? '单库' : mode === 'multi' ? '多库' : '全局' }}
              </button>
            </div>
            <template v-if="scopeMode === 'multi'">
              <p class="px-1 pb-1 text-[10px] text-slate-400">勾选要一起检索的知识库</p>
              <label
                v-for="kb in kbs.kbs"
                :key="kb.id"
                class="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-[11.5px] text-slate-600 hover:bg-kiwi-50/60"
              >
                <input
                  type="checkbox"
                  :checked="multiIds.includes(kb.id)"
                  @change="toggleMultiKb(kb.id)"
                />
                <span class="truncate">{{ kb.name }}</span>
                <span class="ml-auto text-[9.5px] text-slate-400">{{ kb.wiki_count }} Wiki</span>
              </label>
            </template>
            <template v-else-if="scopeMode === 'kb'">
              <button
                v-for="kb in kbs.kbs"
                :key="kb.id"
                type="button"
                class="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[11.5px] hover:bg-kiwi-50/60"
                :class="kbs.currentKbId === kb.id ? 'text-kiwi-700' : 'text-slate-600'"
                @click="kbs.currentKbId = kb.id"
              >
                <span class="truncate">{{ kb.name }}</span>
                <KiwiIcon
                  v-if="kbs.currentKbId === kb.id"
                  name="check"
                  :size="11"
                  class="ml-auto text-kiwi-500"
                />
              </button>
            </template>
            <p v-else class="px-2 py-1 text-[10.5px] leading-relaxed text-slate-400">
              在所有知识库中检索，引用卡片会标注来源库名称。
            </p>
            <button
              type="button"
              class="mt-1 w-full rounded-md bg-slate-50 py-1 text-[10.5px] text-slate-500 hover:bg-slate-100"
              @click="scopeMenuOpen = false"
            >
              完成
            </button>
          </div>
        </div>

        <select v-model="intent" class="kiwi-input !w-auto !py-1 !text-[11px]">
          <option v-for="opt in intentOptions" :key="opt.id" :value="opt.id" :title="opt.hint">
            {{ opt.label }}
          </option>
        </select>

        <select v-model="llmConfigId" class="kiwi-input !w-auto !py-1 !text-[11px]" title="仅本次对话覆盖模型">
          <option value="">默认模型</option>
          <option v-for="cfg in llm.configs" :key="cfg.id" :value="cfg.id">
            {{ cfg.name }} · {{ cfg.model_name }}
          </option>
        </select>

        <button
          v-if="messages.length"
          type="button"
          class="ml-auto inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[10.5px] text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          @click="clearChat"
        >
          <KiwiIcon name="plus" :size="11" />
          新对话
        </button>
      </div>
    </header>

    <!-- 消息区 -->
    <div ref="scrollEl" class="flex-1 overflow-y-auto px-6 py-6" @scroll="onScroll">
      <div class="mx-auto w-full space-y-5" style="max-width: min(960px, 100%)">
        <!-- 空态：建议 chips -->
        <div v-if="!messages.length" class="text-center pt-16 animate-fade-up">
          <div
            class="w-16 h-16 mx-auto rounded-2xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 grid place-items-center text-white shadow-glow mb-5"
          >
            <KiwiIcon name="chat" :size="28" />
          </div>
          <h2 class="text-lg font-semibold text-slate-700">向你的知识库提问</h2>
          <p class="text-sm text-slate-400 mt-1.5 mb-8">
            回答优先综合 Wiki 编译产物，并标注引用来源
          </p>
          <div class="flex flex-col sm:flex-row gap-3 items-center justify-center">
            <button
              v-for="(s, i) in suggestions"
              :key="i"
              class="px-4 py-2.5 rounded-2xl glass hover:border-kiwi-300 hover:shadow-lifted hover:-translate-y-0.5 text-sm text-slate-600 hover:text-kiwi-700 flex items-center gap-2 transition-all duration-200 animate-fade-up"
              :style="{ animationDelay: `${200 + i * 80}ms` }"
              @click="suggest(s)"
            >
              <KiwiIcon :name="s.icon" :size="14" class="text-kiwi-400" />
              {{ s.text }}
            </button>
          </div>
        </div>

        <!-- 消息气泡 -->
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="flex animate-message-in"
          :class="m.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div
            class="max-w-[85%] px-4 py-3 rounded-2xl text-sm leading-relaxed shadow-sm"
            :class="
              m.role === 'user'
                ? 'bg-gradient-to-br from-kiwi-500 to-kiwi-700 text-white rounded-br-md'
                : 'bg-white border border-slate-200 rounded-bl-md text-slate-700'
            "
          >
            <div v-if="m.role === 'user'" class="whitespace-pre-wrap">{{ m.content }}</div>
            <MarkdownView v-else :content="m.content" />
            <span
              v-if="m.streaming"
              class="inline-flex items-center gap-0.5 ml-1 align-baseline"
            >
              <span class="w-1 h-1 rounded-full bg-current animate-blink" :style="{ animationDelay: '0ms' }" />
              <span class="w-1 h-1 rounded-full bg-current animate-blink" :style="{ animationDelay: '200ms' }" />
              <span class="w-1 h-1 rounded-full bg-current animate-blink" :style="{ animationDelay: '400ms' }" />
            </span>
            <!-- 引用来源 -->
            <div
              v-if="m.citations?.length"
              class="mt-3 pt-2.5 border-t text-xs"
              :class="m.role === 'user' ? 'border-white/20' : 'border-slate-100'"
            >
              <p
                class="mb-1.5 flex items-center gap-1"
                :class="m.role === 'user' ? 'text-white/60' : 'text-slate-400'"
              >
                <KiwiIcon name="link2" :size="12" />
                引用来源
              </p>
              <div class="flex flex-wrap gap-1.5">
                <button
                  v-for="(c, ci) in m.citations"
                  :key="ci"
                  type="button"
                  class="rounded-lg px-2 py-0.5 transition-all duration-200 hover:shadow-soft"
                  :class="
                    m.role === 'user'
                      ? 'bg-white/15 text-white/90 hover:bg-white/25'
                      : 'bg-kiwi-50 text-kiwi-700 hover:bg-kiwi-100'
                  "
                  :title="c.chunk_text"
                  @click="openCitation(c)"
                >
                  {{ c.collection === 'wiki' ? 'Wiki' : '原文' }} · {{ c.title }}
                  <span v-if="c.kb_name" class="opacity-60">· {{ c.kb_name }}</span>
                </button>
              </div>
            </div>
            <!-- 回写 -->
            <div
              v-if="m.role === 'assistant' && !m.streaming && m.content.trim() && m.citations?.length"
              class="mt-2 flex justify-end"
            >
              <button
                type="button"
                class="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-kiwi-50 hover:text-kiwi-700"
                @click="openWriteback(m)"
              >
                <KiwiIcon name="wiki" :size="11" />
                回写为 Wiki 综合页
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="p-4 border-t border-slate-200/60 bg-white/55 backdrop-blur-xl">
      <div class="mx-auto w-full" style="max-width: min(960px, 100%)">
        <div
          class="flex items-end gap-2 rounded-2xl glass-strong p-2 focus-within:ring-2 focus-within:ring-kiwi-300/50 focus-within:border-kiwi-300 transition-all duration-200"
        >
          <textarea
            v-model="input"
            rows="1"
            placeholder="输入问题，Enter 发送（Shift+Enter 换行）…"
            class="flex-1 px-3 py-2 bg-transparent text-sm text-slate-700 placeholder:text-slate-400 outline-none resize-none max-h-32"
            @keydown.enter.exact.prevent="ask"
          />
          <button
            class="w-9 h-9 shrink-0 grid place-items-center rounded-xl text-white transition-all duration-200 disabled:opacity-35 disabled:pointer-events-none active:scale-95"
            :class="canSend ? 'bg-gradient-to-br from-kiwi-500 to-kiwi-700 shadow-glow hover:brightness-105' : 'bg-slate-300'"
            :disabled="!canSend"
            @click="ask"
            title="发送"
          >
            <KiwiIcon name="send" :size="15" />
          </button>
        </div>
        <p class="text-[11px] text-slate-400 mt-2 flex items-center gap-1">
          <span
            class="w-1.5 h-1.5 rounded-full inline-block animate-pulse-ring"
            :class="scopeMode === 'global' || kbs.currentKb ? 'bg-kiwi-500' : 'bg-slate-300'"
          />
          检索范围：{{ scopeLabel }}
          <span class="ml-auto">
            {{ intent === 'wiki' ? 'Wiki 优先' : intent === 'raw' ? '原文优先' : '自动路由' }}
          </span>
        </p>
      </div>
    </div>

    <!-- 回写确认 -->
    <KiwiModal :open="writebackOpen" title="回写为 Wiki 综合页" max-w="max-w-lg" @close="writebackOpen = false">
      <div class="space-y-3">
        <label class="block">
          <span class="mb-1 block text-[11px] font-medium text-slate-500">页面标题</span>
          <input v-model="writebackTitle" class="kiwi-input" placeholder="给这篇综合页起个标题" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[11px] font-medium text-slate-500">回写到知识库</span>
          <select v-model="writebackKbId" class="kiwi-input">
            <option v-for="kb in kbs.kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
          </select>
        </label>
        <div class="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2">
          <p class="mb-1 text-[10.5px] text-slate-400">将写入综合页正文，并附 {{ writebackMsg?.citations.length || 0 }} 条引用来源。</p>
          <div class="max-h-32 overflow-y-auto">
            <MarkdownView :content="writebackMsg?.content || ''" />
          </div>
        </div>
        <p class="text-[10px] leading-relaxed text-slate-400">
          回写页面标记为人工编辑，后续素材编译不会覆盖；可在 Wiki 中继续修改。
        </p>
      </div>
      <div class="mt-4 flex justify-end gap-2">
        <button type="button" class="kiwi-btn-secondary" @click="writebackOpen = false">取消</button>
        <button type="button" class="kiwi-btn-primary" :disabled="writebackSaving" @click="saveWriteback">
          <KiwiIcon :name="writebackSaving ? 'loader' : 'wiki'" :size="13" :spin="writebackSaving" />
          确认回写
        </button>
      </div>
    </KiwiModal>
  </div>
</template>

<style scoped>
@keyframes blink {
  0%, 100% { opacity: 0.2; }
  50% { opacity: 1; }
}
.animate-blink {
  animation: blink 1.2s ease-in-out infinite;
}
@keyframes message-in {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.animate-message-in {
  animation: message-in 0.3s cubic-bezier(0.21, 0.75, 0.28, 1) both;
}
</style>
