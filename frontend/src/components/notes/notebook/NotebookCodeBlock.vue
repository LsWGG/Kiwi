<script setup lang="ts">
/** 只读代码块：阅读 / 分屏预览中的 Python 语法高亮。 */
import { computed } from 'vue'
import hljs from 'highlight.js/lib/common'

const props = withDefaults(
  defineProps<{ code: string; language?: string }>(),
  { language: 'python' },
)

const html = computed(() => {
  const code = props.code || ''
  try {
    return hljs.highlight(code, {
      language: props.language,
      ignoreIllegals: true,
    }).value
  } catch {
    return code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  }
})
</script>

<template>
  <pre class="nb-code-hl"><code v-html="html" /></pre>
</template>

<style scoped>
.nb-code-hl {
  @apply overflow-auto rounded-lg border border-slate-200/70 bg-slate-50/70 px-3 py-2 font-mono text-[12px] leading-relaxed text-slate-800;
  max-height: 420px;
}
.nb-code-hl :deep(.hljs-keyword),
.nb-code-hl :deep(.hljs-selector-tag) {
  @apply text-violet-600;
}
.nb-code-hl :deep(.hljs-string),
.nb-code-hl :deep(.hljs-regexp) {
  @apply text-emerald-700;
}
.nb-code-hl :deep(.hljs-number),
.nb-code-hl :deep(.hljs-literal),
.nb-code-hl :deep(.hljs-built_in) {
  @apply text-amber-700;
}
.nb-code-hl :deep(.hljs-comment) {
  @apply italic text-slate-400;
}
.nb-code-hl :deep(.hljs-title),
.nb-code-hl :deep(.hljs-function) {
  @apply text-sky-700;
}
.nb-code-hl :deep(.hljs-params) {
  @apply text-slate-700;
}
.nb-code-hl :deep(.hljs-operator),
.nb-code-hl :deep(.hljs-punctuation) {
  @apply text-cyan-700;
}
.nb-code-hl :deep(.hljs-meta) {
  @apply text-fuchsia-700;
}
</style>
