<script setup lang="ts">
/**
 * Notebook 单元格：代码 / Markdown。
 * 代码使用 CodeMirror 编辑器；Markdown 支持预览 / 编辑切换。
 * Shift+Enter 运行并跳到下一格，Ctrl+Enter 运行并停留，Alt+Enter 运行并插入新格。
 */
import { computed, nextTick, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import NotebookCodeEditor from './NotebookCodeEditor.vue'
import NotebookOutput from './NotebookOutput.vue'
import type { NotebookCell } from './types'

const props = withDefaults(
  defineProps<{
    cell: NotebookCell
    index: number
    total: number
    running?: boolean
    disabled?: boolean
    /** source：分屏左栏，只显示源码；edit：常规编辑 */
    mode?: 'edit' | 'source'
    selected?: boolean
  }>(),
  { running: false, disabled: false, mode: 'edit', selected: false },
)

const emit = defineEmits<{
  (e: 'update:source', value: string): void
  (e: 'run'): void
  (e: 'run-next'): void
  (e: 'run-insert'): void
  (e: 'remove'): void
  (e: 'move-up'): void
  (e: 'move-down'): void
  (e: 'insert-above'): void
  (e: 'insert-below'): void
  (e: 'change-type', type: 'code' | 'markdown'): void
  (e: 'select'): void
  (e: 'focus'): void
  (e: 'escape'): void
  (e: 'clear-output'): void
  (e: 'copied'): void
}>()

const editorRef = ref<InstanceType<typeof NotebookCodeEditor> | null>(null)
const editingMarkdown = ref(!props.cell.source.trim())

const isCode = computed(() => props.cell.type === 'code')
const outputs = computed(() => props.cell.outputs ?? [])
const countLabel = computed(() => {
  if (props.running) return '…'
  const count = props.cell.execution_count
  return count === null || count === undefined ? ' ' : String(count)
})
const typeLabel = computed(() => (isCode.value ? '代码' : 'Markdown'))
const showMarkdownPreview = computed(
  () => !isCode.value && props.mode === 'edit' && !editingMarkdown.value,
)

watch(
  () => props.cell.type,
  (type) => {
    if (type === 'markdown') editingMarkdown.value = !props.cell.source.trim()
  },
)

watch(
  () => props.mode,
  (mode) => {
    if (mode === 'source') editingMarkdown.value = true
  },
)

function focusEditor() {
  void nextTick(() => editorRef.value?.focusEditor(true))
}

defineExpose({ focusEditor })

function startEditMarkdown() {
  if (props.disabled) return
  editingMarkdown.value = true
  focusEditor()
}

function runMarkdown(next: boolean) {
  editingMarkdown.value = false
  if (next) emit('run-next')
  else emit('run')
}

function runMarkdownInsert() {
  editingMarkdown.value = false
  emit('run-insert')
}

function onEditorFocus() {
  emit('select')
  emit('focus')
}

function onEditorEscape() {
  emit('escape')
}

function toggleType() {
  emit('change-type', isCode.value ? 'markdown' : 'code')
}

async function copySource() {
  try {
    await navigator.clipboard.writeText(props.cell.source)
    emit('copied')
  } catch {
    // 剪贴板不可用时静默失败，避免打断编辑
  }
}

function onCellMouseDown(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (target?.closest('.cm-editor, button, input, textarea, a')) return
  emit('select')
}
</script>

<template>
  <div
    class="nb-cell group relative flex gap-2 rounded-xl border px-1.5 py-1.5 transition-all"
    :class="[
      selected
        ? 'border-kiwi-200 bg-white/60 shadow-sm'
        : 'border-transparent hover:border-slate-200/70 hover:bg-white/20',
      running ? 'is-running border-kiwi-200/80 bg-kiwi-50/30' : '',
      disabled && !running ? 'opacity-60' : '',
    ]"
    @mousedown="onCellMouseDown"
  >
    <!-- 左侧：执行序 / 运行按钮 -->
    <div class="w-10 shrink-0 flex flex-col items-center gap-1 pt-1">
      <button
        type="button"
        class="nb-run"
        :class="running ? 'is-running' : ''"
        :disabled="disabled || running"
        :title="
          isCode
            ? '运行（Shift + Enter 运行并跳到下一格）'
            : '渲染 Markdown（Shift + Enter 渲染并跳到下一格）'
        "
        @click="isCode ? emit('run') : runMarkdown(false)"
      >
        <KiwiIcon v-if="running" name="loader" :size="12" spin />
        <KiwiIcon v-else :name="isCode ? 'play' : 'check'" :size="11" />
      </button>
      <span
        v-if="isCode"
        class="nb-count"
        :title="`执行序号 ${countLabel.trim() || '未运行'}`"
      >[{{ countLabel }}]</span>
      <span v-else class="nb-count text-[9px]">M</span>
    </div>

    <div class="min-w-0 flex-1">
      <!-- 单元格头：类型 + 操作 -->
      <div class="flex h-6 items-center gap-1.5">
        <span class="nb-type" :class="isCode ? 'is-code' : 'is-md'">
          <KiwiIcon :name="isCode ? 'code' : 'type'" :size="9" />
          {{ typeLabel }}
        </span>
        <span v-if="running" class="text-[10px] text-kiwi-600">执行中…</span>
        <span v-else-if="!isCode && showMarkdownPreview" class="text-[9.5px] text-slate-300">
          双击正文编辑
        </span>
        <div class="flex-1" />
        <div
          class="flex items-center gap-0.5 transition-opacity"
          :class="selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'"
        >
          <button type="button" class="nb-action" title="复制源码" @click="copySource">
            <KiwiIcon name="copy" :size="12" />
          </button>
          <button type="button" class="nb-action" title="切换为文本 / 代码" @click="toggleType">
            <KiwiIcon :name="isCode ? 'type' : 'code'" :size="12" />
          </button>
          <button type="button" class="nb-action" title="在上方插入单元格" @click="emit('insert-above')">
            <KiwiIcon name="plus" :size="12" class="rotate-180" />
          </button>
          <button type="button" class="nb-action" title="在下方插入单元格" @click="emit('insert-below')">
            <KiwiIcon name="plus" :size="12" />
          </button>
          <button
            type="button"
            class="nb-action"
            title="上移"
            :disabled="index === 0"
            @click="emit('move-up')"
          >
            <KiwiIcon name="chevronRight" :size="12" class="-rotate-90" />
          </button>
          <button
            type="button"
            class="nb-action"
            title="下移"
            :disabled="index === total - 1"
            @click="emit('move-down')"
          >
            <KiwiIcon name="chevronRight" :size="12" class="rotate-90" />
          </button>
          <button
            v-if="isCode && outputs.length"
            type="button"
            class="nb-action"
            title="清除本格输出"
            @click="emit('clear-output')"
          >
            <KiwiIcon name="eraser" :size="12" />
          </button>
          <button
            type="button"
            class="nb-action hover:!text-rose-500"
            title="删除单元格"
            @click="emit('remove')"
          >
            <KiwiIcon name="trash" :size="12" />
          </button>
        </div>
      </div>

      <!-- 代码编辑 -->
      <NotebookCodeEditor
        v-if="isCode"
        ref="editorRef"
        :model-value="cell.source"
        language="python"
        placeholder="输入 Python 代码；支持 !命令、%pip / %uv 安装依赖…"
        :max-height="420"
        @update:model-value="emit('update:source', $event)"
        @focus="onEditorFocus"
        @escape="onEditorEscape"
        @run="emit('run')"
        @run-next="emit('run-next')"
        @run-insert="emit('run-insert')"
      />

      <!-- Markdown：预览态 / 编辑态 -->
      <template v-else>
        <div
          v-if="showMarkdownPreview"
          class="nb-markdown min-h-[40px] cursor-text rounded-lg px-2 py-1.5 transition-colors hover:bg-white/60"
          title="双击编辑"
          @dblclick="startEditMarkdown"
        >
          <MarkdownView v-if="cell.source.trim()" :content="cell.source" />
          <span v-else class="text-xs italic text-slate-400">空 Markdown 单元格，双击编辑</span>
        </div>
        <NotebookCodeEditor
          v-else
          ref="editorRef"
          :model-value="cell.source"
          language="markdown"
          :min-height="54"
          :max-height="360"
          placeholder="输入 Markdown 文本，Shift + Enter 渲染…"
          @update:model-value="emit('update:source', $event)"
          @focus="onEditorFocus"
          @escape="onEditorEscape"
          @run="runMarkdown(false)"
          @run-next="runMarkdown(true)"
          @run-insert="runMarkdownInsert"
        />
        <div
          v-if="mode === 'edit' && editingMarkdown"
          class="mt-1 flex items-center justify-end text-[10px] text-slate-400"
        >
          <button
            type="button"
            class="rounded bg-kiwi-50 px-1.5 py-0.5 text-kiwi-600 transition-colors hover:bg-kiwi-100"
            @click="runMarkdown(false)"
          >
            渲染预览
          </button>
        </div>
      </template>

      <!-- 输出 -->
      <div
        v-if="isCode && mode === 'edit' && outputs.length"
        class="mt-1.5 flex flex-col gap-1.5"
      >
        <NotebookOutput v-for="(output, i) in outputs" :key="i" :output="output" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.nb-run {
  @apply grid h-6 w-6 place-items-center rounded-md border border-slate-200/80 bg-white/80 text-slate-400 shadow-sm transition-colors hover:border-kiwi-300 hover:text-kiwi-600 disabled:cursor-not-allowed disabled:opacity-50;
}
.nb-run.is-running {
  @apply border-kiwi-300 bg-kiwi-50 text-kiwi-600;
}
.nb-count {
  @apply font-mono text-[9px] leading-none text-slate-400 tabular-nums;
}
.nb-type {
  @apply inline-flex items-center gap-1 rounded bg-slate-100/80 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-slate-400;
}
.nb-type.is-code {
  @apply bg-indigo-50 text-indigo-400;
}
.nb-type.is-md {
  @apply bg-slate-100/80 text-slate-400;
}
.nb-action {
  @apply grid h-6 w-6 place-items-center rounded text-slate-400 transition-colors hover:bg-white hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-30;
}
.nb-markdown {
  @apply text-[13px] text-slate-700;
}
.nb-markdown :deep(.prose-wiki) {
  @apply max-w-none text-[13px];
}
</style>
