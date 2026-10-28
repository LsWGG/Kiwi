<script setup lang="ts">
/**
 * Agent 模式：悬浮在正文底部的 AI 指令栏。
 * 快捷动作（续写 / 润色 / 总结 / 翻译 / 知识库解释）+ 自由指令；
 * 结果先预览对比，再显式接受（插入 / 替换）或放弃。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { request } from '@/api/client'
import { useKbsStore } from '@/stores/kbs'
import { useDesktopStore } from '@/stores/desktop'
import { toast } from '@/components/ui/toast'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'

type AssistAction =
  | 'continue'
  | 'polish'
  | 'shorten'
  | 'summarize'
  | 'translate'
  | 'explain'
  | 'custom'
type SelectionRange = { from: number; to: number }

interface AssistReference {
  kind: 'wiki' | 'note' | 'source'
  title: string
  quote: string
  score: number
  wiki_page_id: string | null
  note_id: string | null
  source_id: string | null
}

const props = defineProps<{
  noteId: string
  getSelection: () => string
  getSelectionRange: () => SelectionRange | null
  getDocumentText: () => string
}>()

const emit = defineEmits<{
  (e: 'apply', payload: { text: string; range: SelectionRange | null }): void
  (e: 'close'): void
}>()

const kbs = useKbsStore()
const router = useRouter()
const desktop = useDesktopStore()

/** 仅桌面构建 + 状态就绪 + 未配置大模型时禁用 AI 辅助。 */
const llmMissing = computed(
  () => desktop.isDesktop && desktop.ready && !desktop.llmConfigured,
)

const ACTIONS: { id: AssistAction; label: string; hint: string; icon: string }[] = [
  { id: 'continue', label: '续写', hint: '接着当前内容写', icon: 'sparkle' },
  { id: 'polish', label: '润色', hint: '让选中文本更通顺', icon: 'edit' },
  { id: 'shorten', label: '缩写', hint: '压缩到原文 40%–60%', icon: 'minus' },
  { id: 'summarize', label: '总结', hint: '提炼 3-6 条要点', icon: 'list' },
  { id: 'translate', label: '翻译', hint: '中英互译', icon: 'learn' },
  {
    id: 'explain',
    label: '知识库解释',
    hint: '结合当前知识库的资料解释选中内容，并标注引用',
    icon: 'wiki',
  },
]

const instruction = ref('')
const loading = ref<AssistAction | null>(null)
const result = ref('')
const references = ref<AssistReference[]>([])
const lastAction = ref<AssistAction | null>(null)
const lastRange = ref<SelectionRange | null>(null)
const originSelection = ref('')
const showOrigin = ref(false)
const selectionHint = ref('')

const lastLabel = computed(
  () => ACTIONS.find((a) => a.id === lastAction.value)?.label ?? '自定义',
)
const busy = computed(() => loading.value !== null)

function refreshSelectionHint() {
  const text = props.getSelection()
  selectionHint.value = text ? `已选中 ${text.length} 字` : ''
}

async function run(action: AssistAction) {
  if (llmMissing.value) {
    toast.error('桌面版尚未配置大模型，请先在「设置 → 模型」中完成配置')
    return
  }
  const selection = props.getSelection()
  const context = props.getDocumentText()
  if (action === 'custom' && !instruction.value.trim()) {
    toast.info('先写下你想让 AI 做什么')
    return
  }
  if ((action === 'polish' || action === 'shorten') && !selection) {
    toast.info('先在正文中选中要处理的文字')
    return
  }
  if (!selection && !context.trim()) {
    toast.info('文档还是空的，先写一点内容吧')
    return
  }
  const range = props.getSelectionRange()
  loading.value = action
  result.value = ''
  references.value = []
  originSelection.value = selection
  showOrigin.value = false
  try {
    const res = await request<{ result: string; references?: AssistReference[] }>(
      `/notes/${props.noteId}/assist`,
      {
        method: 'POST',
        kbId: kbs.currentKbId,
        body: JSON.stringify({
          action,
          selection,
          context: context.slice(0, 12000),
          instruction: action === 'custom' ? instruction.value.trim() : null,
        }),
      },
    )
    result.value = res.result
    references.value = res.references || []
    lastAction.value = action
    lastRange.value = range
  } catch (e: any) {
    toast.error(e.message || '生成失败')
  } finally {
    loading.value = null
  }
}

function apply(mode: 'insert' | 'replace') {
  const text = result.value.trim()
  if (!text) return
  emit('apply', { text, range: mode === 'replace' ? lastRange.value : null })
  toast.success(mode === 'replace' ? '已替换选中内容' : '已插入到光标处')
  discard()
}

/** 放弃本次生成（显式的 reject，不写入正文）。 */
function discard() {
  result.value = ''
  references.value = []
  originSelection.value = ''
  showOrigin.value = false
}

function openReference(ref: AssistReference) {
  if (ref.kind === 'wiki' && ref.wiki_page_id) {
    void router.push({
      name: 'wiki-page',
      params: { id: ref.wiki_page_id },
      query: { quote: ref.quote.slice(0, 160) },
    })
  } else if (ref.kind === 'note' && ref.note_id) {
    void router.push({
      name: 'notes',
      params: { id: ref.note_id },
      query: { quote: ref.quote.slice(0, 160) },
    })
  }
}

async function copyResult() {
  try {
    await navigator.clipboard.writeText(result.value)
    toast.success('已复制到剪贴板')
  } catch {
    toast.error('复制失败')
  }
}
</script>

<template>
  <div
    class="agent-command relative rounded-2xl border border-slate-200/80 bg-white/95 shadow-lifted backdrop-blur-xl"
  >
    <!-- 关闭指令栏：始终可退出，不写入正文 -->
    <button
      type="button"
      class="absolute right-1.5 top-1.5 z-10 grid h-6 w-6 place-items-center rounded-md text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-600"
      title="关闭指令栏（Esc）"
      aria-label="关闭 Agent 指令栏"
      @click="emit('close')"
    >
      <KiwiIcon name="close" :size="12" />
    </button>

    <!-- 桌面版未配置模型：保留面板，禁用生成入口并给出配置路径 -->
    <div v-if="llmMissing" class="flex items-start gap-2 border-b border-slate-100 px-3.5 py-2.5 pr-10">
      <KiwiIcon name="alert" :size="13" class="mt-0.5 shrink-0 text-amber-500" />
      <div class="min-w-0 flex-1">
        <p class="text-[11.5px] font-medium text-slate-600">尚未配置大模型</p>
        <p class="mt-0.5 text-[10.5px] leading-relaxed text-slate-400">
          AI 写作辅助需要大模型。正文编辑、搜索与 Wiki 浏览不受影响。
        </p>
      </div>
      <button
        type="button"
        class="shrink-0 rounded-md px-1.5 py-0.5 text-[10.5px] font-medium text-kiwi-600 hover:bg-kiwi-50"
        @click="router.push('/settings/models')"
      >
        去配置
      </button>
    </div>

    <!-- 生成结果 -->
    <div v-if="busy || result" class="border-b border-slate-100">
      <div class="flex items-center gap-1.5 px-3.5 py-2 pr-9">
        <span
          class="w-5 h-5 grid place-items-center rounded-md bg-gradient-to-br from-kiwi-500 to-emerald-500 text-white"
        >
          <KiwiIcon name="sparkle" :size="11" />
        </span>
        <span class="text-[11px] font-medium text-slate-500">
          {{ busy ? '生成中…' : `${lastLabel}结果` }}
        </span>
        <button
          v-if="result && !busy && originSelection"
          type="button"
          class="ml-auto rounded-md px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-slate-100 hover:text-kiwi-600"
          :class="showOrigin ? 'bg-kiwi-50 text-kiwi-600' : ''"
          @click="showOrigin = !showOrigin"
        >
          {{ showOrigin ? '隐藏原文' : '对比原文' }}
        </button>
        <button
          v-if="result && !busy"
          type="button"
          class="grid h-6 w-6 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-kiwi-600"
          :class="originSelection ? '' : 'ml-auto'"
          title="复制结果"
          @click="copyResult"
        >
          <KiwiIcon name="note" :size="12" />
        </button>
      </div>
      <div v-if="busy" class="flex items-center gap-2 px-4 pb-4 pt-1 text-[11px] text-slate-400">
        <KiwiIcon name="loader" :size="13" spin class="text-kiwi-500" />
        正在请求模型…
      </div>
      <div v-else class="agent-result max-h-[260px] overflow-y-auto px-4 pb-2">
        <div
          v-if="showOrigin && originSelection"
          class="mb-2 rounded-lg border border-slate-200 bg-slate-50/80 px-2.5 py-1.5"
        >
          <div class="mb-0.5 text-[9.5px] font-medium uppercase tracking-wide text-slate-400">
            原选中内容
          </div>
          <div class="max-h-24 overflow-y-auto whitespace-pre-wrap text-[11.5px] leading-relaxed text-slate-500">
            {{ originSelection }}
          </div>
        </div>
        <MarkdownView :content="result" />
        <div v-if="references.length" class="mt-2 border-t border-slate-100 pt-2">
          <div class="mb-1 text-[9.5px] font-medium uppercase tracking-wide text-slate-400">
            引用来源
          </div>
          <button
            v-for="(ref, i) in references"
            :key="`${ref.kind}-${ref.wiki_page_id || ref.note_id || ref.source_id}-${i}`"
            type="button"
            class="mb-1 flex w-full items-start gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-kiwi-50/70"
            :class="ref.kind === 'wiki' || ref.kind === 'note' ? 'cursor-pointer' : 'cursor-default'"
            :title="ref.quote"
            @click="openReference(ref)"
          >
            <span class="mt-px shrink-0 text-[10px] font-semibold text-kiwi-500">{{ i + 1 }}</span>
            <span class="min-w-0">
              <span class="block truncate text-[11px] text-slate-600">
                {{ ref.title }}
              </span>
              <span class="line-clamp-2 text-[10px] leading-snug text-slate-400">
                {{ ref.quote }}
              </span>
            </span>
            <span class="ml-auto shrink-0 pt-px text-[9px] text-slate-300">
              {{ ref.kind === 'wiki' ? 'Wiki' : ref.kind === 'note' ? '笔记' : '素材' }}
            </span>
          </button>
        </div>
      </div>
      <div
        v-if="result && !busy"
        class="flex items-center gap-1.5 border-t border-slate-100 px-3 py-2"
      >
        <button
          type="button"
          class="kiwi-btn-primary !py-1 !px-2.5 !text-[10.5px]"
          @click="apply('insert')"
        >
          <KiwiIcon name="plus" :size="11" />
          插入到光标
        </button>
        <button
          type="button"
          class="kiwi-btn-secondary !py-1 !px-2.5 !text-[10.5px]"
          :disabled="!lastRange"
          :title="lastRange ? '替换生成时选中的文本' : '生成时没有选中文本'"
          @click="apply('replace')"
        >
          <KiwiIcon name="refresh" :size="11" />
          替换选中
        </button>
        <button
          type="button"
          class="rounded-md px-1.5 py-1 text-[10.5px] text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          title="放弃本次生成"
          @click="discard"
        >
          放弃
        </button>
        <span class="ml-auto text-[10px] text-slate-300">生成内容不会自动写入正文</span>
      </div>
    </div>

    <!-- 快捷动作 -->
    <div class="flex items-center gap-1 px-2.5 pr-9 pt-2">
      <button
        v-for="action in ACTIONS"
        :key="action.id"
        type="button"
        class="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700 disabled:opacity-40"
        :title="action.hint"
        :disabled="busy || llmMissing"
        @click="run(action.id)"
      >
        <KiwiIcon
          :name="loading === action.id ? 'loader' : action.icon"
          :size="11"
          :spin="loading === action.id"
          class="text-kiwi-500"
        />
        {{ action.label }}
      </button>
      <span v-if="selectionHint" class="ml-auto pr-1 text-[10px] text-kiwi-500">
        {{ selectionHint }}
      </span>
    </div>

    <!-- 指令输入 -->
    <div class="flex items-end gap-2 p-2.5 pt-1.5">
      <textarea
        v-model="instruction"
        rows="1"
        class="agent-input max-h-28 min-h-[34px] flex-1 resize-none rounded-xl border border-transparent bg-transparent px-1 py-1.5 text-[12.5px] leading-relaxed text-slate-700 outline-none placeholder:text-slate-400"
        :placeholder="llmMissing ? '配置模型后可用' : '修改文档，或输入指令…'"
        :disabled="busy || llmMissing"
        @focus="refreshSelectionHint"
        @keydown.enter.exact.prevent="run('custom')"
        @keydown.shift.enter.stop
        @keydown.esc.prevent="emit('close')"
      />
      <button
        type="button"
        class="mb-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-kiwi-600 text-white shadow-sm transition-all hover:bg-kiwi-700 active:scale-95 disabled:opacity-30 disabled:pointer-events-none"
        :disabled="busy || llmMissing || !instruction.trim()"
        title="执行指令（Enter）"
        @click="run('custom')"
      >
        <KiwiIcon :name="loading === 'custom' ? 'loader' : 'sparkle'" :size="14" :spin="loading === 'custom'" />
      </button>
    </div>
    <p class="px-4 pb-2 text-[9.5px] text-slate-300">
      Enter 执行 · Shift + Enter 换行 · 选中文本后再点「润色 / 翻译」更准确
    </p>
  </div>
</template>

<style scoped>
.agent-result :deep(.prose-wiki) {
  font-size: 12px;
  line-height: 1.7;
}
.agent-result :deep(.prose-wiki h1),
.agent-result :deep(.prose-wiki h2),
.agent-result :deep(.prose-wiki h3) {
  font-size: 13px;
  margin: 0.6em 0 0.3em;
}
.agent-result :deep(.prose-wiki p) {
  margin: 0.35em 0;
}
.agent-input:focus {
  border-color: rgba(199, 210, 254, 0.9);
  background: rgba(248, 250, 252, 0.7);
}
</style>
