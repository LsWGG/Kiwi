<script setup lang="ts">
/** Notebook 单元格输出：stdout / stderr / 异常 / 富文本 / 图片。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import DOMPurify from 'dompurify'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import type { NotebookOutput } from './types'

const props = defineProps<{ output: NotebookOutput }>()

const expanded = ref(false)
const previewOpen = ref(false)

function onPreviewKey(event: KeyboardEvent) {
  if (event.key === 'Escape') previewOpen.value = false
}
onMounted(() => window.addEventListener('keydown', onPreviewKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onPreviewKey))

const isError = computed(() => props.output.type === 'error')
const isStream = computed(() => props.output.type === 'stream')
const isStderr = computed(() => isStream.value && props.output.name === 'stderr')
const imageSrc = computed(() => {
  const image = props.output.image
  if (!image?.data) return ''
  return `data:${image.mime || 'image/png'};base64,${image.data}`
})

const rawHtml = computed(() => props.output.html || '')

/**
 * folium / GeoPandas `.explore()` 等交互输出会返回 `<iframe srcdoc="...">`。
 * 取出内层文档，交给下方带 sandbox 的 iframe 渲染，避免外层 iframe 的固定
 * 纵横比导致留白；普通脚本型输出（Plotly 等）则直接作为 iframe 文档。
 */
const interactiveSource = computed(() => {
  const html = rawHtml.value
  if (!html) return ''
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const frame = doc.querySelector('iframe[srcdoc], iframe[src]')
    const srcdoc = frame?.getAttribute('srcdoc')
    if (srcdoc) return srcdoc
  } catch {
    // DOMParser 不可用时退回原始 HTML
  }
  return html
})

/** 含脚本或 iframe 的输出必须隔离渲染，不能直接注入主文档。 */
const isInteractive = computed(() => /<(script|iframe)\b/i.test(rawHtml.value))

/**
 * 其余 HTML 可能来自导入的 `.ipynb`，默认按不可信内容处理：
 * 移除脚本、iframe、表单与外链资源，只保留文本 / 表格 / 内联样式。
 */
const safeHtml = computed(() => {
  if (!rawHtml.value || isInteractive.value) return ''
  return DOMPurify.sanitize(rawHtml.value, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: [
      'script',
      'style',
      'iframe',
      'frame',
      'object',
      'embed',
      'link',
      'meta',
      'base',
      'form',
      'input',
      'textarea',
      'select',
      'button',
      'img',
      'video',
      'audio',
      'source',
      'svg',
    ],
    FORBID_ATTR: ['srcdoc', 'srcset', 'formaction'],
  })
})
</script>

<template>
  <div
    class="nb-output"
    :class="{
      'is-error': isError,
      'is-stderr': isStderr,
      'is-rich': output.type === 'execute_result' || output.type === 'display_data',
    }"
  >
    <div v-if="imageSrc" class="nb-image-wrap">
      <img
        :src="imageSrc"
        alt="Notebook 输出图片"
        class="nb-image"
        @click="previewOpen = true"
      />
      <button type="button" class="nb-image-toggle" @click="previewOpen = true">
        <KiwiIcon name="expand" :size="11" />
        查看原图
      </button>

      <!-- 原图预览：盖住整个视口，避免受输出区域高度与滚动容器裁切 -->
      <Teleport to="html">
        <div
          v-if="previewOpen"
          class="nb-image-lightbox"
          data-preview="notebook-image"
          @click="previewOpen = false"
        >
          <img :src="imageSrc" alt="Notebook 输出原图" @click.stop />
          <button
            type="button"
            class="nb-lightbox-close"
            title="关闭原图（Esc）"
            @click.stop="previewOpen = false"
          >
            <KiwiIcon name="close" :size="16" />
          </button>
        </div>
      </Teleport>
    </div>
    <div v-else-if="isInteractive" class="nb-interactive">
      <div class="nb-interactive-head">
        <span class="nb-interactive-badge">
          <KiwiIcon name="globe" :size="10" />
          交互输出
        </span>
        <span class="nb-interactive-hint">可缩放、拖动与查看提示</span>
        <div class="flex-1" />
        <button type="button" class="nb-image-toggle" @click="expanded = !expanded">
          <KiwiIcon :name="expanded ? 'shrink' : 'expand'" :size="11" />
          {{ expanded ? '收起地图' : '放大地图' }}
        </button>
      </div>
      <iframe
        :srcdoc="interactiveSource"
        class="nb-interactive-frame"
        :style="{ height: expanded ? '76vh' : '440px' }"
        sandbox="allow-scripts allow-pointer-lock"
        referrerpolicy="no-referrer"
        loading="lazy"
        title="Notebook 交互输出"
      />
    </div>
    <div v-else-if="safeHtml" class="nb-html" v-html="safeHtml" />
    <pre v-else class="nb-pre">{{ output.text || '' }}</pre>
  </div>
</template>

<style scoped>
.nb-output {
  @apply rounded-lg border border-slate-200/70 bg-white/70 px-3 py-2 text-[12px] text-slate-700;
}
.nb-output.is-error {
  @apply border-rose-200 bg-rose-50/70 text-rose-700;
}
.nb-output.is-stderr {
  @apply border-amber-200 bg-amber-50/60 text-amber-700;
}
.nb-output.is-rich {
  @apply bg-white/85;
}
.nb-pre {
  @apply whitespace-pre-wrap break-words font-mono text-[11.5px] leading-relaxed;
  max-height: 420px;
  overflow: auto;
}
.nb-image-wrap {
  @apply relative flex flex-col items-start gap-1.5;
}
.nb-image {
  @apply max-h-[420px] w-auto max-w-full cursor-zoom-in rounded-md border border-slate-200/60 bg-white;
}
.nb-image-toggle {
  @apply flex items-center gap-1 rounded px-1 py-0.5 text-[10px] text-slate-400 transition-colors hover:text-kiwi-600;
}
.nb-image-lightbox {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px;
  background: rgb(15 23 42 / 0.82);
  cursor: zoom-out;
}
.nb-image-lightbox img {
  width: auto;
  height: auto;
  max-width: 94vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: 6px;
  background: #fff;
  box-shadow: 0 24px 70px rgb(0 0 0 / 0.5);
  cursor: default;
}
.nb-lightbox-close {
  position: fixed;
  top: 16px;
  right: 20px;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 999px;
  color: #e2e8f0;
  background: rgb(255 255 255 / 0.14);
  transition: background 0.15s ease, color 0.15s ease;
}
.nb-lightbox-close:hover {
  color: #fff;
  background: rgb(255 255 255 / 0.26);
}
.nb-interactive {
  @apply flex flex-col gap-1.5;
}
.nb-interactive-head {
  @apply flex items-center gap-2;
}
.nb-interactive-badge {
  @apply inline-flex items-center gap-1 rounded-full border border-indigo-100 bg-indigo-50/80 px-1.5 py-0.5 text-[9.5px] font-medium text-indigo-500;
}
.nb-interactive-hint {
  @apply text-[9.5px] text-slate-300;
}
.nb-interactive-frame {
  @apply w-full rounded-md border border-slate-200/70 bg-white;
}
.nb-html {
  @apply max-h-[420px] overflow-auto text-[12px];
}
.nb-html :deep(table) {
  @apply border-collapse text-[11.5px];
}
.nb-html :deep(th),
.nb-html :deep(td) {
  @apply border border-slate-200/80 px-2 py-1 text-left align-top;
}
.nb-html :deep(th) {
  @apply bg-slate-50 font-medium text-slate-600;
}
.nb-html :deep(tr:nth-child(even) td) {
  @apply bg-slate-50/40;
}
.nb-html :deep(a) {
  @apply text-kiwi-600 underline;
}
.nb-html :deep(pre) {
  @apply overflow-auto rounded bg-slate-50 p-2 font-mono text-[11px];
}
</style>
