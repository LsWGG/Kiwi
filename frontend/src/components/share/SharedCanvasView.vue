<script setup lang="ts">
/** 公开分享页的画布只读视图：把画布文档导出为静态 SVG。 */
import { computed } from 'vue'
import { canvasDocToSvg } from '@/components/notes/canvas/canvasSvgExport'
import { normalizeDoc } from '@/components/notes/canvas/types'

const props = defineProps<{ doc?: unknown }>()

const svg = computed(() => {
  const doc = normalizeDoc(props.doc)
  if (!doc.nodes.length && !doc.edges.length) return ''
  try {
    return canvasDocToSvg(doc)
  } catch {
    return ''
  }
})
</script>

<template>
  <div
    v-if="svg"
    class="overflow-auto rounded-2xl border border-slate-200/70 bg-white p-2 shadow-soft"
  >
    <!-- canvasDocToSvg 已对节点 / 连线标签做 HTML 转义，仅输出 SVG 结构。 -->
    <div class="share-canvas min-w-[480px]" v-html="svg" />
  </div>
  <div v-else class="rounded-2xl border border-slate-200/70 bg-white/70 px-4 py-16 text-center">
    <p class="text-[12px] text-slate-400">这张画布还没有内容。</p>
  </div>
</template>

<style scoped>
.share-canvas :deep(svg) {
  display: block;
  width: 100%;
  height: auto;
}
</style>
