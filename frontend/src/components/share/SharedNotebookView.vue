<script setup lang="ts">
/** 公开分享页的 Notebook 只读视图：Markdown 单元格 + 代码与运行输出。 */
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import MarkdownView from '@/components/editor/MarkdownView.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import {
  normalizeNotebook,
  type NotebookCell,
  type NotebookDoc,
  type NotebookOutput,
} from '@/components/notes/notebook/types'

const props = defineProps<{ doc?: unknown }>()

const doc = computed<NotebookDoc | null>(() => {
  if (!props.doc || typeof props.doc !== 'object') return null
  const cells = (props.doc as Record<string, unknown>).cells
  if (!Array.isArray(cells) || !cells.length) return null
  return normalizeNotebook(props.doc)
})

function sanitize(html: string | undefined): string {
  return html ? DOMPurify.sanitize(html, { USE_PROFILES: { html: true } }) : ''
}

function imageSrc(output: NotebookOutput): string {
  const mime = String(output.image?.mime || '')
  const data = String(output.image?.data || '')
  if (!data || !/^image\//i.test(mime)) return ''
  return `data:${mime};base64,${data}`
}

function codeCellsBefore(cell: NotebookCell): number {
  if (!doc.value) return 0
  const index = doc.value.cells.indexOf(cell)
  return doc.value.cells.slice(0, index).filter((item) => item.type === 'code').length + 1
}
</script>

<template>
  <div v-if="doc" class="shared-notebook space-y-4">
    <div
      v-for="cell in doc.cells"
      :key="cell.id"
      class="rounded-2xl border border-slate-200/70 bg-white/85 shadow-soft"
    >
      <template v-if="cell.type === 'markdown'">
        <div class="px-4 py-3">
          <MarkdownView :content="cell.source" />
        </div>
      </template>

      <template v-else>
        <div class="flex items-center gap-2 border-b border-slate-100 px-4 py-2 text-[10.5px] text-slate-400">
          <KiwiIcon name="code" :size="12" />
          <span>代码 {{ codeCellsBefore(cell) }}</span>
          <span v-if="cell.execution_count != null" class="font-mono">
            In [{{ cell.execution_count }}]
          </span>
        </div>
        <pre class="overflow-x-auto bg-slate-50/70 px-4 py-3 font-mono text-[12px] leading-relaxed text-slate-700"><code>{{ cell.source }}</code></pre>

        <div v-if="cell.outputs?.length" class="space-y-2 border-t border-slate-100 px-4 py-3">
          <template v-for="(output, index) in cell.outputs" :key="index">
            <div
              v-if="output.type === 'error'"
              class="rounded-xl border border-rose-200 bg-rose-50/70 px-3 py-2"
            >
              <pre class="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-rose-600">{{ output.text }}</pre>
            </div>
            <div
              v-else-if="output.html"
              class="overflow-x-auto rounded-xl border border-slate-200/70 bg-white px-3 py-2 text-[11.5px]"
              v-html="sanitize(output.html)"
            />
            <div v-else-if="output.image" class="overflow-x-auto">
              <img
                :src="imageSrc(output)"
                alt="Notebook 输出"
                class="max-w-full rounded-lg border border-slate-200/70"
              />
            </div>
            <pre
              v-else-if="output.text"
              class="overflow-x-auto whitespace-pre-wrap rounded-xl bg-slate-50 px-3 py-2 font-mono text-[11px] leading-relaxed"
              :class="output.name === 'stderr' ? 'text-amber-600' : 'text-slate-600'"
            >{{ output.text }}</pre>
          </template>
        </div>
      </template>
    </div>
  </div>

  <div v-else class="rounded-2xl border border-slate-200/70 bg-white/70 px-4 py-16 text-center">
    <p class="text-[12px] text-slate-400">Notebook 还没有单元格。</p>
  </div>
</template>

<style scoped>
/* 与工作区 Notebook 预览一致：Markdown 单元格紧凑排版，首块不额外留白 */
.shared-notebook :deep(.markdown-view) {
  max-width: none;
  font-size: 13.5px;
  line-height: 1.75;
  color: #334155;
}
.shared-notebook :deep(.markdown-view > :first-child) {
  margin-top: 0 !important;
}
.shared-notebook :deep(.markdown-view > * + *) {
  margin-top: 0.6em;
}
.shared-notebook :deep(table) {
  border-collapse: collapse;
  font-size: 11.5px;
}

.shared-notebook :deep(th),
.shared-notebook :deep(td) {
  border: 1px solid rgb(226 232 240 / 0.8);
  padding: 4px 8px;
  text-align: left;
}

.shared-notebook :deep(thead th) {
  background: rgb(248 250 252);
  font-weight: 600;
}
</style>
