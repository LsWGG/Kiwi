<script setup lang="ts">
/** 公开分享页的画布只读视图：把 jvs-draw 文档导出为静态 SVG。 */
import { computed } from 'vue'
import { drawDocToSvg } from '@/components/draw/drawSvgExport'
import { drawDocHasContent, normalizeDrawDoc } from '@/components/draw/types'

const props = defineProps<{ doc?: unknown }>()

const svg = computed(() => {
  const doc = normalizeDrawDoc(props.doc)
  if (!doc || !drawDocHasContent(doc)) return ''
  try {
    return drawDocToSvg(doc)
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
    <!-- drawDocToSvg 已对文本 / 属性做转义，仅输出 SVG 结构。 -->
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
