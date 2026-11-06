<script setup lang="ts">
/** Jupyter Notebook（.ipynb）只读预览：Markdown 单元、代码单元与输出。 */
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const props = defineProps<{
  source: string
  /** fill：铺满父容器；block：按内容高度展示，用于正文内嵌预览。 */
  fit?: 'fill' | 'block'
}>()

const isBlock = computed(() => props.fit === 'block')

interface NotebookOutput {
  kind: 'text' | 'html' | 'image' | 'error'
  text?: string
  html?: string
  src?: string
}

interface NotebookCell {
  index: number
  type: string
  source: string
  html: string
  outputs: NotebookOutput[]
}

interface NotebookView {
  error: string
  cells: NotebookCell[]
  total: number
  language: string
}

const MAX_CELLS = 80
const MAX_OUTPUTS = 20

const md = new MarkdownIt({ html: true, linkify: true, breaks: false })

const asText = (value: unknown) =>
  Array.isArray(value) ? value.join('') : String(value ?? '')

const stripAnsi = (value: string) => value.replace(/\u001b\[[0-9;]*m/g, '')

function normalizeOutputs(outputs: unknown): NotebookOutput[] {
  if (!Array.isArray(outputs)) return []
  const result: NotebookOutput[] = []
  for (const raw of outputs.slice(0, MAX_OUTPUTS)) {
    const output = raw as Record<string, any>
    if (!output) continue
    if (output.output_type === 'stream') {
      result.push({ kind: 'text', text: asText(output.text) })
      continue
    }
    if (output.output_type === 'error') {
      const traceback = Array.isArray(output.traceback)
        ? output.traceback.map(stripAnsi).join('\n')
        : ''
      result.push({
        kind: 'error',
        text: traceback || `${output.ename ?? 'Error'}: ${output.evalue ?? ''}`,
      })
      continue
    }
    const data = output.data as Record<string, unknown> | undefined
    if (!data) continue
    if (data['image/png']) {
      result.push({ kind: 'image', src: `data:image/png;base64,${asText(data['image/png'])}` })
    } else if (data['image/jpeg']) {
      result.push({ kind: 'image', src: `data:image/jpeg;base64,${asText(data['image/jpeg'])}` })
    } else if (data['image/svg+xml']) {
      result.push({
        kind: 'html',
        html: DOMPurify.sanitize(asText(data['image/svg+xml']), {
          USE_PROFILES: { svg: true, svgFilters: true },
        }),
      })
    } else if (data['text/html']) {
      result.push({ kind: 'html', html: DOMPurify.sanitize(asText(data['text/html'])) })
    } else if (data['text/plain']) {
      result.push({ kind: 'text', text: asText(data['text/plain']) })
    }
  }
  return result
}

const view = computed<NotebookView>(() => {
  const empty: NotebookView = { error: '', cells: [], total: 0, language: '' }
  try {
    const notebook = JSON.parse(props.source) as Record<string, any>
    if (!notebook || !Array.isArray(notebook.cells)) {
      return { ...empty, error: '不是有效的 Jupyter Notebook（缺少 cells 字段）' }
    }
    const language = String(
      notebook.metadata?.kernelspec?.language ??
        notebook.metadata?.language_info?.name ??
        '',
    )
    const cells: NotebookCell[] = notebook.cells
      .slice(0, MAX_CELLS)
      .map((cell: any, index: number) => {
        const type = String(cell?.cell_type ?? 'unknown')
        const source = asText(cell?.source)
        return {
          index,
          type,
          source,
          html: type === 'markdown' ? DOMPurify.sanitize(md.render(source)) : '',
          outputs: type === 'code' ? normalizeOutputs(cell?.outputs) : [],
        }
      })
    return { error: '', cells, total: notebook.cells.length, language }
  } catch (e: any) {
    return { ...empty, error: e?.message || 'JSON 解析失败' }
  }
})
</script>

<template>
  <div class="w-full bg-white" :class="isBlock ? '' : 'h-full overflow-auto'">
    <div
      v-if="!source.trim()"
      class="grid place-items-center py-16 text-[12px] text-slate-400"
    >
      文件为空
    </div>
    <template v-else-if="!view.error">
      <p class="m-0 border-b border-slate-200 bg-slate-50/70 px-4 py-1.5 text-[10.5px] text-slate-500">
        Notebook · {{ view.total }} 个单元
        <template v-if="view.language"> · {{ view.language }}</template>
        <template v-if="view.total > view.cells.length">
          ，仅展示前 {{ view.cells.length }} 个
        </template>
      </p>
      <article class="space-y-4 px-4 py-4">
        <section v-for="cell in view.cells" :key="cell.index" class="nb-cell">
          <pre v-if="cell.type === 'code'" class="nb-code"><code>{{ cell.source }}</code></pre>
          <div
            v-else-if="cell.type === 'markdown'"
            class="prose-wiki nb-markdown"
            v-html="cell.html"
          />
          <pre v-else class="nb-raw">{{ cell.source }}</pre>
          <div v-if="cell.outputs.length" class="nb-outputs">
            <template v-for="(output, index) in cell.outputs" :key="index">
              <pre v-if="output.kind === 'text'" class="nb-output">{{ output.text }}</pre>
              <pre v-else-if="output.kind === 'error'" class="nb-output nb-output-error">{{ output.text }}</pre>
              <img
                v-else-if="output.kind === 'image'"
                :src="output.src"
                alt="单元输出"
                class="nb-output-image"
              />
              <div v-else class="nb-output nb-output-html" v-html="output.html" />
            </template>
          </div>
        </section>
      </article>
    </template>
    <div v-else class="w-full">
      <p class="m-0 border-b border-amber-100 bg-amber-50/60 px-4 py-1.5 text-[10.5px] text-amber-700">
        Notebook 解析失败（{{ view.error }}），以下为原文
      </p>
      <pre class="m-0 p-4 text-[12px] leading-relaxed text-slate-700 whitespace-pre-wrap break-words">{{ source }}</pre>
    </div>
  </div>
</template>

<style scoped>
.nb-cell {
  border: 1px solid #eef2f6;
  border-radius: 10px;
  overflow: hidden;
}
.nb-code {
  margin: 0;
  padding: 12px 14px;
  background: #f8fafc;
  color: #334155;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.nb-markdown {
  padding: 10px 14px;
  font-size: 13.5px;
  color: #334155;
}
.nb-markdown :deep(pre) {
  background: #f8fafc;
  color: #334155;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.nb-raw {
  margin: 0;
  padding: 12px 14px;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.nb-outputs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px dashed #e2e8f0;
  background: #fff;
}
.nb-output {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f1f5f9;
  color: #334155;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.nb-output-error {
  background: #fef2f2;
  color: #b91c1c;
}
.nb-output-image {
  max-width: 100%;
  border-radius: 8px;
}
.nb-output-html {
  overflow-x: auto;
  font-size: 12.5px;
}
.nb-output-html :deep(table) {
  border-collapse: collapse;
}
.nb-output-html :deep(th),
.nb-output-html :deep(td) {
  border: 1px solid #e2e8f0;
  padding: 4px 8px;
}
</style>
