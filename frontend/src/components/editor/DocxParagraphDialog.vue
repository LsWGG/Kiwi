<script setup lang="ts">
/**
 * Word / WPS 风格的「段落」设置对话框：
 * 对齐、缩进（左/右/特殊格式）、间距（段前/段后/行距）。
 * 打开时读取光标所在段落的实际格式；点「确定」应用到右击 / 选中的段落。
 */
import { computed, ref, watch } from 'vue'
import type { Editor } from '@tiptap/core'
import {
  DEFAULT_DOCX_PREFS,
  DOCX_LINE_HEIGHTS,
  type DocxPrefs,
} from './modes'
import {
  blockAtPosition,
  defaultBlockSize,
  formatFromAttrs,
  type ParagraphAlign,
  type ParagraphFormat,
  type ParagraphFormatPatch,
} from './extensions/paragraphFormat'

const props = defineProps<{
  open: boolean
  prefs: DocxPrefs
  editor: Editor | null
  /** 右击段落范围；不传时使用当前选区 */
  range?: { from: number; to: number } | null
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply', patch: ParagraphFormatPatch): void
}>()

type IndentMode = 'none' | 'first' | 'hanging'

const draft = ref<ParagraphFormat>({
  font: null,
  size: null,
  lineHeight: null,
  lineHeightMode: null,
  lineHeightFixed: null,
  spaceBefore: null,
  spaceAfter: null,
  indentLeft: null,
  indentRight: null,
  firstLineIndent: null,
  hangingIndent: null,
  align: null,
})
const align = ref<ParagraphAlign>('left')
const indentMode = ref<IndentMode>('none')
const lineChoice = ref('multiple')

/** 光标段落未设置的项回退到页面默认值，保证对话框显示“当前效果”。 */
function effectiveFormat(): ParagraphFormat {
  const prefs = props.prefs ?? DEFAULT_DOCX_PREFS
  const block = blockAtPosition(props.editor, props.range?.from ?? null)
  const raw = block ? formatFromAttrs(block.node.attrs) : {}
  return {
    font: raw.font ?? prefs.font,
    size: raw.size ?? defaultBlockSize(block?.node ?? null, prefs),
    lineHeight: raw.lineHeight ?? prefs.lineHeight,
    lineHeightMode: raw.lineHeightMode ?? prefs.lineHeightMode,
    lineHeightFixed: raw.lineHeightFixed ?? prefs.lineHeightFixed,
    spaceBefore: raw.spaceBefore ?? prefs.spaceBefore,
    spaceAfter: raw.spaceAfter ?? prefs.spaceAfter,
    indentLeft: raw.indentLeft ?? prefs.indentLeft,
    indentRight: raw.indentRight ?? prefs.indentRight,
    firstLineIndent: raw.firstLineIndent ?? prefs.firstLineIndent,
    hangingIndent: raw.hangingIndent ?? prefs.hangingIndent,
    align: raw.align ?? 'left',
  }
}

function syncFromParagraph() {
  const format = effectiveFormat()
  draft.value = { ...format }
  align.value = format.align ?? 'left'
  const first = format.firstLineIndent ?? 0
  indentMode.value = first <= 0 ? 'none' : format.hangingIndent ? 'hanging' : 'first'
  lineChoice.value =
    format.lineHeightMode === 'fixed'
      ? 'fixed'
      : String(format.lineHeight ?? props.prefs.lineHeight)
}

watch(
  () => props.open,
  (open) => {
    if (open) syncFromParagraph()
  },
  { immediate: true },
)

function onIndentMode(e: Event) {
  const mode = (e.target as HTMLSelectElement).value as IndentMode
  indentMode.value = mode
  if (mode === 'none') draft.value.firstLineIndent = 0
  else if ((draft.value.firstLineIndent ?? 0) <= 0) draft.value.firstLineIndent = 2
  draft.value.hangingIndent = mode === 'hanging'
}

function onLineChoice(e: Event) {
  const value = (e.target as HTMLSelectElement).value
  lineChoice.value = value
  if (value === 'fixed') {
    draft.value.lineHeightMode = 'fixed'
    if (!draft.value.lineHeightFixed) draft.value.lineHeightFixed = 20
  } else {
    draft.value.lineHeightMode = 'multiple'
    draft.value.lineHeight = Number(value)
  }
}

const lineValue = computed({
  get: () =>
    draft.value.lineHeightMode === 'fixed'
      ? (draft.value.lineHeightFixed ?? 20)
      : (draft.value.lineHeight ?? 1.9),
  set: (value: number) => {
    if (draft.value.lineHeightMode === 'fixed') {
      draft.value.lineHeightFixed = Math.min(72, Math.max(8, value || 8))
    } else {
      draft.value.lineHeight = Math.min(3, Math.max(0.8, value || 0.8))
    }
  },
})

const lineOptions = computed(() => {
  const values = DOCX_LINE_HEIGHTS.map((line) => String(line.value))
  return values.includes(lineChoice.value) || lineChoice.value === 'fixed'
    ? DOCX_LINE_HEIGHTS
    : [...DOCX_LINE_HEIGHTS, { value: Number(lineChoice.value), label: `自定义 ${lineChoice.value} 倍` }]
})

const previewStyle = computed(() => {
  const d = draft.value
  const hanging = indentMode.value === 'hanging'
  const indent = indentMode.value === 'none' ? 0 : (d.firstLineIndent ?? 0)
  const fixed = d.lineHeightMode === 'fixed'
  return {
    lineHeight: fixed
      ? `${((d.lineHeightFixed ?? 20) * 4) / 3}px`
      : String(d.lineHeight ?? 1.9),
    marginTop: `${d.spaceBefore ?? 0}px`,
    marginBottom: `${d.spaceAfter ?? 0}px`,
    marginLeft: `${d.indentLeft ?? 0}em`,
    marginRight: `${d.indentRight ?? 0}em`,
    paddingLeft: hanging ? `${indent}em` : '0',
    textIndent: hanging ? `-${indent}em` : `${indent}em`,
  }
})

function confirm() {
  const d = draft.value
  emit('apply', {
    font: d.font,
    size: d.size,
    lineHeight: d.lineHeight,
    lineHeightMode: d.lineHeightMode,
    lineHeightFixed: d.lineHeightFixed,
    spaceBefore: d.spaceBefore,
    spaceAfter: d.spaceAfter,
    indentLeft: d.indentLeft,
    indentRight: d.indentRight,
    firstLineIndent: indentMode.value === 'none' ? 0 : (d.firstLineIndent ?? 0),
    hangingIndent: indentMode.value === 'hanging',
    align: align.value,
  })
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/25 px-6 backdrop-blur-[1px]"
      @mousedown.self="emit('close')"
    >
      <div
        role="dialog"
        aria-label="段落设置"
        class="w-[420px] max-w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        @keydown.esc.stop="emit('close')"
      >
        <header class="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <div class="flex items-center gap-2">
            <span class="grid h-6 w-6 place-items-center rounded-md bg-kiwi-50 text-kiwi-600">
              <svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="4" y1="6" x2="20" y2="6" />
                <line x1="4" y1="12" x2="14" y2="12" />
                <line x1="4" y1="18" x2="18" y2="18" />
              </svg>
            </span>
            <div>
              <p class="text-[13px] font-semibold text-slate-700">段落</p>
              <p class="text-[10px] text-slate-400">缩进与间距</p>
            </div>
          </div>
          <button
            type="button"
            class="grid h-6 w-6 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            title="关闭"
            @click="emit('close')"
          >
            <svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" />
            </svg>
          </button>
        </header>

        <div class="space-y-4 px-4 py-3.5">
          <!-- 对齐方式 -->
          <section>
            <p class="mb-1.5 text-[11px] font-medium text-slate-500">对齐方式</p>
            <div class="flex gap-1">
              <button
                v-for="item in [
                  { id: 'left', label: '左对齐', icon: 'L' },
                  { id: 'center', label: '居中', icon: 'C' },
                  { id: 'right', label: '右对齐', icon: 'R' },
                  { id: 'justify', label: '两端对齐', icon: 'J' },
                ] as const"
                :key="item.id"
                type="button"
                :title="item.label"
                class="h-7 w-9 rounded-md border text-[11px] font-semibold transition-colors"
                :class="
                  align === item.id
                    ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
                    : 'border-slate-200 text-slate-500 hover:bg-slate-50'
                "
                @click="align = item.id"
              >
                {{ item.icon }}
              </button>
              <span class="ml-1 self-center text-[10px] text-slate-400">作用于当前段落</span>
            </div>
          </section>

          <!-- 缩进 -->
          <section class="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
            <p class="mb-2 text-[11px] font-medium text-slate-500">缩进</p>
            <div class="grid grid-cols-2 gap-2">
              <label class="flex items-center gap-2">
                <span class="w-12 shrink-0 text-[11px] text-slate-500">左缩进</span>
                <input
                  v-model.number="draft.indentLeft"
                  type="number"
                  min="0"
                  max="10"
                  step="1"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 text-[11px] text-slate-600 outline-none focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-100"
                />
                <span class="text-[10px] text-slate-400">字符</span>
              </label>
              <label class="flex items-center gap-2">
                <span class="w-12 shrink-0 text-[11px] text-slate-500">右缩进</span>
                <input
                  v-model.number="draft.indentRight"
                  type="number"
                  min="0"
                  max="10"
                  step="1"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 text-[11px] text-slate-600 outline-none focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-100"
                />
                <span class="text-[10px] text-slate-400">字符</span>
              </label>
              <label class="flex items-center gap-2">
                <span class="w-12 shrink-0 text-[11px] text-slate-500">特殊格式</span>
                <select
                  :value="indentMode"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
                  @change="onIndentMode"
                >
                  <option value="none">无</option>
                  <option value="first">首行缩进</option>
                  <option value="hanging">悬挂缩进</option>
                </select>
              </label>
              <label class="flex items-center gap-2">
                <span class="w-12 shrink-0 text-[11px] text-slate-500">缩进值</span>
                <input
                  v-model.number="draft.firstLineIndent"
                  type="number"
                  min="0"
                  max="4"
                  step="1"
                  :disabled="indentMode === 'none'"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 text-[11px] text-slate-600 outline-none disabled:bg-slate-100 disabled:text-slate-400 focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-100"
                />
                <span class="text-[10px] text-slate-400">字符</span>
              </label>
            </div>
          </section>

          <!-- 间距 -->
          <section class="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
            <p class="mb-2 text-[11px] font-medium text-slate-500">间距</p>
            <div class="grid grid-cols-2 gap-2">
              <label class="flex items-center gap-2">
                <span class="w-12 shrink-0 text-[11px] text-slate-500">段前</span>
                <input
                  v-model.number="draft.spaceBefore"
                  type="number"
                  min="0"
                  max="48"
                  step="1"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 text-[11px] text-slate-600 outline-none focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-100"
                />
                <span class="text-[10px] text-slate-400">px</span>
              </label>
              <label class="flex items-center gap-2">
                <span class="w-12 shrink-0 text-[11px] text-slate-500">段后</span>
                <input
                  v-model.number="draft.spaceAfter"
                  type="number"
                  min="0"
                  max="48"
                  step="1"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 text-[11px] text-slate-600 outline-none focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-100"
                />
                <span class="text-[10px] text-slate-400">px</span>
              </label>
              <label class="flex items-center gap-2">
                <span class="w-12 shrink-0 text-[11px] text-slate-500">行距</span>
                <select
                  :value="lineChoice"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
                  @change="onLineChoice"
                >
                  <option v-for="line in lineOptions" :key="line.value" :value="String(line.value)">
                    {{ line.label }}
                  </option>
                  <option value="fixed">固定值</option>
                </select>
              </label>
              <label class="flex items-center gap-2">
                <span class="w-12 shrink-0 text-[11px] text-slate-500">设置值</span>
                <input
                  v-model.number="lineValue"
                  type="number"
                  :min="draft.lineHeightMode === 'fixed' ? 8 : 0.8"
                  :max="draft.lineHeightMode === 'fixed' ? 72 : 3"
                  :step="draft.lineHeightMode === 'fixed' ? 1 : 0.05"
                  class="h-7 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 text-[11px] text-slate-600 outline-none focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-100"
                />
                <span class="text-[10px] text-slate-400">
                  {{ draft.lineHeightMode === 'fixed' ? '磅' : '倍' }}
                </span>
              </label>
            </div>
          </section>

          <!-- 预览 -->
          <section>
            <p class="mb-1.5 text-[11px] font-medium text-slate-500">预览</p>
            <div class="max-h-[92px] overflow-hidden rounded-lg border border-slate-200 bg-white px-3 py-2">
              <p class="text-[12px] text-slate-600" :style="previewStyle">
                段落排版预览：首行缩进、段间距与行距会应用到正文段落。
              </p>
            </div>
          </section>
        </div>

        <footer class="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50/70 px-4 py-2.5">
          <button
            type="button"
            class="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-[11.5px] text-slate-600 hover:bg-slate-50"
            @click="emit('close')"
          >
            取消
          </button>
          <button type="button" class="kiwi-btn-primary !px-4 !py-1.5 !text-[11.5px]" @click="confirm">
            确定
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>
