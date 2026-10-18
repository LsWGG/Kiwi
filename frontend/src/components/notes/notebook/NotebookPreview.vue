<script setup lang="ts">
/** Notebook 只读预览：分屏右栏与阅读模式共用，渲染 Markdown、代码与输出。 */
import { ref } from 'vue'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import NotebookCodeBlock from './NotebookCodeBlock.vue'
import NotebookOutput from './NotebookOutput.vue'
import type { NotebookCell, NotebookDoc } from './types'

const props = withDefaults(
  defineProps<{
    doc: NotebookDoc
    runningCellId?: string | null
    emptyHint?: string
    /** 阅读模式：默认折叠代码单元格，只展示运行结果，点击展开源码 */
    collapseCode?: boolean
  }>(),
  { runningCellId: null, emptyHint: 'Notebook 还没有内容', collapseCode: false },
)

const expandedIds = ref<string[]>([])

function isExpanded(cell: NotebookCell) {
  return expandedIds.value.includes(cell.id)
}

function toggleCode(cell: NotebookCell) {
  expandedIds.value = isExpanded(cell)
    ? expandedIds.value.filter((id) => id !== cell.id)
    : [...expandedIds.value, cell.id]
}

function lineCount(cell: NotebookCell) {
  return String(cell.source || '').trim().split('\n').filter((line) => line.trim()).length
}

</script>

<template>
  <div class="flex flex-col gap-3">
    <div
      v-for="(cell, index) in doc.cells"
      :key="cell.id"
      class="nb-preview-cell"
      :class="{ 'is-running': runningCellId === cell.id }"
    >
      <template v-if="cell.type === 'markdown'">
        <div v-if="cell.source.trim()" class="nb-preview-md">
          <MarkdownView :content="cell.source" />
        </div>
        <div v-else class="nb-preview-empty">空 Markdown 单元格</div>
      </template>
      <template v-else>
        <div class="mb-1.5 flex items-center gap-2">
          <span class="nb-preview-count">
            <KiwiIcon
              v-if="runningCellId === cell.id"
              name="loader"
              :size="10"
              spin
              class="mr-1 inline"
            />
            In [{{ cell.execution_count ?? ' ' }}]
          </span>
          <span class="text-[10px] text-slate-300">代码单元格 {{ index + 1 }}</span>
          <span
            v-if="runningCellId === cell.id"
            class="text-[10px] text-kiwi-600"
          >执行中…</span>
          <button
            v-if="collapseCode && isExpanded(cell)"
            type="button"
            class="nb-preview-toggle ml-auto"
            title="收起代码，只看运行结果"
            @click="toggleCode(cell)"
          >
            <KiwiIcon name="chevronsUp" :size="10" />
            收起代码
          </button>
        </div>
        <button
          v-if="collapseCode && !isExpanded(cell)"
          type="button"
          class="nb-preview-code-collapsed"
          :title="`展开代码（${lineCount(cell)} 行）`"
          @click="toggleCode(cell)"
        >
          <span class="inline-flex items-center gap-1.5">
            <KiwiIcon name="code" :size="11" />
            <span>代码已折叠</span>
            <span class="nb-preview-code-count">{{ lineCount(cell) }} 行</span>
          </span>
          <span class="inline-flex items-center gap-1 text-[10px] text-slate-400">
            展开
            <KiwiIcon name="chevronsDown" :size="10" />
          </span>
        </button>
        <NotebookCodeBlock
          v-if="!collapseCode || isExpanded(cell)"
          :code="cell.source"
          :language="doc.language || 'python'"
        />
        <div v-if="cell.outputs?.length" class="mt-1.5 flex flex-col gap-1.5">
          <NotebookOutput
            v-for="(output, i) in cell.outputs"
            :key="i"
            :output="output"
          />
        </div>
      </template>
    </div>

    <div v-if="!doc.cells.length" class="py-16 text-center text-[12px] text-slate-400">
      {{ emptyHint }}
    </div>
  </div>
</template>

<style scoped>
.nb-preview-cell {
  @apply rounded-xl border border-transparent px-3 py-2 transition-colors;
}
.nb-preview-cell.is-running {
  @apply border-kiwi-200/80 bg-kiwi-50/30;
}
.nb-preview-md {
  @apply text-[13px] text-slate-700;
}
.nb-preview-md :deep(.prose-wiki) {
  @apply max-w-none text-[13px];
}
.nb-preview-count {
  @apply font-mono text-[10px] text-slate-400 tabular-nums;
}
.nb-preview-empty {
  @apply rounded-lg border border-dashed border-slate-200/80 py-3 text-center text-[11px] italic text-slate-300;
}
.nb-preview-toggle {
  @apply inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600;
}
.nb-preview-code-collapsed {
  @apply flex w-full items-center justify-between gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-2.5 py-1.5 text-left text-[10.5px] text-slate-400 transition-colors;
}
.nb-preview-code-collapsed:hover {
  @apply border-kiwi-200 bg-kiwi-50/50 text-kiwi-700;
}
.nb-preview-code-count {
  @apply rounded bg-white/80 px-1 py-px font-mono text-[9.5px] text-slate-400;
}
</style>
